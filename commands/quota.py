"""配额管理器 — Tavily / Firecrawl / AnySearch

每个服务 1000 次/月 ÷ 20 交易日 ≈ 50次/天。
配额文件: data/audit/search_quota.json
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

from config import PATHS, now_str, now_cst, safe_write_json, append_jsonl

CST = timezone(timedelta(hours=8))


class QuotaTracker:
    """请求配额跟踪器"""

    MONTHLY_LIMIT = 1000
    DAILY_SAFE_LIMIT = 45  # 留 10% 余量

    def __init__(self):
        self.path = PATHS["audit"] / "search_quota.json"
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                pass
        return {
            "providers": {},
            "last_reset_month": now_cst().strftime("%Y-%m"),
        }

    def save(self):
        safe_write_json(self.path, self.data)

    def _current_month(self) -> str:
        return now_cst().strftime("%Y-%m")

    def _today(self) -> str:
        return now_cst().strftime("%Y-%m-%d")

    def check(self, provider: str) -> bool:
        """检查是否允许请求。返回 True 允许，False 配额已满跳过。

        规则:
        - 每月总额度 1000
        - 每日限额 45 (留余量)
        - 月初自动重置
        """
        now = now_cst()
        month = now.strftime("%Y-%m")
        today = now.strftime("%Y-%m-%d")

        prov = self.data["providers"].setdefault(provider, {
            "monthly": 0,
            "daily": {},
            "skipped": 0,
        })

        # 月度重置
        if self.data.get("last_reset_month") != month:
            self.data["last_reset_month"] = month
            for p in self.data["providers"]:
                self.data["providers"][p]["monthly"] = 0
                self.data["providers"][p]["daily"] = {}
                self.data["providers"][p]["skipped"] = 0
            prov = self.data["providers"][provider]
            prov["monthly"] = 0
            prov["daily"] = {}
            prov["skipped"] = 0

        # 检查月额度
        if prov["monthly"] >= self.MONTHLY_LIMIT:
            prov["skipped"] = prov.get("skipped", 0) + 1
            self.save()
            return False

        # 检查日额度
        today_used = prov["daily"].get(today, 0)
        if today_used >= self.DAILY_SAFE_LIMIT:
            prov["skipped"] = prov.get("skipped", 0) + 1
            self.save()
            return False

        return True

    def consume(self, provider: str, count: int = 1):
        """消耗配额"""
        today = now_cst().strftime("%Y-%m-%d")
        prov = self.data["providers"].setdefault(provider, {
            "monthly": 0, "daily": {}, "skipped": 0,
        })
        prov["monthly"] += count
        prov["daily"][today] = prov["daily"].get(today, 0) + count
        self.save()

    def status(self) -> dict:
        """返回当前配额状态"""
        return {
            provider: {
                "monthly_used": d.get("monthly", 0),
                "monthly_remaining": self.MONTHLY_LIMIT - d.get("monthly", 0),
                "today_used": d.get("daily", {}).get(self._today(), 0),
                "daily_remaining": self.DAILY_SAFE_LIMIT - d.get("daily", {}).get(self._today(), 0),
                "skipped": d.get("skipped", 0),
            }
            for provider, d in self.data["providers"].items()
        }


# 单例
_quota = None

def get_quota() -> QuotaTracker:
    global _quota
    if _quota is None:
        _quota = QuotaTracker()
    return _quota


def quota_check(provider: str) -> bool:
    """快捷检查+自动记录配额消耗"""
    q = get_quota()
    if not q.check(provider):
        return False
    q.consume(provider)
    return True


def quota_consume(provider: str, count: int = 1):
    get_quota().consume(provider, count)


# CLI 测试
if __name__ == "__main__":
    q = get_quota()
    print("=== 当前配额状态 ===")
    for prov, s in q.status().items():
        bar_month = "█" * min(s["monthly_used"] // 10, 20)
        bar_day = "█" * min(s["today_used"], 20)
        print(f'{prov:12s} 月:{s["monthly_used"]:4d}/{q.MONTHLY_LIMIT} {bar_month}')
        print(f'{"":12s} 日:{s["today_used"]:2d}/{q.DAILY_SAFE_LIMIT} {bar_day} 跳过:{s["skipped"]}')
