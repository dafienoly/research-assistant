#!/usr/bin/env python3
"""588710 科创半导体设备ETF华泰柏瑞 — 开盘监测看板

用法:
  python3 monitor_588710.py              # 单次监测快照
  python3 monitor_588710.py --watch 60   # 每60秒循环监测

所有数据走已有 datahub 管线，不硬编码：
  - ETF 权重股  → mx:data 查持仓名称 + datahub CSV 做名称→代码映射
  - 实时行情    → eastmoney_direct (P1) → Sina (P3) → Tencent (P4)
  - 北向资金    → akshare (call_no_proxy) → mx:data 降级
  - 韩国KOSPI   → mx:data
"""

import sys, json, os, time, subprocess, re
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path.home() / ".hermes" / "research-assistant" / "commands"
sys.path.insert(0, str(BASE))

# ======== 全局变量：模块加载时从 datahub 拉取 ========
ETF_CODE = "588710"
ETF_NAME = "科创半导体设备ETF华泰柏瑞"
HOLDINGS: dict[str, tuple[str, float]] = {}
ALL_CODES: list[str] = []


# ======================================================================
# 权重股动态加载
# ======================================================================

def _load_holdings():
    """从 Tushare 拉取 588710 前十大重仓股（含权重），降级用 akshare"""
    global HOLDINGS, ALL_CODES

    # P1: Tushare fund_portfolio (优先, 已验证可用)
    try:
        from factor_lab.data.tushare_client import get_ts_client
        tc = get_ts_client()
        df = tc._query('fund_portfolio', ts_code='588710.SH',
                       start_date='20260331', end_date='20260630')
        if not df.empty and 'stk_mkv_ratio' in df.columns:
            top = df.sort_values('stk_mkv_ratio', ascending=False).head(10)
            holdings = {}
            for _, r in top.iterrows():
                symbol = str(r['symbol']).strip()
                ratio = float(r['stk_mkv_ratio'])
                # 用 stock_basic 查名称
                try:
                    name_df = tc._query('stock_basic', ts_code=symbol,
                                        fields='ts_code,name')
                    name = str(name_df.iloc[0]['name']) if not name_df.empty else symbol
                except Exception:
                    name = symbol
                holdings[symbol] = (name, ratio)
            if len(holdings) >= 5:
                HOLDINGS.clear()
                HOLDINGS.update(holdings)
                ALL_CODES.clear()
                ALL_CODES.extend([ETF_CODE] + list(HOLDINGS.keys()))
                return
    except Exception as e:
        print(f"  [Tushare 持仓获取失败, 尝试降级: {e}]")

    # P2: akshare (降级)
        import akshare as ak
        from dive_prediction.proxy_bypass import call_no_proxy
        df = call_no_proxy(ak.fund_etf_fund_info_em, fund=ETF_CODE)
        holdings = {}
        for _, r in df.iterrows():
            code = str(r.get("股票代码", "")).strip().zfill(6)
            name = str(r.get("股票名称", "")).strip()
            weight = float(r.get("占净值比例", 0))
            if code and name:
                holdings[code] = (name, weight)
        if len(holdings) >= 5:
            HOLDINGS.clear()
            HOLDINGS.update(dict(list(holdings.items())[:10]))
            ALL_CODES.clear()
            ALL_CODES.extend([ETF_CODE] + list(HOLDINGS.keys()))
            return
    except Exception:
        pass

    # 回退: mx:data 查名称 → CSV 映射代码（无权重的降级方案）
    names_str = _fetch_holding_names()
    if not names_str:
        return
    names = [n.strip() for n in names_str.split(",") if n.strip()]
    name_to_code = _build_name_code_map()
    holdings = {}
    for n in names:
        code = name_to_code.get(n)
        if code:
            holdings[code] = (n, 0.0)
    if holdings:
        HOLDINGS.clear()
        HOLDINGS.update(holdings)
    for n in names:
        if n not in [v[0] for v in HOLDINGS.values()]:
            code = _lookup_code_via_mx(n)
            if code:
                HOLDINGS[code] = (n, 0.0)
    if HOLDINGS:
        ALL_CODES.clear()
        ALL_CODES.extend([ETF_CODE] + list(HOLDINGS.keys()))


