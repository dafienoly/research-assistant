## Hermes Agent (演示模式)

任务: Auto execute version V6.4: Portfolio Backtest/Benchmark

运行 dry-run...

{
  "run_id": "20260706_151803_540610",
  "generated_at": "2026-07-06T15:18:03.540627+08:00",
  "dry_run": true,
  "stage": {
    "current": "V3.0",
    "next_version": "V3.0.1",
    "reason": "Alpha Factory 底座已存在，下一步应迁移现有因子目录。",
    "next_options": [
      "V2.15 governed dry run",
      "V3.1 LLM Alpha Discovery"
    ],
    "blockers": []
  },
  "task_count": 6,
  "tasks": [
    {
      "task_id": "T003",
      "version": "V3.0.1",
      "title": "执行 Existing Factor Catalog Migration",
      "priority": "P1",
      "owner_role": "migration_engineer",
      "rationale": "现有 factor_base 注册表尚未完整映射进 Alpha Registry，V3.1 之前应先完成目录迁移。",
      "target_files": [
        "commands/factor_lab/alpha/factor_catalog_migration.py",
        "/mnt/d/HermesData/alpha_registry"
      ],
      "instructions": [
        "先运行 dry-run，检查 total/migrated/skipped/duplicates。",
        "确认无 skipped 后再运行正式迁移。",
        "迁移后抽样 alpha_spec.json，确认 enabled/paper_enabled/live_enabled 全为 false。"
      ],
      "acceptance": [
        "factor_base 所有因子都在 migrated 或 duplicate/skipped 列表中有解释。",
        "迁移输出包含 JSON/CSV/HTML/MD/manifest/audit。",
        "重复运行不重复污染 registry。"
      ],
      "test_commands": [
        "cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 hermes_cli.py alpha:migrate-existing-factors --dry-run",
        "cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_factor_catalog_migration.py -q"
      ],
      "safety": {
        "auto_apply": false,
        "requires_human_approval": true,
        "no_live_trade": true,
        "broker_adapter_called": false,
        "miniqmt_called": false,
        "paper_config_modified": false,
        "live_config_modified": false,
        "task_generation_only": true
      }
    },
    {
      "task_id": "T004",
      "version": "V3.0-acceptance",
      "title": "补强 Alpha Factory 注册入口验收",
      "priority": "P0",
      "owner_role": "alpha_foundation_reviewer",
      "rationale": "alpha:register --spec 是后续外部 AlphaSpec、LLM AlphaSpec 和批量迁移的基础入口，必须作为 V3.0 验收点。",
      "target_files": [
        "commands/hermes_cli.py",
        "commands/factor_lab/alpha/alpha_cli.py",
        "commands/tests/test_alpha_factory.py"
      ],
      "instructions": [
        "确认 hermes_cli.py 帮助列出 alpha:register --spec <path>。",
        "确认 alpha:register 只注册 AlphaSpec，不触发回测或配置修改。",
        "新增 CLI smoke test 覆盖 alpha:register、alpha:list、alpha:show、alpha:evaluation-plan。"
      ],
      "acceptance": [
        "hermes alpha:register --spec <path> 可运行。",
        "注册后的 alpha_spec.json 默认 enabled=false、paper_enabled=false、live_enabled=false。",
        "测试必须覆盖 CLI 存在性和安全默认值。"
      ],
      "test_commands": [
        "cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest -q"
      ],
      "safety": {
        "auto_apply": false,
        "requires_human_approval": true,
        "no_live_trade": true,
        "broker_adapter_called": false,
        "miniqmt_called": false,
        "paper_config_modified": false,
        "live_config_modified": false,
        "task_generation_only": true
      }
    },
    {
      "task_id": "T005",
      "version": "V3.0.1-acceptance",
      "title": "补齐 Existing Factor Catalog Migration 验收产物",
      "priority": "P0",
      "owner_role": "migration_acceptance_engineer",
      "rationale": "Hermes 已完成 88 因子迁移，但最新报告目录缺少完整验收清单中的部分产物，需要补齐后才能进入 V3.1。",
      "target_files": [
        "commands/factor_lab/alpha/factor_catalog_migration.py",
        "commands/tests/test_factor_catalog_migration.py",
        "/mnt/d/HermesReports/alpha_factor_migration/"
      ],
      "instructions": [
        "补齐 factor_alpha_mapping.csv、factor_data_requirements.csv、factor_correlation_baseline.csv、alpha_registry_update_preview.json、audit.log。",
        "migrated/skipped/duplicate 三类 CSV 即使为空也必须生成。",
        "为每个因子补 FactorSpec 或等价字段：factor_name、category、subcategory、data_requirements、risk_constraints。"
      ],
      "acceptance": [
        "V3.0.1 最新 run 目录包含完整 15 个验收文件。",
        "88 个因子全部被识别；skipped/duplicate 有明确原因。",
        "leader:accept 不再报 MIGRATION_ACCEPTANCE_GAPS。"
      ],
      "test_commands": [
        "cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 hermes_cli.py leader:accept"
      ],
      "safety": {
        "auto_apply": false,
        "requires_human_approval": true,
        "no_live_trade": true,
        "broker_adapter_called": false,
        "miniqmt_called": false,
        "paper_config_modified": false,
        "live_config_modified": false,
        "task_generation_only": true
      }
    },
    {
      "task_id": "T006",
      "version": "CI-CD",
      "title": "建立自动验收与本地 CI/CD 门禁",
      "priority": "P0",
      "owner_role": "ci_engineer",
      "rationale": "完整投研系统必须让每轮开发后自动跑测试、验收、报告和任务派发，减少人工在 Hermes 与 ChatGPT 之间搬运。",
      "target_files": [
        "commands/factor_lab/leader/acceptance.py",
        "commands/hermes_cli.py",
        ".github/workflows/hermes-research-ci.yml",
        "commands/scripts/run_hermes_ci.sh"
      ],
      "instructions": [
        "新增 leader:accept --full-tests，运行 smoke、artifact checks、安全扫描和 pytest -q。",
        "生成 /mnt/d/HermesReports/leader_acceptance/<run_id>/ acceptance.json、acceptance_report.md、audit.jsonl、manifest.json。",
        "新增 GitHub Actions workflow 或本地等价脚本，按 push/PR/manual 触发。"
      ],
      "acceptance": [
        "leader:accept 可本地运行并生成报告。",
        "leader:accept --full-tests 可作为合并门禁。",
        "CI 失败时阻止进入 V3.1/V2.15。"
      ],
      "test_commands": [
        "cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 hermes_cli.py leader:accept --full-tests"
      ],
      "safety": {
        "auto_apply": false,
        "requires_human_approval": true,
        "no_live_trade": true,
        "broker_adapter_called": false,
        "miniqmt_called": false,
        "paper_config_modified": false,
        "live_config_modified": false,
        "task_generation_only": true
      }
    },
    {
      "task_id": "T007",
      "version": "V3.1",
      "title": "LLM Alpha Discovery 只生成 AlphaSpec 候选",
      "priority": "P1",
      "owner_role": "llm_alpha_researcher",
      "rationale": "CI 和 V3.0.1 验收通过后，下一步才允许 LLM 进入 Alpha Discovery，但只能产出 AlphaSpec 候选。",
      "target_files": [
        "commands/factor_lab/alpha/",
        "commands/tests/test_llm_alpha_discovery.py",
        "skills/research/factor-mining/SKILL.md"
      ],
      "instructions": [
        "定义 LLM AlphaSpec JSON schema 和 candidate review queue。",
        "候选必须包含 hypothesis、factor_expression、data_requirements、risk_notes、evidence。",
        "LLM 不得直接写策略配置，不得进入 paper/live。"
      ],
      "acceptance": [
        "非法 AlphaSpec 被拒绝入库。",
        "合法候选进入 review queue，默认 disabled。",
        "生成 prompt_audit 和候选审查报告。"
      ],
      "test_commands": [
        "cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_alpha_factory.py -q"
      ],
      "safety": {
        "auto_apply": false,
        "requires_human_approval": true,
        "no_live_trade": true,
        "broker_adapter_called": false,
        "miniqmt_called": false,
        "paper_config_modified": false,
        "live_config_modified": false,
        "task_generation_only": true
      }
    },
    {
      "task_id": "T008",
      "version": "V3.2",
      "title": "Alpha Evaluation 与现有回测流水线接入",
      "priority": "P1",
      "owner_role": "evaluation_engineer",
      "rationale": "Alpha Registry 只有接入统一评估、OOS、Walk Forward 和正交性门禁后，才具备持续淘汰和晋级能力。",
      "target_files": [
        "commands/factor_lab/alpha/evaluation_hook.py",
        "commands/factor_lab/core/gate.py",
        "commands/factor_lab/validation/",
        "commands/factor_lab/orthogonality/"
      ],
      "instructions": [
        "以 alpha_id 为主键生成 evaluation run。",
        "复用 IC/ICIR、相关性、行业暴露、OOS、Walk Forward。",
        "评估结果写入 Alpha Registry evaluation/，并产出 gate_report。"
      ],
      "acceptance": [
        "每个 Alpha 可查询最近一次评估。",
        "评估不过不得晋级 paper_ready。",
        "评估报告绑定 run_id、manifest、audit。"
      ],
      "test_commands": [
        "cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest -q"
      ],
      "safety": {
        "auto_apply": false,
        "requires_human_approval": true,
        "no_live_trade": true,
        "broker_adapter_called": false,
        "miniqmt_called": false,
        "paper_config_modified": false,
        "live_config_modified": false,
        "task_generation_only": true
      }
    }
  ],
  "safety": {
    "auto_apply": false,
    "requires_human_approval": true,
    "no_live_trade": true,
    "broker_adapter_called": false,
    "miniqmt_called": false,
    "paper_config_modified": false,
    "live_config_modified": false,
    "task_generation_only": true
  }
}
