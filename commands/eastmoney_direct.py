"""Eastmoney + Tencent 免费无限量数据源

Eastmoney push2.eastmoney.com:
  ✅ /api/qt/stock/get — 实时行情 (HTTP 200, 无限制)
  ❌ /api/qt/stock/kline/get — K线 (后端 geo-restricted)

Tencent web.ifzq.gtimg.cn:
  ✅ /appstock/app/fqkline/get — 日K线 (HTTP 200, 无限制)

RSScast MCP — premium 备用 (有额度限制)
"""

import json
import time
import urllib.request
from typing import Optional

from config import PATHS, now_str, append_jsonl


def log(provider, action, status, records=0, symbols=None, error=""):
    append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
        "timestamp": now_str(), "provider": provider, "action": action,
        "status": status, "records": records,
        "symbols": (symbols or [])[:5], "error": str(error)[:200],
    })


class EastmoneyProvider:
    """Eastmoney 实时行情 (免费无限量)"""

    def __init__(self):
        self.name = "eastmoney_direct"

    def get_quotes(self, codes: list[str]) -> dict[str, dict]:
        """获取实时行情，使用直接可用的 /api/qt/stock/get 端点"""
        t0 = time.time()
        result = {}
        for code in codes:
            # secid: 1=上交所, 0=深交所
            secid = f"1.{code}" if code.startswith(("6", "5", "9")) else f"0.{code}"
            url = ("https://push2.eastmoney.com/api/qt/stock/get"
                   f"?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f170,f171,f843")
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://quote.eastmoney.com/",
                })
                resp = urllib.request.urlopen(req, timeout=8)
                data = json.loads(resp.read().decode())
                if data.get("rc") == 0 and data.get("data"):
                    d = data["data"]
                    change_pct = d.get("f170")
                    change_amount = d.get("f171")
                    result[code] = {
                        "code": code,
                        "name": d.get("f58", ""),
                        "price": d.get("f43") / 100 if d.get("f43") else None,
                        "high": d.get("f44") / 100 if d.get("f44") else None,
                        "low": d.get("f45") / 100 if d.get("f45") else None,
                        "open": d.get("f46") / 100 if d.get("f46") else None,
                        "volume": d.get("f47"),
                        "amount": d.get("f48"),
                        "change_pct": d.get("f170") / 100 if d.get("f170") is not None else None,
                        "change_amount": d.get("f171") / 100 if d.get("f171") else None,
                        "provider": self.name,
                    }
            except Exception:
                pass
            time.sleep(0.05)  # 避免频率限制
        log(self.name, "get_quotes", "ok" if result else "empty",
            len(result), codes)
        return result


class TencentProvider:
    """Tencent 日K线 (免费无限量)"""

    def __init__(self):
        self.name = "tencent_kline"

    def _map_to_sina_prefix(self, code: str) -> str:
        if code.startswith(("6", "5", "9")):
            return f"sh{code}"
        return f"sz{code}"

    def get_kline(self, code: str, start: str, end: str = None) -> list[dict]:
        """获取日K线"""
        t0 = time.time()
        prefix_code = self._map_to_sina_prefix(code)
        url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               f"?param={prefix_code},day,{start},,1,qfq")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.qq.com/",
            })
            resp = urllib.request.urlopen(req, timeout=8)
            data = json.loads(resp.read().decode())
            stock_data = data.get("data", {}).get(prefix_code, {})
            # 尝试 qfqday > day > hfqday
            klines = (stock_data.get("qfqday") or stock_data.get("day")
                      or stock_data.get("hfqday") or [])
            result = []
            for k in klines:
                if len(k) >= 6:
                    result.append({
                        "date": k[0],
                        "open": float(k[1]) if k[1] else None,
                        "close": float(k[2]) if k[2] else None,
                        "high": float(k[3]) if k[3] else None,
                        "low": float(k[4]) if k[4] else None,
                        "volume": float(k[5]) if k[5] else None,
                        "code": code,
                        "provider": self.name,
                    })
            log(self.name, "get_kline", "ok" if result else "empty",
                len(result), [code])
            return result
        except Exception as e:
            log(self.name, "get_kline", "error", 0, [code], str(e))
            return []


# CLI 测试
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python eastmoney_direct.py quotes <code> [code...]")
        print("       python eastmoney_direct.py kline <code>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "quotes":
        codes = sys.argv[2:] or ["688012", "002371"]
        em = EastmoneyProvider()
        q = em.get_quotes(codes)
        for c, d in q.items():
            print(f'{d.get("name",c)} ({c}): {d.get("price")} ({d.get("change_pct",0)}%)')

    elif cmd == "kline":
        code = sys.argv[2] if len(sys.argv) > 2 else "688012"
        tc = TencentProvider()
        k = tc.get_kline(code, "2026-06-01")
        print(f'{code} K线: {len(k)} 条')
        for day in k[-5:]:
            print(f'  {day["date"]} 收:{day["close"]}')
