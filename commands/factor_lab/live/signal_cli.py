#!/usr/bin/env python3
"""V1.9 ret5_ma20_gate 盘前信号 — 三流信号+替代执行路径"""
import sys, os, json, argparse, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd

CST = timezone(timedelta(hours=8))
BASE_OUTPUT = Path("/mnt/d/HermesReports/live_signals")
HV = Path("/mnt/d/HermesReports/live_signals") / "report_helpers"

# ─── 仅导入, 运行时代码在 signal_cli_helpers.py ────────────
_here = Path(__file__).parent
sys.path.insert(0, str(_here))
from signal_cli_helpers import (
    _generate_signal, _build_restricted, _build_etf_framework,
    _build_capital_plan, _assess_readiness,
)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--signal-date", default="latest")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--watch-n", type=int, default=20)
    p.add_argument("--positions", default=None)
    p.add_argument("--output", default=None)
    return p.parse_args()


def main():
    args = parse_args()
    signal_date, df, all_symbols, freshness = _load_data(args)
    if df is None:
        return

    from factor_lab.live.account_profile import get_board, is_self_tradable, ACCOUNT_PROFILE

    # ── 1. Raw: all_watchlist 原始信号 ──
    raw = _generate_signal(df, signal_date, args.top_n, args.watch_n, all_symbols)
    if raw is None:
        return

    # ── 2. Self-account tradable universe ──
    self_symbols = [s for s in all_symbols if is_self_tradable(s)]
    print(f"  Self-account tradable symbols: {len(self_symbols)}")
    self_signal = _generate_signal(df, signal_date, args.top_n, args.watch_n, self_symbols)

    # ── 3. Restricted board candidates ──
    restricted = _build_restricted(raw)

    # ── 4. ETF substitution candidates ──
    etf = _build_etf_framework(restricted)

    # ── 5. Capital plan ──
    cap_plan = _build_capital_plan(self_signal)

    # ── 6. Readiness ──
    readiness = _assess_readiness(raw, self_signal, restricted, freshness)

    # ── 7. Reports ──
    out_dir = args.output or str(BASE_OUTPUT / signal_date.replace("-", ""))
    os.makedirs(out_dir, exist_ok=True)
    _write_reports(out_dir, signal_date, args, freshness, raw, self_signal, restricted, etf, cap_plan, readiness)
    _print_summary(signal_date, freshness, raw, self_signal, restricted, readiness)
    print(f"\n📁 输出目录: {out_dir}")


def _load_data(args):
    from strategy_lab.universe import build
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import list_factors
    from factor_lab.live.data_freshness import check_data_freshness

    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    symbols = sorted(pool)
    if not symbols:
        print("❌ 股票池为空")
        return None, None, None, None
    print(f"  全量股票池: {len(symbols)} 只")

    signal_date = args.signal_date
    if signal_date == "latest":
        test_df = load_stock_kline(symbols, start_date="2026-06-01", end_date="2026-07-10", min_days=1)
        if "date" in test_df.columns and not test_df.empty:
            signal_date = pd.to_datetime(test_df["date"]).max().strftime("%Y-%m-%d")
            print(f"  最近交易日: {signal_date}")
        else:
            signal_date = "2026-06-30"

    padding = pd.Timestamp(signal_date) - pd.Timedelta(days=120)
    df = load_stock_kline(symbols, start_date=str(padding.date()), end_date=signal_date)
    if df.empty:
        return None, None, None, None
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    registry = {f["name"]: f for f in list_factors()}
    for fn in ["ret5", "close_gt_ma20"]:
        if fn in registry:
            df[fn] = registry[fn]["func"](df, **registry[fn]["params"])
    df["ma20"] = df.groupby("symbol")["close"].transform(lambda x: x.rolling(20).mean())
    if "ret1" not in df.columns:
        df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    if "amount" not in df.columns:
        df["amount"] = 0.0

    freshness = check_data_freshness(df, signal_date, factor_cols=["ret5", "close_gt_ma20"])
    if freshness["status"] == "failed":
        print(f"  ❌ {freshness.get('note','')}")
        return None, None, None, None
    print(f"  数据状态: {freshness['status']}")
    return signal_date, df, symbols, freshness


