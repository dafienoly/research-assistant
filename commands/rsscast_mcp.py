"""RSScast MCP Client — A-share data via MCP protocol

Environment: RSSCAST_API_KEY
Docs: https://app-cn.rsscast.io

Proxy policy: ALL domestic financial data sources bypass Clash proxy
(eastmoney, sina, tencent, joinquant, csindex, rsscast, etc.)
Overseas APIs (Tavily, Firecrawl) keep using proxy.
"""
import json
import os
import urllib.request
import urllib.error
from typing import Any, Optional
from datetime import datetime, timezone

from config import now_str

# 国内数据源域名字典（用于 NO_PROXY，保持与 dive_prediction/proxy_bypass.py 同步）
# DataHub 管线所有 HTTP 请求自动绕过 Clash proxy 访问国内金融数据源
_DOMESTIC_DOMAINS = [
    # 东方财富
    "eastmoney.com", "push2.eastmoney.com", "push2his.eastmoney.com",
    "17.push2.eastmoney.com", "datacenter.eastmoney.com",
    "datacenter-web.eastmoney.com", "quote.eastmoney.com",
    "data.eastmoney.com", "www.eastmoney.com",
    # 新浪
    "sina.com.cn", "hq.sinajs.cn", "vip.stock.finance.sina.com.cn",
    "finance.sina.com.cn",
    # 腾讯
    "gtimg.cn", "qt.gtimg.cn", "web.ifzq.gtimg.cn", "ifzq.gtimg.cn",
    # 聚宽
    "joinquant.com", "dataapi.joinquant.com", "www.joinquant.com",
    # 中证指数
    "csindex.com.cn", "www.csindex.com.cn",
    # RSScast
    "rsscast.io", "app-cn.rsscast.io",
]

# 模块加载时自动将国内数据源加入 NO_PROXY
_NO_PROXY_ADDED = False
def _ensure_no_proxy():
    global _NO_PROXY_ADDED
    if _NO_PROXY_ADDED:
        return
    existing = set()
    for val in [os.environ.get("NO_PROXY", ""), os.environ.get("no_proxy", "")]:
        for d in val.split(","):
            d = d.strip()
            if d:
                existing.add(d)
    for d in _DOMESTIC_DOMAINS:
        existing.add(d)
    merged = ",".join(sorted(existing))
    os.environ["NO_PROXY"] = merged
    os.environ["no_proxy"] = merged
    _NO_PROXY_ADDED = True

_ensure_no_proxy()


# === MCP 客户端 ===

MCP_URL = "https://app-cn.rsscast.io/api/mcp/v1/mcp"


def get_api_key() -> str:
    key = os.environ.get("RSSCAST_API_KEY", "")
    if not key:
        print("⚠️ RSSCAST_API_KEY 未设置，MCP 调用将失败")
    return key


