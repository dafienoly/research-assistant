"""ETF 跳水实时预测 + 推送

基于 data_collector 回测验证的信号权重，产出实时跳水概率。
数据从 config.PATHS 标准路径读取。
"""
import json, sys

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
_BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(_BASE.parent))
from config import PATHS
from factor_lab.datahub_access import read_live_snapshot

DATA_DIR = PATHS["daily_kline"]

# Random Forest 模型集成（生产最佳）
_RF_PROB_CACHE = None


def _rf_prob() -> float:
    """用 Random Forest 模型预测当前跳水概率"""
    try:
        from dive_prediction.features import load_etf, load_leaders, compute_full_features
        from dive_prediction.multi_train import predict_rf

        df_etf = load_etf()
        leaders = load_leaders()
        feat = compute_full_features(df_etf, leaders).ffill().bfill()
        # 用最新一行
        last = feat.iloc[-1:]
        return predict_rf(last)
    except Exception:
        return 0.0

ETF_CODE = "159516"
ETF_NAME = "半导体设备ETF"

# 回测验证的信号权重 (high_low_ratio<0.3 → 100%, open_close_ratio<0.25 → 100%, etc.)
# 权重 = 跳水概率 / 100，平滑后使用
SIGNAL_WEIGHTS = {
    "high_low_ratio<0.3": 0.35,      # 最强单一信号
    "open_close_ratio<0.25": 0.30,   # 次强
    "prev_amplitude>8": 0.20,        # 前日高波动
    "consec_up>=3": 0.15,            # 连涨回调
}


