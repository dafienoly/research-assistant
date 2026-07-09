"""Feedback Service — 用户反馈存储与生命周期管理

提供文件系统持久化的用户反馈/任务请求管理:
  - 反馈模型: bug / feature / improvement / question / other
  - 状态管理: new → acknowledged → in_progress → resolved / closed
  - 评论线程: 每项反馈可追加评论
  - 统计聚合: 按分类/状态/来源聚合

路径: FEEDBACK_DIR = /home/ly/.hermes/research-assistant/agent_tasks/feedback
"""
import json, os, uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))
FEEDBACK_DIR = Path("/home/ly/.hermes/research-assistant/agent_tasks/feedback")

# ── 常量 ────────────────────────────────────────────────────────────────

CATEGORIES = ["bug", "feature", "improvement", "question", "other"]
CATEGORY_LABELS = {
    "bug": "🐛 缺陷",
    "feature": "✨ 功能请求",
    "improvement": "📈 改进建议",
    "question": "❓ 疑问",
    "other": "📝 其他",
}
STATUSES = ["new", "acknowledged", "in_progress", "resolved", "closed"]
STATUS_LABELS = {
    "new": "新建",
    "acknowledged": "已确认",
    "in_progress": "处理中",
    "resolved": "已解决",
    "closed": "已关闭",
}
SOURCES = ["user", "ui", "api", "system"]


# ── 数据模型 ────────────────────────────────────────────────────────────

class FeedbackItem:
    def __init__(
        self,
        title: str,
        content: str,
        category: str = "other",
        source: str = "user",
        user_name: str = "",
        user_contact: str = "",
    ):
        if category not in CATEGORIES:
            category = "other"
        if source not in SOURCES:
            source = "user"

        self.id = f"FB_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.title = title
        self.content = content
        self.category = category
        self.status = "new"
        self.source = source
        self.user_name = user_name
        self.user_contact = user_contact
        self.created_at = datetime.now(CST).isoformat()
        self.updated_at = self.created_at
        self.comments = []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "category": self.category,
            "category_label": CATEGORY_LABELS.get(self.category, self.category),
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "source": self.source,
            "user_name": self.user_name,
            "user_contact": self.user_contact,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "comments": self.comments,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FeedbackItem":
        item = cls.__new__(cls)
        item.id = d.get("id", "")
        item.title = d.get("title", "")
        item.content = d.get("content", "")
        item.category = d.get("category", "other")
        item.status = d.get("status", "new")
        item.source = d.get("source", "user")
        item.user_name = d.get("user_name", "")
        item.user_contact = d.get("user_contact", "")
        item.created_at = d.get("created_at", "")
        item.updated_at = d.get("updated_at", "")
        item.comments = d.get("comments", [])
        return item


# ── 存储 ────────────────────────────────────────────────────────────────

def _ensure_dir():
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)


def _file_path(fid: str) -> Path:
    return FEEDBACK_DIR / f"{fid}.json"


def save(item: FeedbackItem) -> dict:
    """保存反馈项到磁盘"""
    _ensure_dir()
    data = item.to_dict()
    _file_path(item.id).write_text(
        json.dumps(data, indent=2, ensure_ascii=False)
    )
    return data


def load(fid: str) -> Optional[FeedbackItem]:
    """加载单个反馈项"""
    fp = _file_path(fid)
    if not fp.exists():
        return None
    try:
        return FeedbackItem.from_dict(json.loads(fp.read_text()))
    except (json.JSONDecodeError, KeyError):
        return None


def delete(fid: str) -> bool:
    """删除反馈项"""
    fp = _file_path(fid)
    if not fp.exists():
        return False
    fp.unlink()
    return True


def list_all(
    category: str = "",
    status: str = "",
    source: str = "",
    limit: int = 100,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_desc: bool = True,
) -> tuple:
    """列出反馈项，支持过滤和分页

    Returns:
        (items: list[dict], total: int)
    """
    _ensure_dir()
    items = []
    for fp in sorted(FEEDBACK_DIR.glob("*.json"), reverse=sort_desc):
        try:
            item = FeedbackItem.from_dict(json.loads(fp.read_text()))
        except (json.JSONDecodeError, KeyError):
            continue

        # 过滤
        if category and item.category != category:
            continue
        if status and item.status != status:
            continue
        if source and item.source != source:
            continue

        items.append(item.to_dict())

    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, total


def create(
    title: str,
    content: str,
    category: str = "other",
    source: str = "user",
    user_name: str = "",
    user_contact: str = "",
) -> dict:
    """创建并保存一条反馈"""
    item = FeedbackItem(
        title=title,
        content=content,
        category=category,
        source=source,
        user_name=user_name,
        user_contact=user_contact,
    )
    return save(item)


def update_status(fid: str, new_status: str) -> Optional[dict]:
    """更新反馈状态"""
    if new_status not in STATUSES:
        return None
    item = load(fid)
    if item is None:
        return None
    item.status = new_status
    item.updated_at = datetime.now(CST).isoformat()
    return save(item)


def add_comment(fid: str, user: str, text: str) -> Optional[dict]:
    """追加评论到反馈项"""
    if not text.strip():
        return None
    item = load(fid)
    if item is None:
        return None
    comment = {
        "id": f"c_{uuid.uuid4().hex[:8]}",
        "user": user or "anonymous",
        "text": text,
        "created_at": datetime.now(CST).isoformat(),
    }
    item.comments.append(comment)
    item.updated_at = datetime.now(CST).isoformat()
    return save(item)


def get_stats() -> dict:
    """获取反馈统计"""
    _ensure_dir()
    total = 0
    by_category = {c: 0 for c in CATEGORIES}
    by_status = {s: 0 for s in STATUSES}
    by_source = {s: 0 for s in SOURCES}

    for fp in FEEDBACK_DIR.glob("*.json"):
        try:
            d = json.loads(fp.read_text())
        except (json.JSONDecodeError):
            continue
        total += 1
        cat = d.get("category", "other")
        if cat in by_category:
            by_category[cat] += 1
        st = d.get("status", "new")
        if st in by_status:
            by_status[st] += 1
        src = d.get("source", "user")
        if src in by_source:
            by_source[src] += 1

    return {
        "total": total,
        "by_category": by_category,
        "by_status": by_status,
        "by_source": by_source,
        "category_labels": CATEGORY_LABELS,
        "status_labels": STATUS_LABELS,
    }
