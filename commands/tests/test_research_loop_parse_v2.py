"""Research Loop Phase 1 解析器增强测试"""

import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from factor_lab.research_loop import ResearchLoop, ResearchConfig


# 所有测试共享一个 light loop 实例
@pytest.fixture
def loop():
    return ResearchLoop(config=ResearchConfig(max_rounds=1))


class TestParseCandidatesV2:
    """测试 _parse_llm_candidates 多格式兼容"""

    def test_pipe_format(self, loop):
        """标准格式: 表达式 | 名称 | 假设"""
        resp = "rank(close/ts_mean(close,20)) | mom_20 | 20日动量"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 1
        assert r[0]["name"] == "mom_20"

    def test_bare_expression(self, loop):
        """裸表达式: 直接写表达式"""
        resp = "rank(close / ts_mean(close, 20))"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 1
        assert r[0]["expression"] == "rank(close / ts_mean(close, 20))"

    def test_equals_assignment(self, loop):
        """等号赋值: name = expression"""
        resp = "mom_20 = rank(close / ts_mean(close, 20))"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 1
        assert r[0]["name"] == "mom_20"
        assert "rank" in r[0]["expression"]

    def test_equals_with_spaces(self, loop):
        """等号赋值带空格"""
        resp = "momentum_5d = rank(ts_delta(close, 5) / ts_shift(close, 5))"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 1
        assert r[0]["name"] == "momentum_5d"

    def test_bullet_list(self, loop):
        """列表项: - 表达式"""
        resp = "- rank(close / ts_mean(close, 20))\n- rank(volume / ts_mean(volume, 20))"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 2

    def test_numbered_list(self, loop):
        """编号列表: 1. 表达式"""
        resp = "1. rank(close / ts_mean(close, 20))\n2. rank(volume / ts_mean(volume, 20))"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 2

    def test_inline_comment(self, loop):
        """行内注释: 表达式 # 注释"""
        resp = "rank(close/ts_mean(close,20)) # 20日动量因子"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 1

    def test_code_fence(self, loop):
        """代码围栏: 内容在 ``` 内部"""
        resp = "```\nrank(close/ts_mean(close,20)) | mom_20 | 20日动量\n```"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 1

    def test_json_format(self, loop):
        """JSON 数组格式"""
        resp = json.dumps([
            {"expression": "rank(close/ts_mean(close,20))", "name": "mom_20", "hypothesis": "20日动量"},
            {"expression": "rank(volume/ts_mean(volume,20))", "name": "vol_20", "hypothesis": "量能"},
        ])
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 2
        assert r[0]["name"] == "mom_20"

    def test_mixed_formats(self, loop):
        """混合多种格式在同一响应中"""
        resp = """Here are some factor ideas:

1. rank(close / ts_mean(close, 20))  # Simple momentum
momentum_5d = rank(ts_delta(close, 5) / ts_shift(close, 5))
- rank(volume / ts_mean(volume, 20))

Final recommendation: rank(ts_corr(close, volume, 20))
"""
        r = loop._parse_llm_candidates(resp)
        assert len(r) >= 3  # should pick up the valid ones

    def test_natural_language_with_expressions(self, loop):
        """自然语言夹杂表达式（模拟第 2 轮失败的场景）"""
        resp = """Based on my analysis, I recommend these factors:

For momentum strategies, the best approach is rank(close / ts_mean(close, 20)).
For reversal, try -rank(ts_delta(close, 5) / ts_shift(close, 5)).
Volume-based: rank(volume / ts_mean(volume, 20)) works well.

Let me know if you need more details."""
        r = loop._parse_llm_candidates(resp)
        assert len(r) >= 3  # should extract all three expressions

    def test_dedup(self, loop):
        """重复表达式去重"""
        resp = "rank(close/ts_mean(close,20)) | a | test\nrank(close/ts_mean(close,20)) | b | dup"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 1  # only unique

    def test_empty_response(self, loop):
        assert loop._parse_llm_candidates("") == []

    def test_invalid_expressions_skipped(self, loop):
        """无效表达式自动跳过"""
        resp = "this is not a valid expression\nrank(close / ts_mean(close, 20))\nbroken syntax {{{"
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 1
        assert "rank" in r[0]["expression"]

    def test_no_false_positives(self, loop):
        """自然语言不含表达式时不应产生候选"""
        resp = "I think we should try some momentum factors today."
        r = loop._parse_llm_candidates(resp)
        assert len(r) == 0
