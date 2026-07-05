# T003 — Scheduler entrypoints

- Version: V2.16
- Priority: P0
- Owner: automation_engineer
- Status: pending

## 目标

把 Leader loop 与 agent-runner 接成可启动、可停止、可诊断的 WSL/Windows 定时入口。

## 要求

新增脚本：

```text
commands/scripts/run_hermes_leader_loop.sh
commands/scripts/run_hermes_agent_runner.sh
commands/scripts/windows/register_hermes_automation_tasks.ps1
commands/scripts/windows/unregister_hermes_automation_tasks.ps1
```

脚本必须：

1. 使用 `/home/ly/.hermes/research-assistant/commands` 作为工作目录。
2. 使用 `../.venv_quant/bin/python3 hermes_cli.py ...`。
3. 默认 agent-runner backend 不得使用 codex。
4. 日志写入 `logs/automation/`。
5. 支持 dry-run 注册说明，不强制创建 Windows 任务。

## 验收标准

- shell 脚本语法正确。
- PowerShell 脚本只生成/注册定时任务，不包含敏感 token。
- 默认 backend 为 claude 或 command，不是 codex。
- 文档说明如何启动/停止。

## 安全边界

自动化只允许运行 research/dry_run/acceptance/test 阶段。遇到 live/broker/capital/real execution 必须 blocked。
