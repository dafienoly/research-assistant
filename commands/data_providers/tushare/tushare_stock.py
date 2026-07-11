#!/usr/bin/env python3
"""Tushare 股票基础/指数/更名/停牌 Provider"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import pandas as pd

try:
    from commands.data_providers import BaseProvider, ProviderCapability, ProviderHealth
except ModuleNotFoundError:
    from data_providers import BaseProvider, ProviderCapability, ProviderHealth

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))


class TushareStockProvider(BaseProvider):
    """Tushare 股票基础数据 Provider (stock_basic, trade_cal, index_daily, namechange, suspend)"""

    def __init__(self):
        super().__init__()
        self._client = None

    def _get_client(self):
        if self._client is None:
            from factor_lab.data.tushare_client import get_ts_client
            self._client = get_ts_client()
        return self._client

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name="tushare_stock", can_stock_basic=True, can_trade_cal=True,
            can_index_daily=True, can_namechange=True, can_suspend=True,
            coverage_start="19901219", stock_count=5528, daily_history_years=35,
        )

    def self_check(self) -> ProviderHealth:
        h = ProviderHealth(source_id="tushare_stock", last_check=datetime.now(CST).isoformat())
        try:
            tc = self._get_client()
            sb = tc._query("stock_basic", list_status="L", fields="ts_code,name")
            if not sb.empty:
                h.status = "ok"
                h.data_freshness["stock_basic"] = "available"
            cal = tc._query("trade_cal", start_date="20260701", end_date="20260708")
            if not cal.empty:
                h.data_freshness["trade_cal"] = "available"
        except Exception as e:
            h.status = "error"
            h.errors.append(str(e))
        return h

    def stock_basic(self, list_status: str = "L") -> pd.DataFrame:
        tc = self._get_client()
        fields = "ts_code,name,area,industry,market,list_date,delist_date,is_hs"
        df = tc._query("stock_basic", fields=fields, list_status=list_status)
        df = df.copy()
        if not df.empty and "list_date" in df.columns:
            df["list_date"] = pd.to_datetime(df["list_date"], format="%Y%m%d", errors="coerce")
        if not df.empty and "delist_date" in df.columns:
            df["delist_date"] = pd.to_datetime(df["delist_date"], format="%Y%m%d", errors="coerce")
        return df

    def trade_cal(self, start_date: str = "20000101", end_date: str = "") -> pd.DataFrame:
        tc = self._get_client()
        if not end_date:
            end_date = datetime.now(CST).strftime("%Y%m%d")
        df = tc._query("trade_cal", start_date=start_date, end_date=end_date)
        if not df.empty and "cal_date" in df.columns:
            df["cal_date"] = pd.to_datetime(df["cal_date"], format="%Y%m%d", errors="coerce")
        if not df.empty and "is_open" not in df.columns:
            df["is_open"] = 1
        return df

    def index_daily(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        tc = self._get_client()
        params = {
            key: value
            for key, value in {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}.items()
            if value
        }
        df = tc._query("index_daily", **params)
        if not df.empty and "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
        return df

    def namechange(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        tc = self._get_client()
        df = tc._query("namechange", ts_code=ts_code, start_date=start_date, end_date=end_date)
        for col in ["start_date", "end_date", "ann_date"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col].astype(str), format="%Y%m%d", errors="coerce")
        return df

    def suspend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        tc = self._get_client()
        params = {
            key: value
            for key, value in {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}.items()
            if value
        }
        df = tc._query("suspend_d", **params)
        if not df.empty and "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
        return df

    # ─── 未实现方法 ───
    def daily(self, **kw): raise NotImplementedError("Use TushareMarketProvider")
    def daily_basic(self, **kw): raise NotImplementedError("Use TushareMarketProvider")
    def adj_factor(self, **kw): raise NotImplementedError("Use TushareMarketProvider")
    def stk_limit(self, **kw): raise NotImplementedError("Use TushareMarketProvider")
    def fina_indicator(self, **kw): raise NotImplementedError("Use TushareFinaProvider")
    def income(self, **kw): raise NotImplementedError("Use TushareFinaProvider")
    def balancesheet(self, **kw): raise NotImplementedError("Use TushareFinaProvider")
    def cashflow(self, **kw): raise NotImplementedError("Use TushareFinaProvider")
    def forecast(self, **kw): raise NotImplementedError("Use TushareFinaProvider")
    def moneyflow(self, **kw): raise NotImplementedError("Use TushareFundFlowProvider")
    def hs_const(self, **kw): raise NotImplementedError("Use TushareFundFlowProvider")
    def moneyflow_hsgt(self, **kw): raise NotImplementedError("Use TushareFundFlowProvider")
    def hsgt_top10(self, **kw): raise NotImplementedError("Use TushareFundFlowProvider")
    def dividend(self, **kw): raise NotImplementedError("Use TushareEventProvider")
    def stk_surv(self, **kw): raise NotImplementedError("Use TushareEventProvider")
    def block_trade(self, **kw): raise NotImplementedError("Use TushareEventProvider")
    def new_share(self, **kw): raise NotImplementedError("Use TushareEventProvider")
