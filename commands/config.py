"""Hermes A股投研助手 — 公共配置

定义路径、环境变量读取、文件操作工具。
"""

import os
import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

# === 时区 ===
CST = timezone(timedelta(hours=8))

def now_cst() -> datetime:
    return datetime.now(CST)

def now_str() -> str:
    return now_cst().strftime("%Y-%m-%dT%H:%M:%S+08:00")

def ts_id() -> str:
    return now_cst().strftime("%Y%m%d_%H%M%S")

def date_id() -> str:
    return now_cst().strftime("%Y-%m-%d")

# === 路径 ===
BASE = Path.home() / ".hermes" / "research-assistant"

PATHS = {
    # 工作目录
    "data": BASE / "data",
    "logs": BASE / "logs",
    "commands": BASE / "commands",
    "docs": BASE / "docs",

    # 市场数据
    "market": BASE / "data" / "market",
    "daily_kline": BASE / "data" / "market" / "daily_kline",
    "minute_kline": BASE / "data" / "market" / "minute_kline_priority",

    # 基本面
    "fundamentals": BASE / "data" / "fundamentals",

    # 事件
    "events": BASE / "data" / "events",

    # 标签
    "tags": BASE / "data" / "tags",

    # 盘中
    "intraday": BASE / "data" / "intraday",
    "audit": BASE / "data" / "audit",
}

# === Windows 发布目录 ===
INCOMING = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/incoming_from_hermes")

# === 只读 Windows 文件 ===
CODEX_DATA = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub")

CODEX_READ_ONLY = {
    "positions": CODEX_DATA / "portfolio" / "positions.csv",
    "recommendation_history": CODEX_DATA / "performance" / "recommendation_history.csv",
    "stock_theme_tags": CODEX_DATA / "tags" / "stock_theme_tags.csv",
    "semiconductor_chain_tags": CODEX_DATA / "tags" / "semiconductor_chain_tags.csv",
    "watchlist": CODEX_DATA / "manual_watchlist.csv",
    "today_candidates": CODEX_DATA / "today_candidates.csv",
}

# === 环境变量 ===
ENV = {
    "WECHAT_WEBHOOK_URL": os.environ.get("WECHAT_WEBHOOK_URL", ""),
    "WECHAT_ENABLED": os.environ.get("WECHAT_ENABLED", "true").lower() == "true",
    "WECHAT_DRY_RUN": os.environ.get("WECHAT_DRY_RUN", "false").lower() != "false",
    "RSSCAST_API_KEY": os.environ.get("RSSCAST_API_KEY", ""),
}


def ensure_dirs():
    """确保所有目录存在"""
    for p in PATHS.values():
        p.mkdir(parents=True, exist_ok=True)
    INCOMING.mkdir(parents=True, exist_ok=True)


def file_sha256(path: Path) -> str:
    """计算文件 sha256"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_rows(path: Path) -> int:
    """估算文件行数"""
    count = 0
    with open(path, "rb") as f:
        for _ in f:
            count += 1
    return count


def safe_write_json(path: Path, data):
    """原子写入 JSON 文件"""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def append_jsonl(path: Path, record: dict):
    """追加 JSONL 记录"""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_csv_safe(path: Path, required=False):
    """安全读取 CSV，返回列表"""
    import csv
    if not path.exists():
        if required:
            return None  # 调用方处理缺失
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []
