"""QuantStats 风格回测报告生成器 — 单一指标源 canonical_metrics"""
import json, os, warnings, base64, io, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

CST = timezone(timedelta(hours=8))
OUTPUT_BASE = Path("/mnt/d/HermesReports/backtests")

try:
    import quantstats as qs
    import quantstats.stats as qs_stats
    HAS_QS = True
except ImportError:
    qs_stats = None
    HAS_QS = False

try:
    from reports.font_setup import setup_chinese_matplotlib_font
    setup_chinese_matplotlib_font()
except Exception:
    pass


def canonical_metrics(sr, br, rf=0.03, periods=252):
    """统一指标计算 — QuantStats 优先，fallback 手动"""
    sr = sr.dropna(); br = br.dropna()
    sr, br = sr.align(br, join='inner')
    if len(sr) < 20:
        return {"error": f"样本不足: {len(sr)}天"}
    if HAS_QS:
        sr.index = pd.DatetimeIndex(sr.index)
        br.index = pd.DatetimeIndex(br.index)
        def _v(fn, *a, **kw):
            try: v = fn(*a, **kw); return None if (v is None or (hasattr(v,'shape') and np.isnan(v))) else float(v)
            except: return None
        # QuantStats 部分函数不可用，手动 fallback
        def _beta(s, b):
            try:
                return float(qs_stats.rolling_beta(s, b).mean()) if hasattr(qs_stats, 'rolling_beta') else None
            except: return None
        total_ret = float((1+sr).prod()-1)
        cagr_v = _v(qs_stats.cagr, sr, rf=rf, periods=periods)
        sharpe_v = _v(qs_stats.sharpe, sr, rf=rf, periods=periods)
        sortino_v = _v(qs_stats.sortino, sr, rf=rf, periods=periods)
        mdd_v = _v(qs_stats.max_drawdown, sr)
        vol_v = _v(qs_stats.volatility, sr, periods=periods)
        calmar_v = _v(qs_stats.calmar, sr, periods=periods)
        win_rate_v = _v(qs_stats.win_rate, sr)
        var_v = _v(qs_stats.value_at_risk, sr)
        ir_v = _v(qs_stats.information_ratio, sr, br, periods=periods)
        # Beta: 手动计算
        cov = np.cov(sr, br) if len(sr) > 20 else None
        beta_v = float(cov[0][1]/cov[1][1]) if cov is not None and cov[1][1] > 0 else (None if cov is None else 0)
        return {
            "cumulative_return": round(total_ret*100, 2),
            "cagr": round(cagr_v*100, 2) if cagr_v else None,
            "sharpe": round(sharpe_v, 2) if sharpe_v else None,
            "sortino": round(sortino_v, 2) if sortino_v else None,
            "max_drawdown": round(mdd_v*100, 2) if mdd_v else None,
            "volatility": round(vol_v*100, 2) if vol_v else None,
            "calmar": round(calmar_v, 2) if calmar_v else None,
            "win_rate": round(win_rate_v*100, 2) if win_rate_v else None,
            "var_95": round(var_v*100, 2) if var_v else None,
            "beta": round(beta_v, 4) if beta_v is not None else None,
            "information_ratio": round(ir_v, 2) if ir_v else None,
            "total_days": len(sr),
        }


