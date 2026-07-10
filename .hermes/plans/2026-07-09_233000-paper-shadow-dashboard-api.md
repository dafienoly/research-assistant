# Paper / Shadow Dashboard API 实现计划

> **V5 路线图遗留任务** — `docs/v5roadmap.md` 第 783-792 行明确规划了 `/api/paper/dashboard` 和 `/api/shadow/dashboard`，但后端 `routes_paper.py` 从未注册这两个端点。前端 `PaperDashboard.tsx` 已完整实现 UI 层，因后端缺失，页面显示全是 `—`。

**Goal:** 补上两个后端聚合端点，使 Paper / Shadow 看板显示真实数据

**Architecture:** 从现有引擎中提取数据 → 路由层做格式转换 → 按前端 TypeScript 类型返回。Paper dashboard 从 `PaperTradingService` 已有的 balance/orders/fills 聚合计算；Shadow dashboard 从 `ShadowTradingEngine.run_shadow()` 结果直接映射。

**Tech Stack:** FastAPI, PaperTradingService (单例), ShadowTradingEngine, PaperTradingV4

---

## 任务 1：PaperTradingService 增加 dashboard 聚合方法

**Objective:** 在 `PaperTradingService` 类中新增 `get_dashboard()` 方法，将已有的 orders/fills/balance 数据聚合成前端 `PaperDashboardData` 结构。

**Files:**
- Modify: `commands/factor_lab/paper_trading_service.py` (末尾新增方法)

**前置调研：**
- `PaperTradingService` 已有:
  - `get_balance()` → balance/cash/total_value
  - `get_orders(status, symbol, limit)` → 订单列表
  - `get_fills(symbol, limit)` → 成交记录
- 从 `get_orders()` 可按 status 统计 pending/completed/blocked 笔数
- 从 `get_fills()` 可得到成交笔数，用于计算 fill_rate
- Sharpe/波动率/最大回撤/胜率/年化收益 ：需要用 `np.log(returns).std()`, `np.sqrt(252) * mean/std`, 从 PnL 序列计算
- 相对半导体同池等权: 通过 `ShadowTradingEngine._calc_relative_performance()` 或直接调 `ShadowTradingEngine` 跑一遍

**具体实现：**

```python
def get_dashboard(self) -> dict:
    """聚合 Paper Dashboard 数据"""
    from datetime import datetime, timezone, timedelta
    import numpy as np
    CST = timezone(timedelta(hours=8))

    bal = self.get_balance()
    orders = self.get_orders(limit=500)
    fills = self.get_fills(limit=500)

    # 统计
    n_pending = sum(1 for o in orders if o.get("status") == "pending")
    n_completed = sum(1 for o in orders if o.get("status") in ("filled", "partial"))
    n_filled = len(fills)
    total_orders = len(orders) or 1  # 避免除零
    fill_rate = round(n_filled / total_orders * 100, 1)

    # 从 fills 提取 PnL 序列
    pnl_values = []
    for f in fills:
        pnl = f.get("pnl", 0) or 0
        pnl_values.append(pnl)

    total_pnl = bal.get("total_pnl", 0)
    initial_capital = bal.get("initial_cash", 1_000_000)
    total_return_pct = round((total_pnl / initial_capital) * 100, 2) if initial_capital else 0

    # Sharpe / 波动率 / 最大回撤 / 胜率 — 从日度 PnL 序列
    # （如果无法从 fills 提取日度序列，用保守默认值）
    sharpe = 0.0
    volatility = 0.0
    max_drawdown = 0.0
    win_rate = 0.0
    annualized_return = 0.0

    if len(pnl_values) >= 5:
        arr = np.array(pnl_values, dtype=float)
        if arr.std() > 0:
            daily_returns = arr / initial_capital
            volatility = round(float(arr.std()) * 100, 2)
            sharpe = round(float(daily_returns.mean() / daily_returns.std() * np.sqrt(252)), 2) if daily_returns.std() > 0 else 0
            annualized_return = round(float(daily_returns.mean() * 252 * 100), 2)
            # 最大回撤
            cum = np.cumprod(1 + daily_returns)
            peak = np.maximum.accumulate(cum)
            dd = (cum - peak) / peak
            max_drawdown = round(float(np.min(dd)) * 100, 2)
            # 胜率
            wins = int((arr > 0).sum())
            win_rate = round(wins / len(arr) * 100, 1)

    # 运行天数
    from factor_lab.paper_trading_service import PaperAccount
    created = bal.get("created_at", "")
    n_trading_days = 1
    if created:
        try:
            start = datetime.fromisoformat(created)
            n_trading_days = max(1, (datetime.now(CST) - start).days)
        except Exception:
            pass

    return {
        "period": f"近{n_trading_days}天",
        "n_trading_days": n_trading_days,
        "n_pending": n_pending,
        "n_completed": n_completed,
        "paper_total_return_pct": total_return_pct,
        "paper_annualized_return_pct": annualized_return,
        "paper_volatility_pct": volatility,
        "paper_sharpe": sharpe,
        "paper_max_drawdown_pct": max_drawdown,
        "paper_win_rate_pct": win_rate,
        "execution_quality": {
            "filled": n_filled,
            "partial_filled": n_completed - n_filled,
            "blocked": n_pending,
            "fill_rate": fill_rate,
        },
        "status": "active",
        "no_real_trade": False,
    }
```

