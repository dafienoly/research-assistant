"""Mutation Engine — 定向突变引擎

诊断因子失败模式，选择定向突变策略:
  - MUTATE_WINDOW:          调整时序窗口参数
  - MUTATE_OPERATOR:        替换核心算子
  - MUTATE_NORMALIZATION:   添加标准化/非线性变换
  - MUTATE_SIGNAL_TYPE:     翻转因子方向
  - MUTATE_NONLINEAR:       引入非线性变换
  - MUTATE_INTERACTION:     组合多信号源
  - SIMPLIFY:               降低复杂度
  - REGENERATE_FULL:        完全重写

基于 QuantGPT mutation_engine.py + XTQuant QuantaAlpha 移植。
"""

import re
from enum import Enum
from dataclasses import dataclass


class MutationStrategy(Enum):
    MUTATE_WINDOW = "mutate_window"
    MUTATE_OPERATOR = "mutate_operator"
    MUTATE_NORMALIZATION = "mutate_normalization"
    MUTATE_SIGNAL_TYPE = "mutate_signal_type"
    MUTATE_NONLINEAR = "mutate_nonlinear"
    MUTATE_INTERACTION = "mutate_interaction"
    SIMPLIFY = "simplify"
    REGENERATE_FULL = "regenerate_full"


@dataclass
class Diagnosis:
    strategy: MutationStrategy
    reason: str
    details: dict


# 算子替换映射
_OPERATOR_REPLACEMENTS = {
    "ts_mean": ["decay_linear", "ts_sum", "ema"],
    "ts_std": ["ts_mean", "ts_rank"],
    "ts_delta": ["ts_shift", "ts_rank"],
    "ts_corr": ["ts_cov", "ts_rank"],
    "ts_rank": ["rank", "zscore"],
    "rank": ["zscore", "scale", "tanh"],
    "decay_linear": ["ts_mean", "ts_sum"],
    "ts_max": ["ts_min", "ts_argmax"],
    "ts_min": ["ts_max", "ts_argmin"],
    "where": ["clip", "sign_power"],
}

_NORMALIZATION_OPS = {"rank", "zscore", "scale", "tanh", "sigmoid"}
_NONLINEAR_OPS = {"tanh", "sigmoid", "power", "sign_power", "log", "sqrt", "exp"}
_BASE_VARS = {"open", "high", "low", "close", "volume", "amount", "vwap", "returns"}


