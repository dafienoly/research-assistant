"""Core Config V2.14.2 — 统一 ConfigManager"""
import json, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from copy import deepcopy

CST = timezone(timedelta(hours=8))


class ConfigManager:
    def __init__(self):
        self.hash_algo = "sha256"

    def hash_config(self, config: dict) -> str:
        raw = json.dumps(config, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def snapshot(self, config: dict) -> dict:
        return {"config": deepcopy(config), "hash": self.hash_config(config),
                "snapped_at": datetime.now(CST).isoformat()}

    def diff(self, before: dict, after: dict) -> list:
        changes = []
        all_keys = set(before.keys()) | set(after.keys())
        for k in sorted(all_keys):
            if before.get(k) != after.get(k):
                changes.append({"key": k, "before": before.get(k), "after": after.get(k)})
        return changes

    def rollback_patch(self, original: dict) -> dict:
        """生成回滚补丁 (回到 original)"""
        return {"rollback_config": deepcopy(original),
                "rollback_hash": self.hash_config(original)}
