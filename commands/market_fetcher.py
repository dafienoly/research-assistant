"""Hermes A股投研助手 — 市场数据获取器 (Phase 2)

使用 RSScast MCP + Sina + AKShare 获取真实行情数据。
"""

import csv
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from config import PATHS, now_str, now_cst, date_id, ensure_dirs, read_csv_safe, safe_write_json, append_jsonl
from rsscast_mcp import (
    fetch_stock_prices, fetch_kline, fetch_index_prices,
    fetch_sina_quotes, fetch_akshare_spot,
)


class MarketDataFetcher:
    """行情数据获取器"""

    def update_live_snapshot(self, priority_codes: list[str] = None) -> dict:
        """更新全A实时快照

        策略:
        1. RSScast MCP 获取优先股
        2. AKShare 获取全A快照
        3. Sina 作为深度备用
        """
        ensure_dirs()
        snapshot_time = now_str()

        # 1. 优先股 - RSScast
        priority_data = []
        if priority_codes:
            priority_data = fetch_stock_prices(priority_codes)
            time.sleep(0.5)  # 避免频率限制

        # 2. 全A - AKShare
        all_data = fetch_akshare_spot()

        # 3. 合并
        all_map = {}
        for row in all_data:
            code = str(row.get("code", "")).strip()
            if code:
                all_map[code] = row

        for row in priority_data:
            code = str(row.get("code", ""))
            if code:
                all_map[code] = row

        # 写 CSV
        snapshot_path = PATHS["market"] / "live_snapshot.csv"
        fields = ["code", "name", "last_price", "change_pct", "change_amount",
                   "volume", "amount", "amplitude", "turnover_rate",
                   "pe", "pb", "open", "high", "low", "source", "update_time"]
        with open(snapshot_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for code, row in all_map.items():
                record = {
                    "code": code,
                    "name": row.get("name", ""),
                    "last_price": row.get("last_price", row.get("最新价", "")),
                    "change_pct": row.get("change_pct", row.get("涨跌幅", "")),
                    "change_amount": row.get("change_amount", row.get("涨跌额", "")),
                    "volume": row.get("volume", row.get("成交量", "")),
                    "amount": row.get("amount", row.get("成交额", "")),
                    "amplitude": row.get("amplitude", row.get("振幅", "")),
                    "turnover_rate": row.get("turnover_rate", row.get("换手率", "")),
                    "pe": row.get("pe", row.get("市盈率-动态", "")),
                    "pb": row.get("pb", row.get("市净率", "")),
                    "open": row.get("open", ""),
                    "high": row.get("high", ""),
                    "low": row.get("low", ""),
                    "source": row.get("source", "akshare"),
                    "update_time": snapshot_time,
                }
                w.writerow(record)

        # 写审计日志
        append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
            "timestamp": snapshot_time,
            "action": "update_live_snapshot",
            "source": "rsscast_mcp+akshare",
            "records": len(all_map),
            "priority_records": len(priority_data),
        })

        return {"total": len(all_map), "priority": len(priority_data)}

    def update_daily_kline(self, codes: list[str], start_date: str = None, end_date: str = None):
        """更新日K线数据"""
        ensure_dirs()
        end = end_date or date_id().replace("-", "")
        # 默认拉取半年
        if not start_date:
            start = (now_cst() - timedelta(days=180)).strftime("%Y%m%d")
        else:
            start = start_date

        kline_dir = PATHS["daily_kline"]
        kline_dir.mkdir(parents=True, exist_ok=True)

        for code in codes:
            data = fetch_kline([code], start, end)
            if not data:
                continue

            path = kline_dir / f"{code}_daily_kline.csv"
            fields = ["code", "timeString", "unixtime", "open", "high", "low",
                       "close", "volume", "amount"]
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for row in data:
                    row["timeString"] = row.get("timeString", "")
                    w.writerow(row)

            time.sleep(0.3)  # 避免频率限制

        append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
            "timestamp": now_str(),
            "action": "update_daily_kline",
            "codes": codes,
            "date_range": f"{start}-{end}",
        })

    def update_priority_snapshot(self, codes: list[str]) -> list[dict]:
        """更新优先池实时快照（用于 intraday monitor）"""
        if not codes:
            return []

        # 优先用 RSScast
        data = fetch_stock_prices(codes)
        if data:
            return data

        # 备用: Sina
        sina = fetch_sina_quotes(codes)
        return list(sina.values())

    def update_sector_snapshot(self) -> list[dict]:
        """更新板块快照（AKShare）"""
        try:
            import akshare as ak
            df = ak.stock_board_industry_name_em()
            if df is None or df.empty:
                return []
            path = PATHS["market"] / "sector_snapshot.csv"
            df.to_csv(path, index=False, encoding="utf-8-sig")
            append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
                "timestamp": now_str(),
                "action": "update_sector_snapshot",
                "records": len(df),
            })
            return df.to_dict("records")
        except Exception as e:
            print(f"⚠️ 板块快照失败 (East Money 可能被阻断): {e}")
            return []


