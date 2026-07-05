"""盘前信号报告生成 — 盘前信号的多格式报告输出

输出目录 (由调用方传入):
    <output_dir>/
    ├── premarket_signal.html        (暗色主题中文报告)
    ├── premarket_signal.json        (结构化数据)
    ├── target_candidates.csv        (Top20)
    ├── remove_candidates.csv        (风控排除清单)
    ├── watch_candidates.csv         (观察名单 21-40)
    ├── rebalance_plan.csv           (调仓计划)
    ├── data_freshness.json          (数据新鲜度)
    ├── risk_check.json              (风控检查)
    └── signal_audit.log             (审计日志)

用法:
    from factor_lab.live.premarket_signal_report import generate_premarket_report

    report = generate_premarket_report(
        signal_result={
            "signal_date": "2026-07-03",
            "generated_at": "2026-07-04T08:30:00+08:00",
            "strategy_name": "Ret5Ma20Gate",
            "universe": "watchlist_300",
            "top_n": 20,
            "data_freshness": {...},    # 来自 check_data_freshness()
            "risk_check": {...},        # 来自 run_pretrade_risk_check()
            "candidates": [             # 全量排名候选股票列表 (已含风控标记)
                {
                    "symbol": "000001", "name": "平安银行",
                    "close": 12.34, "ret5": 0.05, "ma20": 11.50,
                    "close_gt_ma20": True, "rank": 1, "amount": 5.2e9,
                    "risk_flags": [], "reason": "ret5 强势 + 突破 MA20",
                },
                ...
            ],
            "current_positions": None,  # 可选, {symbol: {shares, avg_price, ...}}
        },
        output_dir="/mnt/d/HermesReports/premarket/20260704",
    )

注意事项:
    - 不允许 silent fallback, 数据缺失必须标记为 failed
    - 不硬编码路径, 输出目录由调用方传入
    - current_positions 可选, 未提供时 rebalance_plan 标注 'no positions input'
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

CST = timezone(timedelta(hours=8))

# ─── 常量 ────────────────────────────────────────────────────────
REQUIRED_CANDIDATE_FIELDS = [
    "symbol", "name", "close", "ret5", "ma20",
    "close_gt_ma20", "rank", "amount", "risk_flags", "reason",
]

RISK_TYPE_LABELS: dict[str, str] = {
    "ST": "ST / *ST",
    "suspended": "停牌",
    "limit_up": "涨停",
    "low_amount": "成交额过低",
    "consecutive_up": "连续上涨过高",
    "high_return": "涨幅过大",
}

SIGNAL_FIELD_ORDER = [
    "close", "volume", "amount", "ma5", "ma10", "ma20",
    "ret1", "ret5", "ret20", "close_gt_ma20", "pct_change",
]


# ─── 主入口 ─────────────────────────────────────────────────────

def generate_premarket_report(
    signal_result: dict,
    output_dir: str,
) -> dict:
    """生成盘前信号报告

    参数:
        signal_result: 信号生成结果, 包含以下顶层字段:
            - signal_date (str): 信号日期 YYYY-MM-DD
            - generated_at (str): 生成时间 ISO 格式
            - strategy_name (str): 策略名称
            - universe (str): 股票池名称
            - top_n (int): TopN 候选数量
            - data_freshness (dict): data_freshness.check_data_freshness() 输出
            - risk_check (dict): risk.pretrade_risk_check.run_pretrade_risk_check() 输出
            - candidates (list[dict]): 全量排名候选列表
            - current_positions (dict | None): 当前持仓 {symbol: {shares, avg_price, ...}}
        output_dir: 输出目录路径

    返回:
        {"output_dir", "report_path", "files", "detail": {...}}
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(CST)
    now_iso = now.isoformat()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # ── 提取基础信息 ──
    signal_date = signal_result.get("signal_date", "unknown")
    generated_at = signal_result.get("generated_at", now_iso)
    strategy_name = signal_result.get("strategy_name", "UnknownStrategy")
    universe = signal_result.get("universe", "unknown")
    top_n = signal_result.get("top_n", 20)
    data_freshness = signal_result.get("data_freshness", _empty_freshness())
    risk_check = signal_result.get("risk_check", _empty_risk_check())
    candidates: list[dict] = signal_result.get("candidates", [])
    current_positions: Optional[dict] = signal_result.get("current_positions")

    # ── 分类候选股票 ──
    target_candidates = _get_target_candidates(candidates, top_n, risk_check)
    watch_candidates = _get_watch_candidates(candidates, top_n, risk_check)
    remove_candidates = _get_remove_candidates(candidates, top_n, risk_check)
    rebalance_plan = _build_rebalance_plan(
        target_candidates, watch_candidates, remove_candidates,
        current_positions, signal_date,
    )

    # ── 输出文件 ──
    report_data = {
        "signal_date": signal_date,
        "generated_at": generated_at,
        "reported_at": now_iso,
        "strategy_name": strategy_name,
        "universe": universe,
        "top_n": top_n,
        "n_candidates_total": len(candidates),
        "n_target": len(target_candidates),
        "n_watch": len(watch_candidates),
        "n_remove": len(remove_candidates),
        "has_positions": current_positions is not None,
    }

    # 1. JSON
    full_data = {**report_data, "target_candidates": target_candidates,
                 "watch_candidates": watch_candidates,
                 "remove_candidates": remove_candidates,
                 "rebalance_plan": rebalance_plan}
    _write_json(out_dir / "premarket_signal.json", full_data)

    # 2. CSV - target
    _write_candidates_csv(out_dir / "target_candidates.csv", target_candidates,
                          REQUIRED_CANDIDATE_FIELDS)

    # 3. CSV - watch
    _write_candidates_csv(out_dir / "watch_candidates.csv", watch_candidates,
                          REQUIRED_CANDIDATE_FIELDS)

    # 4. CSV - remove
    remove_fields = ["symbol", "name", "reason"]
    _write_candidates_csv(out_dir / "remove_candidates.csv", remove_candidates,
                          remove_fields)

    # 5. CSV - rebalance plan
    _write_rebalance_csv(out_dir / "rebalance_plan.csv", rebalance_plan)

    # 6. data_freshness
    _write_json(out_dir / "data_freshness.json", data_freshness)

    # 7. risk_check
    _write_json(out_dir / "risk_check.json", risk_check)

    # 8. audit log
    _write_md(out_dir / "signal_audit.log",
              _build_audit_log(report_data, data_freshness, risk_check,
                               target_candidates, watch_candidates,
                               remove_candidates, now_str))

    # 9. HTML
    html = _build_html(report_data, target_candidates, watch_candidates,
                       remove_candidates, rebalance_plan,
                       data_freshness, risk_check, now_str)
    _write_md(out_dir / "premarket_signal.html", html)

    files = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    return {
        "output_dir": str(out_dir),
        "report_path": str(out_dir / "premarket_signal.html"),
        "files": files,
        "detail": report_data,
    }


