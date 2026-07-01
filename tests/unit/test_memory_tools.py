"""Unit tests for the bot's learned-memory navigation tools (P3a)."""

import json

from slack_aws_cost_guardian.llm.base import LLMToolCall
from slack_aws_cost_guardian.llm.tools.memory_tools import register_memory_tools
from slack_aws_cost_guardian.llm.tools.registry import ToolRegistry


class _FakeDeepStore:
    def __init__(self, concepts, index=""):
        self._concepts = concepts
        self._index = index

    def list_concept_paths(self):
        return list(self._concepts.keys())

    def read_all_concepts(self):
        return dict(self._concepts)

    def read_index(self):
        return self._index

    def read_concept(self, path):
        return self._concepts.get(path, "")


CONCEPTS = {
    "services/nat-gateway-baseline.md": "---\nid: nat\n---\n\nNAT baseline is accepted.",
    "patterns/month-end-spike.md": "---\nid: spike\n---\n\nMonth-end batch spike is normal.",
}


def _registry(concepts=CONCEPTS, index="# index\n- services/nat-gateway-baseline.md"):
    reg = ToolRegistry()
    register_memory_tools(reg, _FakeDeepStore(concepts, index))
    return reg


def _call(reg, name, **args):
    result = reg.execute(LLMToolCall(id="1", name=name, arguments=args))
    return json.loads(result.content), result.is_error


def test_registers_three_tools():
    reg = _registry()
    for name in ("list_memory", "search_memory", "read_memory_concept"):
        assert reg.has_tool(name)


def test_list_memory():
    out, err = _call(_registry(), "list_memory")
    assert err is False
    assert out["concept_count"] == 2
    assert "services/nat-gateway-baseline.md" in out["concepts"]
    assert "index" in out["index"]


def test_search_memory_matches_by_keyword():
    out, err = _call(_registry(), "search_memory", query="NAT")
    assert err is False
    assert out["match_count"] == 1
    assert out["matches"][0]["path"] == "services/nat-gateway-baseline.md"
    assert "NAT baseline" in out["matches"][0]["excerpt"]


def test_search_memory_matches_body_text():
    out, _ = _call(_registry(), "search_memory", query="batch spike")
    assert out["match_count"] == 1
    assert out["matches"][0]["path"] == "patterns/month-end-spike.md"


def test_search_memory_no_match():
    out, _ = _call(_registry(), "search_memory", query="kubernetes")
    assert out["match_count"] == 0


def test_read_memory_concept_found():
    out, err = _call(_registry(), "read_memory_concept", path="services/nat-gateway-baseline.md")
    assert err is False
    assert out["found"] is True
    assert "NAT baseline is accepted" in out["content"]


def test_read_memory_concept_missing():
    out, _ = _call(_registry(), "read_memory_concept", path="nope.md")
    assert out["found"] is False


def test_empty_memory_returns_gracefully():
    out, err = _call(_registry(concepts={}, index=""), "list_memory")
    assert err is False
    assert out["concept_count"] == 0
    assert out["concepts"] == []