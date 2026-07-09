#!/usr/bin/env python3
"""
Tushare 市场数据 Provider — daily / daily_basic / adj_factor / stk_limit

封装 Tushare Pro 日线行情及交易约束数据，基于 TushareClient 实现 BaseProvider
接口中的市场数据相关方法。

用法:
    from commands.data_providers.tushare import TushareMarketProvider

    provider = TushareMarketProvider()
    df_daily = provider.daily(ts_code="688012.SH", start_date="20240101", end_date="20240131")
    df_basic = provider.daily_basic(trade_date="20240115")
    df_adj   = provider.adj_factor(ts_code="688012.SH", start_date="20240101", end_date="20240131")
    df_limit = provider.stk_limit(ts_code="688012.SH", trade_date="20240115")
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


class TushareMarketProvider(BaseProvider):
    """Tushare 市场数据 Provider

    基于 TushareClient (get_ts_client 单例) 实现 BaseProvider 中市场数据相关的方法:
      - daily        日线行情 (前复权)
      - daily_basic  每日估值指标 (PE/PB/市值/换手率)
      - adj_factor   复权因子
      - stk_limit    涨跌停价格

    其余抽象方法以 NotImplementedError 占位，待后续扩展。
    """

    def __init__(self):
        self._client = get_ts_client()
        self._capability = ProviderCapability(
            name="tushare",
            can_daily=True,
            can_daily_basic=True,
            can_adj_factor=True,
            can_stk_limit=True,
            coverage_start="20000101",
            coverage_end=datetime.now(CST).strftime("%Y%m%d"),
        )

    # ── 能力声明 ─────────────────────────────────────────────────

    @property
    def capability(self) -> ProviderCapability:
        """返回此 Provider 的能力声明"""
        return self._capability

    # ── 自检 ─────────────────────────────────────────────────────

    def self_check(self) -> ProviderHealth:
        """自检：验证 Tushare 连接与日线数据可用性

        Returns:
            ProviderHealth: 含状态、错误、数据新鲜度
        """
        health = ProviderHealth(source_id="tushare_market", status="unknown")
        try:
            # 用 trade_cal 验证连接
            df_cal = self.trade_cal(start_date="20260101", end_date="20260110")
            if df_cal.empty:
                health.status = "error"
                health.errors.append("trade_cal 返回空")
            else:
                health.status = "ok"
                health.data_freshness["trade_cal"] = "ok"

            # 验证 daily 数据
            df_daily = self._client._query("daily", ts_code="000001.SZ", start_date="20260101", end_date="20260110")
            if df_daily.empty:
                health.warnings.append("daily 日线数据采样空 (可能非交易日)")
            else:
                latest = df_daily["trade_date"].max()
                health.data_freshness["daily"] = str(latest)[:10] if hasattr(latest, "strftime") else str(latest)

            # 验证 stk_limit
            df_limit = self._client._query("stk_limit", ts_code="000001.SZ", trade_date="20260105")
            if df_limit.empty:
                health.warnings.append("stk_limit 采样空")

        except Exception as e:
            health.status = "error"
            health.errors.append(str(e))

        return health

    # ── 股票基础 ─────────────────────────────────────────────────

    def stock_basic(self, list_status: str = "L") -> pd.DataFrame:
        """获取全 A 股票列表 (委托给 TushareClient)

        Args:
            list_status: L=上市 D=退市 P=暂停上市

        Returns:
            DataFrame: ts_code, name, area, industry, market, list_date, ...
        """
        return self._client.stock_basic(list_status=list_status)

    def trade_cal(self, start_date: str = "20000101", end_date: str = "") -> pd.DataFrame:
        """获取交易日历 (委托给 TushareClient)

        Args:
            start_date: 开始日期 YYYYMMDD
            end_date:   结束日期 YYYYMMDD (默认当天)

        Returns:
            DataFrame: cal_date, is_open, pretrade_date
        """
        return self._client.trade_cal(start_date=start_date, end_date=end_date)

    # ═══════════════════════════════════════════════════════════════
    # 日线行情
    # ═══════════════════════════════════════════════════════════════

    def daily(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
        trade_date: str = "",
    ) -> pd.DataFrame:
        """获取日线行情 (前复权)

        通过 tc._query('daily', ...) 调用 Tushare Pro API。

        Args:
            ts_code:   股票代码 (如 688012.SH, 000001.SZ)
            start_date: 开始日期 YYYYMMDD
            end_date:   结束日期 YYYYMMDD
            trade_date: 指定交易日 (与区间二选一)

        Returns:
            DataFrame 列:
                ts_code     - 股票代码
                trade_date  - 交易日 (datetime)
                open        - 开盘价
                high        - 最高价
                low         - 最低价
                close       - 收盘价
                pre_close   - 前收盘价
                change      - 涨跌额
                pct_chg     - 涨跌幅 (%)
                vol         - 成交量 (手)
                amount      - 成交额 (元)

        Raises:
            ValueError: 未提供任何查询参数
        """
        if not any([ts_code, trade_date, start_date, end_date]):
            raise ValueError("至少需要提供 ts_code、trade_date 或日期区间之一")

        params: dict[str, str] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        else:
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

        df = self._client._query("daily", **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        # 按股票代码和日期排序
        if "trade_date" in df.columns:
            df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        return df

    # ═══════════════════════════════════════════════════════════════
    # 每日估值
    # ═══════════════════════════════════════════════════════════════

    def daily_basic(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取每日估值 / 基本面指标

        通过 tc._query('daily_basic', ...) 调用 Tushare Pro API。

        Args:
            ts_code:    股票代码
            trade_date: 交易日 YYYYMMDD (与区间二选一)
            start_date: 开始日期 YYYYMMDD
            end_date:   结束日期 YYYYMMDD

        Returns:
            DataFrame 列:
                ts_code       - 股票代码
                trade_date    - 交易日 (datetime)
                pe            - 市盈率 (动态)
                pe_ttm        - 市盈率 TTM
                pb            - 市净率
                total_mv      - 总市值 (元)
                circ_mv       - 流通市值 (元)
                turnover_rate - 换手率 (%)
                volume_ratio  - 量比
                free_share    - 流通股本 (股)
                total_share   - 总股本 (股)

        Raises:
            ValueError: 未提供任何查询参数
        """
        if not any([ts_code, trade_date, start_date, end_date]):
            raise ValueError("至少需要提供 ts_code、trade_date 或日期区间之一")

        params: dict[str, str] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        else:
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

        df = self._client._query("daily_basic", **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        # 按股票代码和日期排序
        if "trade_date" in df.columns:
            df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        return df

    # ═══════════════════════════════════════════════════════════════
    # 复权因子
    # ═══════════════════════════════════════════════════════════════

    def adj_factor(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取复权因子

        通过 tc._query('adj_factor', ...) 调用 Tushare Pro API。
        用于将不复权价格转为前复权或后复权价格。

        Args:
            ts_code:    股票代码
            trade_date: 交易日 YYYYMMDD (与区间二选一)
            start_date: 开始日期 YYYYMMDD
            end_date:   结束日期 YYYYMMDD

        Returns:
            DataFrame 列:
                ts_code    - 股票代码
                trade_date - 交易日 (datetime)
                adj_factor - 复权因子

        Raises:
            ValueError: 未提供任何查询参数
        """
        if not any([ts_code, trade_date, start_date, end_date]):
            raise ValueError("至少需要提供 ts_code、trade_date 或日期区间之一")

        params: dict[str, str] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        else:
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

        df = self._client._query("adj_factor", **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        # 按股票代码和日期排序
        if "trade_date" in df.columns:
            df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        return df

    # ═══════════════════════════════════════════════════════════════
    # 涨跌停价格
    # ═══════════════════════════════════════════════════════════════

    def stk_limit(
        self,
        ts_code: str = "",
        trade_date: str = "",
    ) -> pd.DataFrame:
        """获取涨跌停价格

        通过 tc._query('stk_limit', ...) 调用 Tushare Pro API。

        Args:
            ts_code:    股票代码
            trade_date: 交易日 YYYYMMDD

        Returns:
            DataFrame 列:
                ts_code      - 股票代码
                trade_date   - 交易日 (datetime)
                up_limit     - 涨停价
                down_limit   - 跌停价
                pre_close    - 前收盘价

        Raises:
            ValueError: 未提供 ts_code 或 trade_date
        """
        if not ts_code and not trade_date:
            raise ValueError("至少需要提供 ts_code 或 trade_date 之一")

        params: dict[str, str] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date

        df = self._client._query("stk_limit", **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        # 按股票代码和日期排序
        if "trade_date" in df.columns:
            df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        return df

    # ═══════════════════════════════════════════════════════════════
    # 以下为尚未实现的抽象方法占位
    # ═══════════════════════════════════════════════════════════════

    def suspend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取停复牌信息 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 suspend")

    def namechange(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取更名/ST 信息 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 namechange")

    def fina_indicator(self, ts_code: str = "", start_date: str = "", end_date: str = "",
                       period: str = "") -> pd.DataFrame:
        """获取财务指标 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 fina_indicator")

    def income(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取利润表 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 income")

    def balancesheet(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取资产负债表 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 balancesheet")

    def cashflow(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取现金流量表 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 cashflow")

    def forecast(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取业绩预告 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 forecast")

    def moneyflow(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取个股资金流向 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 moneyflow")

    def index_daily(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取指数日线 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 index_daily")

    def hs_const(self) -> pd.DataFrame:
        """获取沪深港通标的 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 hs_const")

    def moneyflow_hsgt(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取沪深港通资金流向 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 moneyflow_hsgt")

    def hsgt_top10(self, trade_date: str = "", market_type: str = "1") -> pd.DataFrame:
        """获取沪深港通十大成交股 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 hsgt_top10")

    def dividend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取分红送股 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 dividend")

    def stk_surv(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取机构调研 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 stk_surv")

    def block_trade(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取大宗交易 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 block_trade")

    def new_share(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取新股发行 (暂未实现)"""
        raise NotImplementedError("TushareMarketProvider 暂未实现 new_share")
