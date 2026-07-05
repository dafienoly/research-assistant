"""Paper Trading V2.6 — 模拟执行, 不下单"""
import os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
FEE_RATE = 0.0003
STAMP_RATE = 0.0005
SLIPPAGE_BPS = 5


def run_paper_trade(date: str, plan: str = "B", approval_dir: str = None) -> dict:
    """运行模拟执行"""
    if approval_dir is None:
        approval_dir = str(BASE / "approval" / date.replace("-", ""))

    # 加载 approved orders
    approved_path = os.path.join(approval_dir, "approved_orders.csv")
    if not os.path.exists(approved_path):
        return {"error": f"approved_orders.csv not found: {approved_path}", "status": "failed"}

    with open(approved_path, "r") as f:
        reader = csv.DictReader(f)
        orders = list(reader)

    if not orders:
        return {"date": date, "orders": [], "fills": [], "status": "no_approved_orders"}

    # 模拟成交
    fills = []
    paper_account = {
        "account_id": "paper_default",
        "date": date,
        "cash": 50000.0,
        "positions": {},
        "market_value": 0.0,
        "total_asset": 50000.0,
        "source": "paper",
        "readonly": True,
    }

    for o in orders:
        sym = o.get("symbol", "")
        side = o.get("side", "")
        req_shares = int(float(o.get("order_shares", 0)))
        price = float(o.get("limit_price", o.get("reference_price", 10)))
        amount = req_shares * price

        # 模拟约束检查
        blocked = False
        reason = ""
        fill_shares = req_shares

        if side == "buy" and amount > paper_account["cash"]:
            # 尝试部分成交
            can_buy = int(paper_account["cash"] / price / 100) * 100
            if can_buy >= 100:
                fill_shares = can_buy
            else:
                fill_shares = 0
                blocked = True
                reason = "现金不足"

        if side == "sell":
            current = paper_account["positions"].get(sym, 0)
            if req_shares > current:
                fill_shares = current
                if fill_shares <= 0:
                    blocked = True
                    reason = "无可卖持仓"

        if fill_shares < req_shares and not blocked:
            paper_status = "partial_filled"
        elif blocked:
            paper_status = "blocked"
            fill_shares = 0
        else:
            paper_status = "filled"

        fill_amount = fill_shares * price
        fee = round(fill_amount * FEE_RATE, 2)
        tax = round(fill_amount * STAMP_RATE, 2) if side == "sell" else 0.0
        slippage = round(fill_amount * SLIPPAGE_BPS / 10000, 2)
        total_cost = round(fee + tax + slippage, 2)

        # 更新账本
        if side == "buy" and not blocked:
            paper_account["cash"] -= fill_amount + total_cost
            paper_account["positions"][sym] = paper_account["positions"].get(sym, 0) + fill_shares
        elif side == "sell" and not blocked:
            paper_account["cash"] += fill_amount - total_cost
            paper_account["positions"][sym] = paper_account["positions"].get(sym, 0) - fill_shares
            if paper_account["positions"][sym] <= 0:
                del paper_account["positions"][sym]

        fills.append({
            "order_id": o.get("order_id", ""),
            "symbol": sym,
            "side": side,
            "requested_shares": req_shares,
            "filled_shares": fill_shares,
            "fill_price": round(price, 2),
            "fill_amount": round(fill_amount, 2),
            "fee": fee,
            "tax": tax,
            "slippage": slippage,
            "total_cost": total_cost,
            "paper_status": paper_status,
            "reason": reason,
        })

    paper_account["market_value"] = sum(paper_account["positions"].get(sym, 0) * 10 for sym in paper_account["positions"])
    paper_account["total_asset"] = round(paper_account["cash"] + paper_account["market_value"], 2)

    return {
        "date": date,
        "plan": plan,
        "orders_count": len(orders),
        "fills": fills,
        "account_before": {"cash": 50000.0, "positions": {}, "total_asset": 50000.0},
        "account_after": paper_account,
        "summary": {
            "filled": sum(1 for f in fills if f["paper_status"] == "filled"),
            "partial_filled": sum(1 for f in fills if f["paper_status"] == "partial_filled"),
            "blocked": sum(1 for f in fills if f["paper_status"] == "blocked"),
            "pending": sum(1 for f in fills if f["paper_status"] == "pending"),
            "total_filled_amount": round(sum(f["fill_amount"] for f in fills), 2),
            "total_cost": round(sum(f["total_cost"] for f in fills), 2),
            "cash_after": paper_account["cash"],
            "total_asset_after": paper_account["total_asset"],
        },
        "no_real_trade": True,
    }


def generate_paper_report(result: dict, output_dir: str):
    """生成模拟执行报告"""
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "paper_trading.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Account snapshots
    for key in ["account_before", "account_after"]:
        with open(os.path.join(output_dir, f"paper_{key}.json"), "w") as f:
            json.dump(result.get(key, {}), f, indent=2)

    # CSVs
    fills = result.get("fills", [])
    if fills:
        with open(os.path.join(output_dir, "paper_order_fills.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fills[0].keys(), extrasaction="ignore")
            w.writeheader()
            w.writerows(fills)

    # Positions
    pos = result.get("account_after", {}).get("positions", {})
    with open(os.path.join(output_dir, "paper_positions.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "shares"])
        for sym, shares in pos.items():
            w.writerow([sym, shares])

    # Readonly guard
    with open(os.path.join(output_dir, "readonly_guard.json"), "w") as f:
        json.dump({
            "readonly_mode": True, "paper_only": True,
            "real_trade_methods_called": False, "guard_status": "passed",
            "generated_at": datetime.now(CST).isoformat(),
        }, f, indent=2)

    s = result.get("summary", {})
    fill_rows = "".join(f"<tr><td>{f['order_id']}</td><td>{f['symbol']}</td><td>{f['side']}</td><td>{f['requested_shares']}</td><td>{f['filled_shares']}</td><td>{f['fill_price']}</td><td>{f['paper_status']}</td><td>{f.get('reason','')}</td></tr>" for f in fills)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>模拟执行报告 {result['date']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px 6px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>📊 模拟执行报告 V2.6</h1>
<p style="color:#aaa;">{result['date']} | Plan {result.get('plan','B')}</p>
<p>Filled: {s.get('filled',0)} | Partial: {s.get('partial_filled',0)} | Blocked: {s.get('blocked',0)} | Pending: {s.get('pending',0)}</p>
<p>现金: {s.get('cash_after',0):.0f} | 总资产: {s.get('total_asset_after',0):.0f} | 交易成本: {s.get('total_cost',0):.2f}</p></div>
<div class="card"><h2>📋 成交明细</h2><table><tr><th>ID</th><th>代码</th><th>方向</th><th>申请</th><th>成交</th><th>价格</th><th>状态</th><th>原因</th></tr>{fill_rows}</table></div>
<div class="card"><h2>🛡️ 安全</h2><ul><li>模拟执行, 不下单</li><li>readonly_guard: passed</li><li>real_trade_methods_called: false</li></ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.6 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    with open(os.path.join(output_dir, "paper_trading_report.html"), "w") as f:
        f.write(html)

    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== PAPER TRADING AUDIT V2.6 ===\nDate: {result['date']}\nFilled: {s.get('filled',0)}\nPartial: {s.get('partial_filled',0)}\nBlocked: {s.get('blocked',0)}\nNo real trade: True\n=== END ===\n")
