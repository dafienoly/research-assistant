"""DataQualityGate — 数据质量门禁 (V5.4)

Validates data quality across multiple dimensions before allowing it into
downstream pipelines. Built on the Data Source Registry (V5.0) and the
Realtime Quote Ingest (V5.2) infrastructure.

Quality dimensions:
  - COMPLETENESS   : Required fields non-null
  - REASONABLENESS : Values within expected market ranges
  - CONSISTENCY    : Cross-field consistency (high >= low, etc.)
  - TIMELINESS     : Data freshness relative to current time

Usage:
    gate = DataQualityGate()

    # Check individual quotes
    quote = Quote(symbol="688012", price=158.3, ...)
    results = gate.check_quote(quote)

    # Check a batch result
    report = gate.check_batch_result(batch_result)
    if report.overall_verdict == "fail":
        print(f"Data blocked: {report.blocker_count} blocker failures")

    # Store quality report to registry
    gate.store_report(report)
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from factor_lab.data_source.quote import Quote, QuoteResult, BatchQuoteResult
from factor_lab.data_source.registry import DataRegistry


CST = timezone(timedelta(hours=8))
REGISTRY_ROOT = Path("/mnt/d/HermesData/data_source_registry")

# ---------------------------------------------------------------------------
# Quality dimension & severity
# ---------------------------------------------------------------------------


class QualityDimension(str, Enum):
    """数据质量维度"""
    COMPLETENESS = "completeness"      # 完整性 — 必需字段非空
    REASONABLENESS = "reasonableness"  # 合理性 — 值在合理范围内
    CONSISTENCY = "consistency"        # 一致性 — 跨字段逻辑一致
    TIMELINESS = "timeliness"          # 时效性 — 数据新鲜度


class QualitySeverity(str, Enum):
    """规则严重级别"""
    BLOCKER = "blocker"    # 阻塞级 — 不合格则数据不可用
    WARNING = "warning"    # 警告级 — 建议修复但不阻塞
    INFO = "info"          # 信息级 — 仅记录观察结果


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class QualityRuleResult:
    """单条规则检查结果

    Attributes:
        rule_name:  规则名称 (e.g. 'price_positive')
        dimension:  质量维度
        severity:   严重级别
        passed:     是否通过
        symbol:     股票代码
        expected:   期望值或范围
        actual:     实际值
        message:    可读描述
    """
    rule_name: str
    dimension: str
    severity: str = QualitySeverity.WARNING.value
    passed: bool = True
    symbol: str = ""
    expected: Any = None
    actual: Any = None
    message: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if isinstance(self.expected, (int, float)):
            d["expected"] = self.expected
        if isinstance(self.actual, (int, float)):
            d["actual"] = self.actual
        return d


@dataclass
class QualityReport:
    """数据质量报告

    Aggregates QualityRuleResult checks for one batch of data
    from one source and produces a summary verdict.

    Attributes:
        source_id:      数据源ID
        timestamp:      报告生成时间
        total_checks:   总检查数
        passed_checks:  通过数
        failed_checks:  失败数
        blocker_count:  阻塞级失败数
        warning_count:  警告级失败数
        overall_verdict: 总体判决 (pass / conditional_pass / fail)
        item_reports:   dict[symbol -> list[QualityRuleResult]]
    """
    source_id: str
    timestamp: str = ""
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    blocker_count: int = 0
    warning_count: int = 0
    overall_verdict: str = "pass"
    item_reports: dict[str, list[QualityRuleResult]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(CST).isoformat()

    @property
    def symbol_count(self) -> int:
        return len(self.item_reports)

    def summary(self) -> dict:
        """返回简化的摘要"""
        return {
            "source_id": self.source_id,
            "timestamp": self.timestamp,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "overall_verdict": self.overall_verdict,
            "symbol_count": len(self.item_reports),
        }

    def to_dict(self) -> dict:
        d = asdict(self)
        d["item_reports"] = {
            sym: [r.to_dict() for r in results]
            for sym, results in self.item_reports.items()
        }
        return d


# ---------------------------------------------------------------------------
# A-share market constants
# ---------------------------------------------------------------------------

# Normal A-share daily price change limits (±10% for normal stocks,
# ±20% for ST stocks / ChiNext / STAR). We use ±20% as the conservative
# ceiling to avoid false positives on special-board stocks.
A_SHARE_CHANGE_PCT_LOWER = -20.0
A_SHARE_CHANGE_PCT_UPPER = 20.0

# Maximum age for realtime quote data (seconds)
REALTIME_QUOTE_MAX_AGE_SECONDS = 300  # 5 minutes

# ---------------------------------------------------------------------------
# DataQualityGate
# ---------------------------------------------------------------------------


class DataQualityGate:
    """数据质量门禁 — 对行情/数据执行质量检查

    Attributes:
        registry: DataRegistry 实例
        max_age_seconds: 实时数据最大可接受延迟
    """

    def __init__(
        self,
        registry: Optional[DataRegistry] = None,
        max_age_seconds: int = REALTIME_QUOTE_MAX_AGE_SECONDS,
    ):
        self.registry = registry or DataRegistry()
        self.max_age_seconds = max_age_seconds

    # ------------------------------------------------------------------
    # Public API — check
    # ------------------------------------------------------------------

    def check_quote(self, quote: Quote) -> list[QualityRuleResult]:
        """对单个 Quote 执行所有质量规则检查

        Args:
            quote: Quote 对象

        Returns:
            list[QualityRuleResult]
        """
        checks: list[QualityRuleResult] = [
            # Completeness
            self._check_required_fields(quote),
            self._check_price_positive(quote),
            self._check_volume_non_negative(quote),
            # Reasonableness
            self._check_change_pct_reasonable(quote),
            # Consistency
            self._check_high_low_consistent(quote),
            self._check_open_within_range(quote),
            self._check_price_within_range(quote),
            self._check_amount_consistency(quote),
            # Timeliness
            self._check_timeliness(quote),
        ]
        for c in checks:
            c.symbol = quote.symbol
        return checks

    def check_quotes(self, quotes: list[Quote]) -> QualityReport:
        """对多个 Quote 执行质量检查，生成聚合报告

        Args:
            quotes: Quote 对象列表

        Returns:
            QualityReport
        """
        source_ids = {q.source_id for q in quotes if q.source_id}
        source_id = next(iter(source_ids)) if len(source_ids) == 1 else (",".join(sorted(source_ids)) if source_ids else "unknown")

        item_reports: dict[str, list[QualityRuleResult]] = {}
        total_checks = 0
        passed_checks = 0
        failed_checks = 0
        blocker_count = 0
        warning_count = 0

        for quote in quotes:
            results = self.check_quote(quote)
            item_reports[quote.symbol] = results
            for r in results:
                total_checks += 1
                if r.passed:
                    passed_checks += 1
                else:
                    failed_checks += 1
                    if r.severity == QualitySeverity.BLOCKER.value:
                        blocker_count += 1
                    elif r.severity == QualitySeverity.WARNING.value:
                        warning_count += 1

        # Determine verdict
        if blocker_count > 0:
            overall_verdict = "fail"
        elif warning_count > 0:
            overall_verdict = "conditional_pass"
        else:
            overall_verdict = "pass"

        return QualityReport(
            source_id=source_id,
            total_checks=total_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            blocker_count=blocker_count,
            warning_count=warning_count,
            overall_verdict=overall_verdict,
            item_reports=item_reports,
        )

    def check_batch_result(self, batch: BatchQuoteResult) -> QualityReport:
        """对 BatchQuoteResult 执行质量检查

        Extracts successful Quote objects from the batch result and
        runs quality checks on each.

        Args:
            batch: BatchQuoteResult 对象

        Returns:
            QualityReport
        """
        quotes: list[Quote] = []
        for sym, result in batch.results.items():
            if result.success and result.quote is not None:
                quotes.append(result.quote)

        source_id = batch.results.get(batch.symbols[0], QuoteResult(symbol="", success=False)).source_id if batch.symbols else "unknown"
        if not source_id or source_id == "unknown":
            for r in batch.results.values():
                if r.source_id:
                    source_id = r.source_id
                    break

        item_reports: dict[str, list[QualityRuleResult]] = {}
        total_checks = 0
        passed_checks = 0
        failed_checks = 0
        blocker_count = 0
        warning_count = 0

        for quote in quotes:
            results = self.check_quote(quote)
            item_reports[quote.symbol] = results
            for r in results:
                total_checks += 1
                if r.passed:
                    passed_checks += 1
                else:
                    failed_checks += 1
                    if r.severity == QualitySeverity.BLOCKER.value:
                        blocker_count += 1
                    elif r.severity == QualitySeverity.WARNING.value:
                        warning_count += 1

        # Add entries for failed symbols (no quote to check)
        for sym, result in batch.results.items():
            if not result.success and sym not in item_reports:
                item_reports[sym] = [
                    QualityRuleResult(
                        rule_name="fetch_success",
                        dimension=QualityDimension.COMPLETENESS.value,
                        severity=QualitySeverity.BLOCKER.value,
                        passed=False,
                        symbol=sym,
                        message=f"Failed to fetch: {result.error or 'unknown'}",
                    )
                ]
                total_checks += 1
                failed_checks += 1
                blocker_count += 1

        if blocker_count > 0:
            overall_verdict = "fail"
        elif warning_count > 0:
            overall_verdict = "conditional_pass"
        else:
            overall_verdict = "pass"

        return QualityReport(
            source_id=source_id,
            total_checks=total_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            blocker_count=blocker_count,
            warning_count=warning_count,
            overall_verdict=overall_verdict,
            item_reports=item_reports,
        )

    # ------------------------------------------------------------------
    # Public API — store & retrieve
    # ------------------------------------------------------------------

    def store_report(self, report: QualityReport):
        """将质量报告持久化到数据源注册表目录

        Saves the report under:
          <REGISTRY_ROOT>/<source_id>/quality_reports/<timestamp>.json

        Also updates the source's health metadata with quality score.

        Args:
            report: QualityReport
        """
        source_dir = REGISTRY_ROOT / report.source_id
        quality_dir = source_dir / "quality_reports"
        quality_dir.mkdir(parents=True, exist_ok=True)

        report_path = quality_dir / f"{report.timestamp.replace(':', '-')}.json"
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        # Update source's spec with quality metadata
        self._update_source_quality(report.source_id, report)

    def get_latest_report(self, source_id: str) -> Optional[QualityReport]:
        """获取指定数据源的最新质量报告

        Args:
            source_id: 数据源ID

        Returns:
            QualityReport 或 None
        """
        quality_dir = REGISTRY_ROOT / source_id / "quality_reports"
        if not quality_dir.exists():
            return None

        json_files = sorted(quality_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not json_files:
            return None

        try:
            data = json.loads(json_files[0].read_text(encoding="utf-8"))
            # Deserialize item_reports from dict
            item_reports = {}
            for sym, results_list in data.get("item_reports", {}).items():
                item_reports[sym] = [QualityRuleResult(**r) for r in results_list]
            data["item_reports"] = item_reports
            return QualityReport(**data)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return None

    def get_source_quality_summary(self, source_id: str) -> Optional[dict]:
        """获取数据源的质量摘要

        Args:
            source_id: 数据源ID

        Returns:
            质量摘要 dict 或 None
        """
        report = self.get_latest_report(source_id)
        if report is None:
            return None
        return report.summary()

    # ------------------------------------------------------------------
    # Individual rule checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_required_fields(quote: Quote) -> QualityRuleResult:
        """检查必需字段是否存在

        Blocking — 缺少 symbol 或 price 的数据不可用。
        """
        missing = []
        if not quote.symbol:
            missing.append("symbol")
        if quote.price is None:
            missing.append("price")

        if missing:
            return QualityRuleResult(
                rule_name="required_fields",
                dimension=QualityDimension.COMPLETENESS.value,
                severity=QualitySeverity.BLOCKER.value,
                passed=False,
                expected="symbol, price non-null",
                actual=f"missing: {', '.join(missing)}",
                message=f"Required fields missing: {', '.join(missing)}",
            )
        return QualityRuleResult(
            rule_name="required_fields",
            dimension=QualityDimension.COMPLETENESS.value,
            severity=QualitySeverity.BLOCKER.value,
            passed=True,
            message="All required fields present",
        )

    @staticmethod
    def _check_price_positive(quote: Quote) -> QualityRuleResult:
        """价格必须为正数

        Blocker — 非正价格不可用。
        """
        if quote.price is not None and quote.price > 0:
            return QualityRuleResult(
                rule_name="price_positive",
                dimension=QualityDimension.REASONABLENESS.value,
                severity=QualitySeverity.BLOCKER.value,
                passed=True,
                expected="> 0",
                actual=quote.price,
                message=f"Price {quote.price} is positive",
            )
        return QualityRuleResult(
            rule_name="price_positive",
            dimension=QualityDimension.REASONABLENESS.value,
            severity=QualitySeverity.BLOCKER.value,
            passed=False,
            expected="> 0",
            actual=quote.price,
            message=f"Price {quote.price} is not positive",
        )

    @staticmethod
    def _check_volume_non_negative(quote: Quote) -> QualityRuleResult:
        """成交量必须 >= 0

        Warning — 负成交量异常但数据可能仍有参考价值。
        """
        if quote.volume is None:
            return QualityRuleResult(
                rule_name="volume_non_negative",
                dimension=QualityDimension.COMPLETENESS.value,
                severity=QualitySeverity.WARNING.value,
                passed=True,  # absent is not a failure here
                message="Volume not provided, skipping check",
            )
        if quote.volume >= 0:
            return QualityRuleResult(
                rule_name="volume_non_negative",
                dimension=QualityDimension.REASONABLENESS.value,
                severity=QualitySeverity.WARNING.value,
                passed=True,
                expected=">= 0",
                actual=quote.volume,
                message=f"Volume {quote.volume} is valid",
            )
        return QualityRuleResult(
            rule_name="volume_non_negative",
            dimension=QualityDimension.REASONABLENESS.value,
            severity=QualitySeverity.WARNING.value,
            passed=False,
            expected=">= 0",
            actual=quote.volume,
            message=f"Volume {quote.volume} is negative",
        )

    @staticmethod
    def _check_high_low_consistent(quote: Quote) -> QualityRuleResult:
        """最高价 >= 最低价

        Blocker — 违反市场基本逻辑。
        """
        if quote.high is None or quote.low is None:
            return QualityRuleResult(
                rule_name="high_low_consistent",
                dimension=QualityDimension.CONSISTENCY.value,
                severity=QualitySeverity.WARNING.value,
                passed=True,
                message="High/low not provided, skipping check",
            )
        if quote.high >= quote.low:
            return QualityRuleResult(
                rule_name="high_low_consistent",
                dimension=QualityDimension.CONSISTENCY.value,
                severity=QualitySeverity.BLOCKER.value,
                passed=True,
                expected=f"high >= low",
                actual=f"high={quote.high}, low={quote.low}",
                message=f"High {quote.high} >= Low {quote.low}",
            )
        return QualityRuleResult(
            rule_name="high_low_consistent",
            dimension=QualityDimension.CONSISTENCY.value,
            severity=QualitySeverity.BLOCKER.value,
            passed=False,
            expected=f"high >= low",
            actual=f"high={quote.high}, low={quote.low}",
            message=f"High {quote.high} < Low {quote.low}",
        )

    @staticmethod
    def _check_open_within_range(quote: Quote) -> QualityRuleResult:
        """开盘价应在 [low, high] 区间内

        Warning — 偶尔可接受但应关注。
        """
        if quote.open is None or quote.low is None or quote.high is None:
            return QualityRuleResult(
                rule_name="open_within_range",
                dimension=QualityDimension.CONSISTENCY.value,
                severity=QualitySeverity.WARNING.value,
                passed=True,
                message="Open/low/high not all provided, skipping check",
            )
        if quote.low <= quote.open <= quote.high:
            return QualityRuleResult(
                rule_name="open_within_range",
                dimension=QualityDimension.CONSISTENCY.value,
                severity=QualitySeverity.WARNING.value,
                passed=True,
                expected=f"low <= open <= high",
                actual=f"open={quote.open}, low={quote.low}, high={quote.high}",
                message=f"Open {quote.open} in [{quote.low}, {quote.high}]",
            )
        return QualityRuleResult(
            rule_name="open_within_range",
            dimension=QualityDimension.CONSISTENCY.value,
            severity=QualitySeverity.WARNING.value,
            passed=False,
            expected=f"low <= open <= high",
            actual=f"open={quote.open}, low={quote.low}, high={quote.high}",
            message=f"Open {quote.open} outside [{quote.low}, {quote.high}]",
        )

    @staticmethod
    def _check_price_within_range(quote: Quote) -> QualityRuleResult:
        """最新价应在 [low, high] 区间内

        Blocker — 价格超出当日范围表示数据异常。
        """
        if quote.price is None or quote.low is None or quote.high is None:
            return QualityRuleResult(
                rule_name="price_within_range",
                dimension=QualityDimension.CONSISTENCY.value,
                severity=QualitySeverity.BLOCKER.value,
                passed=True,
                message="Price/low/high not all provided, skipping check",
            )
        if quote.low <= quote.price <= quote.high:
            return QualityRuleResult(
                rule_name="price_within_range",
                dimension=QualityDimension.CONSISTENCY.value,
                severity=QualitySeverity.BLOCKER.value,
                passed=True,
                expected=f"low <= price <= high",
                actual=f"price={quote.price}, low={quote.low}, high={quote.high}",
                message=f"Price {quote.price} in [{quote.low}, {quote.high}]",
            )
        return QualityRuleResult(
            rule_name="price_within_range",
            dimension=QualityDimension.CONSISTENCY.value,
            severity=QualitySeverity.BLOCKER.value,
            passed=False,
            expected=f"low <= price <= high",
            actual=f"price={quote.price}, low={quote.low}, high={quote.high}",
            message=f"Price {quote.price} outside [{quote.low}, {quote.high}]",
        )

    @staticmethod
    def _check_change_pct_reasonable(quote: Quote) -> QualityRuleResult:
        """涨跌幅应在 A 股合理范围内

        Blocker — 超限涨跌幅通常是数据错误。
        """
        if quote.change_pct is None:
            return QualityRuleResult(
                rule_name="change_pct_reasonable",
                dimension=QualityDimension.REASONABLENESS.value,
                severity=QualitySeverity.WARNING.value,
                passed=True,
                message="Change_pct not provided, skipping check",
            )
        if A_SHARE_CHANGE_PCT_LOWER <= quote.change_pct <= A_SHARE_CHANGE_PCT_UPPER:
            return QualityRuleResult(
                rule_name="change_pct_reasonable",
                dimension=QualityDimension.REASONABLENESS.value,
                severity=QualitySeverity.BLOCKER.value,
                passed=True,
                expected=f"[{A_SHARE_CHANGE_PCT_LOWER}, {A_SHARE_CHANGE_PCT_UPPER}]",
                actual=quote.change_pct,
                message=f"Change_pct {quote.change_pct}% is within A-share limits",
            )
        return QualityRuleResult(
            rule_name="change_pct_reasonable",
            dimension=QualityDimension.REASONABLENESS.value,
            severity=QualitySeverity.BLOCKER.value,
            passed=False,
            expected=f"[{A_SHARE_CHANGE_PCT_LOWER}, {A_SHARE_CHANGE_PCT_UPPER}]",
            actual=quote.change_pct,
            message=f"Change_pct {quote.change_pct}% exceeds A-share limits",
        )

    @staticmethod
    def _check_amount_consistency(quote: Quote) -> QualityRuleResult:
        """成交额 ≈ 价格 × 成交量（允许 ±20% 偏差）

        Info — 仅供参考，不阻塞。
        """
        if quote.price is None or quote.volume is None or quote.amount is None:
            return QualityRuleResult(
                rule_name="amount_consistency",
                dimension=QualityDimension.CONSISTENCY.value,
                severity=QualitySeverity.INFO.value,
                passed=True,
                message="Price/volume/amount not all provided, skipping check",
            )
        if quote.volume == 0:
            return QualityRuleResult(
                rule_name="amount_consistency",
                dimension=QualityDimension.CONSISTENCY.value,
                severity=QualitySeverity.INFO.value,
                passed=True,
                message="Volume is zero, skipping amount consistency check",
            )
        expected_amount = quote.price * quote.volume
        ratio = quote.amount / expected_amount if expected_amount != 0 else 0
        # Allow ±20% deviation
        if 0.8 <= ratio <= 1.2:
            return QualityRuleResult(
                rule_name="amount_consistency",
                dimension=QualityDimension.CONSISTENCY.value,
                severity=QualitySeverity.INFO.value,
                passed=True,
                expected=f"~={expected_amount:.0f}",
                actual=quote.amount,
                message=f"Amount {quote.amount:.0f} ≈ Price*Volume {expected_amount:.0f} (ratio={ratio:.2f})",
            )
        return QualityRuleResult(
            rule_name="amount_consistency",
            dimension=QualityDimension.CONSISTENCY.value,
            severity=QualitySeverity.INFO.value,
            passed=False,
            expected=f"~={expected_amount:.0f}",
            actual=quote.amount,
            message=f"Amount {quote.amount:.0f} != Price*Volume {expected_amount:.0f} (ratio={ratio:.2f})",
        )

    def _check_timeliness(self, quote: Quote) -> QualityRuleResult:
        """检查数据时效性

        Blocker — 过期数据不可用。
        """
        if not quote.timestamp:
            return QualityRuleResult(
                rule_name="timeliness",
                dimension=QualityDimension.TIMELINESS.value,
                severity=QualitySeverity.BLOCKER.value,
                passed=False,
                message="No timestamp provided",
            )
        try:
            quote_time = datetime.fromisoformat(quote.timestamp)
            now = datetime.now(CST)
            age_seconds = (now - quote_time).total_seconds()
        except (ValueError, TypeError) as exc:
            return QualityRuleResult(
                rule_name="timeliness",
                dimension=QualityDimension.TIMELINESS.value,
                severity=QualitySeverity.BLOCKER.value,
                passed=False,
                message=f"Invalid timestamp '{quote.timestamp}': {exc}",
            )

        if age_seconds <= self.max_age_seconds:
            return QualityRuleResult(
                rule_name="timeliness",
                dimension=QualityDimension.TIMELINESS.value,
                severity=QualitySeverity.BLOCKER.value,
                passed=True,
                expected=f"age <= {self.max_age_seconds}s",
                actual=f"age={int(age_seconds)}s",
                message=f"Data age {int(age_seconds)}s is within {self.max_age_seconds}s limit",
            )
        return QualityRuleResult(
            rule_name="timeliness",
            dimension=QualityDimension.TIMELINESS.value,
            severity=QualitySeverity.BLOCKER.value,
            passed=False,
            expected=f"age <= {self.max_age_seconds}s",
            actual=f"age={int(age_seconds)}s",
            message=f"Data age {int(age_seconds)}s exceeds {self.max_age_seconds}s limit",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_source_quality(self, source_id: str, report: QualityReport):
        """将质量评分更新到数据源的 spec 中"""
        spec = self.registry.get_source(source_id)
        if spec is None:
            return

        # Calculate quality score as percentage of passed checks
        quality_score = round(
            (report.passed_checks / max(report.total_checks, 1)) * 100, 1
        )

        # Update health metadata
        spec.health.update({
            "quality_score": quality_score,
            "quality_verdict": report.overall_verdict,
            "quality_last_check": report.timestamp,
        })
        spec.updated_at = datetime.now(CST).isoformat()

        # Write back
        from factor_lab.data_source.registry import _spec_path
        _spec_path(source_id).write_text(
            json.dumps(spec.to_dict(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        # Also update the registry index
        from factor_lab.data_source.registry import _load_index, _save_index
        index = _load_index()
        for entry in index:
            if entry["source_id"] == source_id:
                if "health" not in entry:
                    entry["health"] = {}
                entry["health"].update({
                    "quality_score": quality_score,
                    "quality_verdict": report.overall_verdict,
                })
                break
        _save_index(index)


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------


def run_quality_check(symbols: list[str] = None) -> dict:
    """CLI-friendly quality check runner

    Uses RealtimeQuoteEngine to fetch quotes, then runs the quality gate.

    Args:
        symbols: 股票代码列表 (默认 ["688012"])

    Returns:
        dict: { "report": QualityReport summary, "gate": DataQualityGate }
    """
    if symbols is None:
        symbols = ["688012"]

    from factor_lab.data_source.ingest import RealtimeQuoteEngine

    engine = RealtimeQuoteEngine()
    gate = DataQualityGate()

    batch = engine.fetch_batch(symbols)
    report = gate.check_batch_result(batch)
    gate.store_report(report)

    return {"report": report, "gate": gate}


def cmd_quality():
    """CLI entry point: python -m factor_lab.data_source.quality"""
    result = run_quality_check()
    report = result["report"]
    s = report.summary()
    verdict_icon = {"pass": "✅", "conditional_pass": "⚠️", "fail": "❌"}
    print(f"{verdict_icon.get(report.overall_verdict, '❓')} 数据质量检查: {report.overall_verdict}")
    print(f"  Source: {s['source_id']}")
    print(f"  Checks: {s['passed_checks']}/{s['total_checks']} passed")
    print(f"  Blockers: {s['blocker_count']}, Warnings: {s['warning_count']}")
    print(f"  Symbols checked: {s['symbol_count']}")


if __name__ == "__main__":
    cmd_quality()