**Dependency:** 确保 `import numpy as np` 在文件顶部或函数内导入

---

## 任务 2：注册 `/api/paper/dashboard` 端点

**Objective:** 在 `routes_paper.py` 中新增路由，调用 `PaperTradingService.get_dashboard()`。

**Files:**
- Modify: `commands/factor_lab/api_server/routes_paper.py` (在 `paper_status` 后新增)

**代码：**

```python
@router.get("/paper/dashboard")
def paper_dashboard():
    """GET /api/paper/dashboard — Paper 交易仪表盘聚合数据"""
    try:
        service = _get_service()
        dashboard = service.get_dashboard()
        return api_success(data=dashboard)
    except Exception as e:
        return api_error("PAPER_ERROR", f"获取 dashboard 失败: {type(e).__name__}", status_code=500)
```

---

## 任务 3：实现 `/api/shadow/dashboard` 端点

**Objective:** 注册路由，调用 `ShadowTradingEngine.run_shadow()` 获取当日影子交易数据并映射为前端 `ShadowDashboardData` 结构。

**Files:**
- Modify: `commands/factor_lab/api_server/routes_paper.py` (在 `shadow_status` 后新增)

**调研结果：**
- `ShadowTradingEngine.run_shadow(date)` 返回的结构与前端 `ShadowDashboardData` 高度匹配，可直接映射：
  - `return["date"]` → `ShadowDashboardData.date`
  - `return["plan"]` → `ShadowDashboardData.plan`（stocks 中的 symbol/name/direction/shares 均有）
  - `return["execution"]` → `ShadowDashboardData.execution`
  - `return["pnl"]` → `ShadowDashboardData.pnl`
  - `return["tradability"]` → `ShadowDashboardData.tradability`
  - `return["risk_interceptions"]` → `ShadowDashboardData.risk_interceptions`
  - `return["market_context"]` → `ShadowDashboardData.market_context`
  - `return["performance"]` → `ShadowDashboardData.performance`
  - `return["not_ready"]` → `ShadowDashboardData.not_ready`
  - `return["summary"]` → `ShadowDashboardData.summary`
- 无需额外聚合，直接转发

**代码：**

```python
@router.get("/shadow/dashboard")
def shadow_dashboard(
    date: str = Query("", description="交易日 YYYY-MM-DD，默认最新交易日"),
):
    """GET /api/shadow/dashboard — Shadow 交易仪表盘聚合数据"""
    try:
        from factor_lab.paper.shadow_trading import ShadowTradingEngine

        # 默认使用最近一个交易日
        target_date = date
        if not target_date:
            from datetime import datetime, timezone, timedelta
            from factor_lab.data.tushare_client import get_ts_client
            CST = timezone(timedelta(hours=8))
            tc = get_ts_client()
            cal = tc.trade_cal(start_date=(datetime.now(CST) - timedelta(days=10)).strftime("%Y%m%d"),
                               end_date=datetime.now(CST).strftime("%Y%m%d"))
            if cal:
                latest = [d for d in sorted(cal, reverse=True) if d <= datetime.now(CST).strftime("%Y%m%d")]
                target_date = latest[0] if latest else datetime.now(CST).strftime("%Y-%m-%d")
            else:
                target_date = datetime.now(CST).strftime("%Y-%m-%d")

        engine = ShadowTradingEngine(capital=50000)
        result = engine.run_shadow(target_date)
        return api_success(data=result)
    except Exception as e:
        return api_error("SHADOW_ERROR", f"获取 shadow dashboard 失败: {type(e).__name__}: {e}", status_code=500)
```

