"""ETF 选择器 V1.10.1 — 主题去重 + 候选/淘汰/未匹配分类"""
import json
from factor_lab.etf.etf_universe import (
    load_etf_registry, get_etf_by_theme, map_restricted_to_theme, list_themes,
)


def run_etf_selector(
    restricted_candidates: list,
    capital: float = 50000,
    min_amount_20d: float = 3000,
    min_aum: float = 5,
    max_expense_ratio: float = 0.6,
    max_etf_per_theme: int = 1,
) -> dict:
    registry = load_etf_registry()

    # 1. 按受限股票推断主题
    theme_triggers = {}
    board_dist = {}
    for rc in restricted_candidates:
        board = rc.get("board", "")
        sym = rc.get("symbol", "")
        ret5 = rc.get("ret5", 0)
        theme = map_restricted_to_theme(board, keywords=[sym, str(ret5)])
        if theme not in theme_triggers:
            theme_triggers[theme] = []
        theme_triggers[theme].append(rc)
        board_dist[board] = board_dist.get(board, 0) + 1

    # 2. 对每个主题筛选 ETF
    selected = []
    rejected = []
    unmatched_registry = []

    all_reg_etf_codes = {e["etf_code"] for e in registry}
    matched_codes = set()

    for theme, triggers in theme_triggers.items():
        theme_etfs = get_etf_by_theme(theme)
        if not theme_etfs:
            fallback = [e for e in registry if theme in e.get("theme", "")]
            if fallback:
                theme_etfs = fallback

        for etf in theme_etfs:
            matched_codes.add(etf["etf_code"])
            reject_reasons = []
            amount = _float(etf.get("avg_amount_20d", 0))
            aum = _float(etf.get("aum", 0))
            expense = _float(etf.get("expense_ratio", 0))

            if amount > 0 and amount < min_amount_20d:
                reject_reasons.append(f"流动性不足(日均{amount:.0f}万<{min_amount_20d}万)")
            if aum > 0 and aum < min_aum:
                reject_reasons.append(f"规模过小({aum:.0f}亿<{min_aum}亿)")
            if expense > 0 and expense > max_expense_ratio:
                reject_reasons.append(f"费率过高({expense:.2f}%>{max_expense_ratio}%)")

            if reject_reasons:
                rejected.append({**etf, "reject_reasons": reject_reasons, "theme_source": theme})
                continue

            score = _score_etf(etf, triggers, amount, aum, expense)
            selected.append({
                **etf,
                "score": score["total"],
                "score_details": score,
                "trigger_count": len(triggers),
                "trigger_symbols": [t["symbol"] for t in triggers[:10]],
                "theme_source": theme,
            })

    # 未匹配的 registry ETF
    unmatched_codes = all_reg_etf_codes - matched_codes
    for e in registry:
        if e["etf_code"] in unmatched_codes:
            unmatched_registry.append(e)

    # 每个主题只保留 Top1 (除非允许多 ETF)
    if max_etf_per_theme == 1:
        selected_by_theme = {}
        for c in selected:
            t = c.get("theme_source", "")
            if t not in selected_by_theme or c["score"] > selected_by_theme[t]["score"]:
                selected_by_theme[t] = c
        selected = list(selected_by_theme.values())

    # backup etf: 同主题第二名
    backup_etfs = []
    if max_etf_per_theme == 1:
        for c in selected:
            theme = c.get("theme_source", "")
            same_theme = sorted(
                [s for s in selected if s.get("theme_source") == theme],
                key=lambda x: -x["score"]
            )
            if len(same_theme) > 1:
                for s in same_theme[1:]:
                    backup_etfs.append({**s, "backup": True})

    selected.sort(key=lambda e: -e["score"])

    # 3. 主题汇总 (含触发股票明细)
    themes_out = []
    for theme, triggers in theme_triggers.items():
        theme_candidates = [c for c in selected if c.get("theme_source") == theme]
        ret5s = [t.get("ret5", 0) for t in triggers if isinstance(t.get("ret5", 0), (int, float))]
        boards = {}
        for t in triggers:
            b = t.get("board", "?")
            boards[b] = boards.get(b, 0) + 1
        themes_out.append({
            "theme": theme,
            "trigger_count": len(triggers),
            "trigger_symbols": [t["symbol"] for t in triggers],
            "top_trigger_symbols": [t["symbol"] for t in triggers[:5]],
            "avg_ret5": round(sum(ret5s) / max(len(ret5s), 1), 4) if ret5s else 0,
            "max_ret5": round(max(ret5s), 4) if ret5s else 0,
            "board_distribution": boards,
            "reason": f"{len(triggers)}只{theme}相关股票受限",
            "top_etf": theme_candidates[0]["etf_code"] if theme_candidates else None,
            "n_candidates": len(theme_candidates),
            "n_rejected": sum(1 for r in rejected if r.get("theme_source") == theme),
        })

    # 4. 资金计划 (每主题 Top1)
    plan = _build_capital_plan(selected, capital)

    # 5. 缺失字段统计
    missing_fields = _check_missing_fields(registry)

    return {
        "restricted_source_count": len(restricted_candidates),
        "themes": themes_out,
        "candidates": selected,
        "backup_etfs": backup_etfs,
        "rejected": rejected,
        "unmatched_registry_count": len(unmatched_registry),
        "unmatched_registry_etfs": unmatched_registry[:5],  # 仅展示前 5
        "capital_plan": plan,
        "data_status": "ok" if not missing_fields.get("critical") else "partial",
        "missing_fields": missing_fields,
        "board_distribution": board_dist,
    }


