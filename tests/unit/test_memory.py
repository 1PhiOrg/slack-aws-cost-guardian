"""Unit tests for learning-memory P0: hot-memory storage and prompt injection."""

import pytest

from slack_aws_cost_guardian.llm.prompts import build_anomaly_analysis_prompt
from slack_aws_cost_guardian.storage.dynamodb import DynamoDBStorage


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

ANOMALY = {
    "service": "Amazon EC2",
    "current_cost": 150.0,
    "baseline_cost": 100.0,
    "absolute_change": 50.0,
    "percent_change": 50.0,
    "severity": "warning",
}


def test_prompt_omits_memory_block_when_empty():
    prompt = build_anomaly_analysis_prompt(
        anomaly_data=ANOMALY,
        historical_context="no notable history",
        user_context="prod account",
    )
    assert "Learned Memory" not in prompt
    # The core sections are still present.
    assert "Anomaly Details" in prompt
    assert "prod account" in prompt


def test_prompt_omits_memory_block_for_whitespace_only():
    prompt = build_anomaly_analysis_prompt(
        anomaly_data=ANOMALY,
        historical_context="",
        user_context="prod account",
        hot_memory="   \n  ",
    )
    assert "Learned Memory" not in prompt


def test_prompt_includes_memory_block_when_present():
    hot = "NAT Gateway baseline in prod is accepted; do not re-flag."
    prompt = build_anomaly_analysis_prompt(
        anomaly_data=ANOMALY,
        historical_context="",
        user_context="prod account",
        hot_memory=hot,
    )
    assert "Learned Memory" in prompt
    assert "OVERRIDES" in prompt
    assert hot in prompt
    # Memory is injected after the environment context, before the questions.
    assert prompt.index("prod account") < prompt.index(hot) < prompt.index("Provide:")


# ---------------------------------------------------------------------------
# Storage: hot memory + version pointer
# ---------------------------------------------------------------------------


class _FakeTable:
    """Minimal in-memory stand-in for a boto3 DynamoDB Table."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    @staticmethod
    def _key(d: dict) -> tuple[str, str]:
        return (d["PK"], d["SK"])

    def get_item(self, Key):  # noqa: N803 (boto3 casing)
        item = self.items.get(self._key(Key))
        return {"Item": item} if item is not None else {}

    def put_item(self, Item):  # noqa: N803
        self.items[self._key(Item)] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ReturnValues=None):  # noqa: N803
        item = self.items.setdefault(self._key(Key), dict(Key))
        if "version = if_not_exists(version, :zero) + :one" in UpdateExpression:
            current = item.get("version", ExpressionAttributeValues[":zero"])
            item["version"] = current + ExpressionAttributeValues[":one"]
            return {"Attributes": {"version": item["version"]}}
        if "SET last_curated_at = :ts" in UpdateExpression:
            item["last_curated_at"] = ExpressionAttributeValues[":ts"]
            return {}
        raise AssertionError(f"unexpected UpdateExpression: {UpdateExpression}")


class _FakeResource:
    def __init__(self, table):
        self._table = table

    def Table(self, name):  # noqa: N802 (boto3 casing)
        return self._table


@pytest.fixture
def storage():
    return DynamoDBStorage("test-table", dynamodb_resource=_FakeResource(_FakeTable()))


def test_hot_memory_defaults_to_empty(storage):
    assert storage.get_hot_memory() == ""


def test_hot_memory_round_trip(storage):
    storage.put_hot_memory("prod NAT baseline is accepted")
    assert storage.get_hot_memory() == "prod NAT baseline is accepted"


def test_hot_memory_overwrites(storage):
    storage.put_hot_memory("first")
    storage.put_hot_memory("second")
    assert storage.get_hot_memory() == "second"


def test_memory_version_defaults_to_zero(storage):
    assert storage.get_memory_version() == 0


def test_memory_version_bumps_monotonically(storage):
    assert storage.bump_memory_version() == 1
    assert storage.bump_memory_version() == 2
    assert storage.get_memory_version() == 2


def test_last_curated_at_defaults_to_none(storage):
    assert storage.get_last_curated_at() is None


def test_last_curated_at_round_trip(storage):
    storage.set_last_curated_at("2026-06-22T08:00:00Z")
    assert storage.get_last_curated_at() == "2026-06-22T08:00:00Z"


def test_watermark_survives_hot_memory_write(storage):
    # put_hot_memory replaces the item, but the curator writes hot then advances
    # the watermark - verify a subsequent set survives alongside the text.
    storage.put_hot_memory("some memory")
    storage.set_last_curated_at("2026-06-22T08:00:00Z")
    assert storage.get_hot_memory() == "some memory"
    assert storage.get_last_curated_at() == "2026-06-22T08:00:00Z"