"""A 股公告解析器 — CNINFO + SSE + SZSE

Phase 2 实现: 从三大交易所公告源拉取并解析公告，
提取减持、监管函、重大合同、业绩预告等关键事件。
"""

import csv
import re
import time
from pathlib import Path

from config import PATHS, now_str, now_cst, date_id, ensure_dirs, read_csv_safe, append_jsonl
from provider_matrix import AnnouncementProvider


# ========== 公告分类 ==========

EVENT_KEYWORDS = {
    "减持": ["减持", "减持股", "减持计划", "减持进展"],
    "监管函": ["监管函", "监管措施", "警示函", "责令改正", "立案"],
    "重大合同": ["重大合同", "签订合同", "中标", "订单", "获得订单"],
    "业绩预告": ["业绩预告", "业绩预增", "业绩预减", "业绩快报", "业绩修正"],
    "定增": ["非公开发行", "定增", "定向增发", "募集资金"],
    "并购": ["并购", "收购", "重组", "资产出售", "股权转让"],
    "风险事项": ["退市风险", "ST", "*ST", "暂停上市", "破产重整"],
    "分红": ["分红", "派息", "利润分配", "送转"],
    "回购": ["回购", "股份回购"],
    "股权激励": ["股权激励", "限制性股票", "期权"],
}


def classify_announcement(title: str) -> str:
    """根据标题分类公告"""
    title_lower = title.lower()
    for ann_type, keywords in EVENT_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                return ann_type
    return "其他"


def extract_symbols_from_cninfo(items: list[dict], target_symbol: str) -> list[dict]:
    """从 CNINFO 结果中筛选出匹配目标股票代码的公告"""
    filtered = []
    for item in items:
        # CNINFO 返回的 orgId/secCode 可能不在标准字段中
        # 直接在标题/内容中搜索股票代码做二次校验
        title = item.get("title", "")
        # 有些公告是跨公司的，先返回全部，由调用方按需筛选
        filtered.append(item)
    return filtered


class AnnouncementParser:
    """公告解析器"""

    def __init__(self):
        self.provider = AnnouncementProvider()

    def parse_for_stock(self, symbol: str) -> list[dict]:
        """获取并解析单个股票的近期公告"""
        all_items = self.provider.get_all(symbol)

        parsed = []
        for item in all_items:
            title = item.get("title", "")
            ann_type = classify_announcement(title)
            parsed.append({
                "code": symbol,
                "source": item.get("source", ""),
                "announce_type": ann_type,
                "title": title,
                "date": item.get("date", ""),
                "announce_id": item.get("id", item.get("announce_id", "")),
                "parsed_at": now_str(),
            })

        return parsed

    def parse_all(self, symbols: list[str], limit: int = 10) -> list[dict]:
        """批量解析所有关注的股票"""
        all_parsed = []
        for symbol in symbols:
            try:
                items = self.parse_for_stock(symbol)
                all_parsed.extend(items)
                time.sleep(0.5)  # 避免频率限制
            except Exception as e:
                print(f"⚠️ {symbol} 公告解析失败: {e}")

            if limit and len(all_parsed) >= limit:
                break

        return all_parsed

    def save(self, parsed: list[dict]):
        """保存解析结果到 announcements_extracted.csv"""
        if not parsed:
            return

        path = PATHS["fundamentals"] / "announcements_extracted.csv"
        fields = ["code", "source", "announce_type", "title", "date",
                   "announce_id", "parsed_at"]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for item in parsed:
                w.writerow({k: item.get(k, "") for k in fields})

        # 写入审计
        append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
            "timestamp": now_str(),
            "action": "parse_announcements",
            "source": "cninfo+sse+szse",
            "records": len(parsed),
        })

        print(f"📄 公告已保存: {len(parsed)} 条 → {path}")


# === CLI 命令 ===

def cmd_parse():
    """解析最新公告 (announcements:parse)"""
    # 从标签/关注池获取股票列表
    tags_paths = [
        PATHS["tags"] / "semiconductor_chain_tags.csv",
        PATHS["tags"] / "stock_theme_tags.csv",
    ]
    symbols = set()
    for tp in tags_paths:
        for row in read_csv_safe(tp):
            code = str(row.get("code", "")).strip()
            if code:
                symbols.add(code)

    if not symbols:
        # 从 pool.csv 获取样本
        pool = read_csv_safe(PATHS["market"] / "pool.csv")
        symbols = {r.get("code", "") for r in pool[:20] if r.get("code")}

    symbols = sorted(symbols)[:20]  # 限制数量
    print(f"🔍 解析 {len(symbols)} 只股票的公告...")

    parser = AnnouncementParser()
    parsed = parser.parse_all(symbols, limit=200)
    parser.save(parsed)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "parse":
        cmd_parse()
    elif len(sys.argv) > 2 and sys.argv[1] == "stock":
        parser = AnnouncementParser()
        items = parser.parse_for_stock(sys.argv[2])
        for item in items[:5]:
            print(f"  [{item['announce_type']}] {item['date']}: {item['title'][:60]}")
        print(f"共 {len(items)} 条")
    else:
        print("Usage: python announcement_parser.py parse|stock <code>")
