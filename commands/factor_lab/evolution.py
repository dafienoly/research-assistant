"""因子进化引擎 — LLM 驱动的新因子生成 (V4.6 升级: 失败归因/试验计数)"""
import sys, os, json, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# 使用 opencode-go 作为 LLM 后端（与 Hermes 同一模型）
OPENCODE_URL = "https://opencode.ai/zen/go/v1"
OPENCODE_MODEL = "deepseek-v4-flash"

def _llm_chat(prompt: str, temperature: float = 0.7) -> str:
    """通过 Hermes CLI 调用 LLM (temperature param accepted but not passed to CLI)"""
    import subprocess, shlex
    try:
        result = subprocess.run(
            ["hermes", "-z", prompt],
            capture_output=True, text=True, timeout=90
        )
        out = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if not out:
            return f"ERROR: 空响应. stderr={stderr[:200]}"
        return out
    except Exception as e:
        return f"ERROR: {e}"

FACTOR_TEMPLATES = {
    "momentum": "rank(close / ts_mean(close, {window}))",
    "reversal": "-rank(close / ts_mean(close, {window}))",
    "volume_ratio": "rank(volume / ts_mean(volume, {window}))",
    "volatility": "-rank(ts_std(returns, {window}))",
    "ma_cross": "rank(ma_{fast} / ma_{slow} - 1)",
    "vol_price": "rank(ts_corr(returns, volume, {window}))",
    "composite": "rank({f1}) + rank({f2})",
}

