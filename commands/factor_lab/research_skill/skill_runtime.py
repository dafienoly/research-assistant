"""Research Skill Runtime — 投研 Skill 执行引擎

Executes registered Research Skills with proper safety controls, timeout
management, result capture, and error handling. Integrates with the Hermes
agent execution system via the SkillRegistry.
"""

from __future__ import annotations

import json
import os
import time
import uuid
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from factor_lab.research_skill.skill_spec import (
    SkillSpec,
    SkillResult,
    SkillStatus,
    SkillParam,
)
from factor_lab.research_skill.skill_registry import SkillRegistry


CST = timezone(timedelta(hours=8))
RUNTIME_ROOT = Path(
    os.environ.get(
        "HERMES_RESEARCH_SKILL_RUNTIME",
        Path.home() / ".hermes/state/research-assistant/research-skills/runs",
    )
)
DEFAULT_TIMEOUT = 300  # 5 minutes


@dataclass
class ResearchContext:
    """投研上下文 — 传递给 Skill 执行函数的运行时信息

    Attributes:
        run_id: 当前执行 run 的唯一标识
        start_date: 分析开始日期 (YYYY-MM-DD)
        end_date: 分析结束日期 (YYYY-MM-DD)
        symbols: 可选股票代码列表
        extra: 额外上下文参数
    """
    run_id: str
    start_date: str = ""
    end_date: str = ""
    symbols: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


