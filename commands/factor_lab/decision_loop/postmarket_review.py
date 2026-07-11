"""Generate durable post-market reviews from decision, event, and order ledgers."""

from __future__ import annotations

import hashlib
from datetime import datetime

from .benchmark import BenchmarkMatcher
from .models import Book, ReviewRecord
from .review import calculate_review
from .storage import DecisionLoopStore


class PostMarketReviewService:
    def __init__(self, store: DecisionLoopStore | None = None):
        self.store = store or DecisionLoopStore()

    def generate(self, trading_date: str) -> list[ReviewRecord]:
        opportunity = self.store.read_json("opportunities/current.json", default={})
        decision_id = opportunity.get("decision_id")
        positions = self.store.read_json("positions/current.json", default={}).get("positions", [])
        by_symbol = {row.get("symbol"): row for row in positions}
        cycle_rows = [row for row in self.store.read_jsonl("cycles/history.jsonl") if str(row.get("started_at", "")).startswith(trading_date)]
        price_paths: dict[str, list[float]] = {}
        for cycle in cycle_rows:
            for card in cycle.get("action_cards", []):
                evidence = card.get("evidence") or []
                if evidence and evidence[0].get("last_price"):
                    price_paths.setdefault(card.get("symbol"), []).append(float(evidence[0]["last_price"]))
        records = []
        benchmark_matcher = BenchmarkMatcher.from_durable_registry()
        for row in self.store.read_jsonl("execution/audit.jsonl"):
            timestamp = str(row.get("timestamp", ""))
            if not timestamp.startswith(trading_date):
                continue
            payload = row.get("payload") or {}
            symbol = payload.get("symbol")
            if not symbol:
                continue
            position = by_symbol.get(symbol, {})
            entry = float(position.get("cost_price") or payload.get("limit_price") or 0)
            exit_price = float(payload.get("limit_price") or entry)
            quantity = int(payload.get("quantity") or 0)
            path = price_paths.get(symbol) or ([entry, exit_price] if entry > 0 else [])
            instrument_type = str(position.get("instrument_type") or "stock")
            benchmark = benchmark_matcher.match_instrument(symbol, instrument_type)
            metrics = None
            if entry > 0 and exit_price > 0 and quantity > 0:
                metrics = calculate_review(
                    entry_price=entry,
                    path_prices=path,
                    exit_price=exit_price,
                    benchmark_prices=None,
                    recommended_exit_price=exit_price,
                    quantity=quantity,
                    fees=float((row.get("broker_response") or {}).get("fees") or 0),
                    expected_entry_price=exit_price,
                    attribution={
                        "opportunity": decision_id or "missing",
                        "validation": "data_gate:" + str(row.get("status")),
                        "entry": "execution_audit",
                        "sizing": "authorized_or_hard_risk",
                        "exit": payload.get("event_id") or "plan",
                        "risk_alert": payload.get("event_id") or "none",
                    },
                    ordered_quantity=quantity,
                    filled_quantity=int((row.get("broker_response") or {}).get("filled_quantity") or 0),
                )
            fingerprint = f"{trading_date}|{decision_id}|{payload.get('event_id')}|{payload.get('order_id')}"
            record = ReviewRecord(
                review_id="review_" + hashlib.sha256(fingerprint.encode()).hexdigest()[:18],
                trading_date=trading_date,
                decision_id=decision_id,
                event_id=payload.get("event_id"),
                order_id=payload.get("order_id"),
                parameter_version=self._parameter_version(trading_date),
                symbol=symbol,
                book=Book(payload.get("book", "swing")),
                execution_status=row.get("status", "unknown"),
                metrics=metrics,
                benchmark_symbol=benchmark.primary,
                benchmark_missing_reason=None if benchmark.primary else benchmark.reason,
                created_at=datetime.now().astimezone(),
            )
            self.store.append_unique_jsonl("reviews/records.jsonl", record.model_dump(mode="json"), record.review_id)
            records.append(record)
        summary = self._summary(trading_date, records)
        self.store.write_json(f"reviews/{trading_date}.json", summary)
        self.store.write_json("reviews/latest.json", summary)
        return records

    def propose_weekly_candidates(self, week_id: str) -> list[dict]:
        reviews = self.store.read_jsonl("reviews/records.jsonl")
        candidates = []
        false_alerts = [row for row in reviews if (row.get("metrics") or {}).get("attribution", {}).get("risk_alert") == "false_positive"]
        if len(false_alerts) >= 5:
            lineage = false_alerts[-1]
            evidence = {"week_id": week_id, "false_alert_count": len(false_alerts), "reviews": [row.get("review_id") for row in false_alerts]}
            candidate = {
                "parameter": "profit_giveback_warning_points",
                "current_value": 2.0,
                "proposed_value": 2.25,
                "evidence": evidence,
                "status": "candidate",
                "oos_status": "pending",
                "human_status": "pending",
                "decision_id": lineage.get("decision_id"),
                "event_id": lineage.get("event_id"),
                "order_id": lineage.get("order_id"),
            }
            self.store.append_unique_jsonl("parameters/weekly_candidates.jsonl", candidate, f"{week_id}:profit_giveback_warning_points")
            candidates.append(candidate)
        return candidates

    def _parameter_version(self, trading_date: str) -> str | None:
        auth = self.store.read_json(f"authorization/{trading_date}.json", default={})
        return (auth.get("plan") or {}).get("parameter_version")

    @staticmethod
    def _summary(trading_date: str, records: list[ReviewRecord]) -> dict:
        by_book = {}
        for book in Book:
            rows = [record for record in records if record.book == book and record.metrics]
            returns = [record.metrics.returns.get("1d") for record in rows if record.metrics and record.metrics.returns.get("1d") is not None]
            by_book[book.value] = {
                "records": len(rows),
                "average_1d_return": sum(returns) / len(returns) if returns else None,
            }
        return {
            "trading_date": trading_date,
            "generated_at": datetime.now().astimezone().isoformat(),
            "record_count": len(records),
            "by_book": by_book,
            "note": "1/5/20d, benchmark excess, MFE/MAE and costs remain null until sufficient durable observations exist",
        }