def _write_reports(out_dir, signal_date, args, freshness, raw, self_sig, restricted, etf, cap_plan, readiness):
    """写所有报告文件"""
    data = {
        "signal_date": signal_date,
        "generated_at": datetime.now(CST).isoformat(),
        "readiness": readiness,
        "raw_target_candidates": raw.get("target_candidates", []),
        "raw_watch_candidates": raw.get("watch_candidates", []),
        "self_tradable_target_candidates": self_sig.get("target_candidates", []) if self_sig else [],
        "self_tradable_watch_candidates": self_sig.get("watch_candidates", []) if self_sig else [],
        "restricted_board_candidates": restricted,
        "etf_substitution_candidates": etf,
        "capital_plan": cap_plan,
        "data_freshness": freshness,
    }
    with open(os.path.join(out_dir, "premarket_signal.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # CSV
    _write_csv(out_dir, "raw_target_candidates.csv", data["raw_target_candidates"],
               ["symbol", "rank", "close", "ret5", "ma20"])
    _write_csv(out_dir, "self_tradable_target_candidates.csv", data["self_tradable_target_candidates"],
               ["symbol", "rank", "close", "ret5"])
    _write_csv(out_dir, "restricted_board_candidates.csv", restricted,
               ["symbol", "board", "original_rank", "ret5", "suggested_path"])
    _write_csv(out_dir, "capital_plan.csv", cap_plan.get("lots", []),
               ["symbol", "close", "shares", "estimated_cost", "weight_pct"])

    with open(os.path.join(out_dir, "data_freshness.json"), "w") as f:
        json.dump(freshness, f, indent=2)

    # HTML
    html = _build_html(signal_date, raw, self_sig, restricted, etf, cap_plan, readiness)
    with open(os.path.join(out_dir, "premarket_signal.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # audit
    with open(os.path.join(out_dir, "signal_audit.log"), "w") as f:
        log = (
            f"=== PREMARKET SIGNAL AUDIT V1.9 ===\n"
            f"Signal Date: {signal_date}\n"
            f"Raw Target: {len(raw.get('target_candidates',[]))}\n"
            f"Self Tradable Target: {len(self_sig.get('target_candidates',[])) if self_sig else 0}\n"
            f"Restricted: {len(restricted)}\n"
            f"ETF Themes: {len(etf)}\n"
            f"Capital Fillable: {cap_plan.get('n_fillable',0)}\n"
            f"Readiness: {json.dumps(readiness)}\n"
        )
        f.write(log)
    print(f"  📄 报告已生成 (V1.9 三流信号)")


def _write_csv(out_dir, name, rows, fields):
    path = os.path.join(out_dir, name)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _build_html(signal_date, raw, self_sig, restricted, etf, cap_plan, readiness):
    r = readiness
    def badge(k, v):
        c = {"ready": "#00c853", "partial": "#ff9100", "not_ready": "#ff1744",
             "framework_ready": "#00c853", "no_signal": "#888", "no_trigger": "#888"}.get(v, "#888")
        return f'<span class="badge" style="background:{c}22;color:{c};">{v}</span>'

    rt = raw.get("target_candidates", [])
    st = self_sig.get("target_candidates", []) if self_sig else []
    rt_rows = "".join(f"<tr><td>{c.get('rank','')}</td><td>{c.get('symbol','')}</td><td class=\"num\">{c.get('ret5',0)*100:.1f}%</td></tr>" for c in rt)
    st_rows = "".join(f"<tr><td>{c.get('rank','')}</td><td>{c.get('symbol','')}</td><td class=\"num\">{c.get('ret5',0)*100:.1f}%</td><td class=\"num\">{c.get('close','')}</td></tr>" for c in st)
    re_rows = "".join(f"<tr><td>{c['symbol']}</td><td>{c['board']}</td><td>{c['original_rank']}</td><td>{c.get('ret5',0)*100:.1f}%</td><td>{c['suggested_path']}</td></tr>" for c in restricted)
    etf_rows = "".join(f"<tr><td>{t['theme']}</td><td>{t['trigger_count']}</td><td>{t['etf_candidate_type']}</td><td>{t['next_step']}</td></tr>" for t in etf) if etf else "<tr><td colspan=4 style='color:#888;'>无触发信号</td></tr>"
    plan_rows = "".join(f"<tr><td>{l['symbol']}</td><td class=\"num\">{l['close']}</td><td class=\"num\">{l['shares']}</td><td class=\"num\">{l['estimated_cost']}</td><td class=\"num\">{l['weight_pct']}%</td></tr>" for l in cap_plan.get("lots", []))

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>盘前信号 V1.9 {signal_date}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; }}
th {{ color:#888; font-size:0.85em; }} .num {{ text-align:right; }}
.badge {{ display:inline-block; padding:2px 10px; border-radius:3px; font-size:0.85em; }}
</style></head><body>
<div class="card"><h1>📊 盘前信号 V1.9 — ret5_ma20_gate</h1>
<p style="color:#aaa;">{signal_date}</p>
<p>策略: {badge('strategy',r.get('strategy_signal_readiness','?'))}
自营: {badge('self',r.get('self_account_readiness','?'))}
受限: {badge('restricted',r.get('restricted_signal_readiness','?'))}
ETF: {badge('etf',r.get('etf_substitution_readiness','?'))}</p></div>

<div class="card"><h2>📊 原始策略信号 (含科创/创业板)</h2>
<table><tr><th>#</th><th>代码</th><th class="num">ret5</th></tr>{rt_rows}</table></div>

<div class="card"><h2>✅ 本人账户可交易 ({len(st)}只)</h2>
<table><tr><th>#</th><th>代码</th><th class="num">ret5</th><th class="num">收盘</th></tr>{st_rows}</table></div>

<div class="card"><h2>🚫 权限受限强信号 ({len(restricted)}只)</h2>
<table><tr><th>代码</th><th>板块</th><th>原始排名</th><th class="num">ret5</th><th>建议路径</th></tr>{re_rows}</table></div>

<div class="card"><h2>📈 ETF 替代框架</h2>
<table><tr><th>主题</th><th>触发数</th><th>候选类型</th><th>下一步</th></tr>{etf_rows}</table></div>

<div class="card"><h2>💰 资金计划 (5万)</h2>
<p style="color:#aaa;">可买 {cap_plan.get('n_fillable',0)} 只 | 剩余现金 {cap_plan.get('remaining_cash',0):.0f}</p>
<table><tr><th>代码</th><th class="num">价格</th><th class="num">股数</th><th class="num">金额</th><th class="num">占比</th></tr>{plan_rows}</table></div>

<div class="card"><h2>📋 说明</h2>
<ul>
<li>原始信号: all_watchlist (含主板/创业板/科创板/北交所), 仅研究参考</li>
<li>自营账户: 仅主板可交易 (000/001/002/003/600/601/603/605)</li>
<li>受限股票: 不进入自动买入计划, 仅 ETF 替代或人工合规审查</li>
<li>禁止生成借用他人账户交易建议 (allow_borrowed_account_execution=false)</li>
</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V1.9 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""


def _print_summary(signal_date, freshness, raw, self_sig, restricted, readiness):
    rt = len(raw.get("target_candidates", []))
    st = len(self_sig.get("target_candidates", [])) if self_sig else 0
    print(f"\n{'='*60}")
    print(f"  V1.9 盘前信号 {signal_date}")
    print(f"  Raw: {rt} | Self: {st} | Restricted: {len(restricted)}")
    r = readiness
    print(f"  Strategy: {r.get('strategy_signal_readiness','?')}  Self: {r.get('self_account_readiness','?')}")
    print(f"  Restricted: {r.get('restricted_signal_readiness','?')}  ETF: {r.get('etf_substitution_readiness','?')}")
    if restricted:
        syms = [f"{x['symbol']}({x['board']})" for x in restricted[:3]]
        print(f"  受限 Top3: {', '.join(syms)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

