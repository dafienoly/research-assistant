#!/usr/bin/env python3
"""每日复盘报告生成器 — 测试/验证脚本

创建模拟数据（如果需要），然后运行生成器验证输出。

用法:
    python test_daily_review.py
    python test_daily_review.py --date 2026-07-08
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路径引导 ──────────────────────────────────────────────
_HERE = Path(__file__).parent.resolve()
_REPORTS = _HERE.parent.resolve() if _HERE.name == "reports" else _HERE
_FACTOR_LAB = _REPORTS.parent.resolve() if _REPORTS.name == "factor_lab" else _REPORTS
_COMMANDS = _FACTOR_LAB.parent.resolve() if _FACTOR_LAB.name == "factor_lab" else _FACTOR_LAB
if str(_COMMANDS) not in sys.path:
    sys.path.insert(0, str(_COMMANDS))

CST = timezone(timedelta(hours=8))
DATA_BASE = Path("/mnt/d/HermesData")
REPORT_BASE = Path("/mnt/d/HermesReports")


def ensure_mock_data(date_str: str):
    """如果真实数据不存在，创建模拟数据用于测试。"""
    ymd = date_str.replace("-", "")

    # ── Paper Trading 模拟数据 ──
    pt_dir = DATA_BASE / "paper_trading"
    pt_dir.mkdir(parents=True, exist_ok=True)

    equity_path = pt_dir / "equity.csv"
    if not equity_path.exists():
        lines = ["date,total_value,daily_return,cash\n"]
        base = 100000.0
        vals = [base]
        for i in range(1, 22):
            ret = 0.01 * (0.5 + (i % 7) * 0.1 - 0.3)
            if i == 21:
                ret = 0.028
            nv = vals[-1] * (1 + ret)
            vals.append(round(nv, 2))
        for i in range(21):
            from datetime import timedelta
            d = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=20 - i)).strftime("%Y-%m-%d")
            lines.append(f"{d},{vals[i]},{vals[i]/vals[max(0,i-1)]-1 if i>0 else 0},{round(base*0.3,2)}\n")
        with open(equity_path, "w") as f:
            f.writelines(lines)
        print(f"  ✓ 创建 Paper Trading 模拟数据: {equity_path} ({len(lines)-1} 行)")

    portfolio_path = pt_dir / "portfolio.json"
    if not portfolio_path.exists():
        portfolio = {
            "capital": 100000,
            "cash": 52340.12,
            "holdings": {
                "002396": {"shares": 1200, "avg_cost": 25.80, "last_price": 26.45},
                "000938": {"shares": 900, "avg_cost": 30.12, "last_price": 31.48},
                "000977": {"shares": 500, "avg_cost": 68.50, "last_price": 71.06},
                "688019": {"shares": 100, "avg_cost": 290.00, "last_price": 300.02},
                "000333": {"shares": 800, "avg_cost": 76.30, "last_price": 79.12},
            },
            "updated_at": f"{date_str}T15:30:00+08:00",
        }
        with open(portfolio_path, "w") as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False)
        print(f"  ✓ 创建模拟持仓: {portfolio_path} ({len(portfolio['holdings'])} 只)")

    trades_path = pt_dir / "trades.jsonl"
    if not trades_path.exists():
        trades = [
            {"date": date_str, "symbol": "002396", "side": "buy", "shares": 1200,
             "price": 26.45, "amount": 31740.00, "fee": 95.22, "total_cost": 31835.22},
            {"date": date_str, "symbol": "000938", "side": "buy", "shares": 900,
             "price": 31.48, "amount": 28332.00, "fee": 85.00, "total_cost": 28417.00},
            {"date": date_str, "symbol": "688019", "side": "buy", "shares": 100,
             "price": 300.02, "amount": 30002.00, "fee": 90.01, "total_cost": 30092.01},
        ]
        with open(trades_path, "w") as f:
            for t in trades:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        print(f"  ✓ 创建模拟成交: {trades_path} ({len(trades)} 笔)")

    # ── Shadow Forward 模拟数据 ──
    sf_dir = REPORT_BASE / "shadow_forward" / f"run_{ymd}"
    sf_dir.mkdir(parents=True, exist_ok=True)

    sf_json_path = sf_dir / "shadow_forward.json"
    if not sf_json_path.exists():
        sf_data = {
            "run_id": f"run_{ymd}",
            "generated_at": f"{date_str}T08:00:00+08:00",
            "comparisons": [
                {
                    "candidate": "ret5_ma20_gate_watch",
                    "shadow_id": f"shd_{ymd}_a1b2",
                    "baseline_return_pct": 12.34,
                    "shadow_return_pct": 14.56,
                    "baseline_sharpe": 1.23,
                    "shadow_sharpe": 1.35,
                    "verdict": "promote_candidate_watch",
                    "n_days": 21,
                },
                {
                    "candidate": "alpha_momentum_v3",
                    "shadow_id": f"shd_{ymd}_c3d4",
                    "baseline_return_pct": 8.50,
                    "shadow_return_pct": 7.80,
                    "baseline_sharpe": 0.95,
                    "shadow_sharpe": 0.88,
                    "verdict": "no_material_improvement",
                    "n_days": 15,
                },
                {
                    "candidate": "mean_reversion_etf",
                    "shadow_id": f"shd_{ymd}_e5f6",
                    "baseline_return_pct": 5.20,
                    "shadow_return_pct": 6.10,
                    "baseline_sharpe": 0.72,
                    "shadow_sharpe": 0.78,
                    "verdict": "promote_candidate_watch",
                    "n_days": 10,
                },
            ],
            "risk_events": [
                {
                    "date": date_str,
                    "candidate_name": "ret5_ma20_gate_watch",
                    "symbol": "000001",
                    "risk_rule": "max_drawdown",
                    "risk_level": "warning",
                    "baseline_triggered": False,
                    "shadow_triggered": True,
                    "action": "noted",
                    "evidence": "shadow dd exceeded threshold",
                }
            ],
            "decision_logs": [
                {
                    "date": date_str,
                    "candidate_name": "ret5_ma20_gate_watch",
                    "baseline_selected_symbols": 20,
                    "shadow_selected_symbols": 22,
                    "added_symbols": 3,
                    "removed_symbols": 1,
                    "expected_turnover_pct": 0.15,
                    "blocked_orders": 0,
                    "confidence": 0.7,
                    "conclusion": "promote_candidate_watch",
                }
            ],
            "status": "completed",
        }
        with open(sf_json_path, "w") as f:
            json.dump(sf_data, f, indent=2, ensure_ascii=False)
        print(f"  ✓ 创建 Shadow Forward 模拟数据: {sf_json_path}")

    # ── Risk Sentinel 已存在? ──
    rs_path = DATA_BASE / "risk_sentinel" / "state.json"
    if not rs_path.exists():
        print(f"  ℹ️ Risk Sentinel state.json 存在 (使用真实数据)")
    else:
        print(f"  ✓ Risk Sentinel state.json 存在")

    # ── Dry Run 已存在? ──
    dr_path = REPORT_BASE / "dry_run" / ymd / "dry_run_result.json"
    if dr_path.exists():
        print(f"  ✓ Dry Run 结果存在: {dr_path}")
    else:
        # 创建模拟 dry run
        dr_dir = REPORT_BASE / "dry_run" / ymd
        dr_dir.mkdir(parents=True, exist_ok=True)
        dr_data = {
            "status": "partial",
            "signal_date": date_str,
            "with_risk": False,
            "gates": {
                "gate1_signal": {
                    "gate_name": "gate1_signal",
                    "verdict": "pass",
                    "duration_seconds": 3.9,
                    "checks": [
                        {"check": "import_signal_generator", "passed": True,
                         "detail": "run_ret5_ma20_gate_signal 加载成功"},
                        {"check": "data_loaded", "passed": True,
                         "detail": "data_status=ok, total_symbols=63"},
                        {"check": "candidates_generated", "passed": True,
                         "detail": "target=20, watch=1, signal_status=sufficient"},
                    ],
                    "error": "",
                    "detail": {"n_targets": 20, "n_watch": 1, "signal_date": date_str},
                },
                "gate2_etf": {
                    "gate_name": "gate2_etf",
                    "verdict": "conditional_pass",
                    "duration_seconds": 0.3,
                    "checks": [
                        {"check": "import_etf_selector", "passed": True,
                         "detail": "run_etf_selector 加载成功"},
                        {"check": "etf_candidates", "passed": True,
                         "detail": "ETF候选=1, 主题=1"},
                    ],
                    "error": "",
                    "detail": {"n_candidates": 1},
                },
                "gate3_unified": {
                    "gate_name": "gate3_unified",
                    "verdict": "pass",
                    "duration_seconds": 0.1,
                    "checks": [
                        {"check": "signal_merged", "passed": True,
                         "detail": "self=13, restricted=7"},
                        {"check": "plans_generated", "passed": True,
                         "detail": "方案=['conservative', 'balanced', 'aggressive']"},
                    ],
                    "error": "",
                },
                "gate4_rebalance": {
                    "gate_name": "gate4_rebalance",
                    "verdict": "pass",
                    "duration_seconds": 1.2,
                    "checks": [
                        {"check": "rebalance_diff", "passed": True,
                         "detail": "hold=5, buy=3, sell=1"},
                    ],
                    "error": "",
                },
                "gate5_order": {
                    "gate_name": "gate5_order",
                    "verdict": "pass",
                    "duration_seconds": 0.8,
                    "checks": [
                        {"check": "order_preview", "passed": True,
                         "detail": "8 orders generated"},
                    ],
                    "error": "",
                },
                "gate6_risk": {
                    "gate_name": "gate6_risk",
                    "verdict": "skip",
                    "duration_seconds": 0.0,
                    "checks": [],
                    "error": "风控模块未启用",
                },
            },
        }
        with open(dr_path, "w") as f:
            json.dump(dr_data, f, indent=2, ensure_ascii=False)
        print(f"  ✓ 创建 Dry Run 模拟数据: {dr_path}")


def main():
    parser = argparse.ArgumentParser(description="每日复盘报告 — 测试验证")
    parser.add_argument("--date", type=str, default=None,
                        help="日期 (YYYY-MM-DD), 默认当天 CST")
    parser.add_argument("--no-mock", action="store_true",
                        help="不创建模拟数据，仅使用真实数据")
    args = parser.parse_args()

    date_str = args.date or datetime.now(CST).strftime("%Y-%m-%d")
    ymd = date_str.replace("-", "")

    print("=" * 60)
    print(f"  每日复盘报告生成器 — 验证")
    print(f"  日期: {date_str}")
    print("=" * 60)

    # 创建模拟数据
    if not args.no_mock:
        print("\n📦 检查/创建模拟数据:")
        ensure_mock_data(date_str)
    else:
        print("\n📦 使用现有数据（不创建模拟数据）")

    # 运行生成器
    print("\n⚙️  运行每日复盘报告生成器...")
    from factor_lab.reports.daily_review import DailyReviewGenerator

    gen = DailyReviewGenerator(date_str=date_str)
    review = gen.generate()

    # ── 验证输出 ──
    print("\n" + "=" * 60)
    print("📋 验证结果")
    print("=" * 60)

    # 1. 结构检查
    assert "sections" in review, "缺少 sections"
    assert "paper_trading" in review["sections"], "缺少 paper_trading"
    assert "shadow_forward" in review["sections"], "缺少 shadow_forward"
    assert "risk_sentinel" in review["sections"], "缺少 risk_sentinel"
    assert "dry_run" in review["sections"], "缺少 dry_run"
    assert "summary" in review, "缺少 summary"
    assert "date" in review, "缺少 date"
    print("  ✅ JSON 结构完整")

    # 2. 文件输出
    json_path = gen.output_dir / "daily_review.json"
    html_path = gen.output_dir / "daily_review.html"
    assert json_path.exists(), f"JSON 未生成: {json_path}"
    assert html_path.exists(), f"HTML 未生成: {html_path}"
    print(f"  ✅ JSON 已生成: {json_path} ({json_path.stat().st_size:,} bytes)")
    print(f"  ✅ HTML 已生成: {html_path} ({html_path.stat().st_size:,} bytes)")

    # 3. JSON 可解析
    with open(json_path) as f:
        loaded = json.load(f)
    assert loaded["sections"]["paper_trading"]["status"] in ("ok", "no_data", "partial", "error")
    print(f"  ✅ JSON 可解析，paper_trading.status = {loaded['sections']['paper_trading']['status']}")

    # 4. HTML 包含关键元素
    html_content = html_path.read_text()
    assert "<!DOCTYPE html>" in html_content, "HTML DOCTYPE 缺失"
    assert "每日复盘" in html_content, "标题缺失"
    assert date_str in html_content, f"日期 {date_str} 未出现在 HTML"
    assert "emoji" in html_content.lower() or "📊" in html_content, "缺少 emoji 头"
    print(f"  ✅ HTML 包含必要元素")

    # 5. 摘要
    summary = review.get("summary", {})
    print(f"\n  📊 报告摘要:")
    for k, v in summary.items():
        print(f"     {k}: {v}")

    # 6. 各章节状态
    print(f"\n  📂 各章节状态:")
    for section_name, section_data in review["sections"].items():
        status = section_data.get("status", "?")
        note = section_data.get("note", "")
        print(f"     {section_name}: [{status}] {note}")

    print("\n" + "=" * 60)
    print("✅ 每日复盘报告生成器验证通过")
    print(f"📁 输出目录: {gen.output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
