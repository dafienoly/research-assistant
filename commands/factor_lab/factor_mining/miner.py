"""Factor Mining Engine — 因子挖掘引擎主模块

编排完整因子挖掘流程:
  1. 分析已有因子注册表
  2. 生成候选因子
  3. 快速评估候选因子 (IC/ICIR/分层)
  4. 展示并推荐 Top 候选
  5. 支持将优质因子注册到正式注册表
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from factor_lab.factor_mining.candidate_generator import (
    FactorCandidate,
    CandidateGenerator,
    WindowVariationGenerator,
    CrossSectionalGenerator,
    CombinationGenerator,
)
from factor_lab.factor_mining.evaluator import (
    CandidateEvaluator,
    EvaluationResult,
    quick_evaluate,
)


CST = timezone(timedelta(hours=8))


@dataclass
class MiningConfig:
    """挖掘配置

    Attributes:
        top_n: 最终推荐 Top-N 数量
        max_candidates: 最大候选数量
        include_window: 是否包含窗口变体
        include_cross_sectional: 是否包含横截面变体
        include_combinations: 是否包含组合变体
        max_combinations: 组合最大数量
        min_ic_dates: 最小 IC 有效天数
        evaluate_parallel: 是否并行评估
    """
    top_n: int = 10
    max_candidates: int = 100
    include_window: bool = True
    include_cross_sectional: bool = True
    include_combinations: bool = True
    max_combinations: int = 20
    min_ic_dates: int = 5
    evaluate_parallel: bool = False


@dataclass
class MiningReport:
    """挖掘报告

    Attributes:
        timestamp: 挖掘时间
        config: 挖掘配置
        existing_factor_count: 已有因子数量
        candidates_generated: 生成的候选数量
        candidates_evaluated: 成功评估的数量
        top_candidates: Top-N 候选评估结果
        registry_summary: 已有因子分类统计
        candidate_summary: 候选因子分类统计
        duration_ms: 挖掘耗时 (毫秒)
    """
    timestamp: str = ""
    config: dict = field(default_factory=dict)
    existing_factor_count: int = 0
    candidates_generated: int = 0
    candidates_evaluated: int = 0
    top_candidates: list[dict] = field(default_factory=list)
    registry_summary: dict = field(default_factory=dict)
    candidate_summary: dict = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def print_summary(self):
        """打印可读摘要"""
        print(f"\n{'='*60}")
        print(f"  🔬 因子挖掘报告")
        print(f"  {self.timestamp}")
        print(f"{'='*60}")
        print(f"  已有因子: {self.existing_factor_count}")
        print(f"  已生成候选: {self.candidates_generated}")
        print(f"  成功评估: {self.candidates_evaluated}")
        print(f"  耗时: {self.duration_ms:.0f}ms")
        print()

        if self.registry_summary:
            print("  已有因子分类:")
            for cat, cnt in sorted(self.registry_summary.items()):
                print(f"    {cat}: {cnt}")

        if self.candidate_summary:
            print("\n  候选因子分类:")
            for cat, cnt in sorted(self.candidate_summary.items()):
                print(f"    {cat}: {cnt}")

        print("\n  🏆 Top 候选因子:")
        print(f"  {'排名':>4}  {'名称':<25} {'IC均值':>8} {'ICIR':>6} {'多空差':>8} {'评分':>6}")
        print(f"  {'-'*4}  {'-'*25} {'-'*8} {'-'*6} {'-'*8} {'-'*6}")
        for i, cand in enumerate(self.top_candidates[:10], 1):
            info = cand.get("candidate", {})
            print(f"  {i:>4}  {info.get('name', '?'):<25} "
                  f"{cand.get('ic_mean', 0):>8.4f} "
                  f"{cand.get('ic_ir', 0):>6.2f} "
                  f"{cand.get('spread_ret', 0):>8.4f} "
                  f"{cand.get('score', 0):>6.2f}")
        print()


# ═══════════════════════════════════════════════════════════════════
# FactorMiningEngine — 主要挖掘引擎
# ═══════════════════════════════════════════════════════════════════


class FactorMiningEngine:
    """因子挖掘引擎 — 编排完整挖掘流程

    用法:
        engine = FactorMiningEngine()

        # 从已有因子注册表挖掘
        report = engine.mine(df=kline_df)

        # 查看 Top-10 候选
        report.print_summary()

        # 将 Top 候选注册到因子注册表
        engine.register_top_candidates(report, top_n=5)
    """

    def __init__(
        self,
        config: MiningConfig | None = None,
        registry: list[dict] | None = None,
    ):
        """初始化挖掘引擎

        Args:
            config: 挖掘配置 (默认值)
            registry: 已有因子注册表列表 (默认从 factor_base 自动加载)
        """
        self.config = config or MiningConfig()
        self.registry = registry or self._load_registry()

    # ─── Public API ────────────────────────────────────────────────

    def mine(self, df: pd.DataFrame, ret_col: str = "ret1") -> MiningReport:
        """执行完整因子挖掘流程

        Args:
            df: K线数据 (含 date, symbol, close 列)
            ret_col: 下期收益列名

        Returns:
            MiningReport 挖掘报告
        """
        import time
        start = time.monotonic()

        report = MiningReport(
            timestamp=datetime.now(CST).isoformat(),
            config=asdict(self.config),
            existing_factor_count=len(self.registry),
            registry_summary=self._count_by_category(self.registry),
        )

        # 1. 生成候选
        candidates = self._generate_candidates()
        report.candidates_generated = len(candidates)

        if not candidates:
            report.duration_ms = round((time.monotonic() - start) * 1000, 1)
            return report

        # 2. 评估候选
        evaluator = CandidateEvaluator()
        results = evaluator.evaluate(
            df, candidates,
            ret_col=ret_col,
            min_dates=self.config.min_ic_dates,
        )

        # 3. 统计
        ok_results = [r for r in results if r.status == "ok"]
        report.candidates_evaluated = len(ok_results)

        # 4. 候选分类统计
        report.candidate_summary = self._count_candidate_categories(results)

        # 5. 提取 Top-N
        top_results = ok_results[:self.config.top_n]
        report.top_candidates = [r.to_dict() for r in top_results]

        report.duration_ms = round((time.monotonic() - start) * 1000, 1)
        return report

    def register_top_candidates(
        self,
        report: MiningReport,
        top_n: int = 5,
        confirm: bool = False,
    ) -> list[str]:
        """将评估通过的候选注册到因子注册表

        Args:
            report: MiningReport (来自 mine())
            top_n: 注册前 N 个
            confirm: 是否需要人工确认 (True 则只输出不注册)

        Returns:
            已注册的因子名称列表
        """
        registered: list[str] = []
        candidates_to_register = report.top_candidates[:top_n]

        for cand_result in candidates_to_register:
            cand_dict = cand_result.get("candidate", {})
            name = cand_dict.get("name", "")

            if not name:
                continue

            if confirm:
                print(f"  ⏸️  [待确认] {name} — IC={cand_result.get('ic_mean', 0):.4f}")
                continue

            # 检查是否已存在
            existing_names = {f.get("name") for f in self.registry}
            if name in existing_names:
                print(f"  ⏭️  {name} 已存在，跳过")
                continue

            # 注册
            try:
                self._do_register(cand_result)
                registered.append(name)
                print(f"  ✅ {name} 已注册")
            except Exception as e:
                print(f"  ❌ {name} 注册失败: {e}")

        return registered

    # ─── Internal ──────────────────────────────────────────────────

    def _load_registry(self) -> list[dict]:
        """从 factor_base 加载因子注册表"""
        try:
            from factor_lab.factor_base import list_factors
            return list_factors()
        except Exception:
            return []

    def _generate_candidates(self) -> list[FactorCandidate]:
        """生成候选因子"""
        gen = CandidateGenerator(self.registry)
        candidates = gen.generate_all(
            include_window=self.config.include_window,
            include_cross_sectional=self.config.include_cross_sectional,
            include_combinations=self.config.include_combinations,
            max_combinations=self.config.max_combinations,
        )
        # 截断
        if len(candidates) > self.config.max_candidates:
            candidates = candidates[:self.config.max_candidates]
        return candidates

    @staticmethod
    def _count_by_category(items: list[dict]) -> dict:
        """按分类统计"""
        counts: dict[str, int] = {}
        for item in items:
            cat = item.get("category", "uncategorized")
            counts[cat] = counts.get(cat, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _count_candidate_categories(results: list[EvaluationResult]) -> dict:
        """按分类统计候选结果"""
        counts: dict[str, int] = {}
        for r in results:
            if r.status == "ok":
                cat = r.candidate.get("category", "uncategorized")
                counts[cat] = counts.get(cat, 0) + 1
        return dict(sorted(counts.items()))

    def _do_register(self, cand_result: dict):
        """注册一个候选因子到 factor_base 注册表

        实际注册时, 需要将候选转换为 factor_base 的 register 格式。
        这里简化实现: 仅导入 factor_base 并调用 register 装饰器。
        """
        cand_dict = cand_result.get("candidate", {})
        name = cand_dict.get("name", "")
        category = cand_dict.get("category", "others")
        description = cand_dict.get("description", "mined factor")
        params = cand_dict.get("params", {})

        import factor_lab.factor_base as fb

        # 注册新因子
        def register_factor():
            """装饰器方式注册"""
            # 构建因子计算函数
            def compute_func(df, **kwargs):
                # 从注册表中找到同名候选
                gen = CandidateGenerator([])
                all_candidates = gen.generate_all(
                    include_window=True,
                    include_cross_sectional=True,
                    include_combinations=False,
                )
                for c in all_candidates:
                    if c.name == name and c.func is not None:
                        return c.func(df)
                # fallback: 尝试从已有因子中查找
                from factor_lab.factor_base import REGISTRY as _reg
                for f in _reg:
                    if f["name"] == name:
                        return f["func"](df, **kwargs)
                return pd.Series(0.0, index=df.index)

            return compute_func

        func = register_factor()
        fb.REGISTRY.append({
            "name": name,
            "category": category,
            "func": func,
            "params": params,
            "description": description,
        })
