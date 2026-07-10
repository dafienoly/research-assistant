#!/usr/bin/env python3
"""
Tushare DataHub — 全 A 股数据批量拉取管线 V2.0

每日增量拉取:
  1. daily       日线行情 (全A ~5,500只 × 交易日)
  2. daily_basic 每日估值 (PE/PB/市值/换手率)
  3. moneyflow   个股资金流向
  4. fina_indicator 财务指标 (按季度全量同步)

输出:
  data/market/daily_kline/{code}_daily_kline.csv
  data/normalized/market/valuation_{code}.csv
  data/normalized/fund_flow/{code}.csv
  data/normalized/fundamentals/{code}.csv

用法:
  python3 tushare_datahub.py             # 全量拉取（首次）
  python3 tushare_datahub.py --incremental  # 仅拉最近 5 个交易日
"""
import sys, os, csv, json, time, argparse
from pathlib import Path
from datetime import datetime, date, timezone, timedelta

# 确保导入路径
BASE = Path(__file__).resolve().parent.parent.parent  # .../research-assistant
sys.path.insert(0, str(BASE / "commands"))

import pandas as pd
import numpy as np
from factor_lab.data.tushare_client import get_ts_client

CST = timezone(timedelta(hours=8))
NOW = datetime.now(CST)

# 目录
DATA_DIR = BASE / "data"
KLINE_DIR = DATA_DIR / "market" / "daily_kline"
NORM_DIR = DATA_DIR / "normalized"
VAL_DIR = NORM_DIR / "market"       # valuation_*.csv
FF_DIR = NORM_DIR / "fund_flow"     # {ts_code}.csv
FA_DIR = NORM_DIR / "fundamentals"  # {ts_code}.csv

TUSHARE_TOKEN = "66d9505c0bd943b3b00b8bf26df0b862"
TUSHARE_API = "https://ts.gyzcloud.top/api"

# 每批次间隔(秒) — 月卡 60次/分钟，设 1.5s = 40次/分钟 留余量
RATE_LIMIT = 1.5


