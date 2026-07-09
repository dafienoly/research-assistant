# V3.4.2 Paper Trading 持续运行 — 子代理 Spec

## 依赖：V3.4.1 (Governed Dry Run 验证了管线通畅)

## 背景

当前 `commands/factor_lab/paper/paper_trading.py` 存在 PaperTrading 框架，但：
- 只能一次性运行，不保留模拟持仓状态
- 没有持久化机制
- 没有每日自动执行
- 没有收益率跟踪

## 修改文件

### 文件1: commands/factor_lab/paper/paper_trading.py — 改造

#### 1a: 持久化状态管理

```python
"""PaperTrading 增强 — 持续运行模式"""

class StandingPaperTrading:
    """持续模拟交易引擎
    
    功能：
    1. 加载上次模拟持仓状态
    2. 对比最新信号，生成增量调仓
    3. 记录模拟成交（带滑点模型）
    4. 更新持仓快照到持久化文件
    5. 计算日收益率 vs 基准
    """
    
    STATE_DIR = Path("/mnt/d/HermesData/paper_trading")
    PORTFOLIO_FILE = STATE_DIR / "portfolio.json"
    TRADES_FILE = STATE_DIR / "trades.jsonl"
    EQUITY_FILE = STATE_DIR / "equity.csv"
    
    def __init__(self, initial_capital: float = 100000,
                 slippage_bps: int = 10,
                 commission_rate: float = 0.0003,
                 stamp_tax_rate_sell: float = 0.001):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.cash = initial_capital
        self.holdings: dict[str, dict] = {}  # {symbol: {shares, avg_cost, last_price}}
        self.trade_history: list[dict] = []
        self.equity_history: list[dict] = []
        self.daily_returns: list[dict] = []
        self.slippage_bps = slippage_bps
        self.commission_rate = commission_rate
        self.stamp_tax_rate_sell = stamp_tax_rate_sell
        
        # 加载持久化状态
        self._load_state()
    
    # === 持久化 ===
    
    def _load_state(self):
        """加载持久化的组合状态"""
        if self.PORTFOLIO_FILE.exists():
            with open(self.PORTFOLIO_FILE) as f:
                data = json.load(f)
                self.capital = data.get("capital", self.initial_capital)
                self.cash = data.get("cash", self.capital)
                self.holdings = data.get("holdings", {})
        if self.EQUITY_FILE.exists():
            self.equity_history = pd.read_csv(self.EQUITY_FILE).to_dict("records")
    
    def _save_state(self):
        """持久化当前组合状态"""
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.PORTFOLIO_FILE, "w") as f:
            json.dump({
                "capital": self.capital,
                "cash": self.cash,
                "holdings": self.holdings,
                "updated_at": datetime.now(CST).isoformat(),
            }, f, indent=2, ensure_ascii=False)
    
    def _append_trade(self, trade: dict):
        """追加交易记录到 JSONL"""
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.TRADES_FILE, "a") as f:
            f.write(json.dumps(trade, ensure_ascii=False) + "\n")
    
    def _append_equity(self, date: str, total_value: float, 
                       daily_return: float, cash: float):
        """追加净值记录"""
        self.equity_history.append({
            "date": date, "total_value": round(total_value, 2),
            "daily_return": round(daily_return, 6), "cash": round(cash, 2),
        })
        df = pd.DataFrame(self.equity_history)
        df.to_csv(self.EQUITY_FILE, index=False, encoding="utf-8-sig")
    
    # === 交易模拟 ===
    
    def _calc_slippage_price(self, price: float, is_buy: bool) -> float:
        """计算滑点后的模拟成交价"""
        direction = 1 if is_buy else -1
        return price * (1 + direction * self.slippage_bps / 10000)
    
    def _calc_fee(self, amount: float, is_buy: bool) -> float:
        """计算交易费用"""
        commission = max(amount * self.commission_rate, 5.0)
        stamp = amount * self.stamp_tax_rate_sell if not is_buy else 0.0
        return commission + stamp
    
    def execute_buy(self, symbol: str, price: float, shares: int, 
                    date: str) -> dict:
        """执行模拟买入
        
        Returns:
            {"success": bool, "filled_shares": int, "fill_price": float,
             "cost": float, "reason": str}
        """
        slip_price = self._calc_slippage_price(price, is_buy=True)
        amount = shares * slip_price
        fee = self._calc_fee(amount, is_buy=True)
        total_cost = amount + fee
        
        if total_cost > self.cash:
            # 现金不足时按最大可买股数
            max_shares = int((self.cash - 5) / (slip_price * 100)) * 100
            if max_shares < 100:
                return {"success": False, "filled_shares": 0, 
                        "fill_price": slip_price, "cost": 0,
                        "reason": "现金不足"}
            shares = max_shares
            amount = shares * slip_price
            total_cost = amount + fee
        
        # 记录持仓
        if symbol in self.holdings:
            old = self.holdings[symbol]
            total_shares = old["shares"] + shares
            total_cost_basis = old["shares"] * old["avg_cost"] + amount
            self.holdings[symbol] = {
                "shares": total_shares,
                "avg_cost": round(total_cost_basis / total_shares, 4),
                "last_price": slip_price,
            }
        else:
            self.holdings[symbol] = {
                "shares": shares, "avg_cost": round(slip_price, 4),
                "last_price": slip_price,
            }
        
        self.cash -= total_cost
        
        trade = {
            "date": date, "symbol": symbol, "side": "buy",
            "shares": shares, "price": round(slip_price, 2),
            "amount": round(amount, 2), "fee": round(fee, 2),
            "total_cost": round(total_cost, 2),
        }
        self.trade_history.append(trade)
        self._append_trade(trade)
        self._save_state()
        
        return {"success": True, "filled_shares": shares, 
                "fill_price": slip_price, "cost": total_cost, "reason": ""}
    
    def execute_sell(self, symbol: str, price: float, shares: int,
                      date: str) -> dict:
        """执行模拟卖出"""
        if symbol not in self.holdings:
            return {"success": False, "filled_shares": 0,
                    "reason": "未持仓"}
        
        actual_shares = min(shares, self.holdings[symbol]["shares"])
        slip_price = self._calc_slippage_price(price, is_buy=False)
        amount = actual_shares * slip_price
        fee = self._calc_fee(amount, is_buy=False)
        net_proceed = amount - fee
        
        self.cash += net_proceed
        self.holdings[symbol]["shares"] -= actual_shares
        if self.holdings[symbol]["shares"] <= 0:
            del self.holdings[symbol]
        
        trade = {
            "date": date, "symbol": symbol, "side": "sell",
            "shares": actual_shares, "price": round(slip_price, 2),
            "amount": round(amount, 2), "fee": round(fee, 2),
            "net_proceed": round(net_proceed, 2),
        }
        self.trade_history.append(trade)
        self._append_trade(trade)
        self._save_state()
        
        return {"success": True, "filled_shares": actual_shares,
                "fill_price": slip_price, "net_proceed": net_proceed}
    
    # === 每日流程 ===
    
    def daily_process(self, signal: dict, prices: dict, date: str) -> dict:
        """每日模拟交易流程
        
        Args:
            signal: {signal_date, candidates: [{symbol, rank}, ...], ...}
            prices: {symbol: current_price}
            date: 当前日期 YYYY-MM-DD
            
        Returns:
            {"orders": [...], "pnl": {...}, "summary": {...}}
        """
        target_symbols = [c["symbol"] for c in signal.get("candidates", [])
                         if c.get("rank", 999) <= (signal.get("top_n", 10))]
        
        orders = []
        
        # 卖出不在目标中的持仓
        for sym in list(self.holdings.keys()):
            if sym not in target_symbols:
                price = prices.get(sym, self.holdings[sym].get("last_price", 0))
                if price > 0:
                    r = self.execute_sell(sym, price, 
                        self.holdings[sym]["shares"], date)
                    orders.append(r)
        
        # 买入目标中未持仓的股票
        total_buy_budget = self.cash * 0.9
        per_stock_budget = total_buy_budget / max(len(target_symbols), 1)
        
        for sym in target_symbols:
            if sym not in self.holdings:
                price = prices.get(sym, 0)
                if price <= 0:
                    continue
                shares = int(per_stock_budget / (price * 100)) * 100
                if shares >= 100:
                    r = self.execute_buy(sym, price, shares, date)
                    orders.append(r)
        
        # 计算日收益
        total_value = self.cash + sum(
            h["shares"] * prices.get(sym, h.get("last_price", 0))
            for sym, h in self.holdings.items()
        )
        prev_value = self.equity_history[-1]["total_value"] if self.equity_history else self.initial_capital
        daily_return = (total_value - prev_value) / prev_value if prev_value > 0 else 0
        
        self._append_equity(date, total_value, daily_return, self.cash)
        
        # 计算累计收益
        total_return = (total_value - self.initial_capital) / self.initial_capital * 100
        
        return {
            "orders": orders,
            "pnl": {
                "total_value": round(total_value, 2),
                "daily_return_pct": round(daily_return * 100, 4),
                "total_return_pct": round(total_return, 2),
                "cash_ratio": round(self.cash / total_value * 100, 1),
            },
            "summary": {
                "holdings": len(self.holdings),
                "trades_today": len(orders),
                "cash": round(self.cash, 2),
            }
        }
    
    def get_equity_curve(self) -> pd.DataFrame:
        """返回净值曲线"""
        return pd.DataFrame(self.equity_history)
    
    def get_total_return_pct(self) -> float:
        """返回累计收益率"""
        if not self.equity_history:
            return 0.0
        latest = self.equity_history[-1]["total_value"]
        return (latest - self.initial_capital) / self.initial_capital * 100
```

