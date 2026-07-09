"""User Feedback / Task Intake API routes — V7.8

提供用户反馈提交、查看、状态管理、评论的 REST API：
  - GET    /api/feedback/stats         — 反馈统计
  - GET    /api/feedback               — 列表（支持过滤/分页/排序）
  - POST   /api/feedback               — 提交反馈
  - GET    /api/feedback/{fid}         — 反馈详情
  - PUT    /api/feedback/{fid}/status  — 更新状态
  - POST   /api/feedback/{fid}/comments — 追加评论
  - DELETE /api/feedback/{fid}         — 删除反馈

测试时可通过 monkeypatch 替换 FEEDBACK_DIR 指向临时路径。
"""
import os, json, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from factor_lab.leader.feedback_service import (
    CATEGORIES, STATUSES, SOURCES,
    list_all, create, load, delete as fb_delete,
    update_status, add_comment, get_stats,
    FEEDBACK_DIR,
)

CST = timezone(timedelta(hours=8))

router = APIRouter()


# ── 请求/响应模型 ───────────────────────────────────────────────────────

class CreateFeedbackBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="反馈标题")
    content: str = Field(..., min_length=1, max_length=10000, description="反馈内容")
    category: str = Field("other", description=f"分类: {', '.join(CATEGORIES)}")
    source: str = Field("user", description=f"来源: {', '.join(SOURCES)}")
    user_name: str = Field("", max_length=100, description="反馈人")
    user_contact: str = Field("", max_length=200, description="联系方式")


class UpdateStatusBody(BaseModel):
    status: str = Field(..., description=f"新状态: {', '.join(STATUSES)}")


class AddCommentBody(BaseModel):
    user: str = Field("", max_length=100, description="评论人")
    text: str = Field(..., min_length=1, max_length=5000, description="评论内容")


# ── 工具函数 ────────────────────────────────────────────────────────────

def _validate_category(cat: str):
    if cat and cat not in CATEGORIES:
        raise HTTPException(422, f"无效分类 '{cat}'，可选: {', '.join(CATEGORIES)}")


def _validate_status(st: str):
    if st and st not in STATUSES:
        raise HTTPException(422, f"无效状态 '{st}'，可选: {', '.join(STATUSES)}")


# ── 端点 ────────────────────────────────────────────────────────────────


@router.get("/feedback/stats")
def feedback_stats():
    """GET /api/feedback/stats — 反馈统计"""
    return get_stats()


@router.get("/feedback")
def feedback_list(
    category: str = Query("", description="按分类过滤"),
    status: str = Query("", description="按状态过滤"),
    source: str = Query("", description="按来源过滤"),
    limit: int = Query(100, description="每页条数", ge=1, le=500),
    offset: int = Query(0, description="偏移量", ge=0),
    sort_by: str = Query("created_at", description="排序字段"),
    sort_desc: bool = Query(True, description="是否降序"),
):
    """GET /api/feedback — 反馈列表（支持过滤/分页/排序）"""
    _validate_category(category)
    _validate_status(status)

    items, total = list_all(
        category=category,
        status=status,
        source=source,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_desc=sort_desc,
    )
    return {
        "total": total,
        "count": len(items),
        "offset": offset,
        "limit": limit,
        "items": items,
    }


@router.post("/feedback", status_code=201)
def feedback_create(body: CreateFeedbackBody):
    """POST /api/feedback — 提交反馈"""
    _validate_category(body.category)
    if body.source and body.source not in SOURCES:
        raise HTTPException(422, f"无效来源 '{body.source}'")

    result = create(
        title=body.title,
        content=body.content,
        category=body.category,
        source=body.source,
        user_name=body.user_name,
        user_contact=body.user_contact,
    )
    return result


@router.get("/feedback/{fid}")
def feedback_detail(fid: str):
    """GET /api/feedback/{fid} — 反馈详情"""
    item = load(fid)
    if item is None:
        raise HTTPException(404, f"反馈 {fid} 不存在")
    return item


@router.put("/feedback/{fid}/status")
def feedback_update_status(fid: str, body: UpdateStatusBody):
    """PUT /api/feedback/{fid}/status — 更新反馈状态"""
    _validate_status(body.status)
    result = update_status(fid, body.status)
    if result is None:
        raise HTTPException(404, f"反馈 {fid} 不存在")
    return result


@router.post("/feedback/{fid}/comments")
def feedback_add_comment(fid: str, body: AddCommentBody):
    """POST /api/feedback/{fid}/comments — 追加评论"""
    result = add_comment(fid, body.user, body.text)
    if result is None:
        # 区分不存在 vs 空内容
        item = load(fid)
        if item is None:
            raise HTTPException(404, f"反馈 {fid} 不存在")
        raise HTTPException(422, "评论内容不能为空")
    return result


@router.delete("/feedback/{fid}")
def feedback_delete(fid: str):
    """DELETE /api/feedback/{fid} — 删除反馈"""
    if not fb_delete(fid):
        raise HTTPException(404, f"反馈 {fid} 不存在")
    return {"status": "deleted", "id": fid}
