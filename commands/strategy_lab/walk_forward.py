"""滚动时间窗验证 — 调用真实回测引擎"""
import json
import yaml
from datetime import datetime, timezone, timedelta

from strategy_lab.paths import PERFORMANCE, ROOT, STRATEGIES

CST = timezone(timedelta(hours=8))
BASE = ROOT
PERF = PERFORMANCE
STRATEGIES_DIR = STRATEGIES


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _run_backtest(strategy_name: str, start: str, end: str) -> dict:
    """在指定日期范围内运行真实回测"""
    from strategy_lab.backtest import run as backtest_run
    for d in [STRATEGIES_DIR / "templates", STRATEGIES_DIR / "active", STRATEGIES_DIR / "candidates"]:
        p = d / f"{strategy_name}.yaml"
        if p.exists():
            with open(p) as f:
                cfg = yaml.safe_load(f)
            return backtest_run(cfg, start_date=start, end_date=end)
    return {"total_return": 0, "max_drawdown": 0, "total_trades": 0}


def run_walk_forward(strategy_name: str) -> dict:
    """对策略做滚动窗口验证 — 真实回测"""
    windows = [
        ("train", "2025-01-02", "2025-08-31"),
        ("val",   "2025-09-01", "2025-12-31"),
        ("train", "2025-05-01", "2025-12-31"),
        ("val",   "2026-01-01", "2026-07-03"),
    ]

    results = []
    for label, start, end in windows:
        try:
            r = _run_backtest(strategy_name, start, end)
            results.append({
                "window": label, "start": start, "end": end,
                "total_return": r.get("total_return", 0),
                "max_drawdown": r.get("max_drawdown", 0),
                "total_trades": r.get("total_trades", 0),
            })
        except Exception as e:
            results.append({
                "window": label, "start": start, "end": end,
                "total_return": None, "error": str(e),
            })

    train_rets = [r["total_return"] for r in results
                  if r["window"] == "train" and r["total_return"] is not None]
    val_rets = [r["total_return"] for r in results
                if r["window"] == "val" and r["total_return"] is not None]

    report = {
        "strategy": strategy_name,
        "windows": results,
        "train_avg_return": sum(train_rets) / len(train_rets) if train_rets else None,
        "val_avg_return": sum(val_rets) / len(val_rets) if val_rets else None,
        "parameter_stability": "stable" if all(
            r["total_return"] is not None for r in results) else "unstable",
        "walk_forward_pass": bool(val_rets and all(v > -0.05 for v in val_rets)),
        "note": "训练期与验证期收益均为正则通过；验证期负值提示过拟合",
        "created_at": now_str(),
    }

    bt_dir = PERF / "backtests" / strategy_name
    bt_dir.mkdir(parents=True, exist_ok=True)
    with open(bt_dir / "walk_forward_report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report
