"""Convert durable VNext candidates into an automatic no-padding PassList."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import AdviceMode, Book, Candidate, DataGateResult
from .opportunity import OpportunityEngine
from .storage import DecisionLoopStore


BASE = Path(__file__).resolve().parents[3]


class VNextPassListService:
    def __init__(self, store: DecisionLoopStore | None = None):
        self.store = store or DecisionLoopStore()
        self.engine = OpportunityEngine()

    def generate(self, now: datetime | None = None):
        now = now or datetime.now().astimezone()
        source = self._load(BASE / "data/vnext/candidates/latest.json")
        health = self._load(BASE / "data/vnext/data-health/latest.json")
        raw_candidates = (source.get("payload") or {}).get("raw_candidates") or []
        candidates = [self._convert(row, health, now) for row in raw_candidates if row.get("research_signal")]
        result = self.engine.build_pass_list(candidates, now)
        self.store.write_json("opportunities/current.json", result.model_dump(mode="json"))
        targets = []
        for candidate in result.primary + result.backup:
            targets.append({
                "symbol": candidate.symbol, "name": candidate.name,
                "book": candidate.book.value, "instrument_type": candidate.instrument_type,
                "reference_price": candidate.entry_reference_price,
                "kind": "recommendation", "decision_id": result.decision_id,
            })
            if candidate.benchmark_symbol:
                targets.append({
                    "symbol": candidate.benchmark_symbol, "name": "行业锚定",
                    "book": "swing", "instrument_type": "etf", "reference_price": None,
                    "kind": "anchor_etf", "decision_id": result.decision_id,
                })
        self.store.write_json("watchlist/current.json", {"decision_id": result.decision_id, "targets": targets})
        return result

    @staticmethod
    def _convert(raw: dict, health: dict, now: datetime) -> Candidate:
        health_ok = health.get("status") == "OK"
        execution_eligible = bool(raw.get("execution_eligible"))
        mode = AdviceMode.EXECUTABLE if health_ok and execution_eligible else AdviceMode.WATCH_ONLY
        reasons = []
        if not health_ok:
            reasons.append(f"VNext data health={health.get('status', 'MISSING')}")
        if not execution_eligible:
            reasons.append(raw.get("blocked_reason") or "mandatory execution checks missing")
        confidence = float(raw.get("regime_applicability") or 0.5)
        gate = DataGateResult(
            mode=mode,
            confidence_multiplier=max(0.35, min(1.0, confidence)),
            reasons=reasons,
            evaluated_at=now,
        )
        mainline = float(raw.get("mainline_fit") or 0)
        risk_level = str(raw.get("risk_level") or "UNASSESSED")
        risk_score = {"LOW": 85, "MEDIUM": 65, "HIGH": 30}.get(risk_level, 45)
        evidence = [{
            "source": raw.get("data_source"),
            "model_version": raw.get("model_version"),
            "feature_attribution": raw.get("feature_attribution") or {},
        }]
        instrument = "etf" if raw.get("is_etf_substitution") else "stock"
        weight = raw.get("recommended_weight")
        return Candidate(
            candidate_id=f"vnext:{raw['symbol']}:{source_date(raw)}",
            symbol=raw["symbol"], name=raw.get("name", raw["symbol"]),
            instrument_type=instrument, book=Book.CATALYST, holding_period="1-5 trading days",
            catalyst_score=min(100, 45 + mainline * 40),
            industry_fundamental_score=min(100, 40 + mainline * 50),
            technical_flow_score=max(0, min(100, 50 + float(raw.get("ml_rank_score") or 0) * 1000)),
            risk_score=risk_score,
            catalyst_evidence=evidence,
            industry_logic=f"mainline_fit={mainline:.4f}",
            fundamental_valuation="VNext evidence gate; no unsupported valuation conclusion",
            entry_plan="Only after mandatory liquidity/limit/suspension checks pass",
            entry_reference_price=float(raw["latest_price"]) if raw.get("latest_price") else None,
            no_chase_zone="No chase while execution_eligible is false",
            position_pct=max(0.01, min(0.30, float(weight or 0.05))),
            invalidation=raw.get("blocked_reason") or "catalyst or trend invalidated",
            exit_plan="2-point warning; 3-point half; 10-minute structure-break exit",
            crowding_risk=risk_level,
            benchmark_symbol=raw.get("alternative_etf") if raw.get("is_restricted") else None,
            data_gate=gate,
        )

    @staticmethod
    def _load(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def source_date(raw: dict) -> str:
    source = str(raw.get("data_source") or "")
    return Path(source.split(":", 1)[-1]).stem or datetime.now().date().isoformat()
