"""Data-quality gate that separates research degradation from execution safety."""

from __future__ import annotations

from datetime import datetime

from .models import AdviceMode, DataGateResult, DataItemStatus


CORE_DATA = frozenset({"quotes", "positions", "trade_calendar"})
AUXILIARY_DATA = frozenset({"news", "capital_flow", "fundamentals"})


def evaluate_data_gate(
    items: list[DataItemStatus],
    conflicts: list[dict] | None = None,
    now: datetime | None = None,
) -> DataGateResult:
    by_name = {item.name: item for item in items}
    reasons: list[str] = []
    missing_core = []
    weak_auxiliary = []
    for name in CORE_DATA:
        item = by_name.get(name)
        if item is None or not item.available or not item.fresh:
            missing_core.append(name)
    for name in AUXILIARY_DATA:
        item = by_name.get(name)
        if item is None or not item.available or not item.fresh:
            weak_auxiliary.append(name)

    if missing_core:
        mode = AdviceMode.BLOCKED
        confidence = 0.0
        reasons.append("核心数据不可用或过期: " + ", ".join(sorted(missing_core)))
    elif weak_auxiliary:
        mode = AdviceMode.WATCH_ONLY
        confidence = max(0.35, 1.0 - 0.2 * len(weak_auxiliary))
        reasons.append("辅助数据不完整，仅观察: " + ", ".join(sorted(weak_auxiliary)))
    else:
        mode = AdviceMode.EXECUTABLE
        confidence = 1.0

    conflict_rows = conflicts or []
    if conflict_rows:
        reasons.append("存在来源冲突，已保留所有版本")
        if mode == AdviceMode.EXECUTABLE:
            mode = AdviceMode.WATCH_ONLY
            confidence = min(confidence, 0.6)
    return DataGateResult(
        mode=mode,
        confidence_multiplier=confidence,
        reasons=reasons,
        conflicts=conflict_rows,
        evaluated_at=now or datetime.now().astimezone(),
    )
