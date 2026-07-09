"""V7.8 User Feedback / Task Intake — API 测试

覆盖:
  - GET  /api/feedback/stats           — 统计（空/有数据）
  - GET  /api/feedback                 — 列表（空/默认/过滤/分页）
  - POST /api/feedback                 — 提交（正常/无效参数）
  - GET  /api/feedback/{fid}           — 详情（存在/不存在）
  - PUT  /api/feedback/{fid}/status    — 状态更新（正常/无效状态/不存在）
  - POST /api/feedback/{fid}/comments  — 评论（正常/空内容/不存在）
  - DELETE /api/feedback/{fid}         — 删除（存在/不存在）

边界条件:
  - 无反馈时各端点行为
  - 无效分类/状态参数
  - 空内容提交
  - 不存在反馈操作
"""
import sys, os, json, shutil, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from factor_lab.api_server.main import app
from factor_lab.leader.feedback_service import (
    FEEDBACK_DIR,
    CATEGORIES, STATUSES, SOURCES,
    create, load, list_all, get_stats, save,
    CATEGORY_LABELS, STATUS_LABELS,
)

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def temp_feedback_dir(monkeypatch):
    """每个测试前用临时目录替换 FEEDBACK_DIR"""
    tmp = Path(tempfile.mkdtemp(prefix="fb_test_"))
    monkeypatch.setattr("factor_lab.leader.feedback_service.FEEDBACK_DIR", tmp)
    monkeypatch.setattr("factor_lab.api_server.routes_feedback.FEEDBACK_DIR", tmp)
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_data():
    """创建一组测试反馈数据"""
    items = []
    for i, cat in enumerate(CATEGORIES):
        item = create(
            title=f"测试反馈 {cat}",
            content=f"这是{cat}分类的测试内容",
            category=cat,
            source="user",
            user_name=f"测试用户{i}",
        )
        items.append(item)
    return items


# ═══════════════════════════════════════════════════════════════════
# 空状态（无任何反馈）
# ═══════════════════════════════════════════════════════════════════

class TestEmpty:
    """没有任何反馈时的端点行为"""

    def test_stats_empty(self, client):
        resp = client.get("/api/feedback/stats")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 0
        assert all(v == 0 for v in d["by_category"].values())
        assert all(v == 0 for v in d["by_status"].values())
        assert all(v == 0 for v in d["by_source"].values())
        assert "category_labels" in d
        assert "status_labels" in d

    def test_list_empty(self, client):
        resp = client.get("/api/feedback")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == 0
        assert d["count"] == 0
        assert d["items"] == []

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/feedback/FB_NONEXISTENT")
        assert resp.status_code == 404

    def test_update_status_nonexistent_returns_404(self, client):
        resp = client.put("/api/feedback/FB_NONEXISTENT/status",
                          json={"status": "acknowledged"})
        assert resp.status_code == 404

    def test_comment_nonexistent_returns_404(self, client):
        resp = client.post("/api/feedback/FB_NONEXISTENT/comments",
                           json={"user": "tester", "text": "评论内容"})
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/feedback/FB_NONEXISTENT")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 提交反馈
# ═══════════════════════════════════════════════════════════════════

class TestSubmit:
    """POST /api/feedback — 提交反馈"""

    def test_submit_minimal(self, client):
        """最小必填字段"""
        resp = client.post("/api/feedback", json={
            "title": "最小反馈",
            "content": "内容",
        })
        assert resp.status_code == 201
        d = resp.json()
        assert d["title"] == "最小反馈"
        assert d["content"] == "内容"
        assert d["category"] == "other"  # default
        assert d["status"] == "new"
        assert d["source"] == "user"     # default
        assert "id" in d
        assert d["id"].startswith("FB_")

    def test_submit_full(self, client):
        """完整参数"""
        resp = client.post("/api/feedback", json={
            "title": "完整反馈",
            "content": "详细反馈内容",
            "category": "bug",
            "source": "ui",
            "user_name": "张三",
            "user_contact": "zhang@example.com",
        })
        assert resp.status_code == 201
        d = resp.json()
        assert d["title"] == "完整反馈"
        assert d["category"] == "bug"
        assert d["source"] == "ui"
        assert d["user_name"] == "张三"
        assert d["user_contact"] == "zhang@example.com"
        assert d["category_label"] == "🐛 缺陷"
        assert d["status_label"] == "新建"
        assert d["comments"] == []

    def test_submit_all_categories(self, client):
        """所有分类均可提交"""
        for cat in CATEGORIES:
            resp = client.post("/api/feedback", json={
                "title": f"分类 {cat}",
                "content": "内容",
                "category": cat,
            })
            assert resp.status_code == 201, f"分类 {cat} 提交失败"
            assert resp.json()["category"] == cat

    def test_submit_invalid_category_returns_422(self, client):
        """无效分类返回 422"""
        resp = client.post("/api/feedback", json={
            "title": "反馈",
            "content": "内容",
            "category": "invalid_cat",
        })
        assert resp.status_code == 422

    def test_submit_empty_title_returns_422(self, client):
        """空标题返回 422"""
        resp = client.post("/api/feedback", json={
            "title": "",
            "content": "内容",
        })
        assert resp.status_code == 422

    def test_submit_empty_content_returns_422(self, client):
        """空内容返回 422"""
        resp = client.post("/api/feedback", json={
            "title": "反馈",
            "content": "",
        })
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# 反馈列表
# ═══════════════════════════════════════════════════════════════════