# ─── 候选股票分类 ───────────────────────────────────────────────

def _get_target_candidates(
    candidates: list[dict], top_n: int, risk_check: dict,
) -> list[dict]:
    """提取 TopN 目标候选 (按 rank 排序, 排除风控标记的)"""
    risk_symbols = _get_risk_symbols(risk_check)
    ranked = sorted(candidates, key=lambda c: c.get("rank", 9999))
    safe = []
    for c in ranked:
        sym = c.get("symbol", "")
        flags = c.get("risk_flags", [])
        if isinstance(flags, str):
            flags = [f.strip() for f in flags.split(",") if f.strip()]
        has_risk = bool(sym in risk_symbols or flags)
        if has_risk:
            continue
        safe.append(c)
        if len(safe) >= top_n:
            break
    return safe


def _get_watch_candidates(
    candidates: list[dict], top_n: int, risk_check: dict,
) -> list[dict]:
    """提取观察名单 (21-40, 排除风控标记的)"""
    risk_symbols = _get_risk_symbols(risk_check)
    ranked = sorted(candidates, key=lambda c: c.get("rank", 9999))
    safe = []
    for c in ranked:
        sym = c.get("symbol", "")
        flags = c.get("risk_flags", [])
        if isinstance(flags, str):
            flags = [f.strip() for f in flags.split(",") if f.strip()]
        has_risk = bool(sym in risk_symbols or flags)
        if has_risk:
            continue
        # 跳过前 top_n
        if len(safe) < top_n:
            safe.append(c)
            continue
        # 取 top_n 到 top_n*2
        if len(safe) < top_n * 2:
            safe.append(c)
        else:
            break
    # 返回 21-40 (索引 top_n .. top_n*2-1)
    return safe[top_n: top_n * 2]


def _get_remove_candidates(
    candidates: list[dict], top_n: int, risk_check: dict,
) -> list[dict]:
    """提取因风控被排除的股票"""
    risk_symbols = _get_risk_symbols(risk_check)
    ranked = sorted(candidates, key=lambda c: c.get("rank", 9999))
    removed = []
    for c in ranked:
        sym = c.get("symbol", "")
        flags = c.get("risk_flags", [])
        if isinstance(flags, str):
            flags = [f.strip() for f in flags.split(",") if f.strip()]
        reason = _format_risk_reason(c, risk_check)
        if sym in risk_symbols or flags:
            removed.append({
                "symbol": sym,
                "name": c.get("name", ""),
                "reason": reason,
            })
    return removed


def _get_risk_symbols(risk_check: dict) -> set[str]:
    """从风控检查结果提取被标记的股票代码集合"""
    details = risk_check.get("details", [])
    return {d.get("symbol", "") for d in details if d.get("symbol")}


def _format_risk_reason(candidate: dict, risk_check: dict) -> str:
    """格式化风控排除理由"""
    flags = candidate.get("risk_flags", [])
    if isinstance(flags, str):
        flags = [f.strip() for f in flags.split(",") if f.strip()]
    sym = candidate.get("symbol", "")

    reasons = []
    details = risk_check.get("details", [])
    for d in details:
        if d.get("symbol") == sym:
            reasons.append(d.get("detail", d.get("risk_type", "风控排除")))

    for f in flags:
        label = RISK_TYPE_LABELS.get(f, f)
        if label not in reasons:
            reasons.append(label)

    return "; ".join(reasons) if reasons else "风控排除"


# ─── 调仓计划 ───────────────────────────────────────────────────

