"""投资组合 (Portfolio) API — 组合推荐生成与查询。"""

from fastapi import APIRouter, Request
from factor_lab.api_server.response import api_success, api_error
from factor_lab.api_server.services.job_service import job_service
from factor_lab.api_server.services.audit_service import audit_service

router = APIRouter()


@router.get("/portfolio/recommendation/latest")
async def get_latest_recommendation(request: Request):
    """获取最新的投资组合推荐。"""
    # 模拟最近一次的推荐结果
    return api_success(
        data={
            "generated_at": "2026-07-08T15:30:00+08:00",
            "strategy": "多因子均衡策略 v3",
            "holdings": [
                {"ticker": "688001", "name": "华大九天", "weight": 5.2, "reason": "EDA 龙头，国产替代加速"},
                {"ticker": "688002", "name": "中微公司", "weight": 4.8, "reason": "刻蚀设备龙头，先进制程受益"},
                {"ticker": "688003", "name": "天岳先进", "weight": 4.5, "reason": "碳化硅衬底，新能源车驱动"},
                {"ticker": "600519", "name": "贵州茅台", "weight": 3.0, "reason": "核心资产，防御配置"},
                {"ticker": "300750", "name": "宁德时代", "weight": 3.5, "reason": "动力电池龙头，全球份额持续提升"},
            ],
            "expected_annual_return": 18.5,
            "expected_volatility": 22.3,
            "expected_sharpe": 0.83,
            "risk_level": "moderate",
            "status": "active",
        },
        request=request,
    )


@router.post("/portfolio/recommendation/run")
async def run_recommendation(request: Request, body: dict):
    """触发投资组合推荐生成任务。"""
    strategy = body.get("strategy", "multi_factor")
    universe = body.get("universe", "hs300")
    risk_tolerance = body.get("risk_tolerance", "moderate")

    job = job_service.create(
        name=f"portfolio_recommendation_{strategy[:20]}",
        job_type="portfolio",
        params={"strategy": strategy, "universe": universe, "risk_tolerance": risk_tolerance},
    )
    job_service.update_status(job.run_id, "running", "组合推荐计算中...")

    import asyncio

    async def _simulate():
        await asyncio.sleep(3)
        job_service.set_result(job.run_id, {
            "status": "completed",
            "holdings_count": 15,
            "expected_sharpe": 0.85,
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone(__import__("datetime").timedelta(hours=8))
            ).isoformat(),
        })
        job_service.update_status(job.run_id, "completed", "组合推荐生成完成")

    asyncio.create_task(_simulate())

    audit_service.record(
        event_type="portfolio",
        resource="/api/portfolio/recommendation/run",
        action="execute",
        detail={"run_id": job.run_id, "strategy": strategy, "universe": universe},
        run_id=job.run_id,
    )

    return api_success(data={"job": job.to_dict()}, status_code=202, request=request)
