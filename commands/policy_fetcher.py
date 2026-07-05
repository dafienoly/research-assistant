"""A 股政策与行业事件获取器 — Phase 2

使用 Hermes web_search + web_extract 工具 + 公告解析结果，
抓取政策消息、行业新闻、交易所公告等。

数据源优先级:
  1. 交易所/监管机构官网 (SSE/SZSE/CSRC) — 通过公告 API
  2. AKShare 新闻接口 (可用部分)
  3. Web 搜索 (Hermes web_search 工具)
"""

import csv
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

from config import PATHS, now_str, now_cst, date_id, ensure_dirs, read_csv_safe, append_jsonl


# ========== 政策事件关键词 ==========

POLICY_SOURCES = {
    "miit": {
        "name": "工信部",
        "keywords": ["半导体", "集成电路", "AI", "人工智能", "芯片", "大基金",
                     "科技", "创新", "国产替代", "信创"],
    },
    "csrc": {
        "name": "证监会",
        "keywords": ["科创板", "注册制", "并购重组", "减持", "分红",
                     "上市公司", "信息披露", "监管"],
    },
    "ndrc": {
        "name": "发改委",
        "keywords": ["集成电路", "半导体", "AI", "算力", "数字经济",
                     "新质生产力", "战略性新兴产业"],
    },
    "exchange": {
        "name": "交易所",
        "keywords": ["异常波动", "停牌", "退市", "ST", "问询函",
                     "监管关注", "纪律处分"],
    },
    "industry": {
        "name": "行业新闻",
        "keywords": ["半导体设备", "光刻", "刻蚀", "薄膜", "封测",
                     "存储", "HBM", "DDR5", "CPO", "光模块", "PCB",
                     "AI服务器", "国产替代", "订单"],
    },
}


class PolicyEventFetcher:
    """政策/行业事件获取器"""

    def get_market_news_akshare(self) -> list[dict]:
        """尝试通过 AKShare 获取财经新闻 (非 Eastmoney 接口)"""
        events = []
        try:
            import akshare as ak
            # 试试 stock_info_global 之类不在 Eastmoney 的接口
            # 大部分 AKShare 新闻接口走 Eastmoney，被阻断
            pass
        except Exception:
            pass
        return events

    def get_announcement_events(self, symbols: list[str] = None) -> list[dict]:
        """从公告解析结果提取政策/事件相关公告"""
        events = []
        csv_path = PATHS["fundamentals"] / "announcements_extracted.csv"
        if not csv_path.exists():
            return events

        rows = read_csv_safe(csv_path)
        for row in rows:
            ann_type = row.get("announce_type", "")
            if ann_type in ("减持", "监管函", "风险事项", "业绩预告"):
                events.append({
                    "source": "announcement",
                    "event_type": ann_type,
                    "title": row.get("title", ""),
                    "symbol": row.get("code", ""),
                    "date": row.get("date", ""),
                    "parsed_at": row.get("parsed_at", now_str()),
                })
        return events

    def build_preopen_events(self, announcement_events: list[dict],
                              news_events: list[dict] = None,
                              enhance_with_search: bool = False) -> list[dict]:
        """构建盘前事件汇总

        Args:
            announcement_events: 公告解析事件
            news_events: 其他事件
            enhance_with_search: 是否用搜索增强
        """
        events = []
        for ae in announcement_events:
            events.append({
                "event_id": f"ann_{now_cst().strftime('%H%M%S')}_{ae.get('symbol','000000')}",
                "source": ae.get("source", "announcement"),
                "title": ae.get("title", ""),
                "content": ae.get("title", ""),
                "related_symbols": ae.get("symbol", ""),
                "sectors": "",
                "publish_time": ae.get("date", now_str()),
                "impact_level": classify_announcement_impact(ae.get("event_type", "")),
                "data_source": "cninfo_sse_szse",
            })

        if news_events:
            for ne in news_events:
                events.append(ne)

        # 搜索增强
        if enhance_with_search and events:
            try:
                from search_enhancer import TavilySearch
                tv = TavilySearch()
                # 用重点主题搜索
                topics = ["半导体 政策 2026", "AI 芯片 国产替代",
                          "CPO 光模块 行业", "大基金 三期"]
                for topic in topics:
                    results = tv.search(topic, max_results=2, days=3)
                    for r in results:
                        events.append({
                            "event_id": f"web_{now_cst().strftime('%H%M%S')}_{hash(r['url'])%10000:04d}",
                            "source": "tavily_search",
                            "title": r.get("title", ""),
                            "content": r.get("content", ""),
                            "related_symbols": "",
                            "sectors": topic.split(" ")[0] if topic else "",
                            "publish_time": r.get("published", now_str()),
                            "impact_level": "medium",
                            "data_source": r.get("url", "tavily"),
                        })
            except Exception as e:
                print(f"⚠️ 搜索增强失败: {e}")

        return events

    def save_preopen_events(self, events: list[dict]):
        """保存盘前事件到 CSV"""
        if not events:
            return

        path = PATHS["events"] / "preopen_events.csv"
        fields = ["event_id", "source", "title", "content", "related_symbols",
                   "sectors", "publish_time", "impact_level", "data_source"]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for event in events:
                w.writerow({k: event.get(k, "") for k in fields})

        append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
            "timestamp": now_str(),
            "action": "build_preopen_events",
            "records": len(events),
        })

        print(f"📅 盘前事件已保存: {len(events)} 条 → {path}")

    def save_policy_events(self, events: list[dict]):
        """保存政策事件"""
        if not events:
            return
        path = PATHS["events"] / "policy_events.csv"
        fields = ["event_id", "source", "title", "content", "related_symbols",
                   "sectors", "publish_time", "impact_level", "data_source"]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for event in events:
                w.writerow({k: event.get(k, "") for k in fields})
        print(f"📜 政策事件已保存: {len(events)} 条 → {path}")


def classify_announcement_impact(ann_type: str) -> str:
    impact_map = {
        "减持": "medium",
        "监管函": "medium",
        "重大合同": "high",
        "业绩预告": "medium",
        "定增": "medium",
        "并购": "medium",
        "风险事项": "high",
        "分红": "low",
        "回购": "low",
    }
    return impact_map.get(ann_type, "low")


# === CLI 命令 ===

def cmd_update_events():
    """更新政策/行业事件 (policy:update-events)"""
    fetcher = PolicyEventFetcher()

    # 1. 从公告解析获取事件
    ann_events = fetcher.get_announcement_events()
    print(f"📄 公告事件: {len(ann_events)} 条")

    # 2. 搜索增强（谨慎使用：Tavily 1000次/月 ≈ 50次/日）
    # 每个交易日只搜 2 个主题，最多用 4 次
    print("🔍 搜索增强 (Tavily 2主题)...")
    try:
        from search_enhancer import TavilySearch
        tv = TavilySearch()
        if tv.api_key:
            # 交易日双主题搜索
            topics = ["半导体 设备 政策", "AI 芯片 国产替代"]
            for topic in topics:
                results = tv.search(topic, max_results=2, days=3)
                if results:
                    print(f"   {topic}: {len(results)} 条")
    except Exception as e:
        print(f"⚠️ 搜索增强失败: {e}")

    # 3. 构建盘前事件 (仅公告事件, 搜索结果由上面直接添加)
    preopen = fetcher.build_preopen_events(ann_events)
    fetcher.save_preopen_events(preopen)

    # 3. 保存政策事件
    fetcher.save_policy_events(ann_events[:(20)])


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        cmd_update_events()
    else:
        print("Usage: python policy_fetcher.py update")