def mcp_call(method: str, params: Optional[dict] = None) -> dict:
    """调用 RSScast MCP 接口"""
    api_key = get_api_key()
    if not api_key:
        return {"error": "RSSCAST_API_KEY not set"}

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }).encode("utf-8")

    req = urllib.request.Request(
        MCP_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Hermes-Agent/2.0",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        return {"error": str(e)}


def extract_text(result: dict) -> str:
    """从 MCP 结果中提取文本内容"""
    if "error" in result:
        return f"MCP Error: {result['error']}"
    content = result.get("result", {}).get("content", [])
    if not content:
        return ""
    return content[0].get("text", "")


def parse_json_from_text(text: str) -> list:
    """从 MCP 返回文本中提取 JSON 数组"""
    # 文本格式: "说明文字 [json数据]"
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(text[start:end+1])
    except json.JSONDecodeError:
        return []


# === 具体数据 API ===

def fetch_stock_prices(codes: list[str]) -> list[dict]:
    """获取股票实时行情

    Args:
        codes: 6位股票代码列表，如 ['688012', '002371']

    Returns:
        list of dict: [{code, last_price, prev_close, open, high, low,
                        volume, amount, change_pct, amplitude, turnover_rate,
                        unixtime, timeString}]
    """
    result = mcp_call("tools/call", {
        "name": "StockPriceQuery",
        "arguments": {"codes": codes},
    })
    text = extract_text(result)
    if not text or text.startswith("MCP Error"):
        print(f"⚠️ StockPriceQuery 失败: {text}")
        return []
    return parse_json_from_text(text)


def fetch_kline(codes: list[str], start_date: str, end_date: str) -> list[dict]:
    """获取股票日K线（先试聚宽，失败回退 RSScast MCP）

    Args:
        codes: 股票/ETF代码列表
        start_date: YYYYMMDD
        end_date: YYYYMMDD

    Returns:
        list of dict: [{code, unixtime, timeString, open, high, low, close, volume, amount}]
    """
    if codes:
        from dive_prediction.proxy_bypass import no_proxy_for as _npf
        import jqdatasdk as _jq
        _JQ_AUTHED = False
        try:
            with _npf("joinquant"):
                _JQ_AUTHED = bool(_jq.get_account_info())
        except Exception:
            pass
        if not _JQ_AUTHED:
            try:
                with _npf("joinquant"):
                    _jq.auth('13500226163', 'Ly19940930!')
                    _JQ_AUTHED = True
            except Exception:
                pass

        if _JQ_AUTHED:
            result = []
            for code in codes:
                try:
                    sec = f"{code}.XSHE" if code.startswith(("00", "30", "15")) else f"{code}.XSHG"
                    if code.startswith(("51", "56")):
                        sec = f"{code}.XSHG"  # Shanghai-listed ETFs
                    sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
                    ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
                    # 分批拉取（每次最多60天，绕过聚宽境外IP限制）
                    all_rows = []
                    import pandas as _pd
                    from datetime import datetime as _dt, timedelta as _td
                    cur = _dt.strptime(sd, "%Y-%m-%d")
                    end_dt = _dt.strptime(ed, "%Y-%m-%d")
                    while cur < end_dt:
                        chunk_end = min(cur + _td(days=60), end_dt)
                        with _npf("joinquant"):
                            df = _jq.get_price(sec, start_date=cur.strftime("%Y-%m-%d"),
                                                end_date=chunk_end.strftime("%Y-%m-%d"),
                                                frequency='daily',
                                                fields=['open', 'close', 'high', 'low', 'volume', 'money'])
                        for dt, row in df.iterrows():
                            all_rows.append({
                                "code": code,
                                "timeString": dt.strftime("%Y-%m-%d"),
                                "unixtime": int(dt.timestamp()),
                                "open": float(row['open']),
                                "high": float(row['high']),
                                "low": float(row['low']),
                                "close": float(row['close']),
                                "volume": int(row['volume']),
                                "amount": float(row['money']),
                            })
                        cur = chunk_end + _td(days=1)
                    result.extend(all_rows)
                except Exception as e:
                    print(f"  ⚠️ JQData {code}: {e}")
            if result:
                return result

    # Fallback: RSScast MCP
    result = mcp_call("tools/call", {
        "name": "StockKLineQuery",
        "arguments": {
            "codes": codes,
            "startDate": start_date,
            "endDate": end_date,
        },
    })
    text = extract_text(result)
    if not text or text.startswith("MCP Error"):
        print(f"⚠️ StockKLineQuery 失败: {text}")
        return []
    return parse_json_from_text(text)


def fetch_index_prices(codes: list[str]) -> list[dict]:
    """获取指数实时行情

    Args:
        codes: 指数代码如 ['000001', '000688', '399001']

    Returns:
        list of dict
    """
    result = mcp_call("tools/call", {
        "name": "StockIndexPriceQuery",
        "arguments": {"codes": codes},
    })
    text = extract_text(result)
    if not text or text.startswith("MCP Error"):
        print(f"⚠️ StockIndexPriceQuery 失败: {text}")
        return []
    return parse_json_from_text(text)


def fetch_index_kline(codes: list[str], start_date: str, end_date: str) -> list[dict]:
    """获取指数日K线"""
    result = mcp_call("tools/call", {
        "name": "StockIndexKLineQuery",
        "arguments": {
            "codes": codes,
            "startDate": start_date,
            "endDate": end_date,
        },
    })
    text = extract_text(result)
    if not text or text.startswith("MCP Error"):
        print(f"⚠️ StockIndexKLineQuery 失败: {text}")
        return []
    return parse_json_from_text(text)


def fetch_company_overview(symbol: str) -> dict:
    """获取公司概况/基本面

    Args:
        symbol: 6位股票代码

    Returns:
        dict with revenueComposition, financialTrend, dividend, financialIndicators, shareholders
    """
    result = mcp_call("tools/call", {
        "name": "StockOverviewQuery",
        "arguments": {"symbol": symbol},
    })
    text = extract_text(result)
    if not text or text.startswith("MCP Error"):
        print(f"⚠️ StockOverviewQuery 失败: {text}")
        return {}
    data = parse_json_from_text(text)
    return data[0] if data else {}


# === Sina 行情备用 ===

def fetch_sina_quotes(codes: list[str]) -> dict[str, dict]:
    """Sina 实时行情（备用，无 Key 依赖）

    Args:
        codes: 股票代码列表（6位数字）

    Returns:
        dict[code, {last_price, prev_close, open, high, low, volume, amount, change_pct, name}]
    """
    import re

    def normalize_code(code: str) -> str:
        code = re.sub(r"\D", "", str(code or ""))
        return code[-6:] if len(code) >= 6 else ""

    def sina_symbol(code: str) -> str:
        code = normalize_code(code)
        if code in ("000001", "000688", "000300", "000905", "000852"):
            return "sh" + code
        if code.startswith(("399", "159")):
            return "sz" + code
        if code.startswith(("6", "5", "9")):
            return "sh" + code
        return "sz" + code

    normalized = [normalize_code(c) for c in codes if normalize_code(c)]
    if not normalized:
        return {}

    symbols = ",".join(sina_symbol(c) for c in normalized)
    url = "https://hq.sinajs.cn/list=" + symbols
    req = urllib.request.Request(
        url,
        headers={
            "Referer": "https://finance.sina.com.cn/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=8)
        text = resp.read().decode("gbk", errors="replace")
    except Exception as e:
        print(f"⚠️ Sina quotes 失败: {e}")
        return {}

    out = {}
    for line in text.splitlines():
        if '="' not in line:
            continue
        left, payload = line.split('="', 1)
        raw_symbol = left.rsplit("_", 1)[-1]
        code = normalize_code(raw_symbol)
        fields = payload.rstrip('";').split(",")
        if len(fields) < 32 or not code:
            continue
        try:
            last = float(fields[3]) if fields[3] else None
            prev_close = float(fields[2]) if fields[2] else None
        except ValueError:
            last, prev_close = None, None
        out[code] = {
            "code": code,
            "name": fields[0],
            "last_price": last,
            "prev_close": prev_close,
            "open": float(fields[1]) if fields[1] else None,
            "high": float(fields[4]) if fields[4] else None,
            "low": float(fields[5]) if fields[5] else None,
            "volume": float(fields[8]) if fields[8] else 0,
            "amount": float(fields[9]) if fields[9] else 0,
            "change_pct": (last / prev_close - 1) if last and prev_close else None,
            "source": "sina",
        }
    return out


# === AKShare 辅助 ===

def fetch_akshare_spot() -> list[dict]:
    """AKShare 全A实时快照（备用数据源）"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot()
        if df is None or df.empty:
            return []
        # 标准化字段名
        df = df.rename(columns={
            "代码": "code", "名称": "name", "最新价": "last_price",
            "涨跌幅": "change_pct", "涨跌额": "change_amount",
            "成交量": "volume", "成交额": "amount",
            "振幅": "amplitude", "换手率": "turnover_rate",
            "市盈率-动态": "pe", "市净率": "pb",
        })
        return df.to_dict("records")
    except Exception as e:
        print(f"⚠️ AKShare spot 失败: {e}")
        return []


# === 测试 ===

def mcp_list_tools() -> list:
    """列出 MCP 可用工具（用于测试）"""
    result = mcp_call("tools/list")
    if "error" in result:
        print(f"❌ MCP list_tools 失败: {result['error']}")
        return []
    tools = result.get("result", {}).get("tools", [])
    return [(t["name"], t.get("description", "")[:80]) for t in tools]


if __name__ == "__main__":
    print("=== MCP 工具列表 ===")
    for name, desc in mcp_list_tools():
        print(f"  {name}: {desc}")

    print("\n=== 实时行情测试 ===")
    prices = fetch_stock_prices(["688012", "002371"])
    for p in prices:
        print(f"  {p['code']}: {p.get('last_price')} ({p.get('change_pct',0)*100:.2f}%)")

    print("\n=== 指数行情测试 ===")
    idx = fetch_index_prices(["000001", "000688"])
    for i in idx:
        print(f"  {i.get('code')}: {i.get('last_price')}")

    print("\n=== Sina 备用行情 ===")
    sina = fetch_sina_quotes(["688012", "002371"])
    for code, data in sina.items():
        chg = data.get('change_pct')
        print(f"  {code}: {data.get('last_price')} ({chg*100:.2f}% )" if chg else f"  {code}: {data.get('last_price')}")
