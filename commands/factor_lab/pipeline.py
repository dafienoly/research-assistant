"""因子挖掘全流程调度"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get("HERMES_FACTOR_REPORT_ROOT", "/mnt/d/HermesReports/factor_lab"))

def load_universe() -> list:
    """从 universe 加载股票池"""
    from strategy_lab.universe import build
    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    return sorted(pool)

def run_mining(output_dir: str = None) -> dict:
    """全流程：加载数据 → 算因子 → IC分析 → 报告"""
    from factor_lab.factor_engine import load_stock_kline, compute_all
    from factor_lab.ic_analyzer import calc_daily_ic, calc_rankic_ir, layer_test
    from factor_lab.report_html import build_report
    
    out_dir = Path(output_dir) if output_dir else (OUTPUT / datetime.now(CST).strftime("%Y%m%d_%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Step 1: 加载股票池
    symbols = load_universe()
    print(f"📦 股票池: {len(symbols)} 只")
    
    # Step 2: 加载 K 线
    df = load_stock_kline(symbols)
    print(f"📊 K 线: {len(df)} 行, {df['date'].min()} ~ {df['date'].max()}")
    
    # Step 3: 计算收益率（下期收益，用于 IC）
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(-1))
    
    # Step 4: 批量计算因子
    factor_df = compute_all(df)
    print(f"🧮 因子计算完成: {factor_df.shape[1] - 3} 个因子")
    
    # Step 5: IC 分析
    factor_cols = [c for c in factor_df.columns if c not in ("date","symbol","close","ret1")]
    from factor_lab.factor_base import list_factors
    registry = {f["name"]: f for f in list_factors()}
    
    daily_ic_data = {}
    layer_data = {}
    stats_list = []
    
    for col in factor_cols:
        dic = calc_daily_ic(factor_df, col)
        daily_ic_data[col] = dic.to_dict("records") if not dic.empty else []
        ic_stats = calc_rankic_ir(dic)
        stats_list.append({
            "name": col,
            "category": registry.get(col, {}).get("category", ""),
            "description": registry.get(col, {}).get("description", ""),
            **ic_stats,
        })

    # 对 TOP15 因子做分层回测（多空收益）
    top15 = sorted(stats_list, key=lambda x: -abs(x.get("mean_ic", 0)))[:15]
    for s in top15:
        col = s["name"]
        lt = layer_test(factor_df, col)
        layer_data[col] = lt
    
    # 按 IC 排序
    stats_list.sort(key=lambda x: -abs(x.get("mean_ic", 0)))
    
    # Step 6: 输出 CSV 和 JSON
    import csv
    csv_path = out_dir / "factor_ranking.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=stats_list[0].keys() if stats_list else [])
        w.writeheader()
        w.writerows(stats_list)
    
    json_path = out_dir / "factor_ic_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"stats": stats_list, "generated_at": str(datetime.now(CST))}, f, ensure_ascii=False, indent=2)
    
    # Step 7: HTML 报告
    html_path = out_dir / "factor_report.html"
    build_report(stats_list, daily_ic_data, layer_data, str(html_path))
    print(f"📄 报告已生成: {html_path}")
    
    return {
        "symbols": len(symbols),
        "kline_rows": len(df),
        "factors": len(factor_cols),
        "output_dir": str(out_dir),
        "html_report": str(html_path),
        "top_factors": stats_list[:10],
    }

if __name__ == "__main__":
    r = run_mining()
    print(f"✅ 完成: {r['factors']} 个因子, 报告: {r['html_report']}")
