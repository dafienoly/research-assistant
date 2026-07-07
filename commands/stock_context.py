"""Stock Analyst — 数据上下文助手（自动补全缺失数据）"""
import csv, json, os, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
sys.path.insert(0, os.path.dirname(__file__))

KLINE = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")
FUND = Path("/home/ly/.hermes/research-assistant/data/fundamentals")
TAGS = Path("/home/ly/.hermes/research-assistant/data/tags")


def _bs_fetch_all(symbol: str, fetch_kline: bool = True) -> dict:
    """一次登录 Baostock，拉取所有缺失数据

    fetch_kline: 是否刷新 K 线缓存
    """
    import dns_patch
    import baostock as bs
    exchange = "sh" if symbol.startswith(("6", "9")) else "sz"
    full = f"{exchange}.{symbol}"
    result = {"name": "", "fundamentals": {}, "tags": {}, "kline_updated": False, "kline_latest_date": ""}

    bs.login()
    try:
        # 股票名称
        try:
            rs = bs.query_stock_basic(full)
            while rs.next():
                r = rs.get_row_data()
                if r and len(r) > 1:
                    result["name"] = r[1]
                break
        except Exception:
            pass  # name lookup error (non-critical)

        # K 线刷新（仅当 fetch_kline=True 时执行）
        # K 线刷新（仅当 fetch_kline=True 时执行）
        if fetch_kline:
            try:
                import signal
                class TimeoutError(Exception): pass
                def _handler(s, f): raise TimeoutError()
                old = signal.signal(signal.SIGALRM, _handler)
                signal.alarm(5)
                try:
                    rs = bs.query_history_k_data_plus(
                        full, "date,open,high,low,close,volume,amount",
                        "2026-05-01", "2026-07-03", "d", "2"
                    )
                    new_rows = []
                    while rs.next():
                        r = rs.get_row_data()
                        if r and len(r) >= 5 and r[4]:
                            new_rows.append({
                                "date": r[0], "open": r[1], "high": r[2],
                                "low": r[3], "close": r[4],
                                "volume": r[5] if len(r) > 5 else "",
                                "amount": r[6] if len(r) > 6 else "",
                            })
                    if new_rows:
                        kf = KLINE / f"{symbol}.csv"
                        if kf.exists():
                            with open(kf, encoding="utf-8-sig") as fh:
                                existing = list(csv.DictReader(fh))
                            existing_dates = {r["date"] for r in existing}
                            to_add = [r for r in new_rows if r["date"] not in existing_dates]
                        else:
                            existing = []
                            to_add = new_rows
                        if to_add:
                            all_rows = existing + [{"code": symbol, **r} for r in to_add]
                            all_rows.sort(key=lambda x: x["date"])
                            with open(kf, "w", newline="") as fh:
                                w = csv.DictWriter(fh, fieldnames=["code","date","open","high","low","close","volume","amount"])
                                w.writeheader()
                                w.writerows(all_rows)
                            result["kline_updated"] = True
                            result["kline_latest_date"] = max(r["date"] for r in new_rows)
                        else:
                            result["kline_latest_date"] = existing[-1]["date"] if existing else ""
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old)
            except TimeoutError:
                pass
            except:
                pass

        # 盈利能力 2026Q1
        try:
            rs = bs.query_profit_data(full, 2026, 1)
            while rs.next():
                r = rs.get_row_data()
                if r and len(r) > 7 and r[3]:
                    result["fundamentals"]["盈利能力"] = {
                        "report_date": r[2], "pub_date": r[1],
                        "roe": r[3], "net_margin": r[4], "gross_margin": r[5],
                        "net_profit": r[6], "eps": r[7], "revenue": r[8] if len(r) > 8 else "",
                    }
                break
        except Exception:
            pass  # name lookup error (non-critical)

        # 资产负债表 2025Q4
        try:
            rs = bs.query_balance_data(full, 2025, 4)
            while rs.next():
                r = rs.get_row_data()
                if r and len(r) > 5 and r[3]:
                    result["fundamentals"]["资产负债表"] = {
                        "report_date": r[2], "pub_date": r[1],
                        "total_assets": r[3],
                        "total_liab": r[4],
                        "debt_ratio": r[5] if len(r) > 5 else "",
                    }
                break
        except Exception:
            pass  # name lookup error (non-critical)

        # 行业分类
        try:
            rs = bs.query_stock_industry(full)
            while rs.next():
                r = rs.get_row_data()
                if r and len(r) >= 4:
                    result["tags"]["行业"] = r[3]
                break
        except Exception:
            pass  # name lookup error (non-critical)

    finally:
        bs.logout()

    return result


