"""V4.1 Shadow Live Pipeline — Shadow Execution Ledger & Deviation Reports

Records all shadow transactions and generates signal-vs-shadow-fill
deviation reports. This is the audit trail of what WOULD have happened
if signals were executed.

Key reports:
  1. Shadow Execution Ledger — all transactions with timestamps
  2. Signal vs Shadow Fill Report — deviation between signal price and fill price
  3. Slippage Analysis — actual vs expected slippage
  4. Account Summary — PnL, exposure, cash levels
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))


@dataclass
class LedgerEntry:
    """A single entry in the shadow execution ledger."""
    entry_id: str = ""
    timestamp: str = ""
    symbol: str = ""
    name: str = ""
    action: str = ""               # "buy" | "sell" | "mark_to_market" | "dividend" | "fee"
    order_id: str = ""             # Link to ShadowOrder
    signal_id: str = ""            # Link to source signal
    proposal_id: str = ""          # Link to source proposal
    shares: int = 0
    price: float = 0.0             # Execution price
    signal_price: float = 0.0      # Price when signal was generated
    slippage: float = 0.0          # Applied slippage
    commission: float = 0.0
    tax: float = 0.0
    amount: float = 0.0            # Total monetary amount
    cash_before: float = 0.0
    cash_after: float = 0.0
    position_before: int = 0
    position_after: int = 0
    note: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.entry_id:
            self.entry_id = f"ledger_{datetime.now(CST).strftime('%Y%m%d_%H%M%S_%f')}"
        if not self.timestamp:
            self.timestamp = datetime.now(CST).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Deviation entry
# ---------------------------------------------------------------------------
@dataclass
class DeviationEntry:
    """A single deviation measurement between signal and fill."""
    symbol: str = ""
    name: str = ""
    side: str = ""
    signal_price: float = 0.0
    fill_price: float = 0.0
    price_deviation: float = 0.0       # fill_price - signal_price (absolute)
    price_deviation_pct: float = 0.0   # relative deviation (%)
    slippage_applied: float = 0.0
    shares: int = 0
    amount: float = 0.0
    signal_time: str = ""
    fill_time: str = ""
    order_id: str = ""
    signal_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Shadow Execution Ledger
# ---------------------------------------------------------------------------
class ShadowExecutionLedger:
    """Records all shadow transactions and generates deviation reports.

    This is the primary audit trail for the shadow pipeline.
    Every operation (buy, sell, mark-to-market, fee) is recorded.
    """

    def __init__(self, output_dir: str = ""):
        self.entries: list = []
        self.output_dir = output_dir

    def record(self, entry: LedgerEntry):
        """Record a ledger entry."""
        self.entries.append(entry)

    def record_buy(self, symbol: str, shares: int, price: float,
                   signal_price: float = 0.0, slippage: float = 0.0,
                   commission: float = 0.0, tax: float = 0.0,
                   cash_before: float = 0.0, cash_after: float = 0.0,
                   position_before: int = 0, position_after: int = 0,
                   name: str = "", order_id: str = "",
                   signal_id: str = "", proposal_id: str = "",
                   note: str = "", **kwargs) -> LedgerEntry:
        """Record a buy execution."""
        entry = LedgerEntry(
            symbol=symbol, name=name,
            action="buy", order_id=order_id,
            signal_id=signal_id, proposal_id=proposal_id,
            shares=shares, price=price,
            signal_price=signal_price,
            slippage=slippage, commission=commission, tax=tax,
            amount=round(shares * price + commission + tax, 2),
            cash_before=cash_before, cash_after=cash_after,
            position_before=position_before, position_after=position_after,
            note=note,
        )
        self.record(entry)
        return entry

    def record_sell(self, symbol: str, shares: int, price: float,
                    signal_price: float = 0.0, slippage: float = 0.0,
                    commission: float = 0.0, tax: float = 0.0,
                    cash_before: float = 0.0, cash_after: float = 0.0,
                    position_before: int = 0, position_after: int = 0,
                    name: str = "", order_id: str = "",
                    signal_id: str = "", proposal_id: str = "",
                    note: str = "", **kwargs) -> LedgerEntry:
        """Record a sell execution."""
        entry = LedgerEntry(
            symbol=symbol, name=name,
            action="sell", order_id=order_id,
            signal_id=signal_id, proposal_id=proposal_id,
            shares=shares, price=price,
            signal_price=signal_price,
            slippage=slippage, commission=commission, tax=tax,
            amount=round(shares * price - commission - tax, 2),
            cash_before=cash_before, cash_after=cash_after,
            position_before=position_before, position_after=position_after,
            note=note,
        )
        self.record(entry)
        return entry

    def record_mark(self, symbol: str, price: float,
                    shares: int = 0, note: str = "", **kwargs) -> LedgerEntry:
        """Record a mark-to-market event."""
        entry = LedgerEntry(
            symbol=symbol, action="mark_to_market",
            shares=shares, price=price, note=note,
        )
        self.record(entry)
        return entry

    # -- Deviation analysis ----------------------------------------------

    def compute_deviations(self) -> list:
        """Compute price deviations between signal price and fill price.

        Returns list of DeviationEntry objects.
        """
        deviations = []
        for entry in self.entries:
            if entry.action not in ("buy", "sell"):
                continue
            if entry.signal_price <= 0:
                continue

            dev = entry.price - entry.signal_price
            if entry.signal_price > 0:
                dev_pct = round(dev / entry.signal_price * 100, 4)
            else:
                dev_pct = 0.0

            deviations.append(DeviationEntry(
                symbol=entry.symbol,
                name=entry.name,
                side=entry.action,
                signal_price=entry.signal_price,
                fill_price=entry.price,
                price_deviation=round(dev, 2),
                price_deviation_pct=dev_pct,
                slippage_applied=entry.slippage,
                shares=entry.shares,
                amount=entry.amount,
                signal_time="",
                fill_time=entry.timestamp,
                order_id=entry.order_id,
                signal_id=entry.signal_id,
            ))
        return deviations

    def deviation_summary(self, deviations: list = None) -> dict:
        """Summarize deviation statistics across all entries."""
        if deviations is None:
            deviations = self.compute_deviations()

        if not deviations:
            return {
                "n_entries": 0,
                "n_buy": 0,
                "n_sell": 0,
                "mean_deviation": 0.0,
                "mean_deviation_pct": 0.0,
                "max_deviation": 0.0,
                "max_deviation_pct": 0.0,
                "min_deviation": 0.0,
                "min_deviation_pct": 0.0,
                "total_slippage_cost": 0.0,
            }

        buy_devs = [d for d in deviations if d.side == "buy"]
        sell_devs = [d for d in deviations if d.side == "sell"]

        all_devs = [d.price_deviation for d in deviations]
        all_pcts = [d.price_deviation_pct for d in deviations]

        return {
            "n_entries": len(deviations),
            "n_buy": len(buy_devs),
            "n_sell": len(sell_devs),
            "mean_deviation": round(sum(all_devs) / len(all_devs), 4),
            "mean_deviation_pct": round(sum(all_pcts) / len(all_pcts), 4),
            "max_deviation": round(max(all_devs), 2),
            "max_deviation_pct": round(max(all_pcts), 4),
            "min_deviation": round(min(all_devs), 2),
            "min_deviation_pct": round(min(all_pcts), 4),
            "total_slippage_cost": round(sum(d.slippage_applied * d.shares for d in deviations), 2),
            "buy_mean_deviation": round(
                sum(d.price_deviation for d in buy_devs) / len(buy_devs), 4
            ) if buy_devs else 0,
            "sell_mean_deviation": round(
                sum(d.price_deviation for d in sell_devs) / len(sell_devs), 4
            ) if sell_devs else 0,
        }

    # -- Report generation -----------------------------------------------

    def generate_ledger_report(self, output_path: str = "") -> str:
        """Generate the shadow execution ledger as JSON."""
        path = output_path or (
            os.path.join(self.output_dir, "shadow_execution_ledger.json")
            if self.output_dir else "shadow_execution_ledger.json"
        )
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        report = {
            "generated_at": datetime.now(CST).isoformat(),
            "version": "V4.1",
            "n_entries": len(self.entries),
            "entries": [e.to_dict() for e in self.entries],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return path

    def generate_deviation_report(self, output_path: str = "") -> str:
        """Generate signal-vs-shadow-fill deviation report."""
        deviations = self.compute_deviations()
        summary = self.deviation_summary(deviations)

        path = output_path or (
            os.path.join(self.output_dir, "signal_vs_shadow_fill_report.json")
            if self.output_dir else "signal_vs_shadow_fill_report.json"
        )
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        report = {
            "generated_at": datetime.now(CST).isoformat(),
            "version": "V4.1",
            "title": "Signal vs Shadow Fill Deviation Report",
            "description": "价格偏差: fill_price - signal_price. "
                           "正偏差表示买入成本更高或卖出收入更高。",
            "summary": summary,
            "deviations": [d.to_dict() for d in deviations],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return path

    def generate_html_report(self, output_path: str = "") -> str:
        """Generate a human-readable HTML report combining ledger + deviations."""
        deviations = self.compute_deviations()
        dev_summary = self.deviation_summary(deviations)

        path = output_path or (
            os.path.join(self.output_dir, "shadow_pipeline_report.html")
            if self.output_dir else "shadow_pipeline_report.html"
        )
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        # Build ledger table rows
        ledger_rows = ""
        for e in self.entries[-100:]:  # Last 100 entries
            color = {"buy": "#00c853", "sell": "#ff1744",
                     "mark_to_market": "#448aff"}.get(e.action, "#888")
            sym = e.symbol or "-"
            price_str = f"¥{e.price:.2f}" if e.price > 0 else "-"
            amount_str = f"¥{e.amount:.2f}" if e.amount > 0 else "-"
            ledger_rows += (
                f"<tr><td>{e.timestamp[5:19]}</td>"
                f"<td>{sym}</td>"
                f"<td style='color:{color}'>{e.action}</td>"
                f"<td>{e.shares}</td>"
                f"<td>{price_str}</td>"
                f"<td>{amount_str}</td>"
                f"<td>{e.note}</td></tr>"
            )

        # Build deviation table rows
        dev_rows = ""
        for d in deviations[-50:]:  # Last 50 deviations
            color = "#ff1744" if abs(d.price_deviation_pct) > 0.5 else "#00c853"
            dev_rows += (
                f"<tr><td>{d.symbol}</td>"
                f"<td>{d.side}</td>"
                f"<td>¥{d.signal_price:.2f}</td>"
                f"<td>¥{d.fill_price:.2f}</td>"
                f"<td style='color:{color}'>{d.price_deviation_pct:.4f}%</td>"
                f"<td>{d.shares}</td></tr>"
            )

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8">
<title>Shadow Pipeline Report V4.1</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; padding-bottom:4px; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; }}
th {{ color:#888; font-size:0.85em; }}
.summary-item {{ display:inline-block; margin:8px 16px; padding:8px 16px; background:#1a1a2e; border-radius:6px; }}
.summary-value {{ font-size:1.4em; font-weight:bold; color:#00bcd4; }}
.summary-label {{ font-size:0.8em; color:#888; }}
</style></head><body>
<div class="card"><h1>📊 Shadow Live Pipeline Report</h1>
<p style="color:#aaa;">V4.1 | Generated: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>

<div class="card"><h2>📋 Deviation Summary</h2>
<div><div class="summary-item"><div class="summary-value">{dev_summary['n_entries']}</div><div class="summary-label">Total Entries</div></div>
<div class="summary-item"><div class="summary-value">{dev_summary['mean_deviation_pct']:.4f}%</div><div class="summary-label">Mean Deviation</div></div>
<div class="summary-item"><div class="summary-value">¥{dev_summary['total_slippage_cost']:.2f}</div><div class="summary-label">Total Slippage Cost</div></div>
<div class="summary-item"><div class="summary-value">{dev_summary['n_buy']} / {dev_summary['n_sell']}</div><div class="summary-label">Buys / Sells</div></div>
</div>

<div class="card"><h2>📈 Price Deviations</h2>
<table><tr><th>Symbol</th><th>Side</th><th>Signal Price</th><th>Fill Price</th><th>Deviation %</th><th>Shares</th></tr>
{dev_rows or '<tr><td colspan="6" style="text-align:center;color:#666;">No deviation data</td></tr>'}</table></div>

<div class="card"><h2>📜 Execution Ledger</h2>
<table><tr><th>Time</th><th>Symbol</th><th>Action</th><th>Shares</th><th>Price</th><th>Amount</th><th>Note</th></tr>
{ledger_rows or '<tr><td colspan="7" style="text-align:center;color:#666;">No ledger entries</td></tr>'}</table></div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>V4.1 Shadow Live Pipeline | Sandbox Only — No Real Trades</p>
<p>auto_apply=False | no_live_trade=True</p></div>
</body></html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    def generate_all_reports(self, output_dir: str = "") -> dict:
        """Generate all reports and return paths."""
        out_dir = output_dir or self.output_dir
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        return {
            "ledger": self.generate_ledger_report(
                os.path.join(out_dir, "shadow_execution_ledger.json") if out_dir else ""
            ),
            "deviation": self.generate_deviation_report(
                os.path.join(out_dir, "signal_vs_shadow_fill_report.json") if out_dir else ""
            ),
            "html": self.generate_html_report(
                os.path.join(out_dir, "shadow_pipeline_report.html") if out_dir else ""
            ),
        }

    def clear(self):
        """Clear all entries (for test reset)."""
        self.entries.clear()
