"""Quote — 标准化实时行情数据模型

Defines the unified Quote data model used throughout the V5.2
Realtime Quote Ingest pipeline. All provider adapters normalize
their output to this format.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional


CST = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(CST).isoformat()


@dataclass
class Quote:
    """标准化实时行情数据单元

    Attributes:
        symbol:      6位股票代码 (e.g. "688012")
        price:      最新价
        open:       开盘价
        high:       最高价
        low:        最低价
        volume:     成交量 (股)
        amount:     成交额 (元)
        change_pct: 涨跌幅 (%)
        change_amount: 涨跌额
        source_id:  数据源ID (e.g. "eastmoney_direct")
        timestamp:  获取时间 (ISO格式)
        name:       股票名称
        prev_close: 昨收价
        amplitude:  振幅 (%)
        turnover_rate: 换手率 (%)
        bid:        买一价
        ask:        卖一价
        bid_vol:    买一量
        ask_vol:    卖一量
        pe:         市盈率
        market_cap: 总市值
    """
    symbol: str
    price: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    change_pct: Optional[float] = None
    change_amount: Optional[float] = None
    source_id: str = ""
    timestamp: str = ""
    name: str = ""
    prev_close: Optional[float] = None
    amplitude: Optional[float] = None
    turnover_rate: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_vol: Optional[int] = None
    ask_vol: Optional[int] = None
    pe: Optional[float] = None
    market_cap: Optional[float] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = _now_iso()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Quote:
        return cls(**data)

    def is_complete(self) -> bool:
        """检查是否包含核心行情数据（price 非空）"""
        return self.price is not None


@dataclass
class QuoteResult:
    """单次行情获取结果

    Tracks the outcome of fetching a quote for one symbol,
    including fallback chain information.
    """
    symbol: str
    success: bool
    quote: Optional[Quote] = None
    source_id: str = ""
    error: Optional[str] = None
    latency_ms: float = 0.0
    fallback_used: bool = False
    fallback_chain: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.quote:
            d["quote"] = self.quote.to_dict()
        return d


@dataclass
class BatchQuoteResult:
    """批量行情获取结果"""
    symbols: list[str]
    results: dict[str, QuoteResult] = field(default_factory=dict)
    timestamp: str = ""
    total_latency_ms: float = 0.0
    total_symbols: int = 0
    success_count: int = 0
    fail_count: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = _now_iso()
        if self.results:
            self.total_symbols = len(self.results)
            self.success_count = sum(1 for r in self.results.values() if r.success)
            self.fail_count = self.total_symbols - self.success_count

    def summary(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_symbols": self.total_symbols,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "success_rate": round((self.success_count / max(self.total_symbols, 1)) * 100, 1),
        }
