"""Unit tests for the P1 learning-memory curator."""

from types import SimpleNamespace

import pytest

from slack_aws_cost_guardian.analysis.curator import (
    MemoryCurator,
    _extract_json,
    summarize_changes,
    summarize_feedback,
)
from slack_aws_cost_guardian.llm.prompts import build_curator_prompt
from slack_aws_cost_guardian.storage.models import (
    AnomalyFeedback,
    ChangeLog,
    ChangeType,
    DurationType,
    FeedbackType,
)


def _feedback(**overrides) -> AnomalyFeedback:
    base = dict(
        alert_id="a1",
        date="2026-06-20",
        user_id="U1",
        user_name="dan",
        feedback_type=FeedbackType.EXPECTED,
        affected_services=["NATGateway"],
        cost_impact=42.0,
        explanation="known baseline, ignore",
        duration_type=DurationType.ONGOING,
        timestamp="2026-06-20T10:00:00Z",
    )
    base.update(overrides)
    return AnomalyFeedback(**base)


def _change(**overrides) -> ChangeLog:
    base = dict(
        service="AmazonRDS",
        date="2026-06-21",
        change_type=ChangeType.COST_INCREASE,
        description="new read replica",
        baseline_cost=100.0,
        new_cost=140.0,
        percent_change=40.0,
        acknowledged_by="U1",
        acknowledged_at="2026-06-21T09:00:00Z",
    )
    base.update(overrides)
    return ChangeLog(**base)


# ---------------------------------------------------------------------------
# Summaries + JSON extraction
# ---------------------------------------------------------------------------


def test_summarize_feedback_includes_key_fields():
    out = summarize_feedback([_feedback()])
    assert "expected" in out
    assert "NATGateway" in out
    assert "known baseline" in out
    assert "42.00" in out


def test_summaries_empty_when_no_items():
    assert summarize_feedback([]) == ""
    assert summarize_changes([]) == ""


def test_summarize_changes_includes_key_fields():
    out = summarize_changes([_change()])
    assert "cost_increase" in out
    assert "AmazonRDS" in out
    assert "+40%" in out


def test_curator_prompt_embeds_current_hot_and_signal():
    prompt = build_curator_prompt(
        feedback_summary="- [expected] NATGateway: ignore",
        changes_summary="",
        current_hot_memory="existing memory line",
    )
    assert "existing memory line" in prompt
    assert "NATGateway" in prompt
    assert "no acknowledged changes" in prompt.lower()


@pytest.mark.parametrize(
    "raw",
    [
        '{"hot_memory_text": "x", "notes": "n"}',
        '```json\n{"hot_memory_text": "x", "notes": "n"}\n```',
        'Sure, here you go:\n{"hot_memory_text": "x", "notes": "n"}\nDone.',
    ],
)
def test_extract_json_tolerates_wrapping(raw):
    parsed = _extract_json(raw)
    assert parsed == {"hot_memory_text": "x", "notes": "n"}


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("not json at all") is None
    assert _extract_json("") is None


# ---------------------------------------------------------------------------
# MemoryCurator.run
# ---------------------------------------------------------------------------


class _FakeStorage:
    def __init__(self, feedback=None, changes=None, hot="", last_curated_at=None):
        self._feedback = feedback or []
        self._changes = changes or []
        self.hot = hot
        self.last_curated_at = last_curated_at
        self.put_calls = []

    def get_recent_feedback(self, days=30):
        return list(self._feedback)

    def get_active_changes(self):
        return list(self._changes)

    def get_hot_memory(self):
        return self.hot

    def put_hot_memory(self, text):
        self.put_calls.append(text)
        self.hot = text

    def get_last_curated_at(self):
        return self.last_curated_at

    def set_last_curated_at(self, timestamp):
        self.last_curated_at = timestamp

    def bump_memory_version(self):
        self.version = getattr(self, "version", 0) + 1
        return self.version


class _FakeDeepStore:
    def __init__(self, index="", concepts=None):
        self.index = index
        self.concepts = concepts or {}
        self.writes = {}
        self.index_writes = []

    def read_index(self):
        return self.index

    def read_all_concepts(self):
        return dict(self.concepts)

    def write_concept(self, path, content):
        if not path or ".." in path.split("/") or path.startswith("/"):
            return False
        self.writes[path] = content
        return True

    def write_index(self, content):
        self.index = content
        self.index_writes.append(content)


