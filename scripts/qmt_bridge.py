#!/usr/bin/env python3
"""QMT Bridge — xtdata only.

Supports both old xtquant (built-in, auto-connect) and
new xtquant (needs explicit connect).
"""

import argparse, json, os, sys, uuid
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

if sys.version_info >= (3, 7):
    from http.server import ThreadingHTTPServer as _ThreadingHTTPServer
    ThreadingHTTPServer = _ThreadingHTTPServer
else:
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        allow_reuse_address = True; daemon_threads = True

CST = timezone(timedelta(hours=8))

def now_iso():
    return datetime.now(CST).isoformat()


class QMTDataBackend:
    def __init__(self):
        self.xtdata = None; self.connected = False; self.error = ""
        self._connect()

    def _connect(self):
        try:
            from xtquant import xtdata
            # Try explicit connect (new xtquant version)
            port_text = os.environ.get("QMT_XTDATA_PORT", "").strip()
            port = int(port_text) if port_text else None
            if hasattr(xtdata, "connect"):
                try:
                    xtdata.connect(port=port)
                except Exception:
                    pass  # old version connects automatically
            self.xtdata = xtdata
            self.connected = True
        except Exception as exc:
            self.connected = False
            self.error = str(exc)

    def health(self):
        return {"connected": self.connected, "xtdata_available": self.xtdata is not None, "error": self.error}

    @staticmethod
    def _to_qmt_symbol(symbol):
        symbol = symbol.strip().upper()
        if "." in symbol: return symbol
        return f"{symbol}.{'SH' if symbol.startswith(('6','9')) else 'SZ'}"

    def quotes(self, symbols):
        if not self.xtdata: raise RuntimeError("xtdata unavailable")
        qmt_symbols = [self._to_qmt_symbol(s) for s in symbols if s]
        if not qmt_symbols: return {}
        raw = None
        # get_full_tick: returns {symbol: {field: value}, ...} (real-time)
        # get_market_data: returns {field: {symbol: [value]}, ...} (k-line)
        for method in ["get_full_tick", "get_market_data"]:
            fn = getattr(self.xtdata, method, None)
            if not fn: continue
            try:
                if method == "get_market_data":
                    r = fn(["time","open","high","low","close","volume","amount"],
                           qmt_symbols, period="1d", start_time="", end_time="", count=1)
                    if r:
                        # Transpose {field: {symbol: [val]}} -> {symbol: {field: val}}
                        transposed = {}
                        for field, sym_data in r.items():
                            if not isinstance(sym_data, dict): continue
                            for sym, vals in sym_data.items():
                                if isinstance(vals, (list, tuple)) and len(vals) > 0:
                                    v = vals[-1]
                                else:
                                    v = vals
                                transposed.setdefault(sym.split(".")[0], {})[field] = v
                        raw = transposed
                    break
                else:
                    r = fn(qmt_symbols)
                    if r: raw = r; break
            except Exception:
                continue
        if not raw:
            return {}
        out = {}
        for sym, tick in raw.items():
            s = sym.split(".")[0] if "." in str(sym) else str(sym)
            out[s] = {
                "symbol": s,
                "price": tick.get("lastPrice", tick.get("close", 0)),
                "open": tick.get("open", 0),
                "high": tick.get("high", 0),
                "low": tick.get("low", 0),
                "pre_close": tick.get("preClose", 0),
                "volume": tick.get("volume", 0),
                "amount": tick.get("amount", 0),
                "bid_price": tick.get("bidPrice", []),
                "ask_price": tick.get("askPrice", []),
                "bid_volume": tick.get("bidVol", []),
                "ask_volume": tick.get("askVol", []),
            }
        return out

    def bars(self, symbol, period="1d", count=120):
        if not self.xtdata: raise RuntimeError("xtdata unavailable")
        qmt_symbol = self._to_qmt_symbol(symbol)
        # Try newer API first (stock_list), fall back to older (stock_code)
        for kw in ["stock_list", "stock_code"]:
            try:
                data = self.xtdata.get_local_data(
                    field_list=["time","open","high","low","close","volume","amount"],
                    **{kw: [qmt_symbol]}, period=period,
                    start_time="", end_time="", count=int(count))
                if data is None: return []
                frame = data[qmt_symbol] if isinstance(data,dict) and qmt_symbol in data else data
                return frame.reset_index().to_dict("records")
            except (TypeError, ValueError):
                continue  # wrong kw name, try next
            except Exception as e:
                if "unexpected keyword" in str(e):
                    continue
                raise
        return []


class BridgeHandler(BaseHTTPRequestHandler):
    backend = QMTDataBackend()
    def log_message(self, fmt, *a): return
    def _send(self, status, data=None, error=""):
        body = {"status":status,"request_id":str(uuid.uuid4()),
                "timestamp":now_iso(),"data":data,"error":error}
        raw = json.dumps(body,ensure_ascii=False,default=str).encode()
        self.send_response(200 if status=="ok" else 500)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        p = urlparse(self.path); q = parse_qs(p.query)
        try:
            if p.path == "/health": self._send("ok", self.backend.health())
            elif p.path == "/quotes":
                syms = ",".join(q.get("symbols",[""])).split(",")
                self._send("ok", self.backend.quotes(syms))
            elif p.path == "/bars":
                self._send("ok", self.backend.bars(
                    q.get("symbol",[""])[0], q.get("period",["1d"])[0],
                    int(q.get("count",["120"])[0])))
            else: self._send("error",error="unknown path")
        except Exception as e: self._send("error",error=str(e))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host",default=os.environ.get("QMT_BRIDGE_HOST","127.0.0.1"))
    p.add_argument("--port",type=int,default=int(os.environ.get("QMT_BRIDGE_PORT","8765")))
    a = p.parse_args()
    ThreadingHTTPServer((a.host,a.port),BridgeHandler).serve_forever()

if __name__ == "__main__":
    main()
