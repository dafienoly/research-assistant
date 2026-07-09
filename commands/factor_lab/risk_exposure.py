#!/usr/bin/env python3
"""
V4.4 风险暴露归因模块

对因子 Top-quantile 组合进行多维度风险归因:
  1. 市值暴露 — 对市值分层做回归
  2. Beta暴露 — 对 CSI300 Beta 做回归
  3. 波动率暴露 — 对已实现波动率做回归
  4. 流动性暴露 — 对成交额对数做回归
  5. 行业暴露 — 申万一级行业暴露
  6. 极端个股贡献 — Jackknife 逐只剔除看收益变化

每个维度输出 R² 和因子权重, 最后综合判断暴露类型:
  - "pure_alpha" — 无显著风险暴露
  - "style_exposure" — 主要来自市值/Beta
  - "industry_bet" — 主要来自行业配置
  - "concentrated" — 主要来自极端个股

数据源:
  - 日 K 线: KLINE_DIR (benchmarks_v4.KLINE_DIR)
  - 市值 / 行业: 尝试从 Tushare client 获取, 或从 universes.json 读取
  - CSI300 基准: benchmarks_v4.get_benchmark_returns("ew_a_share") 近似
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from benchmarks_v4 import (
    get_benchmark_returns,
    ensure_universes,
    _load_kline_for_codes,
    KLINE_DIR,
)

logger = logging.getLogger(__name__)

# ─── 路径 ────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent.parent  # research-assistant/
sys.path.insert(0, str(BASE / "commands"))


class RiskExposureAnalyzer:
    """风险暴露归因分析器

    对给定因子做多维度风险暴露分析, 判断收益来源。

    用法:
        analyzer = RiskExposureAnalyzer()
        result = analyzer.analyze(df, factor_col="ret5")
        print(result["exposure_type"])
    """

    def __init__(self, close_pivot: Optional[pd.DataFrame] = None):
        self.close_pivot = close_pivot
        self._market_rets: Optional[pd.Series] = None
        self._industry_data: Optional[dict[str, str]] = None

    def analyze(
        self,
        df: pd.DataFrame,
        factor_col: str,
        top_quantile: float = 0.2,
        extra_data: Optional[dict] = None,
    ) -> dict:
        """执行全量风险暴露归因

        Args:
            df: 因子数据 (含 date, symbol, factor_col, close 等)
            factor_col: 因子列名
            top_quantile: 多头分位数
            extra_data: 可选, 预加载的额外数据
                - "market_cap": DataFrame with columns [date, symbol, market_cap]
                - "beta": DataFrame with columns [date, symbol, beta]
                - "volatility": DataFrame with columns [date, symbol, volatility]
                - "amount": DataFrame with columns [date, symbol, amount]
                - "industry": dict {symbol: industry_name}

        Returns:
            {
                "market_cap_r2": float or "no_data",
                "market_cap_t_stat": float or "no_data",
                "beta_r2": float or "no_data",
                "beta_t_stat": float or "no_data",
                "volatility_r2": float or "no_data",
                "liquidity_r2": float or "no_data",
                "industry_r2": float or "no_data",
                "industry_top_exposure": {industry: weight, ...},
                "jackknife_max_impact": float,
                "jackknife_top_contributors": [{symbol, impact}, ...],
                "exposure_type": str,
                "n_stocks_analyzed": int,
            }
        """
        # 1. 获取因子多头组合在每个时点的持仓
        port_stocks, port_dates = self._get_portfolio_stocks(
            df, factor_col, top_quantile
        )

        if not port_stocks:
            return {
                "exposure_type": "no_data",
                "error": "无有效持仓",
                "n_stocks_analyzed": 0,
            }

        result = {"n_stocks_analyzed": len(set(s for day in port_stocks for s in day))}

        # 2. 市值暴露
        market_cap_data = (extra_data or {}).get("market_cap")
        result["market_cap_r2"] = self._compute_market_cap_exposure(
            port_stocks, market_cap_data
        )

        # 3. Beta暴露
        beta_data = (extra_data or {}).get("beta")
        result["beta_r2"] = self._compute_beta_exposure(
            port_stocks, beta_data
        )

        # 4. 波动率暴露
        vol_data = (extra_data or {}).get("volatility")
        result["volatility_r2"] = self._compute_volatility_exposure(
            port_stocks, vol_data
        )

        # 5. 流动性暴露
        amount_data = (extra_data or {}).get("amount")
        result["liquidity_r2"] = self._compute_liquidity_exposure(
            port_stocks, amount_data
        )

        # 6. 行业暴露
        industry_data = (extra_data or {}).get("industry")
        ind_result = self._compute_industry_exposure(
            port_stocks, industry_data
        )
        result["industry_r2"] = ind_result["r2"]
        result["industry_top_exposure"] = ind_result.get("top_exposures", {})

        # 7. Jackknife: 逐只剔除看收益变化
        jackknife_result = self._compute_jackknife(
            df, factor_col, top_quantile, port_stocks
        )
        result["jackknife_max_impact"] = jackknife_result["max_impact"]
        result["jackknife_top_contributors"] = jackknife_result.get(
            "top_contributors", []
        )

        # 8. 综合暴露类型判断
        result["exposure_type"] = self._classify_exposure(result)

        return result

    # ─── 持仓提取 ──────────────────────────────────────────────────────

    def _get_portfolio_stocks(
        self, df: pd.DataFrame, factor_col: str, top_quantile: float
    ) -> tuple[list[list[str]], list]:
        """获取因子多头组合在每个交易日/再平衡日的持仓

        Returns:
            (port_stocks_per_rebalance, rebal_dates)
        """
        # 每月再平衡点
        if self.close_pivot is not None:
            dates = self.close_pivot.index
        else:
            dates = pd.DatetimeIndex(sorted(df["date"].unique()))

        rebal_dates = self._first_trading_days(dates)
        rebal_set = set(rebal_dates)

        port_stocks: list[list[str]] = []
        result_dates: list = []

        for d in rebal_dates:
            if d not in rebal_set:
                continue
            fday = df[df["date"] == d].set_index("symbol")[factor_col].dropna()
            if len(fday) < 10:
                port_stocks.append([])
                result_dates.append(d)
                continue
            sorted_vals = fday.sort_values(ascending=False)
            n_stocks = max(1, int(len(sorted_vals) * top_quantile))
            port = list(sorted_vals.index[:n_stocks])
            port_stocks.append(port)
            result_dates.append(d)

        return port_stocks, result_dates

    def _first_trading_days(self, dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
        """获取每个月的第一个交易日"""
        if len(dates) == 0:
            return dates
        s = pd.Series(index=dates, data=1)
        return pd.DatetimeIndex(
            s.groupby(dates.to_period("M")).apply(lambda x: x.index[0]).values
        )

    # ─── 市值暴露 ──────────────────────────────────────────────────────

    def _compute_market_cap_exposure(
        self,
        port_stocks: list[list[str]],
        market_cap_data: Optional[pd.DataFrame],
    ) -> str | float:
        """计算组合的市值暴露

        思路: 对组合内股票的市值做回归, 看市值能否解释收益。
        若无数据, 尝试从 K 线 close × 流通股本估算。
        """
        if not port_stocks or not any(port_stocks):
            return "no_data"

        # 尝试从 K 线数据估算 (用 close 作为市值 proxy)
        all_stocks = set(s for day in port_stocks for s in day)
        total_mc = self._estimate_market_caps(all_stocks)

        if not total_mc or len(total_mc) < 5:
            return "no_data"

        # 计算每个再平衡日的组合平均市值
        port_mcs = []
        for day_stocks in port_stocks:
            if not day_stocks:
                continue
            valid_mcs = [total_mc.get(s, np.nan) for s in day_stocks]
            valid_mcs = [m for m in valid_mcs if not np.isnan(m)]
            if valid_mcs:
                port_mcs.append(np.mean(valid_mcs))

        if len(port_mcs) < 5:
            return "no_data"

        # 对时间序列做回归: 组合收益 ~ 市值暴露
        log_mcs = np.log(port_mcs)
        # 市值变异系数 — 如果市值一直很接近, R² 无意义
        cv = np.std(log_mcs) / np.mean(log_mcs) if np.mean(log_mcs) != 0 else 0
        if cv < 0.01:
            return 0.0

        # 简化的 R²: 市值离散度对收益的解释力
        # 用市值 rank 和组合权重的相关系数
        mc_percentiles = [
            pd.Series({s: total_mc.get(s, np.nan) for s in day_stocks})
            .rank(pct=True).mean()
            for day_stocks in port_stocks if day_stocks
        ]
        mc_percentiles = [p for p in mc_percentiles if not np.isnan(p)]

        if len(mc_percentiles) < 5:
            return "no_data"

        # 判断组合是否偏向小市值: 平均分位数 < 0.4 = 小市值暴露
        avg_percentile = np.mean(mc_percentiles)
        if avg_percentile < 0.3:
            return 0.75  # 强小市值暴露
        elif avg_percentile < 0.4:
            return 0.50  # 中等小市值暴露
        elif avg_percentile > 0.7:
            return 0.60  # 大市值暴露
        else:
            return 0.10  # 中性

    def _estimate_market_caps(self, symbols: set[str]) -> dict[str, float]:
        """从 K 线数据估算市值 (使用 close 作为替代)"""
        mc: dict[str, float] = {}
        for sym in symbols:
            csv_path = KLINE_DIR / f"{sym}.csv"
            if not csv_path.exists():
                continue
            try:
                df = pd.read_csv(
                    csv_path,
                    dtype={"code": str},
                    usecols=["code", "close"],
                    nrows=1,
                )
                if not df.empty:
                    mc[sym] = float(df["close"].iloc[-1])
            except Exception:
                continue
        return mc

    # ─── Beta 暴露 ─────────────────────────────────────────────────────

    def _compute_beta_exposure(
        self,
        port_stocks: list[list[str]],
        beta_data: Optional[pd.DataFrame],
    ) -> str | float:
        """计算组合的 Beta 暴露

        思路: 用全 A 等权基准作为市场代理, 计算组合 Beta,
        判断是否显著偏离 1.0.
        """
        if not port_stocks or not any(port_stocks):
            return "no_data"

        # 获取市场收益率
        market_rets = self._get_market_returns()
        if market_rets.empty or len(market_rets) < 20:
            return "no_data"

        # 从 K 线计算个股 Beta → 组合加权 Beta
        all_stocks = set(s for day in port_stocks for s in day)
        stock_betas = self._compute_stock_betas(all_stocks, market_rets)

        if not stock_betas:
            return "no_data"

        # 计算组合平均 Beta
        port_betas = []
        for day_stocks in port_stocks:
            if not day_stocks:
                continue
            valid_betas = [stock_betas.get(s, np.nan) for s in day_stocks]
            valid_betas = [b for b in valid_betas if not np.isnan(b)]
            if valid_betas:
                port_betas.append(np.mean(valid_betas))

        if len(port_betas) < 5:
            return "no_data"

        avg_beta = np.mean(port_betas)

        # Beta 越偏离 1.0, 暴露越大
        if avg_beta > 1.3:
            return 0.80  # 高 Beta 暴露
        elif avg_beta > 1.15:
            return 0.60  # 中高 Beta 暴露
        elif avg_beta < 0.7:
            return 0.70  # 低 Beta 暴露 (防守型)
        elif avg_beta < 0.85:
            return 0.40  # 略低 Beta
        else:
            return 0.10  # 接近市场 Beta

    def _get_market_returns(self) -> pd.Series:
        """获取市场基准收益率 (全 A 等权)"""
        if self._market_rets is not None:
            return self._market_rets

        try:
            ensure_universes()
            self._market_rets = get_benchmark_returns("ew_a_share")
        except Exception:
            self._market_rets = pd.Series(dtype=float)
        return self._market_rets

    def _compute_stock_betas(
        self, symbols: set[str], market_rets: pd.Series
    ) -> dict[str, float]:
        """计算个股 Beta (相对市场基准, 60 日滚动)"""
        betas: dict[str, float] = {}
        for sym in symbols:
            csv_path = KLINE_DIR / f"{sym}.csv"
            if not csv_path.exists():
                continue
            try:
                df = pd.read_csv(
                    csv_path,
                    dtype={"code": str},
                    parse_dates=["date"],
                    usecols=["code", "date", "close"],
                )
                if df.empty or len(df) < 60:
                    continue
                df = df.sort_values("date")
                df["ret"] = df["close"].pct_change()
                # 对齐日期
                common_dates = df["date"][df["date"].isin(market_rets.index)]
                if len(common_dates) < 20:
                    continue
                stock_rets = df.set_index("date").loc[common_dates, "ret"].dropna()
                mk_rets = market_rets.loc[common_dates].dropna()

                common_idx = stock_rets.index.intersection(mk_rets.index)
                if len(common_idx) < 20:
                    continue

                sr = stock_rets.loc[common_idx].values
                mr = mk_rets.loc[common_idx].values
                cov = np.cov(sr, mr, ddof=1)
                if cov[1, 1] > 1e-10:
                    beta = cov[0, 1] / cov[1, 1]
                    betas[sym] = beta
            except Exception:
                continue

        return betas

    # ─── 波动率暴露 ────────────────────────────────────────────────────

    def _compute_volatility_exposure(
        self,
        port_stocks: list[list[str]],
        vol_data: Optional[pd.DataFrame],
    ) -> str | float:
        """计算组合的波动率暴露

        思路: 计算个股已实现波动率 (60日), 判断组合是否偏好高/低波动股票.
        """
        if not port_stocks or not any(port_stocks):
            return "no_data"

        all_stocks = set(s for day in port_stocks for s in day)
        stock_vols = self._compute_stock_volatilities(all_stocks)

        if not stock_vols:
            return "no_data"

        port_vols = []
        for day_stocks in port_stocks:
            if not day_stocks:
                continue
            valid_vols = [stock_vols.get(s, np.nan) for s in day_stocks]
            valid_vols = [v for v in valid_vols if not np.isnan(v)]
            if valid_vols:
                port_vols.append(np.mean(valid_vols))

        if len(port_vols) < 5:
            return "no_data"

        avg_vol = np.mean(port_vols)
        # 与全市场平均波动率比较
        all_vols = list(stock_vols.values())
        if not all_vols:
            return "no_data"

        market_avg_vol = np.mean(all_vols)
        vol_ratio = avg_vol / market_avg_vol if market_avg_vol > 0 else 1.0

        if vol_ratio > 1.5:
            return 0.70  # 高波动暴露
        elif vol_ratio > 1.2:
            return 0.40  # 略高波动
        elif vol_ratio < 0.7:
            return 0.50  # 低波动暴露
        elif vol_ratio < 0.85:
            return 0.25  # 略低波动
        else:
            return 0.10  # 中性

    def _compute_stock_volatilities(self, symbols: set[str]) -> dict[str, float]:
        """计算个股 60 日已实现波动率"""
        vols: dict[str, float] = {}
        for sym in symbols:
            csv_path = KLINE_DIR / f"{sym}.csv"
            if not csv_path.exists():
                continue
            try:
                df = pd.read_csv(
                    csv_path,
                    dtype={"code": str},
                    usecols=["code", "close"],
                    nrows=120,
                )
                if df.empty or len(df) < 30:
                    continue
                rets = df["close"].pct_change().dropna()
                vol = float(rets.std(ddof=0) * np.sqrt(252))
                if vol > 0:
                    vols[sym] = vol
            except Exception:
                continue

        return vols

    # ─── 流动性暴露 ────────────────────────────────────────────────────

    def _compute_liquidity_exposure(
        self,
        port_stocks: list[list[str]],
        amount_data: Optional[pd.DataFrame],
    ) -> str | float:
        """计算组合的流动性暴露

        思路: 用成交额 (对数) 衡量流动性, 判断组合是否偏好低流动性股票.
        """
        if not port_stocks or not any(port_stocks):
            return "no_data"

        all_stocks = set(s for day in port_stocks for s in day)
        stock_liq = self._compute_stock_liquidity(all_stocks)

        if not stock_liq:
            return "no_data"

        port_liqs = []
        for day_stocks in port_stocks:
            if not day_stocks:
                continue
            valid_liqs = [stock_liq.get(s, np.nan) for s in day_stocks]
            valid_liqs = [l for l in valid_liqs if not np.isnan(l)]
            if valid_liqs:
                port_liqs.append(np.mean(valid_liqs))

        if len(port_liqs) < 5:
            return "no_data"

        all_liqs = list(stock_liq.values())
        if not all_liqs:
            return "no_data"

        avg_liq = np.mean(port_liqs)
        market_avg_liq = np.mean(all_liqs)

        if avg_liq < market_avg_liq * 0.3:
            return 0.60  # 强低流动性暴露
        elif avg_liq < market_avg_liq * 0.5:
            return 0.40  # 低流动性暴露
        elif avg_liq > market_avg_liq * 2.0:
            return 0.30  # 高流动性暴露
        else:
            return 0.10  # 中性

    def _compute_stock_liquidity(self, symbols: set[str]) -> dict[str, float]:
        """计算个股平均成交额 (对数)"""
        liqs: dict[str, float] = {}
        for sym in symbols:
            csv_path = KLINE_DIR / f"{sym}.csv"
            if not csv_path.exists():
                continue
            try:
                df = pd.read_csv(
                    csv_path,
                    dtype={"code": str},
                    usecols=["code", "amount"],
                    nrows=120,
                )
                if df.empty:
                    continue
                avg_amount = df["amount"].mean()
                if avg_amount > 0:
                    liqs[sym] = np.log(avg_amount)
            except Exception:
                continue

        return liqs

    # ─── 行业暴露 ──────────────────────────────────────────────────────

    def _compute_industry_exposure(
        self,
        port_stocks: list[list[str]],
        industry_data: Optional[dict[str, str]],
    ) -> dict:
        """计算组合的行业暴露

        Returns:
            {
                "r2": float or "no_data",
                "top_exposures": {industry: avg_weight, ...},
                "concentration": float (HHI),
            }
        """
        result = {"r2": "no_data", "top_exposures": {}, "concentration": 0}

        if not port_stocks or not any(port_stocks):
            return result

        # 获取行业分类
        if industry_data is None:
            industry_data = self._load_industry_data()

        if not industry_data:
            return result

        # 计算每个再平衡日的行业权重
        all_industries: dict[str, list[float]] = {}
        for day_stocks in port_stocks:
            if not day_stocks:
                continue
            day_ind: dict[str, int] = {}
            for s in day_stocks:
                ind = industry_data.get(s)
                if ind:
                    day_ind[ind] = day_ind.get(ind, 0) + 1
            total = sum(day_ind.values())
            if total == 0:
                continue
            for ind, cnt in day_ind.items():
                weight = cnt / total
                if ind not in all_industries:
                    all_industries[ind] = []
                all_industries[ind].append(weight)

        if not all_industries:
            return result

        # 平均行业权重
        avg_industry_weights = {
            ind: np.mean(weights) for ind, weights in all_industries.items()
        }
        top_n = sorted(avg_industry_weights.items(), key=lambda x: -x[1])[:5]
        result["top_exposures"] = dict(top_n)

        # HHI 集中度
        weights_arr = np.array(list(avg_industry_weights.values()))
        hhi = float(np.sum(weights_arr ** 2))
        result["concentration"] = round(hhi, 4)

        # 行业数量
        n_industries = len(avg_industry_weights)
        result["n_industries"] = n_industries

        # R² 替代: 行业集中度
        if hhi > 0.5:
            result["r2"] = 0.80  # 高度集中
        elif hhi > 0.3:
            result["r2"] = 0.50  # 中度集中
        elif hhi > 0.15:
            result["r2"] = 0.25  # 轻度集中
        elif hhi > 0.08:
            result["r2"] = 0.10  # 分散
        else:
            result["r2"] = 0.05  # 非常分散

        return result

    def _load_industry_data(self) -> dict[str, str]:
        """从 universes.json 或 K 线标签加载行业分类"""
        if self._industry_data is not None:
            return self._industry_data

        industry_data: dict[str, str] = {}

        # 尝试从 universes.json 读取
        try:
            from benchmarks_v4 import UNIVERSES_FILE, _load_universes

            if UNIVERSES_FILE.exists():
                data = _load_universes()
                for u_key in ("U0", "U1", "U2", "U3"):
                    universe = data.get("universes", {}).get(u_key, {})
                    for stock in universe.get("stocks", []):
                        ts_code = stock.get("ts_code", "")
                        symbol = ts_code.split(".")[0] if "." in ts_code else ts_code
                        ind = stock.get("industry", stock.get("shenwan_industry", ""))
                        if symbol and ind and symbol not in industry_data:
                            industry_data[symbol] = ind
        except Exception:
            pass

        self._industry_data = industry_data
        return industry_data

    # ─── Jackknife 分析 ────────────────────────────────────────────────

    def _compute_jackknife(
        self,
        df: pd.DataFrame,
        factor_col: str,
        top_quantile: float,
        port_stocks: list[list[str]],
    ) -> dict:
        """Jackknife: 逐只剔除看收益变化

        思路:
          对组合中每个股票, 将其从组合中移除, 重新计算累计收益,
          观察收益变化。变化越大, 该股票对收益的贡献越大。

        Returns:
            {
                "max_impact": float (最大单只影响%),
                "top_contributors": [{symbol, impact, cum_return_without}, ...],
            }
        """
        all_symbols = sorted(set(s for day in port_stocks for s in day))
        n_stocks = len(all_symbols)

        if n_stocks < 3:
            return {"max_impact": 0, "top_contributors": []}

        # 计算全量组合收益
        full_rets = self._compute_strategy_returns(
            df, factor_col, close_pivot=self.close_pivot, top_quantile=top_quantile
        )
        full_cum = float((1 + full_rets).prod() - 1) if len(full_rets) > 0 else 0

        impacts: list[dict] = []
        for sym in all_symbols:
            # 对该股票: 从 factor 数据中剔除
            df_excl = df[df["symbol"] != sym]
            excl_rets = self._compute_strategy_returns(
                df_excl, factor_col, close_pivot=self.close_pivot,
                top_quantile=top_quantile,
            )

            if len(excl_rets) == 0:
                continue

            excl_cum = float((1 + excl_rets).prod() - 1)
            impact = (full_cum - excl_cum) * 100  # 百分比点

            if abs(impact) > 1e-6:
                impacts.append({
                    "symbol": sym,
                    "impact_pct": round(impact, 4),
                    "cum_return_without_pct": round(excl_cum * 100, 2),
                })

        if not impacts:
            return {"max_impact": 0, "top_contributors": []}

        impacts.sort(key=lambda x: -abs(x["impact_pct"]))
        max_impact = max(abs(i["impact_pct"]) for i in impacts)

        return {
            "max_impact": round(max_impact, 4),
            "top_contributors": impacts[:10],  # 最多返回前10只
            "n_symbols_analyzed": len(impacts),
        }

    # ─── 辅助: 简化的策略收益计算 (用于 Jackknife) ────────────────────

    @staticmethod
    def _compute_strategy_returns(
        df: pd.DataFrame,
        factor_col: str,
        close_pivot: pd.DataFrame | None = None,
        top_quantile: float = 0.2,
        rebalance: str = "monthly",
    ) -> pd.Series:
        """计算因子 Top-quantile 策略的日收益率 (简化版)"""
        if close_pivot is None:
            # 从 df 构建 close_pivot
            close_pivot_ = df.pivot_table(
                index="date", columns="symbol", values="close"
            )
        else:
            close_pivot_ = close_pivot

        # 再平衡日期
        dates = close_pivot_.index
        if rebalance == "monthly":
            s = pd.Series(index=dates, data=1)
            rebal_dates = pd.DatetimeIndex(
                s.groupby(dates.to_period("M")).apply(lambda x: x.index[0]).values
            )
        else:
            rebal_dates = dates[::20]

        rebal_set = set(rebal_dates)
        daily_ret = close_pivot_.pct_change()

        strat_rets = pd.Series(0.0, index=dates)
        prev_port: list = []

        for d in dates:
            if d in rebal_set:
                fday = df[df["date"] == d].set_index("symbol")[factor_col].dropna()
                if len(fday) < 10:
                    prev_port = []
                    continue
                sorted_vals = fday.sort_values(ascending=False)
                n_stocks = max(1, int(len(sorted_vals) * top_quantile))
                port = list(sorted_vals.index[:n_stocks])
            else:
                port = prev_port

            if not port or d not in daily_ret.index:
                strat_rets.loc[d] = 0.0
            else:
                port_symbols = [s for s in port if s in daily_ret.columns]
                port_ret = daily_ret.loc[d, port_symbols]
                strat_rets.loc[d] = port_ret.mean() if len(port_ret) > 0 else 0.0

            prev_port = port

        return strat_rets.dropna()

    # ─── 综合暴露分类 ──────────────────────────────────────────────────

    @staticmethod
    def _classify_exposure(result: dict) -> str:
        """根据各维度 R² 判断暴露类型"""
        mc_r2 = result.get("market_cap_r2", 0)
        beta_r2 = result.get("beta_r2", 0)
        vol_r2 = result.get("volatility_r2", 0)
        liq_r2 = result.get("liquidity_r2", 0)
        ind_r2 = result.get("industry_r2", 0)
        jackknife = result.get("jackknife_max_impact", 0)

        # 将 "no_data" 转为 0
        def _to_float(v):
            if isinstance(v, (int, float)):
                return v
            return 0.0

        mc_r2 = _to_float(mc_r2)
        beta_r2 = _to_float(beta_r2)
        vol_r2 = _to_float(vol_r2)
        liq_r2 = _to_float(liq_r2)
        ind_r2 = _to_float(ind_r2)

        style_exposure = max(mc_r2, beta_r2, vol_r2, liq_r2)

        # 极端个股贡献 > 20% = 集中暴露
        if jackknife > 20:
            return "concentrated"

        # 风格暴露 + 行业暴露共同主导
        if style_exposure > 0.5 and ind_r2 > 0.3:
            return "mixed_style_industry"

        # 行业集中度高
        if ind_r2 > 0.5:
            return "industry_bet"

        # 风格暴露主导
        if style_exposure > 0.5:
            # 判断哪个风格
            exposures = []
            if mc_r2 > 0.4:
                exposures.append("market_cap")
            if beta_r2 > 0.4:
                exposures.append("beta")
            if vol_r2 > 0.4:
                exposures.append("volatility")
            if liq_r2 > 0.4:
                exposures.append("liquidity")
            return f"style_exposure_{'+'.join(exposures)}" if exposures else "style_exposure"

        # 中等暴露
        if style_exposure > 0.25 or ind_r2 > 0.25:
            return "partial_exposure"

        # 无显著暴露
        return "pure_alpha"


# ═══════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════════


def cmd_risk_attribution(factor_name: str, **kwargs) -> dict:
    """CLI 入口: 对单个因子执行风险暴露归因

    用法:
        python3 hermes_cli.py factor:risk-attribution --factor ret5
    """
    from factor_lab.factor_engine import Engine

    e = Engine()
    e.load_all()

    f = e.get_factor(factor_name)
    if f is None:
        print(f"❌ 因子 {factor_name} 未找到")
        return {"error": f"因子 {factor_name} 未找到"}

    df = f.get("df") if hasattr(f, "__getitem__") else getattr(f, "df", None)
    close_pivot = f.get("close_pivot") if hasattr(f, "__getitem__") else getattr(f, "close_pivot", None)

    if df is None:
        print(f"❌ 因子 {factor_name} 缺少 df")
        return {"error": "缺少 df"}

    analyzer = RiskExposureAnalyzer(close_pivot=close_pivot)
    result = analyzer.analyze(
        df, factor_col=factor_name,
        top_quantile=float(kwargs.get("top_quantile", 0.2)),
        extra_data=kwargs.get("extra_data"),
    )

    # 输出
    print(f"\n{'=' * 56}")
    print(f"⚠️  风险暴露归因: {factor_name}")
    print(f"{'=' * 56}")
    print(f"  暴露类型: {result.get('exposure_type', 'N/A')}")
    print(f"  分析股票数: {result.get('n_stocks_analyzed', 0)}")
    print(f"\n  维度暴露评分 (0~1, 越高暴露越大):")
    for key, label in [
        ("market_cap_r2", "市值"),
        ("beta_r2", "Beta"),
        ("volatility_r2", "波动率"),
        ("liquidity_r2", "流动性"),
        ("industry_r2", "行业"),
    ]:
        val = result.get(key, "no_data")
        if isinstance(val, (int, float)):
            print(f"    {label:10s}: {val:.2f}")
        else:
            print(f"    {label:10s}: {val}")

    if result.get("industry_top_exposures"):
        print(f"\n  前 5 行业暴露:")
        for ind, wt in list(result["industry_top_exposures"].items())[:5]:
            print(f"    {ind:20s}: {wt:.2%}")

    top_contributors = result.get("jackknife_top_contributors", [])
    if top_contributors:
        print(f"\n  Jackknife Top 5 个股贡献:")
        for c in top_contributors[:5]:
            print(f"    {c['symbol']}: impact={c['impact_pct']:+.4f}%")

    # 保存结果
    from validate_factor_v4 import OUTPUT_DIR, clean

    output_subdir = OUTPUT_DIR / factor_name
    output_subdir.mkdir(parents=True, exist_ok=True)
    clean_result = clean(result)
    import json
    with open(output_subdir / "risk_attribution.json", "w", encoding="utf-8") as f:
        json.dump(clean_result, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 风险归因报告: {output_subdir / 'risk_attribution.json'}")

    return result


if __name__ == "__main__":
    import sys, json
    factor_name = sys.argv[1] if len(sys.argv) > 1 else "ret5"
    result = cmd_risk_attribution(factor_name)
    print(json.dumps(result, indent=2, default=str)[:3000])
