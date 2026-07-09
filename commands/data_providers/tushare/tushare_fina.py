#!/usr/bin/env python3
"""
Tushare 财务数据 Provider — TushareFinaProvider

实现 BaseProvider 的 5 个财务数据接口:
  - fina_indicator: 财务指标 (80+ 字段, 2012 年至今)
  - income:         利润表
  - balancesheet:   资产负债表
  - cashflow:       现金流量表
  - forecast:       业绩预告

数据源: Tushare Pro (https://ts.gyzcloud.top)
客户端: factor_lab.data.tushare_client.TushareClient

用法:
    from commands.data_providers.tushare.tushare_fina import TushareFinaProvider

    provider = TushareFinaProvider()
    df = provider.fina_indicator(ts_code="688012.SH", start_date="20240101", end_date="20241231")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd

try:
    from commands.data_providers import BaseProvider, ProviderCapability, ProviderHealth
except ModuleNotFoundError:
    from data_providers import BaseProvider, ProviderCapability, ProviderHealth
from factor_lab.data.tushare_client import get_ts_client

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# Tushare Pro API 名称常量
API_FINA_INDICATOR = "fina_indicator"
API_INCOME = "income"
API_BALANCESHEET = "balancesheet"
API_CASHFLOW = "cashflow"
API_FORECAST = "forecast"


class TushareFinaProvider(BaseProvider):
    """Tushare Pro 财务数据 Provider

    通过 TushareClient 单例查询 Tushare Pro 财务接口,
    返回规范的 DataFrame, 统一日期列为 datetime 类型。

    能力范围:
      - fina_indicator: 2012 年至今, 80+ 财务指标
      - income:         利润表
      - balancesheet:   资产负债表
      - cashflow:       现金流量表
      - forecast:       业绩预告
    """

    def __init__(self):
        self._client = get_ts_client()

    # ─── 能力声明 ───────────────────────────────────────────────

    @property
    def capability(self) -> ProviderCapability:
        """返回此 Provider 的能力声明"""
        return ProviderCapability(
            name="tushare",
            can_fina_indicator=True,
            can_income=True,
            can_balancesheet=True,
            can_cashflow=True,
            can_forecast=True,
            fina_history_years=14,  # 2012 年至今
        )

    # ─── 自检 ───────────────────────────────────────────────────

    def self_check(self) -> ProviderHealth:
        """自检: 验证 Tushare Pro 连接和各财务接口可用性

        尝试依次查询 5 个财务 API (ts_code 为已知样本),
        记录成功/失败状态。

        Returns:
            ProviderHealth: 含每个接口的最新数据日期
        """
        health = ProviderHealth(
            source_id="tushare_pro",
            status="ok",
            last_check=datetime.now(CST).isoformat(),
        )

        sample_code = "688012.SH"  # 中微公司, 长期有数据
        apis = [
            ("fina_indicator", API_FINA_INDICATOR),
            ("income", API_INCOME),
            ("balancesheet", API_BALANCESHEET),
            ("cashflow", API_CASHFLOW),
            ("forecast", API_FORECAST),
        ]

        for label, api_name in apis:
            try:
                df = self._client._query(api_name, ts_code=sample_code, start_date="20240101", end_date="20241231")
                if df is not None and not df.empty:
                    # 取最新 end_date
                    if "end_date" in df.columns:
                        latest = pd.to_datetime(df["end_date"]).max()
                        health.data_freshness[label] = latest.strftime("%Y-%m-%d")
                    elif "ann_date" in df.columns:
                        latest = pd.to_datetime(df["ann_date"]).max()
                        health.data_freshness[label] = latest.strftime("%Y-%m-%d")
                    else:
                        health.data_freshness[label] = f"{len(df)} rows"
                else:
                    health.data_freshness[label] = "empty"
                    health.warnings.append(f"{label}: empty result (no data)")
            except Exception as e:
                health.status = "partial"
                health.errors.append(f"{label} 查询失败: {e}")
                health.data_freshness[label] = "error"

        if health.errors:
            health.status = "partial" if health.status == "ok" else "error"

        # 空数据警告也应降低状态
        if health.warnings and health.status == "ok":
            health.status = "partial"

        return health

    # ─── 辅助方法 ───────────────────────────────────────────────

    @staticmethod
    def _normalize_end_date(df: pd.DataFrame) -> pd.DataFrame:
        """统一处理 end_date / ann_date 等日期列为 datetime"""
        if df.empty:
            return df
        result = df.copy()
        date_cols = ["end_date", "ann_date", "f_ann_date", "report_date"]
        for col in date_cols:
            if col in result.columns:
                result[col] = pd.to_datetime(
                    result[col].astype(str), format="%Y%m%d", errors="coerce"
                )
        return result

    # ─── 财务指标 ───────────────────────────────────────────────

    def fina_indicator(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
        period: str = "",
    ) -> pd.DataFrame:
        """获取财务指标

        返回 ROE, gross_margin, net_margin, debt_to_assets, eps,
        revenue_ps, ocf_ps, bps 等 80+ 财务指标。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 报告期开始 YYYYMMDD
            end_date:   报告期结束 YYYYMMDD
            period:     指定报告期 (如 20241231, 与区间二选一)

        Returns:
            pd.DataFrame: 包含 end_date, ts_code 及各项财务指标

        注意:
            period 参数为 Tushare Pro 特有, 指定具体报告期,
            与 start_date/end_date 互斥。
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if period:
            params["period"] = period

        df = self._client._query(API_FINA_INDICATOR, **params)
        if df.empty:
            logger.info(f"fina_indicator 无数据: ts_code={ts_code}, period={period}")
            return df

        df = self._normalize_end_date(df)
        return df

    # ─── 利润表 ─────────────────────────────────────────────────

    def income(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取利润表

        包含营业收入、营业成本、营业利润、利润总额、净利润等核心科目。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 报告期开始 YYYYMMDD
            end_date:   报告期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 利润表数据, 含 end_date, ts_code 及各科目
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_INCOME, **params)
        if df.empty:
            logger.info(f"income 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_end_date(df)
        return df

    # ─── 资产负债表 ─────────────────────────────────────────────

    def balancesheet(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取资产负债表

        包含流动资产、非流动资产、流动负债、非流动负债、股东权益等核心科目。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 报告期开始 YYYYMMDD
            end_date:   报告期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 资产负债表数据, 含 end_date, ts_code 及各科目
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_BALANCESHEET, **params)
        if df.empty:
            logger.info(f"balancesheet 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_end_date(df)
        return df

    # ─── 现金流量表 ─────────────────────────────────────────────

    def cashflow(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取现金流量表

        包含经营活动现金流、投资活动现金流、筹资活动现金流等核心科目。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 报告期开始 YYYYMMDD
            end_date:   报告期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 现金流量表数据, 含 end_date, ts_code 及各科目
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_CASHFLOW, **params)
        if df.empty:
            logger.info(f"cashflow 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_end_date(df)
        return df

    # ─── 业绩预告 ───────────────────────────────────────────────

    def forecast(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取业绩预告

        包含预告类型(预增/预减/扭亏/首亏等)、净利润变动幅度等。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 公告日期开始 YYYYMMDD
            end_date:   公告日期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 业绩预告数据, 含 end_date, ts_code 及预告内容
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_FORECAST, **params)
        if df.empty:
            logger.info(f"forecast 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_end_date(df)
        return df

    # ─── 其他必要抽象方法 (存根) ───────────────────────────────
    #
    # BaseProvider 还要求以下抽象方法, 但本 Provider 只负责财务数据,
    # 通过 notimplemented 标记让引擎知晓不可用。

    def stock_basic(self, list_status: str = "L") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 stock_basic, 请使用 TushareMarketProvider")

    def trade_cal(self, start_date: str = "20000101", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 trade_cal, 请使用 TushareMarketProvider")

    def daily(self, ts_code: str = "", start_date: str = "", end_date: str = "",
              trade_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 daily, 请使用 TushareMarketProvider")

    def daily_basic(self, ts_code: str = "", trade_date: str = "",
                    start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 daily_basic, 请使用 TushareMarketProvider")

    def adj_factor(self, ts_code: str = "", trade_date: str = "",
                   start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 adj_factor, 请使用 TushareMarketProvider")

    def stk_limit(self, ts_code: str = "", trade_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 stk_limit, 请使用 TushareMarketProvider")

    def suspend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 suspend, 请使用 TushareMarketProvider")

    def namechange(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 namechange, 请使用 TushareMarketProvider")

    def moneyflow(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 moneyflow, 请使用 TushareMarketProvider")

    def index_daily(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 index_daily, 请使用 TushareMarketProvider")

    def hs_const(self) -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 hs_const, 请使用 TushareMarketProvider")

    def moneyflow_hsgt(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 moneyflow_hsgt, 请使用 TushareMarketProvider")

    def hsgt_top10(self, trade_date: str = "", market_type: str = "1") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 hsgt_top10, 请使用 TushareMarketProvider")

    def dividend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 dividend, 请使用 TushareMarketProvider")

    def stk_surv(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 stk_surv, 请使用 TushareMarketProvider")

    def block_trade(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 block_trade, 请使用 TushareMarketProvider")

    def new_share(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareFinaProvider 不支持 new_share, 请使用 TushareMarketProvider")
