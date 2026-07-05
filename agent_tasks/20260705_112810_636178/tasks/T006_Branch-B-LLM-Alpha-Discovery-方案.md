# T006 — Branch B：LLM Alpha Discovery 方案

- Version: **V3.1**
- Priority: **P1**
- Owner Role: **llm_alpha_researcher**
- Status: **pending**

## 背景

LLM 后续应生成 AlphaSpec 候选，而不是直接写策略或下单逻辑。

## 目标文件/目录

- `skills/research/factor-mining/SKILL.md`
- `commands/factor_lab/alpha/`
- `research_outputs/strategy_review_material/`

## 执行指令

1. 补充 LLM 生成 AlphaSpec 的 JSON schema 与审查队列。
2. 候选必须包含 hypothesis/evidence/risk_notes/data_requirements。
3. 禁止 LLM 直接生成 live/paper 策略配置补丁。

## 验收标准

- [ ] LLM 输出非法字段时拒绝入库。
- [ ] 所有候选进入 manual review queue。
- [ ] 审查通过后才 register_alpha，且默认 disabled。

## 测试命令

```bash
cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_alpha_factory.py -q
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
