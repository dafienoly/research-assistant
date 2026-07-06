"""V3.2 Factor Evaluation & Orthogonality — 统一评估 API

将 IC/ICIR、反过拟合(OOS)、Walk-Forward、正交性分析、评分
整合为单一入口, 提供完整的因子评估报告。

用法:
    from factor_lab.factor_evaluation import run_full_evaluation, FactorEvaluation

    # 快捷方式
    report = run_full_evaluation(df, close_pivot, factor_name="ret5")

    # 分步控制
    ev = FactorEvaluation()
    ic_report = ev.evaluate_ic(df, factor_name)
    ao_report = ev.evaluate_anti_overfit(df, factor_name, close_pivot)
    wf_report = ev.evaluate_walk_forward(df, factor_name, close_pivot)
    ortho_report = ev.evaluate_orthogonality(df, factor_name, candidate_factors)
    score = ev.evaluate_scoring(ao_report, walk_forward=wf_report)
    full = ev.run_full_evaluation(df, close_pivot, factor_name)
"""

import sys, os, json, warnings
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════


def _first_trading_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """获取每个月的第一个交易日 (跨年安全)"""
    if len(dates) == 0:
        return dates
    s = pd.Series(index=dates, data=1)
    return pd.DatetimeIndex(
        s.groupby(dates.to_period("M")).apply(lambda x: x.index[0]).values
    )


# ═══════════════════════════════════════════════════════════════════
# IC / ICIR 分析
# ═══════════════════════════════════════════════════════════════════


def evaluate_ic(
    df: pd.DataFrame,
    factor_col: str,
    ret_col: str = "ret1",
) -> dict:
    """计算 IC/ICIR 及分层回测

    参数:
        df: 因子 DataFrame (含 date, symbol, factor_col, ret_col)
        factor_col: 因子列名
        ret_col: 下期收益列名

    返回:
        ic_mean, ic_std, ic_ir, pos_ratio,
        daily_ic_series, layer_test 等
    """
    from factor_lab.ic_analyzer import (
        calc_daily_ic,
        calc_rankic_ir,
        layer_test,
    )

    # 逐日 IC
    ic_df = calc_daily_ic(df, factor_col, ret_col)

    if ic_df.empty:
        return {
            "factor_name": factor_col,
            "n_dates": 0,
            "error": "IC 数据不足 (少于10只股票/日)",
        }

    # RankIC IR
    ic_stats = calc_rankic_ir(ic_df)

    # 分层回测 (5层)
    layers = layer_test(df, factor_col, ret_col, n_layers=5)

    # 月度/季度 IC 聚合 (与 anti_overfit 一致)
    ic_df_copy = ic_df.copy()
    ic_df_copy["date"] = pd.to_datetime(ic_df_copy["date"])
    ic_df_copy["year_month"] = ic_df_copy["date"].dt.strftime("%Y-%m")
    monthly_ic = (
        ic_df_copy.groupby("year_month")["ic"].mean().reset_index().to_dict("records")
    )
    ic_df_copy["quarter"] = ic_df_copy["date"].dt.to_period("Q").astype(str)
    quarterly_ic = (
        ic_df_copy.groupby("quarter")["ic"].mean().reset_index().to_dict("records")
    )

    return {
        "factor_name": factor_col,
        "n_dates": len(ic_df),
        "ic_mean": ic_stats.get("mean_ic"),
        "ic_std": ic_stats.get("std_ic"),
        "ic_ir": ic_stats.get("ir"),
        "pos_ratio": ic_stats.get("pos_ratio"),
        "daily_ic_series": ic_df.to_dict("records"),
        "monthly_ic_series": monthly_ic,
        "quarterly_ic_series": quarterly_ic,
        "layer_test": layers,
    }


# ═══════════════════════════════════════════════════════════════════
# 反过拟合诊断 (IC 稳定性 + 子样本 + Placebo + IC 衰减 + 同池对照)
# ═══════════════════════════════════════════════════════════════════


def evaluate_anti_overfit(
    df: pd.DataFrame,
    factor_name: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
    placebo_trials: int = 100,
    run_full_strategy: bool = True,
) -> dict:
    """运行完整反过拟合诊断

    参数:
        df: 因子 DataFrame
        factor_name: 因子名
        close_pivot: 收盘价 pivot (date × symbol)
        top_quantile: Top 分位数
        rebalance: 调仓频率
        placebo_trials: 安慰剂检验次数
        run_full_strategy: 是否运行完整策略模拟

    返回:
        包含 ic_stability, stress_test, placebo, ic_decay,
        peer_benchmark, overall_verdict 的 dict
    """
    from factor_lab.validation.anti_overfit import run_anti_overfit

    return run_anti_overfit(
        df, factor_name,
        close_pivot=close_pivot,
        top_quantile=top_quantile,
        rebalance=rebalance,
        placebo_trials=placebo_trials,
        run_full_strategy=run_full_strategy,
    )


