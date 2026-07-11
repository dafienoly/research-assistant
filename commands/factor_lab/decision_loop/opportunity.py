"""Hybrid opportunity funnel yielding zero-to-three primary and five backups."""

from __future__ import annotations

import hashlib
from datetime import datetime

from .models import AdviceMode, Candidate, PassList


class OpportunityEngine:
    def __init__(self, primary_threshold: float = 72.0, backup_threshold: float = 60.0):
        self.primary_threshold = primary_threshold
        self.backup_threshold = backup_threshold

    @staticmethod
    def score(candidate: Candidate) -> float:
        gross = (
            candidate.catalyst_score * 0.30
            + candidate.industry_fundamental_score * 0.30
            + candidate.technical_flow_score * 0.25
            + candidate.risk_score * 0.15
        )
        return round(gross * candidate.data_gate.confidence_multiplier, 4)

    def build_pass_list(
        self, candidates: list[Candidate], now: datetime | None = None
    ) -> PassList:
        now = now or datetime.now().astimezone()
        evaluated = [
            candidate.model_copy(update={"total_score": self.score(candidate)})
            for candidate in candidates
        ]
        evaluated.sort(
            key=lambda item: (item.total_score or 0, item.catalyst_score), reverse=True
        )
        primary = [
            item
            for item in evaluated
            if item.data_gate.mode == AdviceMode.EXECUTABLE
            and (item.total_score or 0) >= self.primary_threshold
        ][:3]
        primary_ids = {item.candidate_id for item in primary}
        backup = [
            item
            for item in evaluated
            if item.candidate_id not in primary_ids
            and item.data_gate.mode != AdviceMode.BLOCKED
            and (item.total_score or 0) >= self.backup_threshold
        ][:5]
        no_reason = None
        if not primary:
            blocked = sum(
                item.data_gate.mode == AdviceMode.BLOCKED for item in evaluated
            )
            no_reason = (
                f"今日无满足质量与执行门槛的机会；核心数据阻断 {blocked} 项，保持现金"
            )
        signature = (
            "|".join(item.candidate_id for item in primary + backup)
            or now.date().isoformat()
        )
        return PassList(
            decision_id="decision_"
            + hashlib.sha256(signature.encode()).hexdigest()[:16],
            generated_at=now,
            primary=primary,
            backup=backup,
            no_opportunity_reason=no_reason,
        )
