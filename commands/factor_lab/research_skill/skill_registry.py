"""Research Skill Registry — 投研 Skill 注册表

Centralized registry for all available research skills. Supports:
  - Register / list / get / delete skills
  - Persistence across reloads
  - Built-in skill seeding
  - Category-based filtering
  - Tag-based discovery
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from factor_lab.research_skill.skill_spec import (
    SkillSpec,
    SkillCategory,
    validate_spec,
)


CST = timezone(timedelta(hours=8))
REGISTRY_ROOT = Path("/home/ly/.hermes/research-assistant/agent_tasks/skill_registry")


class SkillRegistry:
    """投研 Skill 注册表"""

    def __init__(self, root: Path | None = None):
        self.root = root or REGISTRY_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, SkillSpec] = {}
        self._load()

    # ─── Core CRUD ─────────────────────────────────────────────────

    def register(self, spec: SkillSpec) -> dict:
        """注册一个 SkillSpec

        Returns:
            {"status": "ok", "skill_id": spec.skill_id}
            或 {"status": "error", "errors": [...]}
        """
        errors = validate_spec(spec)
        if errors:
            return {"status": "error", "errors": errors}
        spec.updated_at = datetime.now(CST).isoformat()
        self._skills[spec.skill_id] = spec
        self._save(spec)
        return {"status": "ok", "skill_id": spec.skill_id}

    def list(self, category: str | None = None, tag: str | None = None) -> list[dict]:
        """列出所有注册的 Skill

        Args:
            category: 按分类筛选 (可选)
            tag: 按标签筛选 (可选)

        Returns:
            Skill dict 列表 (不含 execute 函数)
        """
        results = []
        for spec in self._skills.values():
            if category and spec.category != category:
                continue
            if tag and tag not in spec.tags:
                continue
            d = spec.to_dict()
            d.pop("execute", None)
            results.append(d)
        results.sort(key=lambda x: x["skill_id"])
        return results

    def get(self, skill_id: str) -> Optional[SkillSpec]:
        """按 skill_id 获取 SkillSpec (含 execute 函数)"""
        return self._skills.get(skill_id)

    def delete(self, skill_id: str) -> dict:
        """删除一个 Skill"""
        if skill_id in self._skills:
            del self._skills[skill_id]
            path = self.root / f"{skill_id}.json"
            if path.exists():
                path.unlink()
            return {"status": "ok", "skill_id": skill_id}
        return {"status": "error", "error": f"skill '{skill_id}' not found"}

    # ─── Discovery ─────────────────────────────────────────────────

    def find_by_tag(self, tag: str) -> list[dict]:
        """按标签查找 Skills"""
        return self.list(tag=tag)

    def count_by_category(self) -> dict[str, int]:
        """按分类统计数量"""
        counts: dict[str, int] = {}
        for spec in self._skills.values():
            counts[spec.category] = counts.get(spec.category, 0) + 1
        return dict(sorted(counts.items()))

    # ─── Persistence ───────────────────────────────────────────────

    def _save(self, spec: SkillSpec):
        """持久化单个 Skill 到文件"""
        d = spec.to_dict()
        d.pop("execute", None)  # 不序列化执行函数
        path = self.root / f"{spec.skill_id}.json"
        path.write_text(json.dumps(d, indent=2, ensure_ascii=False))

    def _load(self):
        """从磁盘加载所有注册的 Skills，并尝试恢复 execute 函数"""
        self._skills = {}
        if not self.root.exists():
            return
        for path in sorted(self.root.glob("*.json")):
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text())
                spec = SkillSpec.from_dict(data)
                spec.load_execute()  # attempt to restore execute from handler path
                self._skills[spec.skill_id] = spec
            except Exception:
                continue

    # ─── Built-in Skills ───────────────────────────────────────────

    def seed_defaults(self, builtins: list[SkillSpec] | None = None):
        """注册内置 Skills (跳过已存在的)"""
        from factor_lab.research_skill.builtins import BUILTIN_SKILLS
        specs = builtins or BUILTIN_SKILLS
        count = 0
        for spec in specs:
            if spec.skill_id not in self._skills:
                self.register(spec)
                count += 1
        return count


def init_registry(builtins: list[SkillSpec] | None = None) -> SkillRegistry:
    """初始化注册表并填充内置 Skills，返回 SkillRegistry 实例"""
    registry = SkillRegistry()
    registry.seed_defaults(builtins)
    return registry