class _FakeLLM:
    def __init__(self, content=None, raises=False):
        self._content = content
        self._raises = raises
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return SimpleNamespace(content=self._content, usage={})


def test_run_no_signal_skips_llm_and_write():
    storage = _FakeStorage(feedback=[], changes=[], hot="prior")
    llm = _FakeLLM(content="unused")
    result = MemoryCurator(storage, llm).run()
    assert result["changed"] is False
    assert result["reason"] == "no_signal"
    assert llm.calls == 0
    assert storage.put_calls == []


def test_run_writes_new_hot_memory():
    storage = _FakeStorage(feedback=[_feedback()], hot="old memory")
    llm = _FakeLLM(content='{"hot_memory_text": "NAT baseline accepted", "notes": "folded feedback"}')
    result = MemoryCurator(storage, llm).run()
    assert result["changed"] is True
    assert result["notes"] == "folded feedback"
    assert storage.put_calls == ["NAT baseline accepted"]
    assert storage.hot == "NAT baseline accepted"


def test_run_dry_run_does_not_write():
    storage = _FakeStorage(feedback=[_feedback()], hot="old")
    llm = _FakeLLM(content='{"hot_memory_text": "new", "notes": "n"}')
    result = MemoryCurator(storage, llm).run(dry_run=True)
    assert result["changed"] is True
    assert result["new_chars"] == len("new")
    assert storage.put_calls == []  # nothing persisted


def test_run_null_hot_leaves_unchanged():
    storage = _FakeStorage(feedback=[_feedback()], hot="keep me")
    llm = _FakeLLM(content='{"hot_memory_text": null, "notes": "no durable change"}')
    result = MemoryCurator(storage, llm).run()
    assert result["changed"] is False
    assert result["reason"] == "left_unchanged"
    assert storage.put_calls == []


def test_run_identical_text_is_no_change():
    storage = _FakeStorage(feedback=[_feedback()], hot="same")
    llm = _FakeLLM(content='{"hot_memory_text": "same", "notes": ""}')
    result = MemoryCurator(storage, llm).run()
    assert result["changed"] is False
    assert result["reason"] == "no_change"
    assert storage.put_calls == []


def test_run_unparseable_response_is_safe():
    storage = _FakeStorage(feedback=[_feedback()], hot="prior")
    llm = _FakeLLM(content="the model rambled without JSON")
    result = MemoryCurator(storage, llm).run()
    assert result["changed"] is False
    assert result["reason"] == "unparseable_response"
    assert storage.put_calls == []


def test_run_llm_error_degrades_gracefully():
    storage = _FakeStorage(feedback=[_feedback()], hot="prior")
    llm = _FakeLLM(raises=True)
    result = MemoryCurator(storage, llm).run()
    assert result["changed"] is False
    assert result["reason"] == "llm_error"
    assert storage.put_calls == []


# ---------------------------------------------------------------------------
# Watermark gate
# ---------------------------------------------------------------------------


def test_gate_skips_when_no_signal_newer_than_watermark():
    # Feedback timestamp equals the watermark -> nothing new to consolidate.
    fb = _feedback(timestamp="2026-06-20T10:00:00Z")
    storage = _FakeStorage(feedback=[fb], hot="prior", last_curated_at="2026-06-20T10:00:00Z")
    llm = _FakeLLM(content='{"hot_memory_text": "x", "notes": "n"}')
    result = MemoryCurator(storage, llm).run()
    assert result["changed"] is False
    assert result["reason"] == "no_new_signal"
    assert llm.calls == 0
    assert storage.put_calls == []


def test_gate_runs_when_signal_newer_than_watermark():
    fb = _feedback(timestamp="2026-06-21T09:00:00Z")
    storage = _FakeStorage(feedback=[fb], hot="prior", last_curated_at="2026-06-20T10:00:00Z")
    llm = _FakeLLM(content='{"hot_memory_text": "updated", "notes": "n"}')
    result = MemoryCurator(storage, llm).run()
    assert result["changed"] is True
    assert llm.calls == 1


