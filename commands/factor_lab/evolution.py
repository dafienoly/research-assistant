"""因子进化引擎 — LLM 驱动的新因子生成"""
import sys, os, json, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path

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
    context = "\n".join([
        f"- {f['name']}: IC={f.get('mean_ic',0):+.4f}, IR={f.get('ir',0):.2f}, 类别={f.get('category','')}"
        for f in top
    ])
    prompt = f"""Based on these A-share factor results, design 3 new alpha factors.

Current factors:
{context}

Output format (one per line, no extra text):
FactorName1: EXPRESSION1
FactorName2: EXPRESSION2
FactorName3: EXPRESSION3

Available operators:
  rank(x)       — cross-sectional percentile rank (0-1)
  zscore(x)     — cross-sectional z-score
  ts_mean(x,w)  — time-series rolling mean over w days
  ts_std(x,w)   — time-series rolling std
  ts_min(x,w)   — time-series rolling min
  ts_max(x,w)   — time-series rolling max
  ts_sum(x,w)   — time-series rolling sum
  ts_rank(x,w)  — time-series rolling rank
  ts_delta(x,w) — x - shift(x, w)
  ts_av_diff(x,w) — x - ts_mean(x, w)
  ts_decay_linear(x,w) — linear decay weighted average
  ts_corr(x,y,w) — rolling correlation
  ema(x,w)      — exponential moving average
  rsi(x,w)      — relative strength index
  sigmoid(x)    — 1/(1+exp(-x))
  where(cond, t, f) — conditional selection
  clip(x,lo,hi) — winsorize

Available data fields: close, open, high, low, volume, amount
Also available: {', '.join(f['name'] for f in top)}

Examples:
  mom_vol: rank(ret5) * rank(vol_ratio60)
  range_pos: (close - ts_min(low,10)) / (ts_max(high,10) - ts_min(low,10))
  rev_vol: rank(reversal5) * rank(vol_ratio60)
  mom_strength: ts_av_diff(close, 20) / ts_std(close, 20)
  vol_trend: rank(ema(volume,5) / ema(volume,20))
"""
    response = _llm_chat(prompt)
    return parse_candidates(response)

def parse_candidates(llm_response: str) -> list:
    """解析 LLM 输出的候选因子（每行一个: 因子名: 表达式）"""
    candidates = []
    for line in llm_response.strip().split("\n"):
        line = line.strip()
        if ":" not in line or line.startswith("```"):
            continue
        parts = line.split(":", 1)
        name = parts[0].strip()
        expr = parts[1].strip()
        # 过滤掉非因子行
        if name.startswith("FactorName") or name.startswith("因子"):
            name = name.replace("FactorName", "gen_").replace("因子", "gen_")
        if not name or not expr:
            continue
        if len(name) > 40 or len(expr) > 200:
            continue
        candidates.append({"name": name, "expression": expr, "hypothesis": f"LLM 生成: {expr[:60]}"})
    return candidates

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