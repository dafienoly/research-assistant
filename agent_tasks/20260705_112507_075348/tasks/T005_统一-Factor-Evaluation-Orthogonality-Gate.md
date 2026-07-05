# T005 — 统一 Factor Evaluation & Orthogonality Gate

- Version: **V3.2**
- Priority: **P2**
- Owner Role: **evaluation_engineer**
- Status: **pending**

## 背景

V3.2 需要把 IC/ICIR/相关性/行业暴露/OOS/Walk Forward 收束到统一评估门禁。

## 目标文件/目录

- `commands/factor_lab/alpha/evaluation_hook.py`
- `commands/factor_lab/core/gate.py`
- `commands/factor_lab/orthogonality/`

## 执行指令

1. 以 alpha_id 为主键生成 evaluation plan/run context。
2. 评估输出必须接入 manifest/audit，并可作为 GateEngine 输入。
3. 报告区分 blocker/warning/info，不因缺数据给 pass。

## 验收标准

- [ ] 同一 Alpha 可追踪每次 evaluation run。
- [ ] 高相关冗余 Alpha 被标记为 warning/blocker。
- [ ] Walk Forward/OOS 不通过时不得晋级 paper_ready。

## 测试命令

```bash
cd /home/ly/.hermes/research-assistant/commands && ../.venv_quant/bin/python3 -m pytest tests/test_alpha_factory.py tests/test_factor_correlation_composite.py -q
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
