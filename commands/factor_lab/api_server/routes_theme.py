"""主题 (Theme) API — 行业主题状态查询。"""

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from factor_lab.api_server.response import api_success, api_error

CST = timezone(timedelta(hours=8))

router = APIRouter()


@router.get("/theme/semiconductor/status")
async def semiconductor_theme_status(request: Request):
    """查询半导体主题状态。"""
    return api_success(
        data={
            "theme": "semiconductor",
            "name": "半导体",
            "updated_at": "2026-07-08T15:00:00+08:00",
            "theme_state": "偏强",
            "theme_weight": 70,
            "sentiment": "bullish",
            "sentiment_score": 0.72,
            "metrics": {
                "semi_ew_return": 1.85,
                "all_a_ew_return": 0.52,
                "relative_strength": 1.32,
                "turnover_share": 8.5,
                "advance_ratio": 62.3,
                "core_pool_return": 2.12,
                "broad_pool_return": 1.58,
            },
            "etf": {
                "ticker": "588710",
                "name": "科创板半导体设备ETF",
                "price": 1.235,
                "change_pct": 2.15,
                "volume": 85000000,
            },
            "etf_basket": [
                {"ticker": "588710", "name": "科创芯片设备ETF", "price": 1.235, "change_pct": 2.15, "volume": 85000000, "amount": 1.05e8},
                {"ticker": "512480", "name": "半导体ETF", "price": 0.892, "change_pct": 1.85, "volume": 320000000, "amount": 2.85e8},
                {"ticker": "512760", "name": "芯片ETF", "price": 1.156, "change_pct": 2.35, "volume": 210000000, "amount": 2.43e8},
                {"ticker": "159813", "name": "半导体设备ETF", "price": 0.978, "change_pct": 1.65, "volume": 95000000, "amount": 9.29e7},
                {"ticker": "159865", "name": "芯片50ETF", "price": 1.102, "change_pct": 1.92, "volume": 78000000, "amount": 8.60e7},
            ],
            "key_events": [
                {"date": "2026-07-08", "title": "中微公司发布 3nm 刻蚀设备", "impact": "positive"},
                {"date": "2026-07-07", "title": "美国扩大对华芯片设备出口限制", "impact": "negative"},
                {"date": "2026-07-06", "title": "大基金三期增资华虹半导体", "impact": "positive"},
            ],
            "top_holdings": [
                {"ticker": "688001", "name": "华大九天", "weight": 12.5, "change_pct": 3.2},
                {"ticker": "688002", "name": "中微公司", "weight": 11.8, "change_pct": 2.8},
                {"ticker": "688003", "name": "天岳先进", "weight": 9.2, "change_pct": 1.5},
            ],
            "metrics_fundamental": {
                "pe_ttm": 45.6,
                "pb": 6.2,
                "dividend_yield": 0.5,
                "yoy_revenue_growth": 22.3,
                "yoy_profit_growth": 18.7,
            },
        },
        request=request,
    )


@router.get("/theme/semiconductor/subsectors")
async def semiconductor_subsectors(request: Request):
    """查询半导体细分方向表现。"""
    return api_success(
        data={
            "updated_at": "2026-07-08T15:00:00+08:00",
            "items": [
                {"subsector": "设备", "total_stocks": 85, "advance_count": 62, "advance_ratio": 72.9, "avg_change_pct": 2.35, "turnover": 125.6},
                {"subsector": "材料", "total_stocks": 72, "advance_count": 48, "advance_ratio": 66.7, "avg_change_pct": 1.85, "turnover": 78.3},
                {"subsector": "设计", "total_stocks": 120, "advance_count": 70, "advance_ratio": 58.3, "avg_change_pct": 1.25, "turnover": 185.2},
                {"subsector": "制造", "total_stocks": 35, "advance_count": 22, "advance_ratio": 62.9, "avg_change_pct": 1.55, "turnover": 95.8},
                {"subsector": "封测", "total_stocks": 45, "advance_count": 28, "advance_ratio": 62.2, "avg_change_pct": 1.45, "turnover": 52.4},
                {"subsector": "EDA", "total_stocks": 28, "advance_count": 20, "advance_ratio": 71.4, "avg_change_pct": 2.85, "turnover": 35.6},
            ],
        },
        request=request,
    )


def _generate_history(days: int = 60):
    """生成半导体 vs 全A等权模拟历史数据。"""
    now = datetime.now(CST)
    base_semi = 100.0
    base_all_a = 100.0
    base_core = 100.0
    series = []
    for i in range(days):
        d = now - timedelta(days=days - 1 - i)
        date_str = d.strftime("%Y-%m-%d")
        # 模拟半导体等权走势（小幅波动+趋势）
        semi_change = (0.05 + 0.3 * math.sin(i * 0.15) + 0.15 * math.sin(i * 0.05) + 0.1 * (i / days - 0.5))
        all_a_change = (0.02 + 0.15 * math.sin(i * 0.12) + 0.08 * math.sin(i * 0.04))
        core_change = (0.06 + 0.35 * math.sin(i * 0.15 + 0.3) + 0.18 * math.sin(i * 0.05) + 0.12 * (i / days - 0.5))
        base_semi *= (1 + semi_change / 100)
        base_all_a *= (1 + all_a_change / 100)
        base_core *= (1 + core_change / 100)
        series.append({
            "date": date_str,
            "semi_ew": round(base_semi, 2),
            "all_a_ew": round(base_all_a, 2),
            "core_pool_ew": round(base_core, 2),
        })
    return series


@router.get("/theme/semiconductor/history")
async def semiconductor_history(request: Request, days: int = 60):
    """查询半导体主题历史曲线数据（等权指数模拟）。"""
    series = _generate_history(min(max(days, 5), 120))
    return api_success(
        data={
            "updated_at": datetime.now(CST).isoformat(),
            "series": series,
        },
        request=request,
    )
