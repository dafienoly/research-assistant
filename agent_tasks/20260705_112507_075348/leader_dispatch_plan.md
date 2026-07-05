# Hermes Alpha Factory Leader Dispatch

生成时间：2026-07-05T11:25:07.075257+08:00  
输出目录：`/home/ly/.hermes/research-assistant/agent_tasks/20260705_112507_075348`

## 当前判断

- 当前阶段：**V3.0.1**
- 下一阶段：**V3.1**
- 判断依据：现有因子目录已基本纳入 Alpha Registry，可进入行业相对 Alpha Pack。

## 路线原则

V3 不再按“新增某类因子”排版本，而是按 Alpha Factory 生命周期排版本。现有 P0/P1/P2/P3 因子方向统一挂到 V3 Alpha Factory 下面。

## 发现项

| 级别 | 代码 | 问题 | 建议 |
|------|------|------|------|
| - | - | 无阻塞 | - |

## 已派发任务

| Task | Version | Priority | Owner | Title | Status |
|------|---------|----------|-------|-------|--------|
| T004 | V3.1 | P1 | alpha_engineer | 设计 Industry Relative Alpha Pack | pending |
| T005 | V3.2 | P2 | evaluation_engineer | 统一 Factor Evaluation & Orthogonality Gate | pending |
| T006 | V3.7 | P3 | llm_alpha_researcher | 约束 LLM Alpha Discovery 只生成 AlphaSpec | pending |

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