def build_context(symbol: str) -> dict:
    ctx = {"symbol": symbol, "name": "", "data_freshness": {}, "errors": []}

    # ─── K 线（只读缓存，不做实时补全） ───
    kf = KLINE / f"{symbol}.csv"
    kline_data = None
    if kf.exists():
        with open(kf, encoding="utf-8-sig") as f:
            kline_data = list(csv.DictReader(f))

    if kline_data:
        closes = [float(r.get("close", 0) or 0) for r in kline_data]
        dates = [r["date"] for r in kline_data]
        ctx["kline"] = {
            "rows": len(kline_data),
            "range": f"{dates[0]} ~ {dates[-1]}",
            "latest_close": closes[-1],
            "latest_date": dates[-1],
            "ret5": (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) > 6 else None,
            "ret20": (closes[-1] - closes[-21]) / closes[-21] * 100 if len(closes) > 21 else None,
            "ret60": (closes[-1] - closes[-61]) / closes[-61] * 100 if len(closes) > 61 else None,
            "ma5": sum(closes[-5:]) / 5 if len(closes) >= 5 else None,
            "ma10": sum(closes[-10:]) / 10 if len(closes) >= 10 else None,
            "ma20": sum(closes[-20:]) / 20 if len(closes) >= 20 else None,
            "ma60": sum(closes[-60:]) / 60 if len(closes) >= 60 else None,
            "high60": max(closes[-60:]),
            "low60": min(closes[-60:]),
            "vol60_avg": sum(float(r.get("volume", 0) or 0) for r in kline_data[-60:]) / 60 if len(kline_data) >= 60 else 0,
            "vol5_avg": sum(float(r.get("volume", 0) or 0) for r in kline_data[-5:]) / 5 if len(kline_data) >= 5 else 0,
        }
    else:
        ctx["errors"].append("无 K 线数据（Baostock 也未返回）")

    # ─── 新闻/消息面（Tavily 搜索 + 本地公告） ───
    news = []

    # Tavily 搜索（最多 3 条，省配额）
    try:
        from search_enhancer import TavilySearch
        import quota
        if quota.quota_check("tavily"):
            tv = TavilySearch()
            q = f"{ctx.get('name','')} {symbol}"
            news_results = tv.search(q, max_results=5)
            for n in news_results or []:
                title = n.get("title", "")
                snippet = n.get("content", "")[:200]
                # 只保留标题或摘要中包含股票代码或名称的结果
                if symbol in title or ctx.get('name','') in title:
                    news.append({
                        "source": "tavily",
                        "title": title,
                        "url": n.get("url", ""),
                        "snippet": snippet,
                    })
            if news_results:
                quota.quota_consume("tavily")
    except Exception:
        pass

    # 本地公告
    events_dir = Path("/home/ly/.hermes/research-assistant/data/events")
    if events_dir.exists():
        for f in ["announcement_events.csv", "preopen_events.csv"]:
            fp = events_dir / f
            if fp.exists():
                with open(fp, encoding="utf-8-sig") as fh:
                    for r in csv.DictReader(fh):
                        syms = r.get("symbols", "") or r.get("symbol", "") or ""
                        if symbol in syms and r.get("title", ""):
                            news.append({
                                "source": "公告",
                                "title": r.get("title", ""),
                                "snippet": r.get("summary", "")[:200],
                            })
                            if len(news) >= 5:
                                break
            if len(news) >= 5:
                break

    if news:
        ctx["news"] = news
    else:
        ctx["news"] = [{"source": "system", "title": "无近期相关新闻", "snippet": "Tavily 搜索和本地公告均未找到该股近期消息"}]

    # ─── Baostock 刷新（可选，仅当基础数据缺失时） ───
    # K 线由每日 cron 更新，stock:context 不负责 K 线实时补全
    bf = {}
    if not ctx.get("fundamentals") or not ctx.get("tags") or not ctx.get("name"):
        try:
            import socket
            s = socket.socket()
            s.settimeout(2)
            s.connect(("114.94.20.73", 10030))
            s.close()
            bf = _bs_fetch_all(symbol, fetch_kline=False)
        except Exception:
            pass  # name lookup error (non-critical)

    # K 线已由 _bs_fetch_all 合并到缓存，重新读取
    kf = KLINE / f"{symbol}.csv"
    if kf.exists():
        with open(kf, encoding="utf-8-sig") as f:
            kline_data = list(csv.DictReader(f))
        if kline_data:
            closes = [float(r.get("close", 0) or 0) for r in kline_data]
            dates = [r["date"] for r in kline_data]
            ctx["kline"] = {
                "rows": len(kline_data),
                "range": f"{dates[0]} ~ {dates[-1]}",
                "latest_close": closes[-1],
                "latest_date": dates[-1],
                "ret5": (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) > 6 else None,
                "ret20": (closes[-1] - closes[-21]) / closes[-21] * 100 if len(closes) > 21 else None,
                "ret60": (closes[-1] - closes[-61]) / closes[-61] * 100 if len(closes) > 61 else None,
                "ma5": sum(closes[-5:]) / 5 if len(closes) >= 5 else None,
                "ma10": sum(closes[-10:]) / 10 if len(closes) >= 10 else None,
                "ma20": sum(closes[-20:]) / 20 if len(closes) >= 20 else None,
                "ma60": sum(closes[-60:]) / 60 if len(closes) >= 60 else None,
                "high60": max(closes[-60:]),
                "low60": min(closes[-60:]),
                "vol60_avg": sum(float(r.get("volume", 0) or 0) for r in kline_data[-60:]) / 60 if len(kline_data) >= 60 else 0,
                "vol5_avg": sum(float(r.get("volume", 0) or 0) for r in kline_data[-5:]) / 5 if len(kline_data) >= 5 else 0,
            }
            if bf.get("kline_updated"):
                ctx["data_freshness"]["kline_updated"] = "baostock"
                ctx["data_freshness"]["kline_latest_date"] = bf.get("kline_latest_date", "")

    # 基本面/名称/标签（缓存优先）
    if bf.get("name") and not ctx["name"]:
        ctx["name"] = bf["name"]
        ctx["data_freshness"]["name_source"] = "baostock"
    if bf.get("fundamentals") and not ctx.get("fundamentals"):
        ctx["fundamentals"] = bf["fundamentals"]
        ctx["data_freshness"]["fundamentals_source"] = "baostock"
    if bf.get("tags") and not ctx.get("tags"):
        ctx["tags"] = [bf["tags"]]
        ctx["data_freshness"]["tags_source"] = "baostock"

    # ─── 资金流向（盘中行情类数据，盘后提取历史） ───
    # 非必选：仅当需要资金流向分析时调用
    # 使用方式: stock:context 已含此功能，通过 fund_flow 字段输出
    
    return ctx


