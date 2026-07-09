"""Agent Router V8.1 — 智能任务路由引擎

将任务根据类型、能力需求、优先级、版本安全等级路由到最合适的
Agent 角色和后端执行器。弥合 Task Planning → Agent Execution 之间的缺口。

路由策略:
  - DIRECT:        直接指定 role_id + backend（最高优先级）
  - CAPABILITY:    按能力需求匹配合适角色
  - PRIORITY:      P0/P1 高优任务使用最强后端，P2/P3 低优节约成本
  - VERSION_SAFE:  按版本安全等级限制后端（live/unsafe 阶段 blocked）
  - COMPOSITE:     综合上述维度加权评分

集成:
  - AgentRoleRegistry → 角色发现与能力匹配
  - AgentRunner → 路由结果驱动后端选择
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

from factor_lab.leader.agent_role_registry import AgentRoleRegistry, Capability


CST = timezone(timedelta(hours=8))
ROUTER_LOG_DIR = Path("/home/ly/.hermes/research-assistant/agent_tasks/router_logs")


# ─── Enums ────────────────────────────────────────────────────────────

class RouteStrategy(str, Enum):
    """路由策略枚举"""
    DIRECT = "direct"               # 直接指定 role_id + backend
    CAPABILITY = "capability"       # 按能力匹配合适角色
    PRIORITY = "priority"           # 按优先级选择后端
    VERSION_SAFE = "version_safe"   # 按版本安全等级限制
    COMPOSITE = "composite"         # 综合评分


class TaskType(str, Enum):
    """任务类型分类"""
    FEATURE = "feature"            # 新功能开发
    BUGFIX = "bugfix"              # Bug 修复
    RESEARCH = "research"          # 投研分析
    AUDIT = "audit"                # 审计/审查
    TEST = "test"                  # 测试
    DEPLOY = "deploy"              # 部署
    REFACTOR = "refactor"          # 重构
    DOCS = "docs"                  # 文档
    OPERATION = "operation"        # 运维操作
    UNKNOWN = "unknown"            # 未知


# ─── Data Classes ────────────────────────────────────────────────────

@dataclass
class TaskProfile:
    """任务画像：路由引擎的输入

    Attributes:
        task_id:       任务 ID (e.g. "T001")
        title:         任务标题
        version:       版本号 (e.g. "V8.1")
        priority:      优先级 ("P0" ~ "P3")
        task_type:     任务类型
        required_caps: 所需能力列表
        description:   任务描述
        owner:         指定负责人 (可选)
        backend:       指定后端 (可选, 仅在 DIRECT 策略使用)
        safety_tags:   安全标签 (e.g. ["no_live_trade", "auto_apply=False"])
    """
    task_id: str = ""
    title: str = ""
    version: str = ""
    priority: str = "P2"
    task_type: TaskType = TaskType.UNKNOWN
    required_caps: list[str] = field(default_factory=list)
    description: str = ""
    owner: str = ""
    backend: str = ""
    safety_tags: list[str] = field(default_factory=list)

    def infer_task_type(self) -> TaskType:
        """从 title / description 推断任务类型"""
        text = f"{self.title} {self.description}".lower()

        if any(k in text for k in ("bug", "fix", "修复", "错误")):
            return TaskType.BUGFIX
        if any(k in text for k in ("research", "研究", "分析", "investigate")):
            return TaskType.RESEARCH
        if any(k in text for k in ("audit", "审计", "审查")):
            return TaskType.AUDIT
        if any(k in text for k in ("test", "测试", "regression")):
            return TaskType.TEST
        if any(k in text for k in ("deploy", "部署", "release")):
            return TaskType.DEPLOY
        if any(k in text for k in ("refactor", "重构", "migrate")):
            return TaskType.REFACTOR
        if any(k in text for k in ("docs", "文档", "documentation")):
            return TaskType.DOCS
        if any(k in text for k in ("feature", "功能", "implement", "实现", "add")):
            return TaskType.FEATURE
        if any(k in text for k in ("operation", "运维", "backup", "维护")):
            return TaskType.OPERATION
        return TaskType.UNKNOWN

    def infer_capabilities(self) -> list[str]:
        """从任务画像推断所需能力"""
        caps = list(self.required_caps)
        tt = self.task_type if self.task_type != TaskType.UNKNOWN else self.infer_task_type()

        if tt == TaskType.FEATURE:
            caps.extend([Capability.IMPLEMENT_CODE, Capability.IMPLEMENT_FEATURE])
        elif tt == TaskType.BUGFIX:
            caps.extend([Capability.FIX_BUG, Capability.IMPLEMENT_CODE])
        elif tt == TaskType.RESEARCH:
            caps.append(Capability.REVIEW_PROGRESS)
        elif tt == TaskType.AUDIT:
            caps.extend([Capability.AUDIT_QUALITY, Capability.AUDIT_SECURITY,
                         Capability.VERIFY_ACCEPTANCE])
        elif tt == TaskType.TEST:
            caps.extend([Capability.TEST_UNIT, Capability.TEST_INTEGRATION,
                         Capability.TEST_REGRESSION])
        elif tt == TaskType.REFACTOR:
            caps.extend([Capability.IMPLEMENT_REFACTOR, Capability.REVIEW_CODE])
        elif tt == TaskType.DOCS:
            caps.extend([Capability.DESIGN_ARCH, Capability.DESIGN_INTERFACE])
        elif tt == TaskType.DEPLOY:
            caps.append(Capability.VERIFY_ACCEPTANCE)
        else:
            caps.append(Capability.IMPLEMENT_CODE)

        # 去重
        seen = set()
        deduped = []
        for c in caps:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        return deduped

    def to_dict(self) -> dict:
        d = asdict(self)
        d["task_type"] = self.task_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> TaskProfile:
        if "task_type" in data and isinstance(data["task_type"], str):
            try:
                data["task_type"] = TaskType(data["task_type"])
            except ValueError:
                data["task_type"] = TaskType.UNKNOWN
        return cls(**data)

    @classmethod
    def from_task_md(cls, md_text: str) -> TaskProfile:
        """从 Markdown 任务描述解析 TaskProfile"""
        profile = cls()
        lines = md_text.split("\n")
        title_line = lines[0] if lines else ""
        for m in re.finditer(r"# (\S+) — (.+)", title_line):
            profile.task_id = m.group(1)
            profile.title = m.group(2)

        for line in lines:
            if line.startswith("- Version:"):
                profile.version = line.split(":", 1)[-1].strip()
            elif line.startswith("- Priority:"):
                profile.priority = line.split(":", 1)[-1].strip().upper()
            elif line.startswith("- Owner:"):
                profile.owner = line.split(":", 1)[-1].strip()

        # 提取描述段落
        in_desc = False
        desc_parts = []
        for line in lines:
            if line.startswith("## 描述"):
                in_desc = True
                continue
            if line.startswith("## 验收"):
                in_desc = False
                continue
            if in_desc and line.strip():
                desc_parts.append(line.strip())
        profile.description = " ".join(desc_parts)

        # 提取安全边界
        in_safety = False
        for line in lines:
            if line.startswith("## 安全边界"):
                in_safety = True
                continue
            if line.startswith("## ") and in_safety:
                break
            if in_safety and line.strip():
                profile.safety_tags.append(line.strip())

        profile.task_type = profile.infer_task_type()
        profile.required_caps = profile.infer_capabilities()
        return profile


@dataclass
class TaskRoute:
    """路由结果：任务 → 角色 + 后端

    Attributes:
        task_id:       任务 ID
        role_id:       选中的角色 ID
        backend:       选中的后端
        strategy:      使用的主要路由策略
        confidence:    置信度 (0.0 ~ 1.0)
        reasoning:     路由决策理由
        alternatives:  备选方案列表
        blocked:       是否被拦截 (安全/策略原因)
        blocked_reason: 拦截原因
    """
    task_id: str = ""
    role_id: str = ""
    backend: str = ""
    strategy: RouteStrategy = RouteStrategy.DIRECT
    confidence: float = 0.8
    reasoning: str = ""
    alternatives: list[dict] = field(default_factory=list)
    blocked: bool = False
    blocked_reason: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["strategy"] = self.strategy.value if isinstance(self.strategy, RouteStrategy) else self.strategy
        return d

    @classmethod
    def from_dict(cls, data: dict) -> TaskRoute:
        if "strategy" in data and isinstance(data["strategy"], str):
            try:
                data["strategy"] = RouteStrategy(data["strategy"])
            except ValueError:
                data["strategy"] = RouteStrategy.DIRECT
        return cls(**data)

    @classmethod
    def blocked_route(cls, task_id: str, reason: str) -> TaskRoute:
        """创建拦截路由"""
        return cls(
            task_id=task_id,
            blocked=True,
            blocked_reason=reason,
            strategy=RouteStrategy.VERSION_SAFE,
            confidence=1.0,
            reasoning=f"BLOCKED: {reason}",
        )


@dataclass
class RoutingRule:
    """路由规则定义

    Attributes:
        rule_id:      规则唯一标识
        description:  规则描述
        match_type:   匹配类型 (task_type / priority / version / capability)
        match_value:  匹配值
        role_id:      匹配成功后分配的角色
        backend:      匹配成功后分配的后端
        priority:     规则优先级 (越大越优先)
    """
    rule_id: str
    description: str
    match_type: str           # task_type / priority / version / capability
    match_value: str
    role_id: str = "developer"
    backend: str = "claude"
    priority: int = 5

    def matches(self, profile: TaskProfile) -> bool:
        """检查该规则是否匹配给定任务画像"""
        if self.match_type == "task_type":
            return profile.task_type.value == self.match_value
        elif self.match_type == "priority":
            return profile.priority.upper() == self.match_value.upper()
        elif self.match_type == "version":
            return profile.version.startswith(self.match_value)
        elif self.match_type == "capability":
            return self.match_value in profile.required_caps
        return False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RoutingRule:
        return cls(**data)


# ─── Predefined Routing Rules ────────────────────────────────────────

DEFAULT_ROUTING_RULES: list[RoutingRule] = [
    # 按任务类型路由
    RoutingRule("rtl_feature", "Feature → Developer + Claude",
                "task_type", "feature", "developer", "claude", 8),
    RoutingRule("rtl_bugfix", "Bugfix → Developer + Claude",
                "task_type", "bugfix", "developer", "claude", 8),
    RoutingRule("rtl_research", "Research → PM + Research backend",
                "task_type", "research", "pm", "research", 8),
    RoutingRule("rtl_audit", "Audit → Auditor + Claude",
                "task_type", "audit", "auditor", "claude", 8),
    RoutingRule("rtl_test", "Test → Tester + Dry-run",
                "task_type", "test", "tester", "dry-run", 8),
    RoutingRule("rtl_refactor", "Refactor → Architect + Claude",
                "task_type", "refactor", "architect", "claude", 8),
    RoutingRule("rtl_docs", "Docs → Architect + Dry-run",
                "task_type", "docs", "architect", "dry-run", 6),
    RoutingRule("rtl_deploy", "Deploy → Developer + Claude (auto)",
                "task_type", "deploy", "developer", "claude", 7),

    # 按优先级路由
    RoutingRule("rtl_p0", "P0 → Developer + Claude (max effort)",
                "priority", "P0", "developer", "claude", 10),
    RoutingRule("rtl_p1", "P1 → Developer + Claude",
                "priority", "P1", "developer", "claude", 9),
    RoutingRule("rtl_p2", "P2 → Developer + Dry-run (economy)",
                "priority", "P2", "developer", "dry-run", 7),
    RoutingRule("rtl_p3", "P3 → Tester + Research backend",
                "priority", "P3", "tester", "research", 5),

    # 按版本前缀路由
    RoutingRule("rtl_v8", "V8.x → Developer + Claude",
                "version", "V8", "developer", "claude", 9),
    RoutingRule("rtl_v7", "V7.x → Developer + Claude",
                "version", "V7", "developer", "claude", 8),
    RoutingRule("rtl_v6", "V6.x → Developer + Claude",
                "version", "V6", "developer", "claude", 7),

    # 按能力路由
    RoutingRule("rtl_arch", "Design capability → Architect",
                "capability", Capability.DESIGN_ARCH, "architect", "dry-run", 7),
    RoutingRule("rtl_security", "Security → Auditor",
                "capability", Capability.AUDIT_SECURITY, "auditor", "claude", 9),
    RoutingRule("rtl_acceptance", "Acceptance verify → Auditor",
                "capability", Capability.VERIFY_ACCEPTANCE, "auditor", "dry-run", 7),
]


# ─── Safe Version Prefixes ────────────────────────────────────────────

SAFE_VERSION_PREFIXES = ("V2", "V3", "V4", "V5", "V6", "V7", "V8",
                         "research", "dry-run", "dry_run",
                         "acceptance", "test", "auto")

UNSAFE_VERSION_PREFIXES = ("live", "broker", "real_execution",
                           "capital", "production", "deploy")


# ─── Agent Router ─────────────────────────────────────────────────────

class AgentRouter:
    """Agent 路由引擎

    根据任务画像 (TaskProfile) 和应用的路由策略 (RouteStrategy)，
    匹配 AgentRoleRegistry 中的角色，选择最优后端，返回路由结果。

    用法示例:
        router = AgentRouter()
        profile = TaskProfile(task_id="T001", title="Implement X", ...)
        route = router.route(profile)
        if not route.blocked:
            print(f"Route to {route.role_id} via {route.backend}")
    """

    def __init__(self, registry: AgentRoleRegistry | None = None,
                 rules: list[RoutingRule] | None = None,
                 log_dir: Path | None = None):
        self.registry = registry or AgentRoleRegistry()
        self.registry.seed_defaults()
        self.rules = rules or list(DEFAULT_ROUTING_RULES)
        self.log_dir = log_dir or ROUTER_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)

    # ─── Public API ────────────────────────────────────────────────

    def route(self, profile: TaskProfile,
              preferred_strategy: RouteStrategy = RouteStrategy.COMPOSITE) -> TaskRoute:
        """路由主入口：对任务画像执行路由，返回路由结果

        Args:
            profile:             任务画像
            preferred_strategy:  首选路由策略 (默认 COMPOSITE 综合评分)

        Returns:
            TaskRoute 路由结果
        """
        # 1. 安全检查：版本安全限制
        safety_check = self._check_safety(profile)
        if safety_check.blocked:
            self._log_route(profile, safety_check)
            return safety_check

        # 2. DIRECT 策略：有指定 role_id/backend 优先使用
        if preferred_strategy == RouteStrategy.DIRECT or (
                profile.owner or profile.backend):
            result = self._route_direct(profile)
            if result.role_id:
                self._log_route(profile, result)
                return result

        # 3. CAPABILITY 策略：按能力匹配
        if preferred_strategy == RouteStrategy.CAPABILITY:
            result = self._route_by_capability(profile)
            self._log_route(profile, result)
            return result

        # 4. PRIORITY 策略：按优先级选择
        if preferred_strategy == RouteStrategy.PRIORITY:
            result = self._route_by_priority(profile)
            self._log_route(profile, result)
            return result

        # 5. COMPOSITE / 默认：综合评分
        result = self._route_composite(profile)
        self._log_route(profile, result)
        return result

    def route_many(self, profiles: list[TaskProfile]) -> list[TaskRoute]:
        """批量路由多个任务"""
        return [self.route(p) for p in profiles]

    # ─── Strategy Implementations ──────────────────────────────────

    def _route_direct(self, profile: TaskProfile) -> TaskRoute:
        """DIRECT: 直接指定的 role + backend"""
        role_id = profile.owner if profile.owner and self.registry.get(profile.owner) else ""
        backend = profile.backend if profile.backend else ""

        if role_id:
            spec = self.registry.get(role_id)
            if backend and spec and backend not in spec.allowed_backends:
                # 回退到角色允许的后端
                match = self.registry.match_backend(role_id, preferred=backend)
                backend = match.get("selected_backend", "claude")
            elif not backend and spec:
                match = self.registry.match_backend(role_id)
                backend = match.get("selected_backend", "claude")
            elif not backend:
                backend = "claude"

            reasoning_parts = [f"Direct route: role={role_id}"]
            if profile.owner:
                reasoning_parts.append(f"(specified by owner)")
            if profile.backend:
                reasoning_parts.append(f"backend={profile.backend}")
            reasoning = " ".join(reasoning_parts)

            return TaskRoute(
                task_id=profile.task_id,
                role_id=role_id,
                backend=backend,
                strategy=RouteStrategy.DIRECT,
                confidence=0.95,
                reasoning=reasoning,
            )

        # 没有直接指定 → 尝试从规则匹配
        matched_rules = self._find_matching_rules(profile, ["priority", "task_type"])
        if matched_rules:
            best = matched_rules[0]
            spec = self.registry.get(best.role_id)
            match = self.registry.match_backend(best.role_id) if spec else {}
            return TaskRoute(
                task_id=profile.task_id,
                role_id=best.role_id,
                backend=best.backend if best.backend and spec and best.backend in spec.allowed_backends
                           else match.get("selected_backend", "claude"),
                strategy=RouteStrategy.DIRECT,
                confidence=0.85,
                reasoning=f"Rule match: {best.description}",
            )

        # 无匹配 → 降级到 composite
        return TaskRoute()

    def _route_by_capability(self, profile: TaskProfile) -> TaskRoute:
        """CAPABILITY: 按能力要求匹配合适角色"""
        caps = profile.required_caps or profile.infer_capabilities()
        if not caps:
            return self._fallback(profile, "no_capabilities")

        # 对每个能力找角色，累计得分
        role_scores: dict[str, dict] = {}
        for cap in caps:
            matching = self.registry.find_by_capability(cap)
            for r in matching:
                rid = r["role_id"]
                if rid not in role_scores:
                    role_scores[rid] = {"role_id": rid, "name": r["name"], "score": 0, "matched_caps": []}
                role_scores[rid]["score"] += 1
                role_scores[rid]["matched_caps"].append(cap)

        if not role_scores:
            return self._fallback(profile, "no_role_matches_capabilities")

        # 按得分排序
        ranked = sorted(role_scores.values(), key=lambda x: (-x["score"], x["role_id"]))
        best = ranked[0]

        # 匹配后端
        match = self.registry.match_backend(best["role_id"])
        backend = match.get("selected_backend", "claude")

        alternatives = [
            {"role_id": r["role_id"], "name": r["name"],
             "score": r["score"], "matched_caps": r["matched_caps"]}
            for r in ranked[1:4]
        ]

        caps_str = ", ".join(best["matched_caps"][:3])
        reasoning = (
            f"Capability routing: role={best['role_id']} "
            f"(matched {best['score']} caps: {caps_str}), "
            f"backend={backend}"
        )

        return TaskRoute(
            task_id=profile.task_id,
            role_id=best["role_id"],
            backend=backend,
            strategy=RouteStrategy.CAPABILITY,
            confidence=min(0.95, 0.5 + best["score"] * 0.1),
            reasoning=reasoning,
            alternatives=alternatives,
        )

    def _route_by_priority(self, profile: TaskProfile) -> TaskRoute:
        """PRIORITY: 按优先级选择后端和角色"""
        priority_map = {
            "P0": {"role_id": "developer", "backend": "claude",   "confidence": 0.95, "effort": "max"},
            "P1": {"role_id": "developer", "backend": "claude",   "confidence": 0.90, "effort": "high"},
            "P2": {"role_id": "developer", "backend": "dry-run",  "confidence": 0.70, "effort": "normal"},
            "P3": {"role_id": "tester",    "backend": "research", "confidence": 0.60, "effort": "low"},
        }
        config = priority_map.get(profile.priority.upper(), priority_map["P2"])

        # 验证角色存在，后端是否在角色允许范围内
        spec = self.registry.get(config["role_id"])
        if not spec:
            # 角色不存在，使用降级
            return self._fallback(profile, f"role '{config['role_id']}' not found")

        # 首选后端 = 优先级映射指定的后端
        preferred = config["backend"]
        if preferred in spec.allowed_backends:
            backend = preferred
        else:
            # 回退到注册表匹配
            match = self.registry.match_backend(config["role_id"])
            backend = match.get("selected_backend", "claude")

        reasoning = (
            f"Priority routing: priority={profile.priority} → "
            f"role={config['role_id']}, backend={backend}, "
            f"effort={config['effort']}"
        )

        return TaskRoute(
            task_id=profile.task_id,
            role_id=config["role_id"],
            backend=backend,
            strategy=RouteStrategy.PRIORITY,
            confidence=config["confidence"],
            reasoning=reasoning,
        )

    def _route_composite(self, profile: TaskProfile) -> TaskRoute:
        """COMPOSITE: 综合多维度加权评分

        评分维度:
          - 规则匹配 (规则优先级权重)
          - 能力匹配 (匹配能力数量)
          - 优先级权重 (P0/P1 加分)
          - 版本安全 (safe 前缀加分)
        """
        role_scores: dict[str, dict] = {}

        # 1. 规则匹配贡献
        matched_rules = self._find_matching_rules(profile, ["task_type", "priority", "version", "capability"])
        for rule in matched_rules:
            if rule.role_id not in role_scores:
                role_scores[rule.role_id] = {
                    "role_id": rule.role_id,
                    "score": 0.0,
                    "sources": [],
                    "preferred_backend": "claude",
                }
            contribution = rule.priority * 0.5
            role_scores[rule.role_id]["score"] += contribution
            role_scores[rule.role_id]["sources"].append(f"rule:{rule.rule_id}(+{contribution})")
            # 规则的 backend 作为偏好
            role_scores[rule.role_id]["preferred_backend"] = rule.backend

        # 2. 能力匹配贡献
        caps = profile.required_caps or profile.infer_capabilities()
        for cap in caps:
            matching = self.registry.find_by_capability(cap)
            for r in matching:
                rid = r["role_id"]
                if rid not in role_scores:
                    role_scores[rid] = {
                        "role_id": rid, "score": 0.0, "sources": [],
                        "preferred_backend": "claude",
                    }
                role_scores[rid]["score"] += 3.0
                role_scores[rid]["sources"].append(f"cap:{cap}(+3.0)")

        # 3. 优先级加成
        priority_bonus = {"P0": 5.0, "P1": 3.0, "P2": 1.0, "P3": 0.0}
        bonus = priority_bonus.get(profile.priority.upper(), 0.0)
        if bonus > 0:
            # 给每个角色加等量的优先级分 (保持公平)
            for rid in role_scores:
                role_scores[rid]["score"] += bonus
                role_scores[rid]["sources"].append(f"priority:{profile.priority}(+{bonus})")

        if not role_scores:
            return self._fallback(profile, "no_rules_or_capabilities_matched")

        # 排序
        ranked = sorted(role_scores.values(), key=lambda x: (-x["score"], x["role_id"]))

        # 处理平局：如果有多个角色得分相同，选择更合适的
        best_score = ranked[0]["score"]
        if best_score <= 0:
            return self._fallback(profile, "all_scores_zero")

        best_backend = self._pick_best_backend(ranked[0], profile)
        sources_str = "; ".join(ranked[0]["sources"][:3])
        reasoning = (
            f"Composite routing: role={ranked[0]['role_id']} "
            f"(score={best_score:.1f}, "
            f"sources=[{sources_str}]), "
            f"backend={best_backend}"
        )

        alternatives = [
            {"role_id": r["role_id"], "score": r["score"]}
            for r in ranked[1:4]
        ]

        # 置信度 = sigmoid(score / 10) 近似
        confidence = min(0.95, max(0.3, best_score / 15.0))

        return TaskRoute(
            task_id=profile.task_id,
            role_id=ranked[0]["role_id"],
            backend=best_backend,
            strategy=RouteStrategy.COMPOSITE,
            confidence=confidence,
            reasoning=reasoning,
            alternatives=alternatives,
        )

    # ─── Helpers ───────────────────────────────────────────────────

    def _check_safety(self, profile: TaskProfile) -> TaskRoute:
        """安全检查：拦截不安全版本的任务"""
        version = profile.version or ""

        # 显式 unsafe 前缀拦截
        if any(version.lower().startswith(p) for p in UNSAFE_VERSION_PREFIXES):
            return TaskRoute.blocked_route(
                profile.task_id,
                f"Version '{version}' requires human approval (unsafe prefix)",
            )

        # 检查 safety_tags 中的限制
        for tag in profile.safety_tags:
            lowered = tag.lower()
            if "no_live_trade" in lowered and not lowered.startswith("no_"):
                # 如果明确的 live 标记
                if "live" in lowered or "real" in lowered or "production" in lowered:
                    return TaskRoute.blocked_route(
                        profile.task_id,
                        f"Safety tag blocks live execution: {tag}",
                    )

        return TaskRoute()

    def _pick_best_backend(self, role_entry: dict, profile: TaskProfile) -> str:
        """为角色挑选最佳后端"""
        role_id = role_entry["role_id"]
        preferred = role_entry.get("preferred_backend", "")

        # 高优任务优先使用 claude
        if profile.priority.upper() in ("P0", "P1"):
            preferred = "claude"

        match = self.registry.match_backend(role_id, preferred=preferred)
        return match.get("selected_backend", "claude")

    def _find_matching_rules(self, profile: TaskProfile,
                              match_types: list[str] | None = None) -> list[RoutingRule]:
        """匹配规则并排序（按优先级降序）"""
        matched = []
        for rule in self.rules:
            if match_types and rule.match_type not in match_types:
                continue
            if rule.matches(profile):
                matched.append(rule)
        # 按优先级降序 (同优先级保持规则定义顺序)
        matched.sort(key=lambda r: -r.priority)
        return matched

    def _fallback(self, profile: TaskProfile, reason: str) -> TaskRoute:
        """降级路由：当没有匹配时使用默认角色/后端"""
        default_role = "developer"
        match = self.registry.match_backend(default_role)
        backend = match.get("selected_backend", "claude")
        return TaskRoute(
            task_id=profile.task_id,
            role_id=default_role,
            backend=backend,
            strategy=RouteStrategy.COMPOSITE,
            confidence=0.3,
            reasoning=f"Fallback routing (no match): role={default_role}, "
                      f"backend={backend} (reason: {reason})",
        )

    # ─── Persistence / Logging ─────────────────────────────────────

    def _log_route(self, profile: TaskProfile, route: TaskRoute):
        """记录路由决策到日志文件"""
        if not self.log_dir:
            return
        timestamp = datetime.now(CST).strftime("%Y%m%d_%H%M%S_%f")
        log_entry = {
            "timestamp": timestamp,
            "profile": profile.to_dict(),
            "route": route.to_dict(),
        }
        log_path = self.log_dir / f"route_{profile.task_id or 'unknown'}_{timestamp[:15]}.json"
        log_path.write_text(json.dumps(log_entry, indent=2, ensure_ascii=False))

    def load_rules(self, path: Path) -> int:
        """从 JSON 文件加载自定义路由规则"""
        if not path.exists():
            return 0
        data = json.loads(path.read_text())
        if isinstance(data, list):
            for item in data:
                rule = RoutingRule.from_dict(item)
                # 替换已有规则或追加
                self.rules = [r for r in self.rules if r.rule_id != rule.rule_id]
                self.rules.append(rule)
            return len(data)
        return 0

    def export_rules(self, path: Path) -> int:
        """导出当前路由规则到 JSON 文件"""
        data = [r.to_dict() for r in self.rules]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return len(data)

    # ─── Diagnostics ───────────────────────────────────────────────

    def diagnose(self, profile: TaskProfile | None = None) -> dict:
        """路由诊断：返回路由器的配置和状态快照"""
        return {
            "router_version": "V8.1",
            "registered_roles": self.registry.list(),
            "routing_rules_count": len(self.rules),
            "safe_prefixes": list(SAFE_VERSION_PREFIXES),
            "unsafe_prefixes": list(UNSAFE_VERSION_PREFIXES),
            "log_dir": str(self.log_dir),
            "available_strategies": [s.value for s in RouteStrategy],
            "diagnosed_at": datetime.now(CST).isoformat(),
        }


# ─── Convenience Functions ────────────────────────────────────────────

def route_task(task_profile: TaskProfile | dict | str,
               registry: AgentRoleRegistry | None = None,
               strategy: RouteStrategy = RouteStrategy.COMPOSITE) -> TaskRoute:
    """快速路由：接受 TaskProfile / dict / markdown 文本，返回路由结果

    Args:
        task_profile: TaskProfile 对象、字典或 Markdown 任务描述文本
        registry:     可选的角色注册表 (默认创建新实例)
        strategy:     路由策略

    Returns:
        TaskRoute 路由结果
    """
    if isinstance(task_profile, dict):
        profile = TaskProfile.from_dict(task_profile)
    elif isinstance(task_profile, str):
        profile = TaskProfile.from_task_md(task_profile)
    elif isinstance(task_profile, TaskProfile):
        profile = task_profile
    else:
        raise TypeError(f"Unsupported profile type: {type(task_profile)}")

    router = AgentRouter(registry=registry)
    return router.route(profile, preferred_strategy=strategy)


def init_router(registry: AgentRoleRegistry | None = None) -> AgentRouter:
    """初始化带默认配置的路由器"""
    return AgentRouter(registry=registry)
