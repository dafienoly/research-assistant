"""Real-time Market Data V5.2 — 实时行情接入 (WebSocket 框架)"""
import json, threading, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from factor_lab.minute_storage import store_minute_bars

CST = timezone(timedelta(hours=8))

# 行情回调: 当 WebSocket 收到 tick 时调用
_tick_handlers = []


def register_tick_handler(fn):
    _tick_handlers.append(fn)


def on_tick(symbol: str, price: float, volume: int, timestamp: str):
    """处理 tick 数据"""
    for handler in _tick_handlers:
        try:
            handler(symbol, price, volume, timestamp)
        except Exception:
            pass


# 模拟行情源 (用于开发测试)
class MockMarketFeed:
    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.running = False

    def start(self):
        self.running = True
        t = threading.Thread(target=self._feed, daemon=True)
        t.start()

    def stop(self):
        self.running = False

    def _feed(self):
        import random
        while self.running:
            for sym in self.symbols:
                price = round(random.uniform(10, 100), 2)
                volume = random.randint(1000, 100000)
                ts = datetime.now(CST).isoformat()
                on_tick(sym, price, volume, ts)
            time.sleep(1)


# WebSocket 客户端框架 (连接实盘行情用)
class MarketWebSocket:
    """实盘 WebSocket 行情客户端 (stub)"""

    def __init__(self, url: str, symbols: list[str]):
        self.url = url
        self.symbols = symbols
        self.running = False

    def connect(self):
        # 实际接入时需要:
        # 1. websocket.connect(self.url)
        # 2. 发送订阅消息 {"op": "subscribe", "symbols": self.symbols}
        # 3. 在回调中解析 tick 并调用 on_tick()
        raise NotImplementedError("实盘 WebSocket 连接需配置行情源 URL")

    def disconnect(self):
        self.running = False
