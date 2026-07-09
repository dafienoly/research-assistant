# V3.6.3 LLM因子诊断 — 子代理 Spec

## 依赖：V3.6.1 (FailureDatabase) ✅ | V3.6.2 (prompt 增强) 建议先完成

## 背景

当前因子研究流程：LLM 生成因子 → 回测 → 评分 → A/B/C/D → 注册/淘汰。
缺失一步：**为什么这个因子成功/失败？什么条件下有效？如何改进？**

V3.1.2 验证了 20 个因子，每个都有完整的 IC/IR/WalkForward/Placebo/同池等权结果，但从未被 LLM 分析过。

## 目标

实现 LLM 因子诊断接口：输入因子表达式 + 完整验证报告 → 输出结构化诊断（成功原因、失败原因、市场条件、改进建议）。

## 修改文件

### commands/factor_lab/alpha/llm_alpha_discovery.py

在文件末尾追加：

```python
"""V3.6.3 LLM因子诊断 — 分析因子验证结果并给出改进建议"""

FACTOR_DIAGNOSIS_PROMPT_TEMPLATE = """You are a quantitative alpha research reviewer for A-share market.
Analyze the following factor validation report and provide a structured diagnosis.

## Factor Information
{factor_info}

## Validation Results
{validation_results}

## Diagnosis Requirements
Please analyze:

1. **Why does this factor work (or fail)?**
   - Is the IC positive/negative/stable?
   - Does it beat the peer equal-weight benchmark?
   - What is the exposure (industry, size, volatility)?

2. **What market regime does this factor favor?**
   - Bullish / Bearish / Oscillating / Structural market?
   - Based on IC stability across sub-periods

3. **What are the failure risks?**
   - IC decay speed (half-life)
   - Placebo test significance
   - Walk-forward OOS performance
   - Overfitting risk

4. **Improvement suggestions** (be specific)
   - What orthogonal factor could complement it?
   - What filter could reduce drawdown?
   - What parameter range to test?

## Output Format (JSON only)
```json
{{
  "factor_name": "...",
  "overall_assessment": "strong / moderate / weak / failed",
  "strengths": [...],
  "weaknesses": [...],
  "favored_market_regime": "bullish/bearish/oscillating/structural",
  "failure_risks": {{
    "ic_decay": "fast/moderate/slow",
    "overfitting_risk": "high/medium/low",
    "placebo_significant": true/false
  }},
  "improvement_suggestions": [
    {{
      "type": "orthogonal_factor / filter / parameter_tuning",
      "description": "...",
      "expected_impact": "..."
    }}
  ],
  "verdict": "promote/watch/retire"
}}
```
"""


def diagnose_factor(validation_path: str, factor_expression: str = "") -> dict:
    """LLM 因子诊断 — 分析验证结果并给出改进建议
    
    Args:
        validation_path: 因子验证报告路径（来自 V3.1.2）
            research_outputs/factor_validation/<factor_name>/report.json
        factor_expression: 因子表达式（可选）
    
    Returns:
        dict: LLM 诊断结果
    """
    import json
    from pathlib import Path
    
    val_path = Path(validation_path)
    if not val_path.exists():
        return {"error": f"验证报告不存在: {validation_path}"}
    
    with open(val_path) as f:
        data = json.load(f)
    
    # 构造 factor_info
    factor_info = json.dumps({
        "factor_name": data.get("factor_name", ""),
        "expression": factor_expression or data.get("factor_name", ""),
        "hypothesis": data.get("score", {}).get("factor_family", "unknown"),
    }, indent=2, ensure_ascii=False)
    
    # 提取关键验证结果
    validation_results = json.dumps({
        "ic_mean": data.get("ic_analysis", {}).get("ic_mean", "N/A"),
        "ic_ir": data.get("ic_analysis", {}).get("ic_ir", "N/A"),
        "pos_ratio": data.get("ic_analysis", {}).get("pos_ratio", "N/A"),
        "beats_peer": data.get("anti_overfit", {}).get("peer_benchmark", {}).get("beats_peer", "N/A"),
        "excess_return": data.get("anti_overfit", {}).get("peer_benchmark", {}).get("excess_return_pct", "N/A"),
        "walk_forward_verdict": data.get("walk_forward", {}).get("overall_verdict", "N/A"),
        "placebo_verdict": data.get("anti_overfit", {}).get("placebo", {}).get("verdict", "N/A"),
        "half_life": data.get("anti_overfit", {}).get("ic_decay", {}).get("half_life_days", "N/A"),
        "overall_grade": data.get("score", {}).get("grade", "N/A"),
        "overall_score": data.get("score", {}).get("overall_score", "N/A"),
    }, indent=2, ensure_ascii=False)
    
    # 构造 prompt
    prompt = FACTOR_DIAGNOSIS_PROMPT_TEMPLATE.format(
        factor_info=factor_info,
        validation_results=validation_results,
    )
    
    # 调用 LLM
    response = _call_llm(prompt)
    
    # 解析 JSON
    try:
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            diagnosis = json.loads(json_match.group(1))
        else:
            diagnosis = json.loads(response)
    except Exception as e:
        diagnosis = {"error": f"LLM 响应解析失败: {e}", "raw": response[:500]}
    
    return diagnosis


def diagnose_multiple_factors(validation_dir: str, factor_names: list[str] = None) -> list[dict]:
    """批量诊断多个因子"""
    from pathlib import Path
    results = []
    
    for report_path in sorted(Path(validation_dir).glob("*/report.json")):
        name = report_path.parent.name
        if factor_names and name not in factor_names:
            continue
        print(f"诊断中: {name}...")
        diagnosis = diagnose_factor(str(report_path))
        diagnosis["factor_name"] = name
        results.append(diagnosis)
    
    return results
```

### 验证

```python
from factor_lab.alpha.llm_alpha_discovery import (
    FACTOR_DIAGNOSIS_PROMPT_TEMPLATE, diagnose_factor,
)

# 验证 prompt 模板完整性
assert "{factor_info}" in FACTOR_DIAGNOSIS_PROMPT_TEMPLATE
assert "{validation_results}" in FACTOR_DIAGNOSIS_PROMPT_TEMPLATE
assert "improvement_suggestions" in FACTOR_DIAGNOSIS_PROMPT_TEMPLATE
print("✅ 诊断 prompt 完整")

# 验证诊断函数（使用已有验证报告）
import os
path = "research_outputs/factor_validation/ret5/report.json"
if os.path.exists(path):
    # 只验证函数调用链，不实际调用 LLM（需要 hermes -z）
    # 测试参数校验
    result = diagnose_factor("/nonexistent/path")
    assert "error" in result, "不存在路径应返回 error"
    print(f"✅ 参数校验: {result['error']}")
else:
    print("⚠️ 验证报告不存在，跳过 LLM 调用测试")

print("\n✅ V3.6.3 LLM因子诊断完成")
```

## 注意事项
1. `_call_llm()` 已存在于 llm_alpha_discovery.py 中，直接复用
2. 诊断结果包含 JSON 结构化输出，可被后续流程消费
3. 不修改现有函数，只追加新函数
4. 实际 LLM 调用需要 `hermes -z` 命令可用
