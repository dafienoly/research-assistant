"""Research Skill Spec — 投研 Skill 规范定义

Defines the schema for research skills registered in the Research Skill Runtime.
Every research analysis task (factor ranking, data quality check, universe
overview, market snapshot, etc.) is represented by a SkillSpec.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field


CST = timezone(timedelta(hours=8))


class SkillCategory(str, Enum):
    """投研 Skill 分类"""
    ANALYSIS = "analysis"         # 分析类 (因子分析、IC分析)
    DATA = "data"                 # 数据类 (数据质量、新鲜度)
    REPORT = "report"             # 报告类 (生成报告)
    MONITOR = "monitor"           # 监控类 (盘前、盘中)
    UNIVERSE = "universe"         # 股票池类
    BACKTEST = "backtest"         # 回测类


VALID_CATEGORIES = {e.value for e in SkillCategory}


@dataclass
class SkillParam:
    """Skill 参数定义"""
    name: str
    type: str                          # string / int / float / bool / date / list
    label: str                         # 可读名称
    default: Any = None
    required: bool = False
    description: str = ""
    choices: list[str] | None = None   # 枚举值 (可选)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label,
            "default": self.default,
            "required": self.required,
            "description": self.description,
            "choices": self.choices,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SkillParam:
        return cls(**data)


@dataclass
class SkillSpec:
    """投研 Skill 规范

    Attributes:
        skill_id: 唯一标识 (e.g. 'factor-ranking', 'data-quality')
        name: 可读名称
        description: 详细描述
        category: Skill 分类
        params: 参数列表
        tags: 标签列表
        execute: 执行函数 (接收 ResearchContext, params dict，返回 dict)
        handler: 模块路径引用 (如 'factor_lab.research_skill.builtins:_execute_market_snapshot')
                 用于从磁盘恢复 execute 函数
        version: 版本号
        created_at: 创建时间
        updated_at: 更新时间
    """
    skill_id: str
    name: str
    description: str
    category: str = SkillCategory.ANALYSIS.value
    params: list = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    execute: Optional[Callable] = None
    handler: str = ""
    version: str = "1.0.0"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(CST).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        d = asdict(self)
        d["execute"] = self.execute.__name__ if self.execute else ""
        d["params"] = [p.to_dict() if isinstance(p, SkillParam) else p for p in self.params]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> SkillSpec:
        params_data = data.pop("params", [])
        execute = data.pop("execute", None)
        spec = cls(**data)
        spec.params = [SkillParam.from_dict(p) if isinstance(p, dict) else p for p in params_data]
        return spec

    def load_execute(self) -> bool:
        """从 handler 路径加载 execute 函数

        handler 格式: 'module.path:function_name'
        例如: 'factor_lab.research_skill.builtins:_execute_market_snapshot'

        Returns:
            True if execute was loaded successfully
        """
        if self.execute is not None:
            return True
        if not self.handler:
            return False
        try:
            import importlib
            parts = self.handler.split(":")
            if len(parts) != 2:
                return False
            module_name, func_name = parts
            module = importlib.import_module(module_name)
            self.execute = getattr(module, func_name)
            return True
        except Exception:
            return False


class SkillStatus(str, Enum):
    """Skill 执行状态"""
    PENDING = "pending"           # 等待执行
    RUNNING = "running"           # 执行中
    COMPLETED = "completed"       # 执行成功
    FAILED = "failed"             # 执行失败
    CANCELLED = "cancelled"       # 已取消


@dataclass
class SkillResult:
    """Skill 执行结果"""
    skill_id: str
    status: str = SkillStatus.PENDING.value
    data: dict = field(default_factory=dict)
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_ms: float = 0.0
    run_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SkillResult:
        return cls(**data)


def validate_spec(spec: SkillSpec) -> list[str]:
    """验证 SkillSpec 合法性，返回错误列表（空 = 合法）"""
    errors = []
    if not spec.skill_id or not spec.skill_id.strip():
        errors.append("skill_id is required")
    if not spec.name or not spec.name.strip():
        errors.append("name is required")
    if not spec.description or not spec.description.strip():
        errors.append("description is required")
    if spec.category not in VALID_CATEGORIES:
        errors.append(f"invalid category '{spec.category}', must be one of {sorted(VALID_CATEGORIES)}")
    for p in spec.params:
        if isinstance(p, SkillParam):
            if not p.name or not p.name.strip():
                errors.append("param name is required")
            if p.type not in ("string", "int", "float", "bool", "date", "list"):
                errors.append(f"invalid param type '{p.type}', must be one of string/int/float/bool/date/list")
    return errors
