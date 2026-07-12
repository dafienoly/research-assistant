"""Semiconductor-theme API backed only by canonical DataHub projections."""

from __future__ import annotations

import json

import pandas as pd
from fastapi import APIRouter, Query, Request

from factor_lab.api_server.response import api_error, api_success
from factor_lab.datahub_access import read_benchmark_projection


router = APIRouter()


@router.get("/theme/semiconductor/status")
async def semiconductor_theme_status(request: Request):
    """Fail visibly until the legacy non-null schema can represent partial truth."""
    return api_error(
        "THEME_STATUS_SCHEMA_NOT_INTEGRATED",
        "静态半导体状态、ETF价格、事件和基本面已退役；请使用 VNext semi-mainline 与真实 history 数据。",
        status_code=503,
        request=request,
    )


@router.get("/theme/semiconductor/subsectors")
async def semiconductor_subsectors(request: Request):
    """Return an honest empty set until a canonical subsector projection exists."""
    return api_success(
        data={
            "status": "MISSING",
            "updated_at": None,
            "items": [],
            "reason": "canonical_semiconductor_subsector_projection_missing",
        },
        request=request,
    )


def _history_series(days: int) -> tuple[list[dict], dict]:
    frames = {
        "semi_ew": read_benchmark_projection("semiconductor_ew"),
        "all_a_ew": read_benchmark_projection("ew_a_share"),
        "core_pool_ew": read_benchmark_projection("semiconductor_core_ew"),
    }
    aligned = None
    lineage = {}
    for output_name, frame in frames.items():
        projected = frame.set_index("date")[["return"]].rename(columns={"return": output_name})
        aligned = projected if aligned is None else aligned.join(projected, how="inner")
        lineage[output_name] = {
            "dataset": frame.attrs["dataset"],
            "sha256": frame.attrs["sha256"],
            "generated_at": frame.attrs["generated_at"],
        }
    if aligned is None or aligned.empty:
        raise ValueError("canonical theme benchmark projections have no overlapping dates")
    aligned = aligned.sort_index().tail(days)
    nav = (1.0 + aligned).cumprod() * 100.0
    series = [
        {
            "date": index.date().isoformat(),
            "semi_ew": round(float(row["semi_ew"]), 6),
            "all_a_ew": round(float(row["all_a_ew"]), 6),
            "core_pool_ew": round(float(row["core_pool_ew"]), 6),
        }
        for index, row in nav.iterrows()
    ]
    return series, lineage


@router.get("/theme/semiconductor/history")
async def semiconductor_history(
    request: Request,
    days: int = Query(60, ge=5, le=120),
):
    """Return real equal-weight NAV series derived from DataHub daily returns."""
    try:
        series, lineage = _history_series(days)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        return api_error(
            "THEME_HISTORY_UNAVAILABLE",
            f"canonical theme history unavailable: {type(exc).__name__}",
            status_code=503,
            request=request,
        )
    return api_success(
        data={
            "status": "OK",
            "updated_at": max(item["generated_at"] for item in lineage.values()),
            "series": series,
            "lineage": lineage,
            "synthetic": False,
        },
        request=request,
    )
