"""V4.6 Future Leakage Gate — 未来函数检测与数据时间线校验

检查维度:
  1. T日因子是否使用T日"预测"T日收益（同一天用收盘价算的因子预测当天收益=未来泄露）
  2. 是否使用 end_of_day 价格数据在盘中进行预测
  3. 因子表达式中是否包含 returns/ret1 字段同时出现在结果变量位置
  4. 因子表达式的 window 参数是否暗示使用未来信息

用法:
    from factor_lab.alpha.future_leakage_gate import (
        FutureLeakageGate,
        LeakageSeverity,
        check_factor_expression_leakage,
        check_data_timeline_leakage,
        check_returns_peek_leakage,
    )
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LeakageSeverity(Enum):
    """未来泄露严重程度"""
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class LeakageReport:
    """未来函数检查报告"""
    passed: bool = True
    severity: LeakageSeverity = LeakageSeverity.NONE
    issues: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# 检测模式数据库
# ═══════════════════════════════════════════════════════════════════

# 模式 1: 使用 T 日 returns 作为因子输入 → 用当天收益预测当天收益 = 未来泄露
RETURNS_AS_INPUT_PATTERNS = [
    r'returns\s*[*+/-]',
    r'[*+/-]\s*returns',
    r'rank\s*\(\s*returns',
    r'zscore\s*\(\s*returns',
    r'ts_mean\s*\(\s*returns',
    r'ts_std\s*\(\s*returns',
    r'ts_corr\s*\(\s*returns',
    r'ts_delta\s*\(\s*returns',
    r'ts_decay_linear\s*\(\s*returns',
]

# 模式 2: 收盘价在盘中使用的嫌疑 (如果策略是盘中交易)
CLOSE_PRICE_INTRADAY_USE = [
    r'close\s*[*+/-]',
    r'vwap\s*[*+/-]',
]

# 模式 3: window=1 的未来函数
WINDOW_ONE_PATTERNS = [
    r'ts_mean\s*\(\s*\w+\s*,\s*1\s*\)',
    r'ts_std\s*\(\s*\w+\s*,\s*1\s*\)',
    r'ts_min\s*\(\s*\w+\s*,\s*1\s*\)',
    r'ts_max\s*\(\s*\w+\s*,\s*1\s*\)',
    r'ema\s*\(\s*\w+\s*,\s*1\s*\)',
    r'sma\s*\(\s*\w+\s*,\s*1\s*\)',
]

# 模式 4: 负 window → 读取未来数据
NEGATIVE_WINDOW_PATTERNS = [
    r'ts_delta\s*\(\s*\w+\s*,\s*-?\d+\s*\)',
    r'ts_mean\s*\(\s*\w+\s*,\s*-?\d+\s*\)',
    r'ts_std\s*\(\s*\w+\s*,\s*-?\d+\s*\)',
    r'ts_corr\s*\(\s*\w+\s*,\s*\w+\s*,\s*-?\d+\s*\)',
]

# 模式 5: ts_delta(x, 0) → 无意义但可能泄露
DELTA_ZERO_PATTERN = r'ts_delta\s*\(\s*\w+\s*,\s*0\s*\)'


class FutureLeakageGate:
    """未来函数检查门 — 多维度静态/动态检查

    check_levels:
      - "static": 仅做表达式静态分析 (default)
      - "full": 包含数据时间线检查

    用法:
        gate = FutureLeakageGate()
        report = gate.check("rank(close / ts_mean(close, 20))")
        if not report.passed:
            print(f"泄露等级: {report.severity}")
            for issue in report.issues:
                print(f"  - {issue}")
    """

    def __init__(self, check_level: str = "static"):
        self.check_level = check_level

    def check(self, expression: str, context: Optional[dict] = None) -> LeakageReport:
        """执行全面未来函数检查

        Args:
            expression: 因子表达式
            context: 上下文信息，可包含:
                - trade_time: 交易时间 ("intraday" / "close")
                - data_timeline: 数据时间线描述
                - prediction_target: 预测目标 ("next_day_return" / "same_day_return")

        Returns:
            LeakageReport
        """
        report = LeakageReport()
        context = context or {}

        # 1. 检查 returns 作为输入 (最严重的泄露)
        self._check_returns_as_input(expression, report)

        # 2. 检查 window=1
        self._check_window_one(expression, report)

        # 3. 检查负 window
        self._check_negative_window(expression, report)

        # 4. 检查 ts_delta(x, 0)
        self._check_delta_zero(expression, report)

        # 5. 检查收盘价盘中使用 (仅在 context 指定时)
        if context.get("trade_time") == "intraday":
            self._check_close_use_intraday(expression, report)

        # 6. 完整模式下检查数据时间线
        if self.check_level == "full":
            self._check_data_timeline(expression, context, report)

        # 综合判定
        report.passed = len(report.issues) == 0
        return report

    def _check_returns_as_input(self, expression: str, report: LeakageReport):
        """检查因子是否使用 returns 作为输入 (T日收益预测T日收益)"""
        for pattern in RETURNS_AS_INPUT_PATTERNS:
            if re.search(pattern, expression):
                report.issues.append(
                    f"CRITICAL: 因子表达式使用 returns 字段作为输入 — "
                    f"这代表用 T 日收益预测同一天收益，属于直接未来泄露。"
                    f"匹配模式: {pattern}"
                )
                report.severity = LeakageSeverity.CRITICAL
                return  # 一个 critical 就够了

    def _check_window_one(self, expression: str, report: LeakageReport):
        """检查 window=1 的未来函数"""
        for pattern in WINDOW_ONE_PATTERNS:
            matches = re.findall(pattern, expression)
            for m in matches:
                report.issues.append(
                    f"HIGH: 检测到 window=1 的操作 ({m}) — "
                    f"window=1 等价于使用当日数据预测当日，属于未来泄露"
                )
                if report.severity.value < LeakageSeverity.HIGH.value:
                    report.severity = LeakageSeverity.HIGH

    def _check_negative_window(self, expression: str, report: LeakageReport):
        """检查负 window — 读取未来数据"""
        for pattern in NEGATIVE_WINDOW_PATTERNS:
            matches = re.findall(pattern, expression)
            for m in matches:
                # 只有实际负的才报
                nums = re.findall(r'-?\d+', m)
                if nums:
                    val = int(nums[-1])
                    if val < 0:
                        report.issues.append(
                            f"CRITICAL: 检测到负 window 参数 ({m}) — "
                            f"负窗口读取未来数据，属于直接未来泄露"
                        )
                        report.severity = LeakageSeverity.CRITICAL

    def _check_delta_zero(self, expression: str, report: LeakageReport):
        """检查 ts_delta(x, 0)"""
        if re.search(DELTA_ZERO_PATTERN, expression):
            report.issues.append(
                f"MEDIUM: 检测到 ts_delta(x, 0) — 虽然不会泄露未来数据，"
                f"但该用法无实际意义（window=0 的 delta 始终为 0）"
            )
            if report.severity.value < LeakageSeverity.MEDIUM.value:
                report.severity = LeakageSeverity.MEDIUM

    def _check_close_use_intraday(self, expression: str, report: LeakageReport):
        """检查收盘价在盘中使用 (盘中策略)"""
        for pattern in CLOSE_PRICE_INTRADAY_USE:
            if re.search(pattern, expression):
                report.issues.append(
                    f"HIGH: 盘中交易策略中使用 close/vwap 字段 — "
                    f"收盘价在收盘前不可知，属于未来泄露"
                )
                if report.severity.value < LeakageSeverity.HIGH.value:
                    report.severity = LeakageSeverity.HIGH

    def _check_data_timeline(self, expression: str, context: dict, report: LeakageReport):
        """完整模式下的数据时间线检查"""
        timeline = context.get("data_timeline", "")
        target = context.get("prediction_target", "next_day_return")

        if target == "same_day_return":
            report.issues.append(
                f"CRITICAL: 预测目标为 same_day_return — "
                f"在 T 日无法预测当天收益，属于直接未来泄露"
            )
            report.severity = LeakageSeverity.CRITICAL

        # 检查数据可用性
        if "end_of_day" in timeline.lower() and "intraday" in timeline.lower():
            report.issues.append(
                f"HIGH: 数据时间线同时包含 end_of_day 和 intraday — "
                f"可能存在端数据在盘中使用的情况"
            )
            if report.severity.value < LeakageSeverity.HIGH.value:
                report.severity = LeakageSeverity.HIGH


# ═══════════════════════════════════════════════════════════════════
# 快捷检查函数
# ═══════════════════════════════════════════════════════════════════


def check_factor_expression_leakage(expression: str) -> LeakageReport:
    """快捷检查: 仅检查因子表达式中的未来函数

    等价于 FutureLeakageGate().check(expression)
    """
    gate = FutureLeakageGate(check_level="static")
    return gate.check(expression)


def check_data_timeline_leakage(data_timeline: str, prediction_target: str) -> LeakageReport:
    """快捷检查: 检查数据时间线是否包含未来泄露

    Args:
        data_timeline: 数据时间线描述 (e.g., "intraday_until_1430_end_of_day_close")
        prediction_target: 预测目标 ("next_day_return" / "same_day_return")

    Returns:
        LeakageReport
    """
    gate = FutureLeakageGate(check_level="full")
    return gate.check("", context={
        "data_timeline": data_timeline,
        "prediction_target": prediction_target,
    })


def check_returns_peek_leakage(expression: str) -> bool:
    """快捷检查: 检查是否直接在因子中使用 returns 字段

    返回 True 表示存在泄露风险
    """
    gate = FutureLeakageGate()
    report = gate.check(expression)
    return report.severity in (LeakageSeverity.HIGH, LeakageSeverity.CRITICAL)


# ─── 与 AlphaSpecValidator 的集成钩子 ─────────────────────────

def integrate_into_validator(validator) -> None:
    """将 FutureLeakageGate 集成到 AlphaSpecValidator

    在 AlphaSpecValidator.validate 末尾调用此函数，追加未来泄露检查结果。

    用法:
        from factor_lab.alpha.future_leakage_gate import integrate_into_validator
        # 在 validator.validate 末尾:
        integrate_into_validator(self)  # 追加 future leakage 检查
    """
    if not hasattr(validator, "candidate"):
        return
    expression = validator.candidate.get("factor_expression", "")
    if not expression:
        return
    report = check_factor_expression_leakage(expression)
    if not report.passed:
        for issue in report.issues:
            validator.errors.append(f"[FutureLeakageGate] {issue}")