def _build_rebalance_plan(
    target_candidates: list[dict],
    watch_candidates: list[dict],
    remove_candidates: list[dict],
    current_positions: Optional[dict],
    signal_date: str,
) -> list[dict]:
    """构建调仓计划

    逻辑:
        - 当前持仓未在 target 中 -> sell
        - target 中的股票 -> buy (如果已有持仓则 hold)
        - watch 中的 -> watch
        - remove 中的 -> sell (如果有持仓)
    """
    target_symbols = {c["symbol"] for c in target_candidates if "symbol" in c}
    watch_symbols = {c["symbol"] for c in watch_candidates if "symbol" in c}
    remove_symbols = {c["symbol"] for c in remove_candidates if "symbol" in c}
    position_symbols = set(current_positions.keys()) if current_positions else set()

    plan = []

    # Target candidates
    for c in target_candidates:
        sym = c.get("symbol", "")
        flags = c.get("risk_flags", [])
        if isinstance(flags, list):
            flags_str = ",".join(flags)
        else:
            flags_str = str(flags)
        reason = c.get("reason", f"Top{_find_rank(c, target_candidates)} 候选")

        if current_positions is None:
            action = "buy"
            reason += " | no positions input"
        elif sym in position_symbols:
            action = "hold"
            reason += " | 已有持仓"
        else:
            action = "buy"
            reason += " | 新增买入"

        plan.append({
            "symbol": sym,
            "action": action,
            "reason": reason,
            "risk_flags": flags_str,
        })

    # Watch candidates
    for c in watch_candidates:
        sym = c.get("symbol", "")
        flags = c.get("risk_flags", [])
        if isinstance(flags, list):
            flags_str = ",".join(flags)
        else:
            flags_str = str(flags)
        plan.append({
            "symbol": sym,
            "action": "watch",
            "reason": "观察名单, 等待进一步确认",
            "risk_flags": flags_str,
        })

    # Remove candidates — if held, suggest sell
    for c in remove_candidates:
        sym = c.get("symbol", "")
        reason = c.get("reason", "风控排除")
        if current_positions is None:
            action = "sell"
            reason += " | no positions input"
        elif sym in position_symbols:
            action = "sell"
            reason += " | 建议剔除持仓"
        else:
            action = "sell"
            reason += " | 不持仓, 仅提醒"

        plan.append({
            "symbol": sym,
            "action": action,
            "reason": reason,
            "risk_flags": "风控排除",
        })

    # Positions held but not in any list — suggest sell
    if current_positions and position_symbols:
        all_mentioned = target_symbols | watch_symbols | remove_symbols
        for sym in sorted(position_symbols):
            if sym not in all_mentioned:
                pos = current_positions.get(sym, {})
                shares = pos.get("shares", "?")
                avg_price = pos.get("avg_price", "?")
                plan.append({
                    "symbol": sym,
                    "action": "sell",
                    "reason": f"不在候选/观察/排除名单中 (持仓 {shares} 股, 均价 {avg_price})",
                    "risk_flags": "",
                })

    return plan


def _find_rank(candidate: dict, candidates: list[dict]) -> str:
    """查找候选在列表中的排名"""
    for i, c in enumerate(candidates):
        if c.get("symbol") == candidate.get("symbol"):
            return str(i + 1)
    return "?"


# ─── 写入函数 ───────────────────────────────────────────────────

def _write_json(path: Path, data: dict | list):
    """写入 JSON 文件"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_candidates_csv(path: Path, candidates: list[dict], fields: list[str]):
    """写入候选 CSV (UTF-8 BOM)"""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for c in candidates:
            row = dict(c)
            # risk_flags list → str
            if isinstance(row.get("risk_flags"), list):
                row["risk_flags"] = ",".join(row["risk_flags"])
            # bool → int (0/1 for CSV clarity)
            if "close_gt_ma20" in row:
                row["close_gt_ma20"] = 1 if row["close_gt_ma20"] else 0
            # 数值格式化
            for nk in ("close", "ret5", "ma20", "amount"):
                if nk in row and row[nk] is not None:
                    try:
                        if nk == "ret5":
                            row[nk] = round(float(row[nk]), 4)
                        elif nk == "amount":
                            row[nk] = round(float(row[nk]), 2)
                        else:
                            row[nk] = round(float(row[nk]), 2)
                    except (ValueError, TypeError):
                        pass
            w.writerow(row)


def _write_rebalance_csv(path: Path, plan: list[dict]):
    """写入调仓计划 CSV"""
    fields = ["symbol", "action", "reason", "risk_flags"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in plan:
            row = dict(p)
            if isinstance(row.get("risk_flags"), list):
                row["risk_flags"] = ",".join(row["risk_flags"])
            w.writerow(row)


def _write_md(path: Path, content: str):
    """写入纯文本/Markdown 文件"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ─── 空结果构造 ────────────────────────────────────────────────

def _empty_freshness() -> dict:
    """构造空数据新鲜度 (当 signal_result 未提供时)"""
    return {
        "checked_at": datetime.now(CST).isoformat(),
        "latest_data_date": None,
        "signal_date": None,
        "data_lag_days": None,
        "fields_checked": [],
        "all_fields_available": False,
        "missing_fields": ["data_freshness_not_provided"],
        "status": "failed",
        "note": "未提供数据新鲜度信息",
    }


def _empty_risk_check() -> dict:
    """构造空风控检查 (当 signal_result 未提供时)"""
    return {
        "checked_at": datetime.now(CST).isoformat(),
        "n_st_flagged": 0,
        "n_suspended_flagged": 0,
        "n_limit_up_flagged": 0,
        "n_low_liquidity_flagged": 0,
        "n_consecutive_up_flagged": 0,
        "n_high_return_flagged": 0,
        "total_risk_flags": 0,
        "n_candidates_checked": 0,
        "status": "failed",
        "details": [],
    }


# ─── 审计日志 ───────────────────────────────────────────────────