def generate_candidates(existing_results: list, top_n: int = 5) -> list:
    """基于现有因子表现，让 LLM 生成新因子假设"""
    top = sorted(existing_results, key=lambda x: -abs(x.get("mean_ic", 0)))[:top_n]

    # 从各分类选代表
    from factor_lab.factor_base import list_factors
    all_factors = list_factors()
    seen_cats = set()
    category_reps = []
    for f in all_factors:
        cat = f.get("category", "unknown")
        if cat not in seen_cats and cat not in ("evolved", "unknown"):
            seen_cats.add(cat)
            category_reps.append(f"  [{cat}] {f['name']} — {f.get('description','')[:40]}")

    context = "\n".join([
        f"- {f['name']}: IC={f.get('mean_ic',0):+.4f}, IR={f.get('ir',0):.2f}, 类别={f.get('category','')}"
        for f in top
    ])
    cat_context = "\n".join(category_reps)

    # V4.6: 获取失败归因上下文
    failure_context = _get_failure_context_for_llm(n=10)

    prompt = f"""You are an A-share quantitative factor researcher. Based on the current factor landscape, design 3 NEW alpha factors that EXPLORE UNDISCOVERED TERRITORY.

=== CURRENT TOP FACTORS (by IC) ===
{context}

=== ALL AVAILABLE FACTOR CATEGORIES (pick from different categories!) ===
{cat_context}

=== AVAILABLE DATA FIELDS ===
Raw OHLCV: open, high, low, close, volume, amount
Derived: vwap, returns, ret1
Pre-computed factors (can reference ANY of the 142+ registered factors by name):
  momentum: ret5, ret10, ret20, ret60, ret_std20, max_high60, min_low60
  reversal: reversal5, reversal20
  trend: close_gt_ma20, ts_regression_slope20
  volume: vol_ratio5/20/60, vol_price_corr20, turnover20
  volatility: atr20, volatility20/60, downside_volatility20, intraday_range20
  liquidity: amihud_illiquidity20, amount_rank20, amount_stability20
  breakout: high_20/60_breakout, close_to_high20/60, distance_to_high20/60
  pullback: pullback_5/10_in_ma20_uptrend, low_volume_pullback
  technical: macd_dif/dea/histogram/cross, kdj_k/d/j/cross, boll_position/width/squeeze/breakout
  quality: roe_q, gross_margin_q, net_margin_q, debt_ratio_q, eps_q, quality_composite
  fund_flow: net_inflow_1d/5d, super_large_net, flow_divergence, flow_momentum, institutional_flow_ratio
  north_bound: nb_net_flow_1d/5d, nb_holding_change_5d, nb_flow_ratio
  margin: margin_buy_ratio, margin_balance_change_5d/20d, margin_net_buy
  sentiment: sentiment_1d/5d, sentiment_mom
  event: lockup_expiry_proximity, buyback_signal, dividend_yield_factor, forecast_upgrade/downgrade
  industry_relative: ret5/10/20_industry_adj, volatility20_industry_adj, industry_neutral_quality

=== OPERATORS (all 42+ supported) ===
Cross-sectional: rank(x), zscore(x), scale(x)
Time-series: ts_mean, ts_std, ts_min, ts_max, ts_sum, ts_rank, ts_delta, ts_av_diff, ts_decay_linear, ts_shift, ts_argmax, ts_argmin, ts_product, ts_zscore
Bivariate: ts_corr(x,y,w), ts_cov(x,y,w)
Technical: ema, sma, rsi
Bollinger: boll_upper, boll_lower, boll_mid, bb_width
Comparison: > < >= <= == !=    (return 0.0/1.0)
Logical: and or && ||          (return 0.0/1.0)
Nonlinear: abs, sign, sigmoid, tanh, clip, where, sign_power, log, sqrt, exp
Binary: max, min, power
Alias: delta=ts_delta, delay=ts_shift, correlation=ts_corr, sma=ts_mean, stddev=ts_std

=== VALIDATED WORKING PATTERNS ===
1. rank(A) * rank(B)          — cross-sectional multiplication (most reliable, 15+ validated)
2. where(condition, A, -B)    — regime-switching gate (vol_ratio20-1, close_gt_ma20)
3. rank(A) + rank(B)          — equal-weight blend (less concentrated than product)
4. rank(A) / (1 + rank(B))    — division-based scaling (volatility-scaled momentum)

=== CRITICAL: EXPLORE CROSS-CATEGORY COMBINATIONS ===
Most existing factors are momentum × volume variants. Look for:
- fundamentals × technical  (e.g. roe_q × boll_width)
- sentiment × momentum      (e.g. sentiment_1d × ret5)
- fund_flow × trend         (e.g. super_large_net × close_gt_ma20)
- technical × volatility    (e.g. macd_cross × -volatility20)
- event × reversal          (e.g. buyback_signal × reversal5)
- volatility × volume       (e.g. -volatility20 × vol_ratio60)
- 3-way with where gate     (e.g. where(condition, A×B, C))

=== PITFALLS TO AVOID ===
|- ts_corr(close, volume, N) → scale mismatch produces NaN. Use ts_corr(ret1, volume, N) instead
|- ts_delta(x, 1) → window=1 triggers future-function check. Minimum window=2
|- Don't use ?: ternary syntax. Use where(cond, t, f)
|- Don't use unknown field names. Only use listed fields and registered factor names

=== RECENT FACTOR FAILURES (LEARN FROM PAST MISTAKES) ===
{failure_context}

=== OUTPUT FORMAT ===
Expression | FactorName | Hypothesis/reasoning (why this combination might work)

Examples of GOOD cross-category factors:
volatility20 * bb_width | vol_regime_filter | 高波动+宽布林=趋势延续，低波动+窄布林=反转前兆
roe_q * rank(-bb_width) | quality_squeeze | 优质公司在波动压缩后更可能突破
sentiment_1d * ret5 | sentiment_momentum | 正面情绪+强势动量=趋势强化
super_large_net * close_gt_ma20 | big_money_trend | 主力资金流入+价格在均线上方=上涨确认
where(close_gt_ma20, roe_q * ret5, -ret5) | quality_trend_gate | 趋势中选优质动量，震荡中反向

Generate 3 expressions. One per line. Strict format:
Expression | FactorName | Hypothesis
"""
    response = _llm_chat(prompt)
    return parse_candidates(response)

def parse_candidates(llm_response: str) -> list:
    """解析 LLM 输出的候选因子

    支持两种格式:
      Expression | FactorName | Hypothesis   (新格式)
      FactorName: EXPRESSION                  (旧格式)
    """
    candidates = []
    for line in llm_response.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("```"):
            continue

        # 新格式: Expression | FactorName | Hypothesis
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                expr = parts[0]
                name = parts[1].replace(" ", "_").replace("-", "_")
                hypothesis = parts[2] if len(parts) >= 3 else f"LLM 生成: {expr[:60]}"
                if expr and name:
                    candidates.append({"name": name, "expression": expr, "hypothesis": hypothesis})
                continue

        # 旧格式: FactorName: EXPRESSION
        if ":" in line:
            parts = line.split(":", 1)
            name = parts[0].strip().replace("FactorName", "gen_").replace("因子", "gen_")
            expr = parts[1].strip()
            if name and expr and len(name) <= 40 and len(expr) <= 200:
                candidates.append({"name": name, "expression": expr, "hypothesis": f"LLM 生成: {expr[:60]}"})

    return candidates[:10]

