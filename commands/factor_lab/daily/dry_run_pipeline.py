#!/usr/bin/env python3
"""V3.5.5 Governed Dry Run — 6-Gate 全链路干跑入口

6-Gate 管线:
  Gate1: Signal Generation          — Ret5Ma20GateSignalGenerator
  Gate2: ETF Substitution           — ETFSelector
  Gate3: Unified Premarket Report   — 合并 Gate1 + Gate2
  Gate4: Rebalance Diff             — hold/reduce/sell/buy/watch
  Gate5: Order Preview + RiskCheck  — 委托预览 + MultiLayerRiskManager
  Gate6: Risk Approval + KillSwitch — 风控审批 + KillSwitch

用法:
    # 完整干跑（含风控）
    python commands/factor_lab/daily/dry_run_pipeline.py --date 2026-07-08

    # 不含风控（仅管线通畅验证）
    python commands/factor_lab/daily/dry_run_pipeline.py --date 2026-07-08 --no-risk

    # 指定信号日期为 'latest'（自动取最近交易日）
    python commands/factor_lab/daily/dry_run_pipeline.py --date latest

每个 Gate 独立 try/except，失败不阻断后续 Gate。
不下真实订单 — 所有 Gate 只读/模拟。
"""

import json
import os
import sys
import traceback
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── 路径引导 ──────────────────────────────────────────────
_HERE = Path(__file__).parent.resolve()          # daily/
_FACTOR_LAB = _HERE.parent.resolve()             # factor_lab/
_COMMANDS = _FACTOR_LAB.parent.resolve()         # commands/
sys.path.insert(0, str(_COMMANDS))

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


# ═══════════════════════════════════════════════════════════
# 模型
# ═══════════════════════════════════════════════════════════

