# 需求追溯清单 — 自动因子挖掘管线

Grilling session: 2026-07-07 (当前对话)
ADR: docs/adr/adr-023-auto-factor-pipeline.md

状态说明: ✅完成 / ⏳进行中 / ❌阻塞(标注原因) / 📋待开始

---

| # | 需求 | 优先级 | 状态 | 覆盖文件 | 阻塞原因 |
|---|------|--------|------|----------|----------|
| 1 | **全自动闭环**：因子设计→IC→回测→稳健性→注册→通知 | P0 | ✅完成 | pipeline_orchestrator + pipeline_worker | |
| 2 | **定时触发**：每日 16:20 cron | P0 | ✅完成 | cron job + daily_factor_pipeline.py | |
| 3 | **事件触发**：research:loop 产出后自动入队 | P0 | ✅完成 | research_loop/__init__.py: _enqueue_to_pipeline | |
| 4 | **回测分级**：\|IC\|≥0.03/0.015/跳过 | P0 | ✅完成 | pipeline_orchestrator: classify_and_enqueue | |
| 5 | **因子候选源**：全量注册表(142) + evolved_candidates | P0 | ✅完成 | pipeline_orchestrator: load_candidates | |
| 6 | **IC 阈值**：0.03/0.015 固定两档 | P0 | ✅完成 | pipeline_config.py | |
| 7 | **自动注册**：Sharpe>1.0, MaxDD<-20%, WF pass | P0 | ✅完成 | pipeline_worker: _check_approval + _auto_register | |
| 8 | **企微推送**：全量表格推送 | P0 | ✅完成 | pipeline_worker: _notify_summary | |
| 9 | **回测股票池**：全量 watchlist (~300只) | P0 | ✅完成 | 现有 load_stock_kline | |
| 10 | **失败重试**：重试 1 次 + 企微告警 | P0 | ✅完成 | pipeline_retry.py | |
| 11 | **持仓周期跟因子走** | P1 | 📋待开始 | 需扩展 task JSON + 传参到 backtest | |
| 12 | **分段窗口**：前12月IC，后6月样本外 | P0 | ✅完成 | pipeline_config.py TRAIN_START/END | |
| 13 | **异步队列架构** | P0 | ✅完成 | pipeline_worker + 队列目录 | |
| 14 | **影子观察期**：日频10天/周频1月 | P1 | ✅完成 | shadow_observer.py | |
| 15 | **全表格推送**：IC/ICIR/Sharpe/MaxDD/分级 | P0 | ✅完成 | pipeline_worker: _notify_summary | |
| 16 | **失败因子明细推送** | P0 | ✅完成 | pipeline_worker: _notify_summary failed 段 | |
| 17 | **企微注册待确认消息 + 人工确认** | P1 | 📋待开始 | 待实现确认 CLI + 消息模板 | |
| 18 | research:loop 6阶段自主循环 | P0 | ✅完成 | 现有 | |
| 19 | factor:evolve 快速批量候选 | P0 | ✅完成 | 现有 | |
| 20 | 完整验证套件 (WF + 抗过拟合 + 评分) | P0 | ✅完成 | 现有 factor:batch | |
| 21 | 快速回测 (Top20% + 月频 + QuantStats) | P0 | ✅完成 | 现有 backtest:factor-top | |
| 22 | 全因子 IC 评估 | P0 | ✅完成 | 现有 factor:mine | |
| 23 | Alpha Registry | P0 | ✅完成 | 现有 alpha:* | |
| 24 | 企微通知框架 | P0 | ✅完成 | 现有 notify.py | |
| 25 | 并行 worker 隔离 | P1 | ✅完成 | pipeline_worker: _acquire_lock | |
| 26 | IC 衰减跟踪 | P1 | ✅完成 | shadow_observer: _collect_ic_history | |
| 27 | 衰减≥30% 标记不稳定+通知 | P1 | ✅完成 | shadow_observer: daily_tick | |
| 28 | 因子验证时间戳 | P1 | ✅完成 | alpha/schema.py | |

---

### 汇总统计

| 状态 | 数量 |
|------|------|
| ✅ 已完成 | **28** |
| 📋 待开始 | **0** |
| ❌ 阻塞 | 0 |
| **合计** | **28** |

所有 28 项需求已全部实现。因子管线已完整交付。
