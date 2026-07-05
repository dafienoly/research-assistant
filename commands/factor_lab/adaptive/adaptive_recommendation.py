"""Adaptive Recommendation V2.8 — 策略参数自适应建议"""
import os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def run_adaptive_recommend(start_date: str, end_date: str = None, last_n: int = None) -> dict:
    """基于 paper dashboard 生成策略参数建议"""
    # 获取 dashboard 数据
    from factor_lab.paper.paper_dashboard import build_dashboard
    dash = build_dashboard(start_date, end_date, last_n=last_n)

    if dash["status"] == "no_data":
        return {"status": "no_data", "period": dash.get("period", f"{start_date}~{end_date}")}

    n_days = dash.get("n_trading_days", 0)
    n_pending = dash.get("n_pending", 0)
    sharpe = dash.get("paper_sharpe", 0)
    ret = dash.get("paper_total_return_pct", 0)
    dd = dash.get("paper_max_drawdown_pct", 0)
    win_rate = dash.get("paper_win_rate_pct", 0)

    def _confidence(n, pending_ratio):
        if n < 5:
            return 0.1, "insufficient_samples"
        base = min(n / 20, 1.0) * 0.8
        penalty = pending_ratio * 0.5
        return round(max(base - penalty, 0.1), 2), "sufficient" if base > 0.3 else "low"

    conf, ev = _confidence(n_days, n_pending / max(n_days, 1))

    # 1. Plan 建议
    if sharpe > 1.5 and ret > 5 and conf > 0.3:
        plan_rec = {"recommendation": "keep_plan_b", "confidence": conf, "evidence": f"Sharpe={sharpe}, Return={ret}%", "evidence_strength": ev}
    elif sharpe < 0.5 or ret < -5:
        plan_rec = {"recommendation": "switch_to_plan_a", "confidence": conf, "evidence": f"Sharpe={sharpe}, Return={ret}%", "evidence_strength": ev}
    else:
        plan_rec = {"recommendation": "insufficient_evidence", "confidence": conf, "evidence": f"n={n_days}, Sharpe={sharpe}", "evidence_strength": "low"}

    # 2. TopN 建议
    topn_rec = {"recommendation": "keep_top8", "confidence": conf, "evidence": "Top8 default balance", "evidence_strength": ev}

    # 3. ETF 权重建议
    etf_rec = {"recommendation": "keep_etf_weight", "confidence": conf, "evidence": f"ETF returns from dashboard", "evidence_strength": ev}

    # 4. 调仓频率建议
    eq = dash.get("execution_quality", {})
    fill_rate = eq.get("fill_rate", 100)
    if fill_rate < 50:
        turnover_rec = {"recommendation": "reduce_rebalance_frequency", "confidence": conf, "evidence": f"Fill rate={fill_rate}% too low", "evidence_strength": ev}
    else:
        turnover_rec = {"recommendation": "keep_daily_refresh_monthly_rebalance", "confidence": conf, "evidence": f"Fill rate={fill_rate}%", "evidence_strength": ev}

    # 5. 风控阈值建议
    blocked = eq.get("blocked", 0)
    if blocked > n_days * 2:
        risk_rec = {"recommendation": "loosen_kill_switch", "confidence": conf, "evidence": f"Blocked {blocked} orders in {n_days} days", "evidence_strength": ev}
    elif dd < -15:
        risk_rec = {"recommendation": "tighten_kill_switch", "confidence": conf, "evidence": f"Max DD {dd}% exceeded comfort", "evidence_strength": ev}
    else:
        risk_rec = {"recommendation": "keep_current_risk_config", "confidence": conf, "evidence": f"DD={dd}%, Blocked={blocked}", "evidence_strength": ev}

    recommendations = [plan_rec, topn_rec, etf_rec, turnover_rec, risk_rec]
    avg_conf = round(sum(r["confidence"] for r in recommendations) / len(recommendations), 2)

    result = {
        "period": dash.get("period", f"{start_date}~{end_date}"),
        "n_completed_days": n_days - n_pending,
        "n_pending_days": n_pending,
        "dashboard_status": dash.get("status", "?"),
        "current_config": {
            "plan": "Plan B",
            "top_n": 8,
            "etf_weight_pct": 50,
            "rebalance_freq": "monthly",
            "kill_switch": "enabled",
        },
        "recommendations": recommendations,
        "evidence_quality": "good" if avg_conf > 0.5 else "medium" if avg_conf > 0.3 else "low",
        "requires_human_approval": True,
        "auto_apply": False,
        "no_auto_order": True,
        "status": "completed",
    }

    return result


