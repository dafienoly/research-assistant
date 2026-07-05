"""统一多源 A 股数据获取器 (Provider Matrix)

镜像 Codex 数据底座的全部数据源，按优先级自动选择可用提供者。

Provider 优先级:
  1. RSScast MCP (主数据源, 需 RSSCAST_API_KEY)
  2. AKShare spot (全A快照)
  3. Tencent qt.gtimg.cn (实时行情)
  4. Sina hq.sinajs.cn (实时行情备用)
  5. CNINFO/SSE/SZSE (公告)
  6. Web search (政策/新闻)

不可用 (Eastmoney WAF geo-block — 非中国 IP 被 CDN 层拒绝):
  - Eastmoney push2.eastmoney.com (AKShare 日K线/基本面/行业板块/efinance)
  - Baostock (Akamai/CDN 层阻断)
  
补偿方案:
  - RSScast MCP 完全替代 Eastmoney 行情/K线/基本面
  - Tag maintainer 手动维护替代 AKShare 概念/行业板块
  - 全A快照使用 AKShare stock_zh_a_spot() (不同端点, 可用)
"""

import json
import time
import hashlib
from typing import Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict

from config import PATHS, now_str, append_jsonl

# ========== 审计日志 ==========

def log_fetch(provider: str, action: str, status: str, records: int = 0,
              symbols: list = None, error: str = "", duration_ms: int = 0):
    """写入 fetch_log.jsonl"""
    append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
        "timestamp": now_str(),
        "provider": provider,
        "action": action,
        "status": status,
        "records": records,
        "symbols": (symbols or [])[:5],
        "error": error[:200] if error else "",
        "duration_ms": duration_ms,
    })


# ========== RSScast MCP Provider ==========

