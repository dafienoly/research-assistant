"""Quantitative decision-loop API: safety, opportunity, execution, and learning."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from factor_lab.api_server.response import api_success
from factor_lab.decision_loop.benchmark import BenchmarkMatcher
from factor_lab.decision_loop.models import (
    Candidate,
    DataItemStatus,
    ExecutionRequest,
    PlannedOrder,
    PortfolioRiskInput,
    Position,
    QuoteSnapshot,
)
from factor_lab.decision_loop.portfolio import (
    evaluate_portfolio_risk,
    validate_allocations,
)
from factor_lab.decision_loop.review import calculate_review, calculate_system_metrics
from factor_lab.decision_loop.service import DecisionLoopService


router = APIRouter(prefix="/decision-loop", tags=["decision-loop"])


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PositionPreviewBody(Body):
    source: Literal["csv", "clipboard", "ocr", "manual", "miniqmt"]
    content: str | None = None
    rows: list[dict[str, Any]] | None = None
    image_path: str | None = None


class PositionConfirmBody(Body):
    preview_id: str
    expected_hash: str


class PositionRollbackBody(Body):
    snapshot_id: str


class GuardBody(Body):
    position: Position
    quote: QuoteSnapshot
    data_items: list[DataItemStatus]
    conflicts: list[dict[str, Any]] = Field(default_factory=list)


class AcknowledgeBody(Body):
    actor: str = "user"


class AuthorizationCreateBody(Body):
    trading_date: str
    strategy_summary: str
    risk_budget: dict[str, float]
    max_order_amount: float
    max_total_amount: float
    orders: list[PlannedOrder]
    parameter_version: str


class AuthorizationActivateBody(Body):
    nonce: str
    displayed_plan_hash: str


class RevokeBody(Body):
    reason: str


class OpportunityBody(Body):
    candidates: list[Candidate]


class PortfolioBody(Body):
    positions: list[Position]
    equity: float
    cash: float


class ReviewBody(Body):
    entry_price: float
    path_prices: list[float]
    exit_price: float
    benchmark_prices: list[float] | None = None
    recommended_exit_price: float | None = None
    quantity: int
    fees: float = 0
    expected_entry_price: float | None = None
    attribution: dict[str, str] | None = None
    ordered_quantity: int | None = None
    filled_quantity: int | None = None


class SystemMetricsBody(Body):
    equity_curve: list[float]
    period_days: int
    turnover_notional: float
    capacity_estimate: float | None = None
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    book_trade_returns: dict[str, list[float]] = Field(default_factory=dict)
    planned_orders: int = 0
    filled_orders: int = 0


class ParameterProposalBody(Body):
    parameter: str
    current_value: Any
    proposed_value: Any
    evidence: dict[str, Any]
    decision_id: str | None = None
    event_id: str | None = None
    order_id: str | None = None


class OosBody(Body):
    passed: bool
    metrics: dict[str, Any]


class WeeklyDecisionBody(Body):
    approved: bool
    reviewer: str


class BenchmarkBody(Body):
    symbol: str
    instrument_type: Literal["stock", "etf"]
    stock_sector_map: dict[str, dict[str, Any]] = Field(default_factory=dict)
    etf_map: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PortfolioBenchmarkBody(Body):
    exposure_weights: dict[str, float]
    tradable: list[str]


def _service() -> DecisionLoopService:
    return DecisionLoopService()


@router.get("/status")
async def decision_loop_status(request: Request):
    return api_success(data=_service().status(), request=request)


@router.post("/positions/preview")
async def preview_positions(body: PositionPreviewBody, request: Request):
    service = _service().positions
    try:
        if body.source == "ocr":
            if not body.image_path:
                raise ValueError("image_path is required for OCR")
            result = service.preview_ocr(body.image_path)
        elif body.rows is not None:
            result = service.preview_rows(body.rows, body.source)
        elif body.content is not None:
            result = service.preview_text(body.content, body.source)
        else:
            raise ValueError("content or rows is required")
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.post("/positions/confirm")
async def confirm_positions(body: PositionConfirmBody, request: Request):
    try:
        result = _service().positions.confirm(body.preview_id, body.expected_hash)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.post("/positions/ocr-preview")
async def preview_ocr_upload(request: Request, image: UploadFile = File(...)):
    suffix = Path(image.filename or "position.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        raise HTTPException(status_code=415, detail="unsupported OCR image type")
    content = await image.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="OCR image exceeds 10 MiB")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        result = _service().positions.preview_ocr(temporary_path)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.post("/positions/miniqmt/preview")
async def preview_miniqmt_positions(request: Request):
    try:
        result = _service().qmt_sync.preview()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.post("/positions/miniqmt/confirm")
async def confirm_miniqmt_positions(body: PositionConfirmBody, request: Request):
    try:
        result = _service().qmt_sync.confirm(body.preview_id, body.expected_hash)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.get("/positions/template")
async def position_import_template(request: Request):
    return api_success(data={
        "columns": ["证券代码", "证券名称", "持仓数量", "可用数量", "成本价", "现价", "证券类型", "账簿", "主题"],
        "csv": "证券代码,证券名称,持仓数量,可用数量,成本价,现价,证券类型,账簿,主题\n588200.SH,示例ETF,1000,1000,1.20,1.25,ETF,催化,半导体设备\n",
    }, request=request)


@router.get("/positions/history")
async def position_history(request: Request, limit: int = 50):
    return api_success(data=[row.model_dump(mode="json") for row in _service().positions.history(limit)], request=request)


@router.post("/positions/rollback")
async def rollback_positions(body: PositionRollbackBody, request: Request):
    try:
        result = _service().positions.rollback(body.snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.post("/guard/evaluate")
async def evaluate_guard(body: GuardBody, request: Request):
    result = _service().evaluate_position(
        body.position, body.quote, body.data_items, body.conflicts
    )
    return api_success(data=result, request=request)


@router.post("/events/{event_id}/acknowledge")
async def acknowledge_event(event_id: str, body: AcknowledgeBody, request: Request):
    return api_success(
        data=_service().notifications.acknowledge(event_id, body.actor), request=request
    )


@router.post("/notifications/l2-digest/flush")
async def flush_l2_digest(request: Request):
    return api_success(data=_service().notifications.flush_l2_digest(), request=request)


@router.post("/authorizations")
async def create_authorization(body: AuthorizationCreateBody, request: Request):
    auth, nonce = _service().authorizations.create_plan(**body.model_dump())
    return api_success(
        data={
            "authorization": auth.model_dump(mode="json"),
            "confirmation_nonce": nonce,
        },
        request=request,
    )


@router.post("/authorizations/{trading_date}/activate")
async def activate_authorization(
    trading_date: str, body: AuthorizationActivateBody, request: Request
):
    try:
        auth = _service().authorizations.activate(
            trading_date, body.nonce, body.displayed_plan_hash
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return api_success(data=auth.model_dump(mode="json"), request=request)


@router.post("/authorizations/{trading_date}/revoke")
async def revoke_authorization(trading_date: str, body: RevokeBody, request: Request):
    try:
        auth = _service().authorizations.revoke(trading_date, body.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return api_success(data=auth.model_dump(mode="json"), request=request)


@router.get("/authorizations/{trading_date}")
async def get_authorization(trading_date: str, request: Request):
    auth = _service().authorizations.current(trading_date)
    return api_success(
        data=auth.model_dump(mode="json") if auth else None, request=request
    )


@router.post("/execution/submit")
async def submit_execution(body: ExecutionRequest, trading_date: str, request: Request):
    return api_success(
        data=_service().execution.submit(body, trading_date), request=request
    )


@router.post("/opportunities/evaluate")
async def evaluate_opportunities(body: OpportunityBody, request: Request):
    service = _service()
    result = service.opportunities.build_pass_list(body.candidates)
    service.store.write_json(
        "opportunities/current.json", result.model_dump(mode="json")
    )
    targets = []
    for candidate in result.primary + result.backup:
        targets.append(
            {
                "symbol": candidate.symbol,
                "name": candidate.name,
                "book": candidate.book.value,
                "instrument_type": candidate.instrument_type,
                "reference_price": candidate.entry_reference_price,
                "kind": "recommendation",
            }
        )
        if candidate.benchmark_symbol:
            targets.append(
                {
                    "symbol": candidate.benchmark_symbol,
                    "name": "行业锚定",
                    "book": "swing",
                    "instrument_type": "etf",
                    "reference_price": None,
                    "kind": "anchor_etf",
                }
            )
    service.store.write_json(
        "watchlist/current.json",
        {"decision_id": result.decision_id, "targets": targets},
    )
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.post("/portfolio/validate")
async def validate_portfolio(body: PortfolioBody, request: Request):
    return api_success(
        data=validate_allocations(body.positions, body.equity, body.cash),
        request=request,
    )


@router.post("/portfolio/risk")
async def portfolio_risk(body: PortfolioRiskInput, request: Request):
    return api_success(
        data=evaluate_portfolio_risk(body).model_dump(mode="json"), request=request
    )


@router.post("/benchmarks/match")
async def match_benchmark(body: BenchmarkBody, request: Request):
    matcher = BenchmarkMatcher(body.stock_sector_map, body.etf_map) if body.stock_sector_map or body.etf_map else BenchmarkMatcher.from_durable_registry()
    match = matcher.match_instrument(
        body.symbol, body.instrument_type
    )
    return api_success(
        data={
            "primary": match.primary,
            "secondary": match.secondary,
            "reason": match.reason,
            "evidence_source": match.evidence_source,
        },
        request=request,
    )


@router.post("/benchmarks/portfolio")
async def match_portfolio_benchmark(body: PortfolioBenchmarkBody, request: Request):
    result = BenchmarkMatcher.match_portfolio(body.exposure_weights, set(body.tradable))
    return api_success(
        data=result or {"components": None, "reason": "no reliable tradable exposure mapping"},
        request=request,
    )


@router.post("/reviews/calculate")
async def review_trade(body: ReviewBody, request: Request):
    try:
        result = calculate_review(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.post("/reviews/system-metrics")
async def review_system_metrics(body: SystemMetricsBody, request: Request):
    try:
        result = calculate_system_metrics(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return api_success(data=result, request=request)


@router.post("/parameters/candidates")
async def propose_parameter(body: ParameterProposalBody, request: Request):
    result = _service().parameters.propose(**body.model_dump())
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.post("/parameters/candidates/{candidate_id}/oos")
async def record_oos(candidate_id: str, body: OosBody, request: Request):
    try:
        result = _service().parameters.record_oos(
            candidate_id, body.passed, body.metrics
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return api_success(data=result.model_dump(mode="json"), request=request)


@router.post("/parameters/candidates/{candidate_id}/weekly-decision")
async def weekly_parameter_decision(
    candidate_id: str, body: WeeklyDecisionBody, request: Request
):
    try:
        result = _service().parameters.weekly_decide(
            candidate_id, body.approved, body.reviewer
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return api_success(data=result.model_dump(mode="json"), request=request)
