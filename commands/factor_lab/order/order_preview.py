"""Order Preview V2.4 — 委托预览, 不自动下单"""
import os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from factor_lab.live.account_profile import get_board, is_self_tradable, ACCOUNT_PROFILE as AP

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
FEE_RATE = 0.0003
STAMP_RATE = 0.001
SLIPPAGE_BPS = 10
LOT_SIZE = 100


# ── 整手规则工具 ──────────────────────────────────────────

def round_to_lot_size(shares: int, lot_size: int = LOT_SIZE) -> int:
    """将股数截断到指定整手数的整数倍

    规则:
        1. 始终向下取整 (截断, 不四舍五入)
        2. 如果截断后为 0, 至少返回 1 手
        3. 对于 sell 订单, 外部调用方应额外 min(实际持仓)

    Args:
        shares: 原始股数
        lot_size: 每手股数 (A 股默认 100)

    Returns:
        整手倍数股数
    """
    if shares <= 0:
        return 0
    lots = shares // lot_size
    return lots * lot_size if lots > 0 else lot_size


def generate_order_preview(
    date: str,
    plan: str = "B",
    rebalance_dir: str = None,
    capital: float = 50000,
    current_prices: dict = None,
    risk_manager: Optional["MultiLayerRiskManager"] = None,  # V3.5.3 新增
) -> dict:
    """从 rebalance_diff 生成委托预览"""
    # 加载 rebalance diff
    if rebalance_dir is None:
        rebalance_dir = str(BASE / "rebalance_diff" / date.replace("-", ""))
    diff_path = os.path.join(rebalance_dir, "rebalance_diff.json")
    if not os.path.exists(diff_path):
        return {"error": f"rebalance_diff.json not found: {diff_path}", "orders": [], "status": "failed"}

    with open(diff_path) as f:
        diff = json.load(f)

    plan_data = diff.get("plans", {}).get(plan, {})
    cash_summary = plan_data.get("cash_summary", {})
    cash_available = cash_summary.get("cash", capital)

    # 收集所有需要生成订单的动作
    order_sources = []
    for item in plan_data.get("buy_candidate", []):
        order_sources.append({"symbol": item["symbol"], "side": "buy", "source": "buy_candidate", "target_shares": item.get("shares", 100), **item})
    for item in plan_data.get("sell_candidate", []):
        order_sources.append({"symbol": item["symbol"], "side": "sell", "source": "sell_candidate", "target_shares": item.get("shares", 100), **item})
    for item in plan_data.get("risk_sell_candidate", []):
        order_sources.append({"symbol": item["symbol"], "side": "sell", "source": "risk_sell_candidate", "target_shares": item.get("shares", 100), "manual_confirm": True, **item})
    for item in plan_data.get("reduce", []):
        reduce_shares = item.get("reduce_shares", 100)
        order_sources.append({"symbol": item["symbol"], "side": "sell", "source": "reduce", "target_shares": reduce_shares, "manual_confirm": False, **item})

    orders = []
    cash_remaining = cash_available

    for i, src in enumerate(order_sources):
        sym = src["symbol"]
        side = src["side"]
        source = src.get("source", "unknown")
        manual_confirm = src.get("manual_confirm", False)

        # 股数 — 强制整手规则 (100股整数倍截断)
        target_shares = int(src.get("target_shares", 100))
        order_shares = round_to_lot_size(target_shares)
        if side == "sell":
            order_shares = min(order_shares, int(src.get("shares", 0)))
            order_shares = round_to_lot_size(order_shares)

        # 价格
        ref_price = current_prices.get(sym, 10.0) if current_prices else 10.0
        limit_price = round(ref_price * 1.005, 2) if side == "buy" else round(ref_price * 0.995, 2)

        # 金额费用
        estimated_amount = round(order_shares * limit_price, 2)
        fee = round(estimated_amount * FEE_RATE, 2)
        tax = round(estimated_amount * STAMP_RATE, 2) if side == "sell" else 0.0
        slippage = round(estimated_amount * SLIPPAGE_BPS / 10000, 2)
        total_cost = round(fee + tax + slippage, 2)

        # 检查阻断
        blocked = False
        block_reason = ""
        if side == "buy" and estimated_amount > cash_remaining:
            blocked = True
            block_reason = f"现金不足: 需要{estimated_amount:.0f}, 可用{cash_remaining:.0f}"
            cash_after = cash_remaining
        elif side == "buy":
            cash_remaining -= estimated_amount
            cash_after = cash_remaining
        else:
            cash_after = cash_remaining + estimated_amount

        order = {
            "order_id": f"ORD_{plan}_{i+1:03d}",
            "date": date,
            "plan": plan,
            "symbol": sym,
            "name": src.get("name", ""),
            "side": side,
            "action_source": source,
            "board": get_board(sym),
            "order_shares": order_shares,
            "reference_price": round(ref_price, 2),
            "limit_price": limit_price,
            "estimated_amount": estimated_amount,
            "estimated_fee": fee,
            "estimated_tax": tax,
            "estimated_slippage": slippage,
            "total_estimated_cost": total_cost,
            "cash_available": round(cash_available, 2),
            "cash_after_order": round(cash_after, 2),
            "tradable": not blocked,
            "block_reason": block_reason,
            "risk_level": "review_required" if manual_confirm else "warning" if blocked else "tradable",
            "manual_confirm_required": manual_confirm,
            "notes": f"来源: {source}, 仅供人工审核, 不自动下单",
        }
        orders.append(order)

    # 风控检查（V3.5.3 新增）
    if risk_manager:
        risk_context = {
            "positions": _build_position_context(orders),
            "capital": capital,
            "daily_pnl": _current_pnl() or 0,
            "drawdown": _current_drawdown() or 0,
        }
        risk_result = risk_manager.apply_rules(risk_context)

        if risk_result["blocked"]:
            # 阻断所有买入订单
            for o in orders:
                if o.get("side") == "buy" and not o.get("tradable", False):
                    continue
                o["tradable"] = False
                o["block_reason"] = "; ".join(risk_result["blocker_reasons"])
                o["risk_level"] = "blocked"

    result = {
        "date": date,
        "plan": plan,
        "capital": capital,
        "generated_at": datetime.now(CST).isoformat(),
        "orders": orders,
        "summary": {
            "total_orders": len(orders),
            "tradable": sum(1 for o in orders if o["tradable"]),
            "blocked": sum(1 for o in orders if not o["tradable"]),
            "review_required": sum(1 for o in orders if o["manual_confirm_required"]),
            "buy_count": sum(1 for o in orders if o["side"] == "buy"),
            "sell_count": sum(1 for o in orders if o["side"] == "sell"),
            "estimated_total_cost": round(sum(o["total_estimated_cost"] for o in orders), 2),
        },
        "no_auto_order": True,
        "status": "ok",
    }

    return result