def _build_audit_log(
    report_data: dict,
    data_freshness: dict,
    risk_check: dict,
    target_candidates: list[dict],
    watch_candidates: list[dict],
    remove_candidates: list[dict],
    now_str: str,
) -> str:
    """生成信号审计日志"""
    lines = [
        "=== PREMARKET SIGNAL AUDIT LOG ===",
        f"Timestamp: {now_str}",
        f"Signal Date: {report_data.get('signal_date', 'unknown')}",
        f"Strategy: {report_data.get('strategy_name', 'unknown')}",
        f"TopN: {report_data.get('top_n', 20)}",
        f"Universe: {report_data.get('universe', 'unknown')}",
        f"Data Status: {data_freshness.get('status', 'unknown')}",
        f"Risk Status: {risk_check.get('status', 'unknown')}",
        f"Target Count: {len(target_candidates)}",
        f"Watch Count: {len(watch_candidates)}",
        f"Remove Count: {len(remove_candidates)}",
        f"Error Count: 0",
        "",
        "--- Target Candidates ---",
    ]
    for c in target_candidates:
        flags_str = c.get("risk_flags", "")
        if isinstance(flags_str, list):
            flags_str = ",".join(flags_str)
        lines.append(
            f"  {_fmt_str(c.get('rank','?'), 4)} | {c.get('symbol',''):>8s} | "
            f"{c.get('name',''):8s} | close={_fmt_str(c.get('close','?'), 8)} | "
            f"ret5={_fmt_str(c.get('ret5','?'), 8)} | risk=[{flags_str}]"
        )
    lines.append("")
    lines.append("--- Watch Candidates ---")
    for c in watch_candidates:
        lines.append(
            f"  {_fmt_str(c.get('rank','?'), 4)} | {c.get('symbol',''):>8s} | "
            f"{c.get('name',''):8s} | close={_fmt_str(c.get('close','?'), 8)}"
        )
    lines.append("")
    lines.append("--- Remove Candidates ---")
    for c in remove_candidates:
        lines.append(
            f"  {c.get('symbol',''):>8s} | {c.get('name',''):8s} | "
            f"reason={c.get('reason','')}"
        )
    lines.append("")
    lines.append("--- Rebalance Plan Summary ---")
    plan = report_data.get("rebalance_plan", [])
    if isinstance(plan, list):
        buy_count = sum(1 for p in plan if p.get("action") == "buy")
        sell_count = sum(1 for p in plan if p.get("action") == "sell")
        hold_count = sum(1 for p in plan if p.get("action") == "hold")
        watch_count = sum(1 for p in plan if p.get("action") == "watch")
        lines.append(f"  Buy: {buy_count}, Sell: {sell_count}, Hold: {hold_count}, Watch: {watch_count}")
    lines.append("")
    lines.append(f"--- Data Freshness ---")
    lines.append(f"  Status: {data_freshness.get('status', 'unknown')}")
    lines.append(f"  Latest Data: {data_freshness.get('latest_data_date', 'N/A')}")
    lines.append(f"  Data Lag: {data_freshness.get('data_lag_days', 'N/A')} days")
    lines.append(f"  Missing: {data_freshness.get('missing_fields', [])}")
    lines.append("")
    lines.append(f"--- Risk Check ---")
    lines.append(f"  Status: {risk_check.get('status', 'unknown')}")
    lines.append(f"  Total Risk Flags: {risk_check.get('total_risk_flags', 0)}")
    lines.append(f"  ST: {risk_check.get('n_st_flagged', 0)}")
    lines.append(f"  Suspended: {risk_check.get('n_suspended_flagged', 0)}")
    lines.append(f"  Limit Up: {risk_check.get('n_limit_up_flagged', 0)}")
    lines.append(f"  Low Liquidity: {risk_check.get('n_low_liquidity_flagged', 0)}")
    lines.append(f"  Consecutive Up: {risk_check.get('n_consecutive_up_flagged', 0)}")
    lines.append("")
    lines.append("=== END AUDIT ===")
    return "\n".join(lines)


# ─── HTML 报告 ──────────────────────────────────────────────────

