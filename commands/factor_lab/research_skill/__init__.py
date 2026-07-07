"""Research Skill Runtime V6.0 — 投研 skill 运行时

A runtime system for defining, registering, and executing research "skills"
— reusable, predefined analysis tasks for quantitative research.

Provides:
  - SkillSpec: schema for defining a research skill
  - SkillRegistry: CRUD registry with persistence
  - SkillRuntime: execution engine with safety controls
  - Built-in skills: data-quality, factor-ranking, universe-overview, market-snapshot
  - CLI integration: research:list-skills, research:show-skill, research:run-skill
"""

from factor_lab.research_skill.skill_spec import (
    SkillSpec,
    SkillParam,
    SkillCategory,
    SkillStatus,
    SkillResult,
    validate_spec,
)
from factor_lab.research_skill.skill_registry import SkillRegistry, init_registry
from factor_lab.research_skill.skill_runtime import SkillRuntime, ResearchContext
from factor_lab.research_skill.builtins import BUILTIN_SKILLS

__all__ = [
    "SkillSpec",
    "SkillParam",
    "SkillCategory",
    "SkillStatus",
    "SkillResult",
    "validate_spec",
    "SkillRegistry",
    "init_registry",
    "SkillRuntime",
    "ResearchContext",
    "BUILTIN_SKILLS",
]
