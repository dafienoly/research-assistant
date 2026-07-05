"""Leader planner for Hermes Alpha Factory.

职责：
1. 读取本地开发报告、代码状态、Alpha Registry 与测试状态。
2. 按 V3+ Alpha Factory 生命周期路线图判断当前阶段。
3. 生成可交给 Hermes/Agent 执行的任务包。

安全边界：本模块只生成任务与报告，不触发回测、不修改策略配置、
不调用 broker/miniqmt/交易接口。
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

from factor_lab.leader.roadmap import ALPHA_FACTORY_ROADMAP, roadmap_as_dicts

CST = timezone(timedelta(hours=8))
RESEARCH_ROOT = Path("/home/ly/.hermes/research-assistant")
COMMANDS_ROOT = RESEARCH_ROOT / "commands"
FACTOR_LAB_ROOT = COMMANDS_ROOT / "factor_lab"
CLI_PATH = COMMANDS_ROOT / "hermes_cli.py"
REPORT_ROOT = Path("/mnt/d/HermesReports")
TASK_ROOT = RESEARCH_ROOT / "agent_tasks"


@dataclass(frozen=True)
class LeaderTask:
    task_id: str
    version: str
    title: str
    priority: str
    owner_role: str
    status: str
    rationale: str
    target_files: tuple[str, ...]
    instructions: tuple[str, ...]
    acceptance: tuple[str, ...]
    test_commands: tuple[str, ...]
    safety: dict

    def to_dict(self) -> dict:
        return asdict(self)


def inspect_system() -> dict:
    """检查 Hermes 投研系统当前状态，返回结构化 leader 报告。"""
    modules = _module_inventory()
    cli = _cli_inventory()
    reports = _report_inventory()
    alpha_registry = _alpha_registry_snapshot()
    factor_catalog = _factor_catalog_snapshot()
    tests = _test_inventory()
    findings = _findings(modules, cli, reports, alpha_registry, factor_catalog, tests)
    stage = _infer_stage(findings, alpha_registry, factor_catalog, cli)

    return {
        "generated_at": _now_iso(),
        "roadmap_policy": "V3+ 按 Alpha Factory 生命周期排版本；P0/P1/P2/P3 因子方向挂到 V3 Alpha Factory 下，不再继续堆 V2.x。",
        "stage": stage,
        "summary": {
            "modules": len(modules),
            "cli_handlers": len(cli.get("handlers", [])),
            "cli_help_commands": len(cli.get("help_commands", [])),
            "alpha_registry_count": alpha_registry.get("count", 0),
            "factor_catalog_count": factor_catalog.get("count", 0),
            "test_files": len(tests),
            "latest_report_dirs": len(reports),
        },
        "modules": modules,
        "cli": cli,
        "reports": reports,
        "alpha_registry": alpha_registry,
        "factor_catalog": factor_catalog,
        "tests": tests,
        "findings": findings,
        "roadmap": roadmap_as_dicts(),
        "safety": _leader_safety_flags(),
    }


def dispatch_tasks(dry_run: bool = False, max_tasks: int = 6) -> dict:
    """根据 inspect_system() 结果生成任务包。

    dry_run=True 时只返回计划，不写文件。
    """
    inspection = inspect_system()
    tasks = _plan_tasks(inspection)[:max_tasks]
    run_id = datetime.now(CST).strftime("%Y%m%d_%H%M%S_%f")
    dispatch = {
        "run_id": run_id,
        "generated_at": _now_iso(),
        "dry_run": dry_run,
        "stage": inspection["stage"],
        "task_count": len(tasks),
        "tasks": [t.to_dict() for t in tasks],
        "safety": _leader_safety_flags(),
    }

    if not dry_run:
        out_dir = TASK_ROOT / run_id
        task_dir = out_dir / "tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "leader_inspection.json").write_text(_json(inspection), encoding="utf-8")
        (out_dir / "tasks.json").write_text(_json(dispatch), encoding="utf-8")
        (out_dir / "leader_dispatch_plan.md").write_text(
            _render_dispatch_markdown(inspection, tasks, out_dir), encoding="utf-8"
        )
        for task in tasks:
            filename = f"{task.task_id}_{_slug(task.title)}.md"
            (task_dir / filename).write_text(_render_task_markdown(task), encoding="utf-8")
        latest = {
            "run_id": run_id,
            "path": str(out_dir),
            "generated_at": dispatch["generated_at"],
            "stage": inspection["stage"],
            "task_count": len(tasks),
        }
        TASK_ROOT.mkdir(parents=True, exist_ok=True)
        (TASK_ROOT / "latest.json").write_text(_json(latest), encoding="utf-8")
        dispatch["output_dir"] = str(out_dir)

    return dispatch


def _module_inventory() -> list[dict]:
    modules: list[dict] = []
    if not FACTOR_LAB_ROOT.exists():
        return modules
    for child in sorted(FACTOR_LAB_ROOT.iterdir()):
        if child.name.startswith("__"):
            continue
        if child.is_dir():
            modules.append({
                "module": child.name,
                "path": str(child.relative_to(COMMANDS_ROOT)),
                "py_files": len(list(child.rglob("*.py"))),
                "type": "package",
            })
        elif child.suffix == ".py":
            modules.append({
                "module": child.stem,
                "path": str(child.relative_to(COMMANDS_ROOT)),
                "py_files": 1,
                "type": "module",
            })
    return modules


def _cli_inventory() -> dict:
    if not CLI_PATH.exists():
        return {"handlers": [], "help_commands": [], "help_only": []}
    src = CLI_PATH.read_text(encoding="utf-8")
    handlers = sorted(set(re.findall(r"command\s*==\s*[\"']([^\"']+)[\"']", src)))
    # 支持 command.startswith("alpha:") 这种聚合 handler。
    startswith_handlers = sorted(set(re.findall(r"command\.startswith\([\"']([^\"']+)[\"']\)", src)))
    help_commands = _extract_help_commands(src)
    def _has_handler(cmd: str) -> bool:
        return cmd in handlers or any(cmd.startswith(prefix) for prefix in startswith_handlers)
    help_only = [cmd for cmd in help_commands if not _has_handler(cmd) and not cmd.endswith(":")]
    return {
        "handlers": handlers,
        "startswith_handlers": startswith_handlers,
        "help_commands": help_commands,
        "help_only": help_only,
        "has_alpha_router": any(prefix == "alpha:" for prefix in startswith_handlers),
        "has_leader_inspect": "leader:inspect" in handlers,
        "has_leader_dispatch": "leader:dispatch" in handlers,
        "has_leader_accept": "leader:accept" in handlers,
    }


def _extract_help_commands(src: str) -> list[str]:
    commands: set[str] = set()
    for line in src.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"([a-zA-Z0-9_-]+:[a-zA-Z0-9_-]+)", stripped)
        if match:
            commands.add(match.group(1))
    return sorted(commands)


def _report_inventory() -> list[dict]:
    roots = [
        REPORT_ROOT / "architecture_audit",
        REPORT_ROOT / "alpha_factory",
        REPORT_ROOT / "alpha_factor_migration",
        REPORT_ROOT / "factor_leaderboard",
        REPORT_ROOT / "factor_validation",
        RESEARCH_ROOT / "logs",
        RESEARCH_ROOT / "research_outputs" / "factor_lab",
    ]
    rows: list[dict] = []
    for root in roots:
        if not root.exists():
            continue
        children = [p for p in root.iterdir() if p.is_dir()]
        latest = max(children, key=lambda p: p.stat().st_mtime) if children else None
        rows.append({
            "name": root.name,
            "path": str(root),
            "exists": True,
            "runs": len(children),
            "latest": str(latest) if latest else None,
            "latest_mtime": datetime.fromtimestamp(latest.stat().st_mtime, CST).isoformat() if latest else None,
        })
    return rows


def _alpha_registry_snapshot() -> dict:
    try:
        from factor_lab.alpha.registry import REGISTRY_ROOT, list_alpha
        alphas = list_alpha()
        status_counts: dict[str, int] = {}
        for alpha in alphas:
            status = alpha.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "root": str(REGISTRY_ROOT),
            "exists": REGISTRY_ROOT.exists(),
            "count": len(alphas),
            "status_counts": status_counts,
            "sample": alphas[:5],
        }
    except Exception as exc:  # pragma: no cover - defensive runtime reporting
        return {"exists": False, "count": 0, "error": str(exc)}


def _factor_catalog_snapshot() -> dict:
    try:
        from factor_lab.factor_base import list_factors
        factors = list_factors()
        category_counts: dict[str, int] = {}
        for factor in factors:
            cat = factor.get("category", "unknown")
            category_counts[cat] = category_counts.get(cat, 0) + 1
        return {
            "count": len(factors),
            "category_counts": dict(sorted(category_counts.items())),
            "sample": [{"name": f.get("name"), "category": f.get("category")} for f in factors[:8]],
        }
    except Exception as exc:  # pragma: no cover
        return {"count": 0, "category_counts": {}, "error": str(exc)}


def _test_inventory() -> list[dict]:
    test_dir = COMMANDS_ROOT / "tests"
    if not test_dir.exists():
        return []
    rows: list[dict] = []
    for path in sorted(test_dir.glob("test_*.py")):
        src = path.read_text(encoding="utf-8")
        rows.append({
            "file": str(path.relative_to(COMMANDS_ROOT)),
            "tests": src.count("def test_"),
            "has_safety_test": any(term in src for term in ("no_broker", "no_trade", "no_auto", "live_enabled")),
        })
    return rows


def _findings(modules: list[dict], cli: dict, reports: list[dict], alpha_registry: dict, factor_catalog: dict, tests: list[dict]) -> list[dict]:
    module_names = {m["module"] for m in modules}
    findings: list[dict] = []

    def add(severity: str, code: str, title: str, evidence: str, recommendation: str) -> None:
        findings.append({
            "severity": severity,
            "code": code,
            "title": title,
            "evidence": evidence,
            "recommendation": recommendation,
        })

    if "alpha" not in module_names:
        add("P0", "MISSING_ALPHA_FACTORY", "缺少 Alpha Factory 模块", "factor_lab/alpha 不存在", "先完成 V3.0 Foundation")
    if not cli.get("has_alpha_router"):
        add("P0", "ALPHA_CLI_HELP_ONLY", "alpha:* 帮助存在但未接入 CLI handler", "hermes_cli.py 帮助列出 alpha:list 等，但没有 command.startswith('alpha:') 路由", "接入 alpha_cli.main，并补 migrate-existing-factors")
    if not cli.get("has_leader_inspect") or not cli.get("has_leader_dispatch"):
        add("P0", "MISSING_LEADER_CLI", "缺少 leader 自动派发入口", "未发现 leader:inspect / leader:dispatch", "新增 leader CLI，用于检查报告和生成任务包")
    if not cli.get("has_leader_accept"):
        add("P0", "MISSING_LEADER_ACCEPTANCE", "leader accept missing", "leader:accept not found", "add acceptance report command")
    if factor_catalog.get("count", 0) > 0 and alpha_registry.get("count", 0) < factor_catalog.get("count", 0):
        add(
            "P1",
            "FACTOR_CATALOG_NOT_FULLY_MIGRATED",
            "现有因子尚未完整纳入 Alpha Registry",
            f"factor_catalog={factor_catalog.get('count', 0)}, alpha_registry={alpha_registry.get('count', 0)}",
            "优先执行 V3.0.1 Existing Factor Catalog Migration",
        )
    try:
        from factor_lab.leader.acceptance import REQUIRED_MIGRATION_FILES, MIGRATION_ROOT
        latest_dirs = [p for p in MIGRATION_ROOT.iterdir() if p.is_dir()] if MIGRATION_ROOT.exists() else []
        latest = max(latest_dirs, key=lambda p: p.stat().st_mtime) if latest_dirs else None
        if latest is not None:
            existing = {p.name for p in latest.iterdir() if p.is_file()}
            missing = [name for name in REQUIRED_MIGRATION_FILES if name not in existing]
            if missing:
                add("P0", "MIGRATION_ACCEPTANCE_GAPS", "V3.0.1 迁移报告缺少验收文件", ",".join(missing), "补齐迁移输出与自动验收")
    except Exception:
        pass
    if not any(t["file"].endswith("test_alpha_factory.py") for t in tests):
        add("P1", "MISSING_ALPHA_TESTS", "缺少 Alpha Factory 测试", "tests/test_alpha_factory.py 未发现", "补齐 V3.0 基础测试")
    if not any(r["name"] == "architecture_audit" for r in reports):
        add("P2", "NO_ARCHITECTURE_AUDIT_REPORT", "未发现架构审计报告目录", "/mnt/d/HermesReports/architecture_audit 不存在或不可读", "运行 architecture:audit 后再派发任务")
    return findings


def _infer_stage(findings: list[dict], alpha_registry: dict, factor_catalog: dict, cli: dict) -> dict:
    codes = {f["code"] for f in findings}
    if "MISSING_ALPHA_FACTORY" in codes:
        current = "V2.14.x"
        next_version = "V3.0"
        reason = "Alpha Factory Foundation 尚未完成。"
    elif "ALPHA_CLI_HELP_ONLY" in codes or "MISSING_LEADER_CLI" in codes or "MISSING_LEADER_ACCEPTANCE" in codes:
        current = "V3.0 partial"
        next_version = "V3.0 hardening"
        reason = "V3.0 模块存在，但 CLI/Leader 治理入口不完整。"
    elif alpha_registry.get("count", 0) < factor_catalog.get("count", 0):
        current = "V3.0"
        next_version = "V3.0.1"
        reason = "Alpha Factory 底座已存在，下一步应迁移现有因子目录。"
    elif "MIGRATION_ACCEPTANCE_GAPS" in codes:
        current = "V3.0.1 functional_complete"
        next_version = "V3.0.1 acceptance_hardening"
        reason = "V3.0.1 功能已完成，但迁移报告与自动验收产物未达到完整验收清单。"
    else:
        current = "V3.0.1 acceptance_ready"
        next_version = "V3.1"
        reason = "V3.0.1 通过验收硬门禁后，才进入 V3.1 LLM Alpha Discovery 或行业相对 Alpha Pack。"
    return {
        "current": current,
        "next_version": next_version,
        "reason": reason,
        "next_options": ["V2.15 governed dry run", "V3.1 LLM Alpha Discovery"],
        "blockers": [f for f in findings if f["severity"] == "P0"],
    }


def _plan_tasks(inspection: dict) -> list[LeaderTask]:
    stage = inspection["stage"]
    findings = inspection["findings"]
    codes = {f["code"] for f in findings}
    tasks: list[LeaderTask] = []

    def task(task_id: str, version: str, title: str, priority: str, owner_role: str,
             rationale: str, target_files: Iterable[str], instructions: Iterable[str],
             acceptance: Iterable[str], test_commands: Iterable[str]) -> None:
        tasks.append(LeaderTask(
            task_id=task_id,
            version=version,
            title=title,
            priority=priority,
            owner_role=owner_role,
            status="pending",
            rationale=rationale,
            target_files=tuple(target_files),
            instructions=tuple(instructions),
            acceptance=tuple(acceptance),
            test_commands=tuple(test_commands),
            safety=_leader_safety_flags(),
        ))

    if "ALPHA_CLI_HELP_ONLY" in codes:
        task(
            "T001",
            "V3.0-hardening",
            "接通 Alpha Factory CLI Router",
            "P0",
            "cli_engineer",
            "帮助文档已有 alpha:*，但 hermes_cli.py 没有实际 handler，导致 Hermes 无法独立执行 Alpha Factory。",
            ("commands/hermes_cli.py", "commands/factor_lab/alpha/alpha_cli.py"),
            (
                "在 hermes_cli.py 中增加 command.startswith('alpha:') 聚合路由。",
                "在 alpha_cli.py 中增加 migrate-existing-factors 子命令。",
                "保持所有 Alpha 默认 disabled，不触发回测/交易。",
            ),
            (
                "python3 hermes_cli.py alpha:list 可运行。",
                "python3 hermes_cli.py alpha:migrate-existing-factors --dry-run 可生成迁移报告。",
                "已有 alpha 单元测试通过。",
            ),
            ("cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_alpha_factory.py tests/test_factor_catalog_migration.py -q",),
        )

    if "MISSING_LEADER_CLI" in codes:
        task(
            "T002",
            "V3.0-hardening",
            "新增 Leader Inspect/Dispatch 入口",
            "P0",
            "lead_orchestrator",
            "当前需要人工在 ChatGPT 与 Hermes 之间搬运报告，缺少本地 leader 自动检查与派发层。",
            ("commands/factor_lab/leader/", "commands/hermes_cli.py", "commands/tests/test_alpha_factory_leader.py"),
            (
                "新增 leader:inspect：输出当前阶段、阻塞项、路线图位置。",
                "新增 leader:dispatch：生成 agent_tasks/<run_id>/ 任务包。",
                "任务包包含 leader_inspection.json、tasks.json、leader_dispatch_plan.md 和逐任务 markdown。",
            ),
            (
                "leader:inspect 不写文件，只读本地报告/代码/registry。",
                "leader:dispatch 只生成任务文件，不触发交易或回测。",
                "任务必须按 V3 Alpha Factory 生命周期路线图生成。",
            ),
            ("cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_alpha_factory_leader.py -q",),
        )

    if "FACTOR_CATALOG_NOT_FULLY_MIGRATED" in codes:
        task(
            "T003",
            "V3.0.1",
            "执行 Existing Factor Catalog Migration",
            "P1",
            "migration_engineer",
            "现有 factor_base 注册表尚未完整映射进 Alpha Registry，V3.1 之前应先完成目录迁移。",
            ("commands/factor_lab/alpha/factor_catalog_migration.py", "/mnt/d/HermesData/alpha_registry"),
            (
                "先运行 dry-run，检查 total/migrated/skipped/duplicates。",
                "确认无 skipped 后再运行正式迁移。",
                "迁移后抽样 alpha_spec.json，确认 enabled/paper_enabled/live_enabled 全为 false。",
            ),
            (
                "factor_base 所有因子都在 migrated 或 duplicate/skipped 列表中有解释。",
                "迁移输出包含 JSON/CSV/HTML/MD/manifest/audit。",
                "重复运行不重复污染 registry。",
            ),
            (
                "cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 hermes_cli.py alpha:migrate-existing-factors --dry-run",
                "cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_factor_catalog_migration.py -q",
            ),
        )

    # Continue toward a complete research system: hard acceptance first, new research second.
    task(
        "T004",
        "V3.0-acceptance",
        "补强 Alpha Factory 注册入口验收",
        "P0",
        "alpha_foundation_reviewer",
        "alpha:register --spec 是后续外部 AlphaSpec、LLM AlphaSpec 和批量迁移的基础入口，必须作为 V3.0 验收点。",
        ("commands/hermes_cli.py", "commands/factor_lab/alpha/alpha_cli.py", "commands/tests/test_alpha_factory.py"),
        (
            "确认 hermes_cli.py 帮助列出 alpha:register --spec <path>。",
            "确认 alpha:register 只注册 AlphaSpec，不触发回测或配置修改。",
            "新增 CLI smoke test 覆盖 alpha:register、alpha:list、alpha:show、alpha:evaluation-plan。",
        ),
        (
            "hermes alpha:register --spec <path> 可运行。",
            "注册后的 alpha_spec.json 默认 enabled=false、paper_enabled=false、live_enabled=false。",
            "测试必须覆盖 CLI 存在性和安全默认值。",
        ),
        ("cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest -q",),
    )

    task(
        "T005",
        "V3.0.1-acceptance",
        "补齐 Existing Factor Catalog Migration 验收产物",
        "P0",
        "migration_acceptance_engineer",
        "Hermes 已完成 88 因子迁移，但最新报告目录缺少完整验收清单中的部分产物，需要补齐后才能进入 V3.1。",
        ("commands/factor_lab/alpha/factor_catalog_migration.py", "commands/tests/test_factor_catalog_migration.py", "/mnt/d/HermesReports/alpha_factor_migration/"),
        (
            "补齐 factor_alpha_mapping.csv、factor_data_requirements.csv、factor_correlation_baseline.csv、alpha_registry_update_preview.json、audit.log。",
            "migrated/skipped/duplicate 三类 CSV 即使为空也必须生成。",
            "为每个因子补 FactorSpec 或等价字段：factor_name、category、subcategory、data_requirements、risk_constraints。",
        ),
        (
            "V3.0.1 最新 run 目录包含完整 15 个验收文件。",
            "88 个因子全部被识别；skipped/duplicate 有明确原因。",
            "leader:accept 不再报 MIGRATION_ACCEPTANCE_GAPS。",
        ),
        ("cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 hermes_cli.py leader:accept",),
    )

    task(
        "T006",
        "CI-CD",
        "建立自动验收与本地 CI/CD 门禁",
        "P0",
        "ci_engineer",
        "完整投研系统必须让每轮开发后自动跑测试、验收、报告和任务派发，减少人工在 Hermes 与 ChatGPT 之间搬运。",
        ("commands/factor_lab/leader/acceptance.py", "commands/hermes_cli.py", ".github/workflows/hermes-research-ci.yml", "commands/scripts/run_hermes_ci.sh"),
        (
            "新增 leader:accept --full-tests，运行 smoke、artifact checks、安全扫描和 pytest -q。",
            "生成 /mnt/d/HermesReports/leader_acceptance/<run_id>/ acceptance.json、acceptance_report.md、audit.jsonl、manifest.json。",
            "新增 GitHub Actions workflow 或本地等价脚本，按 push/PR/manual 触发。",
        ),
        (
            "leader:accept 可本地运行并生成报告。",
            "leader:accept --full-tests 可作为合并门禁。",
            "CI 失败时阻止进入 V3.1/V2.15。",
        ),
        ("cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 hermes_cli.py leader:accept --full-tests",),
    )

    task(
        "T007",
        "V3.1",
        "LLM Alpha Discovery 只生成 AlphaSpec 候选",
        "P1",
        "llm_alpha_researcher",
        "CI 和 V3.0.1 验收通过后，下一步才允许 LLM 进入 Alpha Discovery，但只能产出 AlphaSpec 候选。",
        ("commands/factor_lab/alpha/", "commands/tests/test_llm_alpha_discovery.py", "skills/research/factor-mining/SKILL.md"),
        (
            "定义 LLM AlphaSpec JSON schema 和 candidate review queue。",
            "候选必须包含 hypothesis、factor_expression、data_requirements、risk_notes、evidence。",
            "LLM 不得直接写策略配置，不得进入 paper/live。",
        ),
        (
            "非法 AlphaSpec 被拒绝入库。",
            "合法候选进入 review queue，默认 disabled。",
            "生成 prompt_audit 和候选审查报告。",
        ),
        ("cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_alpha_factory.py -q",),
    )

    task(
        "T008",
        "V3.2",
        "Alpha Evaluation 与现有回测流水线接入",
        "P1",
        "evaluation_engineer",
        "Alpha Registry 只有接入统一评估、OOS、Walk Forward 和正交性门禁后，才具备持续淘汰和晋级能力。",
        ("commands/factor_lab/alpha/evaluation_hook.py", "commands/factor_lab/core/gate.py", "commands/factor_lab/validation/", "commands/factor_lab/orthogonality/"),
        (
            "以 alpha_id 为主键生成 evaluation run。",
            "复用 IC/ICIR、相关性、行业暴露、OOS、Walk Forward。",
            "评估结果写入 Alpha Registry evaluation/，并产出 gate_report。",
        ),
        (
            "每个 Alpha 可查询最近一次评估。",
            "评估不过不得晋级 paper_ready。",
            "评估报告绑定 run_id、manifest、audit。",
        ),
        ("cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest -q",),
    )

    task(
        "T009",
        "V2.15",
        "Live Dry Run 治理链路验证",
        "P2",
        "governance_engineer",
        "在 CI 绿灯和 Alpha 评估门禁稳定后，再做实盘前 dry run，只验证链路，不执行交易。",
        ("commands/factor_lab/adaptive/", "commands/factor_lab/approval/", "commands/factor_lab/order/", "commands/tests/"),
        (
            "定义 dry-run SOP：输入、输出、门禁、失败处理、人工确认点。",
            "复用 6 gate、audit、rollback，不引入自动配置改动。",
            "输出 dry-run 报告模板和验收清单。",
        ),
        (
            "dry-run 完整产出报告。",
            "所有 gate 结果可追踪到 run_id 和 artifact manifest。",
            "失败时给出 blocker 原因，不 silent fallback。",
        ),
        ("cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 hermes_cli.py leader:accept --full-tests",),
    )

    return tasks


def _leader_safety_flags() -> dict:
    return {
        "auto_apply": False,
        "requires_human_approval": True,
        "no_live_trade": True,
        "broker_adapter_called": False,
        "miniqmt_called": False,
        "paper_config_modified": False,
        "live_config_modified": False,
        "task_generation_only": True,
    }


def _render_dispatch_markdown(inspection: dict, tasks: list[LeaderTask], out_dir: Path) -> str:
    stage = inspection["stage"]
    findings = inspection["findings"]
    rows = "\n".join(
        f"| {t.task_id} | {t.version} | {t.priority} | {t.owner_role} | {t.title} | {t.status} |"
        for t in tasks
    )
    finding_rows = "\n".join(
        f"| {f['severity']} | {f['code']} | {f['title']} | {f['recommendation']} |"
        for f in findings
    ) or "| - | - | 无阻塞 | - |"
    return f"""# Hermes Alpha Factory Leader Dispatch

