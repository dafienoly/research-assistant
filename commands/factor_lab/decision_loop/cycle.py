"""Single non-overlapping minute decision cycle with a unified result contract."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from factor_lab.broker.qmt_client import QMTClient

from .calendar import TradingCalendarGate
from .data_gate import evaluate_data_gate
from .data_health import load_auxiliary_gate
from .models import (
    AdviceMode,
    DataItemStatus,
    DecisionCycleResult,
    ExecutionRequest,
    PlannedOrder,
    PortfolioRiskInput,
    Position,
    QuoteSnapshot,
)
from .portfolio import evaluate_portfolio_risk


BASE = Path(__file__).resolve().parents[3]


def _quotes_by_symbol(raw: object) -> dict[str, dict]:
    if isinstance(raw, dict):
        if all(isinstance(value, dict) for value in raw.values()):
            rows = raw.items()
            return {str(symbol).split(".")[0]: value for symbol, value in rows}
        raw = raw.get("quotes") or raw.get("items") or []
    rows = raw if isinstance(raw, list) else []
    return {str(row.get("symbol") or row.get("code")).split(".")[0]: row for row in rows if isinstance(row, dict)}


class MinuteDecisionCycle:
    def __init__(self, service, client: QMTClient | None = None):
        self.service = service
        self.store = service.store
        self.client = client or QMTClient()

    def run(self, now: datetime | None = None) -> DecisionCycleResult:
        now = now or datetime.now().astimezone()
        started = now
        cycle_id = f"cycle_{now:%Y%m%d_%H%M}_{uuid.uuid4().hex[:8]}"
        try:
            with self.store.exclusive("cycle/minute", timeout=0.05):
                result = self._run_locked(cycle_id, started)
        except TimeoutError:
            result = DecisionCycleResult(
                cycle_id=cycle_id,
                started_at=started,
                completed_at=datetime.now().astimezone(),
                status="skipped",
                data_gate={"mode": "blocked", "reasons": ["minute_cycle_overlap"]},
                blockers=["minute_cycle_overlap"],
            )
        self.store.write_json("cycles/latest.json", result.model_dump(mode="json"))
        self.store.append_unique_jsonl("cycles/history.jsonl", result.model_dump(mode="json"), cycle_id)
        return result

    def _run_locked(self, cycle_id: str, started: datetime) -> DecisionCycleResult:
        blockers = []
        snapshot = self.service.positions.current()
        if not snapshot or not snapshot.confirmed:
            return self._blocked(cycle_id, started, "no_confirmed_positions")
        calendar = TradingCalendarGate(self.store).resolve(started.date(), started)
        if not calendar.get("available"):
            return self._blocked(cycle_id, started, "trade_calendar_unavailable")
        if not calendar.get("is_open"):
            return DecisionCycleResult(
                cycle_id=cycle_id,
                started_at=started,
                completed_at=datetime.now().astimezone(),
                status="skipped",
                data_gate={"mode": "blocked", "calendar": calendar},
                blockers=["non_trading_day"],
            )
        account_response = self.client.get_account()
        if account_response.get("status") != "ok" or not isinstance(account_response.get("data"), dict):
            self.service.qmt_sync._record_failure(account_response.get("error") or "account_read_failed")
            return self._blocked(cycle_id, started, "account_equity_unavailable")
        try:
            reconciliation = self.service.qmt_sync.preview().model_dump(mode="json")
        except RuntimeError as exc:
            return self._blocked(cycle_id, started, f"position_reconciliation_failed:{exc}")
        account = account_response["data"]
        equity = float(account.get("m_dTotalAsset", account.get("total_asset", 0)) or 0)
        if equity <= 0:
            return self._blocked(cycle_id, started, "non_positive_account_equity")
        risk = self._portfolio_risk(equity, started)
        self.store.write_json("risk/current.json", risk.model_dump(mode="json"))

        watchlist = self.store.read_json("watchlist/current.json", default={"targets": []})
        monitored = list(snapshot.positions)
        known = {p.symbol.split(".")[0] for p in monitored}
        for target in watchlist.get("targets", []):
            symbol = str(target.get("symbol", ""))
            if not symbol or symbol.split(".")[0] in known:
                continue
            monitored.append(Position(
                symbol=symbol,
                name=target.get("name", ""),
                quantity=0,
                available_quantity=0,
                cost_price=float(target.get("reference_price") or 0),
                instrument_type=target.get("instrument_type", "stock"),
                book=target.get("book", "swing"),
                theme="watch_target",
            ))
        quotes_response = self.client.get_quotes(sorted({p.symbol for p in monitored}))
        if quotes_response.get("status") != "ok":
            return self._blocked(cycle_id, started, "quote_fetch_failed")
        quotes = _quotes_by_symbol(quotes_response.get("data"))
        auxiliary, conflicts, manifest = load_auxiliary_gate(started)
        all_cards, receipts, executions = [], [], []
        last_gate = None
        auth = self.service.authorizations.current(started.date().isoformat(), started)
        for position in monitored:
            row = quotes.get(position.symbol.split(".")[0])
            if not row:
                blockers.append(f"quote_missing:{position.symbol}")
                continue
            price = float(row.get("last_price") or row.get("last") or row.get("price") or 0)
            if price <= 0:
                blockers.append(f"quote_invalid:{position.symbol}")
                continue
            effective = position if position.cost_price > 0 else position.model_copy(update={"cost_price": price})
            quote = QuoteSnapshot(
                symbol=position.symbol,
                last_price=price,
                vwap=float(row["vwap"]) if row.get("vwap") else None,
                volume=float(row.get("volume") or 0),
                average_volume=float(row["average_volume"]) if row.get("average_volume") else None,
                observed_at=started,
                source="qmt_bridge",
                freshness_seconds=int(row.get("freshness_seconds") or 0),
            )
            core = [
                DataItemStatus(name="quotes", available=True, fresh=quote.freshness_seconds <= 90, source="qmt_bridge", as_of=started),
                DataItemStatus(name="positions", available=True, fresh=True, source=snapshot.source, as_of=snapshot.as_of),
                DataItemStatus(name="trade_calendar", available=True, fresh=True, source=calendar["source"], as_of=datetime.fromisoformat(calendar["checked_at"])),
            ]
            gate = evaluate_data_gate(core + auxiliary, conflicts, started)
            last_gate = gate
            cards = self.service.guard.evaluate(effective, quote, gate.mode)
            for card in cards:
                all_cards.append(card)
                receipts.append(self.service.notifications.enqueue(card))
                if card.action in {"reduce_half", "exit_remaining"} and card.quantity:
                    executions.append(self._execute_card(card, quote, effective, gate.mode, risk, auth, started))
        gate_payload = last_gate.model_dump(mode="json") if last_gate else {"mode": "blocked", "reasons": ["no_valid_quotes"], "manifest": manifest}
        gate_payload["manifest"] = manifest
        self.store.write_json("data_gate/current.json", gate_payload)
        return DecisionCycleResult(
            cycle_id=cycle_id,
            decision_id=watchlist.get("decision_id"),
            started_at=started,
            completed_at=datetime.now().astimezone(),
            status="degraded" if blockers or (last_gate and last_gate.mode != AdviceMode.EXECUTABLE) else "ok",
            data_gate=gate_payload,
            portfolio_risk=risk,
            action_cards=all_cards,
            notification_receipts=receipts,
            execution_results=executions,
            reconciliation=reconciliation,
            blockers=blockers,
        )

    def _portfolio_risk(self, equity: float, now: datetime):
        state = self.store.read_json("risk/equity_state.json", default={})
        day = now.date().isoformat()
        if state.get("date") != day:
            previous_close = float(state.get("last_equity") or equity)
            intraday_peak = equity
        else:
            previous_close = float(state.get("previous_close") or equity)
            intraday_peak = max(float(state.get("intraday_peak") or equity), equity)
        rolling_peak = max(float(state.get("rolling_20d_peak") or equity), equity)
        self.store.write_json("risk/equity_state.json", {
            "date": day, "last_equity": equity, "previous_close": previous_close,
            "intraday_peak": intraday_peak, "rolling_20d_peak": rolling_peak,
            "updated_at": now.isoformat(),
        })
        return evaluate_portfolio_risk(PortfolioRiskInput(
            equity=equity, intraday_peak_equity=intraday_peak,
            previous_close_equity=previous_close, rolling_20d_peak_equity=rolling_peak,
        ), now)

    def _execute_card(self, card, quote, position, mode, risk, auth, now):
        if not auth:
            return {"status": "blocked", "reason": "daily_authorization_inactive", "event_id": card.event_id}
        order = PlannedOrder(
            order_id=f"risk_{card.event_id}", symbol=position.symbol, side="SELL",
            quantity=card.quantity, limit_price=quote.last_price, book=position.book,
            strategy="intraday_profit_guard", reason=card.reason,
        )
        audit_passed = self._audit_passed()
        request = ExecutionRequest(
            order=order, event_id=card.event_id, hard_risk_sell=True,
            available_quantity=position.available_quantity, data_mode=mode,
            audit_passed=audit_passed, parameter_version=auth.plan.parameter_version,
            plan_hash=auth.plan.plan_hash, risk_mode=risk.mode,
        )
        return self.service.execution.submit(request, now.date().isoformat(), now)

    @staticmethod
    def _audit_passed() -> bool:
        path = BASE / "artifacts/vnext/hardening_report.json"
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("status") == "OK"
        except (OSError, json.JSONDecodeError):
            return False

    @staticmethod
    def _blocked(cycle_id: str, started: datetime, reason: str) -> DecisionCycleResult:
        return DecisionCycleResult(
            cycle_id=cycle_id,
            started_at=started,
            completed_at=datetime.now().astimezone(),
            status="blocked",
            data_gate={"mode": "blocked", "reasons": [reason]},
            blockers=[reason],
        )