def load_hist() -> pd.DataFrame:
    """读取本地历史数据计算昨日信号"""
    csv_path = DATA_DIR / f"{ETF_CODE}_hist.csv"
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    col_map = {
        "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount", "振幅": "amplitude",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
    for c in ["close", "high", "low", "volume", "amount"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def compute_prediction_signals(df: pd.DataFrame) -> dict:
    """基于昨日收盘数据计算今日跳水概率"""
    if df is None or df.empty:
        return {"prob": 0, "signals": [], "detail": "无历史数据"}

    last = df.iloc[-1]
    signals_triggered = []
    score = 0.0
    max_score = sum(SIGNAL_WEIGHTS.values())

    # 信号1: high_low_ratio<0.3 — 收盘在日内低位
    hl_ratio = (last["close"] - last["low"]) / (last["high"] - last["low"] + 0.001)
    if hl_ratio < 0.3:
        w = SIGNAL_WEIGHTS["high_low_ratio<0.3"]
        score += w
        signals_triggered.append(f"收盘在日内低位(hl_ratio={hl_ratio:.2f}) +{w:.0%}")

    # 信号2: open_close_ratio<0.25 — 实体短/阴线
    oc_ratio = (last["close"] - last["open"]) / (last["high"] - last["low"] + 0.001)
    if oc_ratio < 0.25:
        w = SIGNAL_WEIGHTS["open_close_ratio<0.25"]
        score += w
        signals_triggered.append(f"实体短/阴线(oc_ratio={oc_ratio:.2f}) +{w:.0%}")

    # 信号3: prev_amplitude>8 — 前日高振幅
    if len(df) >= 2:
        prev_amp = (df.iloc[-2]["high"] - df.iloc[-2]["low"]) / df.iloc[-2]["close"] * 100
        if prev_amp > 8:
            w = SIGNAL_WEIGHTS["prev_amplitude>8"]
            score += w
            signals_triggered.append(f"前日高振幅({prev_amp:.1f}%) +{w:.0%}")

    # 信号4: consec_up>=3 — 连涨
    if len(df) >= 3:
        consec = sum((df.iloc[-i-1]["close"] > df.iloc[-i-2]["close"]) for i in range(3))
        if consec >= 3:
            w = SIGNAL_WEIGHTS["consec_up>=3"]
            score += w
            signals_triggered.append(f"连涨{consec}天 +{w:.0%}")

    prob = score / max_score * 100 if max_score > 0 else 0

    return {
        "prob": round(prob, 1),
        "score": round(score, 2),
        "max_score": round(max_score, 2),
        "signals": signals_triggered,
        "detail": "; ".join(signals_triggered) if signals_triggered else "无触发信号",
    }


def fetch_realtime_price() -> dict | None:
    """Read the ETF quote from the fresh canonical DataHub snapshot."""
    try:
        row = read_live_snapshot([ETF_CODE]).get(ETF_CODE)
    except (FileNotFoundError, ValueError, OSError):
        return None
    if not row or row.get("price") is None:
        return None
    return {
        "price": row["price"],
        "change_pct": row.get("change_pct") or 0,
        "high": row.get("high") or row["price"],
        "low": row.get("low") or row["price"],
        "open": row.get("open") or row["price"],
        "amount": (row.get("amount") or 0) / 1e8,
        "source": row.get("source", "datahub"),
    }


def check_intraday_dive(realtime: dict) -> dict:
    """盘中实时跳水信号检查"""
    if not realtime:
        return {"signals": [], "intraday_risk": 0}

    signals = []
    risk = 0
    price = realtime["price"]
    change = realtime["change_pct"]
    high = realtime["high"]
    low = realtime["low"]
    open_p = realtime.get("open", price)
    amount = realtime.get("amount", 0)

    # 1. 从高点回撤
    if high > price:
        retrace = (high - price) / high * 100
        if retrace >= 2:
            signals.append(f"从高点回撤{retrace:.1f}%")
            risk += 2 if retrace >= 4 else 1

    # 2. 跌破开盘价
    if price < open_p and change > 0:
        signals.append(f"已跌破开盘价(open={open_p:.3f})")
        risk += 2

    # 3. 放量下跌
    if change < -2 and amount > 30:
        signals.append(f"放量下跌({change:.1f}%, 成交{amount:.0f}亿)")
        risk += 3

    # 4. 加速下跌 (5min跌速>3%) — 简化: 日内从高点跌幅
    if change < -3:
        signals.append(f"跌幅已超3%({change:.1f}%)")
        risk += 4

    return {"signals": signals, "intraday_risk": min(risk, 10), "detail": "; ".join(signals) if signals else "盘中无明显跳水信号"}


# ── 事件驱动检查 ────────────────────────────────────

def check_event_driven(realtime: dict | None = None) -> dict:
    """检查是否需要触发事件驱动预警（龙头异动/大盘急跌等）"""
    events = []
    risk_boost = 0

    # 1. 大盘急跌（同一 canonical DataHub 快照）
    try:
        snapshot = read_live_snapshot()
    except (FileNotFoundError, ValueError, OSError):
        snapshot = {}
    down_count = sum(1 for row in snapshot.values() if (row.get("change_pct") or 0) < -5)
    total = sum(1 for row in snapshot.values() if row.get("change_pct") is not None)
    if total > 100:
        pct_down = down_count / total * 100
        if pct_down > 15:
            events.append(f"全市场{down_count}只跌超5%({pct_down:.0f}%)")
            risk_boost += 2
        elif pct_down > 8:
            events.append(f"市场普跌({pct_down:.0f}%个股跌超5%)")
            risk_boost += 1

    # 2. ETF 自身盘中加速下跌
    if realtime:
        if realtime.get("change_pct", 0) < -2:
            events.append(f"ETF已跌{realtime['change_pct']:.1f}%")
            risk_boost += 2
        if realtime.get("low", 0) < realtime.get("open", 0) * 0.97:
            events.append("盘中跌破开盘3%")
            risk_boost += 3

    return {"events": events, "risk_boost": risk_boost, "detail": "; ".join(events) if events else ""}


def predict(code: str = ETF_CODE) -> dict:
    """综合预测: 昨日信号 + 今日盘中"""
    now = datetime.now(CST)
    market_open = now.hour >= 9 and (now.hour > 9 or now.minute >= 30)
    afternoon = now.hour >= 13

    # 1. 昨日信号
    hist = load_hist()
    pred = compute_prediction_signals(hist)

    # 2. 今日实时
    realtime = fetch_realtime_price() if market_open else None
    intraday = check_intraday_dive(realtime) if realtime else {"signals": [], "intraday_risk": 0, "detail": "盘中尚未开盘"}

    # 2b. 事件驱动检查
    event_driven = check_event_driven(realtime) if market_open else {"events": [], "risk_boost": 0, "detail": ""}

    # 3. 综合概率（规则 + RF + 事件）
    base_prob = pred["prob"]
    event_boost = event_driven.get("risk_boost", 0) * 3  # 事件驱动最多加15%
    intra_boost = intraday["intraday_risk"] * 5  # 盘中信号最多加50%
    rf_prob = _rf_prob()
    if rf_prob > 0:
        # RF 模型与规则引擎加权平均（RF 权重 40%，规则 60%）
        ml_weighted = rf_prob * 0.4
        rule_weighted = min(base_prob + intra_boost + event_boost, 98) * 0.6
        total_prob = min(ml_weighted + rule_weighted, 98)
        ml_label = f"  🌲  RF概率: {rf_prob:.0f}%"
    else:
        total_prob = min(base_prob + intra_boost + event_boost, 98)
        ml_label = ""

    # 4. 风险等级
    if total_prob >= 70:
        level = "极高"
    elif total_prob >= 55:
        level = "高"
    elif total_prob >= 40:
        level = "中"
    else:
        level = "低"

    summary = (
        f"\n{'═'*50}"
        f"\n  🏷️  {ETF_NAME}({ETF_CODE})  跳水预测"
        f"\n  📊  基础概率(昨日): {base_prob:.0f}%"
    )
    if realtime:
        summary += f"\n  📈  实时价: {realtime['price']:.3f}  涨幅: {realtime['change_pct']:+.1f}%"
        summary += f"\n  💰  成交: {realtime['amount']:.0f}亿"
    summary += f"\n  🚨  综合跳水概率: {total_prob:.0f}%  等级: {level}"
    if ml_label:
        summary += ml_label

    if pred["signals"]:
        summary += f"\n  ⚡  昨日信号: {pred['detail']}"
    if intraday["signals"]:
        summary += f"\n  ⚡  盘中信号: {intraday['detail']}"

    advice = {"极高": "强烈建议减仓/止损", "高": "建议减仓，设好止损",
              "中": "谨慎观望，不要追高", "低": "暂无明显跳水信号"}.get(level, "")
    if advice:
        summary += f"\n  💡  建议: {advice}"
    summary += f"\n{'═'*50}"

    return {
        "code": code, "name": ETF_NAME, "prob": total_prob, "level": level,
        "base_prob": base_prob, "intraday_boost": intra_boost,
        "pred_signals": pred, "intraday_signals": intraday,
        "realtime": realtime, "summary": summary,
        "time": now.strftime("%Y-%m-%d %H:%M"),
        "market_open": market_open, "afternoon": afternoon,
    }


def push_wechat(result: dict):
    """推送企业微信"""
    try:
        from factor_lab.notify import notify_goal_done
        risk_icon = {"极高": "🔴", "高": "🟠", "中": "🟡", "低": "🟢"}
        icon = risk_icon.get(result["level"], "⚪")
        title = f"{icon} {ETF_NAME} 跳水预警 — {result['level']}风险"
        msg = f"综合跳水概率: {result['prob']:.0f}%\n"
        if result["pred_signals"]["detail"]:
            msg += f"昨日信号: {result['pred_signals']['detail']}\n"
        if result["intraday_signals"]["detail"]:
            msg += f"盘中信号: {result['intraday_signals']['detail']}\n"
        msg += f"建议: {'减仓/止损' if result['level'] in ('高','极高') else '观望'}"
        notify_goal_done(title, msg, "completed" if result["prob"] < 60 else "failed")
        return True
    except Exception as e:
        print(f"  ⚠️ 推送失败: {e}")
        return False


def main():
    import argparse
    p = argparse.ArgumentParser(description="ETF跳水实时预测")
    p.add_argument("--code", default=ETF_CODE)
    p.add_argument("--json", action="store_true")
    p.add_argument("--push", action="store_true", help="推送企业微信")
    p.add_argument("--forever", action="store_true", help="持续监测(15min间隔)")
    args = p.parse_args()

    def run_once():
        result = predict(code=args.code)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            print(result["summary"])
        if args.push and result["level"] in ("中", "高", "极高"):
            push_wechat(result)
            print(f"  {'✅ 已推送' if result['level'] in ('高','极高') else '⏸️ 中级风险不推送'}")

    if args.forever:
        import time
        print(f"  🔄 持续监测模式 (每15分钟), 按 Ctrl+C 停止")
        while True:
            run_once()
            print(f"  ⏳ 下次检查: {datetime.now(CST) + timedelta(minutes=15):%H:%M}\n")
            time.sleep(900)
    else:
        run_once()


if __name__ == "__main__":
    main()