class SkillRuntime:
    """Skill 执行引擎

    职责：
    - 从注册表获取 SkillSpec
    - 验证参数
    - 执行 Skill
    - 捕获结果 / 错误
    - 超时保护
    - 执行记录持久化
    """

    def __init__(self, registry: SkillRegistry | None = None,
                 runtime_root: Path | None = None):
        self.registry = registry or SkillRegistry()
        self.runtime_root = runtime_root or RUNTIME_ROOT
        self.runtime_root.mkdir(parents=True, exist_ok=True)

    # ─── Execution ─────────────────────────────────────────────────

    def run(self, skill_id: str, params: dict | None = None,
            context: ResearchContext | None = None,
            timeout: int = DEFAULT_TIMEOUT) -> SkillResult:
        """执行一个 Skill

        Args:
            skill_id: 要执行的 Skill 标识
            params: 技能参数 (key-value)
            context: 研究上下文
            timeout: 超时秒数

        Returns:
            SkillResult 执行结果
        """
        spec = self.registry.get(skill_id)
        if not spec:
            return SkillResult(
                skill_id=skill_id,
                status=SkillStatus.FAILED.value,
                error=f"Skill '{skill_id}' not found in registry",
            )

        # 尝试从 handler 路径恢复 execute 函数
        if not spec.execute:
            spec.load_execute()
        if not spec.execute:
            return SkillResult(
                skill_id=skill_id,
                status=SkillStatus.FAILED.value,
                error=f"Skill '{skill_id}' has no execute function",
            )

        # 参数验证
        validated, err = self._validate_params(spec, params or {})
        if err:
            return SkillResult(
                skill_id=skill_id,
                status=SkillStatus.FAILED.value,
                error=err,
            )

        # 构建上下文
        ctx = context or ResearchContext(run_id=self._new_run_id())
        if not ctx.run_id:
            ctx.run_id = self._new_run_id()
        if not ctx.start_date:
            ctx.start_date = datetime.now(CST).strftime("%Y-%m-%d")
        if not ctx.end_date:
            ctx.end_date = datetime.now(CST).strftime("%Y-%m-%d")

        # 执行
        result = SkillResult(
            skill_id=skill_id,
            status=SkillStatus.RUNNING.value,
            run_id=ctx.run_id,
            started_at=datetime.now(CST).isoformat(),
        )

        start = time.monotonic()
        try:
            import signal

            if hasattr(signal, "SIGALRM"):
                # Unix: use SIGALRM for timeout
                def _handler(signum, frame):
                    raise TimeoutError(f"Skill '{skill_id}' timed out after {timeout}s")

                signal.signal(signal.SIGALRM, _handler)
                signal.alarm(timeout)

            data = spec.execute(ctx, validated)
            result.data = data if isinstance(data, dict) else {"result": str(data)}
            result.status = SkillStatus.COMPLETED.value

            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)

        except TimeoutError as e:
            result.status = SkillStatus.FAILED.value
            result.error = str(e)
        except Exception as e:
            result.status = SkillStatus.FAILED.value
            result.error = f"{type(e).__name__}: {e}"
            result.data = {"traceback": traceback.format_exc()}

        elapsed = time.monotonic() - start
        result.duration_ms = round(elapsed * 1000, 1)
        result.completed_at = datetime.now(CST).isoformat()

        # 持久化执行记录
        self._persist(result, spec)
        return result

    def run_many(self, skill_ids: list[str],
                 params_list: list[dict] | None = None,
                 context: ResearchContext | None = None,
                 timeout: int = DEFAULT_TIMEOUT) -> list[SkillResult]:
        """顺序执行多个 Skills

        Args:
            skill_ids: Skill 标识列表
            params_list: 每个 Skill 的参数 (可选)
            context: 研究上下文
            timeout: 超时秒数

        Returns:
            SkillResult 列表
        """
        results = []
        for i, skill_id in enumerate(skill_ids):
            p = params_list[i] if params_list and i < len(params_list) else {}
            result = self.run(skill_id, p, context, timeout)
            results.append(result)
        return results

    # ─── Run History ───────────────────────────────────────────────

    def get_run(self, run_id: str) -> Optional[dict]:
        """按 run_id 获取执行记录"""
        path = self.runtime_root / f"{run_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def list_runs(self, skill_id: str | None = None,
                  limit: int = 50) -> list[dict]:
        """列出执行记录

        Args:
            skill_id: 按 Skill 筛选 (可选)
            limit: 最大返回数

        Returns:
            执行记录列表 (最新在前)
        """
        runs = []
        for path in sorted(self.runtime_root.glob("*.json"), reverse=True):
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text())
                if skill_id and data.get("skill_id") != skill_id:
                    continue
                runs.append(data)
                if len(runs) >= limit:
                    break
            except Exception:
                continue
        return runs

    # ─── Helpers ───────────────────────────────────────────────────

    def _validate_params(self, spec: SkillSpec, params: dict) -> tuple[dict, str]:
        """验证并转换参数

        Returns:
            (validated_params, error_string)
            如果 error 为空，则 validated_params 有效
        """
        validated = {}

        for p in spec.params:
            if isinstance(p, dict):
                p = SkillParam.from_dict(p)
            key = p.name

            if key in params:
                value = params[key]
            elif p.default is not None:
                value = p.default
            elif p.required:
                return {}, f"required parameter '{key}' is missing for skill '{spec.skill_id}'"
            else:
                continue

            # 类型转换
            try:
                if p.type == "int":
                    validated[key] = int(value)
                elif p.type == "float":
                    validated[key] = float(value)
                elif p.type == "bool":
                    if isinstance(value, str):
                        validated[key] = value.lower() in ("true", "1", "yes")
                    else:
                        validated[key] = bool(value)
                elif p.type == "date":
                    validated[key] = str(value)
                elif p.type == "list":
                    if isinstance(value, str):
                        validated[key] = [x.strip() for x in value.split(",") if x.strip()]
                    else:
                        validated[key] = list(value)
                else:
                    validated[key] = str(value)
            except (ValueError, TypeError) as e:
                return {}, f"invalid value for parameter '{key}': {e}"

            # Choices 检查
            if p.choices and validated.get(key) not in p.choices:
                return {}, f"parameter '{key}' must be one of {p.choices}"

        return validated, ""

    def _persist(self, result: SkillResult, spec: SkillSpec):
        """持久化执行记录"""
        d = result.to_dict()
        d["skill_name"] = spec.name
        d["skill_category"] = spec.category
        path = self.runtime_root / f"{result.run_id}.json"
        path.write_text(json.dumps(d, indent=2, ensure_ascii=False))

    @staticmethod
    def _new_run_id() -> str:
        return f"sr_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
