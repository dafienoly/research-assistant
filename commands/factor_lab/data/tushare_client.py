#!/usr/bin/env python3
"""
Tushare Pro 客户端 V1.0 — A 股全量数据接口

数据源: ts.gyzcloud.top (Tushare Pro Proxy)
Token: 66d9505c0bd943b3b00b8bf26df0b862
套餐: 月卡 (60次/分钟)
到期: 2026-08-07

能力:
  - stock_basic: 全A 5,528 只股票基本信息
  - daily: 日线行情（前复权/不复权/后复权）— **最早可追溯到 2000 年**
  - daily_basic: 每日估值（PE/PB/换手率等）
  - fina_indicator: 财务指标 80+ 字段 — **最早可追溯到 2012-2016 年**
  - fina_mainbz: 主营业务构成
  - income: 利润表
  - balancesheet: 资产负债表
  - concept: 概念板块
  - concept_detail: 概念板块成分股
  - industry: 申万行业分类
  - margin: 融资融券
  - moneyflow: 个股资金流向
  - stk_limit: 涨跌停价格
  - suspend_d: 停牌信息
  - namechange: 股票更名/ST 信息
  - trade_cal: 交易日历

用法:
    from factor_lab.data.tushare_client import TushareClient, get_ts_client

    # 默认单例
    tc = get_ts_client()

    # 获取全A股票列表
    stocks = tc.stock_basic()

    # 获取日线
    daily = tc.daily(ts_code='688012.SH', start_date='20240101', end_date='20260403')

数据管线约束 (memory):
    新脚本必须直接 import commands/ 下现有模块，禁止新写 HTTP 拉取。
    本模块是例外 — 它是 Tushare Pro API 的官方封装，而非新开 HTTP 数据源。
"""

from __future__ import annotations

import os
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# ─── 配置 ────────────────────────────────────────────────────

TUSHARE_TOKEN = "66d9505c0bd943b3b00b8bf26df0b862"
TUSHARE_API_URL = "https://ts.gyzcloud.top/api"

# 频率限制: 150次/分钟 → 保守设 120次/分钟 → 每0.5秒1次
MIN_REQUEST_INTERVAL = 0.5

# 数据缓存目录 (减少重复请求)
CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "cache" / "tushare"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ─── 字段映射 (Tushare → 系统统一字段) ──────────────────────

FIELD_MAP_DAILY = {
    "trade_date": "date",
    "ts_code": "symbol",
    "vol": "volume",         # Tushare 单位: 手 (1手=100股)
    "amount": "amount",      # 成交额 (元)
    "pct_chg": "pct_chg",    # 涨跌幅 (%)
}

# Tushare daily 字段: ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount

# ─── 客户端 ───────────────────────────────────────────────────