class FundamentalDataFetcher:
    """基本面数据获取器"""

    def update_financial_snapshot(self, codes: list[str]) -> list[dict]:
        """更新基本面快照"""
        results = []
        for code in codes:
            try:
                overview = fetch_company_overview(code)
                if overview:
                    results.append({
                        "code": code,
                        "data": overview,
                        "fetched_at": now_str(),
                    })
                time.sleep(0.3)
            except Exception as e:
                print(f"⚠️ {code} 基本面获取失败: {e}")

        if results:
            path = PATHS["fundamentals"] / "financial_snapshot.csv"
            # 扁平化写入
            rows = []
            for r in results:
                flat = {"code": r["code"], "fetched_at": r["fetched_at"]}
                data = r["data"]
                # 提取财务指标
                indicators = data.get("financialIndicators", {})
                if isinstance(indicators, dict):
                    flat.update(indicators)
                rows.append(flat)

            if rows:
                fields = list(rows[0].keys())
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)

        append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
            "timestamp": now_str(),
            "action": "update_financial_snapshot",
            "codes": codes,
            "success": len(results),
        })
        return results


# === CLI 命令 ===

def cmd_update_daily():
    """更新全A日K (market:update-daily)"""
    pool = read_csv_safe(PATHS["market"] / "pool.csv")
    if not pool:
        print("⏳ pool.csv 不存在，先更新快照获取全A列表")
        fetcher = MarketDataFetcher()
        snapshot = fetcher.update_live_snapshot()
        print(f"✅ 快照已更新: {snapshot['total']} 只股票")
        return

    codes = [row.get("code", "") for row in pool if row.get("code")]
    # 限制批次大小
    batch_size = 50
    fetcher = MarketDataFetcher()
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        fetcher.update_daily_kline(batch)
        print(f"  日K更新: {i+1}-{min(i+batch_size, len(codes))}/{len(codes)}")
        time.sleep(2)

    print(f"✅ 全A日K更新完成 ({len(codes)} 只)")


def cmd_update_live_snapshot():
    """更新实时快照 (market:update-live-snapshot)"""
    fetcher = MarketDataFetcher()
    result = fetcher.update_live_snapshot()
    print(f"✅ 实时快照已更新: {result['total']} 只股票")


def cmd_update_priority_minute():
    """更新重点池分钟线 (market:update-priority-minute)"""
    # 从 priority_tags 读取重点池
    tags_path = PATHS["tags"] / "semiconductor_chain_tags.csv"
    rows = read_csv_safe(tags_path)
    codes = [r.get("code", "") for r in rows if r.get("code")]
    if not codes:
        print("⚠️ 优先池为空")
        return

    # 获取实时行情（分钟级用实时价格代替）
    fetcher = MarketDataFetcher()
    data = fetcher.update_priority_snapshot(codes)

    if data:
        path = PATHS["minute_kline"] / f"snapshot_{date_id().replace('-','')}.csv"
        fields = ["code", "last_price", "change_pct", "volume", "amount",
                   "turnover_rate", "amplitude"]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for row in data:
                w.writerow({k: row.get(k, "") for k in fields})

    print(f"✅ 优先池行情已更新: {len(data)} 只")


def cmd_update_fundamentals():
    """更新基本面数据 (fundamentals:update)"""
    pool = read_csv_safe(PATHS["market"] / "pool.csv")
    codes = [r.get("code", "") for r in (pool or [])[:20]]  # 先限制20只
    if not codes:
        print("⚠️ pool.csv 为空，跳过")
        return

    fetcher = FundamentalDataFetcher()
    results = fetcher.update_financial_snapshot(codes)
    print(f"✅ 基本面已更新: {len(results)} 只")


if __name__ == "__main__":
    import sys
    cmds = {
        "update-daily": cmd_update_daily,
        "update-live-snapshot": cmd_update_live_snapshot,
        "update-priority-minute": cmd_update_priority_minute,
        "update-fundamentals": cmd_update_fundamentals,
    }
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd in cmds:
        cmds[cmd]()
    else:
        print("Commands:", ", ".join(cmds.keys()))