#### 1b: report 生成方法

```python
    def generate_report(self, benchmark_returns: pd.Series = None) -> str:
        """生成模拟交易 HTML 报告
        
        Args:
            benchmark_returns: 基准收益率序列（可选）
            
        Returns:
            HTML 报告内容
        """
        # ... 生成 HTML 报告，包含净值曲线、持仓分布、交易记录
```

### 文件2: CLI 入口

在 `commands/factor_lab/paper/paper_trading.py` 末尾添加（或 `factor_commands.py` 中）：

```python
cli_entry = """
hermes factor:paper-trade-standing 
        --date 2026-07-08 
        --signal /mnt/d/HermesReports/premarket/20260708/premarket_signal.json
        --prices /mnt/d/HermesData/market/live_snapshot.csv
"""
```

在 `factor_commands.py` 添加：

```python
@cli.command("paper-trade-standing")
@click.option("--date", required=True)
@click.option("--signal", default=None, help="盘前信号 JSON 路径")
@click.option("--prices", default=None, help="实时价格 CSV 路径")
@click.option("--report", is_flag=True, default=True, help="生成报告")
def cmd_paper_trade_standing(date, signal, prices, report):
    """执行每日模拟交易"""
    from factor_lab.paper.paper_trading import StandingPaperTrading
    engine = StandingPaperTrading()
    # ... 加载信号和价格 ...
    result = engine.daily_process(signal_data, price_data, date)
    click.echo(f"收益率: {result['pnl']['daily_return_pct']:.2f}%")
    click.echo(f"持仓: {result['summary']['holdings']} 只")
    click.echo(f"现金: {result['summary']['cash']:.0f}")
```

