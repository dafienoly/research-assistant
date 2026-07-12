"""Strategy Lab 入口调度 — 统筹 universe/factor/backtest/signal/package"""

import csv
import json
import yaml
from datetime import datetime, timezone, timedelta

from strategy_lab.paths import OUTPUTS, PERFORMANCE, ROOT, STRATEGIES

CST = timezone(timedelta(hours=8))
BASE = ROOT
STRATEGIES_DIR = STRATEGIES
OUTPUT_DIR = OUTPUTS
PERF_DIR = PERFORMANCE
SIGNALS_DIR = PERF_DIR / "signals"

def now_str():
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def load_strategy(name: str) -> dict:
    """加载策略 YAML 配置"""
    for d in [STRATEGIES_DIR / "templates", STRATEGIES_DIR / "active", STRATEGIES_DIR / "candidates"]:
        p = d / f"{name}.yaml"
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f)
    raise FileNotFoundError(f"策略未找到: {name}")


def list_strategies() -> list[str]:
    """列出所有可用策略"""
    names = set()
    for d in [STRATEGIES_DIR / "templates", STRATEGIES_DIR / "active", STRATEGIES_DIR / "candidates"]:
        if d.exists():
            for f in d.glob("*.yaml"):
                names.add(f.stem)
    return sorted(names)


def init():
    """初始化策略实验室"""
    for d in [STRATEGIES_DIR / d for d in ["templates", "active", "archived", "candidates"]]:
        d.mkdir(parents=True, exist_ok=True)
    for d in [OUTPUT_DIR / d for d in ["universes", "strategy_mining", "strategy_review_material", "backtests"]]:
        d.mkdir(parents=True, exist_ok=True)
    for d in [PERF_DIR / d for d in ["signals", "backtests", "paper_trading"]]:
        d.mkdir(parents=True, exist_ok=True)
    return {"status": "ok", "dirs_created": True}


def mine_candidates() -> list[dict]:
    """生成候选策略清单"""
    candidates = [
        {
            "strategy_name": "semiconductor_trend_following",
            "category": "trend_following",
            "universe": "semiconductor_theme",
            "main_factors": "ret20, ma20_gt_ma60, vol_ratio20, quality_score",
            "hypothesis": "半导体主题在上升趋势中延续动量",
            "risk_controls": "top_n=10, max_weight=0.15, trailing_drawdown",
            "status": "template",
            "created_at": now_str(),
        },
        {
            "strategy_name": "breakout_semiconductor",
            "category": "breakout",
            "universe": "semiconductor_theme",
            "main_factors": "high_20, volume_ratio, ret5",
            "hypothesis": "半导体股放量突破20日高点后延续上涨",
            "risk_controls": "top_n=5, stop_loss=0.05",
            "status": "candidate",
            "created_at": now_str(),
        },
        {
            "strategy_name": "quality_growth_semiconductor",
            "category": "quality_growth",
            "universe": "semiconductor_theme",
            "main_factors": "quality_score, growth_score, roe, eps_growth",
            "hypothesis": "高ROE高增长的半导体股长期跑赢",
            "risk_controls": "diversified=10, quarterly_rebalance",
            "status": "candidate",
            "created_at": now_str(),
        },
    ]
    out_dir = OUTPUT_DIR / "strategy_mining"
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "candidate_strategies.json", "w") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    with open(out_dir / "candidate_strategy_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(candidates[0].keys()))
        w.writeheader()
        w.writerows(candidates)
    return candidates


def run_backtest(strategy_name: str) -> dict:
    """运行单策略回测并保存结果"""
    cfg = load_strategy(strategy_name)
    from strategy_lab.backtest import run as _run
    result = _run(cfg)
    # 写结果
    bt_dir = PERF_DIR / "backtests" / strategy_name
    bt_dir.mkdir(parents=True, exist_ok=True)
    # summary.json
    with open(bt_dir / "summary.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    # 更新 review material 中的 summary
    try:
        review_file = OUTPUT_DIR / "strategy_review_material" / f"{strategy_name}.json"
        if review_file.exists():
            with open(review_file) as f:
                review = json.load(f)
            review["summary"] = {
                "total_return": result.get("total_return"),
                "annual_return": result.get("annual_return"),
                "max_drawdown": result.get("max_drawdown"),
                "sharpe": result.get("sharpe"),
                "win_rate": result.get("win_rate"),
                "turnover": result.get("turnover"),
                "benchmark_excess_return": result.get("benchmark_excess_return"),
            }
            review["data_range"] = result.get("data_range", {"start": "", "end": ""})
            with open(review_file, "w") as f:
                json.dump(review, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return result


def build_latest_signals(strategy_name: str) -> list[dict]:
    """阻断尚未接入规范数据管线的策略信号生成。"""
    load_strategy(strategy_name)
    raise RuntimeError(
        "策略信号生成尚未接入 DataHub 规范数据与正式策略运行器；"
        "为避免产生伪造交易信号，本命令已阻断且不会写入 latest 文件"
    )


def build_review_material(strategy_name: str) -> dict:
    """生成策略评审材料"""
    cfg = load_strategy(strategy_name)
    review = {
        "strategy_name": strategy_name,
        "version": cfg.get("version", "0.1.0"),
        "category": cfg.get("name", ""),
        "universe": cfg.get("universe", {}).get("name", ""),
        "hypothesis": cfg.get("description", ""),
        "summary": {
            "total_return": None, "annual_return": None,
            "max_drawdown": None, "sharpe": None,
            "win_rate": None, "turnover": None,
        },
        "strengths": ["框架就绪，待完整回测数据"],
        "weaknesses": ["尚未跑完整历史回测"],
        "failure_periods": [],
        "best_periods": [],
        "data_limitations": ["部分基本面数据缺少 pub_date"],
        "bias_warnings": ["半导体标签可能存在时点偏差"],
        "production_readiness": "research_only",
        "codex_questions": [
            "是否需要与盘前推荐做交集验证？",
            "是否需要加入基本面过滤？",
        ],
    }
    out_dir = OUTPUT_DIR / "strategy_review_material"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"{strategy_name}.json", "w") as f:
        json.dump(review, f, ensure_ascii=False, indent=2)
    return review