def register_candidate(candidate: dict) -> bool:
    """将候选因子注册到 factor_base.py"""
    from factor_lab.factor_base import REGISTRY, register
    
    name = candidate["name"].replace(" ", "_")
    expr = candidate["expression"]
    
    # 注册到全局注册表
    def dyn_factor(df, _expr=expr):
        try:
            return df.eval(_expr)
        except Exception:
                    pass  # non-critical evolution step
    
    REGISTRY.append({
        "name": name,
        "category": "evolved",
        "func": dyn_factor,
        "params": {},
        "description": candidate.get("hypothesis", "LLM 生成因子"),
    })
    return True


# ═══════════════════════════════════════════════════════════════════
# V4.6: 失败归因模块 — 因子淘汰时自动记录失败原因 + 试验计数
# ═══════════════════════════════════════════════════════════════════


def record_factor_failure(
    factor_name: str,
    reason: str,
    alpha_id: str = "",
    expression: str = "",
    hypothesis: str = "",
    market_regime: str = "",
    trial_count: int = 1,
) -> dict:
    """记录因子失败到 FailureDatabase 和 AlphaRegistry

    Args:
        factor_name: 因子名
        reason: 失败原因 (如 "ic_decay", "not_beat_peer", "overfit", "placebo_fail")
        alpha_id: Alpha Registry ID (可选)
        expression: 因子表达式
        hypothesis: 因子假设
        market_regime: 市场环境
        trial_count: 尝试次数

    Returns:
        dict: 记录结果
    """
    result = {"recorded": False, "failure_id": ""}

    # 1. 写入 FailureDatabase
    try:
        from factor_lab.alpha.failure_db import FailureDatabase, FailureRecord

        db = FailureDatabase()
        record = FailureRecord(
            factor_name=factor_name,
            expression=expression,
            hypothesis=hypothesis,
            rejection_reason=reason,
            market_regime=market_regime or "",
            created_by="evolution_v46",
            alpha_id=alpha_id,
            details={
                "trial_count": trial_count,
                "recorded_at": datetime.now(CST).isoformat(),
                "source": "evolution.py",
            },
        )
        failure_id = db.record_failure(record)
        result["failure_id"] = failure_id
        result["recorded"] = True
    except Exception as e:
        result["error"] = f"FailureDatabase 写入失败: {e}"

    # 2. 更新 AlphaRegistry 中的 trial_count 和 failure_reason
    if alpha_id:
        try:
            from factor_lab.alpha.registry import AlphaRegistry, REGISTRY_ROOT
            from pathlib import Path

            alpha_dir = REGISTRY_ROOT / alpha_id
            spec_path = alpha_dir / "alpha_spec.json"
            if spec_path.exists():
                spec = json.loads(spec_path.read_text())
                spec["trial_count"] = spec.get("trial_count", 0) + trial_count
                spec["failure_reason"] = reason
                spec["failure_recorded_at"] = datetime.now(CST).isoformat()
                spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
                result["registry_updated"] = True
        except Exception as e:
            result["registry_error"] = str(e)

    return result


def increment_trial_count(alpha_id: str) -> int:
    """增加 Alpha 的试验计数

    Args:
        alpha_id: Alpha Registry ID

    Returns:
        int: 更新后的 trial_count
    """
    try:
        from factor_lab.alpha.registry import REGISTRY_ROOT

        alpha_dir = REGISTRY_ROOT / alpha_id
        spec_path = alpha_dir / "alpha_spec.json"
        if spec_path.exists():
            spec = json.loads(spec_path.read_text())
            spec["trial_count"] = spec.get("trial_count", 0) + 1
            spec["updated_at"] = datetime.now(CST).isoformat()
            spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
            return spec["trial_count"]
    except Exception:
        pass
    return 0


