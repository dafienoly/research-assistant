"""分阶段市场环境评估 — 按时间窗口 + SSE 指数收益分类"""
import csv, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
KLINE_DIR = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")
PERF = Path("/home/ly/.hermes/research-assistant") / "performance"


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _sse_return(start: str, end: str) -> float | None:
    """计算 SSE 指数区间收益"""
    f = KLINE_DIR / "000001.csv"
    if not f.exists():
        return None
    prices = []
    with open(f, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            d = row.get("date", "")
            if start <= d <= end:
                prices.append(float(row.get("close", 0) or 0))
    if len(prices) >= 2:
        return (prices[-1] - prices[0]) / prices[0]
    return None


PERIODS = [
    ("2020-01-02", "2021-12-31", "2020-2021"),
    ("2022-01-01", "2022-12-31", "2022"),
    ("2023-01-01", "2023-12-31", "2023"),
    ("2024-01-01", "2024-12-31", "2024"),
    ("2025-01-01", "2025-12-31", "2025"),
    ("2026-01-01", "2026-07-03", "2026"),
]


def analyze_regime(strategy_name: str, backtest_fn) -> list[dict]:
    """分析策略在不同市场阶段的表现"""
    results = []
    for start, end, label in PERIODS:
        sse_ret = _sse_return(start, end)
        regime = "bull" if sse_ret and sse_ret > 0.10 else "bear" if sse_ret and sse_ret < -0.05 else "sideways"
        try:
            r = backtest_fn(start, end)
            results.append({
                "period": label, "start": start, "end": end,
                "strategy_return": r.get("total_return", 0),
                "sse_return": sse_ret,
                "regime": regime,
            })
        except Exception as e:
            results.append({
                "period": label, "start": start, "end": end,
                "strategy_return": None, "error": str(e),
            })

    bt_dir = PERF / "backtests" / strategy_name
    bt_dir.mkdir(parents=True, exist_ok=True)
    with open(bt_dir / "regime_performance.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["period", "start", "end", "strategy_return", "sse_return", "regime"])
        w.writeheader()
        w.writerows(results)

    return results


def dump_all(registry: list[dict]):
    """写合并版 regime 报告到 research_outputs"""
    out = PERF / "regime_performance.csv"
    if registry:
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(registry[0].keys()))
            w.writeheader()
            w.writerows(registry)
