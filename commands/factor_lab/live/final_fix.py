"""V1.8 hotfix: 修正报告输出文件

在 signal_cli 运行后执行, 修正:
  1. watch_candidates.csv 确保 20 行 (风控排除后补位)
  2. premarket_signal.json 增加 risk_excluded 字段
  3. HTML 标签修正 (watch 范围 + 增加风控排除表)
"""
import json, csv, re
from pathlib import Path

OUT = Path("/mnt/d/HermesReports/live_signals/20260703")


def final_fix():
    with open(OUT / "premarket_signal.json") as f:
        data = json.load(f)

    target = data.get("target_candidates", [])
    watch = data.get("watch_candidates", [])

    # 如果 watch 不足 20, 从 removed 风控的补位
    if len(watch) < 20 and "candidates" in data:
        all_c = data["candidates"]
        used_syms = {c["symbol"] for c in target} | {c["symbol"] for c in watch}
        fill = [c for c in all_c if c["symbol"] not in used_syms]
        needed = 20 - len(watch)
        watch.extend(fill[:needed])
        data["watch_candidates"] = watch
        data["n_watch"] = len(watch)

    # 增加 risk_excluded 字段
    if "risk_check" in data:
        rc = data["risk_check"]
        details = rc.get("details", [])
        risk_excluded = []
        for c in data.get("candidates", target + watch):
            for d in details:
                if d["symbol"] == c.get("symbol", ""):
                    risk_excluded.append({
                        "symbol": c["symbol"],
                        "ret5": c.get("ret5", 0),
                        "rank": c.get("rank", 0),
                        "risk_type": d["risk_type"],
                    })
        data["risk_excluded"] = risk_excluded

    # 写回 JSON
    with open(OUT / "premarket_signal.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # 重写 CSV
    _write_csv(OUT / "watch_candidates.csv", watch,
               ["symbol", "name", "close", "ret5", "ma20", "close_gt_ma20", "rank", "amount", "risk_flags", "reason"])

    # 修复 HTML
    html_path = OUT / "premarket_signal.html"
    html = html_path.read_text("utf-8")

    # 修复 watch 标签
    watch_end = 20 + len(watch)
    html = html.replace("观察名单 (21-39", f"观察名单 (21-{watch_end}")
    html = html.replace("Top19", f"Top{len(watch)}")

    # 如果已经有 risk_excluded 表, 跳过; 否则追加
    if "风控排除" not in html and data.get("risk_excluded"):
        excl_rows = ""
        for e in data["risk_excluded"]:
            excl_rows += f"<tr><td>{e['symbol']}</td><td>{e.get('ret5',0)*100:.1f}%</td><td>{e.get('risk_type','')}</td></tr>"
        excl_section = f"""
<div class="card">
<h2>🛡️ 风控排除</h2>
<p style="color:#ff9100;font-size:0.85em;">以下股票在候选范围内但触发了风控规则, 已从 target/watch 中移除:</p>
<table><tr><th>代码</th><th>ret5</th><th>风控原因</th></tr>{excl_rows}</table></div>"""
        html = html.replace('</body>', excl_section + '\n</body>')

    html_path.write_text(html, "utf-8")

    print(f"✅ 最终修复完成")
    print(f"   watch_candidates.csv: {len(watch)} 行")
    print(f"   risk_excluded: {len(data.get('risk_excluded',[]))} 只")
    print(f"   HTML 标签已修正")


def _write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


if __name__ == "__main__":
    final_fix()