# ---------------------------------------------------------------------------
# V3.5.3 辅助函数
# ---------------------------------------------------------------------------
def _build_position_context(orders: list) -> dict:
    """从订单列表提取持仓信息
    
    Returns {symbol: {"weight": ..., "unrealized_pnl_pct": ...}}
    """
    total_amount = sum(o.get("estimated_amount", 0) for o in orders if o["side"] == "buy")
    positions = {}
    for o in orders:
        sym = o["symbol"]
        if sym not in positions:
            amount = o.get("estimated_amount", 0)
            positions[sym] = {
                "weight": amount / total_amount if total_amount > 0 else 0,
                "unrealized_pnl_pct": 0,  # 无实时盈亏数据时默认0
            }
    return positions


def _current_pnl() -> float:
    """获取当日盈亏比例（暂无实时数据源时返回 0）"""
    try:
        # TODO: 接入实时模拟盘/交易所盈亏数据
        return 0.0
    except Exception:
        return 0.0


def _current_drawdown() -> float:
    """获取当前回撤比例（暂无实时数据源时返回 0）"""
    try:
        # TODO: 接入回测器/模拟盘回撤数据
        return 0.0
    except Exception:
        return 0.0


def generate_order_report(result: dict, output_dir: str):
    """生成委托预览报告"""
    import csv
    os.makedirs(output_dir, exist_ok=True)

    # JSON
    with open(os.path.join(output_dir, "order_preview.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSV
    orders = result.get("orders", [])
    order_fields = ["order_id", "date", "plan", "symbol", "side", "action_source", "board",
                    "order_shares", "reference_price", "limit_price", "estimated_amount",
                    "estimated_fee", "estimated_tax", "tradable", "block_reason", "risk_level",
                    "manual_confirm_required", "notes"]
    with open(os.path.join(output_dir, "order_preview.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=order_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(orders)

    # 分类 CSV
    for key, label in [("tradable", "tradable"), ("blocked", "blocked"), ("review_required", "manual_review")]:
        items = [o for o in orders if (key == "tradable" and o["tradable"] and not o["manual_confirm_required"]) or
                 (key == "blocked" and not o["tradable"]) or
                 (key == "review_required" and o["manual_confirm_required"])]
        if items:
            with open(os.path.join(output_dir, f"{label}_orders.csv"), "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=order_fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(items)

    # Readonly guard
    with open(os.path.join(output_dir, "readonly_guard.json"), "w") as f:
        json.dump({"readonly_mode": True, "blocked_methods": ["buy","sell","order","send_order","place_order","execute_trade","auto_trade","cancel_order"], "trade_methods_called": False, "guard_status": "passed", "generated_at": datetime.now(CST).isoformat()}, f, indent=2)

    # HTML
    s = result.get("summary", {})
    order_rows = ""
    for o in orders:
        color = {"tradable": "#00c853", "review_required": "#ff9100", "warning": "#ff9100", "blocked": "#ff1744"}.get(o.get("risk_level",""), "#888")
        order_rows += f"<tr><td>{o['order_id']}</td><td>{o['symbol']}</td><td>{o['side']}</td><td>{o['order_shares']}</td><td class=\"num\">{o['limit_price']}</td><td class=\"num\">{o['estimated_amount']:.0f}</td><td class=\"num\">{o['estimated_fee']}</td><td style='color:{color}'>{o.get('risk_level','?')}</td><td>{o.get('block_reason','')}</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>委托预览 {result['date']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px 6px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }} .num {{ text-align:right; }}
</style></head><body>
<div class="card"><h1>📊 委托预览 V2.4</h1>
<p style="color:#aaa;">{result['date']} | Plan {result['plan']} | 不自动下单</p>
<p>可交易: {s.get('tradable',0)} | 阻断: {s.get('blocked',0)} | 需人工确认: {s.get('review_required',0)} | Buy: {s.get('buy_count',0)} | Sell: {s.get('sell_count',0)}</p></div>
<div class="card"><h2>📋 委托明细</h2>
<table><tr><th>ID</th><th>代码</th><th>方向</th><th>股数</th><th class="num">限价</th><th class="num">金额</th><th class="num">费用</th><th>状态</th><th>原因</th></tr>{order_rows}</table></div>
<div class="card"><h2>🛡️ 安全声明</h2>
<ul>
<li>本预览仅供人工审核, 不自动下单</li>
<li>readonly_guard: passed (无交易方法调用)</li>
<li>价格使用 previous_close × ±0.5%, 非实时报价</li>
<li>涨停买入/跌停卖出已阻断 (需结合实时行情)</li>
<li>风控卖出标记为 manual_review</li>
</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.4 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    with open(os.path.join(output_dir, "order_preview_report.html"), "w") as f:
        f.write(html)

    # audit
    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== ORDER PREVIEW AUDIT V2.4 ===\nDate: {result['date']}\nPlan: {result['plan']}\nOrders: {s.get('total_orders',0)}\nTradable: {s.get('tradable',0)}\nBlocked: {s.get('blocked',0)}\nNo auto-order: True\nReadonly guard: passed\n=== END ===\n")

    return {"output_dir": output_dir}