def generate_report(result, output_dir=None, run_id=None):
    from reports.report_schema import BacktestResult, align_returns
    if not isinstance(result, BacktestResult):
        raise TypeError(f"需要 BacktestResult，收到 {type(result)}")
    result.validate()
    rid = run_id or result.run_id
    out = Path(output_dir) if output_dir else (OUTPUT_BASE / rid)
    out.mkdir(parents=True, exist_ok=True)
    sr, br = align_returns(result.strategy_returns, result.benchmark_returns)
    extras = getattr(result, "_extras", {}) or {}
    ew_rets = extras.get("universe_ew_returns")
    mkt_rets = extras.get("market_benchmark_returns")
    
    metrics = canonical_metrics(sr, br)
    
    # 计算 Active IR vs 等权 / Beta vs 沪深300
    active_ir_ew = None; beta_mkt = None
    if ew_rets is not None:
        c = sr.index.intersection(ew_rets.index)
        if len(c) > 20:
            active_ir_ew = canonical_metrics(sr.loc[c], ew_rets.loc[c]).get("information_ratio")
    if mkt_rets is not None:
        c = sr.index.intersection(mkt_rets.index)
        if len(c) > 20:
            bm = canonical_metrics(sr.loc[c], mkt_rets.loc[c])
            beta_mkt = bm.get("beta")
    
    if HAS_QS:
        html_path = _gen_via_quantstats(sr, br, result, out, metrics, ew_rets, mkt_rets, active_ir_ew, beta_mkt)
    else:
        html_path = _gen_via_matplotlib(sr, br, result, out, metrics)
    
    # 输出文件
    returns_df = pd.DataFrame({"strategy": sr, "benchmark": br, "excess": sr - br})
    returns_df.to_csv(out / "returns.csv", encoding="utf-8-sig")
    eq = (1+sr).cumprod(); beq = (1+br).cumprod()
    pd.DataFrame({"strategy": eq, "benchmark": beq}).to_csv(out / "equity_curve.csv", encoding="utf-8-sig")
    if result.trades is not None and len(result.trades) > 0:
        result.trades.to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    if result.positions is not None and len(result.positions) > 0:
        result.positions.to_csv(out / "positions.csv", index=False, encoding="utf-8-sig")
    
    metrics_out = {**metrics,
        "run_id": rid, "strategy_name": result.strategy_name, "factor_name": result.factor_name,
        "universe": result.universe, "benchmark": result.benchmark_name,
        "start_date": result.start_date, "end_date": result.end_date,
        "rebalance_freq": result.rebalance_freq,
        "active_ir_vs_ew": active_ir_ew,
        "beta_vs_hs300": beta_mkt,
        "generated_at": datetime.now(CST).isoformat(),
        "report_path": str(html_path),
    }
    with open(out / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics_out, f, ensure_ascii=False, indent=2)
    with open(out / "canonical_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics_out, f, ensure_ascii=False, indent=2)
    return {"run_id": rid, "report_path": str(html_path), "metrics": metrics,
            "files": [str(p) for p in out.glob("*") if p.is_file()]}


def _gen_via_quantstats(sr, br, result, out, metrics, ew_rets, mkt_rets, active_ir_ew=None, beta_mkt=None):
    import quantstats as qs
    qs.extend_pandas()
    report_path = out / "report.html"
    title = f"Factor Top-Group Backtest ({result.factor_name})"
    if result.factor_expression:
        title += f" — {result.factor_expression}"
    extras = getattr(result, "_extras", {}) or {}
    ew_name = extras.get("universe_ew_name", "等权重基准")
    mkt_name = extras.get("market_benchmark_name", "沪深300")
    
    common = sr.index
    if ew_rets is not None: common = common.intersection(ew_rets.index)
    if mkt_rets is not None: common = common.intersection(mkt_rets.index)
    sr_a = sr.reindex(common).dropna()
    br_a = br.reindex(common).dropna() if br is not None else None
    ew_a = ew_rets.reindex(common).fillna(0) if ew_rets is not None else None
    mkt_a = mkt_rets.reindex(common).fillna(0) if mkt_rets is not None else None
    
    matched_start = str(sr_a.index[0].date()) if len(sr_a)>0 else ""
    matched_end = str(sr_a.index[-1].date()) if len(sr_a)>0 else ""
    valid_days = len(sr_a)
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        qs.reports.html(sr_a, br_a, title=title, output=str(report_path),
            download_filename=str(report_path), rf=0.03,
            benchmark_title="同池等权", strategy_title=f"{result.strategy_name} / 策略", match_dates=False)
    
    # 三线图 base64
    b64 = _make_three_line_chart_b64(result, sr_a, ew_a, mkt_a)
    html = report_path.read_text(encoding="utf-8")
    insert = f'<div style="max-width:960px;margin:20px auto;text-align:center"><h3 style="color:#333">三线对比: 策略 / 同池等权 / 沪深300</h3><img src="data:image/png;base64,{b64}" style="width:100%;max-width:960px"/><p style="font-size:12px;color:#666;margin-top:4px">绿色=策略 / 蓝色=同池等权 / 红色(虚线)=沪深300</p></div>'
    html = html.replace("<h1>", insert + "<h1>", 1)
    
    # 替换 QuantStats 原生指标表
    html = _replace_metrics_table(html, metrics, ew_a, mkt_a, active_ir_ew, beta_mkt)
    
    report_path.write_text(html, encoding="utf-8")
    _append_chinese_summary(report_path, result, sr_a, br_a, ew_a, mkt_a,
        ew_name, mkt_name, metrics, active_ir_ew, beta_mkt,
        result.start_date, result.end_date, matched_start, matched_end, valid_days)
    _add_bilingual_labels(report_path)
    return report_path


def _replace_metrics_table(html, metrics, ew_rets, mkt_rets, active_ir_ew, beta_mkt):
    def v(key, suffix=""):
        val = metrics.get(key)
        return f"{val}{suffix}" if val is not None else "--"
    ew_ret = float((1+ew_rets).cumprod().iloc[-1]-1)*100 if ew_rets is not None and len(ew_rets)>0 else None
    mkt_ret = float((1+mkt_rets).cumprod().iloc[-1]-1)*100 if mkt_rets is not None and len(mkt_rets)>0 else None
    ai = f"{active_ir_ew:.2f}" if active_ir_ew is not None else "--"
    bm = f"{beta_mkt:.4f}" if beta_mkt is not None else "N/A"
    
    new_table = f"""<h3>Key Performance Metrics / 核心绩效指标</h3>
<table>
<thead><tr><th>指标</th><th>值</th></tr></thead>
<tbody>
<tr><td>Cumulative Return / 累计收益</td><td>{v('cumulative_return','%')}</td></tr>
<tr><td>CAGR / 年化收益</td><td>{v('cagr','%')}</td></tr>
<tr><td>Sharpe / 夏普比率</td><td>{v('sharpe')}</td></tr>
<tr><td>Sortino / 索提诺比率</td><td>{v('sortino')}</td></tr>
<tr><td>Calmar / 卡玛比率</td><td>{v('calmar')}</td></tr>
<tr><td>Max Drawdown / 最大回撤</td><td>{v('max_drawdown','%')}</td></tr>
<tr><td>Volatility (ann.) / 年化波动率</td><td>{v('volatility','%')}</td></tr>
<tr><td>Win Rate / 胜率</td><td>{v('win_rate','%')}</td></tr>
<tr><td>VaR (95%) / 风险价值</td><td>{v('var_95','%')}</td></tr>
<tr><td>Active IR vs 同池等权</td><td>{ai}</td></tr>
<tr><td>Beta vs 沪深300</td><td>{bm}</td></tr>
<tr><td>有效交易日</td><td>{v('total_days')}</td></tr>
</tbody></table>"""
    # 替换从第一个 <h3>Key Performance 到下一个 <h3> 之间的所有内容
    start = html.find('Key Performance Metrics')
    if start < 0: return html
    h3_start = html.rfind('<h3', 0, start)
    if h3_start < 0: return html
    next_h3 = html.find('<h3', h3_start+3)
    if next_h3 < 0: return html
    return html[:h3_start] + new_table + html[next_h3:]


def _make_three_line_chart_b64(result, sr, ew_rets, mkt_rets):
    import matplotlib.pyplot as plt
    eq = (1+sr).cumprod()
    fig, ax = plt.subplots(figsize=(12,5), facecolor="#f8f9fa")
    ax.set_facecolor("#fff")
    eq.plot(ax=ax, color="#3fb950", label=f"策略: {result.strategy_name}", linewidth=2)
    if ew_rets is not None:
        (1+ew_rets).cumprod().plot(ax=ax, color="#58a6ff", label=f"等权: {result.universe}", linewidth=1.5, alpha=0.8)
    if mkt_rets is not None:
        (1+mkt_rets).cumprod().plot(ax=ax, color="#f85149", label="沪深300", linewidth=1.5, alpha=0.8, linestyle="--")
    ax.legend(fontsize=10); ax.set_title("三线对比: 策略 / 同池等权 / 沪深300", fontsize=13, fontweight="bold")
    ax.set_ylabel("净值", fontsize=11); ax.grid(True, alpha=0.3); fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=150); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _append_chinese_summary(report_path, result, sr, br, ew_rets, mkt_rets,
                             ew_name, mkt_name, metrics, active_ir_ew, beta_mkt,
                             req_start, req_end, matched_start, matched_end, valid_days):
    """中文解读区 — 使用 canonical_metrics 的单一指标源"""
    total_ret = metrics.get("cumulative_return", 0)
    cagr_v = metrics.get("cagr")
    sharpe_v = metrics.get("sharpe")
    sortino_v = metrics.get("sortino")
    mdd_v = metrics.get("max_drawdown")
    vol_v = metrics.get("volatility")
    calmar_v = metrics.get("calmar")
    ew_ret = round(float((1+ew_rets).cumprod().iloc[-1]-1)*100, 2) if ew_rets is not None and len(ew_rets)>0 else 0
    mkt_ret = round(float((1+mkt_rets).cumprod().iloc[-1]-1)*100, 2) if mkt_rets is not None and len(mkt_rets)>0 else 0
    excess_ew = total_ret - ew_ret
    excess_mkt = total_ret - mkt_ret
    ir_s = f"{active_ir_ew:.2f}" if active_ir_ew is not None else "N/A"
    beta_s = f"{beta_mkt:.4f}" if beta_mkt is not None else "N/A"
    req = f"请求区间: {req_start} ~ {req_end}" if req_start else ""
    match = f"有效区间: {matched_start} ~ {matched_end}，共 {valid_days} 个交易日"

    def _color(v, thresh=0):
        return '#3fb950' if (v or 0) > thresh else '#f85149'
    def _fmt(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "--"
    def _mdd_c(v):
        if v is None: return ""
        return f'color:{_color(v,-20)}' if v < -20 else 'color:#d29922'

    summary = f"""
<div style="max-width:960px;margin:30px auto;padding:24px;background:#fff;border:1px solid #ddd;border-radius:8px;font-family:'PingFang SC','Microsoft YaHei',sans-serif">
<h2 style="color:#333;border-bottom:2px solid #09c;padding-bottom:8px">📊 报告解读</h2>
<h3 style="color:#333">本报告验证的是什么？</h3>
<p style="color:#555;line-height:1.7">
在 <strong>{result.universe}</strong> 股票池内部，<strong>{result.factor_name}</strong> 因子选择 Top组 股票构建组合后，
表达式: <code>{result.factor_expression or '(未记录)'}</code>，是否跑赢同池子<strong>等权基准</strong>；同时参考 <strong>{mkt_name}</strong>。<br>
{req}<br>{match}
</p>
<h3 style="color:#333">三基准核心指标对比</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px;margin:10px 0">
<tr style="background:#f0f4ff"><th>指标</th><th style="text-align:right">策略 Top20</th><th style="text-align:right">{result.universe} 等权</th><th style="text-align:right">{mkt_name}</th></tr>
<tr><td>累计收益</td><td style="text-align:right;font-weight:700">{_fmt(total_ret,'%')}</td><td style="text-align:right">{_fmt(ew_ret,'%')}</td><td style="text-align:right">{_fmt(mkt_ret,'%')}</td></tr>
<tr><td>CAGR</td><td style="text-align:right">{_fmt(cagr_v,'%')}</td><td style="text-align:right">—</td><td style="text-align:right">—</td></tr>
<tr><td>年化波动率</td><td style="text-align:right">{_fmt(vol_v,'%')}</td><td style="text-align:right">—</td><td style="text-align:right">—</td></tr>
<tr><td>最大回撤</td><td style="text-align:right;{_mdd_c(mdd_v)}">{_fmt(mdd_v,'%')}</td><td style="text-align:right">—</td><td style="text-align:right">—</td></tr>
<tr><td>Sharpe</td><td style="text-align:right;font-weight:700">{_fmt(sharpe_v)}</td><td style="text-align:right">—</td><td style="text-align:right">—</td></tr>
<tr><td>Sortino</td><td style="text-align:right">{_fmt(sortino_v)}</td><td style="text-align:right">—</td><td style="text-align:right">—</td></tr>
<tr><td>Calmar</td><td style="text-align:right">{_fmt(calmar_v)}</td><td style="text-align:right">—</td><td style="text-align:right">—</td></tr>
</table>
<h3 style="color:#333">双重基准超额收益</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px;margin:10px 0">
<tr style="background:#f0f4ff"><th>指标</th><th style="text-align:right">vs 同池等权</th><th style="text-align:right">vs {mkt_name}</th></tr>
<tr><td>超额累计收益</td><td style="text-align:right;font-weight:700;color:{_color(excess_ew)}">{excess_ew:+.2f}%</td><td style="text-align:right;font-weight:700;color:{_color(excess_mkt)}">{excess_mkt:+.2f}%</td></tr>
<tr><td>Active IR</td><td style="text-align:right;font-weight:700">{ir_s}</td><td style="text-align:right">—</td></tr>
<tr><td>Beta</td><td style="text-align:right">—</td><td style="text-align:right">{beta_s}</td></tr>
</table>
<p style="color:#555;line-height:1.7">
<strong>A. 跑赢等权？</strong> 超额 {excess_ew:+.2f}%，Active IR {ir_s}。{'✅ 跑赢' if excess_ew>0 else '❌ 跑输'}<br>
<strong>B. 跑赢沪深300？</strong> 超额 {excess_mkt:+.2f}%，Beta {beta_s}。{'✅ 跑赢' if excess_mkt>0 else '❌ 跑输'}
</p>
<h3 style="color:#333">指标含义</h3>
<p style="color:#555;line-height:1.7">
<strong>Sharpe</strong>：策略相对无风险利率(3%)的风险调整收益。<br>
<strong>Active IR</strong>：策略相对同池等权基准的超额收益/跟踪误差，衡量选股能力。<br>
<strong>Max Drawdown</strong>：最高点到最低点的回撤幅度。<br>
<strong>Beta</strong>：策略相对沪深300的敏感度。<br>
<strong>Volatility</strong>：年化波动率，越小越稳定。
</p>
</div>"""
    html = report_path.read_text(encoding="utf-8")
    html = html.replace("</body>", summary + "\n</body>")
    report_path.write_text(html, encoding="utf-8")


def _add_bilingual_labels(report_path):
    """双语标签替换 + 图表注解"""
    html = report_path.read_text(encoding="utf-8")
    metric_map = {
        "Cumulative Return": "Cumulative Return / 累计收益",
        "CAGR": "CAGR / 年化收益", "Sharpe": "Sharpe / 夏普比率",
        "Sortino": "Sortino / 索提诺比率", "Max Drawdown": "Max Drawdown / 最大回撤",
        "Volatility": "Volatility / 年化波动率", "Calmar": "Calmar / 卡玛比率",
        "Beta": "Beta / 贝塔", "Win Rate": "Win Rate / 胜率",
        "VaR": "VaR / 风险价值",
        "Information Ratio": "Information Ratio / 信息比率",
        "Best": "Best / 最佳", "Worst": "Worst / 最差",
        "Avg": "Avg / 平均", "Start": "Start / 开始",
        "Valley": "Valley / 谷底", "End": "End / 结束",
        "Days": "Days / 天数", "Drawdown": "Drawdown / 回撤",
        "Strategy": "Strategy / 策略", "Benchmark": "Benchmark / 基准",
        "Return": "Return / 收益", "Year": "Year / 年份",
        "Key Performance Metrics": "Key Performance Metrics / 核心绩效指标",
        "Max DD Date": "Max DD Date / 最大回撤日期",
        "Max DD Period Start": "Max DD Period Start / 回撤开始日期",
        "Max DD Period End": "Max DD Period End / 回撤结束日期",
        "Longest DD Days": "Longest DD Days / 最长回撤天数",
    }
    for eng, bil in metric_map.items():
        html = html.replace(f'>{eng}<', f'>{bil}<')
        html = html.replace(f'>{eng} </', f'>{bil} </')
    report_path.write_text(html, encoding="utf-8")
    _add_chart_annotations(report_path)


def _add_chart_annotations(report_path):
    html = report_path.read_text(encoding="utf-8")
    notes = [
        ("Cumulative Returns vs Benchmark", '📈 <b>累计收益曲线</b>：策略 vs 基准净值。'),
        ("Underwater Plot", '🌊 <b>水下图</b>：从高点回撤幅度。'),
        ("Distribution of Monthly Returns", '📊 <b>月收益分布</b>。'),
        ("Monthly Returns (%)", '📅 <b>月度收益热力图</b>。'),
        ("EOY Returns vs Benchmark", '📊 <b>年度收益表</b>。'),
        ("Return Quantiles", '📐 <b>收益分位数</b>。'),
        ("Rolling Beta", '📉 <b>滚动 Beta</b>。'),
        ("Rolling Volatility", '📉 <b>滚动波动率</b>。'),
        ("Rolling Sharpe", '📉 <b>滚动夏普</b>。'),
        ("Rolling Sortino", '📉 <b>滚动索提诺</b>。'),
        ("Daily Returns", '📆 <b>日收益累计和</b>。'),
        ("Log Scale", '📈 <b>对数坐标</b>。'),
        ("Volatility Matched", '📈 <b>波动率匹配</b>。'),
    ]
    for kw, note in notes:
        idx = html.find(f"<!-- {kw}")
        if idx < 0: idx = html.find(kw)
        if idx < 0: continue
        se = html.find("</svg>", idx)
        if se < 0:
            ss = html.rfind("<svg", 0, idx)
            if ss >= 0: se = html.find("</svg>", ss)
        if se < 0: continue
        ann = f'<div style="font-size:12px;color:#666;margin:-6px 0 18px;font-family:PingFang SC,Microsoft YaHei,sans-serif;text-align:center">{note}</div>'
        html = html[:se+6] + ann + html[se+6:]
    report_path.write_text(html, encoding="utf-8")


def _gen_via_matplotlib(sr, br, result, out, metrics):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    eq = (1+sr).cumprod(); beq = (1+br).cumprod()
    dd = (eq - eq.cummax()) / eq.cummax()
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), facecolor="#0d1117")
    c = {"t":"#e6edf3","g":"#30363d","s":"#3fb950","b":"#58a6ff"}
    def sa(ax):
        ax.set_facecolor("#161b22"); ax.tick_params(colors=c["t"], labelsize=8)
        for s in ax.spines.values(): s.set_color(c["g"])
        ax.grid(True, alpha=0.3, color=c["g"])
    eq.plot(ax=axes[0], color=c["s"], label="Strategy", lw=1.5)
    beq.plot(ax=axes[0], color=c["b"], label="Benchmark", lw=1.5)
    sa(axes[0]); axes[0].set_ylabel("Equity", color=c["t"]); axes[0].legend(labelcolor=c["t"])
    axes[0].set_title("Cumulative Return", color=c["t"])
    dd.plot(ax=axes[1], color="#f85149", lw=1, alpha=0.8)
    axes[1].fill_between(dd.index, 0, dd.values, color="#f85149", alpha=0.2)
    sa(axes[1]); axes[1].set_ylabel("Drawdown", color=c["t"]); axes[1].set_title("Drawdown", color=c["t"])
    m = sr.resample("ME").apply(lambda x: (1+x).prod()-1)*100
    m.plot(kind="bar", ax=axes[2], color=["#f85149" if v<0 else "#3fb950" for v in m.values], width=0.8)
    sa(axes[2]); axes[2].set_ylabel("Return %", color=c["t"]); axes[2].set_title("Monthly Returns", color=c["t"])
    plt.tight_layout()
    png = out / "report_fallback.png"
    fig.savefig(png, dpi=150, facecolor=fig.get_facecolor()); plt.close(fig)
    html_path = out / "report.html"
    _write_fallback_html(html_path, result, sr, br, metrics, str(png))
    return html_path


