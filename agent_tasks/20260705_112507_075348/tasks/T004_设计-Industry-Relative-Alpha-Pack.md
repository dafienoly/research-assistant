# T004 — 设计 Industry Relative Alpha Pack

- Version: **V3.1**
- Priority: **P1**
- Owner Role: **alpha_engineer**
- Status: **pending**

## 背景

用户明确要求 P0/P1/P2/P3 因子方向挂到 V3 Alpha Factory，不再作为 V2.x 堆叠；V3.1 应从行业相对 Alpha 开始。

## 目标文件/目录

- `commands/factor_lab/alpha/`
- `commands/factor_lab/industry/`
- `commands/tests/test_industry_relative_alpha.py`

## 执行指令

1. 定义行业字段来源与缺失处理，禁止 silent fallback。
2. 生成行业相对、行业中性、行业内排序三类 AlphaSpec。
3. 所有 Alpha 只注册为 disabled，不写策略配置。

## 验收标准

- [ ] 每个 AlphaSpec 包含 universe/factor_expression/hypothesis/risk_notes/tags。
- [ ] 输出行业覆盖率、行业暴露、行业内 rank 检查报告。
- [ ] 测试覆盖缺失行业、单行业样本不足、默认 disabled。

## 测试命令

```bash
cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_industry_relative_alpha.py -q
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
