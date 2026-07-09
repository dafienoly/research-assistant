"""V3.4.2 StandingPaperTrading — 持续模拟交易引擎。
V4.8 PaperTradingV4 — 增强的 Paper / Shadow Trading 闭环。

功能：
1. 加载上次模拟持仓状态（持久化到 JSON）
2. 对比最新信号，生成增量调仓（卖出不在目标中的持仓，买入新目标）
3. 记录模拟成交（带滑点模型：买入+10bps, 卖出-10bps）
4. 更新持仓快照到文件
5. 计算日收益率

V4.8 新增:
  - PaperTradingV4: 从 portfolio_builder 获取组合推荐
  - 可交易性检查 (涨跌停/停牌/资金/100股整数倍)
  - 模拟成交 (按收盘价, 含手续费0.025%+印花税0.1%+滑点0.05%)
  - 执行偏差分析

持久化位置：/mnt/d/HermesData/paper_trading/
不下真实订单。买入+10bps, 卖出-10bps（保守滑点）。
进程重启不丢失状态。首次运行持久化文件不存在时自动从 initial_capital 开始。
"""

import json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any
import pandas as pd
import numpy as np
from factor_lab.order.order_preview import round_to_lot_size

CST = timezone(timedelta(hours=8))


class StandingPaperTrading:
    """持续模拟交易引擎 — 状态持久化、增量调仓、模拟成交（保守滑点+费用）、日收益率计算。"""

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
        self.holdings: dict = {}  # {symbol: {shares, avg_cost, last_price}}
        self.trade_history: list = []
        self.equity_history: list = []
        self.slippage_bps = slippage_bps
        self.commission_rate = commission_rate
        self.stamp_tax_rate_sell = stamp_tax_rate_sell
        self._load_state()

    # ── 持久化 ──────────────────────────────────────────────

    def _load_state(self):
        """从磁盘加载上次持仓状态。文件不存在时从 initial_capital 开始。"""
        if self.PORTFOLIO_FILE.exists():
            with open(self.PORTFOLIO_FILE) as f:
                data = json.load(f)
                self.capital = data.get("capital", self.initial_capital)
                self.cash = data.get("cash", self.capital)
                self.holdings = data.get("holdings", {})
        if self.EQUITY_FILE.exists():
            try:
                self.equity_history = pd.read_csv(self.EQUITY_FILE).to_dict("records")
            except Exception:
                self.equity_history = []

    def _save_state(self):
        """保存当前持仓快照到磁盘。"""
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.PORTFOLIO_FILE, "w") as f:
            json.dump({
                "capital": self.capital, "cash": self.cash,
                "holdings": self.holdings,
                "updated_at": datetime.now(CST).isoformat(),
            }, f, indent=2, ensure_ascii=False)

    def _append_trade(self, trade: dict):
        """追加一条成交记录到 trades.jsonl。"""
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.TRADES_FILE, "a") as f:
            f.write(json.dumps(trade, ensure_ascii=False) + "\n")

    def _append_equity(self, date, total_value, daily_return, cash):
        """追加日权益记录并重写 equity.csv。"""
        self.equity_history.append({
            "date": date, "total_value": round(total_value, 2),
            "daily_return": round(daily_return, 6), "cash": round(cash, 2),
        })
        pd.DataFrame(self.equity_history).to_csv(
            self.EQUITY_FILE, index=False, encoding="utf-8-sig")

    # ── 滑点和费用模型 ─────────────────────────────────────

    def _calc_slippage_price(self, price: float, is_buy: bool) -> float:
        """保守滑点模型：买入+10bps, 卖出-10bps"""
        direction = 1 if is_buy else -1
        return price * (1 + direction * self.slippage_bps / 10000)

    def _calc_fee(self, amount: float, is_buy: bool) -> float:
        """计算交易费用：佣金（最低5元）+ 卖出印花税"""
        commission = max(amount * self.commission_rate, 5.0)
        stamp = amount * self.stamp_tax_rate_sell if not is_buy else 0.0
        return commission + stamp

    # ── 交易执行 ────────────────────────────────────────────

    def execute_buy(self, symbol: str, price: float, shares: int, date: str) -> dict:
        """模拟买入，带滑点、费用、现金限制。

        支持部分成交：现金不足时降到可买手数。
        更新持仓加权平均成本。
        整手规则: shares 自动截断到 100 的整数倍。
        """
        # 强制整手规则
        shares = round_to_lot_size(shares)
        if shares <= 0:
            return {"success": False, "reason": "股数不足一手"}

        slip_price = self._calc_slippage_price(price, is_buy=True)
        amount = shares * slip_price
        fee = self._calc_fee(amount, is_buy=True)
        total_cost = amount + fee

        if total_cost > self.cash:
            # 部分成交：降到可买的手数（预留最低佣金5元）
            max_shares = int((self.cash - 5) / slip_price)
            max_shares = (max_shares // 100) * 100  # 整手截断, 不自动补到1手
            if max_shares < 100:
                return {"success": False, "reason": "现金不足"}
            shares = max_shares
            amount = shares * slip_price
            total_cost = amount + fee

        old = self.holdings.get(symbol, {"shares": 0, "avg_cost": 0})
        total_shares = old["shares"] + shares
        total_cost_basis = old["shares"] * old["avg_cost"] + amount
        self.holdings[symbol] = {
            "shares": total_shares,
            "avg_cost": round(total_cost_basis / total_shares, 4) if total_shares > 0 else 0,
            "last_price": slip_price,
        }
        self.cash -= total_cost

        trade = {"date": date, "symbol": symbol, "side": "buy",
                 "shares": shares, "price": round(slip_price, 2),
                 "amount": round(amount, 2), "fee": round(fee, 2),
                 "total_cost": round(total_cost, 2)}
        self.trade_history.append(trade)
        self._append_trade(trade)
        self._save_state()
        return {"success": True, "filled_shares": shares, "fill_price": slip_price, "cost": total_cost}

    def execute_sell(self, symbol: str, price: float, shares: int, date: str) -> dict:
        """模拟卖出，带滑点、费用、持仓检查。

        不会卖出超过持仓的数量。清仓后从 holdings 中移除该标的。
        """
        if symbol not in self.holdings or self.holdings[symbol]["shares"] <= 0:
            return {"success": False, "reason": "未持仓"}
        actual_shares = min(shares, self.holdings[symbol]["shares"])
        slip_price = self._calc_slippage_price(price, is_buy=False)
        amount = actual_shares * slip_price
        fee = self._calc_fee(amount, is_buy=False)
        net_proceed = amount - fee

        self.cash += net_proceed
        self.holdings[symbol]["shares"] -= actual_shares
        if self.holdings[symbol]["shares"] <= 0:
            del self.holdings[symbol]

        trade = {"date": date, "symbol": symbol, "side": "sell",
                 "shares": actual_shares, "price": round(slip_price, 2),
                 "amount": round(amount, 2), "fee": round(fee, 2),
                 "net_proceed": round(net_proceed, 2)}
        self.trade_history.append(trade)
        self._append_trade(trade)
        self._save_state()
        return {"success": True, "filled_shares": actual_shares, "fill_price": slip_price, "net_proceed": net_proceed}

    # ── 每日流程 ────────────────────────────────────────────

    def daily_process(self, signal: dict, prices: dict, date: str) -> dict:
        """每日模拟交易主流程：对比信号持仓差价 → 增量调仓 → 日收益计算。

        Args:
            signal: {
                "signal_date": str,
                "candidates": [{"symbol": str, "rank": int, ...}],
                "top_n": int  # 取前 N 个候选
            }
            prices: {symbol: current_price}
            date: 交易日字符串 (YYYY-MM-DD)

        Returns:
            {
                "orders": [执行结果...],
                "pnl": {"total_value", "daily_return_pct", "total_return_pct"},
                "summary": {"holdings", "trades_today", "cash"}
            }
        """
        target_symbols = [c["symbol"] for c in signal.get("candidates", [])
                         if c.get("rank", 999) <= (signal.get("top_n", 10))]
        orders = []

        # 卖出不再在目标中的持仓
        for sym in list(self.holdings.keys()):
            if sym not in target_symbols:
                price = prices.get(sym, self.holdings[sym].get("last_price", 0))
                if price > 0:
                    r = self.execute_sell(sym, price, self.holdings[sym]["shares"], date)
                    orders.append(r)

        # 买入新目标
        total_budget = self.cash * 0.9
        per_stock = total_budget / max(len(target_symbols), 1)
        for sym in target_symbols:
            if sym not in self.holdings:
                price = prices.get(sym, 0)
                if price <= 0:
                    continue
                shares = round_to_lot_size(int(per_stock / price))
                if shares >= 100:
                    r = self.execute_buy(sym, price, shares, date)
                    orders.append(r)

        # 计算日收益
        total_value = self.cash + sum(
            h["shares"] * prices.get(sym, h.get("last_price", 0))
            for sym, h in self.holdings.items())
        prev = self.equity_history[-1]["total_value"] if self.equity_history else self.initial_capital
        daily_ret = (total_value - prev) / prev if prev > 0 else 0
        self._append_equity(date, total_value, daily_ret, self.cash)

        return {
            "orders": orders,
            "pnl": {"total_value": round(total_value, 2),
                    "daily_return_pct": round(daily_ret * 100, 4),
                    "total_return_pct": round((total_value / self.initial_capital - 1) * 100, 2)},
            "summary": {"holdings": len(self.holdings), "trades_today": len(orders),
                        "cash": round(self.cash, 2)},
        }

    # ── 查询接口 ────────────────────────────────────────────

    def get_equity_curve(self) -> pd.DataFrame:
        """返回权益曲线 DataFrame。"""
        return pd.DataFrame(self.equity_history)

    def get_total_return_pct(self) -> float:
        """返回累计收益率百分比。"""
        if not self.equity_history:
            return 0.0
        return (self.equity_history[-1]["total_value"] - self.initial_capital) / self.initial_capital * 100

    def get_position_summary(self) -> list:
        """返回当前持仓概要。"""
        return [{"symbol": sym, **h} for sym, h in self.holdings.items()]

    def get_state(self) -> dict:
        """返回引擎完整状态快照。"""
        return {
            "initial_capital": self.initial_capital,
            "capital": self.capital,
            "cash": self.cash,
            "holdings": self.holdings,
            "total_trades": len(self.trade_history),
            "total_return_pct": round(self.get_total_return_pct(), 4),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# V4.8 PaperTradingV4 — Enhanced Paper / Shadow Trading Engine
# ═══════════════════════════════════════════════════════════════════════════════

class PaperTradingV4:
    """V4.8 Paper Trading Engine — 组合推荐 → 可交易性检查 → 模拟成交 → 偏差分析

    与 StandingPaperTrading (V3.4.2) 的主要区别:
      - 使用 portfolio_builder.build_portfolio 获取组合推荐
      - 可交易性检查 (涨跌停/停牌/资金/100股整数倍)
      - 模拟成交 (按收盘价, 含手续费0.025%+印花税0.1%+滑点0.05%)
      - 组合收益计算
      - 执行偏差分析 (计划 vs 实际)
      - 外部不持久化状态 (每次 run_paper 独立运行)
    """

    # V4.8 费率参数
    COMMISSION_RATE = 0.00025  # 佣金万分之二点五
    STAMP_TAX_RATE = 0.001     # 印花税千分之一 (卖出)
    SLIPPAGE_RATE = 0.0005     # 滑点万五
    LOT_SIZE = 100

    def __init__(self, capital: float = 50000.0,
                 data_provider: Optional[Any] = None):
        """
        Args:
            capital: 模拟资金
            data_provider: 可选的数据提供器 (用于获取行情/可交易性数据)
                          如不传, 使用默认的市场数据加载
        """
        self.capital = capital
        self.cash = capital
        self.holdings: dict[str, dict] = {}  # {symbol: {shares, avg_cost}}
        self.trades: list[dict] = []
        self.data_provider = data_provider
        self._portfolio_builder: Optional[Any] = None

    # ── PortfolioBuilder 懒加载 ──────────────────────────────────────────────

    @property
    def portfolio_builder(self):
        if self._portfolio_builder is None:
            from portfolio_builder import PortfolioBuilder
            self._portfolio_builder = PortfolioBuilder()
        return self._portfolio_builder

    # ── 核心流程 ─────────────────────────────────────────────────────────────

    def run_paper(self, date: str,
                  factor_signals: Optional[list[dict]] = None,
                  constraints: Optional[dict] = None,
                  market_data: Optional[pd.DataFrame] = None) -> dict:
        """运行当日模拟盘

        Args:
            date: 交易日 YYYY-MM-DD
            factor_signals: 因子信号列表 (如不传, 从 portfolio_builder 获取模拟信号)
            constraints: 组合约束覆盖
            market_data: 市场数据 DataFrame (含 date/symbol/close/open/high/low/volume/prev_close)

        Returns:
            {
                "date": str,
                "plan": { 组合推荐计划 },
                "execution": { 执行结果 },
                "pnl": { 收益计算 },
                "deviation": { 偏差分析 },
                "tradability_check": { 可交易性检查 },
                "risk_interceptions": [ 风控拦截详细 ]
            }
        """
        # Step 1: 获取组合推荐
        constraints_dict = constraints or {}
        if not constraints_dict.get("capital"):
            constraints_dict["capital"] = self.capital
        if not constraints_dict.get("top_n"):
            constraints_dict["top_n"] = 10

        if factor_signals is None:
            factor_signals = self.portfolio_builder._generate_mock_signals()

        portfolio = self.portfolio_builder.build_portfolio(
            factor_signals, constraints_dict, signal_date=date
        )
        portfolio = self.portfolio_builder.apply_constraints(portfolio)
        portfolio = self.portfolio_builder.build_etf_replacement(portfolio)
        report = self.portfolio_builder.portfolio_report(portfolio)

        plan = {
            "signal_date": date,
            "n_stocks": len(portfolio.stocks),
            "n_tradable": sum(1 for s in portfolio.stocks if s.is_tradable),
            "n_blocked": sum(1 for s in portfolio.stocks if not s.is_tradable),
            "stocks": [{
                "symbol": s.symbol,
                "name": s.name,
                "ts_code": s.ts_code,
                "weight": s.weight,
                "shares": s.shares,
                "estimated_amount": s.estimated_amount,
                "is_tradable": s.is_tradable,
                "block_reasons": s.risk.block_reasons if s.risk else [],
            } for s in portfolio.stocks],
            "etf_replacements": portfolio.etf_replacements,
            "theme_position": portfolio.theme_position,
        }

        # Step 2: 可交易性检查
        tradability_check = self._run_tradability_check(
            portfolio.stocks, date, market_data
        )

        # Step 3: 模拟成交
        execution = self._simulate_execution(
            portfolio.stocks, date, market_data
        )

        # Step 4: 组合收益计算
        pnl = self._calculate_pnl(date, market_data)

        # Step 5: 执行偏差分析
        deviation = self._analyze_deviation(plan, execution)

        # Step 6: 风控拦截日志
        risk_interceptions = self._extract_risk_interceptions(
            tradability_check, execution
        )

        return {
            "date": date,
            "plan": plan,
            "execution": execution,
            "pnl": pnl,
            "deviation": deviation,
            "tradability_check": tradability_check,
            "risk_interceptions": risk_interceptions,
        }

    # ── 可交易性检查 ─────────────────────────────────────────────────────

    @staticmethod
    def _is_limit_up(close: float, prev_close: float) -> bool:
        """判断是否涨停"""
        if pd.isna(close) or pd.isna(prev_close) or prev_close <= 0:
            return False
        return close >= prev_close * 1.095 - 0.005

    @staticmethod
    def _is_limit_down(close: float, prev_close: float) -> bool:
        """判断是否跌停"""
        if pd.isna(close) or pd.isna(prev_close) or prev_close <= 0:
            return False
        return close <= prev_close * 0.905 + 0.005

    @staticmethod
    def _is_suspended(row: pd.Series) -> bool:
        """判断是否停牌"""
        close = row.get("close", np.nan)
        volume = row.get("volume", row.get("vol", np.nan))
        if pd.isna(close) or close == 0:
            return True
        if not pd.isna(volume) and volume == 0:
            return True
        return False

    def _run_tradability_check(
        self,
        stocks: list[Any],
        date: str,
        market_data: Optional[pd.DataFrame] = None,
    ) -> dict:
        """对组合中每只股票进行可交易性检查

        检查: 涨跌停, 停牌, 资金充足, 100股整数倍
        """
        results = []
        day_data = None
        if market_data is not None and "date" in market_data.columns:
            day_data = market_data[market_data["date"] == date]

        for stock in stocks:
            result = {"symbol": stock.symbol, "name": stock.name,
                      "plannable": True, "reasons": []}

            # 已有风控标记
            if hasattr(stock, "risk") and stock.risk and stock.risk.block_reasons:
                result["plannable"] = False
                result["reasons"].extend(stock.risk.block_reasons)
                results.append(result)
                continue

            if day_data is not None and not day_data.empty:
                row = day_data[day_data["symbol"] == stock.symbol]
                if not row.empty:
                    r = row.iloc[0]
                    close = r.get("close", 0)
                    prev_close = r.get("prev_close", r.get("pre_close", 0))
                    volume = r.get("volume", 0)

                    # 涨跌停检查
                    if self._is_limit_up(close, prev_close):
                        result["plannable"] = False
                        result["reasons"].append("涨停封板 (禁买)")
                    if self._is_limit_down(close, prev_close):
                        result["plannable"] = False
                        result["reasons"].append("跌停封板 (禁交易)")

                    # 停牌检查
                    if self._is_suspended(r):
                        result["plannable"] = False
                        result["reasons"].append("停牌")

            # 资金检查
            estimated_cost = stock.estimated_amount if hasattr(stock, "estimated_amount") else 0
            if estimated_cost > self.cash * 0.95:
                result["plannable"] = False
                result["reasons"].append("资金不足")

            results.append(result)

        blocked = [r for r in results if not r["plannable"]]
        return {
            "total": len(results),
            "plannable": len(results) - len(blocked),
            "blocked": len(blocked),
            "details": results,
        }

    # ── 模拟成交 ────────────────────────────────────────────────────────

    def _simulate_execution(
        self,
        stocks: list[Any],
        date: str,
        market_data: Optional[pd.DataFrame] = None,
    ) -> dict:
        """模拟成交 (按收盘价, 含费用和滑点)

        费用模型: 佣金0.025% + 印花税0.1%(卖出) + 滑点0.05%
        """
        day_data = None
        if market_data is not None and "date" in market_data.columns:
            day_data = market_data[market_data["date"] == date]

        fills = []
        total_cost = 0.0
        total_fee = 0.0

        for stock in stocks:
            if hasattr(stock, "is_tradable") and not stock.is_tradable:
                continue
            if hasattr(stock, "risk") and stock.risk and stock.risk.is_blocked:
                continue

            price = None
            if day_data is not None and not day_data.empty:
                row = day_data[day_data["symbol"] == stock.symbol]
                if not row.empty:
                    price = float(row.iloc[0].get("close", 0))

            if price is None or price <= 0:
                fills.append({
                    "symbol": stock.symbol, "name": stock.name,
                    "filled": False, "reason": "无价格数据",
                })
                continue

            # 整手截断
            planned_shares = stock.shares if hasattr(stock, "shares") else 0
            if planned_shares <= 0:
                fills.append({
                    "symbol": stock.symbol, "name": stock.name,
                    "filled": False, "reason": "计划股数为0",
                })
                continue

            shares = (planned_shares // self.LOT_SIZE) * self.LOT_SIZE
            if shares < self.LOT_SIZE:
                fills.append({
                    "symbol": stock.symbol, "name": stock.name,
                    "filled": False, "reason": "不足一手(100股)",
                })
                continue

            # 滑点: 买入 +0.05%
            slip_price = price * (1 + self.SLIPPAGE_RATE)
            amount = shares * slip_price

            # 费用: 佣金 + 印花税(仅卖出)
            commission = amount * self.COMMISSION_RATE
            fee = commission  # 买入时不收印花税
            total_cost_stock = amount + fee

            # 资金检查
            if total_cost_stock > self.cash:
                max_shares = int((self.cash - 5) / slip_price)
                max_shares = (max_shares // self.LOT_SIZE) * self.LOT_SIZE
                if max_shares < self.LOT_SIZE:
                    fills.append({
                        "symbol": stock.symbol, "name": stock.name,
                        "filled": False, "reason": "资金不足",
                        "price": slip_price, "shares": shares,
                    })
                    continue
                shares = max_shares
                amount = shares * slip_price
                commission = amount * self.COMMISSION_RATE
                total_cost_stock = amount + commission

            # 执行买入
            old = self.holdings.get(stock.symbol, {"shares": 0, "avg_cost": 0})
            total_new_shares = old["shares"] + shares
            total_cost_basis = old["shares"] * old["avg_cost"] + amount
            self.holdings[stock.symbol] = {
                "shares": total_new_shares,
                "avg_cost": round(total_cost_basis / total_new_shares, 4) if total_new_shares > 0 else 0,
            }
            self.cash -= total_cost_stock
            total_cost += total_cost_stock
            total_fee += commission

            fill = {
                "symbol": stock.symbol,
                "name": stock.name,
                "filled": True,
                "shares": shares,
                "price": round(slip_price, 2),
                "original_price": round(price, 2),
                "slippage": round(slip_price - price, 4),
                "amount": round(amount, 2),
                "commission": round(commission, 4),
                "total_cost": round(total_cost_stock, 2),
            }
            fills.append(fill)

            self.trades.append({
                "date": date,
                "symbol": stock.symbol,
                "side": "buy",
                "shares": shares,
                "price": round(slip_price, 2),
                "commission": round(commission, 4),
            })

        return {
            "date": date,
            "n_planned": len([s for s in stocks if hasattr(s, "is_tradable") and s.is_tradable]),
            "n_filled": sum(1 for f in fills if f.get("filled")),
            "n_failed": sum(1 for f in fills if not f.get("filled")),
            "fills": fills,
            "total_cost": round(total_cost, 2),
            "total_fee": round(total_fee, 4),
            "cash_remaining": round(self.cash, 2),
        }

    # ── 组合收益计算 ───────────────────────────────────────────────────

    def _calculate_pnl(self, date: str,
                       market_data: Optional[pd.DataFrame] = None) -> dict:
        """计算组合收益"""
        day_data = None
        if market_data is not None and "date" in market_data.columns:
            day_data = market_data[market_data["date"] == date]

        # 计算持仓市值
        holdings_value = 0.0
        for sym, h in self.holdings.items():
            price = 0.0
            if day_data is not None and not day_data.empty:
                row = day_data[day_data["symbol"] == sym]
                if not row.empty:
                    price = float(row.iloc[0].get("close", h.get("avg_cost", 0)))
            if price <= 0:
                price = h.get("avg_cost", 0)
            holdings_value += h["shares"] * price

        total_value = self.cash + holdings_value
        total_return = (total_value - self.capital) / self.capital if self.capital > 0 else 0

        # 持仓收益明细
        position_pnl = []
        for sym, h in self.holdings.items():
            price = 0.0
            if day_data is not None and not day_data.empty:
                row = day_data[day_data["symbol"] == sym]
                if not row.empty:
                    price = float(row.iloc[0].get("close", h.get("avg_cost", 0)))
            if price <= 0:
                price = h.get("avg_cost", 0)
            mv = h["shares"] * price
            cost = h["shares"] * h["avg_cost"]
            pnl_stock = mv - cost
            position_pnl.append({
                "symbol": sym,
                "shares": h["shares"],
                "avg_cost": h["avg_cost"],
                "current_price": price,
                "market_value": round(mv, 2),
                "cost_basis": round(cost, 2),
                "pnl": round(pnl_stock, 2),
                "pnl_pct": round((pnl_stock / cost) * 100, 2) if cost > 0 else 0,
            })

        return {
            "date": date,
            "capital": round(self.capital, 2),
            "cash": round(self.cash, 2),
            "holdings_value": round(holdings_value, 2),
            "total_value": round(total_value, 2),
            "total_return_pct": round(total_return * 100, 4),
            "positions": position_pnl,
        }

    # ── 偏差分析 ───────────────────────────────────────────────────────

    def _analyze_deviation(self, plan: dict, execution: dict) -> dict:
        """分析计划 vs 实际执行偏差"""
        planned_stocks = plan.get("stocks", [])
        plan_symbols = set(s["symbol"] for s in planned_stocks)
        plan_weights = {s["symbol"]: s["weight"] for s in planned_stocks}
        plan_amounts = {s["symbol"]: s["estimated_amount"] for s in planned_stocks}

        fills = execution.get("fills", [])
        filled_symbols = set(f["symbol"] for f in fills if f.get("filled"))

        # 偏差明细
        deviations = []
        for s in planned_stocks:
            sym = s["symbol"]
            planned_amount = s["estimated_amount"]
            actual_amount = 0.0
            actual_fill = next((f for f in fills if f["symbol"] == sym and f.get("filled")), None)
            if actual_fill:
                actual_amount = actual_fill["total_cost"]

            deviation_amt = actual_amount - planned_amount
            deviation_pct = (deviation_amt / planned_amount * 100) if planned_amount > 0 else 0

            deviations.append({
                "symbol": sym,
                "name": s.get("name", ""),
                "planned_amount": round(planned_amount, 2),
                "actual_amount": round(actual_amount, 2),
                "deviation_amt": round(deviation_amt, 2),
                "deviation_pct": round(deviation_pct, 2),
                "status": "filled" if sym in filled_symbols else "unfilled",
                "reason": "" if sym in filled_symbols else (
                    next((f["reason"] for f in fills if f["symbol"] == sym), "unknown")
                ),
            })

        # 汇总
        n_planned = len(plan_symbols)
        n_filled = len(filled_symbols)
        n_missed = n_planned - n_filled
        total_planned = sum(p["estimated_amount"] for p in planned_stocks)
        total_actual = sum(f["total_cost"] for f in fills if f.get("filled"))
        total_deviation = total_actual - total_planned
        total_deviation_pct = (total_deviation / total_planned * 100) if total_planned > 0 else 0

        return {
            "total_planned": round(total_planned, 2),
            "total_actual": round(total_actual, 2),
            "total_deviation_amt": round(total_deviation, 2),
            "total_deviation_pct": round(total_deviation_pct, 2),
            "n_planned": n_planned,
            "n_filled": n_filled,
            "n_missed": n_missed,
            "fill_rate_pct": round(n_filled / n_planned * 100, 2) if n_planned > 0 else 0,
            "details": deviations,
        }

    # ── 风控拦截提取 ──────────────────────────────────────────────────

    def _extract_risk_interceptions(self,
                                     tradability_check: dict,
                                     execution: dict) -> list[dict]:
        """提取风控拦截详细信息"""
        interceptions = []

        # 从可交易性检查中提取
        for detail in tradability_check.get("details", []):
            if not detail.get("plannable", True) and detail.get("reasons"):
                for reason in detail["reasons"]:
                    interceptions.append({
                        "symbol": detail["symbol"],
                        "name": detail.get("name", ""),
                        "reason": reason,
                        "stage": "tradability_check",
                    })

        # 从执行失败中提取
        for fill in execution.get("fills", []):
            if not fill.get("filled"):
                interceptions.append({
                    "symbol": fill["symbol"],
                    "name": fill.get("name", ""),
                    "reason": fill.get("reason", "执行失败"),
                    "stage": "execution",
                })

        return interceptions

    # ── 批量运行 ───────────────────────────────────────────────────────

    def run_multiple_days(
        self,
        dates: list[str],
        factor_signals: Optional[list[dict]] = None,
        constraints: Optional[dict] = None,
        market_data: Optional[pd.DataFrame] = None,
    ) -> list[dict]:
        """按顺序运行多日模拟盘

        每期开始时重置持仓和资金, 独立运行。
        """
        results = []
        for date in dates:
            sub = PaperTradingV4(
                capital=self.capital,
                data_provider=self.data_provider,
            )
            result = sub.run_paper(date, factor_signals, constraints, market_data)
            results.append(result)

        return results

    # ── 摘要 ───────────────────────────────────────────────────────────

    @staticmethod
    def summary(results: list[dict]) -> dict:
        """生成多日回测摘要"""
        if not results:
            return {"n_days": 0, "message": "无数据"}

        pnls = [r["pnl"] for r in results if r.get("pnl")]
        deviations = [r["deviation"] for r in results if r.get("deviation")]
        risk_ics_lists = [r["risk_interceptions"] for r in results if r.get("risk_interceptions")]

        # 收益率统计
        avg_return = sum(p["total_return_pct"] for p in pnls) / len(pnls) if pnls else 0
        final_value = pnls[-1]["total_value"] if pnls else 0
        initial_value = pnls[0]["capital"] if pnls else 0
        total_return = (final_value - initial_value) / initial_value * 100 if initial_value > 0 else 0

        # 执行质量
        avg_fill_rate = sum(d["fill_rate_pct"] for d in deviations) / len(deviations) if deviations else 0

        # 风控统计
        total_risk = sum(len(r) for r in risk_ics_lists)
        risk_by_reason: dict[str, int] = {}
        for rlist in risk_ics_lists:
            for r in rlist:
                reason = r.get("reason", "unknown")
                risk_by_reason[reason] = risk_by_reason.get(reason, 0) + 1

        # 偏差统计
        avg_deviation_pct = sum(d["total_deviation_pct"] for d in deviations) / len(deviations) if deviations else 0

        return {
            "n_days": len(results),
            "date_range": f"{results[0]['date']} ~ {results[-1]['date']}",
            "initial_capital": initial_value,
            "final_value": round(final_value, 2),
            "total_return_pct": round(total_return, 4),
            "avg_daily_return_pct": round(avg_return, 4),
            "avg_fill_rate_pct": round(avg_fill_rate, 2),
            "avg_deviation_pct": round(avg_deviation_pct, 2),
            "total_risk_interceptions": total_risk,
            "risk_breakdown": risk_by_reason,
        }

    # ── CLI 工具 ───────────────────────────────────────────────────────

    @staticmethod
    def cmd_v4_run(args: list[str], factor_signals: Optional[list] = None):
        """CLI: paper:v4-run 入口"""
        import json
        from datetime import datetime

        date = ""
        capital = 50000.0
        top_n = 10

        for i, a in enumerate(args):
            if a == "--date" and i + 1 < len(args):
                date = args[i + 1]
            elif a == "--capital" and i + 1 < len(args):
                try:
                    capital = float(args[i + 1])
                except ValueError:
                    pass
            elif a == "--top-n" and i + 1 < len(args):
                try:
                    top_n = int(args[i + 1])
                except ValueError:
                    pass

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        engine = PaperTradingV4(capital=capital)
        result = engine.run_paper(date, factor_signals=factor_signals,
                                   constraints={"top_n": top_n, "capital": capital})

        print(f"\n📊 V4.8 Paper Trading — {date}")
        print(f"{'=' * 50}")
        print(f"  模拟资金: {capital:,.0f}")
        print(f"  目标数量: {top_n}")
        print()

        # 计划摘要
        plan = result["plan"]
        print(f"━━━ 组合计划 ━━━")
        print(f"  推荐: {plan['n_stocks']} 只  |  可交易: {plan['n_tradable']} 只  |  受阻: {plan['n_blocked']} 只")
        print()

        # 执行摘要
        exec_r = result["execution"]
        print(f"━━━ 模拟成交 ━━━")
        print(f"  计划: {exec_r['n_planned']} 只  |  成交: {exec_r['n_filled']} 只  |  失败: {exec_r['n_failed']} 只")
        print(f"  总成本: {exec_r['total_cost']:,.2f}  |  费用: {exec_r['total_fee']:,.4f}")
        print(f"  剩余现金: {exec_r['cash_remaining']:,.2f}")
        print()

        for f in exec_r["fills"]:
            if f.get("filled"):
                print(f"  ✅ {f['symbol']} {f.get('name',''):10s}  "
                      f"{f['shares']}股 @ {f['price']}  |  "
                      f"金额={f['total_cost']:,.2f}")
            else:
                print(f"  ❌ {f['symbol']} {f.get('name',''):10s}  {f.get('reason','')}")
        print()

        # 组合收益
        pnl = result["pnl"]
        print(f"━━━ 组合收益 ━━━")
        print(f"  总资产: {pnl['total_value']:,.2f}")
        print(f"  现金: {pnl['cash']:,.2f}")
        print(f"  持仓市值: {pnl['holdings_value']:,.2f}")
        print(f"  累计收益: {pnl['total_return_pct']:+.4f}%")
        print()

        # 偏差分析
        dev = result["deviation"]
        print(f"━━━ 执行偏差 ━━━")
        print(f"  计划总额: {dev['total_planned']:,.2f}")
        print(f"  实际总额: {dev['total_actual']:,.2f}")
        print(f"  偏差: {dev['total_deviation_amt']:+,.2f} ({dev['total_deviation_pct']:+.2f}%)")
        print(f"  成交率: {dev['fill_rate_pct']:.2f}%  |  错失: {dev['n_missed']} 只")
        print()

        # 风控拦截
        risk_ics = result["risk_interceptions"]
        if risk_ics:
            print(f"━━━ 风控拦截 ({len(risk_ics)} 次) ━━━")
            by_reason: dict[str, int] = {}
            for r in risk_ics:
                reason = r["reason"]
                by_reason[reason] = by_reason.get(reason, 0) + 1
            for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
                print(f"  🛑 {reason}: {count} 次")
            print()

        # ETF替代
        if plan.get("etf_replacements"):
            print(f"━━━ ETF替代方案 ━━━")
            for etf in plan["etf_replacements"]:
                print(f"  {etf['ts_code']} {etf['name']:12s}  替代: {', '.join(etf.get('replaces', []))}")
            print()

        return result

    @staticmethod
    def cmd_v4_dashboard(args: list[str]):
        """CLI: paper:v4-dashboard — 查看 V4.8 Paper Trading 看板"""
        from pathlib import Path
        import json

        output_dir = Path("/mnt/d/HermesReports/paper_v4")
        if not output_dir.exists():
            print("❌ 无历史 V4.8 Paper 记录")
            return

        files = sorted(output_dir.glob("paper_v4_*.json"), reverse=True)
        if not files:
            print("❌ 无历史 V4.8 Paper 记录文件")
            return

        latest = files[0]
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)

        print(f"\n📊 V4.8 Paper Dashboard")
        print(f"   {'=' * 45}")
        print(f"   文件: {latest.name}")

        if isinstance(data, list):
            # 多日结果
            print(f"   回测天数: {len(data)}")
            pnls = [d.get("pnl", {}) for d in data if d.get("pnl")]
            if pnls:
                rets = [p.get("total_return_pct", 0) for p in pnls]
                print(f"   初始资金: {pnls[0].get('capital', '?'):,.2f}")
                print(f"   最终总值: {pnls[-1].get('total_value', '?'):,.2f}")
                print(f"   总收益: {rets[-1]:+.4f}%")
                print(f"   平均收益: {sum(rets)/len(rets):+.4f}%")
                print(f"   正收益日: {sum(1 for r in rets if r > 0)}/{len(rets)}")
        elif isinstance(data, dict):
            pnl = data.get("pnl", {})
            print(f"   资金: {pnl.get('total_value', '?'):,.2f}")
            print(f"   收益: {pnl.get('total_return_pct', '?'):+.4f}%")

        print(f"   路径: {latest}")