def log(msg: str):
    ts = datetime.now(CST).strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def ensure_dirs():
    for d in [KLINE_DIR, VAL_DIR, FF_DIR, FA_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def get_tc():
    tc = get_ts_client()
    # 确保 token 和 api_url 正确
    tc.token = TUSHARE_TOKEN
    tc.api_url = TUSHARE_API
    return tc


# ─── 1. 全 A 股票列表 ──────────────────────────────────────

def pull_stock_list() -> pd.DataFrame:
    """获取全 A 已上市股票列表"""
    tc = get_tc()
    df = tc.stock_basic(list_status="L")
    if df.empty:
        log("⚠️  stock_basic 返回空")
        return df
    log(f"✅ 全A股票: {len(df)} 只")
    return df


# ─── 2. 日线行情 (按交易日逐日拉取) ─────────────────────────

def pull_daily_by_date(trade_date: str) -> pd.DataFrame:
    """拉取指定交易日全市场日线"""
    tc = get_tc()
    try:
        df = tc.daily(trade_date=trade_date)
        if df.empty:
            return df
        # 转系统格式: code, timeString, open, high, low, close, volume, amount
        records = []
        for _, row in df.iterrows():
            code = row.get("ts_code", "").replace(".SZ", "").replace(".SH", "")
            records.append({
                "code": code,
                "timeString": trade_date[:4] + "-" + trade_date[4:6] + "-" + trade_date[6:],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("vol", 0) * 100 if pd.notna(row.get("vol")) else 0,  # 手→股
                "amount": row.get("amount", 0),
            })
        result = pd.DataFrame(records)
        time.sleep(RATE_LIMIT)
        return result
    except Exception as e:
        log(f"⚠️  daily({trade_date}) 失败: {e}")
        time.sleep(RATE_LIMIT * 2)
        return pd.DataFrame()


def save_daily(df: pd.DataFrame, trade_date: str):
    """按股票拆分保存日线"""
    if df.empty:
        return
    count = 0
    for code, grp in df.groupby("code"):
        fpath = KLINE_DIR / f"{code}_daily_kline.csv"
        header = not fpath.exists()
        grp.to_csv(fpath, mode="a" if fpath.exists() else "w",
                   index=False, header=header,
                   columns=["code", "timeString", "open", "high", "low", "close", "volume", "amount"])
        count += 1
    log(f"  daily_kline: {trade_date} → {count} 只股票已保存")


# ─── 3. 每日估值 (daily_basic) ──────────────────────────────

def pull_daily_basic(trade_date: str) -> pd.DataFrame:
    """拉取指定交易日全市场估值数据"""
    tc = get_tc()
    try:
        df = tc.daily_basic(trade_date=trade_date)
        if df.empty:
            return df
        records = []
        for _, row in df.iterrows():
            code = row.get("ts_code", "").replace(".SZ", "").replace(".SH", "")
            records.append({
                "ts_code": row.get("ts_code", ""),
                "trade_date": trade_date,
                "pe": row.get("pe"),
                "pe_ttm": row.get("pe_ttm"),
                "pb": row.get("pb"),
                "total_mv": row.get("total_mv"),
                "circ_mv": row.get("circ_mv"),
                "turnover_rate": row.get("turnover_rate_f"),
            })
        result = pd.DataFrame(records)
        time.sleep(RATE_LIMIT)
        return result
    except Exception as e:
        log(f"⚠️  daily_basic({trade_date}) 失败: {e}")
        time.sleep(RATE_LIMIT * 2)
        return pd.DataFrame()


def save_valuation(df: pd.DataFrame):
    """按股票拆分保存估值数据"""
    if df.empty:
        return
    for code, grp in df.groupby("ts_code"):
        fname = f"valuation_{code}.csv"
        fpath = VAL_DIR / fname
        header = not fpath.exists()
        grp.to_csv(fpath, mode="a" if fpath.exists() else "w",
                   index=False, header=header)
    log(f"  valuation: {df['trade_date'].iloc[0]} → {df['ts_code'].nunique()} 只股票")


# ─── 4. 个股资金流向 (moneyflow) ────────────────────────────

def pull_moneyflow(trade_date: str) -> pd.DataFrame:
    """拉取指定交易日全市场资金流向"""
    tc = get_tc()
    try:
        # Tushare moneyflow API
        df = tc._query("moneyflow", trade_date=trade_date)
        if df.empty:
            return df
        records = []
        for _, row in df.iterrows():
            code = row.get("ts_code", "").replace(".SZ", "").replace(".SH", "")
            records.append({
                "ts_code": row.get("ts_code", ""),
                "trade_date": trade_date,
                "buy_sm_vol": row.get("buy_sm_vol"),
                "buy_sm_amount": row.get("buy_sm_amount"),
                "sell_sm_vol": row.get("sell_sm_vol"),
                "sell_sm_amount": row.get("sell_sm_amount"),
                "buy_md_vol": row.get("buy_md_vol"),
                "buy_md_amount": row.get("buy_md_amount"),
                "sell_md_vol": row.get("sell_md_vol"),
                "sell_md_amount": row.get("sell_md_amount"),
                "buy_lg_vol": row.get("buy_lg_vol"),
                "buy_lg_amount": row.get("buy_lg_amount"),
                "sell_lg_vol": row.get("sell_lg_vol"),
                "sell_lg_amount": row.get("sell_lg_amount"),
                "buy_elg_vol": row.get("buy_elg_vol"),
                "buy_elg_amount": row.get("buy_elg_amount"),
                "sell_elg_vol": row.get("sell_elg_vol"),
                "sell_elg_amount": row.get("sell_elg_amount"),
                "net_mf_vol": row.get("net_mf_vol"),
                "net_mf_amount": row.get("net_mf_amount"),
            })
        result = pd.DataFrame(records)
        time.sleep(RATE_LIMIT)
        return result
    except Exception as e:
        log(f"⚠️  moneyflow({trade_date}) 失败: {e}")
        time.sleep(RATE_LIMIT * 2)
        return pd.DataFrame()


def save_moneyflow(df: pd.DataFrame):
    """按股票拆分保存资金流向"""
    if df.empty:
        return
    for code, grp in df.groupby("ts_code"):
        fname = f"{code}.csv"
        fpath = FF_DIR / fname
        header = not fpath.exists()
        grp.to_csv(fpath, mode="a" if fpath.exists() else "w",
                   index=False, header=header)
    log(f"  fund_flow: {df['trade_date'].iloc[0]} → {df['ts_code'].nunique()} 只股票")


# ─── 5. 财务指标 (fina_indicator) — 按季度全量 ──────────────

def pull_fina_indicator_batch(ts_codes: list[str], start_date: str, end_date: str):
    """批量拉取财务指标"""
    tc = get_tc()
    total = len(ts_codes)
    count = 0
    for i, code in enumerate(ts_codes):
        try:
            df = tc.fina_indicator(ts_code=code, start_date=start_date, end_date=end_date)
            if not df.empty:
                fname = f"{code}.csv"
                fpath = FA_DIR / fname
                header = not fpath.exists()
                df.to_csv(fpath, mode="a" if fpath.exists() else "w",
                          index=False, header=header)
                count += 1
            time.sleep(RATE_LIMIT)
        except Exception as e:
            log(f"⚠️  fina({code}) 失败: {e}")
            time.sleep(RATE_LIMIT * 2)
        if (i + 1) % 50 == 0:
            log(f"  fina_indicator: {i+1}/{total} — {count} 只已保存")
    log(f"  fina_indicator: {count}/{total} 只股票已保存")


# ─── 主流程 ──────────────────────────────────────────────────

def run_incremental(days_back: int = 5):
    """增量拉取最近 N 个交易日"""
    ensure_dirs()
    stocks = pull_stock_list()
    if stocks.empty:
        return

    # 获取交易日历
    tc = get_tc()
    today_str = NOW.strftime("%Y%m%d")
    cal = tc._query("trade_cal", start_date=(NOW - timedelta(days=30)).strftime("%Y%m%d"),
                    end_date=today_str, exchange="SSE")
    if cal.empty:
        log("⚠️  交易日历为空，使用日历日")
        trade_dates = [(NOW - timedelta(days=i)).strftime("%Y%m%d") for i in range(days_back)]
    else:
        # 过滤交易日
        cal = cal[cal["is_open"] == 1]
        trade_dates = sorted(cal["cal_date"].tolist())[-days_back:]

    log(f"目标交易日: {trade_dates}")

    for td in trade_dates:
        # 日线
        df_d = pull_daily_by_date(td)
        save_daily(df_d, td)

        # 估值
        df_v = pull_daily_basic(td)
        save_valuation(df_v)

        # 资金流向
        df_f = pull_moneyflow(td)
        save_moneyflow(df_f)

    log("✅ 增量更新完成")


def run_full():
    """全量拉取（从 2020-01-01 至今的日线+估值+资金流，基本面全量）"""
    ensure_dirs()
    stocks = pull_stock_list()
    if stocks.empty:
        return

    all_codes = stocks["ts_code"].tolist()
    today_str = NOW.strftime("%Y%m%d")
    start_date = "20200101"

    log(f"开始全量拉取: {len(all_codes)} 只股票, {start_date} ~ {today_str}")

    # 日线+估值+资金流: 按日拉取
    tc = get_tc()
    cal = tc._query("trade_cal", start_date=start_date, end_date=today_str, exchange="SSE")
    if cal.empty:
        log("⚠️  交易日历为空")
        return
    cal = cal[cal["is_open"] == 1]
    trade_dates = sorted(cal["cal_date"].tolist())
    log(f"交易日数: {len(trade_dates)}")

    for i, td in enumerate(trade_dates):
        if (i + 1) % 20 == 0:
            log(f"  [{i+1}/{len(trade_dates)}] {td}")

        df_d = pull_daily_by_date(td)
        save_daily(df_d, td)

        df_v = pull_daily_basic(td)
        save_valuation(df_v)

        df_f = pull_moneyflow(td)
        save_moneyflow(df_f)

    # 基本面：按股票批量拉取
    log("开始拉取财务指标...")
    pull_fina_indicator_batch(all_codes, "20200101", today_str)

    log("✅ 全量拉取完成")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tushare DataHub 全A数据拉取")
    parser.add_argument("--incremental", action="store_true", help="增量模式（最近5个交易日）")
    parser.add_argument("--days", type=int, default=5, help="增量拉取的天数")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  Tushare DataHub — {'增量' if args.incremental else '全量'}拉取")
    print(f"  {NOW.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}\n")

    if args.incremental:
        run_incremental(days_back=args.days)
    else:
        run_full()
