"""DataHub 跳水预测数据补充 — 通过 market_fetcher 管线批量拉取个股+资金流

用法:
  python3 datahub_supplement.py           # 拉全部
  python3 datahub_supplement.py --stocks  # 只拉个股K线
  python3 datahub_supplement.py --fund    # 只拉资金流向
  python3 datahub_supplement.py --index   # 只拉板块指数
"""
import os, sys, csv, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

for k in list(os.environ):
    if 'proxy' in k.lower():
        os.environ.pop(k, None)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import PATHS

CST = timezone(timedelta(hours=8))
JQ_ACCOUNT = '13500226163'
JQ_PWD = 'Ly19940930!'

# 龙头个股 + ETF
CODES = {
    "etf": [("159516", "半导体设备ETF")],
    "stocks": [
        ("002371", "北方华创"), ("688012", "中微公司"),
        ("300604", "长川科技"), ("688072", "拓荆科技"),
        ("688120", "华海清科"),
    ],
}

INDEX_CODE = "931743"  # 中证半导体材料设备主题指数
DATA_END = "2026-04-05"  # 聚宽试用数据截止日
DATA_START = "2025-03-29"  # 聚宽试用数据起始日


def _jq_auth():
    import jqdatasdk as jq
    try:
        jq.get_account_info()
    except Exception:
        jq.auth(JQ_ACCOUNT, JQ_PWD)
    return jq


def pull_stock_kline():
    """拉龙头个股日K线 → data/market/daily_kline/"""
    import jqdatasdk as jq
    jq = _jq_auth()
    kline_dir = PATHS["daily_kline"]
    kline_dir.mkdir(parents=True, exist_ok=True)

    for code, name in CODES["etf"] + CODES["stocks"]:
        path = kline_dir / f"{code}_daily_kline.csv"
        sec = f"{code}.XSHE" if code.startswith(("00", "30", "15")) else f"{code}.XSHG"
        try:
            df = jq.get_price(sec, start_date=DATA_START, end_date=DATA_END, frequency='daily',
                              fields=['open', 'close', 'high', 'low', 'volume', 'money'])
            if df.empty:
                print(f"  ⚠️ {name}({code}): 无数据")
                continue
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["code", "timeString", "open", "high", "low", "close", "volume", "amount"])
                for dt, row in df.iterrows():
                    w.writerow([code, dt.strftime("%Y-%m-%d"),
                                round(row["open"], 4), round(row["high"], 4),
                                round(row["low"], 4), round(row["close"], 4),
                                int(row["volume"]), round(row["money"], 2)])
            print(f"  ✅ {name}({code}): {len(df)} 条 → {path.name}")
        except Exception as e:
            print(f"  ❌ {name}({code}): {e}")


def pull_fund_flow():
    """拉资金流向 → data/fundamentals/fund_flow_timeseries.csv（追加）"""
    import jqdatasdk as jq
    jq = _jq_auth()
    fund_path = PATHS["fundamentals"] / "fund_flow_timeseries.csv"

    # 读取已有数据，跳过已拉取的日期
    existing = set()
    if fund_path.exists():
        with open(fund_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                existing.add((row["symbol"], row["date"]))

    new_rows = []
    all_codes = [c[0] for c in CODES["etf"] + CODES["stocks"]]
    for code in all_codes:
        sec = f"{code}.XSHE" if code.startswith(("00", "30", "15")) else f"{code}.XSHG"
        try:
            df = jq.get_money_flow(sec, start_date=DATA_START, end_date=DATA_END)
            for dt, row in df.iterrows():
                d = dt.strftime("%Y-%m-%d")
                if (code, d) not in existing:
                    new_rows.append({
                        "symbol": code, "date": d,
                        "net_main_force": float(row.get("net_main_force", 0)),
                        "net_super_large": float(row.get("net_super_large", 0)),
                        "net_large": float(row.get("net_large", 0)),
                        "net_medium": float(row.get("net_medium", 0)),
                        "net_small": float(row.get("net_small", 0)),
                    })
            print(f"  📊 {code}: 新增 {len(new_rows)} 条资金流")
        except Exception as e:
            print(f"  ⚠️ {code} 资金流: {e}")

    if new_rows:
        mode = "a" if fund_path.exists() else "w"
        with open(fund_path, mode, encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=new_rows[0].keys())
            if mode == "w":
                w.writeheader()
            w.writerows(new_rows)
        print(f"  ✅ 资金流: 追加 {len(new_rows)} 条到 {fund_path.name}")


def pull_index():
    """拉板块指数历史 → data/market/daily_kline/index_931743.csv"""
    import jqdatasdk as jq
    jq = _jq_auth()
    index_path = PATHS["daily_kline"] / f"index_{INDEX_CODE}.csv"
    try:
        df = jq.get_price(f"{INDEX_CODE}.XSHG", start_date=DATA_START, end_date=DATA_END,
                          frequency='daily', fields=['open', 'close', 'high', 'low', 'volume', 'money'])
        df.to_csv(index_path)
        print(f"  ✅ 板块指数 {INDEX_CODE}: {len(df)} 条")
    except Exception as e:
        print(f"  ⚠️ 板块指数: {e}")


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--stocks", action="store_true")
    p.add_argument("--fund", action="store_true")
    p.add_argument("--index", action="store_true")
    args = p.parse_args()

    do_all = not (args.stocks or args.fund or args.index)

    if do_all or args.stocks:
        print("\n--- 拉取个股ETF日K线 ---")
        pull_stock_kline()

    if do_all or args.fund:
        print("\n--- 拉取资金流向 ---")
        pull_fund_flow()

    if do_all or args.index:
        print("\n--- 拉取板块指数 ---")
        pull_index()

    print("\n✅ DataHub 补充完成")


if __name__ == "__main__":
    main()
