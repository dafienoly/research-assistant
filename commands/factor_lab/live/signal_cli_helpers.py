# ─── Signal Generation ──────────────────────────────────────
def _generate_signal(df, signal_date, top_n, watch_n, symbols):
    """对给定 symbol 列表生成 ret5_ma20_gate 信号"""
    from factor_lab.live.signal_generator import Ret5Ma20GateSignalGenerator
    # 过滤 df 只包含指定 symbols
    sub = df[df["symbol"].isin(symbols)].copy() if symbols else df
    gen = Ret5Ma20GateSignalGenerator(sub)
    sig = gen.generate_signals(signal_date=signal_date, top_n=top_n, watch_n=watch_n)
    # 去重
    for key in ["target_candidates", "watch_candidates"]:
        entries = sig.get(key, [])
        seen = set()
        deduped = []
        for e in entries:
            s = e.get("symbol", "")
            if s in seen:
                continue
            seen.add(s)
            deduped.append(e)
        sig[key] = deduped
    # target/watch 互斥
    t_syms = {c["symbol"] for c in sig.get("target_candidates", [])}
    sig["watch_candidates"] = [c for c in sig.get("watch_candidates", []) if c["symbol"] not in t_syms]
    # 重排 rank
    for i, c in enumerate(sig.get("target_candidates", [])):
        c["rank"] = i + 1
    for i, c in enumerate(sig.get("watch_candidates", [])):
        c["rank"] = len(sig.get("target_candidates", [])) + i + 1
    return sig


def _build_restricted(raw):
    """从原始信号中筛出权限受限但信号强的股票"""
    from factor_lab.live.account_profile import get_board, is_self_tradable
    boards_map = {"chinext": "创业板", "star": "科创板", "beijing": "北交所"}

    restricted = []
    for entry in raw.get("target_candidates", []) + raw.get("watch_candidates", []):
        sym = entry["symbol"]
        if is_self_tradable(sym):
            continue
        board = get_board(sym)
        board_label = boards_map.get(board, board)
        rank = entry.get("rank", 0)
        ret5 = entry.get("ret5", 0)
        # 仅保留信号较强的 (ret5 > 0 或在 Top40)
        if rank > 40 and ret5 <= 0:
            continue
        suggested = "etf_substitution_candidate" if board in ("star", "chinext") else "manual_compliance_review"
        restricted.append({
            "symbol": sym,
            "board": board_label,
            "original_rank": rank,
            "ret5": round(float(ret5), 4) if ret5 else 0,
            "suggested_path": suggested,
            "reason": f"{board_label}权限受限, 信号强度rank={rank}",
        })
    return restricted


def _build_etf_framework(restricted):
    """构建 ETF 替代框架 (不筛选具体 ETF)"""
    star_stocks = [r for r in restricted if r["board"] in ("科创板",) and r["original_rank"] <= 20]
    chinext_stocks = [r for r in restricted if r["board"] in ("创业板",) and r["original_rank"] <= 20]
    themes = []
    if len(star_stocks) >= 2:
        themes.append({
            "theme": "科创/半导体",
            "trigger_symbols": [r["symbol"] for r in star_stocks[:5]],
            "trigger_count": len(star_stocks),
            "reason": f"{len(star_stocks)}只科创板股票信号较强但权限受限",
            "etf_candidate_type": "board_etf / sector_etf",
            "next_step": "后续由 ETF selector 根据流动性/跟踪指数/费率筛选",
        })
    if len(chinext_stocks) >= 2:
        themes.append({
            "theme": "创业板成长",
            "trigger_symbols": [r["symbol"] for r in chinext_stocks[:5]],
            "trigger_count": len(chinext_stocks),
            "reason": f"{len(chinext_stocks)}只创业板股票信号较强但权限受限",
            "etf_candidate_type": "board_etf / sector_etf",
            "next_step": "后续由 ETF selector 筛选",
        })
    return themes


def _build_capital_plan(self_signal):
    """资金计划 (仅 self-account)"""
    target = self_signal.get("target_candidates", [])
    capital = 50000
    plan = {"capital": capital, "lots": []}
    remaining = capital
    for c in target[:20]:
        close = float(c.get("close", 10) or 10)
        shares = max(100, int(remaining * 0.15 / close / 100) * 100)
        cost = shares * close
        if cost > remaining:
            shares = max(100, int(remaining / close / 100) * 100)
            cost = shares * close
        if shares < 100 or cost > remaining:
            break
        plan["lots"].append({
            "symbol": c["symbol"],
            "close": close,
            "shares": shares,
            "estimated_cost": round(cost, 2),
            "weight_pct": round(cost / capital * 100, 1),
        })
        remaining -= cost
    plan["remaining_cash"] = round(remaining, 2)
    plan["n_fillable"] = len(plan["lots"])
    return plan


def _assess_readiness(raw, self_sig, restricted, freshness):
    return {
        "strategy_signal_readiness": "ready" if len(raw.get("target_candidates", [])) > 0 else "not_ready",
        "self_account_readiness": "ready" if len(self_sig.get("target_candidates", [])) >= 10 else "partial" if len(self_sig.get("target_candidates", [])) > 0 else "not_ready",
        "restricted_signal_readiness": "ready" if len(restricted) > 0 else "no_signal",
        "etf_substitution_readiness": "framework_ready" if len(restricted) > 0 else "no_trigger",
    }
