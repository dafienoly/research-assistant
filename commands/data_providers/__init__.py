#!/usr/bin/env python3
"""
V4.0 数据源 Provider 抽象基类 — BaseProvider

定义所有数据源 Provider 的统一接口。
每个数据源 Provider 必须实现此类，以保证数据管道可替换、可审计。

用法:
    from commands.data_providers.base_provider import BaseProvider, ProviderCapability

    class TushareProvider(BaseProvider):
        ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd


@dataclass
class ProviderCapability:
    """Provider 能力声明"""
    name: str                                    # 数据源名称 (tushare/baostock/akshare)
    can_daily: bool = False                      # 日线行情
    can_daily_basic: bool = False                # 每日估值/指标
    can_adj_factor: bool = False                 # 复权因子
    can_stk_limit: bool = False                  # 涨跌停价格
    can_suspend: bool = False                    # 停复牌
    can_namechange: bool = False                 # 更名/ST
    can_fina_indicator: bool = False             # 财务指标
    can_income: bool = False                     # 利润表
    can_balancesheet: bool = False               # 资产负债表
    can_cashflow: bool = False                   # 现金流量表
    can_forecast: bool = False                   # 业绩预告
    can_express: bool = False                    # 业绩快报
    can_moneyflow: bool = False                  # 个股资金流向
    can_margin: bool = False                     # 融资融券
    can_top_list: bool = False                  # 龙虎榜
    can_stock_basic: bool = False               # 股票基本信息
    can_trade_cal: bool = False                 # 交易日历
    can_index_daily: bool = False                # 指数日线
    can_concept: bool = False                    # 概念板块
    can_industry: bool = False                   # 行业分类
    can_repurchase: bool = False                 # 回购
    can_share_float: bool = False                # 限售解禁
    can_dividend: bool = False                   # 分红送股
    can_stk_surv: bool = False                   # 机构调研
    can_stk_rewards: bool = False                # 股权激励
    can_stk_holdertrade: bool = False            # 大股东增减持
    can_stk_holdernumber: bool = False           # 股东人数
    can_new_share: bool = False                  # 新股发行
    can_block_trade: bool = False                # 大宗交易
    can_hs_const: bool = False                   # 沪深港通标的
    can_moneyflow_hsgt: bool = False             # 沪深港通资金流向
    can_hsgt_top10: bool = False                 # 沪深港通十大成交
    coverage_start: Optional[str] = None         # 最早可用日期 YYYYMMDD
    coverage_end: Optional[str] = None           # 最晚可用日期 YYYYMMDD
    stock_count: int = 0                         # 覆盖股票数
    daily_history_years: int = 0                 # 日线历史年数
    fina_history_years: int = 0                  # 财务历史年数


@dataclass
class ProviderHealth:
    """Provider 健康状态"""
    source_id: str = ""
    status: str = "unknown"                      # ok / partial / error
    last_check: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_freshness: dict[str, str] = field(default_factory=dict)   # {data_type: latest_date}


class BaseProvider(ABC):
    """所有数据源 Provider 的抽象基类"""

    @property
    @abstractmethod
    def capability(self) -> ProviderCapability:
        """返回此 Provider 的能力声明"""
        ...

    @abstractmethod
    def self_check(self) -> ProviderHealth:
        """自检：验证连接、数据可用性、返回健康状态"""
        ...

    # ─── 股票基础 ───────────────────────────────────────

    @abstractmethod
    def stock_basic(self, list_status: str = "L") -> pd.DataFrame:
        """获取全A股票列表"""
        ...

    @abstractmethod
    def trade_cal(self, start_date: str = "20000101", end_date: str = "") -> pd.DataFrame:
        """获取交易日历"""
        ...

    # ─── 日线行情 ───────────────────────────────────────

    @abstractmethod
    def daily(self, ts_code: str = "", start_date: str = "", end_date: str = "",
              trade_date: str = "") -> pd.DataFrame:
        """获取日线行情"""
        ...

    @abstractmethod
    def daily_basic(self, ts_code: str = "", trade_date: str = "",
                    start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取每日估值数据 (pe/pb/市值/换手率)"""
        ...

    @abstractmethod
    def adj_factor(self, ts_code: str = "", trade_date: str = "",
                   start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取复权因子"""
        ...

    # ─── 交易约束 ───────────────────────────────────────

    @abstractmethod
    def stk_limit(self, ts_code: str = "", trade_date: str = "") -> pd.DataFrame:
        """获取涨跌停价格"""
        ...

    @abstractmethod
    def suspend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取停复牌信息"""
        ...

    @abstractmethod
    def namechange(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取更名/ST 信息"""
        ...

    # ─── 财务数据 ───────────────────────────────────────

    @abstractmethod
    def fina_indicator(self, ts_code: str = "", start_date: str = "", end_date: str = "",
                       period: str = "") -> pd.DataFrame:
        """获取财务指标"""
        ...

    @abstractmethod
    def income(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取利润表"""
        ...

    @abstractmethod
    def balancesheet(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取资产负债表"""
        ...

    @abstractmethod
    def cashflow(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取现金流量表"""
        ...

    @abstractmethod
    def forecast(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取业绩预告"""
        ...

    # ─── 资金流向 ───────────────────────────────────────

    @abstractmethod
    def moneyflow(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取个股资金流向 (大/中/小单)"""
        ...

    # ─── 指数 ───────────────────────────────────────────

    @abstractmethod
    def index_daily(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取指数日线"""
        ...

    # ─── 沪深港通 ───────────────────────────────────────

    @abstractmethod
    def hs_const(self) -> pd.DataFrame:
        """获取沪深港通标的列表"""
        ...

    @abstractmethod
    def moneyflow_hsgt(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取沪深港通资金流向"""
        ...

    @abstractmethod
    def hsgt_top10(self, trade_date: str = "", market_type: str = "1") -> pd.DataFrame:
        """获取沪深港通十大成交股"""
        ...

    # ─── 事件与公司行为 ─────────────────────────────────

    @abstractmethod
    def dividend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取分红送股"""
        ...

    @abstractmethod
    def stk_surv(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取机构调研"""
        ...

    @abstractmethod
    def block_trade(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取大宗交易"""
        ...

    @abstractmethod
    def new_share(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取新股发行"""
        ...

    # ─── 辅助方法 ───────────────────────────────────────

    def normalize_date(self, df: pd.DataFrame, date_col: str = "trade_date") -> pd.DataFrame:
        """统一日期列为 datetime"""
        if date_col in df.columns and not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df = df.copy()
            df[date_col] = pd.to_datetime(df[date_col].astype(str), format="%Y%m%d", errors="coerce")
        return df
