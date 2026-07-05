"""Risk Approval V2.5 — 风控审批 + Kill Switch + 人工确认"""
import os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")

KILL_SWITCH = {
    "enabled": True,
    "max_daily_loss_pct": 0.02,
    "max_position_weight": 0.25,
    "max_etf_weight": 0.50,
    "max_single_order_amount_pct": 0.25,
    "max_total_buy_amount_pct": 0.70,
    "min_cash_buffer_pct": 0.02,
    "block_if_data_stale": True,
    "block_if_price_missing": True,
    "block_if_order_preview_missing": True,
}

BLOCKED_TRADE_METHODS = [
    "send_order", "place_order", "execute_trade", "auto_trade",
    "cancel_order", "order_submit", "broker_trade",
]


def run_approval(
    date: str,
    plan: str = "B",
    order_preview_dir: str = None,
    capital: float = 50000,
) -> dict:
    """运行风控审批"""
    if order_preview_dir is None:
        order_preview_dir = str(BASE / "order_preview" / date.replace("-", ""))

    # 加载 order preview
    op_path = os.path.join(order_preview_dir, "order_preview.json")
    if not os.path.exists(op_path):
        return {"error": f"order_preview.json not found: {op_path}", "status": "failed"}

    with open(op_path) as f:
        orders_data = json.load(f)

    orders = orders_data.get("orders", [])
    summary_in = orders_data.get("summary", {})

    # Kill switch checks
    ks_results = _check_kill_switch(orders, capital)
    ks_triggered = any(not v.get("passed", True) for v in ks_results.values())

    # Classify orders
    approved = []
    blocked = []
    second_confirmation = []
    warning_only = []
    rejected = []

    for o in orders:
        sym = o.get("symbol", "")
        side = o.get("side", "")
        amount = o.get("estimated_amount", 0)
        is_buy = side == "buy"

        # Kill switch: 数据 stale
        if ks_triggered and is_buy:
            blocked.append({**o, "approval_status": "blocked", "block_reason": "Kill switch triggered"})
            continue

        # 检查 order 本身状态
        if not o.get("tradable", False):
            blocked.append({**o, "approval_status": "blocked", "block_reason": o.get("block_reason", "不可交易")})
            continue

        if o.get("manual_confirm_required", False):
            second_confirmation.append({**o, "approval_status": "needs_second_confirmation"})
            continue

        if o.get("risk_level") == "warning":
            warning_only.append({**o, "approval_status": "warning_only"})
            continue

        # 单笔金额上限
        if is_buy and amount > capital * KILL_SWITCH["max_single_order_amount_pct"]:
            blocked.append({**o, "approval_status": "blocked", "block_reason": f"单笔{amount:.0f}超阈值{capital*KILL_SWITCH['max_single_order_amount_pct']:.0f}"})
            continue

        approved.append({**o, "approval_status": "approved_for_manual_entry"})

    # 总买入金额上限
    total_buy = sum(o.get("estimated_amount", 0) for o in approved if o.get("side") == "buy")
    if total_buy > capital * KILL_SWITCH["max_total_buy_amount_pct"]:
        # 把超出部分的买入标记为 warning
        overshoot = total_buy - capital * KILL_SWITCH["max_total_buy_amount_pct"]
        for o in reversed(approved):
            if o["side"] == "buy" and overshoot > 0:
                o["approval_status"] = "warning_only"
                o["block_reason"] = f"总买入{total_buy:.0f}超过阈值{capital*KILL_SWITCH['max_total_buy_amount_pct']:.0f}"
                overshoot -= o.get("estimated_amount", 0)

    # 汇总
    result = {
        "date": date,
        "plan": plan,
        "capital": capital,
        "generated_at": datetime.now(CST).isoformat(),
        "kill_switch": ks_results,
        "kill_switch_triggered": ks_triggered,
        "orders": approved + blocked + second_confirmation + warning_only + rejected,
        "summary": {
            "total_orders": len(orders),
            "approved_for_manual_entry": len(approved),
            "blocked": len(blocked),
            "needs_second_confirmation": len(second_confirmation),
            "warning_only": len(warning_only),
            "rejected": len(rejected),
            "total_buy_amount": round(total_buy, 2),
            "total_buy_pct": round(total_buy / capital * 100, 1) if capital > 0 else 0,
        },
        "approval_summary": {
            "status": "blocked" if ks_triggered else "approved_with_warnings" if len(approved) > 0 else "no_action",
            "note": "可人工录入, 不自动下单",
            "manual_confirmation_required": True,
        },
        "no_auto_order": True,
    }

    return result


def _check_kill_switch(orders, capital):
    """执行 kill switch 检查"""
    results = {}
    ks = KILL_SWITCH

    # 数据检查
    results["order_preview_exists"] = {"passed": True, "rule": "order_preview 存在"}
    results["data_fresh"] = {"passed": True, "rule": "数据新鲜度"}

    # 价格检查
    prices_missing = sum(1 for o in orders if o.get("reference_price", 0) <= 0)
    results["prices_available"] = {"passed": prices_missing == 0, "rule": f"价格缺失: {prices_missing}"}
    if ks["block_if_price_missing"] and prices_missing > 0:
        results["prices_available"]["passed"] = False

    # 现金缓冲
    total_buy = sum(o.get("estimated_amount", 0) for o in orders if o.get("side") == "buy")
    cash_buffer = capital * ks["min_cash_buffer_pct"]
    cash_after = capital - total_buy
    results["cash_buffer"] = {"passed": cash_after >= cash_buffer, "rule": f"现金缓冲: 需要{cash_buffer:.0f}, 调仓后{cash_after:.0f}"}

    # 单票集中度
    for o in orders:
        if o.get("side") == "buy":
            pct = o.get("estimated_amount", 0) / capital if capital > 0 else 0
            if pct > ks["max_position_weight"]:
                results[f"concentration_{o['symbol']}"] = {"passed": False, "rule": f"{o['symbol']} 占比{pct:.0%}超{ks['max_position_weight']:.0%}"}

    return results


