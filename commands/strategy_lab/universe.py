"""通用股票池构建器 (Universe Builder)

从 data hub 和 tags 构建可回测的股票池。
每个 universe 标记 survivorship_bias 和 label_timing_bias。
"""

import csv, json, yaml
from pathlib import Path
from typing import Optional

BASE = Path("/home/ly/.hermes/research-assistant")
DATA_HUB = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub")
WSL_TAGS = BASE / "data" / "tags"

UNIVERSE_DIR = BASE / "research_outputs" / "universes"


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _code_set(rows: list[dict], key: str = "code") -> set[str]:
    return {r[key].strip() for r in rows if r.get(key, "").strip()}


def build_semiconductor_theme() -> tuple[list[dict], dict]:
    """半导体主题池"""
    sources = {}
    codes = set()

    # 半导体链标签
    for f in ["semiconductor_chain_tags.csv", "stock_theme_tags.csv", "industry_chain_tags.csv"]:
        p = WSL_TAGS / f
        rows = _read_csv(p)
        sources[f] = rows
        codes.update(_code_set(rows))

    # Baostock 行业分类
    p = DATA_HUB / "tags" / "stock_industry.csv"
    if p.exists():
        rows = _read_csv(p)
        sources["stock_industry.csv"] = rows
        for r in rows:
            ind = (r.get("industry") or "").lower()
            if any(k in ind for k in ["半导体", "集成电路", "电子"]):
                codes.add(r.get("code", ""))

    # 过滤
    code_list = sorted(codes)
    metadata = {
        "universe_name": "semiconductor_theme",
        "source_files": list(sources.keys()),
        "total_stocks": len(code_list),
        "survivorship_bias_warning": "true — 标签基于当前股票, 已退市/ST/暂停的未排除",
        "label_timing_bias_warning": "true — 概念/产业链标签无历史生效日期",
        "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }
    return [{"symbol": c, "universe": "semiconductor_theme"} for c in code_list], metadata


def build_ai_cpo_pcb_storage() -> tuple[list[dict], dict]:
    """AI / CPO / PCB / 存储 主题池"""
    codes = set()
    theme_data = _read_csv(WSL_TAGS / "stock_theme_tags.csv")
    for r in theme_data:
        theme = (r.get("theme") or "").strip()
        if any(k in theme for k in ["AI", "CPO", "PCB", "存储", "光模块"]):
            c = r.get("code", "").strip()
            if c:
                codes.add(c)
    code_list = sorted(codes)
    metadata = {
        "universe_name": "ai_cpo_pcb_storage",
        "source_files": ["stock_theme_tags.csv"],
        "total_stocks": len(code_list),
        "survivorship_bias_warning": "true",
        "label_timing_bias_warning": "true",
        "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }
    return [{"symbol": c, "universe": "ai_cpo_pcb_storage"} for c in code_list], metadata


def build_manual_watchlist() -> tuple[list[dict], dict]:
    """手动关注池"""
    rows = _read_csv(DATA_HUB / "manual_watchlist.csv")
    codes = _code_set(rows, "symbol") or _code_set(rows, "code")
    return [{"symbol": c, "universe": "manual_watchlist"} for c in sorted(codes)], {
        "universe_name": "manual_watchlist", "total_stocks": len(codes),
        "survivorship_bias_warning": "false",
        "label_timing_bias_warning": "false",
        "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }


def build_today_candidates() -> tuple[list[dict], dict]:
    """今日候选池"""
    rows = _read_csv(DATA_HUB / "today_candidates.csv")
    codes = _code_set(rows, "symbol") or _code_set(rows, "code")
    return [{"symbol": c, "universe": "today_candidates"} for c in sorted(codes)], {
        "universe_name": "today_candidates", "total_stocks": len(codes),
        "survivorship_bias_warning": "false",
        "label_timing_bias_warning": "false",
        "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }


UNIVERSE_BUILDERS = {
    "semiconductor_theme": build_semiconductor_theme,
    "ai_cpo_pcb_storage": build_ai_cpo_pcb_storage,
    "manual_watchlist": build_manual_watchlist,
    "today_candidates": build_today_candidates,
}


def build(name: str) -> tuple[list[dict], dict]:
    """构建指定 universe"""
    builder = UNIVERSE_BUILDERS.get(name)
    if not builder:
        raise ValueError(f"未知 universe: {name}, 可选: {list(UNIVERSE_BUILDERS.keys())}")
    stocks, meta = builder()
    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    # 写 CSV
    csv_path = UNIVERSE_DIR / f"{name}.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "universe", "created_at"])
        for s in stocks:
            w.writerow([s["symbol"], s["universe"], meta["created_at"]])
    # 写 metadata
    meta_path = UNIVERSE_DIR / f"{name}_metadata.json"
    import json
    with open(meta_path, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return stocks, meta


def list_universes() -> list[str]:
    return list(UNIVERSE_BUILDERS.keys())
