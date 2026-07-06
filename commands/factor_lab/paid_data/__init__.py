"""Paid Data Source Interface V5.9 — 付费数据源接口预留"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional


@dataclass
class DataQuery:
    symbol: str
    start_date: date
    end_date: date
    fields: list[str] = None
    frequency: str = "1d"  # 1d, 1m, 5m, tick


@dataclass
class DataResponse:
    symbol: str
    data: list[dict]
    total: int
    source: str
    latency_ms: float
    error: Optional[str] = None


class PaidDataSource(ABC):
    """付费数据源接口: Wind / Choice / iFinD 等需要实现此接口"""

    @abstractmethod
    def connect(self) -> bool:
        """连接到数据源"""
        ...

    @abstractmethod
    def query(self, q: DataQuery) -> DataResponse:
        """执行数据查询"""
        ...

    @abstractmethod
    def available_fields(self) -> list[str]:
        """返回可查询的字段列表"""
        ...

    @abstractmethod
    def status(self) -> dict:
        """返回连接状态 / 剩余查询次数 / 过期时间"""
        ...


class WindAdapter(PaidDataSource):
    """Wind 金融终端适配器 (预留)"""
    def connect(self) -> bool:
        return False  # 未安装 Wind Python 接口

    def query(self, q: DataQuery) -> DataResponse:
        return DataResponse(symbol=q.symbol, data=[], total=0, source="wind", latency_ms=0,
                            error="Wind 接口未安装")

    def available_fields(self) -> list[str]:
        return []

    def status(self) -> dict:
        return {"connected": False, "source": "wind", "note": "预留接口, 需安装 WindPy"}


class ChoiceAdapter(PaidDataSource):
    """东方财富 Choice 适配器 (预留)"""
    def connect(self) -> bool:
        return False

    def query(self, q: DataQuery) -> DataResponse:
        return DataResponse(symbol=q.symbol, data=[], total=0, source="choice", latency_ms=0,
                            error="Choice 接口未安装")

    def available_fields(self) -> list[str]:
        return []

    def status(self) -> dict:
        return {"connected": False, "source": "choice", "note": "预留接口"}