---

## 任务 4：验证

**Objective:** 确认两个端点返回数据结构匹配前端 TypeScript 类型。

**Step 1: 启动 api server**

```bash
cd /home/ly/.hermes/research-assistant/commands
python3 hermes_cli.py serve
```

**Step 2: 验证 paper/dashboard**

```bash
curl -s http://127.0.0.1:8766/api/paper/dashboard | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok'), f'not ok: {d}'
data = d.get('data', {})
required = ['period', 'n_trading_days', 'paper_total_return_pct', 'paper_sharpe', 'execution_quality']
for k in required:
    assert k in data, f'missing {k}'
print(f'✅ paper/dashboard OK — {data[\"period\"]}, Sharpe={data[\"paper_sharpe\"]}')
"
```

**Step 3: 验证 shadow/dashboard**

```bash
curl -s http://127.0.0.1:8766/api/shadow/dashboard | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok'), f'not ok: {d}'
data = d.get('data', {})
required = ['date', 'plan', 'execution', 'pnl', 'tradability', 'risk_interceptions', 'performance', 'not_ready', 'summary']
for k in required:
    assert k in data, f'missing {k}'
print(f'✅ shadow/dashboard OK — {data[\"date\"]}, summary={data[\"summary\"]}')
"
```

**Step 4: 前端验证**

```
npm run build   # 确保前端已构建
浏览器访问 http://localhost:5173/paper
检查:
  ✅ 4 张 Paper 指标卡显示真实数字（不再全是 —）
  ✅ Paper 详情卡片展开
  ✅ Shadow 区域 Tab 显示计划/成交/复盘/风控
```

---

## 验证要点

| 检查项 | 预期 |
|--------|------|
| `GET /api/paper/dashboard` | 返回 `{ok:true, data:{period, n_trading_days, …, execution_quality}}` |
| `GET /api/shadow/dashboard` | 返回 `{ok:true, data:{date, plan, execution, pnl, tradability, risk_interceptions, performance, not_ready, summary}}` |
| Paper 指标卡 | 显示运行天数/组合收益/成交率/Sharpe |
| Shadow Tab | 显示计划交易列表、模拟成交、日度复盘、风控拦截 |
| npm build | 零错误 |

## 风险和注意事项

1. **`PaperTradingService` 订单数据可能为空** — 如果从未下过模拟单，`get_orders()` 返回空列表。此时 dashboard 应返回 `n_trading_days=1`, `n_pending=0`, `n_completed=0` 等默认值，前端显示 `—` 仍属正常。
2. **`ShadowTradingEngine.run_shadow()` 耗时** — 需要拉取行情数据+因子信号组合推荐，可能 5-30s。前端应有适当加载状态。
3. **交易日判断** — `shadow/dashboard` 默认取最近交易日。如果今天不是交易日或 Tushare 数据未就绪，应优雅降级（返回空态而非崩溃）。
4. **numpy 依赖** — `PaperTradingService.get_dashboard()` 中 `import numpy as np` 需确保在文件顶部或函数内导入，避免模块级导入失败。

## 历史背景

经查 `docs/v5roadmap.md`，这两个端点在 V5 路线图中明确规划（第 783-792 行），且前端 `PaperDashboard.tsx` 在该路线图阶段已完成开发。但后端 `routes_paper.py` 对应的聚合端点从未实现——前端壳子完成后，后端"聚合层"开发任务被遗漏。属于 V5 时期**前后端不同步的遗留缺陷**，不是新增需求。