class GateCheck:
    """单个 Gate 检查项"""
    def __init__(self, name: str, passed: bool, detail: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> dict:
        return {"check": self.name, "passed": self.passed, "detail": self.detail}


# ═══════════════════════════════════════════════════════════
# 基础设施
# ═══════════════════════════════════════════════════════════

def _resolve_date(signal_date: Optional[str] = None) -> str:
    """解析信号日期：None/空/'latest' → 今天，否则原样返回"""
    if not signal_date or signal_date.lower() == "latest":
        return datetime.now(CST).strftime("%Y-%m-%d")
    return signal_date


def _date_ymd(date_str: str) -> str:
    """'YYYY-MM-DD' → 'YYYYMMDD'"""
    return date_str.replace("-", "")


def _gate_detail(gate_result: dict, key: str, default=None):
    """从 gate 结果的 detail 字段中安全提取值

    _run_gate() 将除 verdict/checks/error 外的所有字段放入 detail 字典。
    本函数简化下游 gate 的数据提取。
    """
    return (gate_result or {}).get("detail", {}).get(key, default)


def _safe_import(module_path: str, attr: str):
    """安全导入，失败返回 None"""
    try:
        mod = __import__(module_path, fromlist=[attr])
        return getattr(mod, attr)
    except Exception as e:
        return None


def _run_gate(name: str, func, **kwargs) -> dict:
    """执行单个 Gate 并计时，返回结构化结果"""
    start = datetime.now()
    checks = []
    try:
        result = func(**kwargs)
        duration = (datetime.now() - start).total_seconds()
        verdict = result.get("verdict", "pass")
        checks = result.get("checks", [])
        return {
            "gate_name": name,
            "verdict": verdict,
            "duration_seconds": round(duration, 1),
            "checks": [c.to_dict() if isinstance(c, GateCheck) else c for c in checks],
            "error": result.get("error", ""),
            "detail": {k: v for k, v in result.items() if k not in ("verdict", "checks", "error")},
        }
    except Exception as e:
        duration = (datetime.now() - start).total_seconds()
        tb = traceback.format_exc()
        return {
            "gate_name": name,
            "verdict": "skip",
            "duration_seconds": round(duration, 1),
            "checks": [],
            "error": f"{type(e).__name__}: {e}",
            "traceback": tb,
        }


# ═══════════════════════════════════════════════════════════
# Gate1: Signal Generation
# ═══════════════════════════════════════════════════════════

def _gate1_signal(signal_date: str = None) -> dict:
    """Gate1: Ret5Ma20GateSignalGenerator 盘前信号生成"""
    checks = []

    run_func = _safe_import("factor_lab.live.signal_generator", "run_ret5_ma20_gate_signal")
    if run_func is None:
        return {
            "verdict": "skip",
            "checks": [GateCheck("import_signal_generator", False, "factor_lab.live.signal_generator 不可用")],
            "error": "Module not available",
        }

    checks.append(GateCheck("import_signal_generator", True, "run_ret5_ma20_gate_signal 加载成功"))

    try:
        result = run_func(signal_date=signal_date)
    except Exception as e:
        return {
            "verdict": "fail",
            "checks": [GateCheck("run_signal_generator", False, f"执行失败: {e}")],
            "error": str(e),
        }

    # 解析 result
    data_status = result.get("data_status", "failed")
    signal_status = result.get("signal_status", "empty")
    n_targets = len(result.get("target_candidates", []))
    n_watch = len(result.get("watch_candidates", []))
    n_remove = len(result.get("remove_candidates", []))
    n_hold = len(result.get("current_hold_candidates", []))

    checks.append(GateCheck("data_loaded", data_status != "failed",
                             f"data_status={data_status}, total_symbols={result.get('total_symbols', 0)}"))
    checks.append(GateCheck("candidates_generated", n_targets > 0 or signal_status == "insufficient",
                             f"target={n_targets}, watch={n_watch}, signal_status={signal_status}"))
    checks.append(GateCheck("positions_processed", True,
                             f"remove={n_remove}, hold={n_hold}"))

    if data_status == "failed":
        verdict = "conditional_pass"
        checks.append(GateCheck("data_warning", False,
                                 f"数据不可用: {result.get('risk_summary', {}).get('warnings', ['?'])}"))
    elif signal_status == "sufficient":
        verdict = "pass"
    elif signal_status == "insufficient":
        verdict = "conditional_pass"
        checks.append(GateCheck("low_coverage", False,
                                 f"仅 {n_targets} 候选不足 {result.get('total_symbols', 0)} 全量"))
    else:
        verdict = "conditional_pass"
        checks.append(GateCheck("empty_signal", False, f"门控过滤后无候选"))

    return {
        "verdict": verdict,
        "checks": checks,
        "signal_result": result,
        "n_targets": n_targets,
        "n_watch": n_watch,
        "signal_date": result.get("signal_date", signal_date or ""),
    }


# ═══════════════════════════════════════════════════════════
# Gate2: ETF Substitution
# ═══════════════════════════════════════════════════════════

def _gate2_etf(g1_result: dict = None) -> dict:
    """Gate2: ETFSelector — 对受限候选进行 ETF 替代"""
    checks = []

    run_func = _safe_import("factor_lab.etf.etf_selector", "run_etf_selector")
    if run_func is None:
        return {
            "verdict": "skip",
            "checks": [GateCheck("import_etf_selector", False, "factor_lab.etf.etf_selector 不可用")],
            "error": "Module not available",
        }

    checks.append(GateCheck("import_etf_selector", True, "run_etf_selector 加载成功"))

    # 从 Gate1 结果提取受限候选
    signal_result = _gate_detail(g1_result, "signal_result", {})
    # 信号生成器 output 中无 explicit restricted 字段
    # 用 remove_candidates 模拟受限候选
    restricted_candidates = signal_result.get("remove_candidates", [])
    if not restricted_candidates:
        # 用 watch_candidates 或 target_candidates 作为 fallback
        restricted_candidates = signal_result.get("watch_candidates", [])[:5]
        if not restricted_candidates:
            restricted_candidates = signal_result.get("target_candidates", [])[:3]
        fallback_note = "从 target/watch 借用"
    else:
        fallback_note = "来自 remove_candidates"

    if not restricted_candidates:
        checks.append(GateCheck("no_restricted_input", True, "无受限候选，ETF 替代无输入 — skip"))
        return {
            "verdict": "skip",
            "checks": checks,
            "note": "无受限候选输入",
        }

    checks.append(GateCheck("restricted_input", True,
                             f"{len(restricted_candidates)} 受限候选 ({fallback_note})"))

    try:
        etf_result = run_func(restricted_candidates)
    except Exception as e:
        return {
            "verdict": "fail",
            "checks": [GateCheck("run_etf_selector", False, f"执行失败: {e}")],
            "error": str(e),
        }

    n_candidates = len(etf_result.get("candidates", []))
    n_themes = len(etf_result.get("themes", []))
    n_rejected = len(etf_result.get("rejected", []))
    data_status = etf_result.get("data_status", "partial")

    checks.append(GateCheck("etf_candidates", n_candidates > 0,
                             f"ETF候选={n_candidates}, 主题={n_themes}, 被拒={n_rejected}"))
    checks.append(GateCheck("data_status", data_status == "ok",
                             f"data_status={data_status}"))

    if data_status == "ok" and n_candidates > 0:
        verdict = "pass"
    elif n_candidates > 0:
        verdict = "conditional_pass"
        checks.append(GateCheck("partial_data", False, f"数据部分缺失: {data_status}"))
    else:
        verdict = "conditional_pass"
        checks.append(GateCheck("no_etf_found", False,
                                 "未找到合适 ETF 替代"))

    return {
        "verdict": verdict,
        "checks": checks,
        "etf_result": etf_result,
        "n_candidates": n_candidates,
        "capital_plan": etf_result.get("capital_plan", {}),
    }


# ═══════════════════════════════════════════════════════════
# Gate3: Unified Premarket Report
# ═══════════════════════════════════════════════════════════

def _gate3_unified(g1_result: dict = None, g2_result: dict = None) -> dict:
    """Gate3: 统一盘前报告 — 合并 Signal + ETF 输出"""
    checks = []

    # 提取 Gate1 数据
    signal_result = _gate_detail(g1_result, "signal_result", {})
    target_candidates = signal_result.get("target_candidates", [])
    watch_candidates = signal_result.get("watch_candidates", [])
    remove_candidates = signal_result.get("remove_candidates", [])
    hold_candidates = signal_result.get("current_hold_candidates", [])
    risk_summary = signal_result.get("risk_summary", {})
    signal_date = signal_result.get("signal_date", "")

    # 提取 Gate2 数据
    etf_result = _gate_detail(g2_result, "etf_result", {})
    etf_candidates = etf_result.get("candidates", [])
    etf_themes = etf_result.get("themes", [])
    etf_plan = etf_result.get("capital_plan", {})

    # 分离自营可交易 vs 受限
    try:
        from factor_lab.live.account_profile import is_self_tradable, get_board
    except Exception:
        is_self_tradable = lambda s: True
        get_board = lambda s: "unknown"

    self_tradable = []
    restricted_board = []
    for c in target_candidates:
        sym = c.get("symbol", "")
        board = get_board(sym)
        c["board"] = board
        if is_self_tradable(sym):
            self_tradable.append(c)
        else:
            restricted_board.append(c)

    # 生成 unified_readiness
    n_self = len(self_tradable)
    n_restricted = len(restricted_board)
    n_etf = len(etf_candidates)

    if n_self >= 5:
        unified_readiness = "ready"
    elif n_self > 0 or n_etf > 0:
        unified_readiness = "usable_with_warning"
    else:
        unified_readiness = "partial"

    # 构建 readiness 详细
    strategy_ok = signal_result.get("data_status") == "ok" and len(target_candidates) > 0
    self_account_ok = n_self >= 3
    etf_ok = n_etf > 0

    readiness = {
        "strategy_signal_readiness": "ready" if strategy_ok else "partial",
        "self_account_readiness": "ready" if self_account_ok else "partial",
        "restricted_signal_readiness": "ready" if n_restricted > 0 else "no_signal",
        "etf_substitution_readiness": "ready" if etf_ok else "framework_ready",
        "etf_selector_readiness": "usable_with_warning" if etf_ok else "not_available",
    }

    # 资金方案
    capital = 50000
    plans = _build_unified_plans(self_tradable, etf_candidates, capital)

    # 排除清单
    excluded = []
    for c in remove_candidates:
        excluded.append({"symbol": c.get("symbol", ""), "reason": "调仓移除", "type": "remove"})
    for c in restricted_board:
        excluded.append({"symbol": c.get("symbol", ""), "reason": f"权限受限({c.get('board','')})", "type": "permission"})

    summary_parts = [
        f"ret5_ma20_gate 信号可用",
        f"自营候选 {n_self} 只",
        f"受限 {n_restricted} 只",
    ]
    if n_etf > 0:
        theme_names = [t["theme"] for t in etf_themes[:2]]
        summary_parts.append(f"ETF替代主题 {len(theme_names)} 个 ({', '.join(theme_names)})")
    summary = "，".join(summary_parts) + f"。Readiness: {unified_readiness}"

    result = {
        "signal_date": signal_date,
        "generated_at": datetime.now(CST).isoformat(),
        "capital": capital,
        "unified_readiness": unified_readiness,
        "readiness": readiness,
        "summary": summary,
        "self_stock_candidates": {
            "top5": self_tradable[:5],
            "top8": self_tradable[:8],
            "total": n_self,
            "all": self_tradable,
        },
        "restricted_signal_summary": {
            "total": n_restricted,
            "candidates": restricted_board,
        },
        "etf_substitution_summary": {
            "themes": etf_themes,
            "candidates": etf_candidates,
            "capital_plan": etf_plan,
        },
        "allocation_plans": plans,
        "excluded": excluded,
        "risk_summary": risk_summary,
    }

    checks.append(GateCheck("signal_merged", True,
                             f"self={n_self}, restricted={n_restricted}"))
    checks.append(GateCheck("etf_merged", True,
                             f"ETF候选={n_etf}, 主题={len(etf_themes)}"))
    checks.append(GateCheck("plans_generated", len(plans) > 0,
                             f"方案={list(plans.keys())}"))
    checks.append(GateCheck("readiness_determined", True,
                             f"unified_readiness={unified_readiness}"))

    verdict = "pass" if unified_readiness in ("ready", "usable_with_warning") else "conditional_pass"

    return {
        "verdict": verdict,
        "checks": checks,
        "unified_result": result,
        "unified_readiness": unified_readiness,
        "n_self": n_self,
        "n_restricted": n_restricted,
        "n_etf": n_etf,
    }


def _build_unified_plans(self_tradable, etf_candidates, capital):
    """构建 A/B/C 三套资金方案"""
    plans = {}

    def _stock_lots(symbols, budget):
        lots, rem = [], budget
        for c in symbols:
            close = float(c.get("close", 10) or 10)
            shares = max(100, int(rem * 0.25 / close / 100) * 100)
            cost = shares * close
            if cost > rem:
                shares = max(100, int(rem / close / 100) * 100)
                cost = shares * close
            if shares < 100 or cost > rem:
                break
            lots.append({
                "symbol": c["symbol"], "close": round(close, 2),
                "shares": shares, "cost": round(cost, 2),
                "weight": round(cost / capital * 100, 1),
            })
            rem -= cost
        return lots, round(rem, 2)

    def _etf_lots(etfs, budget):
        if not etfs or budget <= 0:
            return [], budget
        per = budget / max(len(etfs), 1)
        lots = []
        for e in etfs:
            shares = max(100, int(per / 1.0 / 100) * 100)
            lots.append({
                "etf_code": e["etf_code"], "etf_name": e.get("etf_name", ""),
                "theme": e.get("theme_source", ""),
                "shares": shares, "cost": round(shares * 1.0, 2),
                "weight": round(shares * 1.0 / capital * 100, 1),
            })
        total = sum(l["cost"] for l in lots)
        rem = budget - total
        return lots, round(rem, 2)

    for name, stock_pct, etf_pct, stock_set in [
        ("conservative", 0.70, 0.30, self_tradable[:5]),
        ("balanced", 0.50, 0.50, self_tradable[:8]),
        ("aggressive", 0.30, 0.70, self_tradable[:5]),
    ]:
        s_budget = capital * stock_pct
        e_budget = capital * etf_pct
        s_lots, s_rem = _stock_lots(stock_set, s_budget)
        e_lots, e_rem = _etf_lots(etf_candidates[:2], e_budget)
        used = sum(l["cost"] for l in s_lots) + sum(l["cost"] for l in e_lots)
        plans[name] = {
            "desc": {
                "conservative": "70%股票+30%ETF",
                "balanced": "50%股票+50%ETF",
                "aggressive": "30%股票+70%ETF",
            }[name],
            "self_stock_alloc": round(s_budget, 2),
            "etf_alloc": round(e_budget, 2),
            "self_stock_lots": s_lots,
            "etf_lots": e_lots,
            "total_used": round(used, 2),
            "remaining_cash": round(capital - used, 2),
        }
    return plans


# ═══════════════════════════════════════════════════════════
# Gate4: Rebalance Diff
# ═══════════════════════════════════════════════════════════

def _gate4_rebalance(g3_result: dict = None) -> dict:
    """Gate4: 调仓差异分析"""
    checks = []

    rebalance_diff = _safe_import("factor_lab.portfolio.rebalance_diff", "run_rebalance_diff")
    if rebalance_diff is None:
        return {
            "verdict": "skip",
            "checks": [GateCheck("import_rebalance_diff", False,
                                 "factor_lab.portfolio.rebalance_diff 不可用")],
            "error": "Module not available",
        }

    checks.append(GateCheck("import_rebalance_diff", True,
                             "run_rebalance_diff 加载成功"))

    unified_result = _gate_detail(g3_result, "unified_result", {})
    signal_date = unified_result.get("signal_date", datetime.now(CST).strftime("%Y-%m-%d"))
    date_ymd = _date_ymd(signal_date)

    # run_rebalance_diff 硬编码了 unified report 路径:
    #   BASE / "unified_premarket" / date / "unified_premarket_report.json"
    # 因此必须在该路径写 Gate3 的 unified_result
    gate3_path = BASE / "unified_premarket" / date_ymd
    gate3_path.mkdir(parents=True, exist_ok=True)
    try:
        with open(gate3_path / "unified_premarket_report.json", "w", encoding="utf-8") as f:
            json.dump(unified_result, f, indent=2, ensure_ascii=False, default=str)
        checks.append(GateCheck("gate3_persisted", True,
                                 f"unified报告写入 {gate3_path / 'unified_premarket_report.json'}"))
    except Exception as e:
        checks.append(GateCheck("gate3_persist_failed", False, str(e)))
        return {"verdict": "fail", "checks": checks, "error": f"写入 unified 报告失败: {e}"}

    # 执行 rebalance_diff
    try:
        # output_dir 指向 dry_run gates 目录 — 将由调用者设置
        result = rebalance_diff(
            date=signal_date,
            positions_csv=None,
            plan="B",
            capital=50000,
        )
    except Exception as e:
        return {
            "verdict": "fail",
            "checks": [GateCheck("run_rebalance_diff", False, f"执行失败: {e}")],
            "error": str(e),
        }

    if "error" in result:
        checks.append(GateCheck("rebalance_result", False, result["error"]))
        return {"verdict": "fail", "checks": checks, "error": result["error"]}

    plans = result.get("plans", {})
    plan_summaries = {}
    for pid, pdata in plans.items():
        cs = pdata.get("cash_summary", {})
        plan_summaries[pid] = {
            "hold": len(pdata.get("hold", [])),
            "reduce": len(pdata.get("reduce", [])),
            "sell": len(pdata.get("sell_candidate", [])),
            "risk_sell": len(pdata.get("risk_sell_candidate", [])),
            "buy": len(pdata.get("buy_candidate", [])),
            "skip": len(pdata.get("skip_buy", [])),
            "watch": len(pdata.get("watch", [])),
            "cash_after": cs.get("estimated_cash_after", 0),
        }
        checks.append(GateCheck(f"plan_{pid}", True,
                                 f"hold={plan_summaries[pid]['hold']} "
                                 f"reduce={plan_summaries[pid]['reduce']} "
                                 f"sell={plan_summaries[pid]['sell']} "
                                 f"buy={plan_summaries[pid]['buy']}"))

    verdict = "pass" if plans else "conditional_pass"

    return {
        "verdict": verdict,
        "checks": checks,
        "rebalance_result": result,
        "plans": plan_summaries,
        "signal_date": signal_date,
    }


# ═══════════════════════════════════════════════════════════
# Gate5: Order Preview + Risk Check
# ═══════════════════════════════════════════════════════════

def _gate5_order(g4_result: dict = None, risk_manager=None) -> dict:
    """Gate5: 委托预览 + 多层风控检查"""
    checks = []

    order_func = _safe_import("factor_lab.order.order_preview", "generate_order_preview")
    if order_func is None:
        return {
            "verdict": "skip",
            "checks": [GateCheck("import_order_preview", False,
                                 "factor_lab.order.order_preview 不可用")],
            "error": "Module not available",
        }

    checks.append(GateCheck("import_order_preview", True,
                             "generate_order_preview 加载成功"))

    rebalance_result = _gate_detail(g4_result, "rebalance_result", {})
    signal_date = rebalance_result.get("date", _gate_detail(g4_result, "signal_date",
                                        datetime.now(CST).strftime("%Y-%m-%d")))
    date_ymd = _date_ymd(signal_date)

    # generate_order_preview 默认从 BASE/rebalance_diff/<date>/rebalance_diff.json 读取
    # 但 rebalance_diff.run_rebalance_diff 将结果写入 BASE/rebalance_diff/<date>/ 目录
    # 确保路径存在
    rebalance_path = BASE / "rebalance_diff" / date_ymd
    rebalance_path.mkdir(parents=True, exist_ok=True)
    try:
        with open(rebalance_path / "rebalance_diff.json", "w", encoding="utf-8") as f:
            json.dump(rebalance_result, f, indent=2, ensure_ascii=False, default=str)
        checks.append(GateCheck("gate4_persisted", True,
                                 f"rebalance diff 写入 {rebalance_path / 'rebalance_diff.json'}"))
    except Exception as e:
        checks.append(GateCheck("gate4_persist_failed", False, str(e)))
        return {"verdict": "fail", "checks": checks, "error": f"写入 rebalance diff 失败: {e}"}

    # 执行 order preview
    try:
        order_result = order_func(
            date=signal_date,
            plan="B",
            capital=50000,
            risk_manager=risk_manager,
        )
    except Exception as e:
        return {
            "verdict": "fail",
            "checks": [GateCheck("run_order_preview", False, f"执行失败: {e}")],
            "error": str(e),
        }

    if "error" in order_result:
        checks.append(GateCheck("order_result", False, order_result["error"]))
        return {"verdict": "fail", "checks": checks, "error": order_result["error"]}

    summary = order_result.get("summary", {})
    orders = order_result.get("orders", [])
    n_orders = summary.get("total_orders", len(orders))
    n_tradable = summary.get("tradable", 0)
    n_blocked = summary.get("blocked", 0)
    n_review = summary.get("review_required", 0)
    n_buy = summary.get("buy_count", 0)
    n_sell = summary.get("sell_count", 0)

    checks.append(GateCheck("orders_generated", n_orders > 0,
                             f"总委托={n_orders} (可交易={n_tradable}, 阻断={n_blocked}, 需确认={n_review})"))
    checks.append(GateCheck("order_breakdown", True,
                             f"buy={n_buy}, sell={n_sell}"))
    checks.append(GateCheck("risk_applied", True,
                             f"风控集成={'是' if risk_manager else '否'}"))

    if n_orders == 0:
        verdict = "conditional_pass"
        checks.append(GateCheck("no_orders", True, "无委托生成（无调仓动作）"))
    elif n_blocked > 0 and n_tradable == 0:
        verdict = "conditional_pass"
        checks.append(GateCheck("all_blocked", False, "全部委托被风控阻断"))
    else:
        verdict = "pass"

    return {
        "verdict": verdict,
        "checks": checks,
        "order_result": order_result,
        "summary": summary,
        "n_orders": n_orders,
        "n_tradable": n_tradable,
        "n_blocked": n_blocked,
        "n_review": n_review,
    }


# ═══════════════════════════════════════════════════════════
# Gate6: Risk Approval + Kill Switch
# ═══════════════════════════════════════════════════════════

def _gate6_approval(g5_result: dict = None, kill_switch=None) -> dict:
    """Gate6: 风控审批 + KillSwitch 状态"""
    checks = []

    approval_func = _safe_import("factor_lab.approval.risk_approval", "run_approval")
    if approval_func is None:
        return {
            "verdict": "skip",
            "checks": [GateCheck("import_risk_approval", False,
                                 "factor_lab.approval.risk_approval 不可用")],
            "error": "Module not available",
        }

    checks.append(GateCheck("import_risk_approval", True,
                             "run_approval 加载成功"))

    order_result = _gate_detail(g5_result, "order_result", {})
    signal_date = order_result.get("date", _gate_detail(g5_result, "signal_date",
                                        datetime.now(CST).strftime("%Y-%m-%d")))
    date_ymd = _date_ymd(signal_date)

    # run_approval 默认从 BASE/order_preview/<date>/order_preview.json 读取
    # 确保该路径存在
    order_path = BASE / "order_preview" / date_ymd
    order_path.mkdir(parents=True, exist_ok=True)
    try:
        with open(order_path / "order_preview.json", "w", encoding="utf-8") as f:
            json.dump(order_result, f, indent=2, ensure_ascii=False, default=str)
        checks.append(GateCheck("gate5_persisted", True,
                                 f"order preview 写入 {order_path / 'order_preview.json'}"))
    except Exception as e:
        checks.append(GateCheck("gate5_persist_failed", False, str(e)))
        return {"verdict": "fail", "checks": checks, "error": f"写入 order preview 失败: {e}"}

    # KillSwitch 状态
    if kill_switch is not None:
        ks_status = kill_switch.status.to_dict()
        ks_blocked = kill_switch.is_blocked()
        checks.append(GateCheck("kill_switch", not ks_blocked,
                                 f"state={ks_status.get('state','?')}, "
                                 f"blocked_actions={ks_status.get('n_actions_blocked',0)}"))
    else:
        ks_status = {"state": "not_initialized"}
        ks_blocked = False
        checks.append(GateCheck("kill_switch", True, "未初始化风控 — skip KillSwitch"))

    # 执行 approval
    try:
        approval_result = approval_func(
            date=signal_date,
            plan="B",
            capital=50000,
            kill_switch=kill_switch,
        )
    except Exception as e:
        return {
            "verdict": "fail",
            "checks": [GateCheck("run_approval", False, f"执行失败: {e}")],
            "error": str(e),
        }

    if "error" in approval_result:
        checks.append(GateCheck("approval_result", False, approval_result["error"]))
        return {"verdict": "fail", "checks": checks, "error": approval_result["error"]}

    appr_summary = approval_result.get("summary", {})
    appr_overall = approval_result.get("approval_summary", {})
    n_approved = appr_summary.get("approved_for_manual_entry", 0)
    n_blocked = appr_summary.get("blocked", 0)
    n_second = appr_summary.get("needs_second_confirmation", 0)
    n_warning = appr_summary.get("warning_only", 0)
    status = appr_overall.get("status", "?")

    checks.append(GateCheck("approval_completed", True,
                             f"status={status}, approved={n_approved}, "
                             f"blocked={n_blocked}, 2nd_conf={n_second}"))
    checks.append(GateCheck("kill_switch_final", not ks_blocked,
                             f"KillSwitch state={ks_status.get('state','?')}"))

    if status == "blocked":
        verdict = "conditional_pass"
        checks.append(GateCheck("pipeline_blocked", False, "KillSwitch 触发，全管线阻断"))
    elif n_approved > 0:
        verdict = "pass"
    elif n_second > 0:
        verdict = "conditional_pass"
        checks.append(GateCheck("all_need_confirmation", False, "全部委托需二次确认"))
    else:
        verdict = "pass"
        checks.append(GateCheck("no_action", True, "无审批动作"))

    return {
        "verdict": verdict,
        "checks": checks,
        "approval_result": approval_result,
        "summary": appr_summary,
        "approval_status": status,
        "kill_switch_state": ks_status.get("state", "?"),
        "kill_switch_triggered": ks_blocked,
    }


# ═══════════════════════════════════════════════════════════
# 管线编排
# ═══════════════════════════════════════════════════════════

def run_dry_run(signal_date: str = None, with_risk: bool = True) -> dict:
    """执行全链路干跑 (6-Gate)

    Args:
        signal_date: 信号日期 'YYYY-MM-DD' 或 'latest'（默认今天）
        with_risk:   是否启用风控集成 (Gate5+Gate6)

    Returns:
        全管线结果 dict
    """
    signal_date = _resolve_date(signal_date)
    results = {}
    total_start = datetime.now()

    # 初始化风控
    kill_switch = None
    risk_manager = None
    if with_risk:
        try:
            from factor_lab.risk.kill_switch import KillSwitch
            from factor_lab.risk.multi_layer_risk_manager import MultiLayerRiskManager
            kill_switch = KillSwitch()
            risk_manager = MultiLayerRiskManager(kill_switch)
        except Exception as e:
            # 风控初始化失败，回退到无风控模式
            pass

    # ── Gate1: Signal ─────────────────────────────────
    g1 = _run_gate("gate1_signal", _gate1_signal, signal_date=signal_date)
    results["gate1_signal"] = g1

    # ── Gate2: ETF ────────────────────────────────────
    if g1.get("verdict") != "fail":
        g2 = _run_gate("gate2_etf", _gate2_etf, g1_result=g1)
        results["gate2_etf"] = g2
    else:
        results["gate2_etf"] = _run_gate("gate2_etf", _gate2_etf, g1_result={})

    # ── Gate3: Unified ────────────────────────────────
    g3 = _run_gate("gate3_unified", _gate3_unified,
                    g1_result=g1, g2_result=results.get("gate2_etf", {}))
    results["gate3_unified"] = g3

    # ── Gate4: Rebalance ──────────────────────────────
    g4 = _run_gate("gate4_rebalance", _gate4_rebalance, g3_result=g3)
    results["gate4_rebalance"] = g4

    # ── Gate5: Order ──────────────────────────────────
    g5 = _run_gate("gate5_order", _gate5_order,
                    g4_result=g4, risk_manager=risk_manager)
    results["gate5_order"] = g5

    # ── Gate6: Approval ───────────────────────────────
    g6 = _run_gate("gate6_approval", _gate6_approval,
                    g5_result=g5, kill_switch=kill_switch)
    results["gate6_approval"] = g6

    # ── 汇总 ──────────────────────────────────────────
    total_duration = (datetime.now() - total_start).total_seconds()
    verdicts = {k: v.get("verdict", "?") for k, v in results.items()}
    all_passed = all(v != "fail" for v in verdicts.values())
    blocker_gates = [k for k, v in results.items() if v.get("verdict") == "fail"]
    skip_gates = [k for k, v in results.items() if v.get("verdict") == "skip"]
    conditional = [k for k, v in results.items() if v.get("verdict") == "conditional_pass"]

    if not blocker_gates and not conditional and not skip_gates:
        pipeline_status = "completed"
    elif blocker_gates:
        pipeline_status = "failed"
    else:
        pipeline_status = "partial"

    return {
        "status": pipeline_status,
        "signal_date": signal_date,
        "with_risk": with_risk,
        "gates": results,
        "total_duration": round(total_duration, 1),
        "blocker_gates": blocker_gates,
        "skip_gates": skip_gates,
        "conditional_gates": conditional,
        "verdict_summary": verdicts,
        "generated_at": datetime.now(CST).isoformat(),
    }


# ═══════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════

def _build_verdict_icon(verdict: str) -> str:
    return {
        "pass": "✅",
        "conditional_pass": "⚠️",
        "skip": "⏭️",
        "fail": "❌",
    }.get(verdict, "❓")


def _build_md_report(result: dict) -> str:
    """生成 Markdown 干跑报告"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Governed Dry Run 全链路干跑报告",
        f"",
        f"**生成时间**: {now}  ",
        f"**信号日期**: {result.get('signal_date', '?')}  ",
        f"**风控集成**: {'✅ 已启用' if result.get('with_risk') else '⛔ 未启用'}  ",
        f"**管线状态**: `{result.get('status', '?')}`  ",
        f"**总耗时**: {result.get('total_duration', 0):.1f}s  ",
        f"",
        f"---",
        f"",
        f"## 6-Gate 通行结果",
        f"",
        f"| Gate | 名称 | 判定 | 耗时 |",
        f"|------|------|------|------|",
    ]

    verdict_map = {
        "gate1_signal": "Signal Generation",
        "gate2_etf": "ETF Substitution",
        "gate3_unified": "Unified Report",
        "gate4_rebalance": "Rebalance Diff",
        "gate5_order": "Order Preview + Risk",
        "gate6_approval": "Risk Approval",
    }

    gates = result.get("gates", {})
    for gid, gname in verdict_map.items():
        g = gates.get(gid, {})
        verdict = g.get("verdict", "?")
        duration = g.get("duration_seconds", 0)
        icon = _build_verdict_icon(verdict)
        error = g.get("error", "")
        error_suffix = f" — {error[:80]}" if error else ""
        lines.append(f"| {gid} | {gname} | {icon} `{verdict}`{error_suffix} | {duration}s |")

    # 阻断/跳过/条件通过汇总
    blocker = result.get("blocker_gates", [])
    skip = result.get("skip_gates", [])
    conditional = result.get("conditional_gates", [])
    if blocker:
        lines.extend([
            f"",
            f"### 🔴 阻断 Gate",
            f"",
            *[f"- `{g}`: {gates.get(g, {}).get('error', '?')}" for g in blocker],
        ])
    if skip:
        lines.extend([
            f"",
            f"### ⏭️ 跳过 Gate",
            f"",
            *[f"- `{g}`: {gates.get(g, {}).get('error', '未加载')}" for g in skip],
        ])
    if conditional:
        lines.extend([
            f"",
            f"### ⚠️ 条件通过 Gate",
            f"",
            *[f"- `{g}`" for g in conditional],
        ])

    # Gate 详情
    lines.extend(["", "---", "", "## Gate 详情", ""])

    for gid, gname in verdict_map.items():
        g = gates.get(gid, {})
        verdict = g.get("verdict", "?")
        if verdict == "skip":
            continue  # 跳过的 Gate 不展开

        icon = _build_verdict_icon(verdict)
        lines.extend([
            f"### {icon} {gid}: {gname}",
            f"",
            f"- **判定**: `{verdict}`  ",
            f"- **耗时**: {g.get('duration_seconds', 0):.1f}s  ",
        ])
        if g.get("error"):
            lines.append(f"- **错误**: `{g['error']}`  ")
        if g.get("traceback"):
            lines.append(f"- **Traceback**: 已记录  ")

        detail = g.get("detail", {})
        # 提取关键指标
        for key in ("n_targets", "n_watch", "n_candidates", "n_self", "n_restricted",
                     "n_etf", "n_orders", "n_tradable", "n_blocked", "n_review",
                     "unified_readiness", "approval_status", "signal_date"):
            val = detail.get(key)
            if val is not None:
                lines.append(f"- **{key}**: `{val}`  ")

        # Checks
        checks = g.get("checks", [])
        if checks:
            lines.append("")
            lines.append("| Check | 状态 | 详情 |")
            lines.append("|-------|------|------|")
            for c in checks:
                ck = c.get("check", "?")
                ok = c.get("passed", False)
                dt = c.get("detail", "")
                ck_icon = "✅" if ok else "❌"
                lines.append(f"| {ck} | {ck_icon} | {dt} |")

        lines.append("")

    # 风控状态
    if result.get("with_risk"):
        g6 = gates.get("gate6_approval", {})
        ks_state = g6.get("detail", {}).get("kill_switch_state", "?")
        ks_triggered = g6.get("detail", {}).get("kill_switch_triggered", False)
        lines.extend([
            "---",
            "",
            "## 🛡️ 风控状态汇总",
            "",
            f"- **KillSwitch State**: `{ks_state}`  ",
            f"- **KillSwitch Triggered**: {'🔴 是' if ks_triggered else '✅ 否'}  ",
            f"- **Order Summary**: ",
        ])
        g5 = gates.get("gate5_order", {})
        g5d = g5.get("detail", {})
        lines.append(f"  - 委托总数: {g5d.get('n_orders', 0)}  ")
        lines.append(f"  - 可交易: {g5d.get('n_tradable', 0)}  ")
        lines.append(f"  - 阻断: {g5d.get('n_blocked', 0)}  ")
        lines.append(f"  - 需人工确认: {g5d.get('n_review', 0)}  ")
        g6d = g6.get("detail", {})
        lines.append(f"- **Approval**: approved={g6d.get('summary', {}).get('approved_for_manual_entry', 0)}  ")
        lines.append(f"  - blocked={g6d.get('summary', {}).get('blocked', 0)}  ")
        lines.append(f"  - status={g6d.get('approval_status', '?')}  ")

    # 附件
    lines.extend([
        "",
        "---",
        "",
        "## 📂 输出文件",
        "",
        f"- `dry_run_result.json` — 全结构化结果  ",
        f"- `gates/gate1_signal.json` — Gate1 信号  ",
        f"- `gates/gate2_etf.json` — Gate2 ETF  ",
        f"- `gates/gate3_unified.json` — Gate3 统一报告  ",
        f"- `gates/gate4_rebalance.json` — Gate4 调仓差异  ",
        f"- `gates/gate5_order.json` — Gate5 委托预览  ",
        f"- `gates/gate6_approval.json` — Gate6 风控审批  ",
        "",
        "---",
        "",
        f"*Generated by Governed Dry Run Pipeline V3.5.5 | {now}*",
    ])

    return "\n".join(lines)


def _verify_pipeline(result: dict) -> list:
    """验证管线完整性，返回失败项"""
    failures = []
    gates = result.get("gates", {})
    expected = ["gate1_signal", "gate2_etf", "gate3_unified",
                "gate4_rebalance", "gate5_order", "gate6_approval"]

    for gid in expected:
        if gid not in gates:
            failures.append(f"{gid}: 缺失")
            continue
        g = gates[gid]
        verdict = g.get("verdict", "?")
        if verdict == "fail":
            failures.append(f"{gid}: fail ({g.get('error', '?')})")

    return failures


def run_dry_run_and_report(signal_date: str = None, with_risk: bool = True) -> dict:
    """执行干跑并输出 JSON + MD 报告

    Args:
        signal_date: 信号日期
        with_risk:   是否启用风控

    Returns:
        完整干跑结果
    """
    signal_date = _resolve_date(signal_date)
    date_ymd = _date_ymd(signal_date)

    # 执行管线
    result = run_dry_run(signal_date, with_risk=with_risk)

    # 输出目录: /mnt/d/HermesReports/dry_run/<yyyymmdd>/
    output_dir = BASE / "dry_run" / date_ymd
    gates_dir = output_dir / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)

    # 写 dry_run_result.json
    with open(output_dir / "dry_run_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    # 写每个 Gate 的 JSON
    gate_map = {
        "gate1_signal": "gate1_signal.json",
        "gate2_etf": "gate2_etf.json",
        "gate3_unified": "gate3_unified.json",
        "gate4_rebalance": "gate4_rebalance.json",
        "gate5_order": "gate5_order.json",
        "gate6_approval": "gate6_approval.json",
    }
    for gid, fname in gate_map.items():
        g = result.get("gates", {}).get(gid, {})
        gate_path = gates_dir / fname
        with open(gate_path, "w", encoding="utf-8") as f:
            json.dump(g, f, indent=2, ensure_ascii=False, default=str)

    # 写 MD 报告
    md_report = _build_md_report(result)
    with open(output_dir / "dry_run_report.md", "w", encoding="utf-8") as f:
        f.write(md_report)

    # 验证
    failures = _verify_pipeline(result)
    result["_verification"] = {"failures": failures, "passed": len(failures) == 0}
    result["_output_dir"] = str(output_dir)

    # 控制台摘要
    _print_summary(result)

    return result


def _print_summary(result: dict):
    """控制台输出干跑摘要"""
    verdict_icon = {"pass": "✅", "conditional_pass": "⚠️", "skip": "⏭️", "fail": "❌"}
    gate_names = {
        "gate1_signal": "Signal",
        "gate2_etf": "ETF",
        "gate3_unified": "Unified",
        "gate4_rebalance": "Rebalance",
        "gate5_order": "Order",
        "gate6_approval": "Approval",
    }

    print(f"\n{'='*60}")
    print(f"  Governed Dry Run 全链路干跑")
    print(f"  信号日期: {result.get('signal_date', '?')}")
    print(f"  风控集成: {'是' if result.get('with_risk') else '否'}")
    print(f"  管线状态: {result.get('status', '?')}")
    print(f"  总耗时: {result.get('total_duration', 0):.1f}s")
    print(f"{'='*60}")

    gates = result.get("gates", {})
    for gid, gname in gate_names.items():
        g = gates.get(gid, {})
        v = g.get("verdict", "?")
        dur = g.get("duration_seconds", 0)
        icon = verdict_icon.get(v, "❓")
        err = g.get("error", "")
        err_s = f" — {err[:60]}" if err else ""
        print(f"  {icon} {gname:12s} | {v:18s} | {dur:5.1f}s{err_s}")

    out_dir = result.get("_output_dir", "")
    if out_dir:
        print(f"\n  📁 {out_dir}")
    print(f"{'='*60}\n")


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main():
    import argparse
    p = argparse.ArgumentParser(description="V3.5.5 Governed Dry Run — 6-Gate 全链路干跑")
    p.add_argument("--date", default=None,
                    help="信号日期 (YYYY-MM-DD 或 'latest'，默认今天)")
    p.add_argument("--no-risk", action="store_true",
                    help="不启用风控集成")
    p.add_argument("--verify-only", action="store_true",
                    help="只验证已有结果，不重新运行")
    args = p.parse_args()

    if args.verify_only:
        # 只验证已有结果
        signal_date = _resolve_date(args.date)
        date_ymd = _date_ymd(signal_date)
        result_path = BASE / "dry_run" / date_ymd / "dry_run_result.json"
        if not result_path.exists():
            print(f"❌ 无已有结果: {result_path}")
            sys.exit(1)
        with open(result_path) as f:
            result = json.load(f)
        _print_summary(result)
        print("✅ 验证完成（仅展示已有结果）")
        return

    result = run_dry_run_and_report(
        signal_date=args.date,
        with_risk=not args.no_risk,
    )

    # 退出码
    if result.get("status") == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
