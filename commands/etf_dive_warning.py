"""科创板半导体设备 ETF 下午跳水预警

分析逻辑：
1. 量价背离 — 上午量增价不涨 / 缩量拉升
2. 大单资金 — 主力净流入转为流出
3. 分时均线偏离 — 价格远离分时均线
4. 板块联动 — 龙头股冲高回落
5. 涨幅过高 — 上午涨幅 >3% 且回撤 >1/2

数据源：DataHub canonical live snapshot。业务模块不自行访问 provider。

用法:
  python3 etf_dive_warning.py [--code 159516]
"""
import sys, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
_BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(_BASE))
from factor_lab.datahub_access import read_live_snapshot

# ── 配置 ────────────────────────────────────────────
DEFAULT_CODE = "159516"
DEFAULT_NAME = "半导体设备ETF(159516)"
def _fetch_snapshot(code: str) -> dict | None:
    """从 DataHub canonical live snapshot 读取行情。"""
    try:
        row = read_live_snapshot([code]).get(code)
    except (FileNotFoundError, ValueError, OSError) as error:
        return {"_error": str(error)}
    if not row or row.get("price") is None:
        return None
    return {
        "price": row.get("price") or 0,
        "change_pct": row.get("change_pct") or 0,
        "high": row.get("high") or 0,
        "low": row.get("low") or 0,
        "open": row.get("open") or 0,
        "turnover": (row.get("amount") or 0) / 1e8,
        "amplitude": row.get("amplitude") or 0,
        "turnover_rate": row.get("turnover_rate") or 0,
        "volume": row.get("volume") or 0,
        "name": row.get("name") or "",
        "source": row.get("source", "datahub"),
        "fund": None,
    }


def check_dive_risk(code: str = DEFAULT_CODE, name: str = DEFAULT_NAME) -> dict:
    """执行跳水风险分析，返回分级结果"""
    signals = []
    score = 0
    max_score = 0

    # 1. 只读 DataHub；缺失或过期时不允许业务层自行联网降级。
    quote = _fetch_snapshot(code)
    if quote is None or quote.get("_error"):
        reason = str(quote.get("_error", "所有数据源均不可用")) if quote else "所有数据源均不可用"
        return {
            "error": f"数据获取失败: {reason}",
            "risk": "未知", "score": 0, "code": code, "name": name,
            "summary": f"\n{'═'*50}\n  ⚠️  无法获取 {code} 实时数据\n  💡  {reason}\n{'═'*50}\n",
        }

    price = quote.get("price", 0)
    change_pct = quote.get("change_pct", 0)
    high = quote.get("high", 0)
    low = quote.get("low", 0)
    turnover = quote.get("turnover", 0)
    amplitude = quote.get("amplitude", 0)

    # 资金流向（akshare 特有字段）
    fund = quote.get("fund", {})
    main_net = fund.get("主力净流入", 0) / 1e8 if fund else 0
    large_net = fund.get("大单净流入", 0) / 1e8 if fund else 0
    mid_net = fund.get("中单净流入", 0) / 1e8 if fund else 0

    # 2. 信号分析
    now = datetime.now(CST)
    is_afternoon = now.hour >= 13

    # 信号 1: 冲高回落
    if change_pct > 3.0 and high > price:
        retrace = (high - price) / high * 100
        if retrace > change_pct / 2:
            signals.append({"signal": "morning_surge_fade", "label": "上午冲高回落",
                            "detail": f"涨幅{change_pct:.1f}%，从高点回撤{retrace:.1f}%（过半）", "weight": 3})
        elif retrace > 1.0:
            signals.append({"signal": "morning_surge_fade", "label": "涨幅偏高",
                            "detail": f"涨幅{change_pct:.1f}%，距高点回撤{retrace:.1f}%", "weight": 2})

    # 信号 2: 大单流出
    if main_net < -0.5:
        w = 3 if main_net < -1.0 else 2
        signals.append({"signal": "large_order_outflow", "label": "主力资金流出",
                        "detail": f"主力净流入{main_net:+.2f}亿", "weight": w})
    elif large_net < -0.3 and mid_net > 0.3:
        signals.append({"signal": "retail_suckered", "label": "散户接盘",
                        "detail": f"大单{large_net:+.2f}亿 vs 中单{mid_net:+.2f}亿", "weight": 2})

    # 信号 3: 放量滞涨
    if turnover > 20 and abs(change_pct) < 0.5:
        signals.append({"signal": "volume_price_divergence", "label": "放量滞涨",
                        "detail": f"成交额{turnover:.0f}亿，涨幅仅{change_pct:.1f}%", "weight": 2})

    # 信号 4: 多空分歧大
    if amplitude > 5 and abs(change_pct) < 1.0:
        signals.append({"signal": "high_volatility", "label": "多空分歧大",
                        "detail": f"振幅{amplitude:.1f}%，涨幅仅{change_pct:.1f}%", "weight": 1})

    # 3. 综合评分
    for s in signals:
        score += s["weight"]
        max_score += 3

    # 4. 风险等级
    ratio = score / max(9, max_score)
    if ratio >= 0.6 or score >= 8:
        risk = "极高"
    elif ratio >= 0.4 or score >= 5:
        risk = "高"
    elif ratio >= 0.25 or score >= 3:
        risk = "中"
    else:
        risk = "低"

    parts = [
        f"\n{'═'*50}",
        f"  🏷️  {name}  (数据源: {quote.get('source','?')})",
        f"  📊  {price:.3f}  涨幅{change_pct:+.1f}%  振幅{amplitude:.1f}%",
        f"  💰  成交额{turnover:.0f}亿",
    ]
    if fund:
        parts.append(f"  🏦  主力{main_net:+.2f}亿  大单{large_net:+.2f}亿  中单{mid_net:+.2f}亿")
    parts.append(f"  ⏰  {now.strftime('%H:%M')} ({'下午' if is_afternoon else '上午'})")
    parts.append(f"\n  🚨 跳水风险: {risk} (评分 {score}/{max(9, max_score)})")
    for s in signals:
        parts.append(f"  ⚡ [{s['label']}] {s['detail']}")
    parts.append(f"{'═'*50}")
    advice = {"极高": "下午密切关注，设置回落止损", "高": "下午注意回落风险",
              "中": "留意量能变化，不要追高", "低": "暂无明显跳水信号"}.get(risk, "")
    if advice:
        parts.append(f"  💡 建议: {advice}")

    return {
        "code": code, "name": name, "price": price, "change_pct": change_pct,
        "turnover": turnover, "main_net": main_net, "risk": risk,
        "fund_data_status": "OK" if fund else "MISSING",
        "score": score, "max_score": max(9, max_score),
        "signals": signals, "summary": "\n".join(parts),
        "time": now.strftime("%H:%M"), "is_afternoon": is_afternoon,
        "source": quote.get("source", "?"),
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
