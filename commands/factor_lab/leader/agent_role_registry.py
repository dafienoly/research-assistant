"""Agent Role Registry V8.0 — 多 Agent 角色注册表

定义 Agent 角色 Schema、注册/发现 API、角色分配策略。
支持五种标准角色: PM, Architect, Developer, Tester, Auditor。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


CST = timezone(timedelta(hours=8))
REGISTRY_ROOT = Path("/home/ly/.hermes/research-assistant/agent_tasks/agent_role_registry")


# ─── Role Capability Constants ─────────────────────────────────────

class Capability:
    """Agent 能力常量定义"""
    # PM 能力
    PLAN_TASK = "plan:task"                     # 任务规划
    PLAN_ROADMAP = "plan:roadmap"                # 路线图规划
    PLAN_SPRINT = "plan:sprint"                  # Sprint 规划
    PRIORITIZE = "plan:prioritize"               # 优先级排序
    REVIEW_PROGRESS = "review:progress"          # 进度评审
    ASSIGN_ROLE = "assign:role"                  # 角色分配

    # 架构能力
    DESIGN_ARCH = "design:architecture"          # 架构设计
    DESIGN_INTERFACE = "design:interface"        # 接口设计
    DESIGN_SCHEMA = "design:schema"              # Schema 设计
    REVIEW_DESIGN = "review:design"              # 设计评审
    EVAL_TECH = "eval:technology"                # 技术评估

    # 开发能力
    IMPLEMENT_CODE = "implement:code"            # 编码实现
    IMPLEMENT_FEATURE = "implement:feature"      # 功能实现
    IMPLEMENT_REFACTOR = "implement:refactor"     # 重构
    FIX_BUG = "fix:bug"                          # Bug 修复
    WRITE_TEST = "write:test"                    # 编写测试

    # 测试能力
    TEST_UNIT = "test:unit"                      # 单元测试
    TEST_INTEGRATION = "test:integration"         # 集成测试
    TEST_REGRESSION = "test:regression"           # 回归测试
    TEST_PERFORMANCE = "test:performance"         # 性能测试
    REVIEW_CODE = "review:code"                  # 代码审查
    ANALYZE_COVERAGE = "analyze:coverage"         # 覆盖率分析

    # 审计能力
    AUDIT_COMPLIANCE = "audit:compliance"         # 合规审计
    AUDIT_SECURITY = "audit:security"             # 安全审计
    AUDIT_QUALITY = "audit:quality"               # 质量审计
    AUDIT_PERFORMANCE = "audit:performance"       # 性能审计
    AUDIT_CONTRACT = "audit:contract"             # 合约审计
    VERIFY_ACCEPTANCE = "verify:acceptance"       # 验收验证


VALID_CAPABILITIES = {
    getattr(Capability, attr) for attr in dir(Capability)
    if not attr.startswith("_") and isinstance(getattr(Capability, attr), str)
}


# ─── Pre-defined role groups ───────────────────────────────────────

STANDARD_ROLES = {
    "pm": {
        "role_id": "pm",
        "name": "Project Manager",
        "description": "项目经理 — 负责任务规划、优先级排序、进度跟踪和资源协调",
        "capabilities": [
            Capability.PLAN_TASK, Capability.PLAN_ROADMAP, Capability.PLAN_SPRINT,
            Capability.PRIORITIZE, Capability.REVIEW_PROGRESS, Capability.ASSIGN_ROLE,
            Capability.REVIEW_CODE,
        ],
        "responsibilities": [
            "生成任务计划和 Sprint 规划",
            "评估任务优先级和依赖关系",
            "分配资源和角色",
            "跟踪版本进度和完成状态",
            "审批关键里程碑交付",
        ],
        "constraints": [
            "不直接修改代码",
            "不执行测试",
            "不访问交易系统",
        ],
        "allowed_backends": ["dry-run", "claude"],
        "max_concurrent_tasks": 3,
        "requires_approval": False,
        "auto_assignable": True,
    },
    "architect": {
        "role_id": "architect",
        "name": "Architect",
        "description": "架构师 — 负责系统架构设计、接口定义、技术选型和设计评审",
        "capabilities": [
            Capability.DESIGN_ARCH, Capability.DESIGN_INTERFACE, Capability.DESIGN_SCHEMA,
            Capability.REVIEW_DESIGN, Capability.EVAL_TECH,
            Capability.REVIEW_CODE, Capability.AUDIT_QUALITY,
        ],
        "responsibilities": [
            "设计和评审系统架构",
            "定义模块接口和数据 Schema",
            "进行技术选型和评估",
            "审查代码架构一致性",
            "确保设计文档完整",
        ],
        "constraints": [
            "不直接实现业务功能",
            "不修改数据层代码",
        ],
        "allowed_backends": ["dry-run", "claude"],
        "max_concurrent_tasks": 2,
        "requires_approval": False,
        "auto_assignable": True,
    },
    "developer": {
        "role_id": "developer",
        "name": "Developer",
        "description": "开发工程师 — 负责编码实现、功能开发、Bug 修复和单元测试编写",
        "capabilities": [
            Capability.IMPLEMENT_CODE, Capability.IMPLEMENT_FEATURE, Capability.IMPLEMENT_REFACTOR,
            Capability.FIX_BUG, Capability.WRITE_TEST,
        ],
        "responsibilities": [
            "根据设计文档实现功能",
            "修复已确认的 Bug",
            "编写单元测试和集成测试",
            "保持代码质量和风格一致",
            "提交代码前的自查",
        ],
        "constraints": [
            "不修改架构设计文档",
            "不执行审批操作",
            "不直接操作生产环境",
        ],
        "allowed_backends": ["claude", "codex", "dry-run"],
        "max_concurrent_tasks": 1,
        "requires_approval": True,
        "auto_assignable": True,
    },
    "tester": {
        "role_id": "tester",
        "name": "Tester",
        "description": "测试工程师 — 负责测试编写、代码审查、回归测试和质量保证",
        "capabilities": [
            Capability.TEST_UNIT, Capability.TEST_INTEGRATION, Capability.TEST_REGRESSION,
            Capability.TEST_PERFORMANCE, Capability.REVIEW_CODE, Capability.ANALYZE_COVERAGE,
        ],
        "responsibilities": [
            "编写和维护测试用例",
            "执行回归测试和集成测试",
            "审查代码质量和测试覆盖率",
            "报告和追踪缺陷",
            "验证 Bug 修复",
        ],
        "constraints": [
            "不修改生产代码（测试代码除外）",
            "不架构设计",
            "不部署代码",
        ],
        "allowed_backends": ["dry-run", "claude"],
        "max_concurrent_tasks": 2,
        "requires_approval": False,
        "auto_assignable": True,
    },
    "auditor": {
        "role_id": "auditor",
        "name": "Auditor",
        "description": "审计员 — 负责合规审计、安全审计、质量检查和验收验证",
        "capabilities": [
            Capability.AUDIT_COMPLIANCE, Capability.AUDIT_SECURITY, Capability.AUDIT_QUALITY,
            Capability.AUDIT_PERFORMANCE, Capability.AUDIT_CONTRACT, Capability.VERIFY_ACCEPTANCE,
            Capability.REVIEW_CODE,
        ],
        "responsibilities": [
            "审计代码合规性和安全性",
            "验证验收标准和完成条件",
            "检查版本交付质量",
            "审查数据完整性和合约一致性",
            "生成审计报告",
        ],
        "constraints": [
            "不修改代码",
            "不执行业务操作",
            "不参与开发决策",
        ],
        "allowed_backends": ["dry-run", "claude"],
        "max_concurrent_tasks": 2,
        "requires_approval": False,
        "auto_assignable": True,
    },
}


# ─── Data Classes ──────────────────────────────────────────────────

@dataclass
class AgentRoleSpec:
    """Agent 角色规范定义

    Attributes:
        role_id: 唯一标识 (e.g. 'pm', 'developer')
        name: 可读名称
        description: 角色描述
        capabilities: 能力列表
        responsibilities: 职责列表
        constraints: 约束/边界列表
        allowed_backends: 允许使用的后端列表
        max_concurrent_tasks: 最大并发任务数
        requires_approval: 是否需要审批
        auto_assignable: 是否可自动分配
        version: 版本号
        created_at: 创建时间
        updated_at: 更新时间
    """
    role_id: str
    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    allowed_backends: list[str] = field(default_factory=list)
    max_concurrent_tasks: int = 1
    requires_approval: bool = False
    auto_assignable: bool = True
    version: str = "1.0.0"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(CST).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AgentRoleSpec:
        return cls(**data)


@dataclass
class RoleAssignment:
    """角色分配记录"""
    assignment_id: str
    role_id: str
    task_id: str
    task_desc: str
    backend: str = ""
    status: str = "assigned"       # assigned / running / completed / failed
    assigned_at: str = ""
    completed_at: str = ""

    def __post_init__(self):
        if not self.assigned_at:
            self.assigned_at = datetime.now(CST).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RoleAssignment:
        return cls(**data)


# ─── Validation ────────────────────────────────────────────────────

def validate_role_spec(spec: AgentRoleSpec) -> list[str]:
    """验证 AgentRoleSpec 合法性，返回错误列表（空 = 合法）"""
    errors = []
    if not spec.role_id or not spec.role_id.strip():
        errors.append("role_id is required")
    if not spec.name or not spec.name.strip():
        errors.append("name is required")
    if not spec.description or not spec.description.strip():
        errors.append("description is required")
    for c in spec.capabilities:
        if c not in VALID_CAPABILITIES:
            errors.append(f"unknown capability '{c}'")
    return errors


# ─── Registry ──────────────────────────────────────────────────────

class AgentRoleRegistry:
    """Agent 角色注册表

    集中管理所有 Agent 角色的定义、发现和分配策略。
    支持:
      - 角色 CRUD (注册/列表/查看/删除)
      - 预定义标准角色
      - 按能力发现角色
      - 角色/后端匹配
      - 分配策略
    """

    def __init__(self, root: Path | None = None):
        self.root = root or REGISTRY_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self._roles: dict[str, AgentRoleSpec] = {}
        self._assignments: dict[str, RoleAssignment] = {}
        self._load()

    # ─── Core CRUD ─────────────────────────────────────────────────

    def register(self, spec: AgentRoleSpec) -> dict:
        """注册一个 AgentRoleSpec

        Returns:
            {"status": "ok", "role_id": spec.role_id}
            或 {"status": "error", "errors": [...]}
        """
        errors = validate_role_spec(spec)
        if errors:
            return {"status": "error", "errors": errors}
        spec.updated_at = datetime.now(CST).isoformat()
        self._roles[spec.role_id] = spec
        self._save(spec)
        return {"status": "ok", "role_id": spec.role_id}

    def list(self, capability: str | None = None) -> list[dict]:
        """列出所有注册的角色

        Args:
            capability: 按能力筛选 (可选)

        Returns:
            角色 dict 列表
        """
        results = []
        for spec in self._roles.values():
            if capability and capability not in spec.capabilities:
                continue
            results.append(spec.to_dict())
        results.sort(key=lambda x: x["role_id"])
        return results

    def get(self, role_id: str) -> Optional[AgentRoleSpec]:
        """按 role_id 获取 AgentRoleSpec"""
        return self._roles.get(role_id)

    def delete(self, role_id: str) -> dict:
        """删除一个角色"""
        if role_id in self._roles:
            del self._roles[role_id]
            path = self.root / f"{role_id}.json"
            if path.exists():
                path.unlink()
            return {"status": "ok", "role_id": role_id}
        return {"status": "error", "error": f"role '{role_id}' not found"}

    # ─── Discovery ─────────────────────────────────────────────────

    def find_by_capability(self, capability: str) -> list[dict]:
        """按能力查找角色"""
        return self.list(capability=capability)

    def find_by_backend(self, backend: str) -> list[dict]:
        """按允许的后端查找角色"""
        results = []
        for spec in self._roles.values():
            if backend in spec.allowed_backends:
                results.append(spec.to_dict())
        results.sort(key=lambda x: x["role_id"])
        return results

    def has_capability(self, role_id: str, capability: str) -> bool:
        """检查角色是否具有某能力"""
        spec = self._roles.get(role_id)
        if not spec:
            return False
        return capability in spec.capabilities

    # ─── Role Assignment ───────────────────────────────────────────

    def assign_role(self, role_id: str, task_id: str, task_desc: str = "") -> dict:
        """分配角色到任务

        Returns:
            {"status": "ok", "assignment": RoleAssignment dict}
            或 {"status": "error", "error": reason}
        """
        spec = self._roles.get(role_id)
        if not spec:
            return {"status": "error", "error": f"role '{role_id}' not found"}

        if not spec.auto_assignable:
            return {"status": "error", "error": f"role '{role_id}' is not auto-assignable"}

        # 检查并发限制
        active_count = sum(
            1 for a in self._assignments.values()
            if a.role_id == role_id and a.status == "running"
        )
        if active_count >= spec.max_concurrent_tasks:
            return {
                "status": "error",
                "error": f"role '{role_id}' has reached max concurrent tasks ({spec.max_concurrent_tasks})",
            }

        now = datetime.now(CST).isoformat()
        ts_part = now[:19].replace(':', '').replace('T', '_')
        unique_suffix = f"{task_id}_{len(self._assignments) + 1}"
        assignment_id = f"assign_{ts_part}_{role_id}_{unique_suffix}"
        assignment = RoleAssignment(
            assignment_id=assignment_id,
            role_id=role_id,
            task_id=task_id,
            task_desc=task_desc,
            status="assigned",
            assigned_at=now,
        )
        self._assignments[assignment_id] = assignment
        self._save_assignment(assignment)
        return {"status": "ok", "assignment": assignment.to_dict()}

    def complete_assignment(self, assignment_id: str, status: str = "completed") -> dict:
        """完成任务分配

        Args:
            assignment_id: 分配记录 ID
            status: completed 或 failed
        """
        assignment = self._assignments.get(assignment_id)
        if not assignment:
            return {"status": "error", "error": f"assignment '{assignment_id}' not found"}
        assignment.status = status
        assignment.completed_at = datetime.now(CST).isoformat()
        self._save_assignment(assignment)
        return {"status": "ok", "assignment": assignment.to_dict()}

    def list_assignments(self, role_id: str | None = None,
                         status: str | None = None) -> list[dict]:
        """列出分配记录"""
        results = []
        for a in self._assignments.values():
            if role_id and a.role_id != role_id:
                continue
            if status and a.status != status:
                continue
            results.append(a.to_dict())
        results.sort(key=lambda x: x.get("assigned_at", ""), reverse=True)
        return results

    # ─── Backend Matching ──────────────────────────────────────────

    def match_backend(self, role_id: str, preferred: str | None = None) -> dict:
        """为角色匹配最佳后端

        Args:
            role_id: 角色 ID
            preferred: 首选后端 (可选)

        Returns:
            {"role_id": ..., "selected_backend": ..., "available_backends": [...]}
        """
        spec = self._roles.get(role_id)
        if not spec:
            return {"role_id": role_id, "error": "role not found"}
        available = list(spec.allowed_backends)
        if preferred and preferred in available:
            return {
                "role_id": role_id,
                "selected_backend": preferred,
                "available_backends": available,
            }
        # 优先级: 首选 > claude > dry-run > 其他
        priority = ["claude", "dry-run"]
        for p in priority:
            if p in available:
                return {
                    "role_id": role_id,
                    "selected_backend": p,
                    "available_backends": available,
                }
        return {
            "role_id": role_id,
            "selected_backend": available[0] if available else "dry-run",
            "available_backends": available,
        }

    # ─── Statistics ────────────────────────────────────────────────

    def stats(self) -> dict:
        """注册表统计信息"""
        active = sum(1 for a in self._assignments.values() if a.status == "running")
        completed = sum(1 for a in self._assignments.values() if a.status == "completed")
        failed = sum(1 for a in self._assignments.values() if a.status == "failed")
        return {
            "total_roles": len(self._roles),
            "total_assignments": len(self._assignments),
            "active_assignments": active,
            "completed_assignments": completed,
            "failed_assignments": failed,
            "roles_by_backend": self._count_by_backend(),
        }

    def _count_by_backend(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for spec in self._roles.values():
            for b in spec.allowed_backends:
                counts[b] = counts.get(b, 0) + 1
        return dict(sorted(counts.items()))

    # ─── Persistence ───────────────────────────────────────────────

    def _save(self, spec: AgentRoleSpec):
        path = self.root / f"{spec.role_id}.json"
        path.write_text(json.dumps(spec.to_dict(), indent=2, ensure_ascii=False))

    def _save_assignment(self, assignment: RoleAssignment):
        assigns_dir = self.root / "assignments"
        assigns_dir.mkdir(parents=True, exist_ok=True)
        path = assigns_dir / f"{assignment.assignment_id}.json"
        path.write_text(json.dumps(assignment.to_dict(), indent=2, ensure_ascii=False))

    def _load(self):
        """从磁盘加载所有注册的角色和分配记录"""
        self._roles = {}
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.json")):
            if not path.is_file() or path.name == "index.json":
                continue
            try:
                data = json.loads(path.read_text())
                spec = AgentRoleSpec.from_dict(data)
                self._roles[spec.role_id] = spec
            except Exception:
                continue
        # Load assignments
        self._assignments = {}
        assigns_dir = self.root / "assignments"
        if assigns_dir.exists():
            for path in sorted(assigns_dir.glob("*.json")):
                if not path.is_file():
                    continue
                try:
                    data = json.loads(path.read_text())
                    assignment = RoleAssignment.from_dict(data)
                    self._assignments[assignment.assignment_id] = assignment
                except Exception:
                    continue

    # ─── Built-in Roles ────────────────────────────────────────────

    def seed_defaults(self) -> int:
        """注册预定义标准角色 (跳过已存在的)

        Returns:
            新注册的角色数量
        """
        count = 0
        for role_id, data in STANDARD_ROLES.items():
            if role_id not in self._roles:
                spec = AgentRoleSpec(**data)
                self.register(spec)
                count += 1
        return count


def init_registry() -> AgentRoleRegistry:
    """初始化注册表并填充标准角色，返回 AgentRoleRegistry 实例"""
    registry = AgentRoleRegistry()
    registry.seed_defaults()
    return registry
