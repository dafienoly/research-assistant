"""Candidate Evaluator — 候选因子评估器

对生成的因子候选进行快速评估:
  1. 计算因子值
  2. 计算 IC (Information Coefficient)
  3. 计算 ICIR (IC/IC标准差)
  4. 按综合评分排名
  5. 返回评估报告
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.factor_mining.candidate_generator import FactorCandidate


# ═══════════════════════════════════════════════════════════════════
# EvaluationResult — 评估结果数据结构
# ═══════════════════════════════════════════════════════════════════


@dataclass
class EvaluationResult:
    """单个候选因子的评估结果

    Attributes:
        candidate: 原始候选定义
        ic_mean: RankIC 均值
        ic_std: RankIC 标准差
        ic_ir: ICIR (IC均值/IC标准差)
        ic_positive_ratio: IC 为正的天数比例
        layer1_ret: 分层回测第一层 (多头) 平均收益
        layer5_ret: 分层回测第五层 (空头) 平均收益
        spread_ret: 多空收益差
        score: 综合评分
        n_dates: 有效交易天数
        error: 错误信息 (评估失败时)
        status: 状态 (ok / error)
    """
    candidate: dict
    ic_mean: float = 0.0
    ic_std: float = 0.0
    ic_ir: float = 0.0
    ic_positive_ratio: float = 0.0
    layer1_ret: float = 0.0
    layer5_ret: float = 0.0
    spread_ret: float = 0.0
    score: float = 0.0
    n_dates: int = 0
    error: str = ""
    status: str = "ok"

    def to_dict(self) -> dict:
        return {
            "candidate": self.candidate,
            "ic_mean": self.ic_mean,
            "ic_std": self.ic_std,
            "ic_ir": self.ic_ir,
            "ic_positive_ratio": self.ic_positive_ratio,
            "layer1_ret": self.layer1_ret,
            "layer5_ret": self.layer5_ret,
            "spread_ret": self.spread_ret,
            "score": self.score,
            "n_dates": self.n_dates,
            "error": self.error,
            "status": self.status,
        }


# ═══════════════════════════════════════════════════════════════════
# CandidateEvaluator — 候选因子评估器
# ═══════════════════════════════════════════════════════════════════


class CandidateEvaluator:
    """候选因子评估器

    对生成的候选因子执行:
      1. 因子值计算 (使用候选的 func)
      2. RankIC 计算 (逐日 Spearman 相关)
      3. ICIR 计算
      4. 分层回测 (5层)
      5. 综合评分
    """

    def __init__(self, n_layers: int = 5):
        self.n_layers = n_layers

    def evaluate(
        self,
        df: pd.DataFrame,
        candidates: list[FactorCandidate],
        ret_col: str = "ret1",
        min_dates: int = 5,
    ) -> list[EvaluationResult]:
        """评估一批候选因子

        Args:
            df: K线数据 (含 date, symbol, close + ret_col)
            candidates: 候选因子列表
            ret_col: 下期收益列名
            min_dates: 最少有效天数

        Returns:
            评估结果列表 (按综合评分降序)
        """
        results: list[EvaluationResult] = []

        for cand in candidates:
            if cand.func is None:
                results.append(EvaluationResult(
                    candidate={"name": cand.name},
                    status="error",
                    error="no compute function",
                ))
                continue

            try:
                # 1. 计算因子值
                factor_series = cand.func(df)

                if factor_series is None or len(factor_series) == 0:
                    results.append(EvaluationResult(
                        candidate=cand.to_dict(),
                        status="error",
                        error=f"factor computation returned empty for {cand.name}",
                    ))
                    continue

                # 2. 构建临时 DataFrame
                temp_df = df[["date", "symbol", ret_col]].copy()
                temp_df[cand.name] = factor_series.values

                # 3. 移除 NaN
                valid = temp_df.dropna(subset=[cand.name, ret_col])
                if len(valid) < 100:
                    results.append(EvaluationResult(
                        candidate=cand.to_dict(),
                        status="error",
                        error=f"too few valid observations ({len(valid)}) for {cand.name}",
                    ))
                    continue

                # 4. 计算 RankIC
                ic_result = self._compute_rank_ic(valid, cand.name, ret_col)

                if ic_result["n_dates"] < min_dates:
                    results.append(EvaluationResult(
                        candidate=cand.to_dict(),
                        status="error",
                        error=f"too few IC dates ({ic_result['n_dates']} < {min_dates})",
                    ))
                    continue

                # 5. 分层回测
                layers = self._compute_layer_returns(valid, cand.name, ret_col)

                # 6. 计算综合评分
                score = self._compute_score(ic_result, layers)

                results.append(EvaluationResult(
                    candidate=cand.to_dict(),
                    ic_mean=round(ic_result["ic_mean"], 6),
                    ic_std=round(ic_result["ic_std"], 6),
                    ic_ir=round(ic_result["ic_ir"], 4),
                    ic_positive_ratio=round(ic_result["positive_ratio"], 4),
                    layer1_ret=round(layers.get("layer_1", 0), 6),
                    layer5_ret=round(layers.get(f"layer_{self.n_layers}", 0), 6),
                    spread_ret=round(layers.get("spread", 0), 6),
                    score=round(score, 4),
                    n_dates=ic_result["n_dates"],
                    status="ok",
                ))

            except Exception as e:
                results.append(EvaluationResult(
                    candidate=cand.to_dict(),
                    status="error",
                    error=f"{type(e).__name__}: {e}",
                ))

        # 按评分降序排列
        results.sort(key=lambda r: abs(r.score), reverse=True)
        return results

    def _compute_rank_ic(
        self, df: pd.DataFrame, factor_col: str, ret_col: str
    ) -> dict:
        """计算逐日 RankIC

        Returns:
            {ic_mean, ic_std, ic_ir, positive_ratio, n_dates, daily_ics}
        """
        daily_ics: list[float] = []

        for date, group in df.groupby("date"):
            if len(group) < 10:
                continue
            factor_vals = group[factor_col].values
            ret_vals = group[ret_col].values

            # RankIC: Spearman 相关
            from scipy.stats import spearmanr
            corr, _ = spearmanr(factor_vals, ret_vals)
            if not np.isnan(corr):
                daily_ics.append(corr)

        if not daily_ics:
            return {"ic_mean": 0, "ic_std": 0, "ic_ir": 0,
                    "positive_ratio": 0, "n_dates": 0, "daily_ics": []}

        ic_arr = np.array(daily_ics)
        ic_mean = float(np.mean(ic_arr))
        ic_std = float(np.std(ic_arr, ddof=1)) or 1e-10
        ic_ir = ic_mean / ic_std
        positive_ratio = float(np.sum(ic_arr > 0) / len(ic_arr))

        return {
            "ic_mean": ic_mean,
            "ic_std": ic_std,
            "ic_ir": ic_ir,
            "positive_ratio": positive_ratio,
            "n_dates": len(daily_ics),
            "daily_ics": daily_ics,
        }

    def _compute_layer_returns(
        self, df: pd.DataFrame, factor_col: str, ret_col: str
    ) -> dict:
        """分层回测 (按每日的因子值分 n_layers 层)

        Returns:
            {layer_1, layer_2, ..., layer_N, spread} 平均收益
        """
        layer_returns: dict[int, list[float]] = {i: [] for i in range(1, self.n_layers + 1)}

        for date, group in df.groupby("date"):
            if len(group) < self.n_layers * 2:
                continue
            ranked = group[factor_col].rank()
            # 等分: 按排名分 n_layers 层, 处理重复值
            n = len(ranked)
            group["layer"] = pd.cut(
                ranked, bins=np.linspace(0, n, self.n_layers + 1),
                labels=list(range(1, self.n_layers + 1)),
                include_lowest=True,
            )
            for layer in range(1, self.n_layers + 1):
                layer_data = group[group["layer"] == layer]
                if len(layer_data) > 0:
                    layer_returns[layer].append(layer_data[ret_col].mean())

        result = {}
        spread_avgs = []
        for layer in range(1, self.n_layers + 1):
            if layer_returns[layer]:
                result[f"layer_{layer}"] = float(np.mean(layer_returns[layer]))
            else:
                result[f"layer_{layer}"] = 0.0

        # 多空收益差
        l1 = result.get("layer_1", 0)
        lN = result.get(f"layer_{self.n_layers}", 0)
        result["spread"] = float(l1 - lN)

        return result

    def _compute_score(self, ic_result: dict, layers: dict) -> float:
        """计算综合评分

        考虑因素:
          - |IC| 越高越好
          - ICIR 越高越好 (绝对值)
          - 分层多空收益差越大越好
          - 多头收益 > 0

        Score = |IC_mean| * 10 + |IC_IR| + spread_ret * 100
        """
        ic_abs = abs(ic_result.get("ic_mean", 0))
        icir_abs = abs(ic_result.get("ic_ir", 0))
        spread = layers.get("spread", 0)

        score = ic_abs * 10 + icir_abs + abs(spread) * 100
        return score


# ═══════════════════════════════════════════════════════════════════
# 快捷工具
# ═══════════════════════════════════════════════════════════════════


def quick_evaluate(
    df: pd.DataFrame,
    candidates: list[FactorCandidate],
    top_n: int = 10,
) -> list[dict]:
    """快速评估一批候选因子并返回 Top-N 结果

    用法:
        results = quick_evaluate(kline_df, candidates, top_n=10)
        for r in results:
            print(f"{r['candidate']['name']}: IC={r['ic_mean']:.4f}, IR={r['ic_ir']:.2f}")
    """
    evaluator = CandidateEvaluator()
    results = evaluator.evaluate(df, candidates)
    return [r.to_dict() for r in results[:top_n]]