生成时间：{inspection['generated_at']}  
输出目录：`{out_dir}`

## 当前判断

- 当前阶段：**{stage['current']}**
- 下一阶段：**{stage['next_version']}**
- 判断依据：{stage['reason']}

## 路线原则

V3 不再按“新增某类因子”排版本，而是按 Alpha Factory 生命周期排版本。现有 P0/P1/P2/P3 因子方向统一挂到 V3 Alpha Factory 下面。

## 发现项

| 级别 | 代码 | 问题 | 建议 |
|------|------|------|------|
{finding_rows}

## 已派发任务

| Task | Version | Priority | Owner | Title | Status |
|------|---------|----------|-------|-------|--------|
{rows}

## 安全边界

- 不修改 paper/live 策略配置
- 不调用 broker/miniqmt/交易接口
- 不触发自动下单
- 所有任务默认 requires_human_approval=true
- Leader 只做检查、规划、派发任务文件

## 给 Hermes/Agent 的使用方式

1. 读取本目录 `tasks.json` 获取任务队列。
2. 按 `tasks/Txxx_*.md` 逐个执行。
3. 每个任务完成后写入对应开发报告、测试报告和审计记录。
4. 未通过测试不得推进下一版本。
"""


def _render_task_markdown(task: LeaderTask) -> str:
    targets = "\n".join(f"- `{p}`" for p in task.target_files)
    instructions = "\n".join(f"{i+1}. {line}" for i, line in enumerate(task.instructions))
    acceptance = "\n".join(f"- [ ] {line}" for line in task.acceptance)
    tests = "\n".join(f"```bash\n{cmd}\n```" for cmd in task.test_commands)
    safety = "\n".join(f"- {k}: `{v}`" for k, v in task.safety.items())
    return f"""# {task.task_id} — {task.title}

- Version: **{task.version}**
- Priority: **{task.priority}**
- Owner Role: **{task.owner_role}**
- Status: **{task.status}**

## 背景

{task.rationale}

## 目标文件/目录

{targets}

## 执行指令

{instructions}

## 验收标准

{acceptance}

## 测试命令

{tests}

## 安全边界

{safety}
"""


def _json(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now(CST).isoformat()


def _slug(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return text[:80] or "task"
