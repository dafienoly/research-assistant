"""策略排行与注册表 — Strategy Ranker"""
import csv, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path("/home/ly/.hermes/research-assistant")
PERF = BASE / "performance"
OUTPUT = BASE / "research_outputs"


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def rank_strategies():
    """扫描所有 backtest summary.json，生成策略排行榜"""
    bt_dir = PERF / "backtests"
    if not bt_dir.exists():
        return []

    registry = []
    for strategy_dir in sorted(bt_dir.iterdir()):
        if not strategy_dir.is_dir():
            continue
        summary_file = strategy_dir / "summary.json"
        if not summary_file.exists():
            continue
        with open(summary_file) as f:
            s = json.load(f)

        tr = s.get("total_return", 0) or 0
        dd = s.get("max_drawdown", 0) or 0
        registry.append({
            "strategy_name": strategy_dir.name,
            "version": "0.1.0",
            "universe": s.get("universe", ""),
            "total_return": round(tr, 4),
            "annual_return": round(s.get("annual_return", 0) or 0, 4),
            "max_drawdown": round(dd, 4),
            "sharpe": s.get("sharpe"),
            "calmar": round(tr / dd, 2) if dd else 0,
            "win_rate": s.get("win_rate"),
            "turnover": s.get("turnover"),
            "benchmark_excess_return": None,
            "stability_score": None,
            "overfit_risk": "unknown",
            "production_readiness": "research_only",
            "updated_at": now_str(),
        })

    # 按 total_return 降序排序
    registry.sort(key=lambda x: -x["total_return"])

    # 写 strategy_registry.csv
    PERF.mkdir(parents=True, exist_ok=True)
    fields = ["strategy_name", "version", "universe", "total_return",
              "annual_return", "max_drawdown", "sharpe", "calmar",
              "win_rate", "turnover", "production_readiness", "updated_at"]
    with open(PERF / "strategy_registry.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(registry)

    # 写 strategy_leaderboard.csv (前10名)
    top10 = registry[:10]
    with open(PERF / "strategy_leaderboard.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(top10)

    # 写 risk_dashboard.json
    dashboard = {
        "last_updated": now_str(),
        "total_strategies": len(registry),
        "strategies": registry,
        "warnings": [],
        "paper_trade_candidates": [
            r["strategy_name"] for r in registry
            if r.get("max_drawdown", 1) < 0.10 and r.get("total_return", 0) > 0.05
        ],
    }
    with open(PERF / "strategy_risk_dashboard.json", "w") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    return registry
