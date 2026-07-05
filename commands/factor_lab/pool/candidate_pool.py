"""候选因子池管理 — 读取 V1.4 排行榜, 管理 promoted/rejected/watchlist

用法:
    from factor_lab.pool.candidate_pool import load_from_leaderboard, CandidatePool
    pool = load_from_leaderboard("/mnt/d/HermesReports/factor_leaderboard/20260704_155707/factor_leaderboard.json")
"""
import json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))


class CandidatePool:
    """候选因子池"""

    def __init__(self, data: dict = None):
        if data is None:
            data = {}
        self.promoted = data.get("promoted_factors", []) if data else []
        self.rejected = data.get("rejected_factors", []) if data else []
        self.watchlist = data.get("watchlist_factors", []) if data else []
        self.all_entries = data.get("entries", []) if data else []
        self.source_run_id = data.get("source_run_id", "")
        self.source_path = data.get("source_path", "")
        self.generated_at = data.get("generated_at", "")

    @property
    def promoted_names(self) -> list:
        return [e["factor_name"] for e in self.promoted]

    @property
    def rejected_names(self) -> list:
        return [e["factor_name"] for e in self.rejected]

    @property
    def all_promoted_pass_gate(self) -> list:
        """仅返回 pass_gate=True 的推荐因子"""
        return [e for e in self.promoted if e.get("pass_gate", False)]

    def to_dict(self) -> dict:
        return {
            "source_run_id": self.source_run_id,
            "source_path": self.source_path,
            "generated_at": self.generated_at or datetime.now(CST).isoformat(),
            "promoted_factors": self.promoted,
            "rejected_factors": self.rejected,
            "watchlist_factors": self.watchlist,
            "entries": self.all_entries,
        }


def load_from_leaderboard(leaderboard_path: str) -> CandidatePool:
    """从 V1.4 factor_leaderboard.json 加载候选池"""
    path = Path(leaderboard_path)
    if not path.exists():
        raise FileNotFoundError(f"排行榜文件不存在: {leaderboard_path}")

    with open(path, "r", encoding="utf-8") as f:
        lb = json.load(f)

    entries = lb.get("entries", [])

    promoted = [
        e for e in entries
        if e.get("pass_gate") and e.get("grade", "D") in ("A", "B")
    ]
    rejected = [
        e for e in entries
        if not (e.get("pass_gate") and e.get("grade", "D") in ("A", "B"))
    ]

    pool = CandidatePool()
    pool.promoted = promoted
    pool.rejected = rejected
    pool.all_entries = entries
    pool.source_run_id = lb.get("generated_at", "")
    pool.source_path = str(path.resolve())
    pool.generated_at = lb.get("generated_at", "")

    return pool


def save_candidate_pool(pool: CandidatePool, output_dir: str) -> str:
    """保存候选池到 JSON"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    d = pool.to_dict()
    # 添加时间戳
    d["last_validated_at"] = datetime.now(CST).isoformat()
    d["n_promoted"] = len(pool.promoted)
    d["n_rejected"] = len(pool.rejected)
    d["n_watchlist"] = len(pool.watchlist)

    path = out / "candidate_pool.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return str(path)


def build_composite_descriptions(factor_names: list, method: str) -> str:
    """生成组合因子的人类可读描述"""
    fn = "+".join(factor_names)
    return f"{method}({fn})"
