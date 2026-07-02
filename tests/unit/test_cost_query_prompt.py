"""Tests for the cost-query system prompt date anchor.

The tools only resolve concrete dates, so the model must translate relative
periods ("last month", "June") into concrete dates itself. Without a current-date
anchor it falls back to a training-data year and picks the wrong year. The prompt
builder prepends today's date so relative references resolve correctly.
"""

from datetime import date

from slack_aws_cost_guardian.llm.tools.schemas import (
    COST_QUERY_SYSTEM_PROMPT,
    build_cost_query_system_prompt,
)


def test_prompt_prepends_current_date():
    prompt = build_cost_query_system_prompt(date(2026, 7, 1))
    assert "Today's date is 2026-07-01 (UTC)." in prompt
    # The base prompt is preserved after the anchor.
    assert COST_QUERY_SYSTEM_PROMPT in prompt


def test_prompt_instructs_deriving_year_from_today():
    prompt = build_cost_query_system_prompt(date(2026, 7, 1))
    assert "Never assume a year" in prompt


def test_prompt_defaults_to_today_when_omitted():
    prompt = build_cost_query_system_prompt()
    assert f"Today's date is {date.today().isoformat()} (UTC)." in prompt