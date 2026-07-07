"""Candidate Generator — 因子候选生成器

提供多种策略生成新的因子候选:
  1. WindowVariationGenerator — 对已有因子模式生成不同窗口参数变体
  2. CrossSectionalGenerator — 生成横截面排名/Z-Score 变体
  3. CombinationGenerator — 生成已有因子的两两组合
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════
# FactorCandidate — 因子候选数据结构
# ═══════════════════════════════════════════════════════════════════


@dataclass
class FactorCandidate:
    """因子候选 — 描述一个待评估的因子定义

    Attributes:
        name: 因子名称 (snake_case)
        category: 因子分类 (momentum / trend / volume / volatility / ...)
        description: 因子描述
        generation_method: 生成方法标识 (window_variation / cross_sectional / combination)
        source: 来源描述 (如 "ret5" 或 "ret5+volume")
        expression: 表达式文本描述
        params: 参数字典
        func: 计算函数, 接收 DataFrame 返回 pd.Series
    """
    name: str
    category: str
    description: str
    generation_method: str
    source: str
    expression: str
    params: dict = field(default_factory=dict)
    func: Optional[Callable] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "generation_method": self.generation_method,
            "source": self.source,
            "expression": self.expression,
            "params": self.params,
        }


# ═══════════════════════════════════════════════════════════════════
# 基础计算工具
# ═══════════════════════════════════════════════════════════════════


def _grouped_rolling(df: pd.DataFrame, col: str, window: int, func: str) -> pd.Series:
    """分组滚动计算"""
    grp = df.groupby("symbol")[col]
    if func == "mean":
        return grp.transform(lambda x: x.rolling(window).mean())
    elif func == "std":
        return grp.transform(lambda x: x.rolling(window).std())
    elif func == "sum":
        return grp.transform(lambda x: x.rolling(window).sum())
    elif func == "max":
        return grp.transform(lambda x: x.rolling(window).max())
    elif func == "min":
        return grp.transform(lambda x: x.rolling(window).min())
    return grp.transform(lambda x: x.rolling(window).mean())


def _grouped_pct_change(df: pd.DataFrame, col: str, periods: int) -> pd.Series:
    """分组百分比变化"""
    return df.groupby("symbol")[col].transform(lambda x: x.pct_change(periods))


def _cross_sectional_rank(df: pd.DataFrame, factor_col: str) -> pd.Series:
    """横截面排名 (每日)"""
    ranks = df.groupby("date")[factor_col].rank(pct=True)
    return ranks


def _cross_sectional_zscore(df: pd.DataFrame, factor_col: str) -> pd.Series:
    """横截面 Z-Score (每日)"""
    def _zscore(g):
        mu = g.mean()
        std = g.std()
        return (g - mu) / std if std > 0 else g * 0

    return df.groupby("date")[factor_col].transform(lambda g: _zscore(g))


def _sector_relative(df: pd.DataFrame, factor_col: str, sector_col: str = "industry") -> pd.Series:
    """行业相对因子: 因子值减去行业中位数"""
    if sector_col not in df.columns:
        return pd.Series(0.0, index=df.index)
    sector_median = df.groupby(["date", sector_col])[factor_col].transform("median")
    return df[factor_col] - sector_median


# ═══════════════════════════════════════════════════════════════════
# WindowVariationGenerator — 窗口参数变体
# ═══════════════════════════════════════════════════════════════════


class WindowVariationGenerator:
    """对常见因子模式生成不同窗口参数的变体

    例如: ret5 → ret3, ret8, ret15
          vol_ratio20 → vol_ratio10, vol_ratio30, vol_ratio40
    """

    # 因子模式定义: (name_template, category, description_template, base_func, param_name)
    PATTERNS = [
        {
            "prefix": "ret",
            "category": "momentum",
            "desc": "{}日收益率动量 (mined)",
            "func": lambda df, w: _grouped_pct_change(df, "close", w),
            "param": "window",
            "windows": [3, 8, 15, 25, 45],
            "existing": {5, 10, 20, 60},
        },
        {
            "prefix": "vol_ratio",
            "category": "volume",
            "desc": "{}日量比 (mined)",
            "func": lambda df, w: (
                df.groupby("symbol")["volume"].transform(
                    lambda x: x / x.rolling(w).mean()
                )
            ),
            "param": "window",
            "windows": [3, 10, 30, 40],
            "existing": {5, 20, 60},
        },
        {
            "prefix": "ret_std",
            "category": "volatility",
            "desc": "{}日收益率波动 (mined)",
            "func": lambda df, w: _grouped_pct_change(df, "close", 1).groupby(
                df["symbol"]
            ).transform(lambda x: x.rolling(w).std()),
            "param": "window",
            "windows": [5, 10, 15, 30],
            "existing": {20},
        },
        {
            "prefix": "ma_gap",
            "category": "trend",
            "desc": "快慢均线比 ({}/{}日) (mined)",
            "func": lambda df, w: (
                df.groupby("symbol")["close"].transform(
                    lambda x: x.rolling(w[0]).mean()
                )
                / df.groupby("symbol")["close"].transform(
                    lambda x: x.rolling(w[1]).mean()
                )
                - 1
            ),
            "param": "fast_slow",
            "windows": [(3, 10), (5, 15), (10, 30), (15, 60)],
            "existing": {(5, 10), (10, 20), (20, 60)},
        },
        {
            "prefix": "close_gt_ma",
            "category": "trend",
            "desc": "收盘价在MA{}上方 (mined)",
            "func": lambda df, w: (
                df["close"]
                / df.groupby("symbol")["close"].transform(
                    lambda x: x.rolling(w).mean()
                )
                - 1
            ),
            "param": "window",
            "windows": [5, 10, 30, 60],
            "existing": {20},
        },
    ]

    def __init__(self, existing_registry: list[dict] | None = None):
        """初始化

        Args:
            existing_registry: 已有因子注册表列表 (每个元素含 name, category 字段)
        """
        self.existing_registry = existing_registry or []

    def generate(self) -> list[FactorCandidate]:
        """生成所有窗口变体候选

        Returns:
            未被已有因子覆盖的候选列表
        """
        existing_names = {
            f["name"] for f in self.existing_registry if isinstance(f, dict)
        }
        candidates: list[FactorCandidate] = []

        for pattern in self.PATTERNS:
            for w in pattern["windows"]:
                if pattern["param"] == "fast_slow":
                    w_tuple = tuple(w)
                    name = f"{pattern['prefix']}_{w[0]}_{w[1]}"
                else:
                    w_tuple = w
                    name = f"{pattern['prefix']}{w}"

                # 跳过已存在的因子
                if name in existing_names:
                    continue

                desc = pattern["desc"].format(
                    *(w if isinstance(w, tuple) else [w])
                )

                # 构建计算函数 (闭包捕获 window)
                if pattern["param"] == "fast_slow":

                    def _make_combo(ws):
                        return lambda df: (
                            df.groupby("symbol")["close"].transform(
                                lambda x: x.rolling(ws[0]).mean()
                            )
                            / df.groupby("symbol")["close"].transform(
                                lambda x: x.rolling(ws[1]).mean()
                            )
                            - 1
                        )

                    func = _make_combo(w)
                else:
                    func = lambda df, ws=w: pattern["func"](df, ws)

                candidates.append(FactorCandidate(
                    name=name,
                    category=pattern["category"],
                    description=desc,
                    generation_method="window_variation",
                    source=f"{pattern['prefix']}*",
                    expression=f"{pattern['prefix']}({w_tuple})",
                    params={pattern["param"]: w_tuple if isinstance(w_tuple, tuple) else w_tuple},
                    func=func,
                ))

        return candidates


# ═══════════════════════════════════════════════════════════════════
# CrossSectionalGenerator — 横截面变体
# ═══════════════════════════════════════════════════════════════════


class CrossSectionalGenerator:
    """在已有因子之上添加横截面排名/Z-Score/行业相对变体"""

    TARGET_CATEGORIES = ["momentum", "volume", "trend", "volatility"]

    def __init__(self, existing_registry: list[dict] | None = None):
        self.existing_registry = existing_registry or []

    def generate(self) -> list[FactorCandidate]:
        """为已有动量/成交量/趋势因子生成横截面变体"""
        existing_names = {
            f["name"] for f in self.existing_registry if isinstance(f, dict)
        }
        candidates: list[FactorCandidate] = []

        for f in self.existing_registry:
            if not isinstance(f, dict):
                continue
            name = f.get("name", "")
            category = f.get("category", "")
            if category not in self.TARGET_CATEGORIES:
                continue
            if name in ["ret1"] or not name:
                continue

            # Rank 变体
            rank_name = f"{name}_rank"
            if rank_name not in existing_names:
                def _make_rank(n):
                    return lambda df: _cross_sectional_rank(df, n)
                candidates.append(FactorCandidate(
                    name=rank_name,
                    category=category,
                    description=f"{name} 横截面排名 (mined)",
                    generation_method="cross_sectional",
                    source=name,
                    expression=f"rank({name})",
                    func=_make_rank(name),
                ))

            # Z-Score 变体
            zscore_name = f"{name}_zscore"
            if zscore_name not in existing_names:
                def _make_zscore(n):
                    return lambda df: _cross_sectional_zscore(df, n)
                candidates.append(FactorCandidate(
                    name=zscore_name,
                    category=category,
                    description=f"{name} 横截面 Z-Score (mined)",
                    generation_method="cross_sectional",
                    source=name,
                    expression=f"zscore({name})",
                    func=_make_zscore(name),
                ))

        return candidates


# ═══════════════════════════════════════════════════════════════════
# CombinationGenerator — 因子组合
# ═══════════════════════════════════════════════════════════════════


class CombinationGenerator:
    """生成已有因子的两两组合

    组合方式: 加法 (A+B), 差值 (A-B), 乘积 (A*B), 比值 (A/B)
    """

    def __init__(self, existing_registry: list[dict] | None = None):
        self.existing_registry = existing_registry or []

    def generate(self, max_combinations: int = 20) -> list[FactorCandidate]:
        """生成两两组合因子候选

        Args:
            max_combinations: 最大生成数

        Returns:
            组合候选列表
        """
        existing_names = {
            f["name"] for f in self.existing_registry if isinstance(f, dict)
        }
        candidates: list[FactorCandidate] = []

        # 挑选适合组合的因子 (排除排名类等已组合的)
        base_names = []
        for f in self.existing_registry:
            if not isinstance(f, dict):
                continue
            n = f.get("name", "")
            if n and not n.endswith("_rank") and not n.endswith("_zscore"):
                base_names.append(n)

        count = 0
        for i, a in enumerate(base_names):
            for b in base_names[i + 1:]:
                if count >= max_combinations:
                    break
                if a == b:
                    continue

                cat_a = self._get_category(a)
                cat_b = self._get_category(b)

                # 不同分类的组合
                combos = [
                    ("add", f"{a}_plus_{b}", f"{a} + {b}", cat_a,
                     lambda df, x=a, y=b: df[x] + df[y]),
                    ("sub", f"{a}_minus_{b}", f"{a} - {b}", cat_a,
                     lambda df, x=a, y=b: df[x] - df[y]),
                    ("mul", f"{a}_mul_{b}", f"{a} * {b}", cat_a,
                     lambda df, x=a, y=b: df[x] * df[y]),
                ]

                for method, c_name, expr, cat, func in combos:
                    if c_name in existing_names:
                        continue
                    if len(c_name) > 40:
                        continue

                    candidates.append(FactorCandidate(
                        name=c_name,
                        category=cat,
                        description=f"{a} 与 {b} 组合 ({method}) (mined)",
                        generation_method="combination",
                        source=f"{a}+{b}",
                        expression=expr,
                        func=func,
                    ))
                    count += 1

        return candidates

    def _get_category(self, factor_name: str) -> str:
        for f in self.existing_registry:
            if isinstance(f, dict) and f.get("name") == factor_name:
                return f.get("category", "others")
        return "others"


# ═══════════════════════════════════════════════════════════════════
# Unified CandidateGenerator
# ═══════════════════════════════════════════════════════════════════


class CandidateGenerator:
    """统一因子候选生成器 — 组合多个生成策略"""

    def __init__(self, existing_registry: list[dict] | None = None):
        self.existing_registry = existing_registry or []

    def generate_all(
        self,
        include_window: bool = True,
        include_cross_sectional: bool = True,
        include_combinations: bool = True,
        max_combinations: int = 20,
    ) -> list[FactorCandidate]:
        """使用所有启用的策略生成候选

        Returns:
            所有生成的候选列表
        """
        candidates: list[FactorCandidate] = []
        seen_names: set[str] = set()

        if include_window:
            gen = WindowVariationGenerator(self.existing_registry)
            for c in gen.generate():
                if c.name not in seen_names:
                    candidates.append(c)
                    seen_names.add(c.name)

        if include_cross_sectional:
            gen = CrossSectionalGenerator(self.existing_registry)
            for c in gen.generate():
                if c.name not in seen_names:
                    candidates.append(c)
                    seen_names.add(c.name)

        if include_combinations:
            gen = CombinationGenerator(self.existing_registry)
            for c in gen.generate(max_combinations=max_combinations):
                if c.name not in seen_names:
                    candidates.append(c)
                    seen_names.add(c.name)

        return candidates