def set_parent_factor_id(alpha_id: str, parent_id: str) -> bool:
    """设置 Alpha 的父代因子 ID（演化来源）

    Args:
        alpha_id: 当前 Alpha ID
        parent_id: 父代 Alpha ID

    Returns:
        bool: 是否成功
    """
    try:
        from factor_lab.alpha.registry import REGISTRY_ROOT

        alpha_dir = REGISTRY_ROOT / alpha_id
        spec_path = alpha_dir / "alpha_spec.json"
        if spec_path.exists():
            spec = json.loads(spec_path.read_text())
            spec["parent_factor_id"] = parent_id
            spec["trial_count"] = spec.get("trial_count", 0) + 1
            spec["updated_at"] = datetime.now(CST).isoformat()
            spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
            return True
    except Exception:
        pass
    return False


def set_next_iteration_suggestion(alpha_id: str, suggestion: str) -> bool:
    """设置 Alpha 的下一代建议

    Args:
        alpha_id: Alpha Registry ID
        suggestion: 下一代改进建议

    Returns:
        bool: 是否成功
    """
    try:
        from factor_lab.alpha.registry import REGISTRY_ROOT

        alpha_dir = REGISTRY_ROOT / alpha_id
        spec_path = alpha_dir / "alpha_spec.json"
        if spec_path.exists():
            spec = json.loads(spec_path.read_text())
            spec["next_iteration_suggestion"] = suggestion
            spec["updated_at"] = datetime.now(CST).isoformat()
            spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
            return True
    except Exception:
        pass
    return False


def _get_failure_context_for_llm(n: int = 10) -> str:
    """获取失败归因上下文，用于 LLM prompt 嵌入

    Args:
        n: 最近的失败记录数

    Returns:
        str: 格式化后的失败模式文本
    """
    try:
        from factor_lab.alpha.failure_db import FailureDatabase

        db = FailureDatabase()
        recent = db.get_recent_failures(n)
        summary = db.get_summary()
    except Exception:
        return "（暂无失败记录）"

    if not recent:
        return "（暂无失败记录）"

    lines = []
    lines.append(f"最近 {len(recent)} 个被淘汰的因子（避免重复同样的错误）:")
    lines.append("")
    for i, f in enumerate(recent, 1):
        name = (f.get("factor_name", "?") or "?")[:20]
        reason = f.get("rejection_reason", "?") or "?"
        regime = f.get("market_regime", "?") or "?"
        lines.append(f"  {i}. {name} — 原因: {reason}, 市场: {regime}")

    # 统计最常见失败原因
    by_reason = summary.get("by_reason", {})
    total = summary.get("total_failures", 0)
    if by_reason and total > 0:
        most_common = max(by_reason, key=by_reason.get)
        pct = by_reason[most_common] / total * 100
        lines.append("")
        lines.append(f"提示: '{most_common}' 是最常见的失败原因 ({pct:.0f}%)，新因子应避免同类问题。")
    else:
        lines.append("")
        lines.append("提示: 关注因子多样性，避免市场环境依赖。")

    return "\n".join(lines)


def audit_evolution_run(candidates_count: int, accepted_count: int, rejected_count: int) -> dict:
    """生成进化运行审计日志

    Args:
        candidates_count: 候选总数
        accepted_count: 通过数
        rejected_count: 拒绝数

    Returns:
        dict: 审计记录
    """
    record = {
        "timestamp": datetime.now(CST).isoformat(),
        "module": "evolution_v46",
        "candidates_count": candidates_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "acceptance_rate": f"{accepted_count / max(candidates_count, 1) * 100:.1f}%",
    }

    # 写入审计日志
    try:
        log_dir = Path("/mnt/d/HermesReports/evolution_v46")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "evolution_audit.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return record


if __name__ == "__main__":
    import pandas as pd
    from factor_lab.pipeline import run_mining
    
    # 跑一次现有因子
    r = run_mining()
    candidates = generate_candidates(r["top_factors"])
    print(f"LLM 生成 {len(candidates)} 个候选因子:")
    for c in candidates:
        print(f"  {c['name']}")
        print(f"    表达式: {c['expression']}")
        print(f"    假设: {c['hypothesis']}")
        register_candidate(c)
    
    # 重新跑包含新因子
    r2 = run_mining()
    print(f"\n包含新因子的结果:")
    for f in r2["top_factors"]:
        if f["category"] == "evolved":
            print(f"  {f['name']}: IC={f.get('mean_ic',0):+.4f}")