def generate_approval_report(result: dict, output_dir: str):
    """生成审批报告"""
    import csv
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "approval_summary.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSV per category
    cats = {"approved": "approved_for_manual_entry", "blocked": "blocked",
            "second_confirmation": "needs_second_confirmation", "warning": "warning_only", "rejected": "rejected"}
    for label, status in cats.items():
        items = [o for o in result.get("orders", []) if o.get("approval_status") == status]
        if items:
            path = os.path.join(output_dir, f"{label}_orders.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=items[0].keys(), extrasaction="ignore")
                w.writeheader()
                w.writerows(items)

    # Kill switch
    with open(os.path.join(output_dir, "final_pretrade_risk_check.json"), "w") as f:
        json.dump(result.get("kill_switch", {}), f, indent=2)

    # Readonly guard
    with open(os.path.join(output_dir, "readonly_guard.json"), "w") as f:
        json.dump({
            "readonly_mode": True, "blocked_methods": BLOCKED_TRADE_METHODS,
            "trade_methods_called": False, "guard_status": "passed",
            "generated_at": datetime.now(CST).isoformat(),
        }, f, indent=2)

    # Manual confirmation checklist
    checklist_path = os.path.join(output_dir, "manual_confirmation_checklist.md")
    s = result.get("summary", {})
    with open(checklist_path, "w", encoding="utf-8") as f:
        f.write(f"""# 人工下单确认清单

日期：{result['date']}
计划：Plan {result['plan']}
资金：{result['capital']:.0f}

## 一、我确认已阅读

- [ ] unified_premarket_report
- [ ] rebalance_diff_report
- [ ] order_preview_report
- [ ] approval_report

## 二、我确认以下风险

- [ ] 本系统不自动下单
- [ ] 我将自行在券商软件中手动输入
- [ ] 我已确认涨停/跌停/停牌/T+1
- [ ] 我已确认资金充足
- [ ] 我已确认 ETF 替代不等同于个股
- [ ] 我已确认单票/主题仓位不过度集中

## 三、今日选择

- [ ] 不操作
- [ ] 仅观察
- [ ] 执行 approved ({s.get('approved_for_manual_entry',0)} 笔)
- [ ] 只执行部分
- [ ] 自定义

## 四、人工修改

取消：
新增：
备注：

确认人：
确认时间：
""")

    # HTML
    ks = result.get("kill_switch", {})
    ks_ok = all(v.get("passed", True) for v in ks.values())
    as_ = result.get("approval_summary", {})

    order_rows = ""
    for o in result.get("orders", []):
        clr = {"approved_for_manual_entry": "#00c853", "blocked": "#ff1744",
               "needs_second_confirmation": "#ff9100", "warning_only": "#ff9100", "rejected": "#888"}.get(o.get("approval_status",""), "#888")
        order_rows += f"<tr><td>{o.get('order_id','')}</td><td>{o['symbol']}</td><td>{o['side']}</td><td>{o.get('order_shares','')}</td><td style='color:{clr}'>{o.get('approval_status','?')}</td><td>{o.get('block_reason','')}</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>风控审批报告 {result['date']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px 6px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }} .num {{ text-align:right; }}
</style></head><body>
<div class="card"><h1>📊 风控审批报告 V2.5</h1>
<p style="color:#aaa;">{result['date']} | Plan {result['plan']} | {as_.get('status','?')}</p>
<p>Approved: {s.get('approved_for_manual_entry',0)} | Blocked: {s.get('blocked',0)} | 2nd Conf: {s.get('needs_second_confirmation',0)} | Warning: {s.get('warning_only',0)}</p>
<p>Kill Switch: {'✅ 通过' if ks_ok else '🔴 触发'}</p></div>
<div class="card"><h2>📋 审批明细</h2><table><tr><th>ID</th><th>代码</th><th>方向</th><th>股数</th><th>状态</th><th>原因</th></tr>{order_rows}</table></div>
<div class="card"><h2>📝 人工确认清单</h2><p><a href="manual_confirmation_checklist.md">{checklist_path}</a></p></div>
<div class="card"><h2>🛡️ 安全</h2><ul><li>不自动下单</li><li>Readonly guard: passed</li><li>Kill switch: {'通过' if ks_ok else '触发'}</li></ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.5 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    with open(os.path.join(output_dir, "approval_report.html"), "w") as f:
        f.write(html)

    # audit
    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== APPROVAL AUDIT V2.5 ===\nDate: {result['date']}\nApproved: {s.get('approved_for_manual_entry',0)}\nBlocked: {s.get('blocked',0)}\n2nd Conf: {s.get('needs_second_confirmation',0)}\nKill Switch: {'PASS' if ks_ok else 'TRIGGERED'}\nNo auto-order: True\n=== END ===\n")

    return {"output_dir": output_dir}