class TestList:
    """GET /api/feedback — 反馈列表"""

    def test_list_default(self, client, sample_data):
        """默认返回全部"""
        resp = client.get("/api/feedback")
        assert resp.status_code == 200
        d = resp.json()
        assert d["total"] == len(CATEGORIES)
        assert len(d["items"]) == len(CATEGORIES)

    def test_list_filter_category(self, client, sample_data):
        """按分类过滤"""
        for cat in CATEGORIES:
            resp = client.get(f"/api/feedback?category={cat}")
            assert resp.status_code == 200
            d = resp.json()
            assert d["total"] == 1
            assert d["items"][0]["category"] == cat

    def test_list_filter_invalid_category_returns_422(self, client, sample_data):
        """无效分类值返回 422"""
        resp = client.get("/api/feedback?category=bad_cat")
        assert resp.status_code == 422

    def test_list_filter_status(self, client, sample_data):
        """按状态过滤"""
        # 所有反馈都是 new
        resp = client.get("/api/feedback?status=new")
        assert resp.status_code == 200
        assert resp.json()["total"] == len(CATEGORIES)

        resp = client.get("/api/feedback?status=resolved")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_filter_invalid_status_returns_422(self, client, sample_data):
        """无效状态值返回 422"""
        resp = client.get("/api/feedback?status=unknown_status")
        assert resp.status_code == 422

    def test_list_pagination(self, client, sample_data):
        """分页"""
        resp = client.get("/api/feedback?limit=2&offset=0")
        assert resp.status_code == 200
        d = resp.json()
        assert d["count"] == 2
        assert d["total"] == len(CATEGORIES)

        # 第二页
        resp2 = client.get("/api/feedback?limit=2&offset=2")
        assert resp2.status_code == 200
        assert resp2.json()["count"] == 2

        # offset 超出
        resp3 = client.get("/api/feedback?limit=10&offset=100")
        assert resp3.status_code == 200
        assert resp3.json()["count"] == 0


# ═══════════════════════════════════════════════════════════════════
# 反馈详情
# ═══════════════════════════════════════════════════════════════════

class TestDetail:
    """GET /api/feedback/{fid} — 反馈详情"""

    def test_detail_returns_full_data(self, client, sample_data):
        """返回完整字段"""
        fid = sample_data[0]["id"]
        resp = client.get(f"/api/feedback/{fid}")
        assert resp.status_code == 200
        d = resp.json()
        assert d["id"] == fid
        assert d["title"] == sample_data[0]["title"]
        assert d["category"] == sample_data[0]["category"]
        assert d["status"] == "new"
        assert d["comments"] == []
        assert "content" in d
        assert "created_at" in d
        assert "updated_at" in d

    def test_detail_not_found(self, client):
        """不存在返回 404"""
        resp = client.get("/api/feedback/FB_NONEXISTENT")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 状态更新
# ═══════════════════════════════════════════════════════════════════

class TestStatusUpdate:
    """PUT /api/feedback/{fid}/status — 状态更新"""

    def test_update_status(self, client, sample_data):
        """正常状态流转"""
        fid = sample_data[0]["id"]
        for new_status in ["acknowledged", "in_progress", "resolved"]:
            resp = client.put(f"/api/feedback/{fid}/status",
                              json={"status": new_status})
            assert resp.status_code == 200
            assert resp.json()["status"] == new_status

    def test_update_status_invalid(self, client, sample_data):
        """无效状态返回 422"""
        fid = sample_data[0]["id"]
        resp = client.put(f"/api/feedback/{fid}/status",
                          json={"status": "invalid_status"})
        assert resp.status_code == 422

    def test_update_status_not_found(self, client):
        """不存在返回 404"""
        resp = client.put("/api/feedback/FB_NONEXISTENT/status",
                          json={"status": "acknowledged"})
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 评论
# ═══════════════════════════════════════════════════════════════════

