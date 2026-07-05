"""妙想金融 — Hermes 数据增强入口

API 端点:
  mx-data:    https://mkapi2.dfcfs.com/finskillshub/api/claw/query       金融数据查询
  mx-search:  https://mkapi2.dfcfs.com/finskillshub/api/claw/news-search   资讯搜索
  mx-xuangu:  https://mkapi2.dfcfs.com/finskillshub/api/claw/stock-screen  智能选股
"""

import os, sys, json, requests

API_KEY = os.getenv("MX_APIKEY")
if not API_KEY:
    print(json.dumps({"error": "MX_APIKEY 未设置，请先在 .bashrc 中 export MX_APIKEY=..."}, ensure_ascii=False))
    sys.exit(1)

BASE_URLS = {
    "data":   "https://mkapi2.dfcfs.com/finskillshub/api/claw/query",
    "search": "https://mkapi2.dfcfs.com/finskillshub/api/claw/news-search",
    "xuangu": "https://mkapi2.dfcfs.com/finskillshub/api/claw/stock-screen",
}

def query(endpoint: str, question: str) -> dict:
    """调用妙想 API"""
    url = BASE_URLS.get(endpoint)
    if not url:
        return {"error": f"未知端点: {endpoint}"}
    headers = {"apikey": API_KEY, "Content-Type": "application/json"}
    # 各端点字段名不同
    field_map = {"data": "toolQuery", "search": "query", "xuangu": "keyword"}
    field = field_map.get(endpoint, "query")
    data = {field: question}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        return result
    except Exception as e:
        return {"error": str(e)}

def format_data(result: dict) -> str:
    """格式化数据查询结果"""
    lines = []
    if "error" in result:
        return f"❌ {result['error']}"
    if result.get("code") != 0:
        return f"⚠️ API 返回异常: {result.get('message', '未知')}"
    
    inner = result.get("data", {})
    inner2 = inner.get("data", {}) if isinstance(inner, dict) else {}
    
    # 尝试提取 searchDataResultDTO.dataTableDTOList
    dtos = inner2.get("searchDataResultDTO", {}) or inner.get("searchDataResultDTO", {})
    tables = dtos.get("dataTableDTOList", [])
    if not tables:
        # 尝试直接取 table/rows
        return json.dumps(result.get("data", {}), ensure_ascii=False, indent=2)[:2000]
    
    label_map = {
        "f62": "主力净流入", "f184": "主力净比",
        "f66": "超大单净流入", "f69": "超大单净比",
        "f72": "大单净流入", "f75": "大单净比",
        "f78": "中单净流入", "f81": "中单净比",
        "f84": "小单净流入", "f87": "小单净比",
        "f64": "5日主力净流入", "f65": "5日主力净流入",
    }
    
    for t in tables[:5]:
        name = t.get("entityName", "")
        table = t.get("table", {})
        timestamp = (table.get("headName") or [""])[0] if isinstance(table.get("headName"), list) else ""
        if name:
            lines.append(f"\n**{name}**  ({timestamp})")
        # 资金流向字段
        for field_key, field_label in label_map.items():
            vals = table.get(field_key, [])
            if vals and len(vals) > 0:
                lines.append(f"  {field_label}: {vals[0]}")
        # 其他字段
        for k, v in table.items():
            if k not in label_map and k != "headName":
                if isinstance(v, list) and len(v) > 0:
                    lines.append(f"  {k}: {v[0]}")
    
    return "\n".join(lines) if lines else json.dumps(result, ensure_ascii=False, indent=2)[:2000]

def format_search(result: dict) -> str:
    """格式化搜索结果为 Markdown"""
    if "error" in result:
        return f"❌ {result['error']}"
    if result.get("code") != 0:
        return f"⚠️ API 返回异常: {result.get('message', '未知')}"
    
    inner = result.get("data", {})
    inner2 = inner.get("data", {}) if isinstance(inner, dict) else {}
    
    lines = []
    # llmSearchResponse
    lr = inner2.get("llmSearchResponse", {}) or inner.get("llmSearchResponse", {})
    items = lr.get("data", [])
    
    if not items:
        # 尝试其他格式
        sr = inner2.get("searchResponse", {}) or inner.get("searchResponse", {})
        items = sr.get("data", [])
    
    if isinstance(items, list):
        for item in items[:10]:
            if isinstance(item, dict):
                title = item.get("newsTitle") or item.get("title") or ""
                summary = item.get("summary") or item.get("content") or ""
                source = item.get("sourceName") or item.get("source") or ""
                url = item.get("newsUrl") or item.get("url") or ""
                pub_date = item.get("pubDate") or item.get("date") or ""
                lines.append(f"- **{title}**  [{source}] ({pub_date})")
                if summary:
                    lines.append(f"  {summary[:200]}")
                lines.append("")
    if not lines:
        lines.append(json.dumps(result.get("data", {}), ensure_ascii=False, indent=2)[:1500])
    return "\n".join(lines)

def format_xuangu(result: dict) -> str:
    """格式化选股结果"""
    if "error" in result:
        return f"❌ {result['error']}"
    if result.get("code") != 0:
        return f"⚠️ API 返回异常: {result.get('message', '未知')}"
    
    inner = result.get("data", {})
    inner2 = inner.get("data", {}) if isinstance(inner, dict) else {}
    
    lines = []
    stocks = inner2.get("stocks", []) or inner.get("stocks", []) or inner2.get("data", []) or inner2.get("result", [])
    if isinstance(stocks, list):
        lines.append(f"共 {len(stocks)} 只股票")
        for s in stocks[:20]:
            if isinstance(s, dict):
                code = s.get("code") or s.get("CODE") or ""
                name = s.get("name") or s.get("NAME") or ""
                price = s.get("price") or s.get("latestPrice") or s.get("close") or ""
                pct = s.get("changePct") or s.get("pctChg") or ""
                lines.append(f"  {code} {name}  {price}  {pct}")
    if not lines:
        lines.append(json.dumps(result.get("data", {}), ensure_ascii=False, indent=2)[:1500])
    return "\n".join(lines)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法:")
        print("  python3 mx.py data   <自然语言问句>   # 金融数据查询")
        print("  python3 mx.py search <关键词>         # 资讯搜索")
        print("  python3 mx.py xuangu <选股条件>       # 智能选股")
        print("")
        print("示例:")
        print('  python3 mx.py data   "雷赛智能主力资金流向"')
        print('  python3 mx.py search "雷赛智能 最新公告 2026"')
        print('  python3 mx.py xuangu "半导体板块 放量突破20日均线 近3日"')
        sys.exit(1)

    cmd = sys.argv[1]
    question = " ".join(sys.argv[2:])
    result = query(cmd, question)

    if cmd == "data":
        print(format_data(result))
    elif cmd == "search":
        print(format_search(result))
    elif cmd == "xuangu":
        print(format_xuangu(result))
    else:
        print(f"未知命令: {cmd}，可用: data / search / xuangu")