### 文件3: cron 任务设置

```bash
# 每日 09:10 执行 paper trading（盘前信号已生成后）
hermes cron action=create schedule="10 9 * * 1-5" \
    name="paper-trading-daily" \
    prompt="执行 paper trading: hermes factor:paper-trade-standing --date $(date +%%Y-%%m-%%d) --report" \
    deliver=origin
```

## 数据处理

输入信号格式（来自 premaket_signal.json）：
```json
{
  "signal_date": "2026-07-08",
  "strategy_name": "Ret5Ma20Gate",
  "top_n": 10,
  "candidates": [
    {"symbol": "688012", "name": "中微公司", "rank": 1, ...},
    ...
  ]
}
```

输入价格格式（来自 live_snapshot.csv）：
```csv
symbol,price,change_pct
688012,158.3,-1.2
...
```

## 注意事项

1. **不下真实订单**：所有交易都是模拟，不调用任何 broker/券商接口
2. **滑点模型**：买入+10bps, 卖出-10bps（偏保守），模拟实际交易成本
3. **状态持久化**：持仓/现金/交易记录都写入 `/mnt/d/HermesData/paper_trading/`，进程重启不丢失
4. **首次运行时**：如果持久化文件不存在，从初始资金 10 万开始
5. 不修改 paper_trading.py 现有类的接口（新增 StandingPaperTrading 类，保持向后兼容）

## 验收标准

```python
# 测试持久化和恢复
import tempfile, os
engine = StandingPaperTrading(initial_capital=100000)

# 执行模拟买入
r = engine.execute_buy("688012", 150.0, 200, "2026-07-08")
assert r["success"], f"买入失败: {r.get('reason', '')}"
print(f"买入: {r['filled_shares']}股, 均价{r['fill_price']}")

# 验证持久化
assert StandingPaperTrading.PORTFOLIO_FILE.exists()
with open(StandingPaperTrading.PORTFOLIO_FILE) as f:
    state = json.load(f)
assert "688012" in state.get("holdings", {})

# 恢复测试
engine2 = StandingPaperTrading(initial_capital=100000)
assert "688012" in engine2.holdings, "恢复后应仍有持仓"
print(f"恢复后持仓: {engine2.holdings['688012']}")

# 日流程测试
result = engine2.daily_process(
    signal={"signal_date": "2026-07-09", "candidates": [], "top_n": 10},
    prices={"688012": 155.0},
    date="2026-07-09",
)
print(f"日收益率: {result['pnl']['daily_return_pct']:.2f}%")
assert "pnl" in result

# 清空测试数据
print("✅ Paper trading 持续运行测试通过")
```
