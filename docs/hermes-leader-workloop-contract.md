# Hermes ↔ Leader 自动工作循环契约

更新时间：2026-07-05

## 目标

让 Hermes 和 Leader 不再依赖用户在 ChatGPT 与 Hermes 之间手动复制粘贴状态，实现：

```text
Leader 派发任务 → Hermes 执行任务 → Hermes 写 completion → Leader 读取 completion → Leader 派发下一轮任务
```

## 当前状态判断

当前已有：

1. `agent_tasks/<run_id>/tasks.json`
2. `agent_tasks/<run_id>/leader_dispatch_plan.md`
3. `agent_tasks/latest.json` 规划中
4. Hermes 可人工读取任务包并执行

当前缺口：

1. Hermes 完成任务后尚未稳定写入统一 completion 文件。
2. Leader 尚未稳定支持 `--from-latest-completion`。
3. 没有一个常驻/定时 loop 自动串起 Hermes 与 Leader。
4. 没有任务锁，可能重复派发或重复消费。

所以当前还不是 fully automatic，只是 semi-automatic。

## 最小自动化闭环

### 1. Leader 输出当前任务

Leader 每次派发后必须写：

```text
/home/ly/.hermes/research-assistant/agent_tasks/latest.json
```

字段：

```json
{
  "run_id": "20260705_v2151_dry_run_completion",
  "path": "/home/ly/.hermes/research-assistant/agent_tasks/20260705_v2151_dry_run_completion",
  "status": "pending",
  "current": "V2.15 functional_complete_partial",
  "next": "V2.15.1 dry_run_completion",
  "task_count": 4,
  "updated_at": "2026-07-05T00:00:00+08:00"
}
```

### 2. Hermes 消费任务

Hermes 读取：

```text
/home/ly/.hermes/research-assistant/agent_tasks/latest.json
```

然后打开 `path/tasks.json`，按 priority 执行任务。

执行中写：

```text
/home/ly/.hermes/research-assistant/agent_tasks/current_run.lock
```

避免重复执行。

### 3. Hermes 写完成信号

每轮完成后必须写：

```text
/home/ly/.hermes/research-assistant/agent_tasks/latest_completion.json
```

字段：

```json
{
  "source": "hermes",
  "version": "V2.15.1",
  "stage": "dry_run_completion",
  "status": "completed",
  "report_dir": "/mnt/d/HermesReports/dry_run/<run_id>/",
  "summary": {
    "passed": 6,
    "failed": 0,
    "skeleton": 0
  },
  "completed_tasks": ["T001", "T002", "T003", "T004"],
  "remaining_tasks": [],
  "next_question": "是否进入 V2.15.2 full dry-run acceptance 或 V3.1 LLM Alpha Discovery？",
  "generated_at": "2026-07-05T00:00:00+08:00"
}
```

状态枚举：

- `completed`
- `partial`
- `failed`
- `blocked`

### 4. Leader 读取完成信号

Leader 必须支持：

```bash
hermes leader:dispatch --from-latest-completion
```

行为：

1. 读取 `latest_completion.json`。
2. 如果 `status=completed`：根据 `next_question` 和 roadmap 派发下一阶段。
3. 如果 `status=partial`：只派发剩余缺口，不跳阶段。
4. 如果 `status=failed` 或 `blocked`：派发 bugfix/remediation 任务。
5. 写新的 `agent_tasks/<run_id>/tasks.json` 和 `agent_tasks/latest.json`。

### 5. 自动循环入口

推荐先做本地定时轮询，不直接做长驻守护进程。

Windows schtasks 或 cron 每 3-5 分钟运行一次：

```bash
cd /home/ly/.hermes/research-assistant/commands
/home/ly/.hermes/research-assistant/.venv_quant/bin/python3 hermes_cli.py leader:dispatch --from-latest-completion
```

Hermes 自己也应有一个消费任务命令，例如：

```bash
hermes leader:consume-latest-task
```

或：

```bash
hermes agent:run-latest-task
```

## 推荐先实现顺序

1. `latest_completion.json` schema。
2. `leader:dispatch --from-latest-completion`。
3. `agent_tasks/latest.json` 稳定更新。
4. `current_run.lock` 防重复。
5. Windows schtasks 定时触发 Leader。
6. Hermes 消费 latest task 的命令。
7. 企业微信只发状态摘要，不承载完整任务内容。

## 安全约束

1. 自动循环只允许派发和执行 research/dry-run/acceptance 任务。
2. 自动循环不得进入真实下单。
3. 自动循环不得修改 live config。
4. paper config 修改也必须 human approval。
5. 如果任务涉及 V2.15/V4.0/live，必须停在人工确认点。

## 当前 V2.15.1 决策

Hermes 已完成 V2.15 Governed Dry Run，但 rebalance_diff、order_preview、approval 仍为 skeleton。

下一步必须先执行：

```text
V2.15.1 dry_run_completion
```

不要直接进入 V3.1。
