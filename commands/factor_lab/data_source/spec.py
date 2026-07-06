"""DataSourceSpec — 数据源规范定义

Defines the schema for data sources registered in the Data Source Registry.
Every data source (RSScast, AKShare, Tencent, Sina, Eastmoney, Baostock, etc.)
is represented by a DataSourceSpec.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional


CST = timezone(timedelta(hours=8))


class DataSourceCategory(str, Enum):
    """数据源分类"""
    MARKET = "market"              # 行情数据 (实时报价、K线)
    FUNDAMENTAL = "fundamental"    # 基本面数据
    EVENT = "event"                # 事件数据
    TAG = "tag"                    # 标签/概念数据
    MACRO = "macro"                # 宏观数据
    ANNOUNCEMENT = "announcement"  # 公告数据


class DataSourceCapability(str, Enum):
    """数据源能力"""
    REALTIME_QUOTE = "realtime_quote"    # 实时报价
    KLINE_DAILY = "kline_daily"          # 日K线
    KLINE_MINUTE = "kline_minute"        # 分钟K线
    SNAPSHOT = "snapshot"                # 全A快照
    OVERVIEW = "overview"                # 公司概览
    INDEX = "index"                      # 指数行情
    ANNOUNCEMENT = "announcement"        # 公告
    FUNDAMENTAL = "fundamental"          # 基本面


class DataSourceStatus(str, Enum):
    """数据源运行状态"""
    ACTIVE = "active"          # 正常运行 (>80% success)
    DEGRADED = "degraded"      # 降级运行 (50-80% success)
    INACTIVE = "inactive"      # 不可用 (<50% success)
    UNCHECKED = "unchecked"    # 尚未检测


VALID_CATEGORIES = {e.value for e in DataSourceCategory}
VALID_CAPABILITIES = {e.value for e in DataSourceCapability}
VALID_STATUSES = {e.value for e in DataSourceStatus}


@dataclass
class DataSourceSpec:
    """数据源规范

    Attributes:
        source_id: 唯一标识 (e.g. 'rsscast_mcp', 'akshare_spot')
        name: 可读名称
        category: 数据分类
        capabilities: 能力列表
        priority: 优先级 (数字越小越优先)
        status: 运行状态
        config: 提供者配置参数
        health: 健康摘要 (last_check, success_rate, total_calls, error_count)
        created_at: 注册时间
        updated_at: 最后更新时间
    """
    source_id: str
    name: str
    category: str = DataSourceCategory.MARKET.value
    capabilities: list = field(default_factory=lambda: [DataSourceCapability.REALTIME_QUOTE.value])
    priority: int = 10
    status: str = DataSourceStatus.UNCHECKED.value
    config: dict = field(default_factory=dict)
    health: dict = field(default_factory=lambda: {
        "last_check": "",
        "success_rate": 100,
        "total_calls": 0,
        "error_count": 0,
    })
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> DataSourceSpec:
        return cls(**data)


def validate_spec(spec: DataSourceSpec) -> list[str]:
    """验证 DataSourceSpec 合法性，返回错误列表（空 = 合法）"""
    errors = []
    if not spec.source_id or not spec.source_id.strip():
        errors.append("source_id is required")
    if not spec.name or not spec.name.strip():
        errors.append("name is required")
    if spec.category not in VALID_CATEGORIES:
        errors.append(f"invalid category '{spec.category}', must be one of {sorted(VALID_CATEGORIES)}")
    if spec.status not in VALID_STATUSES:
        errors.append(f"invalid status '{spec.status}', must be one of {sorted(VALID_STATUSES)}")
    for cap in spec.capabilities:
        if cap not in VALID_CAPABILITIES:
            errors.append(f"invalid capability '{cap}', must be one of {sorted(VALID_CAPABILITIES)}")
    if spec.priority < 0:
        errors.append("priority must be >= 0")
    return errors