class MutationEngine:
    """诊断因子失败模式并构建定向突变 prompt"""

    def __init__(self, expression: str, metrics: dict, score: float):
        self.expression = expression
        self.metrics = metrics
        self.score = score
        self.backtest = metrics.get("backtest_summary", {})
        self.report = metrics.get("report_metrics", {})

    def diagnose_failure(self) -> Diagnosis:
        """分析指标并选择最佳突变策略"""
        ic_mean = self.backtest.get("ic_mean", 0) or 0
        ic_ir = self.backtest.get("ic_ir", 0) or 0
        nesting = self._count_nesting(self.expression)
        has_norm = self._has_normalization(self.expression)
        has_nonlinear = self._has_nonlinear(self.expression)

        # 1. 极低评分 → 完全重写
        if self.score < 20:
            return Diagnosis(
                MutationStrategy.REGENERATE_FULL,
                f"极低评分({self.score}), 需要完全重写",
                {"score": self.score},
            )

        # 2. IC 接近零 → 算子问题
        if abs(ic_mean) < 0.005:
            return Diagnosis(
                MutationStrategy.MUTATE_OPERATOR,
                f"IC 接近零({ic_mean:.4f}), 当前算子无预测能力",
                {"ic_mean": ic_mean, "suggested": self._suggest_replacements()},
            )

        # 3. IC 为负 → 方向反转
        if ic_mean < -0.01:
            return Diagnosis(
                MutationStrategy.MUTATE_SIGNAL_TYPE,
                f"IC 为负({ic_mean:.4f}), 因子方向反转",
                {"ic_mean": ic_mean},
            )

        # 4. 嵌套过深 → 简化
        if nesting > 8:
            return Diagnosis(
                MutationStrategy.SIMPLIFY,
                f"嵌套层数过深({nesting}层), 需简化",
                {"nesting_depth": nesting},
            )

        # 5. 中分 + 无非线性 → 引入非线性
        if 20 <= self.score < 50 and not has_nonlinear:
            return Diagnosis(
                MutationStrategy.MUTATE_NONLINEAR,
                f"评分中等({self.score})且无非线性变换",
                {"score": self.score, "has_nonlinear": False},
            )

        # 6. IR 低 + 无标准化 → 添加标准化
        if ic_ir < 0.5 and not has_norm:
            return Diagnosis(
                MutationStrategy.MUTATE_NORMALIZATION,
                f"IR 较低({ic_ir:.2f})且无标准化",
                {"ic_ir": ic_ir, "has_normalization": has_norm},
            )

        # 7. 单信号 → 组合交互
        if self._is_single_signal():
            return Diagnosis(
                MutationStrategy.MUTATE_INTERACTION,
                "单信号因子, 建议组合多个信号源",
                {"signal_count": 1},
            )

        # 8. 默认 → 调整窗口
        return Diagnosis(
            MutationStrategy.MUTATE_WINDOW,
            "默认策略: 调整时序窗口参数",
            {"ic_mean": ic_mean, "ic_ir": ic_ir, "windows": self._extract_windows()},
        )

    def build_mutation_prompt(self) -> str:
        """构建突变 prompt"""
        diagnosis = self.diagnose_failure()
        strategy = diagnosis.strategy

        parts = [
            "你是一个量化因子表达式优化专家。基于诊断结果改进因子。",
            "",
            f"当前因子: {self.expression}",
            f"评分: {self.score:.1f}/100",
            f"IC均值: {self.backtest.get('ic_mean', 'N/A')}",
            f"IC_IR: {self.backtest.get('ic_ir', 'N/A')}",
            f"换手率: {self.backtest.get('turnover', 'N/A')}",
            "",
            f"## 诊断: {strategy.value}",
            f"原因: {diagnosis.reason}",
            "",
        ]

        strategy_prompts = {
            MutationStrategy.MUTATE_WINDOW:
                "## 突变指令: 调整时序窗口\n"
                f"当前窗口参数: {diagnosis.details.get('windows', [])}\n"
                "请尝试不同的窗口长度（5/10/20/40/60），保留核心算子结构。",
            MutationStrategy.MUTATE_OPERATOR:
                "## 突变指令: 替换核心算子\n"
                f"建议替换方案: {diagnosis.details.get('suggested', {})}\n"
                "当前算子无预测能力，请替换为其他类型的时序/截面算子。",
            MutationStrategy.MUTATE_NORMALIZATION:
                "## 突变指令: 添加标准化\n"
                "请在表达式外层添加 rank() 或 zscore()，"
                "或在关键子表达式上添加 scale() / tanh() 压缩极端值。",
            MutationStrategy.MUTATE_SIGNAL_TYPE:
                "## 突变指令: 翻转因子方向\n"
                "因子 IC 为负，请在表达式前添加 -1 * 或调整信号逻辑。",
            MutationStrategy.MUTATE_NONLINEAR:
                "## 突变指令: 引入非线性变换\n"
                "- tanh(x): 压缩极端值，增强鲁棒性\n"
                "- power(x, 0.5) / sign_power(x, 0.5): 弱化极端值\n"
                "- sigmoid(x): S 型映射，适合二值化信号\n"
                "- 组合: rank(tanh(ts_delta(close, 20) / ts_std(close, 20)))",
            MutationStrategy.MUTATE_INTERACTION:
                "## 突变指令: 组合多信号源\n"
                "- 量价交互: rank(volume_signal) * rank(price_signal)\n"
                "- 动量+波动: rank(momentum) * rank(-volatility)\n"
                "- 条件组合: where(vol_condition, signal_a, signal_b)\n"
                "- 加权组合: 0.6*rank(a) + 0.4*rank(b)",
            MutationStrategy.SIMPLIFY:
                f"## 突变指令: 简化表达式\n"
                f"当前嵌套深度: {self._count_nesting(self.expression)} 层\n"
                "减少嵌套到 6 层以内，移除冗余变换，保留核心信号。",
            MutationStrategy.REGENERATE_FULL:
                "## 突变指令: 完全重写\n"
                "当前因子完全无效，从零开始设计新因子。\n"
                "建议尝试: 动量、反转、量价相关、波动率等经典因子类别。",
        }

        parts.append(strategy_prompts.get(strategy, ""))
        parts.append("")
        parts.append(
            "## 输出格式\n"
            "只返回一个因子表达式，不要任何解释或 markdown 代码块。\n"
            "表达式必须是一行可执行的因子公式。"
        )
        parts.append("")
        parts.append("请生成改进后的因子表达式：")

        return "\n".join(parts)

    # ── 分析辅助函数 ─────────────────────────────────

    def _count_nesting(self, expr: str) -> int:
        max_depth = depth = 0
        for ch in expr:
            if ch == '(':
                depth += 1
                max_depth = max(max_depth, depth)
            elif ch == ')':
                depth -= 1
        return max_depth

    def _has_normalization(self, expr: str) -> bool:
        return any(op + "(" in expr.lower() for op in _NORMALIZATION_OPS)

    def _has_nonlinear(self, expr: str) -> bool:
        return any(op + "(" in expr.lower() for op in _NONLINEAR_OPS)

    def _is_single_signal(self) -> bool:
        expr_lower = self.expression.lower()
        used = [v for v in _BASE_VARS if v in expr_lower]
        return len(used) <= 1

    def _extract_windows(self) -> list[int]:
        matches = re.findall(r"ts_\w+\([^,]+,\s*(\d+)\)", self.expression)
        return sorted(set(int(m) for m in matches))

    def _suggest_replacements(self) -> dict[str, list[str]]:
        suggestions = {}
        expr_lower = self.expression.lower()
        for op, replacements in _OPERATOR_REPLACEMENTS.items():
            if op + "(" in expr_lower:
                suggestions[op] = replacements
        return suggestions
