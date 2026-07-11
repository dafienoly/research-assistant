#!/usr/bin/env python3
"""588710 科创半导体设备ETF华泰柏瑞 — 开盘监测看板

用法:
  python3 monitor_588710.py              # 单次监测快照
  python3 monitor_588710.py --watch 60   # 每60秒循环监测

所有业务输入只读 DataHub：
  - ETF 权重股  → normalized/etf_holdings + canonical stock_basic
  - 实时行情    → canonical market/live_snapshot
  - 北向资金    → canonical north_flow_timeseries
  - 韩国KOSPI   → canonical 数据未接入时显式 MISSING
"""

import sys, json, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path.home() / ".hermes" / "research-assistant" / "commands"
sys.path.insert(0, str(BASE))
from factor_lab.datahub_access import read_etf_holdings, read_latest_north_flow, read_live_snapshot, read_stock_name_map

# ======== 全局变量：模块加载时从 datahub 拉取 ========
ETF_CODE = "588710"
ETF_NAME = "科创半导体设备ETF华泰柏瑞"
HOLDINGS: dict[str, tuple[str, float]] = {}
ALL_CODES: list[str] = []


# ======================================================================
# 权重股动态加载
# ======================================================================

def _load_holdings():
    """从 DataHub canonical ETF holdings 加载最新十大重仓。"""
    global HOLDINGS, ALL_CODES
    try:
        frame = read_etf_holdings("588710.SH")
        names = read_stock_name_map()
    except (FileNotFoundError, ValueError, OSError) as error:
        print(f"  [DataHub ETF 持仓不可用: {error}]")
        return
    holdings = {}
    for row in frame.head(10).to_dict(orient="records"):
        symbol = str(row["symbol"]).split(".")[0].zfill(6)
        holdings[symbol] = (names.get(symbol, symbol), float(row["stk_mkv_ratio"]))
    HOLDINGS.clear()
    HOLDINGS.update(holdings)
    ALL_CODES.clear()
    ALL_CODES.extend([ETF_CODE, *HOLDINGS])


# 模块加载时不主动拉取（build_snapshot 惰性加载）


# ======================================================================
# 工具函数
# ======================================================================

def now_str() -> str:
    return datetime.now(CST).strftime("%H:%M:%S")


def market_status():
    now = datetime.now(CST)
    t = now.hour * 60 + now.minute
    wd = now.weekday()
    if wd >= 5:
        return "休市 (周末)", 0
    if t < 570:
        return f"盘前 (距开盘还有{570 - t}分钟)", 570 - t
    if 570 <= t < 780:
        return "交易中 ⚡", 0
    if 780 <= t < 810:
        return "午休", 0
    if 810 <= t < 900:
        return "交易中 ⚡", 0
    if 900 <= t < 930:
        return "收盘集合竞价", 0
    return "已收盘", 0


def get_quotes() -> dict:
    """只读 DataHub canonical live snapshot；缺失或过期时 fail-closed。"""
    try:
        return read_live_snapshot(ALL_CODES)
    except (FileNotFoundError, ValueError, OSError) as error:
        print(f"  [DataHub 实时快照不可用: {error}]")
        return {}


def get_north_flow() -> list[str]:
    """Read the latest persisted northbound flow without provider fallback."""
    try:
        row = read_latest_north_flow()
    except (FileNotFoundError, ValueError, OSError) as error:
        return [f"  DataHub 北向资金不可用: {error}"]
    return [f"  {row['trade_date']} 北向净额: {float(row['north_money']) / 100:.2f}亿"]


def get_kospi() -> list[str]:
    """KOSPI is unavailable until a canonical DataHub series is ingested."""
    return ["  DataHub KOSPI 数据缺失（不启用业务层联网 fallback）"]


def fmt_change(pct) -> str:
    if pct is None:
        return "--"
    pct = float(pct)
    return f"+{pct:.2f}%" if pct > 0 else (f"{pct:.2f}%" if pct < 0 else f" {pct:.2f}%")


def fmt_vol(v):
    if not v:
        return "--"
    v = float(v)
    return f"{v/1e8:.2f}亿" if v >= 1e8 else (f"{v/1e4:.2f}万" if v >= 1e4 else str(v))


def fmt_amt(v):
    if not v:
        return "--"
    v = float(v)
    return f"{v/1e8:.2f}亿" if v >= 1e8 else (f"{v/1e4:.2f}万" if v >= 1e4 else str(v))


# ======================================================================
# 监测看板
# ======================================================================

