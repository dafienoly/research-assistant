# Hermes Agent Runner 非 Codex 后端方案

背景：Codex 额度不足时，后台执行器不要绑定 Codex。

推荐方案：把 agent-runner 改成可插拔后端，默认使用本地 Claude Code CLI。用户当前 WSL 中 `claude` 已安装，并且通常可通过 ccswitch/OpenCodeGo/DeepSeek 链路转发。

## 推荐命令形态

```bash
cd /home/ly/.hermes/research-assistant/commands
../.venv_quant/bin/python3 hermes_cli.py leader:agent-runner --once --backend claude
```

持续轮询：

```bash
../.venv_quant/bin/python3 hermes_cli.py leader:agent-runner --watch --interval 180 --backend claude
```

## 后端优先级

1. `claude`：默认后端，使用 Claude Code `--print` 非交互执行，走本地模型路由。
2. `command`：自定义命令模板，用环境变量 `HERMES_AGENT_COMMAND` 指定。
3. `dry-run`：只生成 prompt，不调用模型，用于验收。
4. `codex`：仅作为可选备用，不作为默认。

## command 后端示例

```bash
export HERMES_AGENT_COMMAND='claude --print --add-dir /home/ly/.hermes/research-assistant < {prompt_file}'
../.venv_quant/bin/python3 hermes_cli.py leader:agent-runner --once --backend command
```

## 任务输入

agent-runner 读取：

```text
/home/ly/.hermes/research-assistant/agent_tasks/latest.json
```

然后读取：

```text
<latest.path>/tasks/*.md
```

## 输出

每次运行写：

```text
/home/ly/.hermes/research-assistant/agent_tasks/latest_completion.json
/home/ly/.hermes/research-assistant/agent_tasks/agent_runner_logs/<run_id>/
```

## 安全边界

自动执行只允许 research / dry_run / acceptance / test 类任务。涉及实盘、资金、生产配置、人工审批的任务必须写 blocked。

## Hermes 需要实现的改动

1. `agent_runner.py` 增加 `--backend claude|command|dry-run|codex`。
2. 默认 backend 改为 `claude`。
3. Codex 后端保留但不默认使用。
4. `leader:agent-runner --once/--watch` 支持 `--backend` 参数。
5. 测试覆盖 dry-run 和 command 后端，不消耗模型额度。
