"""自动因子挖掘管线 — 编排器

入口：PipelineOrchestrator.run()
  1. 加载因子候选（注册表 + 进化候选）
  2. 去重（跳过 7 天内验证过的）
  3. 调用 factor_engine.compute_all → IC
  4. 按 IC 分级写入队列
"""
from __future__ import annotations
import json
import sys
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

CST = timezone(timedelta(hours=8))

# 确保 commands/ 在 path 中
_SCRIPT_DIR = Path(__file__).parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from factor_lab.pipeline_config import PipelineConfig
from factor_lab.pipeline_retry import run_with_retry

# ─── lazy 导入（避免循环依赖） ────────────────────────


def _import_engine():
    from factor_lab.factor_engine import load_stock_kline, compute_all
    return load_stock_kline, compute_all


def _import_base():
    from factor_lab.factor_base import REGISTRY, _load_evolved, list_factors
    return REGISTRY, _load_evolved, list_factors


# ─────────────────────────────────────────────────────


@dataclass
class FactorMeta:
    """单个因子元信息"""
    name: str
    expression: str
    category: str
    source: str  # "registry" | "evolved"
    last_validated: Optional[str] = None
    holding_period: int = 5  # 持仓周期（交易日）


class FactorPipelineOrchestrator:
    """因子管线编排器"""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.cfg = config or PipelineConfig()
        self.queue_dirs = self.cfg.queue_subdirs()

    # ── 公开入口 ────────────────────────────────────

    def run(self) -> dict:
        """执行完整管线编排

        Returns:
            {
                "status": "ok" | "partial" | "failed",
                "n_candidates": int,
                "n_skipped": int,
                "n_queued_quick": int,
                "n_queued_full": int,
                "error": str | None,
            }
        """
        print(f"📊 自动因子管线启动 @ {datetime.now(CST):%Y-%m-%d %H:%M:%S}")
        print(f"   队列目录: {self.cfg.QUEUE_DIR}")

        # 1. 加载候选
        candidates = self.load_candidates()
        if not candidates:
            print("   ⚠️ 无因子候选，跳过")
            return {"status": "ok", "n_candidates": 0, "n_skipped": 0,
                    "n_queued_quick": 0, "n_queued_full": 0}

        print(f"   候选因子: {len(candidates)} 个")

        # 2. 去重
        candidates = self.deduplicate(candidates)
        print(f"   去重后: {len(candidates)} 个（最近 7 天验证过的已跳过）")
        if not candidates:
            return {"status": "ok", "n_candidates": 0, "n_skipped": len(candidates),
                    "n_queued_quick": 0, "n_queued_full": 0}

        # 3. IC 评估
        ic_results = self.evaluate_ic(candidates)
        if not ic_results:
            return {"status": "failed", "error": "IC 评估无有效结果",
                    "n_candidates": len(candidates), "n_skipped": 0,
                    "n_queued_quick": 0, "n_queued_full": 0}

        # 4. 分级入队
        stats = self.classify_and_enqueue(ic_results)

        print(f"\n✅ 编排完成: 快速回测 {stats['n_queued_quick']}, "
              f"完整验证 {stats['n_queued_full']}, 跳过 {stats['n_skipped']}")
        return {"status": "ok", **stats}

    # ── 候选加载 ────────────────────────────────────

    def load_candidates(self) -> list[FactorMeta]:
        """加载因子候选：注册表 + 进化候选"""
        REGISTRY, _load_evolved, list_factors = _import_base()
        _load_evolved()

        candidates: list[FactorMeta] = []

        # 注册表因子
        for f in REGISTRY:
            expr = f.get("expression", f["name"])
            candidates.append(FactorMeta(
                name=f["name"],
                expression=expr,
                category=f.get("category", "unknown"),
                source="registry",
            ))

        return candidates

    # ── 去重 ────────────────────────────────────────

    def deduplicate(self, candidates: list[FactorMeta]) -> list[FactorMeta]:
        """跳过最近 7 天内验证过的因子

        基于 Alpha Registry 的 last_validated 字段，
        或 pipeline_results 目录中的上次运行记录。
        """
        # 检查最近的结果目录
        recent = set()
        if self.cfg.RESULT_DIR.exists():
            for d in self.cfg.RESULT_DIR.iterdir():
                if d.is_dir():
                    meta_file = d / "factor_meta.json"
                    if meta_file.exists():
                        try:
                            meta = json.loads(meta_file.read_text())
                            name = meta.get("name", "")
                            validated = meta.get("validated_at", "")
                            if name and validated:
                                vdate = datetime.fromisoformat(validated)
                                age_days = (datetime.now(CST) - vdate).days
                                if age_days < self.cfg.REVALIDATE_DAYS:
                                    recent.add(name)
                        except Exception:
                            continue

        # 保留未在 recent 中的
        result = [c for c in candidates if c.name not in recent]
        # 相同名称的只保留第一个（注册表优先）
        seen = set()
        unique = []
        for c in result:
            if c.name not in seen:
                seen.add(c.name)
                unique.append(c)
        return unique

    # ── IC 评估 ─────────────────────────────────────

    def evaluate_ic(
        self, candidates: list[FactorMeta]
    ) -> list[dict]:
        """加载行情数据 → 计算所有因子 → 提取 IC

        返回按 |IC| 降序排列的列表：
            [{name, expression, ic_mean, ic_ir, grade, score, status}]
        """
        load_stock_kline, compute_all = _import_engine()

        # 加载数据（用分段验证的训练窗口）
        symbols = self._load_universe()
        if not symbols:
            print("  ❌ 无法加载股票池")
            return []

        kline_df = load_stock_kline(
            symbols,
            start_date=self.cfg.TRAIN_START,
            end_date=self.cfg.TRAIN_END,
        )
        if kline_df is None or len(kline_df) < 100:
            print(f"  ❌ 行情数据不足: {len(kline_df) if kline_df is not None else 0}")
            return []

        # 计算所有因子
        out_df = compute_all(kline_df)

        # 补全 ret1（compute_all 不保证输出）
        if "ret1" not in out_df.columns and "close" in out_df.columns:
            out_df["ret1"] = out_df.groupby("symbol")["close"].transform(
                lambda x: x.pct_change(1)
            ).fillna(0)

        # 提取 IC（通过 ic_analyzer）
        from factor_lab.ic_analyzer import calc_daily_ic, calc_rankic_ir

        results = []
        for c in candidates:
            col = c.name
            if col not in out_df.columns:
                continue
            factor_col = out_df[["date", "symbol", col, "ret1"]].dropna()
            if len(factor_col) < 50:
                continue
            try:
                ic_df = calc_daily_ic(factor_col, col)
                if ic_df.empty:
                    continue
                metrics = calc_rankic_ir(ic_df)
                ic_mean = metrics["mean_ic"]
                ic_ir = metrics["ir"]

                # 简略评分
                abs_ic = abs(ic_mean)
                if abs_ic > 0.05:
                    score = 80
                    grade = "A"
                elif abs_ic > 0.03:
                    score = 60
                    grade = "B"
                elif abs_ic > 0.015:
                    score = 40
                    grade = "C"
                else:
                    score = max(abs_ic / 0.015 * 40, 0)
                    grade = "D"

                results.append({
                    "name": c.name,
                    "expression": c.expression,
                    "ic_mean": round(ic_mean, 4),
                    "ic_ir": round(ic_ir, 4),
                    "score": round(score, 1),
                    "grade": grade,
                    "abs_ic": abs_ic,
                    "holding_period": getattr(c, "holding_period", 5),
                })
            except Exception as e:
                print(f"  ⚠️ {c.name}: IC 计算失败 — {e}")
                continue

        results.sort(key=lambda r: r["abs_ic"], reverse=True)
        return results

    # ── 分级入队 ────────────────────────────────────

    def classify_and_enqueue(self, ic_results: list[dict]) -> dict:
        """按 IC 分级，写入任务队列"""
        n_quick = 0
        n_full = 0
        n_skipped = 0

        for r in ic_results:
            abs_ic = r["abs_ic"]
            task = {
                "name": r["name"],
                "expression": r["expression"],
                "ic_mean": r["ic_mean"],
                "ic_ir": r["ic_ir"],
                "score": r["score"],
                "grade": r["grade"],
                "holding_period": r.get("holding_period", 5),
                "created_at": datetime.now(CST).isoformat(),
                "retry_count": 0,
                "status": "pending",
            }

            if abs_ic >= self.cfg.IC_THRESHOLD_FULL:
                dest = self.queue_dirs["complete_validation"]
                n_full += 1
            elif abs_ic >= self.cfg.IC_THRESHOLD_QUICK:
                dest = self.queue_dirs["quick_backtest"]
                n_quick += 1
            else:
                # 跳过 — 写入日志
                skip_path = self.queue_dirs["completed"] / f"{r['name']}_skipped.json"
                skip_path.write_text(json.dumps(task, ensure_ascii=False, indent=2))
                n_skipped += 1
                continue

            task_path = dest / f"{r['name']}.json"
            task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2))
            print(f"  📥 {r['name']}: |IC|={abs_ic:.4f} → {dest.name}")

        return {
            "n_queued_quick": n_quick,
            "n_queued_full": n_full,
            "n_skipped": n_skipped,
        }

    # ── 辅助 ────────────────────────────────────────

    def _load_universe(self) -> list[str]:
        """加载股票池"""
        from strategy_lab.universe import build

        pool: set[str] = set()
        for u_name in self.cfg.UNIVERSE_NAMES or [
            "manual_watchlist", "today_candidates"
        ]:
            try:
                stocks, meta = build(u_name)
                for s in stocks:
                    pool.add(s["symbol"])
            except Exception:
                continue

        if not pool:
            # 回退
            pool = {"000001.SZ", "000002.SZ", "000858.SZ",
                    "600519.SH", "000333.SZ"}
        return sorted(pool)


# ─── CLI 入口 ────────────────────────────────────────


def cmd_pipeline_info() -> str:
    """查看管线状态"""
    cfg = PipelineConfig()
    lines = [
        "📊 自动因子管线状态",
        f"  队列目录: {cfg.QUEUE_DIR}",
        f"  IC 阈值: 完整 ≥{cfg.IC_THRESHOLD_FULL} / 快速 ≥{cfg.IC_THRESHOLD_QUICK}",
        f"  注册条件: Sharpe≥{cfg.SHARPE_MIN}, MaxDD≤{cfg.MAX_DD_MAX:.0%}",
        f"  重试次数: {cfg.RETRY_MAX}",
        f"  去重窗口: {cfg.REVALIDATE_DAYS} 天",
    ]
    for name, d in cfg.queue_subdirs().items():
        n = len(list(d.glob("*.json")))
        lines.append(f"  {name}: {d} ({n} 个任务)")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "info":
        print(cmd_pipeline_info())
    else:
        orch = FactorPipelineOrchestrator()
        result = orch.run()
        print(f"\n结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
