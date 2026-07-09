# 因子库报告

> **生成时间**: 2026-07-08 23:40 CST
> **审计依据**: 因子注册表 (factor_commands.py), 因子验证报告, 半导体审计报告
> **因子范畴**: 142 个注册因子

---

## 1. 因子分类总览

| 类别 | 因子数量 | 占比 | 示例 | 状态 |
|------|---------|------|------|------|
| 动量因子 | 6 | ~4% | ret5/10/20/60, max_high60, min_low60 | ✅ 基础 |
| 趋势因子 | 7 | ~5% | close_gt_ma5/10/20/60, ma5_gt_ma20/60 | ✅ 基础 |
| 波动率因子 | 6 | ~4% | volatility20/60, atr20, boll_width | ✅ 基础 |
| 反转因子 | 5 | ~4% | reversal5/20 | ✅ 基础 |
| 量价突破因子 | 12 | ~8% | 成交量/K线形态组合 | ✅ 基础 |
| 技术形态因子 | 12 | ~8% | MACD, KDJ, Bollinger, 金叉死叉 | ✅ 基础 |
| 流动性因子 | 7 | ~5% | amihud, turnover | ✅ 基础 |
| ret5_penalty 族 | 5 | ~4% | ret5 衍生/门控 | ✅ 基础 |
| **价量小计** | **~60** | **~42%** | — | — |
| **复合/衍生价量** | **~60** | **~42%** | 价量组合 | ⚠️ 实验性 |
| 估值因子 | 4 | ~3% | pe_ttm_inv, pb_lf_inv, ps_ttm_inv, ep | ⚠️ 可用但未验证 |
| 质量因子 | 4 | ~3% | roe_q, gross_margin_q, net_margin_q, debt_ratio_q | ❌ IC 为负 |
| 成长因子 | 2 | ~1% | revenue_growth_q, profit_growth_q | ⚠️ 实验性 |
| 资金因子 | 9 | ~6% | 主力/超大单/小单/分化 | ⚠️ 可用 |
| 北向因子 | 3 | ~2% | 净流入/持仓/比例 | ✅ 基础 |
| 两融因子 | 3 | ~2% | 融资买入/余额/融券 | ⚠️ 可用 |
| 事件因子 | 1 | <1% | 解禁/回购/业绩预告 | ⚠️ 可用 |
| 情绪因子 | 3 | ~2% | 新闻情感评分 | ⚠️ 实验性 |
| **非价量小计** | **~29** | **~20%** | — | — |

**总因子: ~142 (含 LLM 候选进化因子)**

---

## 2. 因子代码位置

| 模块 | 路径 | 功能 |
|------|------|------|
| 因子注册表 | `commands/factor_commands.py` | 因子元数据/分类/参数 |
| 因子基础 | `commands/factor_lab/factor_base.py` | 因子计算基类 |
| 因子进化 | `commands/factor_lab/evolution.py` | LLM 生成候选因子 (价量模板) |
| LLM Alpha 发现 | `commands/factor_lab/alpha/llm_alpha_discovery.py` | LLM 产业假设→因子 |
| 因子验证 V3 | `commands/factor_lab/alpha/` 相关 | IC/IR/Walk-forward |
| 因子验证 V4 | `commands/factor_lab/validate_v4.py` | 同池基准验证 |
| 因子评价 V4.4 | `commands/factor_lab/validate_factor_v4.py` | 增强指标/成本/风险 |
| 半导体事件因子 | `commands/factor_lab/semiconductor_events.py` | 事件因子提取 |
| 风险暴露 | `commands/factor_lab/risk_exposure.py` | 风险归因分析 |

---

## 3. 因子验证状态

### 3.1 V3 验证结果 (来自审计报告)

**验证通过的因子** (IC 正且 Walk-forward 通过):

| 因子 | IC | 说明 |
|------|----|------|
| volatility20 | 正 | 20日波动率选股 |
| vol_ratio60 | 正 | 60日量比 |
| ret5 | 正 | 5日动量 |
| ... | ... | (审计报告未列出完整 list) |

