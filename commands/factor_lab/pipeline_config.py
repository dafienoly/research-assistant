"""自动因子挖掘管线 — 配置

集中管理所有阈值、路径、超时参数。
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


class PipelineConfig:
    """管线全局配置"""

    # ── IC 分级阈值 ────────────────────────────────────
    IC_THRESHOLD_FULL: float = 0.03     # |IC| ≥ 0.03 → 完整验证
    IC_THRESHOLD_QUICK: float = 0.015   # 0.015 ≤ |IC| < 0.03 → 快速回测
    # |IC| < 0.015 → 跳过

    # ── 注册条件 ────────────────────────────────────────
    SHARPE_MIN: float = 1.0              # 完整验证 Sharpe 最低要求
    MAX_DD_MAX: float = -0.20            # 最大回撤上限（-20%）

    # ── 重试 ────────────────────────────────────────────
    RETRY_MAX: int = 1                   # 每环节最大重试次数
    RETRY_DELAY_SEC: float = 5.0         # 重试间隔

    # ── 影子观察期（交易日） ────────────────────────────
    SHADOW_DAYS_DAILY: int = 10          # 日频因子观察期
    SHADOW_DAYS_WEEKLY: int = 30         # 周频因子观察期（持有期 ≥ 5 日）
    IC_DECAY_THRESHOLD: float = 0.30     # 衰减率 ≥ 30% → 标记不稳定

    # ── 去重 ────────────────────────────────────────────
    REVALIDATE_DAYS: int = 7             # 7 天内不重复验证

    # ── 路径 ────────────────────────────────────────────
    QUEUE_DIR: Path = Path(
        "/mnt/d/HermesReports/pipeline_queue"
    )
    RESULT_DIR: Path = Path(
        "/mnt/d/HermesReports/pipeline_results"
    )
    AUDIT_DIR: Path = Path(
        "/mnt/d/HermesReports/pipeline_audit"
    )

    # ── 时间窗口 ────────────────────────────────────────
    TRAIN_START: str = "2025-01-02"
    TRAIN_END: str = "2025-12-31"
    TEST_START: str = "2026-01-02"
    TEST_END: str = "2026-06-30"

    # ── 股票池 ──────────────────────────────────────────
    UNIVERSE_NAMES: list[str] = None  # None = 使用默认 (manual_watchlist + today_candidates)

    @classmethod
    def queue_subdirs(cls) -> dict[str, Path]:
        """创建并返回队列子目录"""
        dirs = {
            "incoming": cls.QUEUE_DIR / "incoming",
            "quick_backtest": cls.QUEUE_DIR / "quick_backtest",
            "complete_validation": cls.QUEUE_DIR / "complete_validation",
            "completed": cls.QUEUE_DIR / "completed",
            "failed": cls.QUEUE_DIR / "failed",
        }
        for d in dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        return dirs