class TestComments:
    """POST /api/feedback/{fid}/comments — 评论"""

    def test_add_comment(self, client, sample_data):
        """正常添加评论"""
        fid = sample_data[0]["id"]
        resp = client.post(f"/api/feedback/{fid}/comments", json={
            "user": "测试者",
            "text": "这是一个测试评论",
        })
        assert resp.status_code == 200
        d = resp.json()
        assert len(d["comments"]) == 1
        assert d["comments"][0]["user"] == "测试者"
        assert d["comments"][0]["text"] == "这是一个测试评论"
        assert "id" in d["comments"][0]
        assert "created_at" in d["comments"][0]

    def test_add_multiple_comments(self, client, sample_data):
        """多条评论累积"""
        fid = sample_data[0]["id"]
        for i in range(3):
            resp = client.post(f"/api/feedback/{fid}/comments", json={
                "user": f"用户{i}",
                "text": f"第{i+1}条评论",
            })
            assert resp.status_code == 200
        # 详情应包含全部 3 条
        resp = client.get(f"/api/feedback/{fid}")
        assert len(resp.json()["comments"]) == 3

    def test_add_comment_empty_text_returns_422(self, client, sample_data):
        """评论内容为空返回 422"""
        fid = sample_data[0]["id"]
        resp = client.post(f"/api/feedback/{fid}/comments", json={
            "user": "测试者",
            "text": "",
        })
        assert resp.status_code == 422

    def test_add_comment_not_found(self, client):
        """不存在返回 404"""
        resp = client.post("/api/feedback/FB_NONEXISTENT/comments", json={
            "user": "tester",
            "text": "评论内容",
        })
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════════════

class TestDelete:
    """DELETE /api/feedback/{fid} — 删除反馈"""

    def test_delete_existing(self, client, sample_data):
        """删除存在的反馈"""
        fid = sample_data[0]["id"]
        resp = client.delete(f"/api/feedback/{fid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        # 确认已删除
        resp2 = client.get(f"/api/feedback/{fid}")
        assert resp2.status_code == 404

    def test_delete_nonexistent(self, client):
        """删除不存在的反馈"""
        resp = client.delete("/api/feedback/FB_NONEXISTENT")
        assert resp.status_code == 404

    def test_delete_updates_stats(self, client, sample_data):
        """删除后统计数据更新"""
        resp = client.get("/api/feedback/stats")
        assert resp.json()["total"] == len(CATEGORIES)

        fid = sample_data[0]["id"]
        client.delete(f"/api/feedback/{fid}")

        resp = client.get("/api/feedback/stats")
        assert resp.json()["total"] == len(CATEGORIES) - 1


# ═══════════════════════════════════════════════════════════════════
# 集成场景
# ═══════════════════════════════════════════════════════════════════

class TestIntegration:
    """完整业务流程测试"""

    def test_full_flow(self, client):
        """提交 → 查看 → 评论 → 状态更新 → 统计验证"""
        # 1) 提交反馈
        resp = client.post("/api/feedback", json={
            "title": "发现一个bug",
            "content": "在回测中收益率计算有误",
            "category": "bug",
            "user_name": "李四",
        })
        assert resp.status_code == 201
        fid = resp.json()["id"]

        # 2) 列表应包含
        resp = client.get("/api/feedback?category=bug")
        assert resp.json()["total"] == 1

        # 3) 查看详情
        resp = client.get(f"/api/feedback/{fid}")
        assert resp.json()["title"] == "发现一个bug"

        # 4) 添加评论
        resp = client.post(f"/api/feedback/{fid}/comments", json={
            "user": "管理员",
            "text": "已确认，正在修复中",
        })
        assert len(resp.json()["comments"]) == 1

        # 5) 更新状态
        resp = client.put(f"/api/feedback/{fid}/status",
                          json={"status": "acknowledged"})
        assert resp.json()["status"] == "acknowledged"

        # 6) 再次评论
        client.post(f"/api/feedback/{fid}/comments", json={
            "user": "李四",
            "text": "大概什么时候能修好？",
        })

        # 7) 状态推进
        client.put(f"/api/feedback/{fid}/status",
                   json={"status": "in_progress"})

        # 8) 查看完整详情
        resp = client.get(f"/api/feedback/{fid}")
        d = resp.json()
        assert d["status"] == "in_progress"
        assert len(d["comments"]) == 2

        # 9) 统计验证
        resp = client.get("/api/feedback/stats")
        stats = resp.json()
        assert stats["total"] == 1
        assert stats["by_status"]["in_progress"] == 1
        assert stats["by_category"]["bug"] == 1