def build_snapshot() -> str:
    lines = []
    now = datetime.now(CST)
    mkt, _ = market_status()

    # 确保权重股已加载（惰性加载）
    if not HOLDINGS:
        _load_holdings()

    lines.append("=" * 62)
    lines.append(f"  📊 {ETF_CODE} 开盘监测看板")
    lines.append(f"  {now.strftime('%Y-%m-%d %H:%M:%S')}  |  状态: {mkt}")
    lines.append("=" * 62)

    # ── 1. ETF 实时行情 ──
    lines.append(f"\n📈 ETF 实时行情")
    lines.append("-" * 42)
    quotes = get_quotes()
    etf = quotes.get(ETF_CODE, {})
    if etf.get("price") is not None:
        p = etf["price"]
        cp = etf.get("change_pct")
        dir_sym = "📈" if cp and cp > 0 else "📉"
        lines.append(f"  {ETF_CODE}  {ETF_NAME}")
        lines.append(f"  现价: {p:.4f}  {dir_sym}{fmt_change(cp)}")
        lines.append(f"  今开: {etf['open']:.4f}  高: {etf['high']:.4f}  低: {etf['low']:.4f}"
                     if etf.get("open") else "")
        lines.append(f"  成交: {fmt_vol(etf.get('volume',0))}  金额: {fmt_amt(etf.get('amount',0))}")
    else:
        lines.append(f"  {ETF_CODE}  {ETF_NAME}")
        lines.append(f"  行情数据: 盘前/休市  (交易时段自动更新)")

    # ── 2. 权重股行情 ──
    lines.append(f"\n🏭 前十大权重股行情")
    lines.append("-" * 42)
    if not HOLDINGS:
        lines.append(f"  持仓数据加载中...")
    else:
        lines.append(f"  {'代码':<8} {'名称':<10} {'现价':<10} {'涨跌幅':<10} {'权重':<8}")
        lines.append(f"  {'-'*46}")
        for code, (name, weight) in HOLDINGS.items():
            q = quotes.get(code, {})
            ps = f"{q['price']:.2f}" if q.get("price") is not None else "--"
            cs = fmt_change(q.get("change_pct")) if q.get("change_pct") is not None else "--"
            ws = f"{weight:.1f}%" if weight > 0 else "--"
            lines.append(f"  {code:<8} {name:<10} {ps:<10} {cs:<10} {ws:<8}")

        valid = [q for c, q in quotes.items() if c in HOLDINGS and q.get("change_pct") is not None]
        if valid:
            pcts = [float(q["change_pct"]) for q in valid]
            up = sum(1 for p in pcts if p > 0)
            dn = sum(1 for p in pcts if p < 0)
            lines.append(f"  {'-'*46}")
            lines.append(f"  权重股均值: {fmt_change(sum(pcts)/len(pcts))}  "
                         f"涨{up} 跌{dn} 平{len(pcts)-up-dn}")
            lines.append(f"  最强: {fmt_change(max(pcts))}  最弱: {fmt_change(min(pcts))}")

    # ── 3. 北向资金 ──
    lines.append(f"\n💰 北向资金")
    lines.append("-" * 42)
    lines.extend(get_north_flow())

    # ── 4. 韩国KOSPI ──
    lines.append(f"\n🌏 韩国KOSPI")
    lines.append("-" * 42)
    lines.extend(get_kospi())

    # ── 5. 美股昨夜参考 ──
    lines.append(f"\n🇺🇸 美股昨夜 (7/7)")
    lines.append("-" * 42)
    lines.append(f"  费城半导体(SOX): -4.65%")
    lines.append(f"  英特尔: -10.7% | 闪迪: -13.9% | 美光: -8.8%")

    # ── 6. 操作参考 ──
    lines.append(f"\n💡 今日参考")
    lines.append("-" * 42)
    cp = etf.get("change_pct")
    if etf.get("price") is not None and cp is not None:
        if cp < -3:
            lines.append(f"  ⚠️ 当前跌 {cp:.1f}%，明显承压")
            lines.append(f"     量能萎缩+权重全线下挫则保护利润")
            lines.append(f"     反弹至-1%以内减仓，尾盘看情况接回")
        elif cp < -1.5:
            lines.append(f"  🔍 当前跌 {cp:.1f}%，中等跌幅")
            lines.append(f"     观察北向和KOSPI方向，企稳则持有")
            lines.append(f"     持续走弱至-3%+再考虑减仓")
        else:
            lines.append(f"  ✅ 当前 {fmt_change(cp)}，强于外围")
            lines.append(f"     国产替代独立逻辑支撑，继续持有")
    else:
        lines.append(f"  ⏳ 盘前预判: 等待开盘后更新判断")

    lines.append("\n" + "=" * 62)
    return "\n".join(lines)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--watch":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        print(f"🔄 循环监测模式，每 {interval}s 刷新 (Ctrl+C 退出)\n")
        try:
            while True:
                print("\033[2J\033[H", end="")
                print(build_snapshot())
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n监测已停止")
    else:
        print(build_snapshot())


if __name__ == "__main__":
    main()