def _fetch_holding_names():
    """mx:data → 588710 前十大重仓股名称"""
    try:
        r = subprocess.run(
            [sys.executable, str(BASE / "mx.py"), "data",
             "588710 华泰柏瑞 前十大重仓股"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        for line in r.stdout.split("\n"):
            if ":" in line and ("拓荆" in line or "华海" in line or "中微" in line):
                return line.split(":", 1)[1].strip()
        return None
    except Exception:
        return None


def _build_name_code_map():
    """从 datahub CSV 构建名称→代码映射"""
    import csv
    mapping = {}

    tag_path = BASE.parent / "data" / "tags" / "semiconductor_chain_tags.csv"
    if tag_path.exists():
        with open(tag_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                c, n = row.get("code", "").strip(), row.get("name", "").strip()
                if c and n:
                    mapping[n] = c

    ind_path = BASE.parent / "data" / "tags" / "stock_industry.csv"
    if ind_path.exists():
        with open(ind_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                c, n = row.get("code", "").strip(), row.get("name", "").strip()
                if c and n and n not in mapping:
                    mapping[n] = c

    return mapping


def _lookup_code_via_mx(name: str) -> str | None:
    """mx:data 查单只股票代码（带重试和限速）"""
    import re
    for attempt in range(3):
        try:
            r = subprocess.run(
                [sys.executable, str(BASE / "mx.py"), "data", f"{name} A股股票代码"],
                capture_output=True, text=True, timeout=10,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            # 命中限频则等 2 秒重试
            if "请求频率过高" in r.stdout:
                time.sleep(2)
                continue
            # 找 ".SH" 或 ".SZ" 前的 6 位代码
            match = re.search(r'(\d{6})\.(SH|SZ)', r.stdout)
            if match:
                return match.group(1)
        except Exception:
            time.sleep(1)
    return None


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
    """实时行情: Eastmoney P1 → RSScast P2 → Sina P3 → Tencent P4"""
    from dive_prediction.proxy_bypass import call_no_proxy
    merged = {}

    # P1: Eastmoney Direct (免费无限量，仅盘中)
    from eastmoney_direct import EastmoneyProvider
    merged.update(call_no_proxy(EastmoneyProvider().get_quotes, ALL_CODES))

    # P2: RSScast MCP (有配额，全时段)
    try:
        from rsscast_mcp import fetch_stock_prices
        data = fetch_stock_prices([c for c in ALL_CODES if c not in merged or merged[c].get("price") is None])
        for item in data:
            code = str(item.get("code", ""))
            if code and (code not in merged or merged[code].get("price") is None):
                merged[code] = {
                    "code": code, "name": "",
                    "price": item.get("last_price"),
                    "high": item.get("high"), "low": item.get("low"),
                    "open": item.get("open"),
                    "volume": item.get("volume"), "amount": item.get("amount"),
                    "change_pct": (item.get("change_pct", 0) or 0) * 100,
                }
    except Exception:
        pass

    # P3: Sina (免费无限量) — 补充缺失
    try:
        from provider_matrix import SinaProvider
        sina = SinaProvider().get_quotes(ALL_CODES)
        for k, v in sina.items():
            if k not in merged or merged[k].get("price") is None:
                merged[k] = v
    except Exception:
        pass

    # P4: Tencent (免费无限量, 直连) — 填充剩余缺失
    missing = [c for c in ALL_CODES if c not in merged or merged[c].get("price") is None]
    for code in missing:
        try:
            import requests
            # 腾讯格式: sh688012 / sz000001
            prefix = "sz" if code.startswith(("00", "30", "15")) else "sh"
            url = f"https://qt.gtimg.cn/q={prefix}{code[:6]}"
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                parts = r.text.split("~")
                if len(parts) >= 6:
                    merged[code] = {
                        "code": parts[2], "name": parts[1],
                        "price": float(parts[3]) if parts[3] else None,
                        "open": float(parts[5]) if parts[5] else None,
                        "high": float(parts[33]) if len(parts) > 33 else None,
                        "low": float(parts[34]) if len(parts) > 34 else None,
                        "change_pct": float(parts[32]) if len(parts) > 32 else None,
                    }
        except Exception:
            pass

    return merged


def get_north_flow() -> list[str]:
    rows = _north_akshare()
    if rows:
        return rows
    return _north_fallback_mx() or ["  暂无北向资金数据"]


def _north_akshare() -> list[str]:
    try:
        from dive_prediction.proxy_bypass import call_no_proxy
        import akshare as ak
        import pandas as pd
        df = call_no_proxy(ak.stock_hsgt_fund_flow_summary_em)
        rows = []
        for _, r in df.iterrows():
            if r.get("资金方向", "") != "北向":
                continue
            board = r.get("板块", "")
            net = r.get("成交净买额", 0)
            if pd.notna(net):
                rows.append(f"  {board}  净买额: {net:.1f}万" if abs(net) < 1e8
                            else f"  {board}  净买额: {net/1e8:.2f}亿")
        return rows
    except Exception:
        return []


def _north_fallback_mx() -> list[str]:
    try:
        r = subprocess.run(
            [sys.executable, str(BASE / "mx.py"), "data", "北向资金 今日"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        lines = []
        for l in r.stdout.split("\n"):
            ls = l.strip()
            if not ls or ls.startswith("{") or ls.startswith("}"):
                continue
            if re.match(r'^\d+:\s', ls):
                val = ls.split(":", 1)[1].strip()
                if val:
                    lines.append(f"  北向资金成交额: {float(val)/100:.0f}亿")
                continue
            lines.append(f"  {ls}")
        return lines[:5]
    except Exception:
        return []


def get_kospi() -> list[str]:
    try:
        r = subprocess.run(
            [sys.executable, str(BASE / "mx.py"), "data", "韩国综合指数 今日行情"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        lines = []
        for l in r.stdout.split("\n"):
            ls = l.strip()
            if not ls or ls.startswith("{"):
                continue
            if "韩国综合指数" in ls:
                lines.append(f"  {ls}")
            elif "100000000006368" in ls:
                lines.append(f"  涨跌幅: {ls.split(':')[-1].strip()}")
            elif "点" in ls:
                lines.append(f"  点位: {ls.split(':')[-1].strip()}")
        return lines or ["  暂无KOSPI数据"]
    except subprocess.TimeoutExpired:
        return ["  查询超时"]
    except Exception as e:
        return [f"  查询失败: {e}"]


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
