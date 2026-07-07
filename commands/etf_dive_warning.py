"""科创板半导体设备 ETF 下午跳水预警

分析逻辑：
1. 量价背离 — 上午量增价不涨 / 缩量拉升
2. 大单资金 — 主力净流入转为流出
3. 分时均线偏离 — 价格远离分时均线
4. 板块联动 — 龙头股冲高回落
5. 涨幅过高 — 上午涨幅 >3% 且回撤 >1/2

数据源（优先级）:
  1. akshare (fund_etf_spot_em) — 全字段实时行情 + 资金流向
  2. 本地 live_snapshot.csv — 已有快照
  3. mx:data — 东方财富妙想（免费版 150次/日）

用法:
  python3 etf_dive_warning.py [--code 159516]
"""
import sys, json, subprocess, os, re, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
_BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(_BASE))
from config import VENV_PYTHON

# ── 配置 ────────────────────────────────────────────
DEFAULT_CODE = "159516"
DEFAULT_NAME = "半导体设备ETF(159516)"
PROJECT_ROOT = Path.home() / ".hermes" / "research-assistant"
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "market" / "live_snapshot.csv"


def _fetch_akshare(code: str) -> dict | None:
    """通过 akshare 获取 ETF 实时行情 + 资金流向（优先）"""
    try:
        import akshare as ak
        df = ak.fund_etf_spot_em()
        row = df[df["代码"] == code]
        if row.empty:
            return None
        r = row.iloc[0]
        # 资金流向也用 akshare
        fund = None
        try:
            fdf = ak.stock_individual_fund_flow(stock=code, market="sh")
            if not fdf.empty:
                fund = {
                    "主力净流入": fdf.iloc[-1].get("主力净流入-净额", 0),
                    "超大单净流入": fdf.iloc[-1].get("超大单净流入-净额", 0),
                    "大单净流入": fdf.iloc[-1].get("大单净流入-净额", 0),
                    "中单净流入": fdf.iloc[-1].get("中单净流入-净额", 0),
                    "小单净流入": fdf.iloc[-1].get("小单净流入-净额", 0),
                }
        except Exception:
            pass

        quote = {
            "price": float(r.get("最新价", 0)),
            "change_pct": float(r.get("涨跌幅", 0)),
            "high": float(r.get("最高价", 0)),
            "low": float(r.get("最低价", 0)),
            "open": float(r.get("开盘价", 0)),
            "turnover": float(r.get("成交额", 0)) / 1e8,  # 转亿
            "amplitude": float(r.get("振幅", 0)),
            "turnover_rate": float(r.get("换手率", 0)),
            "volume": float(r.get("成交量", 0)),
            "name": str(r.get("名称", "")),
            "source": "akshare",
            "fund": fund,
        }
        return quote
    except ImportError:
        return None
    except Exception as e:
        return {"_error": str(e)}


def _fetch_snapshot(code: str) -> dict | None:
    """从本地 live_snapshot.csv 读取行情"""
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("code", "").strip() == code:
                    return {
                        "price": float(row.get("last_price", 0)),
                        "change_pct": float(row.get("change_pct", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "turnover": float(row.get("amount", 0)) / 1e8,
                        "amplitude": float(row.get("amplitude", 0)),
                        "source": "snapshot",
                    }
    except Exception:
        pass
    return None


def _fetch_mx(code: str) -> dict | None:
    """通过 mx:data 获取行情（末位备用）"""
    MX = [VENV_PYTHON, str(_BASE / "mx.py")]
    r = subprocess.run(MX + ["data", f"{code} 实时行情"], capture_output=True, text=True, timeout=30)
    if "调用次数已达到上限" in r.stdout:
        return {"_error": "API limit"}
    price = change = high = low = turnover = amplitude = 0.0
    for line in r.stdout.split("\n"):
        m = re.match(r"\s*(f\d+):\s*(.+)", line.strip())
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        try:
            vf = float(v.replace("%", "").replace("亿元", "").replace("亿", ""))
        except ValueError:
            continue
        if k == "f2":
            price = vf
        elif k == "f3":
            change = vf
        elif k == "f15":
            high = vf
        elif k == "f16":
            low = vf
        elif k == "f6":
            turnover = vf
        elif k == "f7":
            amplitude = vf
    if price == 0:
        return None
    return {
        "price": price,
        "change_pct": change,
        "high": high,
        "low": low,
        "turnover": turnover,
        "amplitude": amplitude,
        "source": "mxdata",
    }


def check_dive_risk(code: str = DEFAULT_CODE, name: str = DEFAULT_NAME) -> dict:
    """执行跳水风险分析，返回分级结果"""
    signals = []
    score = 0
    max_score = 0

    # 1. 获取行情（akshare → snapshot → mx:data）
    quote = _fetch_akshare(code)
    if quote is None or quote.get("_error"):
        quote = _fetch_snapshot(code)
    if quote is None:
        quote = _fetch_mx(code)
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
