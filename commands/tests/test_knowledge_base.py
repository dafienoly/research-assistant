"""Knowledge Base 单元测试"""

import os, sys, json, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from factor_lab.research_skill.knowledge_base import (
    KnowledgeBase, KnowledgeEntry, VALID_KINDS,
    cmd_knowledge_list, cmd_knowledge_add, cmd_knowledge_search, cmd_knowledge_stats,
)


@pytest.fixture
def kb():
    """使用临时目录创建 KnowledgeBase"""
    tmp = tempfile.mkdtemp()
    kb = KnowledgeBase(root=tmp)
    yield kb
    shutil.rmtree(tmp)


class TestKnowledgeEntry:
    def test_create_entry(self):
        e = KnowledgeEntry(kind="finding", title="测试", hypothesis="h1", conclusion="c1")
        assert e.kind == "finding"
        assert e.confidence == 0.5

    def test_to_dict_roundtrip(self):
        e = KnowledgeEntry(kind="rule", title="T1", hypothesis="h1", conclusion="c1",
                          tags=["a", "b"], confidence=0.8)
        d = e.to_dict()
        e2 = KnowledgeEntry.from_dict(d)
        assert e2.title == e.title
        assert e2.tags == e.tags
        assert e2.confidence == e.confidence


class TestKnowledgeBase:
    def test_empty_kb(self, kb):
        assert kb.stats()["total"] == 0

    def test_add_entry(self, kb):
        eid = kb.add_entry(KnowledgeEntry(
            kind="finding", title="FT1", hypothesis="fh1", conclusion="fc1"
        ))
        assert eid.startswith("k_")
        assert kb.stats()["total"] == 1

    def test_add_rule(self, kb):
        eid = kb.add_entry(KnowledgeEntry(
            kind="rule", title="R1", hypothesis="rh1", conclusion="rc1"
        ))
        entry = kb.get_entry(eid)
        assert entry is not None
        assert entry.kind == "rule"

    def test_add_failure(self, kb):
        eid = kb.add_entry(KnowledgeEntry(
            kind="failure", title="F1", hypothesis="fh1", conclusion="fc1"
        ))
        entry = kb.get_entry(eid)
        assert entry is not None
        assert entry.kind == "failure"

    def test_invalid_kind(self, kb):
        with pytest.raises(ValueError):
            kb.add_entry(KnowledgeEntry(kind="invalid", title="X", hypothesis="h", conclusion="c"))

    def test_get_nonexistent(self, kb):
        assert kb.get_entry("nonexistent") is None

    def test_list_entries(self, kb):
        kb.add_entry(KnowledgeEntry(kind="finding", title="F1", hypothesis="h1", conclusion="c1"))
        kb.add_entry(KnowledgeEntry(kind="rule", title="R1", hypothesis="h2", conclusion="c2"))
        all_entries = kb.list_entries()
        assert len(all_entries) == 2
        findings = kb.list_entries(kind="finding")
        assert len(findings) == 1
        assert findings[0]["kind"] == "finding"

    def test_update_entry(self, kb):
        eid = kb.add_entry(KnowledgeEntry(kind="finding", title="F1", hypothesis="h1", conclusion="c1"))
        entry = kb.get_entry(eid)
        entry.conclusion = "updated"
        assert kb.update_entry(entry)
        updated = kb.get_entry(eid)
        assert updated.conclusion == "updated"

    def test_delete_entry(self, kb):
        eid = kb.add_entry(KnowledgeEntry(kind="finding", title="F1", hypothesis="h1", conclusion="c1"))
        assert kb.delete_entry(eid)
        assert kb.get_entry(eid) is None

    def test_search(self, kb):
        kb.add_entry(KnowledgeEntry(kind="finding", title="动量反转", hypothesis="短期动量反转有效",
                                     conclusion="验证有效", tags=["momentum"]))
        kb.add_entry(KnowledgeEntry(kind="rule", title="量价规则", hypothesis="放量突破",
                                     conclusion="需配合确认", tags=["volume"]))
        results = kb.search("动量")
        assert len(results) == 1
        assert "动量" in results[0]["title"]

    def test_search_by_tag(self, kb):
        kb.add_entry(KnowledgeEntry(kind="finding", title="VWAP", hypothesis="vwap策略",
                                     conclusion="有效", tags=["vwap"]))
        results = kb.search("vwap")
        assert len(results) == 1

    def test_duplicate_hypothesis(self, kb):
        eid = kb.add_entry(KnowledgeEntry(kind="finding", title="T1", hypothesis="同假设测试",
                                           conclusion="c1"))
        dup = kb.check_duplicate_hypothesis("同假设测试")
        assert dup is not None
        assert dup["entry_id"] == eid

    def test_duplicate_expression(self, kb):
        kb.add_entry(KnowledgeEntry(kind="finding", title="T1", hypothesis="h1",
                                     conclusion="c1", evidence="rank(close/ts_mean(close,20))"))
        dup = kb.check_duplicate_expression("rank(close / ts_mean(close, 20))")
        assert dup is not None

    def test_persistence(self, kb):
        """验证文件系统持久化"""
        eid = kb.add_entry(KnowledgeEntry(kind="finding", title="Persist", hypothesis="ph1",
                                           conclusion="pc1"))
        # 重建 KnowledgeBase 应能读到之前保存的条目
        kb2 = KnowledgeBase(root=str(kb.root))
        entry = kb2.get_entry(eid)
        assert entry is not None
        assert entry.title == "Persist"

    def test_stats(self, kb):
        kb.add_entry(KnowledgeEntry(kind="finding", title="F1", hypothesis="h1", conclusion="c1"))
        kb.add_entry(KnowledgeEntry(kind="rule", title="R1", hypothesis="h2", conclusion="c2"))
        kb.add_entry(KnowledgeEntry(kind="failure", title="X1", hypothesis="h3", conclusion="c3"))
        s = kb.stats()
        assert s["rules"] == 1
        assert s["findings"] == 1
        assert s["failures"] == 1
        assert s["total"] == 3

    def test_index_update_on_add(self, kb):
        """验证添加条目后 INDEX.md 自动更新"""
        kb.add_entry(KnowledgeEntry(kind="finding", title="Index测试", hypothesis="ih1",
                                     conclusion="ic1"))
        index_content = (kb.root / "INDEX.md").read_text()
        assert "Index测试" in index_content


class TestCLICommands:
    # CLI commands use real filesystem; tested manually.
    # Core KnowledgeBase logic is covered by TestKnowledgeBase above.
    pass