# ═══════════════════════════════════════════════════════════════════
# Walk-Forward OOS 验证
# ═══════════════════════════════════════════════════════════════════


def evaluate_walk_forward(
    df: pd.DataFrame,
    factor_name: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
    method: str = "rolling",
    **kwargs,
) -> dict:
    """运行 Walk-Forward 样本外验证

    参数:
        df: 因子 DataFrame
        factor_name: 因子名
        close_pivot: 收盘价 pivot
        top_quantile: Top 分位数
        rebalance: 调仓频率
        method: "rolling" (默认, 推荐) 或 "classic"
        **kwargs: 传递给具体实现的其他参数

    返回:
        Walk-Forward 验证结果 dict
    """
    if method == "rolling":
        from factor_lab.validation.rolling_validator import run_rolling_validation

        return run_rolling_validation(
            df, factor_name, close_pivot,
            top_quantile=top_quantile,
            rebalance=rebalance,
            **kwargs,
        )
    else:
        from factor_lab.walk_forward import run_window_backtest, WINDOWS

        window_results = []
        for name, ts, te, vs, ve in WINDOWS:
            r = run_window_backtest(
                df, factor_name, ts, te, vs, ve, top_quantile, rebalance
            )
            r["window_name"] = name
            window_results.append(r)

        from factor_lab.walk_forward import compute_overfitting_diagnostics

        diagnostics = compute_overfitting_diagnostics(window_results)
        return {
            "factor_name": factor_name,
            "method": "classic",
            "windows": window_results,
            "diagnostics": diagnostics,
            "generated_at": datetime.now(CST).isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════
# 正交性分析
# ═══════════════════════════════════════════════════════════════════


def evaluate_orthogonality(
    factor_df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    reference_factor: str = "ret5",
    candidate_factors: Optional[list] = None,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
    n_top_iv: int = 10,
) -> dict:
    """计算候选因子对参考因子的正交性及增量价值

    参数:
        factor_df: 因子 DataFrame (含 date, symbol, 各因子列)
        close_pivot: 收盘价 pivot
        reference_factor: 参考因子 (默认 ret5)
        candidate_factors: 候选因子列表; 默认从 factor_df 列推断
        top_quantile: 选股分位数
        rebalance: 调仓频率
        n_top_iv: 对最正交的前 N 个因子计算增量价值

    返回:
        正交性结果 dict
    """
    from factor_lab.orthogonality.orthogonality_analyzer import (
        compute_orthogonality,
        compute_incremental_value,
    )

    # 自动推断候选因子
    if candidate_factors is None:
        skip_cols = {
            "date", "symbol", "close", "ret1", "volume", "amount",
            "open", "high", "low", "ret10", "ret20", "ret60",
        }
        candidate_factors = [
            c for c in factor_df.columns
            if c not in skip_cols and c != reference_factor
            and factor_df[c].nunique() > 10  # 有足够变化
        ]

    # 正交性计算
    ortho_result = compute_orthogonality(
        factor_df, candidate_factors, reference_factor=reference_factor,
    )

    # 对最正交的因子做增量价值评估
    candidates = ortho_result.get("candidates", [])
    valid = [c for c in candidates if "error" not in c]
    sorted_candidates = sorted(
        valid, key=lambda c: c.get("orthogonality_score", 0), reverse=True,
    )
    top_n = sorted_candidates[:n_top_iv]

    iv_results = []
    for cand in top_n:
        try:
            iv = compute_incremental_value(
                factor_df, close_pivot, cand["name"],
                reference=reference_factor,
                top_quantile=top_quantile,
                rebalance=rebalance,
            )
            iv_results.append(iv)
        except Exception:
            iv_results.append({"candidate_name": cand["name"], "error": "增量价值计算失败"})

    return {
        "reference_factor": reference_factor,
        "n_candidates": len(candidates),
        "candidates": candidates,
        "incremental_value": iv_results,
        "n_top_iv": n_top_iv,
        "generated_at": datetime.now(CST).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# 因子评分
# ═══════════════════════════════════════════════════════════════════


def evaluate_scoring(
    anti_overfit: dict,
    walk_forward: Optional[dict] = None,
    expression: str = "",
    family: str = "unknown",
    config: Optional[dict] = None,
) -> dict:
    """对因子进行综合评分 (IC 稳定性 + 同池超额 + 回撤 + Walk-Forward + 简洁性)

    参数:
        anti_overfit: evaluate_anti_overfit() 或 run_anti_overfit() 的输出
        walk_forward: evaluate_walk_forward() 的输出 (可选)
        expression: 因子表达式
        family: 因子家族
        config: 评分配置覆写

    返回:
        包含 overall_score, grade, pass_gate, 各维度评分的 dict
    """
    from factor_lab.scoring.factor_score import score_factor

    return score_factor(
        anti_overfit=anti_overfit,
        rolling_validation=walk_forward,
        expression=expression,
        family=family,
        config=config,
    )


# ═══════════════════════════════════════════════════════════════════
# Unified FactorEvaluation 类 — 分步控制
# ═══════════════════════════════════════════════════════════════════


class FactorEvaluation:
    """V3.2 因子评估 & 正交性 — 分步控制类

    提供分步方法, 每一步返回结构化结果, 最后可用 run_full_evaluation()
    一次完成全流程。

    用法:
        ev = FactorEvaluation()
        report = ev.run_full_evaluation(df, close_pivot, "ret5")
    """

    def __init__(self):
        self.results = {}

    # ── IC/ICIR ─────────────────────────────────────────────────

    def evaluate_ic(
        self, df: pd.DataFrame, factor_col: str, ret_col: str = "ret1"
    ) -> dict:
        """IC/ICIR 分析 + 分层回测"""
        result = evaluate_ic(df, factor_col, ret_col)
        self.results["ic_analysis"] = result
        return result

    # ── 反过拟合 ────────────────────────────────────────────────

    def evaluate_anti_overfit(
        self,
        df: pd.DataFrame,
        factor_name: str,
        close_pivot: pd.DataFrame,
        top_quantile: float = 0.2,
        rebalance: str = "monthly",
        placebo_trials: int = 100,
    ) -> dict:
        """反过拟合诊断 (IC稳定性 + 子样本 + Placebo + IC衰减 + 同池对照)"""
        # 先确保 df 有 ret1
        if "ret1" not in df.columns:
            df["ret1"] = df.groupby("symbol")["close"].transform(
                lambda x: x.pct_change(-1)
            )

        result = evaluate_anti_overfit(
            df, factor_name, close_pivot,
            top_quantile=top_quantile,
            rebalance=rebalance,
            placebo_trials=placebo_trials,
        )
        self.results["anti_overfit"] = result
        return result

    # ── Walk-Forward ─────────────────────────────────────────────

    def evaluate_walk_forward(
        self,
        df: pd.DataFrame,
        factor_name: str,
        close_pivot: pd.DataFrame,
        top_quantile: float = 0.2,
        rebalance: str = "monthly",
        method: str = "rolling",
        **kwargs,
    ) -> dict:
        """Walk-Forward 样本外验证"""
        result = evaluate_walk_forward(
            df, factor_name, close_pivot,
            top_quantile=top_quantile,
            rebalance=rebalance,
            method=method,
            **kwargs,
        )
        self.results["walk_forward"] = result
        return result

    # ── 正交性 ───────────────────────────────────────────────────

    def evaluate_orthogonality(
        self,
        factor_df: pd.DataFrame,
        close_pivot: pd.DataFrame,
        reference_factor: str = "ret5",
        candidate_factors: Optional[list] = None,
        top_quantile: float = 0.2,
        rebalance: str = "monthly",
    ) -> dict:
        """正交性分析 + 增量价值"""
        result = evaluate_orthogonality(
            factor_df, close_pivot,
            reference_factor=reference_factor,
            candidate_factors=candidate_factors,
            top_quantile=top_quantile,
            rebalance=rebalance,
        )
        self.results["orthogonality"] = result
        return result

    # ── 评分 ─────────────────────────────────────────────────────

    def evaluate_scoring(
        self,
        anti_overfit: Optional[dict] = None,
        walk_forward: Optional[dict] = None,
        expression: str = "",
        family: str = "unknown",
        config: Optional[dict] = None,
    ) -> dict:
        """综合评分"""
        ao = anti_overfit or self.results.get("anti_overfit", {})
        wf = walk_forward or self.results.get("walk_forward")

        result = evaluate_scoring(ao, walk_forward=wf, expression=expression,
                                  family=family, config=config)
        self.results["scoring"] = result
        return result

    # ── 全流程 ───────────────────────────────────────────────────

    def run_full_evaluation(
        self,
        df: pd.DataFrame,
        close_pivot: pd.DataFrame,
        factor_name: str,
        ret_col: str = "ret1",
        top_quantile: float = 0.2,
        rebalance: str = "monthly",
        candidate_factors: Optional[list] = None,
        expression: str = "",
        family: str = "unknown",
        method: str = "rolling",
    ) -> dict:
        """运行完整因子评估全流程

        步骤:
          1. IC/ICIR 分析 + 分层回测
          2. 反过拟合诊断 (IC稳定性 + 子样本 + Placebo + IC衰减 + 同池对照)
          3. Walk-Forward 样本外验证
          4. (可选) 正交性分析 — 需要 candidate_factors
          5. 综合评分

        返回:
            {ic_analysis, anti_overfit, walk_forward, orthogonality, scoring}
        """
        # 确保 ret1
        if ret_col not in df.columns:
            df[ret_col] = df.groupby("symbol")["close"].transform(
                lambda x: x.pct_change(-1)
            )

        results = {}

        # ── 1. IC/ICIR ──
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results["ic_analysis"] = self.evaluate_ic(df, factor_name, ret_col)

        # ── 2. 反过拟合 ──
        results["anti_overfit"] = self.evaluate_anti_overfit(
            df, factor_name, close_pivot,
            top_quantile=top_quantile,
            rebalance=rebalance,
        )

        # ── 3. Walk-Forward ──
        results["walk_forward"] = self.evaluate_walk_forward(
            df, factor_name, close_pivot,
            top_quantile=top_quantile,
            rebalance=rebalance,
            method=method,
            start_date=str(df["date"].min())[:10],
            end_date=str(df["date"].max())[:10],
        )

        # ── 4. 正交性 (可选) ──
        if candidate_factors is not None:
            results["orthogonality"] = self.evaluate_orthogonality(
                df if candidate_factors else None,
                close_pivot,
                reference_factor=factor_name,
                candidate_factors=candidate_factors,
                top_quantile=top_quantile,
                rebalance=rebalance,
            )
        else:
            results["orthogonality"] = {"note": "未提供候选因子, 跳过正交性分析"}

        # ── 5. 综合评分 ──
        results["scoring"] = self.evaluate_scoring(
            results["anti_overfit"],
            walk_forward=results["walk_forward"],
            expression=expression,
            family=family,
        )

        results["factor_name"] = factor_name
        results["generated_at"] = datetime.now(CST).isoformat()
        results["config"] = {
            "top_quantile": top_quantile,
            "rebalance": rebalance,
            "method": method,
            "family": family,
        }

        self.results = results
        return results

    def summary(self) -> dict:
        """生成评估摘要"""
        results = self.results
        if not results:
            return {"status": "no_results"}

        ic = results.get("ic_analysis", {})
        ao = results.get("anti_overfit", {})
        wf = results.get("walk_forward", {})
        score = results.get("scoring", {})

        return {
            "status": "completed",
            "factor_name": results.get("factor_name", ""),
            "ic_ir": ic.get("ic_ir"),
            "ic_pos_ratio": ic.get("pos_ratio"),
            "layer_long_short_sharpe": (
                ic.get("layer_test", {}).get("long_short_sharpe")
            ),
            "anti_overfit_verdict": ao.get("overall_verdict"),
            "walk_forward_verdict": wf.get("overall_verdict"),
            "wf_avg_test_sharpe": wf.get("avg_test_sharpe"),
            "wf_avg_decay": wf.get("avg_decay"),
            "overall_score": score.get("overall_score"),
            "grade": score.get("grade"),
            "pass_gate": score.get("pass_gate"),
            "generated_at": datetime.now(CST).isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════
# 快捷函数
# ═══════════════════════════════════════════════════════════════════


def run_full_evaluation(
    df: pd.DataFrame,
    close_pivot: pd.DataFrame,
    factor_name: str,
    ret_col: str = "ret1",
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
    candidate_factors: Optional[list] = None,
    expression: str = "",
    family: str = "unknown",
    method: str = "rolling",
) -> dict:
    """运行完整因子评估全流程 (快捷函数)

    直接返回所有评估结果的 dict, 不需创建 FactorEvaluation 实例。

    参数:
        df: 因子 DataFrame (含 date, symbol, close)
        close_pivot: 收盘价 pivot (date × symbol)
        factor_name: 因子名
        top_quantile: 选股分位数
        rebalance: 调仓频率
        candidate_factors: 正交性分析的候选因子列表 (可选)
        expression: 因子表达式
        family: 因子家族
        method: Walk-Forward 方法 ("rolling" 或 "classic")

    返回:
        {ic_analysis, anti_overfit, walk_forward, orthogonality, scoring}
    """
    ev = FactorEvaluation()
    return ev.run_full_evaluation(
        df, close_pivot, factor_name,
        ret_col=ret_col,
        top_quantile=top_quantile,
        rebalance=rebalance,
        candidate_factors=candidate_factors,
        expression=expression,
        family=family,
        method=method,
    )
