"""因子挖掘报告生成器 — 模板加载式"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

TEMPLATE_PATH = Path(__file__).parent / "report_template.html"

def _load_template() -> str:
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()

def build_report(factor_stats: list, daily_ic: dict, layer_results: dict,
                 output_path: str = None) -> str:
    total = len(factor_stats)
    mean_ics = [s.get("mean_ic", 0) for s in factor_stats if s.get("mean_ic")]
    mean_ic_avg = sum(mean_ics) / len(mean_ics) if mean_ics else 0
    irs = [s.get("ir", 0) for s in factor_stats if s.get("ir")]
    ir_avg = sum(irs) / len(irs) if irs else 0
    pos = sum(1 for s in factor_stats if s.get("mean_ic", 0) > 0)
    top = sum(1 for s in factor_stats if abs(s.get("mean_ic", 0)) >= 0.03)

    # 多空收益数据
    ls_data = {}
    for fn, lt in layer_results.items():
        if isinstance(lt, dict) and "long_short_mean" in lt:
            ls_data[fn] = {
                "ls_return": round(lt.get("long_short_mean", 0) * 100, 2),
                "ls_sharpe": round(lt.get("long_short_sharpe", 0), 2),
            }

    html = _load_template()
    html = html.replace("{{FACTORS_JSON}}", json.dumps(factor_stats, ensure_ascii=False, default=str))
    html = html.replace("{{IC_JSON}}", json.dumps(daily_ic, ensure_ascii=False, default=str))
    html = html.replace("{{LAYER_JSON}}", json.dumps(layer_results, ensure_ascii=False, default=str))
    html = html.replace("{{LS_JSON}}", json.dumps(ls_data, ensure_ascii=False, default=str))
    html = html.replace("{{TOTAL_FACTORS}}", str(total))
    html = html.replace("{{MEAN_IC}}", f"{mean_ic_avg:.4f}")
    html = html.replace("{{IR}}", f"{ir_avg:.2f}")
    html = html.replace("{{TOP_COUNT}}", str(top))
    html = html.replace("{{POS_RATIO}}", f"{pos}/{total}")
    html = html.replace("{{TIMESTAMP}}", datetime.now(CST).strftime("%Y-%m-%d %H:%M"))

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
    return html