"""Minute Bar Storage V5.3 — 分钟线数据存储"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
MINUTE_DIR = Path("/mnt/d/HermesData/minute_bars")
MINUTE_DIR.mkdir(parents=True, exist_ok=True)


def store_minute_bars(symbol: str, date_str: str, bars: list[dict]):
    """存储分钟线数据"""
    path = MINUTE_DIR / symbol / f"{date_str}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"symbol": symbol, "date": date_str, "bars": bars,
                                 "count": len(bars), "stored_at": datetime.now(CST).isoformat()},
                                indent=2))
    return len(bars)


def load_minute_bars(symbol: str, date_str: str) -> list[dict]:
    """读取分钟线数据"""
    path = MINUTE_DIR / symbol / f"{date_str}.json"
    if path.exists():
        data = json.loads(path.read_text())
        return data.get("bars", [])
    return []


def list_available_dates(symbol: str) -> list[str]:
    """列出该股票有分钟线数据的日期"""
    path = MINUTE_DIR / symbol
    if path.exists():
        return sorted([f.stem for f in path.glob("*.json")], reverse=True)
    return []