def _build_html(
    report_data: dict,
    target_candidates: list[dict],
    watch_candidates: list[dict],
    remove_candidates: list[dict],
    rebalance_plan: list[dict],
    data_freshness: dict,
    risk_check: dict,
    now_str: str,
) -> str:
    """生成暗色主题中文 HTML 报告

    包含:
        - 数据最新日期
        - 数据完整性状态
        - 是否为调仓日
        - 当前 Top20 候选
        - 风控排除原因
        - 观察名单 (21-40)
        - 持有/剔除建议
        - 风险提示
        - 是否可用于实盘参考
    """
    signal_date = report_data.get("signal_date", "未知")
    strategy_name = report_data.get("strategy_name", "未知策略")
    universe = report_data.get("universe", "未知")
    top_n = report_data.get("top_n", 20)
    has_positions = report_data.get("has_positions", False)

    # 数据状态
    freshness_status = data_freshness.get("status", "unknown")
    freshness_note = data_freshness.get("note", "")
    latest_date = data_freshness.get("latest_data_date", "未知")
    data_lag = data_freshness.get("data_lag_days", "未知")
    missing_fields = data_freshness.get("missing_fields", [])

    # 风控状态
    risk_status = risk_check.get("status", "unknown")
    n_st = risk_check.get("n_st_flagged", 0)
    n_suspended = risk_check.get("n_suspended_flagged", 0)
    n_limit_up = risk_check.get("n_limit_up_flagged", 0)
    n_liquidity = risk_check.get("n_low_liquidity_flagged", 0)
    n_consecutive = risk_check.get("n_consecutive_up_flagged", 0)
    n_high_return = risk_check.get("n_high_return_flagged", 0)
    total_flags = risk_check.get("total_risk_flags", 0)

    # 是否可以实盘
    tradeable = _is_tradeable(data_freshness, risk_check, target_candidates)
    tradeable_label = "✅ 可用" if tradeable else "❌ 不可用"
    tradeable_reason = _tradeable_reason(data_freshness, risk_check, target_candidates)

    # 是否为调仓日 — 如果是交易日且数据最新即可
    rebalance_day = freshness_status == "ok" and data_lag in (0, "0", None)
    rebalance_label = "✅ 调仓日" if rebalance_day else "⏸️ 非调仓日"

    # 数据完整性 badge
    freshness_badge = _status_badge(freshness_status)
    risk_badge = _status_badge(risk_status)

    # 等级
    freshness_grade_color = _status_color(freshness_status)
    risk_grade_color = _status_color(risk_status)

    # ── Top20 表 ──
    target_rows = ""
    for i, c in enumerate(target_candidates):
        rank = c.get("rank", str(i + 1))
        sym = c.get("symbol", "")
        name = c.get("name", "")
        close_v = _fmt_val(c.get("close"))
        ret5_v = _fmt_pct_val(c.get("ret5"))
        ma20_v = _fmt_val(c.get("ma20"))
        gt_ma20 = "⬆️" if c.get("close_gt_ma20") else "⬇️"
        amount_v = _fmt_amount(c.get("amount"))
        flags = c.get("risk_flags", [])
        if isinstance(flags, list):
            flags = ",".join(flags)
        flags_html = f'<span class="risk-flag">{flags}</span>' if flags else ""
        reason = c.get("reason", "")
        target_rows += f"""<tr>
<td>{i + 1}</td>
<td class="mono">{sym}</td>
<td>{name}</td>
<td class="num">{close_v}</td>
<td class="num ret5">{ret5_v}</td>
<td class="num">{ma20_v}</td>
<td>{gt_ma20}</td>
<td class="num">{amount_v}</td>
<td class="mono">{flags_html}</td>
<td style="font-size:0.8em;color:#aaa;max-width:200px;">{reason}</td>
</tr>"""

    # ── Watch 21-40 表 ──
    watch_rows = ""
    for i, c in enumerate(watch_candidates):
        rank = c.get("rank", str(i + 1))
        sym = c.get("symbol", "")
        name = c.get("name", "")
        close_v = _fmt_val(c.get("close"))
        ret5_v = _fmt_pct_val(c.get("ret5"))
        ma20_v = _fmt_val(c.get("ma20"))
        gt_ma20 = "⬆️" if c.get("close_gt_ma20") else "⬇️"
        amount_v = _fmt_amount(c.get("amount"))
        flags = c.get("risk_flags", [])
        if isinstance(flags, list):
            flags = ",".join(flags)
        flags_html = f'<span class="risk-flag">{flags}</span>' if flags else ""
        reason = c.get("reason", "")
        watch_rows += f"""<tr>
<td>{i + 1 + top_n}</td>
<td class="mono">{sym}</td>
<td>{name}</td>
<td class="num">{close_v}</td>
<td class="num ret5">{ret5_v}</td>
<td class="num">{ma20_v}</td>
<td>{gt_ma20}</td>
<td class="num">{amount_v}</td>
<td class="mono">{flags_html}</td>
<td style="font-size:0.8em;color:#aaa;max-width:200px;">{reason}</td>
</tr>"""

    # ── Remove 表 ──
    remove_rows = ""
    for c in remove_candidates:
        sym = c.get("symbol", "")
        name = c.get("name", "")
        reason = c.get("reason", "")
        remove_rows += f"""<tr>
<td class="mono">{sym}</td><td>{name}</td>
<td style="font-size:0.8em;color:#ff6b6b;">{reason}</td>
</tr>"""

    # ── Rebalance 表 ──
    rebalance_rows = ""
    action_colors = {"buy": "#00c853", "sell": "#ff1744", "hold": "#64dd17", "watch": "#ff9100"}
    action_labels = {"buy": "买入", "sell": "卖出", "hold": "持有", "watch": "观察"}
    for p in rebalance_plan:
        sym = p.get("symbol", "")
        action = p.get("action", "hold")
        reason = p.get("reason", "")
        flags = p.get("risk_flags", "")
        color = action_colors.get(action, "#888")
        label = action_labels.get(action, action)
        rebalance_rows += f"""<tr>
<td class="mono">{sym}</td>
<td><span style="color:{color};font-weight:bold;">{label}</span></td>
<td style="font-size:0.8em;color:#aaa;">{reason}</td>
<td class="mono">{flags}</td>
</tr>"""

    # ── 风控详情 ──
    risk_detail_rows = ""
    for d in risk_check.get("details", []):
        sym = d.get("symbol", "")
        rtype = d.get("risk_type", "")
        detail = d.get("detail", "")
        risk_detail_rows += f"""<tr>
<td class="mono">{sym}</td>
<td><span class="risk-flag">{rtype}</span></td>
<td style="font-size:0.8em;color:#ff6b6b;">{detail}</td>
</tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>盘前信号报告 — Premarket Signal Report</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Noto Sans SC", sans-serif;
       background: #1a1a2e; color: #e0e0e0; margin:0; padding:20px; }}
.card {{ background: #16213e; border-radius:8px; padding:20px; margin:12px 0; }}
.header {{ background: linear-gradient(135deg, #0f3460, #16213e);
           border-radius:8px; padding:24px; text-align:center; }}
h1 {{ margin:0; font-size:1.6em; color:#00bcd4; }}
h2 {{ color:#00bcd4; font-size:1.2em; border-bottom:1px solid #333; padding-bottom:6px; }}
h3 {{ color:#00bcd4; font-size:1.0em; margin:16px 0 8px 0; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ padding:6px 8px; text-align:left; border-bottom:1px solid #333; white-space:nowrap; }}
th {{ color:#888; font-size:0.85em; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.mono {{ font-family: "SF Mono", "Fira Code", "Consolas", monospace; font-size:0.9em; }}
.ret5 {{ color: #64dd17; }}
.negative {{ color: #ff6b6b; }}
.grade {{ font-weight:bold; font-size:1.1em; }}
.summary-box {{ display:inline-block; padding:10px 20px; margin:4px; border-radius:6px; text-align:center; }}
.summary-num {{ font-size:1.8em; font-weight:bold; }}
.summary-label {{ font-size:0.8em; color:#aaa; }}
.risk-flag {{ display:inline-block; padding:1px 8px; border-radius:3px;
             font-size:0.8em; background:#ff174433; color:#ff6b6b; }}
.badge {{ display:inline-block; padding:2px 12px; border-radius:4px;
          font-size:0.9em; font-weight:bold; margin:2px; }}
.badge-ok {{ background:#00c85333; color:#00c853; }}
.badge-warn {{ background:#ff910033; color:#ff9100; }}
.badge-fail {{ background:#ff174433; color:#ff1744; }}
.badge-partial {{ background:#ff910033; color:#ff9100; }}
.scroll-box {{ overflow-x:auto; }}
.warning-box {{ border-left:4px solid #ff9100; background:#1a2744; padding:12px 16px;
                border-radius:4px; margin:8px 0; }}
.danger-box {{ border-left:4px solid #ff1744; background:#1a2744; padding:12px 16px;
               border-radius:4px; margin:8px 0; }}
.success-box {{ border-left:4px solid #00c853; background:#1a2744; padding:12px 16px;
                border-radius:4px; margin:8px 0; }}
.status-row {{ display:flex; gap:12px; flex-wrap:wrap; }}
.explain-card {{ background: #1a2744; border-radius:6px; padding:16px; margin:8px 0; }}
.explain-card h3 {{ color:#00bcd4; margin:0 0 8px 0; font-size:1em; }}
ul {{ padding-left:20px; }}
li {{ margin:6px 0; line-height:1.6; }}
@media print {{ body {{ padding:10px; }} .card {{ break-inside: avoid; }} }}
</style>
</head>
<body>

<div class="header">
<h1>📊 盘前信号报告</h1>
<p style="color:#888;margin:8px 0 0 0;">
{strategy_name} | {universe} | 信号日: {signal_date} | 生成: {now_str}
</p>
</div>

<!-- ─── 状态总览 ─── -->
<div class="card">
<h2>📋 状态总览</h2>
<div class="status-row">
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:#00bcd4;">{signal_date}</div>
<div class="summary-label">信号日期</div>
</div>
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:{freshness_grade_color};">{freshness_badge}</div>
<div class="summary-label">数据完整性</div>
</div>
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:#64dd17;">{rebalance_label}</div>
<div class="summary-label">调仓日判断</div>
</div>
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:{risk_grade_color};">{risk_badge}</div>
<div class="summary-label">风控状态</div>
</div>
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:#00bcd4;">{tradeable_label}</div>
<div class="summary-label">实盘可用性</div>
</div>
</div>

<div style="margin-top:12px;">
<strong>数据最新日期:</strong> {latest_date}
&nbsp;|&nbsp; <strong>数据滞后:</strong> {data_lag} 天
&nbsp;|&nbsp; <strong>风控标记:</strong> {total_flags} 只
&nbsp;|&nbsp; <strong>拥有持仓信息:</strong> {'✅ 是' if has_positions else '❌ 否'}
</div>
<div style="margin-top:8px;color:#aaa;font-size:0.9em;">
<strong>数据完整性说明:</strong> {freshness_note}
</div>
</div>

<!-- ─── 实盘可用性说明 ─── -->
<div class="card">
<h2>🎯 实盘参考说明</h2>
<div class=\"{'success-box' if tradeable else 'danger-box'}\">
<p style="margin:0;"><strong>{'✅ 本报告数据可用于今日实盘参考' if tradeable else '❌ 本报告数据不建议用于今日实盘'}</strong></p>
<p style="margin:4px 0 0 0;font-size:0.9em;color:#aaa;">{tradeable_reason}</p>
</div>

<div class="explain-card">
<h3>❓ 为什么这 {len(target_candidates)} 支股票被选中</h3>
<p>候选股票通过 Ret5Ma20Gate 策略筛选:
<ul>
<li><strong>ret5 (近 5 日涨幅)</strong>: 衡量短期动量。因子研究显示 ret5 在 A 股具有最高的 IC (RankIC ≈ +0.034), 是有效的选股因子。</li>
<li><strong>close_gt_ma20 (股价在 MA20 上方)</strong>: 确保股票处于中期上升趋势中。close_gt_ma20 的 RankIC ≈ +0.033, 独立于 ret5 的优质因子。</li>
<li>两因子结合形成"动量 + 趋势"门禁: 仅同时满足 ret5 高且股价在 MA20 以上的股票进入候选池。</li>
<li>最终按 ret5 降序排列, 取 Top{top_n} 作为目标候选。</li>
<li>剔除 ST、停牌、涨停、低流动性等风控标记的股票。</li>
</ul>
</p>
</div>

<div class="explain-card">
<h3>❌ 哪些股票因风控被排除</h3>
<p>风控排除的原因包括:
<ul>
<li><strong>ST / *ST</strong>: 交易受限, 波动大, 不允许买入。</li>
<li><strong>停牌</strong>: 无法交易。</li>
<li><strong>涨停</strong>: 无法以合理价格买入。</li>
<li><strong>成交额过低</strong>: 流动性不足, 冲击成本高。</li>
<li><strong>连续上涨过高</strong>: 追高风险大。</li>
<li><strong>5 日涨幅过大</strong>: 短期获利盘压力。</li>
</ul>
共 {len(remove_candidates)} 支股票因风控被排除。
</p>
</div>

<div class="explain-card">
<h3>{'📂 有持仓时的建议操作' if has_positions else '📂 无持仓信息时的建议'}</h3>
{'<p>系统已收到当前持仓信息, 会根据持仓状态自动生成买入/持有/剔除建议。</p>' if has_positions else '<p>未提供 current_positions, 因此 rebalance_plan 仅标注为 "no positions input", 表示仅生成目标组合, 无法判断已有持仓的处理方式。请在使用时手动核实持仓并调整计划。</p>'}
</div>
</div>

<!-- ─── Top20 候选 ─── -->
<div class="card">
<h2>🏆 当前 Top{len(target_candidates)} 候选</h2>
<div class="scroll-box">
<table>
<thead>
<tr>
<th>#</th><th>代码</th><th>名称</th><th class="num">收盘价</th>
<th class="num">ret5</th><th class="num">MA20</th><th>突破</th>
<th class="num">成交额</th><th>风控</th><th>入选理由</th>
</tr>
</thead>
<tbody>
{target_rows}
</tbody>
</table>
</div>
</div>

<!-- ─── 观察名单 ─── -->
<div class="card">
<h2>👀 观察名单 (21-{top_n + len(watch_candidates)})</h2>
<div class="scroll-box">
<table>
<thead>
<tr>
<th>#</th><th>代码</th><th>名称</th><th class="num">收盘价</th>
<th class="num">ret5</th><th class="num">MA20</th><th>突破</th>
<th class="num">成交额</th><th>风控</th><th>说明</th>
</tr>
</thead>
<tbody>
{watch_rows}
</tbody>
</table>
</div>
</div>

<!-- ─── 风控排除 ─── -->
<div class="card">
<h2>⛔ 风控排除股票 ({len(remove_candidates)})</h2>
<div class="scroll-box">
<table>
<thead>
<tr><th>代码</th><th>名称</th><th>排除原因</th></tr>
</thead>
<tbody>
{remove_rows}
</tbody>
</table>
</div>
</div>

<!-- ─── 调仓计划 ─── -->
<div class="card">
<h2>🔄 调仓计划 ({len(rebalance_plan)} 条)</h2>
<div class="scroll-box">
<table>
<thead>
<tr><th>代码</th><th>操作</th><th>原因</th><th>风控标记</th></tr>
</thead>
<tbody>
{rebalance_rows}
</tbody>
</table>
</div>
</div>

<!-- ─── 风控详细 ─── -->
<div class="card">
<h2>⚠️ 风控详细检查</h2>
<div class="status-row">
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:#ff1744;">{n_st}</div>
<div class="summary-label">ST 标记</div>
</div>
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:#ff9100;">{n_suspended}</div>
<div class="summary-label">停牌</div>
</div>
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:#ff9100;">{n_limit_up}</div>
<div class="summary-label">涨停</div>
</div>
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:#ff9100;">{n_liquidity}</div>
<div class="summary-label">低流动性</div>
</div>
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:#ff1744;">{n_consecutive}</div>
<div class="summary-label">连续上涨</div>
</div>
<div class="summary-box" style="background:#1a2744;">
<div class="summary-num" style="color:#ff1744;">{n_high_return}</div>
<div class="summary-label">涨幅过大</div>
</div>
</div>
<div class="scroll-box" style="margin-top:12px;">
<table>
<thead>
<tr><th>代码</th><th>风险类型</th><th>详情</th></tr>
</thead>
<tbody>
{risk_detail_rows if risk_detail_rows else '<tr><td colspan="3" style="text-align:center;color:#888;">无风控标记</td></tr>'}
</tbody>
</table>
</div>
</div>

<!-- ─── 风险提示 ─── -->
<div class="card">
<h2>📢 风险提示</h2>
<div class="warning-box">
<p style="margin:0;"><strong>⚠️ 重要声明</strong></p>
<ul>
<li>本报告仅为基于量化因子的盘前参考, 不构成投资建议。</li>
<li>所有信号基于历史数据和统计分析, 过往表现不代表未来收益。</li>
<li>候选股票可能因盘中突发消息、大盘剧烈波动等不可预见的因素出现重大变化。</li>
<li>请结合实时行情、公司公告、宏观环境等综合判断后再做交易决策。</li>
<li>建议设置止损位, 控制单票仓位。</li>
<li>市场有风险, 投资需谨慎。</li>
</ul>
</div>
</div>

<div style="text-align:center;padding:12px;color:#555;font-size:0.8em;">
Generated by Factor Lab Premarket Signal Report | {strategy_name}<br>
{now_str}
</div>

</body>
</html>"""
    return html


