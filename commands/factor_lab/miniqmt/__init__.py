"""MiniQMT Broker Adapter Sandbox V4.2/V4.7"""
def connect(): return False  # 沙箱模式
def query_positions(): return []
def place_order(symbol, amount, price): return {"status": "sandbox", "note": "沙箱模式未连接实盘"}