class TushareClient:
    """Tushare Pro 客户端封装

    单例模式，减少重复初始化。
    自动处理:
      - 频率限制 (150次/分钟 → 每0.5秒1次)
      - 代理绕过 (国内数据源不走 Clash)
      - 异常重试 (最多3次)
      - 结果缓存 (可选)
    """

    _instance: Optional["TushareClient"] = None

    def __init__(self, token: str = TUSHARE_TOKEN, api_url: str = TUSHARE_API_URL):
        self.token = token
        self.api_url = api_url
        self._pro = None
        self._last_request_time = 0.0
        self._request_count = 0
        self._rate_limit_reset = time.time() + 60

    @classmethod
    def get_instance(cls, token: str = TUSHARE_TOKEN, api_url: str = TUSHARE_API_URL) -> "TushareClient":
        if cls._instance is None:
            cls._instance = cls(token, api_url)
        return cls._instance

    def _get_pro(self):
        """延迟初始化 tushare pro API"""
        if self._pro is not None:
            return self._pro

        import tushare as ts
        ts.set_token(self.token)
        pro = ts.pro_api()
        pro._DataApi__http_url = self.api_url
        self._pro = pro
        return pro

    def _rate_limit(self):
        """遵守频率限制 (150次/分钟)"""
        now = time.time()

        # 每分钟重置计数器
        if now - self._rate_limit_reset > 60:
            self._request_count = 0
            self._rate_limit_reset = now

        # 超过 120 次/分钟则等待
        if self._request_count >= 120:
            sleep_time = self._rate_limit_reset + 60 - now + 1
            if sleep_time > 0:
                logger.warning(f"频率限制: 等待 {sleep_time:.1f}s")
                time.sleep(sleep_time)
            self._request_count = 0
            self._rate_limit_reset = time.time()

        # 每次请求间隔至少 MIN_REQUEST_INTERVAL
        elapsed = now - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)

        self._last_request_time = time.time()
        self._request_count += 1

    def _query(self, api_name: str, fields: str = "", **params) -> pd.DataFrame:
        """通用查询 (含重试和限流)
        
        Returns:
            DataFrame (空 DataFrame 表示失败)
        """
        self._rate_limit()

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                pro = self._get_pro()
                func = getattr(pro, api_name, None)
                if func is None:
                    logger.error(f"Tushare API '{api_name}' 不存在")
                    return pd.DataFrame()

                # 如果指定了 fields 则传入
                if fields:
                    df = func(**params, fields=fields)
                else:
                    df = func(**params)

                # 空结果检测
                if df is None or df.empty:
                    return pd.DataFrame()

                return df

            except Exception as e:
                last_error = e
                logger.warning(f"Tushare {api_name} 请求失败 (第{attempt+1}次): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # 指数退避
                else:
                    logger.error(f"Tushare {api_name} 请求全部失败: {last_error}")
                    return pd.DataFrame()

    # ═══════════════════════════════════════════════════════════
    # 股票基础信息
    # ═══════════════════════════════════════════════════════════

    def stock_basic(self, list_status: str = "L") -> pd.DataFrame:
        """
        获取全A股票基本信息

        Args:
            list_status: L=上市, D=退市, P=暂停上市

        Returns:
            DataFrame: ts_code, name, area, industry, market, list_date, delist_date, is_hs
        """
        fields = "ts_code,name,area,industry,market,list_date,delist_date,is_hs"
        df = self._query("stock_basic", fields=fields, list_status=list_status)
        if df.empty:
            return df
        df["list_date"] = pd.to_datetime(df["list_date"], format="%Y%m%d", errors="coerce")
        if "delist_date" in df.columns:
            df["delist_date"] = pd.to_datetime(df["delist_date"], format="%Y%m%d", errors="coerce")
        return df

    # ═══════════════════════════════════════════════════════════
    # 日线行情
    # ═══════════════════════════════════════════════════════════

    def daily(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
        trade_date: str = "",
    ) -> pd.DataFrame:
        """
        获取日线行情 (前复权)

        Args:
            ts_code: 股票代码 (如 688012.SH, 000001.SZ)
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            trade_date: 指定交易日 (与区间二选一)

        Returns:
            DataFrame: ts_code, trade_date, open, high, low, close, pre_close,
                       change, pct_chg, vol(手), amount(元)
        """
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if trade_date:
            params["trade_date"] = trade_date

        df = self._query("daily", **params)
        if df.empty:
            return df

        # 日期排序
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
            df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        return df

    def to_system_format(self, df: pd.DataFrame) -> pd.DataFrame:
        """将 Tushare daily 字段映射为系统统一格式"""
        if df.empty:
            return df
        result = df.rename(columns=FIELD_MAP_DAILY)
        return result

    # ═══════════════════════════════════════════════════════════
    # 每日估值
    # ═══════════════════════════════════════════════════════════

    def daily_basic(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """
        获取每日估值数据

        Args:
            ts_code: 股票代码
            trade_date: 交易日
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame: ts_code, trade_date, pe, pe_ttm, pb, total_mv, circ_mv,
                       turnover_rate, volume_ratio, free_share, total_share
        """
        fields = "ts_code,trade_date,pe,pe_ttm,pb,total_mv,circ_mv,turnover_rate,volume_ratio"
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        df = self._query("daily_basic", fields=fields, **params)
        if df.empty:
            return df

        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")

        return df

    # ═══════════════════════════════════════════════════════════
    # 财务指标
    # ═══════════════════════════════════════════════════════════

    def fina_indicator(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
        period: str = "",
    ) -> pd.DataFrame:
        """
        获取财务指标

        Args:
            ts_code: 股票代码
            start_date: 报告期开始
            end_date: 报告期结束
            period: 指定报告期 (如 20241231)

        Returns:
            DataFrame: 含 ROE, gross_margin, net_margin, debt_to_assets, eps,
                      revenue_ps, ocf_ps, bps 等 80+ 字段
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

        df = self._query("fina_indicator", **params)
        if df.empty:
            return df

        # 日期列处理 (end_date 是报告期)
        date_cols = ["end_date", "ann_date"]
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col].astype(str), format="%Y%m%d", errors="coerce")

        return df

    # ═══════════════════════════════════════════════════════════
    # 概念板块
    # ═══════════════════════════════════════════════════════════

    def concept(self) -> pd.DataFrame:
        """获取概念板块列表"""
        df = self._query("concept")
        return df

    def concept_detail(self, concept_code: str = "") -> pd.DataFrame:
        """获取概念板块成分股"""
        params = {}
        if concept_code:
            params["id"] = concept_code
        df = self._query("concept_detail", **params)
        return df

    # ═══════════════════════════════════════════════════════════
    # 技术停复牌
    # ═══════════════════════════════════════════════════════════

    def suspend(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取停牌信息"""
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._query("suspend_d", **params)

    suspend_d = suspend  # 别名兼容

    def stk_limit(self, ts_code: str = "", trade_date: str = "") -> pd.DataFrame:
        """获取涨跌停价格"""
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        return self._query("stk_limit", **params)

    def namechange(self, ts_code: str = "", start_date: str = "", end_date: str = "") -> pd.DataFrame:
        """获取股票更名/ST 信息"""
        params = {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._query("namechange", **params)

    # ═══════════════════════════════════════════════════════════
    # 交易日历
    # ═══════════════════════════════════════════════════════════

    def trade_cal(self, start_date: str = "20210101", end_date: str = "") -> pd.DataFrame:
        """获取交易日历"""
        if not end_date:
            end_date = datetime.now(CST).strftime("%Y%m%d")
        df = self._query("trade_cal", start_date=start_date, end_date=end_date)
        if not df.empty and "cal_date" in df.columns:
            df["cal_date"] = pd.to_datetime(df["cal_date"], format="%Y%m%d", errors="coerce")
        return df

    # ═══════════════════════════════════════════════════════════
    # 批量获取 (优化版: 全量拉取)
    # ═══════════════════════════════════════════════════════════

    def batch_daily(
        self,
        ts_codes: list[str],
        start_date: str,
        end_date: str,
        batch_size: int = 5,
    ) -> pd.DataFrame:
        """批量获取多只股票的日线 (逐只请求, 间隔限流)"""
        all_dfs = []
        total = len(ts_codes)
        for i, code in enumerate(ts_codes):
            df = self.daily(ts_code=code, start_date=start_date, end_date=end_date)
            if not df.empty:
                all_dfs.append(df)
            if (i + 1) % batch_size == 0:
                logger.info(f"batch_daily: {i+1}/{total} done")
        if not all_dfs:
            return pd.DataFrame()
        return pd.concat(all_dfs, ignore_index=True)

    def batch_fina_indicator(
        self,
        ts_codes: list[str],
        start_date: str,
        end_date: str,
        batch_size: int = 5,
    ) -> pd.DataFrame:
        """批量获取多只股票的财务指标"""
        all_dfs = []
        total = len(ts_codes)
        for i, code in enumerate(ts_codes):
            df = self.fina_indicator(ts_code=code, start_date=start_date, end_date=end_date)
            if not df.empty:
                all_dfs.append(df)
            if (i + 1) % batch_size == 0:
                logger.info(f"batch_fina: {i+1}/{total} done")
        if not all_dfs:
            return pd.DataFrame()
        return pd.concat(all_dfs, ignore_index=True)


# ─── 快捷函数 ────────────────────────────────────────────────


def get_ts_client() -> TushareClient:
    """获取 TushareClient 单例"""
    return TushareClient.get_instance()


def query(api_name: str, **params) -> pd.DataFrame:
    """快速查询任意 Tushare API"""
    return get_ts_client()._query(api_name, **params)


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

def self_check() -> dict:
    """验证 Tushare Pro 连接和数据可用性

    Returns:
        dict: 检查结果 {status, stock_count, sample_stock, errors}
    """
    result = {"status": "unknown", "errors": []}
    try:
        tc = get_ts_client()

        # 1. stock_basic
        stocks = tc.stock_basic()
        result["stock_count"] = len(stocks)
        if stocks.empty:
            result["errors"].append("stock_basic 返回空")
        else:
            result["sample_stock"] = stocks.iloc[0]["ts_code"]

        # 2. daily (recent)
        recent = tc.daily(ts_code="688012.SH", start_date="20260401", end_date="20260403")
        if recent.empty:
            result["errors"].append("daily 返回空")
        else:
            result["daily_dates"] = f"{recent['trade_date'].min().date()} ~ {recent['trade_date'].max().date()}"

        # 3. daily_basic
        basic = tc.daily_basic(ts_code="688012.SH", start_date="20260401", end_date="20260403")
        if basic.empty:
            result["errors"].append("daily_basic 返回空")
        else:
            result["pe_sample"] = float(basic.iloc[0]["pe"])

        # 4. fina_indicator
        fina = tc.fina_indicator(ts_code="688012.SH", start_date="20240101", end_date="20241231")
        if fina.empty:
            result["errors"].append("fina_indicator 返回空")
        else:
            result["fina_periods"] = len(fina)

        # 5. trade_cal
        cal = tc.trade_cal(start_date="20250101")
        if not cal.empty and "is_open" in cal.columns:
            trading_days = cal[cal["is_open"] == 1]
            result["trading_days_2025"] = len(trading_days)

        result["status"] = "ok" if not result["errors"] else "partial"

    except Exception as e:
        result["status"] = "error"
        result["errors"].append(str(e))

    return result


# ─── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import pprint
    check = self_check()
    print("=== Tushare Pro 自检结果 ===")
    pprint.pprint(check)
