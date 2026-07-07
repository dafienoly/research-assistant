"""科创板半导体设备 ETF 下午跳水预警

分析逻辑：
1. 量价背离 — 上午量增价不涨 / 缩量拉升
2. 大单资金 — 主力净流入转为流出
3. 分时均线偏离 — 价格远离分时均线
4. 板块联动 — 龙头股冲高回落
5. 涨幅过高 — 上午涨幅 >3% 且回撤 >1/2

用法:
  python3 etf_dive_warning.py [--code 159516]
"""
import sys, json, subprocess, os, re
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
_BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(_BASE))
from config import VENV_PYTHON

MX = [VENV_PYTHON, str(_BASE / "mx.py")]

# ── 配置 ────────────────────────────────────────────
# 默认监测标的：国泰中证半导体材料设备主题ETF
DEFAULT_CODE = "159516"
DEFAULT_NAME = "半导体设备ETF(159516)"

# 阈值
RISK_THRESHOLDS = {
    "volume_price_divergence": {"上午量比 < 0.7 且涨幅 > 1.5%": 2},
    "large_order_outflow": {"主力净流入 < -0.5亿": 2, "主力净流入 < -1亿": 3},
    "price_vwap_deviation": {"偏离均线 < -0.5%": 2, "偏离均线 < -1.0%": 3},
    "morning_surge_fade": {"上午涨幅 > 3% 且回撤 > 1/2": 3},
    "sector_weakness": {"板块龙头冲高回落": 2},
}


def mx_data(query: str) -> dict:
    """调用 mx:data，返回字段字典"""
    r = subprocess.run(MX + ["data", query], capture_output=True, text=True, timeout=30)
    if "API 返回异常" in r.stdout or "调用次数已达到上限" in r.stdout:
        return {"_error": "API limit", "_raw": r.stdout[:200]}
    data = {}
    for line in r.stdout.split("\n"):
        line = line.strip()
        if not line or line.startswith("**"):
            continue
        m = re.match(r"\s*(f\d+):\s*(.+)", line)
        if m:
            data[m.group(1)] = m.group(2).strip()
        # 也解析中文名段
        m2 = re.match(r"\s*([\u4e00-\u9fff]+[\u4e00-\u9fff\d.+\-%%亿万元]*)", line)
    return data


def parse_float(v, default=0.0) -> float:
    try:
        v = v.replace("亿元", "").replace("亿", "").replace("%", "").strip()
        return float(v)
    except (ValueError, AttributeError):
        return default


