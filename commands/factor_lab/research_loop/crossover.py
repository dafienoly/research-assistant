"""Crossover Engine — 高分因子交叉重组

从迭代历史中提取高分表达式，构建 crossover prompt:
  - A 的时间窗口 + B 的算子 + C 的标准化
  - 或加权组合多个信号源

基于 QuantGPT crossover_engine.py (XTQuant QuantaAlpha) 移植。
"""


def extract_top_segments(
    iterations: list[dict],
    min_score_ratio: float = 0.5,
    max_segments: int = 5,
) -> list[dict]:
    """从迭代历史提取高分表达式片段

    Args:
        iterations: {expression, score, ...} 列表
        min_score_ratio: 最低分数比例（相对 best）
        max_segments: 最多返回数量

    Returns:
        按评分降序排列的 top 片段列表
    """
    if not iterations:
        return []

    best_score = max(it.get("score", 0) or 0 for it in iterations)
    if best_score <= 0:
        return []

    threshold = best_score * min_score_ratio
    qualified = [
        it for it in iterations
        if it.get("expression") and (it.get("score", 0) or 0) >= threshold
    ]
    qualified.sort(key=lambda x: x.get("score", 0), reverse=True)
    return qualified[:max_segments]


def build_crossover_prompt(
    segments: list[dict],
    current_expression: str,
    current_score: float,
) -> str:
    """构建交叉重组 LLM prompt

    Args:
        segments: extract_top_segments 的输出
        current_expression: 当前因子表达式
        current_score: 当前评分

    Returns:
        LLM prompt 字符串
    """
    if not segments:
        return ""

    parts = [
        "你是一个量化因子表达式优化专家。分析多个历史高分因子表达式，",
        "提取各自的成功要素，创造性地重组为一个更优的因子。",
        "",
        "## 重组策略",
        "- 分析每个片段的核心逻辑（为什么它有效）",
        "- 提取成功要素：时间窗口、算子类型、信号方向、标准化方式",
        "- 创造性组合：A 的时间窗口 + B 的算子 + C 的标准化",
        "- 或：加权组合多个信号源",
        "- 引入非线性变换（tanh, sigmoid, power）增强表达能力",
        "",
        f"当前因子: {current_expression}",
        f"当前评分: {current_score:.1f}/100",
        "",
        "## 历史高分片段（按评分排序）",
    ]

    for i, seg in enumerate(segments, 1):
        expr = seg.get("expression", "")
        score = seg.get("score", 0)
        hypothesis = seg.get("hypothesis", "")
        parts.append(f"  {i}. [{score:.1f}分] {expr}")
        if hypothesis:
            parts.append(f"     假设: {hypothesis}")

    parts.extend([
        "",
        "## 输出格式",
        "只返回一个因子表达式，不要任何解释或 markdown 代码块。",
        "表达式必须是一行可执行的因子公式。",
        "",
        "请生成交叉重组后的新因子表达式：",
    ])

    return "\n".join(parts)