def test_force_bypasses_gate():
    fb = _feedback(timestamp="2026-06-20T10:00:00Z")
    storage = _FakeStorage(feedback=[fb], hot="prior", last_curated_at="2026-06-20T10:00:00Z")
    llm = _FakeLLM(content='{"hot_memory_text": "forced", "notes": "n"}')
    result = MemoryCurator(storage, llm).run(force=True)
    assert result["changed"] is True
    assert llm.calls == 1


def test_watermark_advances_after_successful_pass():
    fb = _feedback(timestamp="2026-06-22T08:00:00Z")
    storage = _FakeStorage(feedback=[fb], hot="old")
    llm = _FakeLLM(content='{"hot_memory_text": "new", "notes": "n"}')
    MemoryCurator(storage, llm).run()
    assert storage.last_curated_at == "2026-06-22T08:00:00Z"


def test_watermark_not_advanced_on_dry_run():
    fb = _feedback(timestamp="2026-06-22T08:00:00Z")
    storage = _FakeStorage(feedback=[fb], hot="old")
    llm = _FakeLLM(content='{"hot_memory_text": "new", "notes": "n"}')
    MemoryCurator(storage, llm).run(dry_run=True)
    assert storage.last_curated_at is None


def test_watermark_not_advanced_on_llm_error():
    fb = _feedback(timestamp="2026-06-22T08:00:00Z")
    storage = _FakeStorage(feedback=[fb], hot="old")
    llm = _FakeLLM(raises=True)
    MemoryCurator(storage, llm).run()
    assert storage.last_curated_at is None


# ---------------------------------------------------------------------------
# Deep memory (P2)
# ---------------------------------------------------------------------------

_DEEP_RESPONSE = """{
  "hot_memory_text": "NAT baseline accepted",
  "concept_writes": [
    {"path": "services/nat-gateway-baseline.md", "action": "create",
     "frontmatter": {"id": "nat-gateway-baseline", "type": "service"},
     "body": "NAT baseline is accepted.\\n\\n**Why:** user feedback."}
  ],
  "index_md": "# Deep memory index\\n- services/nat-gateway-baseline.md",
  "notes": "filed NAT baseline"
}"""


def test_deep_writes_concept_and_index_and_bumps_version():
    storage = _FakeStorage(feedback=[_feedback()], hot="old")
    deep = _FakeDeepStore()
    llm = _FakeLLM(content=_DEEP_RESPONSE)
    result = MemoryCurator(storage, llm, deep_store=deep).run()

    assert "services/nat-gateway-baseline.md" in deep.writes
    assert "id: nat-gateway-baseline" in deep.writes["services/nat-gateway-baseline.md"]
    assert "services/nat-gateway-baseline.md" in deep.index
    assert result["concepts_written"] == 1
    assert result["index_updated"] is True
    assert result["memory_version"] == 1  # bumped once


def test_deep_dry_run_writes_nothing():
    storage = _FakeStorage(feedback=[_feedback()], hot="old")
    deep = _FakeDeepStore()
    llm = _FakeLLM(content=_DEEP_RESPONSE)
    result = MemoryCurator(storage, llm, deep_store=deep).run(dry_run=True)

    assert deep.writes == {}
    assert deep.index_writes == []
    assert result["concept_writes_proposed"] == 1


def test_no_deep_store_ignores_concept_writes():
    storage = _FakeStorage(feedback=[_feedback()], hot="old")
    llm = _FakeLLM(content=_DEEP_RESPONSE)
    result = MemoryCurator(storage, llm).run()  # no deep_store
    # Hot still updated, deep proposals counted but not applied.
    assert result["changed"] is True
    assert result["concept_writes_proposed"] == 1
    assert "concepts_written" not in result


def test_deep_unsafe_path_skipped():
    storage = _FakeStorage(feedback=[_feedback()], hot="old")
    deep = _FakeDeepStore()
    bad = _DEEP_RESPONSE.replace(
        "services/nat-gateway-baseline.md", "../escape.md"
    )
    llm = _FakeLLM(content=bad)
    result = MemoryCurator(storage, llm, deep_store=deep).run()
    assert deep.writes == {}
    assert result["concepts_written"] == 0
    assert result["concepts_skipped"] == 1