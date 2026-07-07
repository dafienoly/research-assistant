"""每日 K 线更新 — Baostock + RSScast MCP 降级

策略:
  1. 优先用 Baostock 批量查全部股票（免费无限量）
  2. 如果今天数据未就绪(17:00前) → 用 RSScast MCP 只更新优先股
"""

import sys, os, csv, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import dns_patch
from config import read_csv_safe, PATHS

KLINE = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")

def today_str():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

def update_one_file(code: str, row: dict) -> bool:
    """追加一条 K 线到 CSV，去重"""
    f = KLINE / f"{code}.csv"
    if not f.exists():
        with open(f, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(["code","date","open","high","low","close","volume","amount"])
    with open(f, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        reader.fieldnames = [fn.lstrip("\ufeff") for fn in reader.fieldnames]
        rows = list(reader)
    if any(r.get("date") == row["date"] for r in rows if r.get("date")):
        return False
    rows.append(row)
    with open(f, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["code","date","open","high","low","close","volume","amount"])
        w.writeheader()
        w.writerows(rows)
    return True

def update_via_baostock(today: str) -> int:
    """用 Baostock 批量更新（免费无限量）"""
    import baostock as bs
    bs.login()

    # 获取最近的交易日
    rs_trade = bs.query_trade_dates(start_date='2026-07-02', end_date=today)
    trade_dates = []
    while rs_trade.next():
        row = rs_trade.get_row_data()
        if row and len(row) >= 2 and row[1] == '1':  # is_trading_day
            trade_dates.append(row[0])
    if not trade_dates:
        print("  Baostock: 无交易日数据")
        bs.logout()
        return 0
    last_date = max(trade_dates)

    rs = bs.query_all_stock(last_date)
    stocks = []
    while rs.next():
        row = rs.get_row_data()
        if row and len(row) >= 6 and row[5].strip() == '1':
            code_long = row[2].strip()
            code_short = code_long.split('.')[1]
            stocks.append((code_long, code_short))

    print(f"Baostock: {len(stocks)} 只正常交易 (日期: {last_date})")
    updated = 0

    for i in range(0, len(stocks), 10):
        batch = stocks[i:i+10]
        codes_str = ",".join(s[0] for s in batch)
        try:
            rs_k = bs.query_history_k_data_plus(
                codes_str, "date,open,high,low,close,volume,amount",
                start_date=last_date, end_date=last_date,
                frequency="d", adjustflag="2"
            )
            while rs_k.next():
                row = rs_k.get_row_data()
                if not row or not row[4]:  # close 非空
                    continue
                code_short = row[0].split('.')[1] if '.' in row[0] else row[0]
                if update_one_file(code_short, {
                    "code": code_short, "date": row[1], "open": row[2],
                    "high": row[3], "low": row[4], "close": row[5],
                    "volume": row[6], "amount": row[7] if len(row) > 7 else ""
                }):
                    updated += 1
        except Exception:
            import logging; logging.warning('update_kline_daily: suppressed error')

        if (i+1) % 1000 == 0 or i >= len(stocks) - 10:
            print(f"\r  Baostock进度: {min(i+10, len(stocks))}/{len(stocks)} 更新:{updated}", end="")

    bs.logout()
    print()
    return updated

def update_priority_via_mcp(today: str) -> int:
    """用 RSScast MCP 更新优先股（1次调用）"""
    from rsscast_mcp import fetch_kline

    codes = set()
    for p in [Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/portfolio/positions.csv"),
              Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/today_candidates.csv")]:
        for r in read_csv_safe(p):
            c = r.get('symbol','') or r.get('code','')
            if c: codes.add(c)
    for r in read_csv_safe(PATHS['tags'] / 'semiconductor_chain_tags.csv'):
        if r.get('code'): codes.add(r['code'])
    for w in read_csv_safe(Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/manual_watchlist.csv"))[:50]:
        c = w.get('symbol','') or w.get('code','')
        if c: codes.add(c)

    priority = sorted(codes)
    data = fetch_kline(priority, today, today)
    updated = 0
    for k in data:
        if k.get('close'):
            if update_one_file(k['code'], {
                "code": k['code'], "date": k.get('timeString','') or k.get('date',''),
                "open": str(k.get('open','')), "high": str(k.get('high','')),
                "low": str(k.get('low','')), "close": str(k['close']),
                "volume": str(k.get('volume','')), "amount": str(k.get('amount',''))
            }):
                updated += 1
    print(f"  MCP优先股: {updated} 只")
    return updated

def run():
    today = today_str()
    print(f"=== K线更新 {today} ===")

    # 先试 Baostock
    print("1️⃣  Baostock 批量更新...")
    count = update_via_baostock(today)
    print(f"   Baostock 完成: {count} 只")

    # 如果 Baostock 没返回数据（今日数据未就绪），降级到 MCP 更新优先股
    if count == 0:
        print("2️⃣  Baostock 今日数据未就绪，降级到 RSScast MCP 更新优先股...")
        count = update_priority_via_mcp(today)

    print(f"\n✅ 完成: 更新 {count} 只股票")

if __name__ == "__main__":
    run()