def _write_fallback_html(html_path, result, sr, br, metrics, png_path):
    total_ret = metrics.get("cumulative_return", 0)
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{result.strategy_name} Backtest Report</title>
<style>
body{{font-family:'PingFang SC',sans-serif;background:#fff;color:#333;margin:30px}}
.container{{max-width:960px;margin:auto}}
h1{{border-bottom:2px solid #09c;padding-bottom:8px}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}}
.metric{{background:#f8f9fa;padding:12px;border-radius:6px;text-align:center}}
.metric-value{{font-size:1.3rem;font-weight:700}}
.metric-label{{font-size:.8rem;color:#666}}
img{{width:100%}}
.footer{{text-align:center;color:#999;font-size:.8rem;margin-top:40px}}
</style></head><body>
<div class="container">
<h1>{result.strategy_name} Backtest Report</h1>
<div class="metrics">
<div class="metric"><div class="metric-value">{total_ret:.2f}%</div><div class="metric-label">累计收益</div></div>
<div class="metric"><div class="metric-value">{metrics.get('sharpe','--')}</div><div class="metric-label">夏普</div></div>
<div class="metric"><div class="metric-value">{metrics.get('max_drawdown','--')}%</div><div class="metric-label">最大回撤</div></div>
<div class="metric"><div class="metric-value">{metrics.get('cagr','--')}%</div><div class="metric-label">年化</div></div>
</div>
<img src="{png_path}" alt="Equity Curve">
<div class="footer">Hermes Factor Lab · {datetime.now(CST).strftime('%Y-%m-%d %H:%M')}</div>
</div></body></html>"""
    html_path.write_text(html, encoding="utf-8")


def _calc_fallback(sr, br, rf=0.03, periods=252):
    total_ret = float((1+sr).prod()-1)
    ny = len(sr)/periods
    cagr = float((1+total_ret)**(1/ny)-1) if ny>0 else 0
    vol = float(sr.std()*np.sqrt(periods))
    sharpe = float((sr.mean()*periods-rf)/vol) if vol>0 else 0
    ds = sr[sr<0]
    ddv = float(ds.std()*np.sqrt(periods)) if len(ds)>0 else vol
    sortino = float((sr.mean()*periods-rf)/ddv) if ddv>0 else 0
    eq = (1+sr).cumprod()
    mdd = float(((eq-eq.cummax())/eq.cummax()).min())
    calmar = float(cagr/abs(mdd)) if mdd!=0 else 0
    cov = np.cov(sr, br)
    beta = float(cov[0][1]/cov[1][1]) if cov[1][1]>0 else 0
    exc = sr-br
    te = float(exc.std()*np.sqrt(periods)) if len(exc)>0 else 0
    ir = float(exc.mean()/exc.std()*np.sqrt(periods)) if exc.std()>0 else 0
    return {"cumulative_return": round(total_ret*100,2), "cagr": round(cagr*100,2),
        "sharpe": round(sharpe,2), "sortino": round(sortino,2),
        "max_drawdown": round(mdd*100,2), "volatility": round(vol*100,2),
        "calmar": round(calmar,2), "beta": round(beta,4),
        "information_ratio": round(ir,2), "total_days": len(sr)}