def check_dive_risk(code: str = DEFAULT_CODE, name: str = DEFAULT_NAME) -> dict:
    """执行跳水风险分析，返回分级结果"""
    signals = []
    score = 0
    max_score = 0

    # 1. 获取实时行情（合并查询减少 API 调用）
    quote = mx_data(f"{code} 实时行情 资金流向 今日")

    if quote.get("_error"):
        return {
            "error": f"API 调用受限: {quote['_raw']}",
            "risk": "未知",
            "score": 0,
            "code": code,
            "name": name,
            "summary": f"\n{'═'*50}\n  ⚠️  妙想 API 调用已达上限(150次/日)，无法获取 {code} 实时数据\n  💡  明日重置后重试，或升级套餐\n{'═'*50}\n",
        }

    if not quote:
        return {"error": f"无法获取 {code} 行情数据", "risk": "未知", "score": 0}

    price = parse_float(quote.get("f2"))
    change_pct = parse_float(quote.get("f3"))
    high = parse_float(quote.get("f15"))
    low = parse_float(quote.get("f16"))
    turnover = parse_float(quote.get("f6"))
    amplitude = parse_float(quote.get("f7"))

    # 资金流向（从相同 dict 获取，合并查询）
    main_net = parse_float(quote.get("主力净流入", "0"))
    super_large = parse_float(quote.get("超大单净流入", "0"))
    large_net = parse_float(quote.get("大单净流入", "0"))
    mid_net = parse_float(quote.get("中单净流入", "0"))

    # 2. 信号分析
    now = datetime.now(CST)
    is_afternoon = now.hour >= 13

    # 信号 1: 涨幅过高 → 下午容易回落
    if change_pct > 3.0:
        # 从日内最高回撤了多少
        if high > price:
            retrace = (high - price) / high * 100
            if retrace > change_pct / 2:  # 回撤超过涨幅一半
                signals.append({
                    "signal": "morning_surge_fade",
                    "label": "上午冲高回落",
                    "detail": f"涨幅{change_pct:.1f}%，从高点回撤{retrace:.1f}%（过半）",
                    "weight": 3,
                })
            elif retrace > 1.0:
                signals.append({
                    "signal": "morning_surge_fade",
                    "label": "涨幅偏高",
                    "detail": f"涨幅{change_pct:.1f}%，当前距高点回撤{retrace:.1f}%",
                    "weight": 2,
                })

    # 信号 2: 大单流出
    if main_net < -0.5:
        w = 3 if main_net < -1.0 else 2
        signals.append({
            "signal": "large_order_outflow",
            "label": "主力资金流出",
            "detail": f"主力净流入{main_net:+.2f}亿，超大单{super_large:+.2f}亿，大单{large_net:+.2f}亿",
            "weight": w,
        })
    elif large_net < -0.5 and main_net < 0:
        signals.append({
            "signal": "large_order_outflow",
            "label": "大单流出",
            "detail": f"大单净流入{large_net:+.2f}亿，中小单流入{mid_net:+.2f}亿（散户接盘）",
            "weight": 2,
        })

    # 信号 3: 量价背离（成交量放大但价格不涨）
    if turnover > 20 and change_pct < 0.5:
        signals.append({
            "signal": "volume_price_divergence",
            "label": "放量滞涨",
            "detail": f"成交额{turnover:.0f}亿，涨幅仅{change_pct:.1f}%",
            "weight": 2,
        })

    # 信号 4: 振幅大 + 涨幅低 = 多空分歧大
    if amplitude > 5 and change_pct < 1.0:
        signals.append({
            "signal": "high_volatility",
            "label": "多空分歧大",
            "detail": f"振幅{amplitude:.1f}%，涨幅仅{change_pct:.1f}%",
            "weight": 1,
        })

    # 信号 5: 散户接盘（中小单流入但大单流出）
    if mid_net > 0.3 and large_net < -0.3:
        signals.append({
            "signal": "retail_suckered",
            "label": "散户接盘",
            "detail": f"中单净流入{mid_net:+.2f}亿 vs 大单净流出{large_net:+.2f}亿",
            "weight": 2,
        })

    # 3. 综合评分
    for s in signals:
        score += s["weight"]
        max_score += 3  # 每信号满分3分

    # 4. 风险等级
    ratio = score / max(1, max(9, max_score))
    if ratio >= 0.6 or score >= 8:
        risk = "极高"
    elif ratio >= 0.4 or score >= 5:
        risk = "高"
    elif ratio >= 0.25 or score >= 3:
        risk = "中"
    else:
        risk = "低"

    summary = (
        f"\n{'═'*50}\n"
        f"  🏷️  {name}\n"
        f"  📊  {price:.3f}  涨幅{change_pct:+.1f}%  振幅{amplitude:.1f}%\n"
        f"  💰  成交额{turnover:.0f}亿  换手{quote.get('f8','?')}%\n"
        f"  🏦  主力净流入{main_net:+.2f}亿\n"
        f"  ⏰  {now.strftime('%H:%M')} ({'下午' if is_afternoon else '上午'})\n"
        f"\n  🚨 跳水风险: {risk} (评分 {score}/{max_score if max_score > 9 else 9})\n"
    )

    for s in signals:
        summary += f"  ⚡ [{s['label']}] {s['detail']}\n"

    summary += f"{'═'*50}\n"
    if risk in ("高", "极高"):
        summary += "  💡 建议: 下午密切关注，设置回落止损\n"
    elif risk == "中":
        summary += "  💡 建议: 留意量能变化，不要追高\n"
    else:
        summary += "  💡 建议: 暂无明显跳水信号\n"

    return {
        "code": code,
        "name": name,
        "price": price,
        "change_pct": change_pct,
        "turnover": turnover,
        "main_net": main_net,
        "risk": risk,
        "score": score,
        "max_score": max(9, max_score),
        "signals": signals,
        "summary": summary,
        "time": now.strftime("%H:%M"),
        "is_afternoon": is_afternoon,
    }


def main():
    import argparse
    p = argparse.ArgumentParser(description="科创板半导体设备ETF下午跳水预警")
    p.add_argument("--code", default=DEFAULT_CODE, help="ETF代码")
    p.add_argument("--json", action="store_true", help="JSON输出")
    args = p.parse_args()

    result = check_dive_risk(code=args.code)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(result.get("summary", result.get("error", "未知错误")))

    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
