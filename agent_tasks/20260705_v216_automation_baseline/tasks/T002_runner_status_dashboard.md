# T002 — Runner status dashboard

- Version: V2.16
- Priority: P0
- Owner: automation_engineer
- Status: pending

## 目标

新增一个轻量状态看板命令，让用户不用翻多个 JSON 文件即可看到当前自动化状态。

## 建议命令

```bash
hermes leader:status
```

## 输出内容

至少包含：

1. latest.json 当前 run_id / task_count / status / path。
2. latest_completion.json version / stage / status / remaining_tasks。
3. current_run.lock 是否 running。
4. auto_loop_state.json 最近 actions。
5. agent_runner_logs 最新目录。
6. GitHub 最近 commit hash。
7. 是否存在 unsafe blocked 状态。

## 验收标准

- `hermes leader:status` 可运行。
- 输出清晰标明：idle / pending / running / blocked / failed / completed。
- 不依赖模型，不消耗额度。
- 新增测试覆盖缺文件、blocked、pending、completed 三类状态。

## 安全边界

只读检查，不修改任何运行态。
