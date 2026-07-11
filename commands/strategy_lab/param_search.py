"""参数网格搜索 — 对任意策略做参数稳定性测试"""
import csv
import itertools
import json
from datetime import datetime, timezone, timedelta

from strategy_lab.paths import PERFORMANCE, STRATEGIES

CST = timezone(timedelta(hours=8))
PERF = PERFORMANCE


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


GRID = {
    "breakout_semiconductor": {
        "top_n": [5, 10, 15],
        "ret20_weight": [0.15, 0.20, 0.25],
        "vol_ratio20_weight": [0.15, 0.25, 0.35],
    },
    "semiconductor_trend_following": {
        "top_n": [5, 10, 15],
        "ret20_weight": [0.20, 0.25, 0.30],
        "vol_ratio20_weight": [0.10, 0.15, 0.20],
    },
    "quality_growth_semiconductor": {
        "top_n": [5, 8, 12],
        "ret20_weight": [0.08, 0.10, 0.12],
        "vol_ratio20_weight": [0.08, 0.10, 0.12],
    },
}


def get_default_grid(strategy_name: str) -> dict:
    return GRID.get(strategy_name, {"top_n": [10]})


def run_parameter_grid(strategy_name: str) -> dict:
    """对策略运行参数网格搜索，调用真实回测引擎"""
    from strategy_lab.backtest import run as backtest_run
    import yaml

    for d in [STRATEGIES / "templates", STRATEGIES / "active", STRATEGIES / "candidates"]:
        p = d / f"{strategy_name}.yaml"
        if p.exists():
            with open(p) as f:
                cfg = yaml.safe_load(f)
            break
    else:
        return {"strategy": strategy_name, "error": "config not found"}

    grid = get_default_grid(strategy_name)
    keys = list(grid.keys())
    results = []

    for values in itertools.product(*[grid[k] for k in keys]):
        params = dict(zip(keys, values))
        overrides = {}
        if "top_n" in params:
            overrides["top_n"] = params.pop("top_n")
        overrides.update(params)
        try:
            r = backtest_run(cfg, factor_weight_overrides=overrides)
            results.append({
                **params, **{k: overrides.get(k) for k in overrides},
                "total_return": r.get("total_return", 0),
                "max_drawdown": r.get("max_drawdown", 0),
                "total_trades": r.get("total_trades", 0),
            })
        except Exception as e:
            results.append({**params, "total_return": None, "error": str(e)})

    results.sort(key=lambda x: -(x.get("total_return") or 0))

    # 输出
    bt_dir = PERF / "backtests" / strategy_name
    bt_dir.mkdir(parents=True, exist_ok=True)

    if results and results[0].get("total_return") is not None:
        fields = list(results[0].keys())
        with open(bt_dir / "parameter_grid_results.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(results)

    # 写报告
    best = results[0] if results else {}
    returns = [r.get("total_return") or 0 for r in results if r.get("total_return") is not None]
    report = {
        "strategy": strategy_name,
        "total_combinations": len(results),
        "best_params": {k: best.get(k) for k in keys},
        "best_total_return": best.get("total_return"),
        "best_max_drawdown": best.get("max_drawdown"),
        "return_range": {"min": min(returns), "max": max(returns), "std": (max(returns) - min(returns)) / 2} if returns else {},
        "stability_note": "检查 best_params 是否在 grid 边缘；如果在边缘则需扩展搜索范围",
        "overfit_risk": "low" if len(results) < 30 else "medium",
        "created_at": now_str(),
    }
    with open(bt_dir / "parameter_report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report
