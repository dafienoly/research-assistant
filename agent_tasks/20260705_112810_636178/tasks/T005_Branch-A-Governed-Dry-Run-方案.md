# T005 — Branch A：Governed Dry Run 方案

- Version: **V2.15**
- Priority: **P1**
- Owner Role: **governance_engineer**
- Status: **pending**

## 背景

若用户选择 Branch A，应验证信号、门禁、报告、审计、回滚材料的完整 dry-run 闭环。

## 目标文件/目录

- `commands/factor_lab/adaptive/`
- `commands/factor_lab/approval/`
- `commands/factor_lab/order/`
- `commands/tests/`

## 执行指令

1. 定义 V2.15 dry-run SOP：输入、输出、门禁、失败处理、人工确认点。
2. 复用既有 6 gate 和 audit，不引入自动配置改动。
3. 输出 dry-run 报告模板和验收清单。

## 验收标准

- [ ] dry-run 能完整产出报告。
- [ ] 所有 gate 结果可追踪到 run_id 和 artifact manifest。
- [ ] 失败时给出 blocker 原因，不 silent fallback。

## 测试命令

```bash
cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_alpha_factory.py tests/test_validation_report_outputs.py -q
```

## 安全边界

- auto_apply: `False`
- requires_human_approval: `True`
- no_live_trade: `True`
- broker_adapter_called: `False`
- miniqmt_called: `False`
- paper_config_modified: `False`
- live_config_modified: `False`
- task_generation_only: `True`