def _score_etf(etf, triggers, amount, aum, expense) -> dict:
    theme_score = 25
    theme = etf.get("theme", "")
    if theme == "科创芯片":
        theme_score = 30
    elif theme in ("科创50", "科创100"):
        theme_score = 20

    holdings_score = 15 if etf.get("holdings_available") == "true" else 10

    if amount >= 50000:
        liq_score = 20
    elif amount >= 20000:
        liq_score = 15
    elif amount >= 5000:
        liq_score = 10
    else:
        liq_score = 5

    if aum >= 100:
        size_score = 10
    elif aum >= 30:
        size_score = 8
    elif aum >= 10:
        size_score = 5
    else:
        size_score = 2

    fee_score = 10 if expense <= 0.15 else 8 if expense <= 0.50 else 4
    tradable_score = 5

    total = theme_score + holdings_score + liq_score + size_score + fee_score + tradable_score
    grade = "A" if total >= 80 else "B" if total >= 60 else "C" if total >= 40 else "D"

    return {
        "total": total, "grade": grade,
        "theme_match": theme_score, "holdings_match": holdings_score,
        "liquidity": liq_score, "size": size_score,
        "fee": fee_score, "tradability": tradable_score,
    }


def _build_capital_plan(candidates, capital):
    if not candidates or capital <= 0:
        return {"capital": capital, "allocations": [], "total_allocated": 0,
                "remaining": capital, "note": "无候选 ETF 或资金不足"}

    per_etf = capital / len(candidates)
    allocations = []
    for etf in candidates:
        shares = max(100, int(per_etf / 1.0 / 100) * 100)
        cost = shares * 1.0
        allocations.append({
            "etf_code": etf["etf_code"], "etf_name": etf["etf_name"],
            "theme": etf.get("theme_source", ""), "score": etf.get("score", 0),
            "allocated": round(cost, 2), "weight_pct": round(cost / capital * 100, 1),
            "shares": shares, "note": "默认配置, 每主题只选 Top1",
        })

    total_allocated = sum(a["allocated"] for a in allocations)
    return {
        "capital": capital, "allocations": allocations,
        "total_allocated": round(total_allocated, 2),
        "remaining": round(capital - total_allocated, 2),
        "note": "每主题仅 Top1 ETF, 仅供参考配置, 不自动执行",
    }


def _check_missing_fields(registry):
    fields = ["avg_amount_20d", "aum", "expense_ratio",
              "premium_discount", "tracking_error", "holdings_date", "top_holdings"]
    missing = {}
    for field in fields:
        missing_count = sum(1 for e in registry if not e.get(field))
        if missing_count > 0:
            missing[field] = f"{missing_count}/{len(registry)} 缺失"
    return {
        "fields": missing,
        "critical": "holdings_date" in missing or "top_holdings" in missing,
    }


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ═══════════════════════════════════════════════════════════
# ETF 替代入口 — 个股→ETF 匹配
# ═══════════════════════════════════════════════════════════

def find_etf_substitute(
    symbol: str,
    etf_universe: list = None,
    theme_map: dict = None,
) -> list[dict]:
    """为不可交易的股票寻找最佳替代 ETF

    匹配优先级: 同主题 > 同行业 > 宽基指数
    委托给 etf_universe.find_etf_substitute() 实现。

    Args:
        symbol: 股票代码 (如 "688012" 或 "688012.SH")
        etf_universe: ETF 数据库 (list of dicts), 默认 load_etf_registry()
        theme_map: {symbol: [theme_tags]}, 可选的外部主题映射

    Returns:
        [{etf_code, etf_name, match_reason, weight, score}, ...]
        按匹配度降序排列, 最多返回 5 个
    """
    from factor_lab.etf.etf_universe import (
        find_etf_substitute as _find_sub,
    )
    return _find_sub(symbol, etf_universe=etf_universe, theme_map=theme_map)