class RSScastProvider:
    """RSScast MCP — 主数据源"""

    def __init__(self):
        from rsscast_mcp import (
            fetch_stock_prices, fetch_kline, fetch_index_prices,
            fetch_index_kline, fetch_company_overview,
            fetch_sina_quotes as _sina_fallback,
        )
        self.fetch_stock_prices = fetch_stock_prices
        self.fetch_kline = fetch_kline
        self.fetch_index_prices = fetch_index_prices
        self.fetch_index_kline = fetch_index_kline
        self.fetch_company_overview = fetch_company_overview
        self.fallback_sina = _sina_fallback
        self.name = "rsscast_mcp"

    def get_quotes(self, codes: list[str]) -> dict[str, dict]:
        """获取实时行情，返回 {code: {price, change_pct, ...}}"""
        t0 = time.time()
        try:
            data = self.fetch_stock_prices(codes)
            result = {}
            for item in data:
                code = str(item.get("code", ""))
                if code:
                    result[code] = {
                        "code": code,
                        "price": item.get("last_price"),
                        "change_pct": (item.get("change_pct", 0) or 0) * 100,
                        "change_amount": item.get("change_amount"),
                        "open": item.get("open"),
                        "high": item.get("high"),
                        "low": item.get("low"),
                        "volume": item.get("volume"),
                        "amount": item.get("amount"),
                        "amplitude": (item.get("amplitude", 0) or 0) * 100,
                        "turnover_rate": (item.get("turnover_rate", 0) or 0) * 100,
                        "prev_close": item.get("prev_close"),
                        "provider": self.name,
                    }
            log_fetch(self.name, "get_quotes", "ok", len(result), codes,
                     duration_ms=int((time.time() - t0) * 1000))
            return result
        except Exception as e:
            log_fetch(self.name, "get_quotes", "error", 0, codes, str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return {}

    def get_kline(self, codes: list[str], start: str, end: str) -> list[dict]:
        t0 = time.time()
        try:
            data = self.fetch_kline(codes, start, end)
            log_fetch(self.name, "get_kline", "ok", len(data), codes,
                     duration_ms=int((time.time() - t0) * 1000))
            return data
        except Exception as e:
            log_fetch(self.name, "get_kline", "error", 0, codes, str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return []

    def get_indices(self, codes: list[str]) -> dict[str, dict]:
        t0 = time.time()
        try:
            data = self.fetch_index_prices(codes)
            result = {str(item.get("code", "")): item for item in data if item.get("code")}
            log_fetch(self.name, "get_indices", "ok", len(result), codes,
                     duration_ms=int((time.time() - t0) * 1000))
            return result
        except Exception as e:
            log_fetch(self.name, "get_indices", "error", 0, codes, str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return {}

    def get_overview(self, symbol: str) -> dict:
        t0 = time.time()
        try:
            data = self.fetch_company_overview(symbol)
            log_fetch(self.name, "get_overview", "ok" if data else "empty", 1, [symbol],
                     duration_ms=int((time.time() - t0) * 1000))
            return data
        except Exception as e:
            log_fetch(self.name, "get_overview", "error", 0, [symbol], str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return {}


# ========== Tencent Provider ==========

class TencentProvider:
    """Tencent qt.gtimg.cn — 实时行情备用"""

    def __init__(self):
        self.name = "tencent"

    def get_quotes(self, codes: list[str]) -> dict[str, dict]:
        """获取 Tencent 实时行情"""
        import urllib.request, re
        t0 = time.time()

        def normalize(code):
            code = re.sub(r"\D", "", str(code or ""))
            return code[-6:] if len(code) >= 6 else ""

        def _prefix(code):
            c = normalize(code)
            if c.startswith(("6", "5", "9")): return "sh" + c
            if c.startswith(("0", "3", "2")): return "sz" + c
            return "sh" + c

        codes = [c for c in codes if normalize(c)]
        if not codes:
            return {}

        symbols = ",".join(_prefix(c) for c in codes)
        url = f"https://qt.gtimg.cn/q={symbols}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=8)
            text = resp.read().decode("gbk", errors="replace")
        except Exception as e:
            log_fetch(self.name, "get_quotes", "error", 0, codes, str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return {}

        result = {}
        for line in text.splitlines():
            if '=\"' not in line:
                continue
            try:
                data = line.split('=\"')[1].rstrip(';\";').split('~')
                if len(data) < 39:
                    continue
                code = normalize(data[2])
                close_str, open_str = data[4], data[5]
                high_str, low_str = data[33], data[34]
                last_str, change_pct_str = data[3], data[32]
                volume_str, amount_str = data[6], data[37]
                turnover_str, amplitude_str = data[38], data[43]

                def f(v, d=None):
                    try: return float(v)
                    except: return d

                prev_close = f(close_str)
                last = f(last_str)
                result[code] = {
                    "code": code,
                    "name": data[1],
                    "price": last,
                    "prev_close": prev_close,
                    "open": f(open_str),
                    "high": f(high_str),
                    "low": f(low_str),
                    "volume": f(volume_str, 0),
                    "amount": f(amount_str, 0),
                    "change_pct": f(change_pct_str),
                    "turnover_rate": f(turnover_str),
                    "amplitude": f(amplitude_str),
                    "provider": self.name,
                }
            except (IndexError, ValueError):
                continue

        log_fetch(self.name, "get_quotes", "ok", len(result), codes,
                 duration_ms=int((time.time() - t0) * 1000))
        return result


# ========== Sina Provider ==========

class SinaProvider:
    """Sina hq.sinajs.cn — 备用实时行情"""

    def __init__(self):
        self.name = "sina"

    def get_quotes(self, codes: list[str]) -> dict[str, dict]:
        from rsscast_mcp import fetch_sina_quotes
        t0 = time.time()
        try:
            data = fetch_sina_quotes(codes)
            result = {}
            for code, item in data.items():
                result[code] = {
                    "code": code,
                    "name": item.get("name"),
                    "price": item.get("last_price"),
                    "prev_close": item.get("prev_close"),
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "volume": item.get("volume"),
                    "amount": item.get("amount"),
                    "change_pct": item.get("change_pct"),
                    "provider": self.name,
                }
            log_fetch(self.name, "get_quotes", "ok", len(result), codes,
                     duration_ms=int((time.time() - t0) * 1000))
            return result
        except Exception as e:
            log_fetch(self.name, "get_quotes", "error", 0, codes, str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return {}


# ========== AKShare Provider ==========

class AKShareProvider:
    """AKShare — 全A快照 (仅可用 endpoint)"""

    def __init__(self):
        self.name = "akshare"

    def get_full_market_snapshot(self) -> list[dict]:
        """全A实时快照"""
        t0 = time.time()
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot()
            if df is None or df.empty:
                log_fetch(self.name, "get_full_market", "empty", 0,
                         duration_ms=int((time.time() - t0) * 1000))
                return []
            rows = df.rename(columns={
                "代码": "code", "名称": "name", "最新价": "price",
                "涨跌幅": "change_pct", "涨跌额": "change_amount",
                "成交量": "volume", "成交额": "amount",
                "振幅": "amplitude", "换手率": "turnover_rate",
                "市盈率-动态": "pe", "市净率": "pb",
            }).to_dict("records")
            log_fetch(self.name, "get_full_market", "ok", len(rows),
                     duration_ms=int((time.time() - t0) * 1000))
            return rows
        except Exception as e:
            log_fetch(self.name, "get_full_market", "error", 0, error=str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return []

    def get_stock_info(self, symbol: str) -> dict:
        try:
            import akshare as ak
            df = ak.stock_individual_info_em(symbol=symbol)
            if df is not None and len(df) > 0:
                return dict(zip(df["item"], df["value"]))
        except Exception:
            pass
        return {}


# ========== 公告 Provider (CNINFO/SSE/SZSE) ==========

class AnnouncementProvider:
    """公司公告获取 — CNINFO + SSE + SZSE"""

    def __init__(self):
        self.name = "announcement"

    def get_cninfo(self, symbol: str, page: int = 1, page_size: int = 10) -> list[dict]:
        """CNINFO 巨潮公告"""
        import urllib.request
        t0 = time.time()
        url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
        payload = json.dumps({
            "stock": f"{symbol},",
            "pageNum": page,
            "pageSize": page_size,
            "category": "",
            "seDate": "",
        }).encode()
        try:
            req = urllib.request.Request(url, data=payload, headers={
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/json",
                "Referer": "https://www.cninfo.com.cn/",
            })
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode())
            items = data.get("announcements", [])
            result = []
            for item in items:
                result.append({
                    "source": "cninfo",
                    "symbol": symbol,
                    "title": item.get("announcementTitle", ""),
                    "date": item.get("announcementDate", ""),
                    "ann_type": item.get("announcementTypeName", ""),
                    "id": item.get("announcementId", ""),
                    "adjunct_url": item.get("adjunctUrl", ""),
                    "adjunct_size": item.get("adjunctSize", ""),
                })
            log_fetch(self.name, "get_cninfo", "ok", len(result), [symbol],
                     duration_ms=int((time.time() - t0) * 1000))
            return result
        except Exception as e:
            log_fetch(self.name, "get_cninfo", "error", 0, [symbol], str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return []

    def get_sse(self, symbol: str) -> list[dict]:
        """上交所公告"""
        import urllib.request
        t0 = time.time()
        url = (f"https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
               f"?security_Code={symbol}&pageHelp.pageSize=10&pageHelp.pageNo=1")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.sse.com.cn/",
            })
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode())
            items = data.get("pageHelp", {}).get("data", [])
            result = []
            for item in items:
                result.append({
                    "source": "sse",
                    "symbol": symbol,
                    "title": item.get("TITLE", ""),
                    "date": item.get("DATE", ""),
                    "url": item.get("URL", ""),
                })
            log_fetch(self.name, "get_sse", "ok", len(result), [symbol],
                     duration_ms=int((time.time() - t0) * 1000))
            return result
        except Exception as e:
            log_fetch(self.name, "get_sse", "error", 0, [symbol], str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return []

    def get_szse(self, symbol: str) -> list[dict]:
        """深交所公告"""
        import urllib.request
        t0 = time.time()
        url = "http://www.szse.cn/api/disc/announcement/annList"
        payload = json.dumps({
            "stock": [symbol],
            "channelCode": ["fixed_disc"],
            "pageNum": 1,
            "pageSize": 10,
        }).encode()
        try:
            req = urllib.request.Request(url, data=payload, headers={
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/json",
                "Referer": "https://www.szse.cn/",
            })
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode())
            items = data.get("data", [])
            result = []
            for item in items:
                result.append({
                    "source": "szse",
                    "symbol": symbol,
                    "title": item.get("announcementTitle", ""),
                    "date": item.get("announcementDate", ""),
                    "id": item.get("id", ""),
                })
            log_fetch(self.name, "get_szse", "ok", len(result), [symbol],
                     duration_ms=int((time.time() - t0) * 1000))
            return result
        except Exception as e:
            log_fetch(self.name, "get_szse", "error", 0, [symbol], str(e),
                     duration_ms=int((time.time() - t0) * 1000))
            return []

    def get_all(self, symbol: str) -> list[dict]:
        """合并所有公告源"""
        all_items = []
        all_items.extend(self.get_cninfo(symbol))
        all_items.extend(self.get_sse(symbol))
        all_items.extend(self.get_szse(symbol))
        return all_items


# ========== 统一调度器 ==========

class ProviderMatrix:
    """统一多源数据调度器

    Provider 优先级 (免费无限量优先, RSScast 备用):
      实时行情: Eastmoney Direct > RSScast MCP > Tencent > Sina
      K线: Tencent > RSScast MCP
      基本面/指数: RSScast MCP
      全A快照: AKShare spot
    """

    def __init__(self):
        from eastmoney_direct import EastmoneyProvider, TencentProvider as TencentKlineProvider
        self.eastmoney_direct = EastmoneyProvider()
        self.tencent_kline = TencentKlineProvider()
        self.rsscast = RSScastProvider()
        self.tencent = TencentProvider()
        self.sina = SinaProvider()
        self.akshare = AKShareProvider()
        self.announcement = AnnouncementProvider()
        self._provider_status = {}

    def get_quotes(self, codes: list[str], prefer: str = "eastmoney") -> dict[str, dict]:
        """获取实时行情，免费无限量优先"""
        errors = []

        providers_order = {
            "eastmoney": [self.eastmoney_direct, self.rsscast, self.tencent, self.sina],
            "rsscast": [self.rsscast, self.eastmoney_direct, self.tencent, self.sina],
        }.get(prefer, [self.eastmoney_direct, self.rsscast, self.tencent, self.sina])

        for provider in providers_order:
            try:
                result = provider.get_quotes(codes)
                if result:
                    return result
            except Exception as e:
                errors.append(f"{provider.name}: {e}")
                continue

        log_fetch("provider_matrix", "get_quotes", "all_failed", 0, codes,
                 error="; ".join(errors))
        return {}

    def get_kline(self, codes: list[str], start: str, end: str) -> list[dict]:
        """日K线，Tencent 优先（免费无限量），RSScast 备用"""
        errors = []
        # Tencent 只支持单只查询
        for provider in [self.tencent_kline, self.rsscast]:
            try:
                if provider is self.tencent_kline:
                    # 单只
                    all_data = []
                    for code in codes:
                        data = provider.get_kline(code, start, end)
                        all_data.extend(data)
                    if all_data:
                        return all_data
                else:
                    result = provider.get_kline(codes, start, end)
                    if result:
                        return result
            except Exception as e:
                errors.append(f"{provider.name}: {e}")
                continue

        log_fetch("provider_matrix", "get_kline", "all_failed", 0, codes,
                 error="; ".join(errors))
        return []

    def get_full_market(self) -> list[dict]:
        return self.akshare.get_full_market_snapshot()

    def get_indices(self, codes: list[str]) -> dict[str, dict]:
        return self.rsscast.get_indices(codes)

    def get_announcements(self, symbol: str) -> list[dict]:
        return self.announcement.get_all(symbol)

    def get_overview(self, symbol: str) -> dict:
        return self.rsscast.get_overview(symbol)


# ========== 简便单例 ==========
_provider = None

def get_provider() -> ProviderMatrix:
    global _provider
    if _provider is None:
        _provider = ProviderMatrix()
    return _provider


# === CLI 测试 ===
if __name__ == "__main__":
    import sys
    pm = get_provider()

    if len(sys.argv) > 1 and sys.argv[1] == "quotes":
        codes = sys.argv[2:] or ["688012", "002371"]
        result = pm.get_quotes(codes)
        for code, data in result.items():
            chg = data.get("change_pct")
            print(f'{data.get("name",code)} ({code}): {data.get("price")} ({chg:.2f}%)' if chg else f'{data.get("name",code)} ({code}): {data.get("price")}')

    elif sys.argv[1] == "announcements":
        symbol = sys.argv[2] if len(sys.argv) > 2 else "688012"
        items = pm.get_announcements(symbol)
        print(f'{symbol} 公告 ({len(items)} 条):')
        for item in items[:5]:
            print(f'  [{item["source"]}] {item.get("date","")}: {item.get("title","")[:60]}')

    elif sys.argv[1] == "market":
        data = pm.get_full_market()
        print(f'全A: {len(data)} 只')
        if data:
            print(f'样本: {data[0].get("code")} {data[0].get("name")} {data[0].get("price")}')

    elif sys.argv[1] == "indices":
        codes = sys.argv[2:] or ["000001", "000688", "399001"]
        result = pm.get_indices(codes)
        for code, data in result.items():
            print(f'{code}: {data.get("last_price","?")}')

    else:
        print("Usage: python provider_matrix.py <quotes|announcements|market|indices> [codes...]")
