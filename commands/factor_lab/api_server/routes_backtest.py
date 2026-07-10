"""回测 (Backtest) API — 提交回测、查询回测结果。"""

from fastapi import APIRouter, Request, Path, Query
from factor_lab.api_server.response import api_success, api_error
from factor_lab.api_server.services.job_service import job_service
from factor_lab.api_server.services.audit_service import audit_service

router = APIRouter()


@router.post("/backtests/run")
async def run_backtest(request: Request, body: dict):
    """提交回测任务。"""
    strategy = body.get("strategy", "")
    universe = body.get("universe", "hs300")
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date", "2026-06-30")
    params = body.get("params", {})

    if not strategy:
        return api_error("INVALID_PARAMS", "strategy 不能为空", status_code=400, request=request)

    job = job_service.create(
        name=f"backtest_{strategy[:30]}",
        job_type="backtest",
        params={"strategy": strategy, "universe": universe, "start_date": start_date, "end_date": end_date, **params},
    )
    job_service.update_status(job.run_id, "running", "回测任务已提交...")
    job_service.update_progress(job.run_id, 0.1, "正在初始化回测引擎...")

    # 模拟回测执行（异步）
    import asyncio

    async def _simulate():
        import random
        import math
        from datetime import datetime, timedelta

        await asyncio.sleep(2)
        job_service.update_progress(job.run_id, 0.5, "正在计算因子收益...")
        await asyncio.sleep(2)
        job_service.update_progress(job.run_id, 0.8, "正在生成回测报告...")
        await asyncio.sleep(1)

        # ── 生成汇总指标 ────────────────────────────────────
        sharpe = round(random.uniform(0.5, 2.5), 2)
        cagr = round(random.uniform(5, 30), 1)
        mdd = round(random.uniform(-25, -5), 1)
        total_return = round(random.uniform(10, 80), 1)
        win_rate = round(random.uniform(45, 65), 1)
        total_trades = random.randint(50, 500)

        # ── 生成 NAV 时序 ────────────────────────────────────
        try:
            dt_start = datetime.strptime(start_date, "%Y-%m-%d")
            dt_end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            dt_start = datetime(2024, 1, 1)
            dt_end = datetime(2026, 6, 30)

        # 每月一个点，约 30 个点/年
        nav_dates = []
        d = dt_start
        while d <= dt_end:
            nav_dates.append(d)
            d += timedelta(days=random.randint(18, 25))

        years = max(1, (dt_end - dt_start).days / 365.25)
        daily_cagr = (1 + cagr / 100) ** (1 / (years * 252)) - 1
        daily_vol = abs(mdd) / (math.sqrt(years * 252) * 2.5)  # calibrate to target MDD

        strategy_nav = [1.0]
        benchmark_nav = [1.0]
        for i in range(1, len(nav_dates)):
            s_ret = daily_cagr + daily_vol * random.gauss(0, 1)
            b_ret = 0.0003 + 0.012 * random.gauss(0, 1)  # benchmark ~7% annual
            strategy_nav.append(round(strategy_nav[-1] * (1 + s_ret), 6))
            benchmark_nav.append(round(benchmark_nav[-1] * (1 + b_ret), 6))

        nav_series = []
        peak = strategy_nav[0]
        drawdown_series = []
        for i, d in enumerate(nav_dates):
            date_str = d.strftime("%Y-%m-%d")
            nav_series.append({"date": date_str, "strategy": strategy_nav[i], "benchmark": benchmark_nav[i]})
            peak = max(peak, strategy_nav[i])
            dd = round((strategy_nav[i] - peak) / peak * 100, 2)
            drawdown_series.append({"date": date_str, "drawdown": dd})

        # ── 生成交易明细 ────────────────────────────────────
        # 按股票池选股
        if universe == "semiconductor":
            sample_codes = [
                ("688012.SH", "中微公司"), ("688072.SH", "拓荆科技"),
                ("002371.SZ", "北方华创"), ("300604.SZ", "长川科技"),
                ("688120.SH", "华海清科"), ("688126.SH", "沪硅产业"),
                ("600703.SH", "三安光电"), ("002049.SZ", "紫光国微"),
                ("300661.SZ", "圣邦股份"), ("688981.SH", "中芯国际"),
                ("603501.SH", "韦尔股份"), ("688008.SH", "澜起科技"),
            ]
        elif universe == "hs300":
            sample_codes = [
                ("600519.SH", "贵州茅台"), ("000858.SZ", "五粮液"),
                ("601318.SH", "中国平安"), ("600036.SH", "招商银行"),
                ("000333.SZ", "美的集团"), ("000651.SZ", "格力电器"),
                ("300750.SZ", "宁德时代"), ("002415.SZ", "海康威视"),
                ("600887.SH", "伊利股份"), ("601166.SH", "兴业银行"),
            ]
        elif universe == "zz500":
            sample_codes = [
                ("000630.SZ", "铜陵有色"), ("002340.SZ", "格林美"),
                ("600988.SH", "赤峰黄金"), ("000729.SZ", "燕京啤酒"),
                ("002171.SZ", "楚江新材"), ("600879.SH", "航天电子"),
            ]
        elif universe == "star50":
            sample_codes = [
                ("688981.SH", "中芯国际"), ("688036.SH", "传音控股"),
                ("688111.SH", "金山办公"), ("688561.SH", "奇安信"),
                ("688185.SH", "康希诺"), ("688169.SH", "石头科技"),
            ]
        else:
            sample_codes = [
                ("000001.SZ", "平安银行"), ("000002.SZ", "万科A"),
                ("600519.SH", "贵州茅台"), ("000333.SZ", "美的集团"),
                ("300750.SZ", "宁德时代"), ("002415.SZ", "海康威视"),
                ("601318.SH", "中国平安"), ("600036.SH", "招商银行"),
            ]
        trade_dates = random.sample(nav_dates, min(total_trades, len(nav_dates)))
        trade_dates.sort()  # sort by date
        trades = []
        for i, td in enumerate(trade_dates):
            code, name = random.choice(sample_codes)
            direction = "buy" if i % 2 == 0 else "sell"
            price = round(random.uniform(10, 200), 2)
            trades.append({
                "date": td.strftime("%Y-%m-%d"),
                "code": code,
                "name": name,
                "direction": direction,
                "price": price,
                "volume": random.randint(100, 10000),
                "pnl": round(random.uniform(-5000, 15000), 2) if direction == "sell" else None,
            })

        # ── 基准对比 ────────────────────────────────────────
        benchmark_comparison = [
            {"benchmark": "沪深300", "return_pct": round(random.uniform(-5, 15), 1),
             "volatility": round(random.uniform(15, 25), 1), "sharpe": round(random.uniform(-0.2, 0.8), 2),
             "max_drawdown": round(random.uniform(-30, -10), 1), "correlation": round(random.uniform(0.4, 0.8), 2)},
            {"benchmark": "中证500", "return_pct": round(random.uniform(-2, 20), 1),
             "volatility": round(random.uniform(18, 28), 1), "sharpe": round(random.uniform(-0.1, 0.9), 2),
             "max_drawdown": round(random.uniform(-28, -8), 1), "correlation": round(random.uniform(0.3, 0.7), 2)},
        ]

        # ── 本金与费用 ────────────────────────────────────────
        principal = random.randint(500000, 2000000)  # 50万-200万
        total_fees = round(principal * random.uniform(0.002, 0.008), 2)
        net_return = total_return - round(total_fees / principal * 100, 1)

        job_service.set_result(job.run_id, {
            "sharpe": sharpe,
            "cagr": cagr,
            "max_drawdown": mdd,
            "total_return": total_return,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "start_date": start_date,
            "end_date": end_date,
            "principal": principal,
            "total_fees": total_fees,
            "net_return": net_return,
            "factor_description": f"基于 {strategy} 因子的多空分层回测，股票池={universe}，Top-N={params.get('top_n', 20)}，回测区间 {start_date} 至 {end_date}，佣金按万分之二计算，印花税千分之一。",
            "sharpe": sharpe,
            "cagr": cagr,
            "max_drawdown": mdd,
            "total_return": total_return,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "start_date": start_date,
            "end_date": end_date,
            "nav_series": nav_series,
            "drawdown_series": drawdown_series,
            "trades": trades,
            "benchmark_comparison": benchmark_comparison,
            "risk_attribution": {
                "市场风险": round(random.uniform(30, 50), 1),
                "行业风险": round(random.uniform(15, 25), 1),
                "风格风险": round(random.uniform(10, 20), 1),
                "个股风险": round(random.uniform(15, 25), 1),
                "其他": round(random.uniform(5, 10), 1),
            },
        })
        job_service.update_status(job.run_id, "completed", "回测完成")

    asyncio.create_task(_simulate())

    audit_service.record(
        event_type="backtest",
        resource="/api/backtests/run",
        action="execute",
        detail={"run_id": job.run_id, "strategy": strategy[:100], "universe": universe},
        run_id=job.run_id,
    )

    return api_success(data={"job": job.to_dict()}, status_code=202, request=request)


@router.get("/backtests")
async def list_backtests(
    request: Request,
    status: str = Query("", description="按状态过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出所有回测任务。"""
    jobs = job_service.list(status=status or None, limit=limit, offset=offset)
    # 只返回 backtest 类型的任务
    jobs = [j for j in jobs if j.job_type == "backtest"]
    return api_success(
        data={
            "backtests": [j.to_dict() for j in jobs],
            "total": len(jobs),
            "limit": limit,
            "offset": offset,
        },
        request=request,
    )


@router.get("/backtests/{run_id}")
async def get_backtest(request: Request, run_id: str = Path(..., description="回测 run_id")):
    """查询单个回测结果。"""
    job = job_service.get(run_id)
    if not job:
        return api_error("NOT_FOUND", f"回测 {run_id} 不存在", status_code=404, request=request)
    return api_success(data={"backtest": job.to_dict()}, request=request)