def format_markdown(ctx: dict) -> str:
    lines = [f"## {ctx['symbol']}{'.SZ' if not ctx['symbol'].startswith(('6','9')) else '.SH'} {ctx.get('name', '')}", ""]

    # 数据口径
    sources = []
    sources.append("K 线: data hub（daily_kline/）")
    if ctx.get("data_freshness", {}).get("fundamentals_source"):
        sources.append("基本面: Baostock（实时拉取）")
    else:
        sources.append("基本面: data hub 缓存")
    if ctx.get("news"):
        news_sources = set(n.get("source", "") for n in ctx["news"])
        if news_sources:
            sources.append(f"消息: {', '.join(news_sources)}")
    if ctx.get("errors"):
        sources.append(f"⚠️ 缺失: {'; '.join(ctx['errors'])}")
    lines.append(f"_数据口径：{' | '.join(sources)}_")
    lines.append("")

    # K 线
    k = ctx.get("kline", {})
    if k:
        lines.append("### 最新交易状态")
        lines.append(f"最新交易日 **{k['latest_date']}** 收 **{k['latest_close']:.2f}** 元")
        if k.get("vol5_avg") and k.get("vol60_avg"):
            vol_ratio = k["vol5_avg"] / k["vol60_avg"] if k["vol60_avg"] else 1
            lines.append(f"近 5 日均量 {k['vol5_avg']/10000:.0f} 万，60 日均量 {k['vol60_avg']/10000:.0f} 万（量比 {vol_ratio:.2f}）")
        lines.append("")
        lines.append("均线状态：")
        for name, val in [("MA5", k.get("ma5")), ("MA10", k.get("ma10")),
                          ("MA20", k.get("ma20")), ("MA60", k.get("ma60"))]:
            if val is not None:
                status = "已跌破 ❌" if k["latest_close"] < val else "仍在上方 ✅"
                lines.append(f"- {name}: {val:.2f} → {status}")
        lines.append("")
        if k.get("high60") and k.get("low60"):
            lines.append(f"60 日最高 {k['high60']:.2f}，最低 {k['low60']:.2f}")
            lines.append(f"距高点 {(k['high60']-k['latest_close'])/k['high60']*100:.1f}%")
            lines.append("")

    # 基本面
    if ctx.get("fundamentals"):
        lines.append("### 基本面")
        for label, data in ctx["fundamentals"].items():
            items = ", ".join(f"{k}={v}" for k, v in data.items() if v)
            lines.append(f"- **{label}**：{items}")
        lines.append("")

    # 消息面
    if ctx.get("news"):
        lines.append("### 消息面")
        for n in ctx["news"][:5]:
            lines.append(f"- **[{n.get('source','')}]** {n.get('title','')}")
            if n.get("snippet"):
                lines.append(f"  {n['snippet']}")
        lines.append("")

    return "\n".join(lines)
