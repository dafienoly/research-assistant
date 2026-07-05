# T001 — Clear ad-hoc verification state

- Version: V2.16
- Priority: P0
- Owner: automation_engineer
- Status: pending

## 背景

当前 `latest_completion.json` 是 `live_broker` unsafe verification 留下的 blocked 状态。它证明安全门禁有效，但不应该阻断正式投研系统开发主线。

## 目标

建立正式的 verification state 清理/归档机制，避免测试 completion 影响后台 Leader 主循环。

## 要求

1. 增加命令或函数，把 ad-hoc verification completion 归档到：
   `/home/ly/.hermes/research-assistant/agent_tasks/completion_archive/`
2. 清理后写入正式开发主线 completion：
   - version: V2.15.2
   - stage: automation_baseline_ready
   - status: completed
   - remaining_tasks: []
   - next_question: start V2.16 Automation Baseline Hardening
3. 不删除原始验证文件，必须可追溯。
4. 增加测试覆盖 blocked verification 不应永久阻断 safe roadmap。

## 验收标准

- unsafe verification 被归档。
- latest_completion.json 回到 safe completed 状态。
- leader:loop-once 不再因为测试态 blocked 停住。
- GitHub 不提交运行态 latest_completion.json，只提交代码/文档/测试。

## 安全边界

- 不触碰 live config。
- 不触碰 broker。
- 不真实下单。
