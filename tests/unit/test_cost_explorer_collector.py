"""Tests for the Cost Explorer collector's credit/refund filtering.

AWS promotional credits post as negative Credit line items that every Cost
Explorer metric nets in. The collector filters the RECORD_TYPE dimension so
reported cost reflects gross (pre-credit) usage. These tests verify the filter
is attached to every get_cost_and_usage / get_cost_forecast call when enabled,
and omitted entirely when disabled.
"""

from datetime import date
from unittest.mock import MagicMock

from slack_aws_cost_guardian.collectors.aws_cost_explorer import CostExplorerCollector

EXPECTED_FILTER = {
    "Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit", "Refund"]}}
}


def _make_collector(exclude_credits: bool) -> tuple[CostExplorerCollector, MagicMock]:
    ce = MagicMock()
    # Empty-ish responses so the collector methods return without error.
    ce.get_cost_and_usage.return_value = {"ResultsByTime": []}
    ce.get_cost_forecast.return_value = {"Total": {"Amount": "0"}}
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    collector = CostExplorerCollector(
        exclude_credits=exclude_credits, ce_client=ce, sts_client=sts
    )
    return collector, ce


def test_record_type_filter_returns_filter_when_enabled():
    collector, _ = _make_collector(exclude_credits=True)
    assert collector._record_type_filter() == EXPECTED_FILTER


def test_record_type_filter_returns_none_when_disabled():
    collector, _ = _make_collector(exclude_credits=False)
    assert collector._record_type_filter() is None


def test_default_excludes_credits():
    # Primary deployment runs on credits — the flag must default on.
    collector = CostExplorerCollector(ce_client=MagicMock(), sts_client=MagicMock())
    assert collector.exclude_credits is True


def test_filter_applied_to_every_get_cost_and_usage_call():
    collector, ce = _make_collector(exclude_credits=True)

    collector._get_daily_costs(date(2026, 6, 1), date(2026, 6, 15))
    collector._get_cost_by_service(date(2026, 6, 1), date(2026, 6, 15))
    collector._get_cost_by_account(date(2026, 6, 1), date(2026, 6, 15))
    collector.get_cost_for_date(date(2026, 6, 1))

    assert ce.get_cost_and_usage.call_count == 4
    for call in ce.get_cost_and_usage.call_args_list:
        assert call.kwargs["Filter"] == EXPECTED_FILTER


def test_filter_omitted_when_disabled():
    collector, ce = _make_collector(exclude_credits=False)

    collector._get_daily_costs(date(2026, 6, 1), date(2026, 6, 15))
    collector.get_cost_for_date(date(2026, 6, 1))

    assert ce.get_cost_and_usage.call_count == 2
    for call in ce.get_cost_and_usage.call_args_list:
        assert "Filter" not in call.kwargs


def test_forecast_applies_filter_to_both_calls():
    collector, ce = _make_collector(exclude_credits=True)

    # Pick a mid-month target so the forecast isn't short-circuited by the
    # end-of-month guard. date.today() is used internally, so patch it.
    from slack_aws_cost_guardian.collectors import aws_cost_explorer as mod

    original_date = mod.date

    class _FixedDate(original_date):
        @classmethod
        def today(cls):
            return original_date(2026, 6, 10)

    mod.date = _FixedDate
    try:
        collector._get_forecast()
    finally:
        mod.date = original_date

    assert ce.get_cost_forecast.call_args.kwargs["Filter"] == EXPECTED_FILTER
    assert ce.get_cost_and_usage.call_args.kwargs["Filter"] == EXPECTED_FILTER