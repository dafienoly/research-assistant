"""Stock Analyst context assembled exclusively from canonical DataHub datasets."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from factor_lab.datahub_access import STOCK_BASIC_PATH, daily_kline_path


ROOT = Path(__file__).resolve().parents[1]
FUNDAMENTALS_ROOT = ROOT / "data/normalized/fundamentals"
FUND_FLOW_ROOT = ROOT / "data/normalized/fund_flow"
REGULATORY_PATH = ROOT / "data/normalized/events/regulatory_watchlist.json"


def _exchange_code(symbol: str) -> str:
    code = "".join(character for character in str(symbol) if character.isdigit())[:6]
    if len(code) != 6:
        raise ValueError(f"invalid A-share symbol: {symbol}")
    exchange = "SH" if code.startswith(("6", "9")) else "BJ" if code.startswith(("8", "4")) else "SZ"
    return f"{code}.{exchange}"


def _read_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def _technical_context(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {}
    date_column = next((column for column in ("trade_date", "date", "timeString") if column in frame), None)
    if date_column is None or "close" not in frame:
        return {}
    normalized = frame.copy()
    raw_dates = normalized[date_column].astype("string").str.replace(r"\.0$", "", regex=True).str.replace("-", "", regex=False)
    normalized["date"] = pd.to_datetime(raw_dates, format="%Y%m%d", errors="coerce")
    normalized["close"] = pd.to_numeric(normalized["close"], errors="coerce")
    volume_column = "volume" if "volume" in normalized else "vol" if "vol" in normalized else None
    normalized["volume_value"] = pd.to_numeric(normalized[volume_column], errors="coerce") if volume_column else 0.0
    normalized = normalized.dropna(subset=["date", "close"]).sort_values("date", kind="stable")
    if normalized.empty:
        return {}
    closes = normalized["close"]
    volumes = normalized["volume_value"]
    result = {
        "rows": len(normalized),
        "range": f"{normalized['date'].iloc[0]:%Y-%m-%d} ~ {normalized['date'].iloc[-1]:%Y-%m-%d}",
        "latest_close": float(closes.iloc[-1]),
        "latest_date": normalized["date"].iloc[-1].strftime("%Y-%m-%d"),
    }
    for window in (5, 10, 20, 60):
        result[f"ma{window}"] = float(closes.tail(window).mean()) if len(closes) >= window else None
    for window in (5, 20, 60):
        result[f"ret{window}"] = (
            float((closes.iloc[-1] / closes.iloc[-window - 1] - 1) * 100)
            if len(closes) > window and closes.iloc[-window - 1] != 0 else None
        )
    result["high60"] = float(closes.tail(60).max())
    result["low60"] = float(closes.tail(60).min())
    result["vol60_avg"] = float(volumes.tail(60).mean()) if len(volumes) >= 60 else 0.0
    result["vol5_avg"] = float(volumes.tail(5).mean()) if len(volumes) >= 5 else 0.0
    return result


def build_context(
    symbol: str,
    *,
    kline_file: Path | None = None,
    reference_path: Path | None = None,
    fundamentals_root: Path | None = None,
    fund_flow_root: Path | None = None,
    regulatory_path: Path | None = None,
) -> dict:
    ts_code = _exchange_code(symbol)
    code = ts_code.split(".")[0]
    ctx = {"symbol": code, "name": "", "data_freshness": {}, "errors": []}

    reference = _read_frame(reference_path or STOCK_BASIC_PATH)
    if not reference.empty and "symbol" in reference:
        match = reference[reference["symbol"].astype("string").str.zfill(6) == code]
        if not match.empty:
            row = match.iloc[-1]
            ctx["name"] = str(row.get("name") or "")
            industry = row.get("industry")
            if pd.notna(industry) and str(industry).strip():
                ctx["tags"] = [{"行业": str(industry).strip()}]
            ctx["data_freshness"]["reference_source"] = "datahub:stock_basic"
    if not ctx["name"]:
        ctx["errors"].append("canonical stock reference missing")

    try:
        source = kline_file or daily_kline_path(ts_code)
        ctx["kline"] = _technical_context(_read_frame(source))
        if not ctx["kline"]:
            raise ValueError("unusable kline")
        ctx["data_freshness"]["kline_source"] = "datahub:daily_kline"
    except (FileNotFoundError, ValueError):
        ctx["errors"].append("canonical daily kline missing or invalid")

    fundamentals = _read_frame((fundamentals_root or FUNDAMENTALS_ROOT) / f"{ts_code}.csv")
    if not fundamentals.empty:
        sort_column = "end_date" if "end_date" in fundamentals else "ann_date" if "ann_date" in fundamentals else None
        if sort_column:
            fundamentals = fundamentals.sort_values(sort_column, kind="stable")
        row = fundamentals.iloc[-1]
        selected = {
            key: row.get(key)
            for key in ("end_date", "eps", "roe", "grossprofit_margin", "netprofit_margin", "debt_to_assets", "revenue_ps")
            if key in fundamentals and pd.notna(row.get(key))
        }
        ctx["fundamentals"] = {"最新财务指标": selected}
        ctx["data_freshness"]["fundamentals_source"] = "datahub:fina_indicator"
    else:
        ctx["errors"].append("canonical fundamentals missing")

    flow = _read_frame((fund_flow_root or FUND_FLOW_ROOT) / f"{ts_code}.csv")
    if not flow.empty:
        if "trade_date" in flow:
            flow = flow.sort_values("trade_date", kind="stable")
        latest = flow.iloc[-1]
        ctx["fund_flow"] = {
            key: latest.get(key)
            for key in ("trade_date", "net_mf_amount", "net_mf_vol")
            if key in flow and pd.notna(latest.get(key))
        }
        ctx["data_freshness"]["fund_flow_source"] = "datahub:moneyflow"

    news_path = regulatory_path or REGULATORY_PATH
    try:
        snapshot = json.loads(news_path.read_text(encoding="utf-8"))
        if code not in set(snapshot.get("covered_symbols", [])):
            ctx["errors"].append("canonical announcement coverage missing")
        else:
            ctx["news"] = [
                {
                    "source": item.get("source", "announcement"),
                    "title": item.get("title", ""),
                    "snippet": "",
                    "source_ref": item.get("source_ref"),
                }
                for item in snapshot.get("announcements", [])
                if item.get("symbol") == code
            ][:5]
            ctx["data_freshness"]["news_source"] = "datahub:regulatory_watchlist"
    except (OSError, json.JSONDecodeError):
        ctx["errors"].append("canonical announcement snapshot missing or invalid")
    ctx.setdefault("news", [])
    return ctx


def format_markdown(ctx: dict) -> str:
    symbol = ctx["symbol"]
    suffix = ".SH" if symbol.startswith(("6", "9")) else ".BJ" if symbol.startswith(("8", "4")) else ".SZ"
    lines = [f"## {symbol}{suffix} {ctx.get('name', '')}", ""]
    sources = ["K 线: DataHub canonical"]
    if ctx.get("fundamentals"):
        sources.append("基本面: DataHub canonical")
    if ctx.get("news"):
        sources.append("消息: DataHub regulatory snapshot")
    if ctx.get("errors"):
        sources.append(f"⚠️ 缺失: {'; '.join(ctx['errors'])}")
    lines.extend([f"_数据口径：{' | '.join(sources)}_", ""])

    kline = ctx.get("kline", {})
    if kline:
        lines.extend(["### 最新交易状态", f"最新交易日 **{kline['latest_date']}** 收 **{kline['latest_close']:.2f}** 元"])
        if kline.get("vol5_avg") and kline.get("vol60_avg"):
            ratio = kline["vol5_avg"] / kline["vol60_avg"]
            lines.append(f"近 5 日均量 {kline['vol5_avg']/10000:.0f} 万，60 日均量 {kline['vol60_avg']/10000:.0f} 万（量比 {ratio:.2f}）")
        lines.extend(["", "均线状态："])
        for name, value in (("MA5", kline.get("ma5")), ("MA10", kline.get("ma10")), ("MA20", kline.get("ma20")), ("MA60", kline.get("ma60"))):
            if value is not None:
                status = "已跌破 ❌" if kline["latest_close"] < value else "仍在上方 ✅"
                lines.append(f"- {name}: {value:.2f} → {status}")
        lines.extend(["", f"60 日最高 {kline['high60']:.2f}，最低 {kline['low60']:.2f}", ""])

    if ctx.get("fundamentals"):
        lines.append("### 基本面")
        for label, data in ctx["fundamentals"].items():
            lines.append(f"- **{label}**：" + ", ".join(f"{key}={value}" for key, value in data.items()))
        lines.append("")
    if ctx.get("fund_flow"):
        lines.extend(["### 资金流", "- " + ", ".join(f"{key}={value}" for key, value in ctx["fund_flow"].items()), ""])
    if ctx.get("news"):
        lines.append("### 消息面")
        for item in ctx["news"]:
            lines.append(f"- **[{item.get('source', '')}]** {item.get('title', '')}")
        lines.append("")
    return "\n".join(lines)
