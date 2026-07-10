# T001 — Resolve dirty tree and streaming runner patch
- Version: V3.0.1
- Priority: P0
- Owner: hermes_auto_developer
- Status: pending

## 背景
当前 Hermes 项目是 `/home/ly/.hermes/research-assistant`。不要读取、修改或依赖 `~/Repo/quant-trading-agent`，该项目已暂停。

Dashboard 修复已完成并已有 commit:

- `3068be5 fix: stream accurate Hermes agent output in dashboard`

但当前工作区仍可能存在未提交修改：

- `commands/factor_lab/leader/agent_runner.py`
- `commands/factor_lab/leader/dashboard.py`
- `commands/tests/test_leader_dashboard.py`

其中 `agent_runner.py` 的未提交改动可能是把 Claude/command backend 从 `subprocess.run(..., capture_output=True)` 改为 `subprocess.Popen` 实时 flush 到 `agent_logs/*.log`，用于让 Dashboard SSE 真正看到 Claude Code 的运行中输出。

## 任务
1. 检查当前 `git status --short` 和 `git diff`。
2. 判断未提交改动是否应该保留：
   - 如果是必要的实时输出修复，整理成最小、可测试、可维护的补丁。
   - 如果已被 `3068be5` 或后续提交覆盖，安全回滚无效残留。
3. 不要混入 unrelated 改动。
4. 如保留补丁，提交为独立 commit，建议信息：
   - `fix: stream Claude backend output during agent runner execution`
5. 更新或新增测试，覆盖：
   - Claude/command backend 不再等进程结束后才写日志。
   - 日志文件在进程运行中可被 Dashboard `/api/stream` tail 到。
   - 超时、命令不存在、非零退出码仍有清晰日志。

## 验收标准
- `git status --short` 只剩合理的任务产物，或完全 clean。
- `pytest` 相关测试通过。
- 若保留实时 runner patch，必须有独立 commit。
- 不允许修改 live/broker/real_execution 相关配置。
- 不允许触发任何真实交易、paper config apply 或 broker 操作。
