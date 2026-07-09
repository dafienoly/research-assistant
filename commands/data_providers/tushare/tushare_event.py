#!/usr/bin/env python3
"""
Tushare 事件与公司行为 Provider — TushareEventProvider

实现 BaseProvider 的事件/公司行为接口:
  - dividend        — 分红送股
  - stk_surv        — 机构调研
  - block_trade     — 大宗交易
  - new_share       — 新股发行 / IPO
  - repurchase      — 股票回购
  - share_float     — 限售解禁
  - stk_holdertrade — 大股东增减持（高管及持股 5% 以上股东）
  - stk_holdernumber— 股东人数
  - stk_rewards     — 股权激励

数据源: Tushare Pro (https://ts.gyzcloud.top)
客户端: factor_lab.data.tushare_client.TushareClient

用法:
    from commands.data_providers.tushare import TushareEventProvider

    provider = TushareEventProvider()
    df = provider.dividend(ts_code="688012.SH", start_date="20240101", end_date="20241231")
    df = provider.stk_surv(ts_code="688012.SH", start_date="20230101", end_date="20241231")
    df = provider.block_trade(ts_code="688012.SH", start_date="20240101", end_date="20240630")
    df = provider.new_share(start_date="20240101", end_date="20240630")
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

# ─── Tushare Pro API 名称常量 ─────────────────────────────────────
API_DIVIDEND = "dividend"
API_STK_SURV = "stk_surv"
API_BLOCK_TRADE = "block_trade"
API_NEW_SHARE = "new_share"
API_REPURCHASE = "repurchase"
API_SHARE_FLOAT = "share_float"
API_STK_HOLDERTRADE = "stk_holdertrade"
API_STK_HOLDERNUMBER = "stk_holdernumber"
API_STK_REWARDS = "stk_rewards"


class TushareEventProvider(BaseProvider):
    """Tushare Pro 事件与公司行为 Provider

    通过 TushareClient 单例查询 Tushare Pro 事件/公司行为接口,
    返回规范的 DataFrame, 统一日期列为 datetime 类型。

    能力范围:
      - dividend:        分红送股 (上市以来)
      - stk_surv:        机构调研 (2013 年至今)
      - block_trade:     大宗交易 (2008 年至今)
      - new_share:       新股发行 (2010 年至今)
      - repurchase:      股票回购 (2015 年至今)
      - share_float:     限售解禁 (2005 年至今)
      - stk_holdertrade: 大股东增减持 (2010 年至今)
      - stk_holdernumber:股东人数 (2010 年至今)
      - stk_rewards:     股权激励 (2005 年至今)
    """

    def __init__(self):
        self._client = get_ts_client()

    # ─── 能力声明 ───────────────────────────────────────────────

    @property
    def capability(self) -> ProviderCapability:
        """返回此 Provider 的能力声明"""
        return ProviderCapability(
            name="tushare",
            can_dividend=True,
            can_stk_surv=True,
            can_block_trade=True,
            can_new_share=True,
            can_repurchase=True,
            can_share_float=True,
            can_stk_holdertrade=True,
            can_stk_holdernumber=True,
            can_stk_rewards=True,
        )

    # ─── 自检 ───────────────────────────────────────────────────

    def self_check(self) -> ProviderHealth:
        """自检: 验证 Tushare Pro 连接及各事件/公司行为接口可用性

        依次查询 9 个 API (样本 ts_code 为 688012.SH / 中微公司),
        记录成功/失败状态和最新数据日期。

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
            ("dividend",        API_DIVIDEND,        {"ts_code": sample_code, "start_date": "20200101", "end_date": "20241231"}),
            ("stk_surv",        API_STK_SURV,        {"ts_code": sample_code, "start_date": "20230101", "end_date": "20241231"}),
            ("block_trade",     API_BLOCK_TRADE,     {"ts_code": sample_code, "start_date": "20240101", "end_date": "20241231"}),
            ("new_share",       API_NEW_SHARE,       {"start_date": "20240101", "end_date": "20241231"}),
            ("repurchase",      API_REPURCHASE,      {"ts_code": sample_code, "ann_date": "20240601"}),
            ("share_float",     API_SHARE_FLOAT,     {"ts_code": sample_code, "start_date": "20230101", "end_date": "20241231"}),
            ("stk_holdertrade", API_STK_HOLDERTRADE, {"ts_code": sample_code, "start_date": "20230101", "end_date": "20241231"}),
            ("stk_holdernumber",API_STK_HOLDERNUMBER,{"ts_code": sample_code, "start_date": "20230101", "end_date": "20241231"}),
            ("stk_rewards",     API_STK_REWARDS,     {"ts_code": sample_code, "start_date": "20200101", "end_date": "20241231"}),
        ]

        for label, api_name, params in apis:
            try:
                df = self._client._query(api_name, **params)
                if df is not None and not df.empty:
                    # 取最新的日期列
                    freshness = _extract_freshness(df)
                    health.data_freshness[label] = freshness
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
    def _normalize_dates(df: pd.DataFrame, date_cols: Optional[list[str]] = None) -> pd.DataFrame:
        """统一处理日期列为 datetime

        Args:
            df:         输入的 DataFrame
            date_cols:  需要转换的列名列表; None 时自动检测常见日期列

        Returns:
            转换后的 DataFrame (copy)
        """
        if df.empty:
            return df
        result = df.copy()
        if date_cols is None:
            date_cols = [
                "ann_date", "end_date", "record_date", "ex_date",
                "pay_date", "div_listdate", "float_date", "trade_date",
                "change_date", "effect_date", "notice_date",
                "surv_date", "start_date", "end_date",
            ]
        for col in date_cols:
            if col in result.columns:
                result[col] = pd.to_datetime(
                    result[col].astype(str), format="%Y%m%d", errors="coerce"
                )
        return result

    # ─── 分红送股 ───────────────────────────────────────────────

    def dividend(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取分红送股信息

        基于 Tushare Pro dividend 接口，包含上市公司分红送股数据，
        涵盖送股、转增、派息等股本变动事件。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 公告日期开始 YYYYMMDD
            end_date:   公告日期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 分红送股数据
                含 ts_code, ann_date, end_date, stk_div, stk_bo,
                stk_trans, cash_div, ...（日期列已转为 datetime）
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_DIVIDEND, **params)
        if df.empty:
            logger.info(f"dividend 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_dates(df)
        return df

    # ─── 机构调研 ───────────────────────────────────────────────

    def stk_surv(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取机构调研记录

        基于 Tushare Pro stk_surv 接口，包含上市公司接待机构调研的记录，
        含调研机构列表、调研类别、接待人员等信息。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 公告日期开始 YYYYMMDD
            end_date:   公告日期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 机构调研数据
                含 ts_code, surv_date, com_name, fund_name,
                surv_type, org_type, ...（日期列已转为 datetime）
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_STK_SURV, **params)
        if df.empty:
            logger.info(f"stk_surv 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_dates(df)
        return df

    # ─── 大宗交易 ───────────────────────────────────────────────

    def block_trade(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取大宗交易记录

        基于 Tushare Pro block_trade 接口，包含单笔成交额或成交量较大的交易信息，
        涵盖买卖方营业部、成交折溢价等细节。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 成交日期开始 YYYYMMDD
            end_date:   成交日期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 大宗交易数据
                含 ts_code, trade_date, price, vol, amount,
                buyer, seller, ...（日期列已转为 datetime）
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_BLOCK_TRADE, **params)
        if df.empty:
            logger.info(f"block_trade 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_dates(df)
        return df

    # ─── 新股发行 ───────────────────────────────────────────────

    def new_share(
        self,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取新股发行/IPO 数据

        基于 Tushare Pro new_share 接口，A 股新股发行信息，
        包含发行价、发行量、中签率、募资额等。

        Args:
            start_date: 发行日期开始 YYYYMMDD
            end_date:   发行日期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 新股发行数据
                含 ts_code, ipo_amount, issue_price, issue_amount,
                hy_pdf, win_rate, ...（日期列已转为 datetime）
        """
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_NEW_SHARE, **params)
        if df.empty:
            logger.info(f"new_share 无数据: start_date={start_date}")
            return df

        df = self._normalize_dates(df)
        return df

    # ─── 股票回购 ───────────────────────────────────────────────

    def repurchase(
        self,
        ts_code: str = "",
        ann_date: str = "",
    ) -> pd.DataFrame:
        """获取股票回购数据

        基于 Tushare Pro repurchase 接口，上市公司股份回购记录，
        包含回购进度、金额、数量等。

        Args:
            ts_code:  股票代码 (如 688012.SH), 为空时返回全部
            ann_date: 公告日期 YYYYMMDD, 按公告日期查询

        Returns:
            pd.DataFrame: 股票回购数据
                含 ts_code, ann_date, end_date, progress, amount,
                vol, purpose, ...（日期列已转为 datetime）

        Note:
            Tushare repurchase 接口支持 ann_date 精确到日,
            但 ts_code + start_date / end_date 也可使用。
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if ann_date:
            params["ann_date"] = ann_date

        df = self._client._query(API_REPURCHASE, **params)
        if df.empty:
            logger.info(f"repurchase 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_dates(df)
        return df

    # ─── 限售解禁 ───────────────────────────────────────────────

    def share_float(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取限售解禁数据

        基于 Tushare Pro share_float 接口，限售股解禁信息，
        包含解禁数量、占股本比例、解禁批次等。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 解禁日期开始 YYYYMMDD
            end_date:   解禁日期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 限售解禁数据
                含 ts_code, float_date, vol, ratio, name, ...（日期列已转为 datetime）
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_SHARE_FLOAT, **params)
        if df.empty:
            logger.info(f"share_float 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_dates(df)
        return df

    # ─── 大股东增减持 ───────────────────────────────────────────

    def stk_holdertrade(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取大股东增减持记录

        基于 Tushare Pro stk_holdertrade 接口，持股 5% 以上股东及高管
        的二级市场交易记录，包含变动方向、数量、均价等。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 交易日期开始 YYYYMMDD
            end_date:   交易日期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 股东增减持数据
                含 ts_code, change_date, vol, change_ratio, trade_type,
                holder_name, ...（日期列已转为 datetime）
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_STK_HOLDERTRADE, **params)
        if df.empty:
            logger.info(f"stk_holdertrade 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_dates(df)
        return df

    # ─── 股东人数 ───────────────────────────────────────────────

    def stk_holdernumber(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取股东人数（含户均持股）

        基于 Tushare Pro stk_holdernumber 接口，股东户数变化数据，
        可用于筹码集中度分析。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 公告日期开始 YYYYMMDD
            end_date:   公告日期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 股东人数数据
                含 ts_code, ann_date, end_date, holder_number,
                holder_avg_stake, ...（日期列已转为 datetime）
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_STK_HOLDERNUMBER, **params)
        if df.empty:
            logger.info(f"stk_holdernumber 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_dates(df)
        return df

    # ─── 股权激励 ───────────────────────────────────────────────

    def stk_rewards(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取股权激励计划

        基于 Tushare Pro stk_rewards 接口，上市公司股权激励方案，
        包含激励方式、授予数量、行权价格等。

        Args:
            ts_code:    股票代码 (如 688012.SH), 为空时返回全部
            start_date: 公告日期开始 YYYYMMDD
            end_date:   公告日期结束 YYYYMMDD

        Returns:
            pd.DataFrame: 股权激励数据
                含 ts_code, ann_date, end_date, reward_type,
                granted_qty, exercise_price, ...（日期列已转为 datetime）
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_STK_REWARDS, **params)
        if df.empty:
            logger.info(f"stk_rewards 无数据: ts_code={ts_code}")
            return df

        df = self._normalize_dates(df)
        return df

    # ─── 其他必要抽象方法 (存根) ───────────────────────────────
    #
    # BaseProvider 还要求以下抽象方法, 但本 Provider 只负责事件/公司行为,
    # 通过 NotImplementedError 告知引擎不可用。

    def stock_basic(self, list_status: str = "L") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 stock_basic, 请使用 TushareStockProvider")

    def trade_cal(self, start_date: str = "20000101", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 trade_cal, 请使用 TushareStockProvider")

    def daily(self, ts_code: str = "", start_date: str = "", end_date: str = "",
              trade_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 daily, 请使用 TushareMarketProvider")

    def daily_basic(self, ts_code: str = "", trade_date: str = "",
                    start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 daily_basic, 请使用 TushareMarketProvider")

    def adj_factor(self, ts_code: str = "", trade_date: str = "",
                   start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 adj_factor, 请使用 TushareMarketProvider")

    def stk_limit(self, ts_code: str = "", trade_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 stk_limit, 请使用 TushareMarketProvider")

    def suspend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 suspend, 请使用 TushareStockProvider")

    def namechange(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 namechange, 请使用 TushareStockProvider")

    def fina_indicator(self, ts_code: str = "", start_date: str = "",
                       end_date: str = "", period: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 fina_indicator, 请使用 TushareFinaProvider")

    def income(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 income, 请使用 TushareFinaProvider")

    def balancesheet(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 balancesheet, 请使用 TushareFinaProvider")

    def cashflow(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 cashflow, 请使用 TushareFinaProvider")

    def forecast(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 forecast, 请使用 TushareFinaProvider")

    def moneyflow(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 moneyflow, 请使用 TushareFundFlowProvider")

    def index_daily(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 index_daily, 请使用 TushareStockProvider")

    def hs_const(self) -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 hs_const, 请使用 TushareFundFlowProvider")

    def moneyflow_hsgt(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 moneyflow_hsgt, 请使用 TushareFundFlowProvider")

    def hsgt_top10(self, trade_date: str = "", market_type: str = "1") -> pd.DataFrame:
        raise NotImplementedError("TushareEventProvider 不支持 hsgt_top10, 请使用 TushareFundFlowProvider")


# ─── 模块级辅助 ──────────────────────────────────────────────────


def _extract_freshness(df: pd.DataFrame) -> str:
    """从 DataFrame 中提取最新日期字符串

    优先尝试常见的日期列名, 取最大日期。

    Args:
        df: 数据 DataFrame

    Returns:
        最新日期的 YYYYMMDD 字符串或行数描述
    """
    date_cols_candidates = [
        "ann_date", "end_date", "trade_date", "change_date",
        "float_date", "record_date", "ex_date", "surv_date",
    ]
    for col in date_cols_candidates:
        if col in df.columns:
            try:
                latest = pd.to_datetime(df[col]).max()
                return latest.strftime("%Y%m%d")
            except Exception:
                continue
    return f"{len(df)} rows"