**验证未通过的因子**:

| 因子 | IC | 说明 |
|------|----|------|
| roe_q | -0.016 | IC 为负 |
| gross_margin_q | -0.016 | IC 为负, Walk-forward 未通过 |

### 3.2 V4 晋级判定 (新增)

因子需满足:
- `beats_semiconductor_peer = True` (跑赢半导体核心池等权)
- 或 `beats_core_peer = True` (跑赢核心池等权)

**注意**: 由于 daily_kline 数据仅覆盖 ~6 只标的, 实际 V4 验证的可信度受数据限制。

---

## 4. 因子 CLI 命令

```bash
# 列出所有因子 (按分类)
python3 hermes_cli.py factor:list
python3 hermes_cli.py factor:list momentum

# 单因子验证
python3 hermes_cli.py factor:validate --factor ret5
python3 hermes_cli.py factor:validate-v4 --factor ret5

# 批量验证
python3 hermes_cli.py factor:batch --factors ret5,vol_ratio60

# 风险归因
python3 hermes_cli.py factor:risk-attribution --factor ret5

# 因子进化 (LLM 生成新候选)
python3 hermes_cli.py factor:evolve

# 因子挖掘
python3 hermes_cli.py factor:mine 20

# 因子组合
python3 hermes_cli.py factor:composites

# 因子正交性
python3 hermes_cli.py factor:orthogonality
```

---

## 5. V4.5 半导体专属因子库 — 未建立

**当前缺失的半导体专属因子类别**:

| 因子类别 | 是否存在 | 优先级 | 说明 |
|---------|---------|--------|------|
| 产业链位置标签因子 | ❌ | P0 | 设备/材料/设计/封测/EDA/IP 分类 |
| 细分方向轮动因子 | ❌ | P0 | 设备 vs 材料 vs 设计 轮动信号 |
| ETF 资金映射因子 | ❌ | P1 | 半导体ETF资金流→个股映射 |
| 主题择时因子 | ❌ | P0 | 半导体/全A相对强度、成交额占比 |
| 国产替代程度因子 | ❌ | P1 | 国产化率/替代进展 |
| 海外映射因子 | ❌ | P1 | 费城半导体/台积电/英伟达映射 |
| 政策催化因子 | ❌ | P1 | 大基金/减免税/出口管制 |
| 库存周期因子 | ❌ | P2 | 半导体库存周期位置 |

**现状说明**: V4.5 未实际实现。当前所有因子仍以价量为基础，没有产业链位置感知的因子。

---

## 6. 关键验证清单

| 检查项 | 状态 | 证据 |
|-------|------|------|
| 因子必须跑赢同池才可晋级 | ✅ | `validate_v4.py:promotion_eligible` = beats_semiconductor_peer OR beats_core_peer |
| 因子类别覆盖价量+基本面+资金 | ⚠️ | 价量 ~85%, 基本面 4 个且 IC 为负 |
| 半导体专属因子存在 | ❌ | V4.5 未实现 |
| LLM 不是纯价量公式生成器 | ❌ | evolution.py 仅 6 个价量模板, llm_alpha_discovery prompt 仅 8 个价量字段 |
| 因子注册表与验证联动 | ⚠️ | alpha:list/register/retire 存在, 但未与验证结果自动联动 |

---

## 7. 已知限制

1. **因子严重偏价量**: ~85% 为价量技术指标变体
2. **基本面因子验证失败**: ROE/毛利率 IC 为负 (可能因数据不足)
3. **LLM 因子生成受限**: Available Data Fields 仅 close/open/high/low/volume/amount/returns/vwap 8 个字段
4. **V4.5 半导体专属因子未实现**: 无产业链/主题择时/海外映射因子
5. **因子验证受数据限制**: 仅 ~6 只标的的 1 年数据, 结论不可靠
6. **无因子衰减监控**: 无 IC decay tracking, 无因子拥挤度
7. **因子自动晋级/退役流程缺失**: alpha register/retire 命令存在但未与验证结果联动
