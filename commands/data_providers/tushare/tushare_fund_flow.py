#!/usr/bin/env python3
"""
Tushare 资金流向 Provider — moneyflow / hsgt / margin / top_list

实现 BaseProvider 中资金流向、沪深港通、融资融券、龙虎榜相关接口:

抽象方法（必须实现）:
  - moneyflow        个股资金流向 (大/中/小单)
  - hs_const         沪深港通标的列表
  - moneyflow_hsgt   沪深港通资金流向
  - hsgt_top10       沪深港通十大成交股

额外实现（非抽象方法，Tushare 特有）:
  - margin           融资融券交易汇总
  - top_list         龙虎榜榜单
  - top_inst         龙虎榜机构明细

用法:
    from commands.data_providers.tushare import TushareFundFlowProvider

    provider = TushareFundFlowProvider()
    df = provider.moneyflow(ts_code="688012.SH", start_date="20240101", end_date="20240131")
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
from factor_lab.data import tushare_client

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# Tushare Pro API 名称常量
API_MONEYFLOW = "moneyflow"
API_HS_CONST = "hs_const"
API_MONEYFLOW_HSGT = "moneyflow_hsgt"
API_HSGT_TOP10 = "hsgt_top10"
API_MARGIN = "margin"
API_TOP_LIST = "top_list"
API_TOP_INST = "top_inst"


class TushareFundFlowProvider(BaseProvider):
    """Tushare Pro 资金流向 Provider

    Tushare Pro 相关的资金流向、沪深港通、融资融券、龙虎榜数据接口。

    能力范围:
      - moneyflow:      个股资金流向（大单/中单/小单）
      - hs_const:       沪深港通成份股
      - moneyflow_hsgt: 沪深港通资金流向
      - hsgt_top10:     沪深港通十大成交
      - margin:         融资融券明细
      - top_list:       龙虎榜明细
      - top_inst:       龙虎榜机构交易明细
    """

    def __init__(self):
        self._client = tushare_client.get_ts_client()

    # ─── 能力声明 ───────────────────────────────────────────────

    @property
    def capability(self) -> ProviderCapability:
        """返回此 Provider 的能力声明"""
        return ProviderCapability(
            name="tushare",
            can_moneyflow=True,
            can_hs_const=True,
            can_moneyflow_hsgt=True,
            can_hsgt_top10=True,
            can_margin=True,
            can_top_list=True,
            coverage_start="20000101",
            coverage_end=datetime.now(CST).strftime("%Y%m%d"),
        )

    # ─── 自检 ───────────────────────────────────────────────────

    def self_check(self) -> ProviderHealth:
        """自检：验证 Tushare Pro 连接和各资金流向接口可用性

        Returns:
            ProviderHealth: 含每个接口的状态及最新数据日期
        """
        health = ProviderHealth(
            source_id="tushare_fund_flow",
            status="ok",
            last_check=datetime.now(CST).isoformat(),
        )

        sample_code = "688012.SH"
        apis = [
            ("moneyflow", API_MONEYFLOW),
            ("hs_const", API_HS_CONST),
            ("moneyflow_hsgt", API_MONEYFLOW_HSGT),
            ("hsgt_top10", API_HSGT_TOP10),
            ("margin", API_MARGIN),
            ("top_list", API_TOP_LIST),
            ("top_inst", API_TOP_INST),
        ]

        for label, api_name in apis:
            try:
                params: dict[str, str] = {}
                if api_name == API_HS_CONST:
                    pass  # 无需参数
                elif api_name in (API_TOP_LIST, API_TOP_INST):
                    params["trade_date"] = "20260708"
                elif api_name == API_HSGT_TOP10:
                    params["trade_date"] = "20260708"
                    params["market_type"] = "1"
                elif api_name in (API_MONEYFLOW, API_MARGIN):
                    params["ts_code"] = sample_code
                    params["start_date"] = "20260701"
                    params["end_date"] = "20260708"
                elif api_name == API_MONEYFLOW_HSGT:
                    params["start_date"] = "20260701"
                    params["end_date"] = "20260708"

                df = self._client._query(api_name, **params)
                if df is not None and not df.empty:
                    if "trade_date" in df.columns:
                        latest = pd.to_datetime(df["trade_date"]).max()
                        health.data_freshness[label] = latest.strftime("%Y-%m-%d")
                    elif "cal_date" in df.columns:
                        latest = pd.to_datetime(df["cal_date"]).max()
                        health.data_freshness[label] = latest.strftime("%Y-%m-%d")
                    else:
                        health.data_freshness[label] = f"{len(df)} rows"
                else:
                    health.data_freshness[label] = "empty"
                    health.warnings.append(f"{label}: empty result")
            except Exception as e:
                health.status = "partial"
                health.errors.append(f"{label} 查询失败: {e}")
                health.data_freshness[label] = "error"

        if health.warnings and health.status == "ok":
            health.status = "partial"

        return health

    # ═══════════════════════════════════════════════════════════════
    # 个股资金流向
    # ═══════════════════════════════════════════════════════════════

    def moneyflow(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取个股资金流向（大单/中单/小单）

        通过 tc._query('moneyflow', ...) 调用 Tushare Pro API。
        包含主力净流入、超大单/大单/中单/小单的净流入额及占比。

        Args:
            ts_code:    股票代码（如 688012.SH）
            start_date: 开始日期 YYYYMMDD
            end_date:   结束日期 YYYYMMDD

        Returns:
            DataFrame 列:
                ts_code           - 股票代码
                trade_date        - 交易日 (datetime)
                buy_sm_vol        - 小单买入量 (手)
                buy_sm_amount     - 小单买入金额 (万元)
                sell_sm_vol       - 小单卖出量 (手)
                sell_sm_amount    - 小单卖出金额 (万元)
                buy_md_vol        - 中单买入量 (手)
                buy_md_amount     - 中单买入金额 (万元)
                sell_md_vol       - 中单卖出量 (手)
                sell_md_amount    - 中单卖出金额 (万元)
                buy_lg_vol        - 大单买入量 (手)
                buy_lg_amount     - 大单买入金额 (万元)
                sell_lg_vol       - 大单卖出量 (手)
                sell_lg_amount    - 大单卖出金额 (万元)
                buy_elg_vol       - 超大单买入量 (手)
                buy_elg_amount    - 超大单买入金额 (万元)
                sell_elg_vol      - 超大单卖出量 (手)
                sell_elg_amount   - 超大单卖出金额 (万元)
                net_mf_amount     - 净流入额 (万元)
                net_mf_vol        - 净流入量 (手)
                ...               - 其它 Tushare 原生字段

        注意:
            ts_code 为必填参数，不支持全市场查询。
        """
        params: dict[str, str] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_MONEYFLOW, **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        # 按股票代码和日期排序
        if "trade_date" in df.columns:
            df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        return df

    # ═══════════════════════════════════════════════════════════════
    # 沪深港通
    # ═══════════════════════════════════════════════════════════════

    def hs_const(self) -> pd.DataFrame:
        """获取沪深港通标的列表

        通过 tc._query('hs_const') 调用 Tushare Pro API。
        返回沪股通/深股通/港股通可交易的成份股。

        Returns:
            DataFrame 列:
                ts_code     - 股票代码
                name        - 股票名称
                holder      - 持有人类型（H 港股通 / S 沪深股通）
                in_date     - 纳入日期 (datetime)
                out_date    - 调出日期 (datetime, NaT 表示未调出)
                is_valid    - 是否有效（Y/N）
        """
        df = self._client._query(API_HS_CONST)
        if df.empty:
            return df

        df = df.copy()

        # 日期列标准化
        for col in ("in_date", "out_date"):
            if col in df.columns:
                df[col] = pd.to_datetime(
                    df[col].astype(str), format="%Y%m%d", errors="coerce"
                )

        return df

    def moneyflow_hsgt(
        self,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取沪深港通资金流向

        通过 tc._query('moneyflow_hsgt', ...) 调用 Tushare Pro API。
        包含北向/南向资金的每日净买入、累计净买入等。

        Args:
            start_date: 开始日期 YYYYMMDD
            end_date:   结束日期 YYYYMMDD

        Returns:
            DataFrame 列:
                trade_date    - 交易日 (datetime)
                ggt_ss        - 沪股通（亿元）
                ggt_sz        - 深股通（亿元）
                ggt_amount    - 沪深合计（亿元）
                hgt_sh        - 港股通（沪）
                hgt_sz        - 港股通（深）
                ...           - 其它 Tushare 原生字段
        """
        params: dict[str, str] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_MONEYFLOW_HSGT, **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        # 按日期排序
        if "trade_date" in df.columns:
            df = df.sort_values("trade_date").reset_index(drop=True)

        return df

    def hsgt_top10(
        self,
        trade_date: str = "",
        market_type: str = "1",
    ) -> pd.DataFrame:
        """获取沪深港通十大成交股

        通过 tc._query('hsgt_top10', ...) 调用 Tushare Pro API。
        列出指定交易日北向/南向资金成交额最高的 10 只股票。

        Args:
            trade_date:  交易日 YYYYMMDD（必填）
            market_type: 市场类型
                         1 = 沪股通
                         3 = 深股通

        Returns:
            DataFrame 列:
                trade_date - 交易日 (datetime)
                ts_code    - 股票代码
                name       - 股票名称
                close      - 收盘价
                pct_change - 涨跌幅
                amount     - 成交额（万元）
                net_amount - 净买入额（万元）
                ...        - 其它 Tushare 原生字段

        Raises:
            ValueError: 未提供 trade_date
        """
        if not trade_date:
            raise ValueError("hsgt_top10 需要提供 trade_date 参数")

        params: dict[str, str] = {
            "trade_date": trade_date,
            "market_type": market_type,
        }

        df = self._client._query(API_HSGT_TOP10, **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        # 按成交额排序（如有 amount 列）
        if "amount" in df.columns:
            df = df.sort_values("amount", ascending=False).reset_index(drop=True)

        return df

    # ═══════════════════════════════════════════════════════════════
    # 融资融券
    # ═══════════════════════════════════════════════════════════════

    def margin(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取融资融券交易汇总

        通过 tc._query('margin', ...) 调用 Tushare Pro API。
        包含融资余额、融资买入额、融券余额、融券卖出量等。

        Args:
            ts_code:    股票代码（如 688012.SH）
            start_date: 开始日期 YYYYMMDD
            end_date:   结束日期 YYYYMMDD

        Returns:
            DataFrame 列:
                ts_code    - 股票代码
                trade_date - 交易日 (datetime)
                rzye       - 融资余额（万元）
                rzmre      - 融资买入额（万元）
                rqye       - 融券余额（万元）
                rqmcl      - 融券卖出量（万股）
                ...        - 其它 Tushare 原生字段
        """
        params: dict[str, str] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._client._query(API_MARGIN, **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        # 按股票代码和日期排序（ts_code 可能不存在，如不指定个股时只返回交易所汇总数据）
        sort_cols = [c for c in ["ts_code", "trade_date"] if c in df.columns]
        if sort_cols:
            df = df.sort_values(sort_cols).reset_index(drop=True)

        return df

    # ═══════════════════════════════════════════════════════════════
    # 龙虎榜
    # ═══════════════════════════════════════════════════════════════

    def top_list(
        self,
        trade_date: str = "",
    ) -> pd.DataFrame:
        """获取龙虎榜榜单

        通过 tc._query('top_list', ...) 调用 Tushare Pro API。
        列出指定交易日上榜的股票及成交信息。

        Args:
            trade_date: 交易日 YYYYMMDD（必填）

        Returns:
            DataFrame 列:
                trade_date  - 交易日 (datetime)
                ts_code     - 股票代码
                name        - 股票名称
                close       - 收盘价
                pct_chg     - 涨跌幅 (%)
                amount      - 成交额（万元）
                buy         - 买入额（万元）
                buy_rate    - 买入占比 (%)
                sell        - 卖出额（万元）
                sell_rate   - 卖出占比 (%)
                net_amount  - 净额（万元）
                ...         - 其它 Tushare 原生字段

        Raises:
            ValueError: 未提供 trade_date
        """
        if not trade_date:
            raise ValueError("top_list 需要提供 trade_date 参数")

        params: dict[str, str] = {
            "trade_date": trade_date,
        }

        df = self._client._query(API_TOP_LIST, **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        return df

    def top_inst(
        self,
        trade_date: str = "",
    ) -> pd.DataFrame:
        """获取龙虎榜机构交易明细

        通过 tc._query('top_inst', ...) 调用 Tushare Pro API。
        列出指定交易日龙虎榜上榜股票的机构专用席位买入/卖出明细。

        Args:
            trade_date: 交易日 YYYYMMDD（必填）

        Returns:
            DataFrame 列:
                trade_date  - 交易日 (datetime)
                ts_code     - 股票代码
                name        - 股票名称
                buy         - 机构买入额（万元）
                buy_rate    - 机构买入占比 (%)
                sell        - 机构卖出额（万元）
                sell_rate   - 机构卖出占比 (%)
                net_buy     - 机构净买入（万元）
                ...         - 其它 Tushare 原生字段

        Raises:
            ValueError: 未提供 trade_date
        """
        if not trade_date:
            raise ValueError("top_inst 需要提供 trade_date 参数")

        params: dict[str, str] = {
            "trade_date": trade_date,
        }

        df = self._client._query(API_TOP_INST, **params)
        if df.empty:
            return df

        # 标准化日期
        df = self.normalize_date(df, date_col="trade_date")

        return df

    # ═══════════════════════════════════════════════════════════════
    # 以下为尚未实现的抽象方法占位
    # ═══════════════════════════════════════════════════════════════

    def stock_basic(self, list_status: str = "L") -> pd.DataFrame:
        """股票基础信息 — 请使用 TushareStockProvider"""
        raise NotImplementedError(
            "股票基础信息请使用 TushareStockProvider"
        )

    def trade_cal(self, start_date: str = "20000101", end_date: str = "") -> pd.DataFrame:
        """交易日历 — 请使用 TushareStockProvider"""
        raise NotImplementedError(
            "交易日历请使用 TushareStockProvider"
        )

    def daily(self, ts_code: str = "", start_date: str = "", end_date: str = "",
              trade_date: str = "") -> pd.DataFrame:
        """日线行情 — 请使用 TushareMarketProvider"""
        raise NotImplementedError(
            "日线行情请使用 TushareMarketProvider"
        )

    def daily_basic(self, ts_code: str = "", trade_date: str = "",
                    start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """每日估值 — 请使用 TushareMarketProvider"""
        raise NotImplementedError(
            "每日估值请使用 TushareMarketProvider"
        )

    def adj_factor(self, ts_code: str = "", trade_date: str = "",
                   start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """复权因子 — 请使用 TushareMarketProvider"""
        raise NotImplementedError(
            "复权因子请使用 TushareMarketProvider"
        )

    def stk_limit(self, ts_code: str = "", trade_date: str = "") -> pd.DataFrame:
        """涨跌停价格 — 请使用 TushareMarketProvider"""
        raise NotImplementedError(
            "涨跌停价格请使用 TushareMarketProvider"
        )

    def suspend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """停复牌信息 — 请使用 TushareStockProvider"""
        raise NotImplementedError(
            "停复牌信息请使用 TushareStockProvider"
        )

    def namechange(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """更名/ST 信息 — 请使用 TushareStockProvider"""
        raise NotImplementedError(
            "更名/ST 信息请使用 TushareStockProvider"
        )

    def fina_indicator(self, ts_code: str = "", start_date: str = "",
                       end_date: str = "", period: str = "") -> pd.DataFrame:
        """财务指标 — 请使用 TushareFinaProvider"""
        raise NotImplementedError(
            "财务指标请使用 TushareFinaProvider"
        )

    def income(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """利润表 — 请使用 TushareFinaProvider"""
        raise NotImplementedError(
            "利润表请使用 TushareFinaProvider"
        )

    def balancesheet(self, ts_code: str = "", start_date: str = "",
                     end_date: str = "") -> pd.DataFrame:
        """资产负债表 — 请使用 TushareFinaProvider"""
        raise NotImplementedError(
            "资产负债表请使用 TushareFinaProvider"
        )

    def cashflow(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """现金流量表 — 请使用 TushareFinaProvider"""
        raise NotImplementedError(
            "现金流量表请使用 TushareFinaProvider"
        )

    def forecast(self, ts_code: str = "", start_date: str = "",
                 end_date: str = "") -> pd.DataFrame:
        """业绩预告 — 请使用 TushareFinaProvider"""
        raise NotImplementedError(
            "业绩预告请使用 TushareFinaProvider"
        )

    def index_daily(self, ts_code: str = "", start_date: str = "",
                    end_date: str = "") -> pd.DataFrame:
        """指数日线 — 请使用 TushareStockProvider"""
        raise NotImplementedError(
            "指数日线请使用 TushareStockProvider"
        )

    def dividend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """分红送股 — 请使用 TushareEventProvider"""
        raise NotImplementedError(
            "分红送股请使用 TushareEventProvider"
        )

    def stk_surv(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """机构调研 — 请使用 TushareEventProvider"""
        raise NotImplementedError(
            "机构调研请使用 TushareEventProvider"
        )

    def block_trade(self, ts_code: str = "", start_date: str = "",
                    end_date: str = "") -> pd.DataFrame:
        """大宗交易 — 请使用 TushareEventProvider"""
        raise NotImplementedError(
            "大宗交易请使用 TushareEventProvider"
        )

    def new_share(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """新股发行 — 请使用 TushareEventProvider"""
        raise NotImplementedError(
            "新股发行请使用 TushareEventProvider"
        )