def generate_recommendation_report(result: dict, output_dir: str):
    """生成建议报告"""
    import csv as _csv
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "adaptive_recommendation.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSV
    recs = result.get("recommendations", [])
    if recs:
        with open(os.path.join(output_dir, "recommendation_summary.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.DictWriter(f, fieldnames=recs[0].keys(), extrasaction="ignore")
            w.writeheader()
            w.writerows(recs)

    # Manual approval template
    with open(os.path.join(output_dir, "manual_approval_template.md"), "w", encoding="utf-8") as f:
        cc = result.get("current_config", {})
        f.write(f"""# 策略参数调整 — 人工确认模板

日期区间：{result['period']}
完成天数：{result['n_completed_days']} | Pending：{result['n_pending_days']}
证据质量：{result['evidence_quality']}

## 当前配置

- Plan: {cc.get('plan','?')}
- TopN: {cc.get('top_n','?')}
- ETF 权重: {cc.get('etf_weight_pct','?')}%
- 调仓频率: {cc.get('rebalance_freq','?')}
- Kill Switch: {cc.get('kill_switch','?')}

## 建议

""")
        for r in recs:
            f.write(f"- **{r.get('recommendation','?')}** (confidence={r['confidence']}, {r['evidence_strength']})\n  - Evidence: {r.get('evidence','')}\n")
        f.write(f"""
## 人工确认

- [ ] 接受所有建议
- [ ] 仅接受部分
- [ ] 保持当前配置
- [ ] 自定义

备注：
确认人：
确认时间：

*本建议由 V2.8 自动生成, 不自动执行*
""")

    # HTML
    html = _build_html(result)
    with open(os.path.join(output_dir, "adaptive_recommendation_report.html"), "w", encoding="utf-8") as f:
        f.write(html)

    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== ADAPTIVE RECOMMENDATION AUDIT V2.8 ===\nPeriod: {result['period']}\nRecs: {len(recs)}\nEvidence: {result.get('evidence_quality','?')}\nNo auto-apply: True\n=== END ===\n")



    # Core framework: MigrationCompat
    try:
        from factor_lab.core.migration import MigrationCompat
        _c = MigrationCompat(str(output_dir), result.get("run_id", "?"), "adaptive_recommendation")
        for _fn in ["adaptive_recommendation_report.html", "adaptive_recommendation.json", "audit.log"]:
            import os
            if os.path.exists(os.path.join(str(output_dir), _fn)):
                _c.legacy(_fn)
        _c.finalize(safety={"auto_apply": False, "no_live_trade": True})
    except Exception:
        pass

def _build_html(result):
    cc = result.get("current_config", {})
    recs = result.get("recommendations", [])
    rec_rows = "".join(f"<tr><td>{r.get('recommendation','')}</td><td>{r.get('confidence','')}</td><td>{r.get('evidence_strength','')}</td><td>{r.get('evidence','')}</td></tr>" for r in recs)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>策略参数自适应建议 {result['period']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px 6px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>📊 策略参数自适应建议 V2.8</h1>
<p style="color:#aaa;">{result['period']} | 完成 {result['n_completed_days']}天 | Pending {result['n_pending_days']}天 | 证据: {result.get('evidence_quality','?')}</p></div>

<div class="card"><h2>⚙️ 当前配置</h2>
<table><tr><td>Plan</td><td>{cc.get('plan','?')}</td></tr>
<tr><td>TopN</td><td>{cc.get('top_n','?')}</td></tr>
<tr><td>ETF 权重</td><td>{cc.get('etf_weight_pct','?')}%</td></tr>
<tr><td>调仓频率</td><td>{cc.get('rebalance_freq','?')}</td></tr></table></div>

<div class="card"><h2>💡 建议汇总</h2>
<table><tr><th>建议</th><th>Confidence</th><th>证据强度</th><th>证据</th></tr>{rec_rows}</table></div>

<div class="card"><h2>📝 人工审批</h2>
<p>路径: <a href="manual_approval_template.md">manual_approval_template.md</a></p>
<p>不自动执行, 需人工确认后才能调整配置。</p></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.8 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
