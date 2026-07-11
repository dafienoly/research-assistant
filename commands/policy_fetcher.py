"""A 股政策与行业事件获取器 — Phase 2

从 DataHub canonical 公告快照构建政策与盘前事件派生视图。

数据源优先级:
  1. 交易所/监管机构官网 (SSE/SZSE/CSRC) — 通过公告 API
  2. AKShare 新闻接口 (可用部分)
  3. Web 搜索 (Hermes web_search 工具)
"""

import json
from pathlib import Path

import pandas as pd

from config import PATHS, now_str, now_cst, append_jsonl
from announcement_parser import classify_announcement
from data_recovery import atomic_write_frame
from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion


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

    def __init__(self, snapshot_path: Path | None = None):
        self.snapshot_path = snapshot_path or (
            Path(__file__).resolve().parents[1] / "data/normalized/events/regulatory_watchlist.json"
        )
        self.snapshot_meta: dict = {}

    def get_announcement_events(self, symbols: list[str] = None) -> list[dict]:
        """从 DataHub canonical 公告快照提取政策/事件。"""
        events = []
        if not self.snapshot_path.exists():
            raise FileNotFoundError(f"canonical announcement snapshot missing: {self.snapshot_path}")
        snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        self.snapshot_meta = snapshot
        covered = set(snapshot.get("covered_symbols", []))
        requested = {"".join(ch for ch in str(symbol) if ch.isdigit())[:6] for symbol in (symbols or [])}
        if requested and not requested.issubset(covered):
            raise ValueError(f"canonical announcement coverage missing: {sorted(requested - covered)}")
        for row in snapshot.get("announcements", []):
            if requested and row.get("symbol") not in requested:
                continue
            ann_type = classify_announcement(str(row.get("title", "")))
            if ann_type in ("减持", "监管函", "风险事项", "业绩预告"):
                events.append({
                    "source": row.get("source", "announcement"),
                    "event_type": ann_type,
                    "title": row.get("title", ""),
                    "symbol": row.get("symbol", ""),
                    "date": row.get("date", ""),
                    "parsed_at": snapshot.get("generated_at", now_str()),
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
        path = PATHS["events"] / "preopen_events.csv"
        fields = ["event_id", "source", "title", "content", "related_symbols",
                   "sectors", "publish_time", "impact_level", "data_source"]
        self._publish(events, path, fields, "events/preopen_events")

        audit_path = PATHS["audit"] / "fetch_log.jsonl"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(audit_path, {
            "timestamp": now_str(),
            "action": "build_preopen_events",
            "records": len(events),
        })

        print(f"📅 盘前事件已保存: {len(events)} 条 → {path}")

    def save_policy_events(self, events: list[dict]):
        """保存政策事件"""
        path = PATHS["events"] / "policy_events.csv"
        fields = ["event_id", "source", "title", "content", "related_symbols",
                   "sectors", "publish_time", "impact_level", "data_source"]
        self._publish(events, path, fields, "events/policy_events")
        print(f"📜 政策事件已保存: {len(events)} 条 → {path}")

    def _publish(self, events: list[dict], path: Path, fields: list[str], dataset: str) -> None:
        frame = pd.DataFrame(
            [{key: event.get(key, "") for key in fields} for event in events],
            columns=fields,
        )
        content_hash = atomic_write_frame(frame, path)
        manifest = {
            "status": "OK" if events else "EMPTY",
            "dataset": dataset,
            "generated_at": now_str(),
            "rows": len(events),
            "sha256": content_hash,
            "source": "datahub_regulatory_watchlist",
            "source_generated_at": self.snapshot_meta.get("generated_at"),
            "covered_symbols": self.snapshot_meta.get("covered_symbols", []),
            "coverage_policy": "CSV content is valid only with this canonical coverage manifest",
        }
        EventTruthIngestion._atomic_json(path.with_suffix(".manifest.json"), manifest)


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

    # 2. 构建 canonical 公告派生事件；新闻催化剂由独立 DataHub ingestion 负责。
    preopen = fetcher.build_preopen_events(ann_events)
    fetcher.save_preopen_events(preopen)

    # 3. policy/preopen 使用同一标准化 schema，避免写入空字段。
    fetcher.save_policy_events(preopen[:20])


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        cmd_update_events()
    else:
        print("Usage: python policy_fetcher.py update")