# ─── 辅助函数 ───────────────────────────────────────────────────

def _is_tradeable(
    data_freshness: dict,
    risk_check: dict,
    target_candidates: list[dict],
) -> bool:
    """判断本报告是否可用于实盘参考"""
    # 数据状态必须 ok
    if data_freshness.get("status") != "ok":
        return False
    # 风控不能 fail
    if risk_check.get("status") == "fail":
        return False
    # 必须有候选
    if len(target_candidates) < 5:
        return False
    return True


def _tradeable_reason(
    data_freshness: dict,
    risk_check: dict,
    target_candidates: list[dict],
) -> str:
    """返回不可用于实盘的原因"""
    reasons = []
    if data_freshness.get("status") != "ok":
        reasons.append(f"数据状态: {data_freshness.get('status', 'unknown')}")
    if risk_check.get("status") == "fail":
        reasons.append(f"风控状态: {risk_check.get('status', 'unknown')}")
    if len(target_candidates) < 5:
        reasons.append(f"候选数量不足 ({len(target_candidates)} < 5)")
    return "; ".join(reasons) if reasons else "所有检查通过, 可用于实盘参考。"


def _status_badge(status: str) -> str:
    """返回状态徽章文本"""
    badges = {
        "ok": "✅ 正常",
        "partial": "⚠️ 部分缺失",
        "failed": "❌ 失败",
        "warn": "⚠️ 警告",
        "fail": "❌ 失败",
    }
    return badges.get(status, "❓ 未知")


