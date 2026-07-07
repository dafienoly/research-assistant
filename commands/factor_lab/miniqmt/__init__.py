"""QMT Broker Adapter — 只读模式
   使用 xtquant 连接本地 QMT 客户端
   仅支持: 行情查询、持仓查询、账户查询
   不支持: 自动下单（严格遵守系统安全边界）"""
import sys, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))
DATA_DIR = Path("/home/ly/.hermes/research-assistant/data/qmt")

# ─── 连接管理 ─────────────────────────────────────

_connected = False
_ds = None  # xtdata 数据接口


def connect(account_id: str = "", password: str = "") -> bool:
    """连接本地 QMT 客户端（只读模式）
    
    依赖:
        pip install xtquant -i https://pypi.org/simple
    
    QMT 客户端需在本地运行，xtquant 通过本地端口通信。
    不需要 miniQMT 权限 — 只读操作使用 xtdata 接口。
    """
    global _connected, _ds
    try:
        from xtquant import xtdata
        # xtdata.connect() 连接本地 QMT 客户端
        # 不需要账号密码，只要本地 QMT 在运行
        xtdata.run()
        _ds = xtdata
        _connected = True
        print(f"  ✅ QMT 已连接 (只读模式)")
        return True
    except ImportError:
        print("  ⚠️ xtquant 未安装。运行: pip install xtquant -i https://pypi.org/simple")
        return False
    except Exception as e:
        print(f"  ⚠️ QMT 连接失败: {e}")
        return False


def disconnect():
    global _connected
    _connected = False
    print("  QMT 已断开")


def is_connected() -> bool:
    return _connected


# ─── 只读接口 ─────────────────────────────────────

def query_positions() -> list:
    """查询当前持仓（只读）
    
    返回:
        [{"symbol": "000001", "name": "平安银行", "shares": 1000, 
          "avg_price": 12.34, "market_value": 12340, "profit_pct": 5.2}, ...]
    """
    if not _connected:
        return _load_cached("positions") or []
    try:
        # xtdata 不直接支持持仓查询，需要 xttrading 模块
        # 标准 QMT 下使用 xtdata.get_institution_positions()
        positions = []
        try:
            raw = _ds.get_institution_positions()
            for p in raw or []:
                positions.append({
                    "symbol": p.get("stock_code", ""),
                    "name": p.get("stock_name", ""),
                    "shares": int(p.get("current_shares", 0)),
                    "avg_price": float(p.get("avg_price", 0)),
                    "market_value": float(p.get("market_value", 0)),
                    "profit_pct": float(p.get("profit_ratio", 0)),
                })
        except:
            pass
        _cache("positions", positions)
        return positions
    except:
        return _load_cached("positions") or []


def query_account() -> dict:
    """查询账户资产（只读）
    
    返回:
        {"total_asset": 1000000, "cash": 500000, "market_value": 500000,
         "frozen_cash": 0, "profit_loss": 5000}
    """
    if not _connected:
        return _load_cached("account") or {"total_asset": 0, "cash": 0}
    try:
        account = {}
        try:
            raw = _ds.get_account_info()
            if raw:
                account = {
                    "total_asset": float(raw.get("total_asset", 0)),
                    "cash": float(raw.get("cash", 0)),
                    "market_value": float(raw.get("market_value", 0)),
                    "frozen_cash": float(raw.get("frozen_cash", 0)),
                    "profit_loss": float(raw.get("profit_loss", 0)),
                }
        except:
            pass
        _cache("account", account)
        return account
    except:
        return _load_cached("account") or {"total_asset": 0, "cash": 0}


def get_market_quote(symbols: list[str]) -> dict:
    """获取实时行情快照（只读）
    
    Args:
        symbols: ["000001", "000333", ...]
    
    返回:
        {"000001": {"price": 12.34, "volume": 5000000, "amount": 6.17e7, 
                     "high": 12.50, "low": 12.20, "open": 12.30}, ...}
    """
    if not _connected or not _ds:
        return {}
    try:
        full_codes = []
        for s in symbols:
            prefix = "SH" if s.startswith(("6", "9")) else "SZ"
            full_codes.append(f"{prefix}.{s}")
        
        quotes = _ds.get_full_tick(full_codes)
        result = {}
        for code, tick in (quotes or {}).items():
            sym = code.split(".")[-1]
            result[sym] = {
                "price": tick.get("lastPrice", 0),
                "volume": tick.get("volume", 0),
                "amount": tick.get("amount", 0),
                "high": tick.get("high", 0),
                "low": tick.get("low", 0),
                "open": tick.get("open", 0),
                "pre_close": tick.get("preClose", 0),
            }
        return result
    except:
        return {}


def get_kline(symbol: str, period: str = "1d", count: int = 120) -> list[dict]:
    """获取历史 K 线（只读）
    
    Args:
        symbol: "000001"
        period: "1d" 日线, "5m" 5分钟
        count: 条数
    """
    if not _connected or not _ds:
        return []
    try:
        prefix = "SH" if symbol.startswith(("6", "9")) else "SZ"
        full = f"{prefix}.{symbol}"
        data = _ds.get_local_data(
            field_list=["time", "open", "high", "low", "close", "volume", "amount"],
            stock_code=[full],
            period=period,
            start_time="",
            end_time="",
            count=count,
        )
        if data is not None and not data.empty:
            rows = []
            data = data.reset_index()
            for _, row in data.iterrows():
                rows.append({
                    "date": str(row.get("time", "")),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", 0)),
                    "amount": float(row.get("amount", 0)),
                })
            return rows
        return []
    except:
        return []


# ─── 安全边界 ─────────────────────────────────────

def place_order(symbol: str, amount: int, price: float = 0) -> dict:
    """❌ 下单功能被禁用 — 当前运行在只读模式"""
    return {
        "status": "blocked",
        "reason": "QMT 适配器当前为只读模式，下单功能已禁用。如需交易请使用人工确认流程。",
        "symbol": symbol,
        "amount": amount,
        "price": price,
    }


# ─── 缓存辅助 ─────────────────────────────────────

def _cache(name: str, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        (DATA_DIR / f"{name}.json").write_text(
            json.dumps({"data": data, "cached_at": str(datetime.now(CST))}, ensure_ascii=False))
    except:
        pass


def _load_cached(name: str) -> Optional[list]:
    p = DATA_DIR / f"{name}.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("data")
        except:
            pass
    return None