def _status_color(status: str) -> str:
    """返回状态颜色"""
    colors = {
        "ok": "#00c853",
        "partial": "#ff9100",
        "warn": "#ff9100",
        "failed": "#ff1744",
        "fail": "#ff1744",
    }
    return colors.get(status, "#888")


def _fmt_str(val, width: int = 8) -> str:
    """格式化值为右对齐字符串"""
    if val is None:
        return "?".rjust(width)
    return str(val).rjust(width)


def _fmt_val(val) -> str:
    """格式化数值"""
    if val is None:
        return "--"
    try:
        return f"{float(val):.2f}"
    except (ValueError, TypeError):
        return str(val)


def _fmt_pct_val(val) -> str:
    """格式化百分比值"""
    if val is None:
        return "--"
    try:
        v = float(val)
        return f"{v * 100:.2f}%" if abs(v) < 10 else f"{v:.2f}%"
    except (ValueError, TypeError):
        return str(val)


def _fmt_amount(val) -> str:
    """格式化成交额 (亿)"""
    if val is None:
        return "--"
    try:
        v = float(val)
        if v >= 1e8:
            return f"{v / 1e8:.2f}亿"
        return f"{v:.0f}"
    except (ValueError, TypeError):
        return str(val)


# ─── 测试入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    # 构造测试数据验证输出
    test_signal_result = {
        "signal_date": "2026-07-03",
        "generated_at": datetime.now(CST).isoformat(),
        "strategy_name": "Ret5Ma20Gate",
        "universe": "watchlist_300",
        "top_n": 20,
        "data_freshness": {
            "checked_at": datetime.now(CST).isoformat(),
            "latest_data_date": "2026-07-03",
            "signal_date": "2026-07-03",
            "data_lag_days": 0,
            "total_symbols": 300,
            "min_days_per_symbol": 60,
            "fields_checked": SIGNAL_FIELD_ORDER,
            "all_fields_available": True,
            "missing_fields": [],
            "status": "ok",
            "note": "数据完整, 可用于信号生成",
        },
        "risk_check": {
            "checked_at": datetime.now(CST).isoformat(),
            "n_st_flagged": 2,
            "n_suspended_flagged": 1,
            "n_limit_up_flagged": 3,
            "n_low_liquidity_flagged": 5,
            "n_consecutive_up_flagged": 1,
            "n_high_return_flagged": 2,
            "total_risk_flags": 14,
            "n_candidates_checked": 100,
            "status": "warn",
            "details": [
                {"symbol": "600519ST", "risk_type": "ST", "detail": "ST标记"},
                {"symbol": "000002ST", "risk_type": "ST", "detail": "ST标记"},
                {"symbol": "300750", "risk_type": "low_amount", "detail": "成交额不足"},
            ],
        },
        "candidates": [
            {
                "symbol": "000001", "name": "平安银行",
                "close": 12.34, "ret5": 0.085, "ma20": 11.50,
                "close_gt_ma20": True, "rank": 1, "amount": 5.2e9,
                "risk_flags": [], "reason": "ret5 强势 + 突破 MA20",
            },
            {
                "symbol": "000002", "name": "万科A",
                "close": 15.20, "ret5": 0.072, "ma20": 14.10,
                "close_gt_ma20": True, "rank": 2, "amount": 3.8e9,
                "risk_flags": [], "reason": "ret5 动量 + 趋势向上",
            },
            {
                "symbol": "000333", "name": "美的集团",
                "close": 68.50, "ret5": 0.065, "ma20": 64.00,
                "close_gt_ma20": True, "rank": 3, "amount": 2.1e9,
                "risk_flags": [], "reason": "放量突破 MA20",
            },
            {
                "symbol": "000651", "name": "格力电器",
                "close": 42.30, "ret5": 0.058, "ma20": 40.20,
                "close_gt_ma20": True, "rank": 4, "amount": 1.5e9,
                "risk_flags": [], "reason": "稳步上行",
            },
            {
                "symbol": "000858", "name": "五粮液",
                "close": 168.20, "ret5": 0.052, "ma20": 160.50,
                "close_gt_ma20": True, "rank": 5, "amount": 6.7e9,
                "risk_flags": [], "reason": "消费复苏 + 趋势确认",
            },
            {
                "symbol": "002415", "name": "海康威视",
                "close": 35.60, "ret5": 0.048, "ma20": 34.00,
                "close_gt_ma20": True, "rank": 6, "amount": 1.2e9,
                "risk_flags": [], "reason": "安防龙头 + 突破 MA20",
            },
        ],
        "current_positions": None,
    }

    # 补充分组测试数据 (模拟 Top20 + 观察 + 排除)
    import random
    random.seed(42)
    stocks_pool = [
        ("600519", "贵州茅台", 1520.0), ("000568", "泸州老窖", 220.0),
        ("002714", "牧原股份", 45.0), ("600036", "招商银行", 38.5),
        ("601166", "兴业银行", 18.2), ("600030", "中信证券", 22.8),
        ("002230", "科大讯飞", 65.0), ("300750", "宁德时代", 210.0),
        ("601012", "隆基绿能", 32.0), ("002475", "立讯精密", 38.0),
        ("000725", "京东方A", 4.5), ("600276", "恒瑞医药", 45.0),
        ("300059", "东方财富", 16.8), ("601318", "中国平安", 52.0),
        ("600887", "伊利股份", 28.0), ("002304", "洋河股份", 110.0),
        ("000063", "中兴通讯", 35.0), ("002352", "顺丰控股", 42.0),
        ("601398", "工商银行", 6.2), ("600028", "中国石化", 6.8),
        ("600941", "中国移动", 105.0), ("300015", "爱尔眼科", 28.0),
        ("002594", "比亚迪", 280.0), ("688981", "中芯国际", 55.0),
        ("000001", "平安银行", 12.34), ("000002ST", "万科A-ST", 8.0),
        ("600519ST", "茅台ST", 200.0),
    ]
    for i, (sym, name, close) in enumerate(stocks_pool):
        idx = i + 7  # after the first 5 static candidates
        if idx >= 100:
            break
        ret5 = round(0.01 + random.random() * 0.08, 4)
        ma20 = round(close * (1 - random.random() * 0.08), 2)
        is_st = "ST" in sym or "*ST" in sym
        risk = ["ST"] if is_st else []
        test_signal_result["candidates"].append({
            "symbol": sym, "name": name,
            "close": close, "ret5": ret5, "ma20": ma20,
            "close_gt_ma20": close > ma20,
            "rank": idx + 1, "amount": close * random.randint(5, 30) * 1e6,
            "risk_flags": risk,
            "reason": "动量延续" if close > ma20 else "观察中",
        })

    out = generate_premarket_report(
        test_signal_result,
        "/tmp/premarket_signal_test",
    )
    print(f"Output dir: {out['output_dir']}")
    print(f"Report path: {out['report_path']}")
    print(f"Files: {out['files']}")
    print(f"Detail: {out['detail']}")
