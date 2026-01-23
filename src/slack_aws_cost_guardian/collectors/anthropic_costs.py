"""Anthropic API cost collector using the Admin Cost API.

Requires an Anthropic Organization account and Admin API key.
See: https://platform.claude.com/docs/en/build-with-claude/usage-cost-api
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx

from slack_aws_cost_guardian.collectors.base import (
    CostCollector,
    CostData,
    DailyCost,
)

logger = logging.getLogger(__name__)

ANTHROPIC_COST_API_URL = "https://api.anthropic.com/v1/organizations/cost_report"
ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicCostCollector(CostCollector):
    """Collector for Anthropic Claude API costs.

    Uses the Anthropic Admin Cost API to retrieve organization-level
    cost data. Requires an Admin API key (sk-ant-admin-...).
    """

    collector_name = "anthropic"

    def __init__(self, admin_api_key: str, timeout: float = 30.0):
        """Initialize the Anthropic cost collector.

        Args:
            admin_api_key: Anthropic Admin API key (sk-ant-admin-...)
            timeout: HTTP request timeout in seconds
        """
        self._admin_api_key = admin_api_key
        self._client = httpx.Client(timeout=timeout)

    def collect(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        lookback_days: int = 14,
    ) -> CostData:
        """Collect Anthropic API costs for the specified period.

        Args:
            start_date: Start of collection period (defaults to yesterday)
            end_date: End of collection period (defaults to today)
            lookback_days: Days to look back for daily_costs trend data

        Returns:
            CostData with Anthropic costs
        """
        # Default to yesterday's costs (matches AWS pattern)
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=1)

        collection_timestamp = datetime.now(UTC).isoformat() + "Z"

        logger.info(
            f"Collecting Anthropic costs from {start_date.isoformat()} "
            f"to {end_date.isoformat()}"
        )

        try:
            # Get yesterday's costs for snapshot (single day, like AWS)
            yesterday = date.today() - timedelta(days=1)
            cost_data = self._fetch_costs_for_day(yesterday)

            # Get lookback period for trend analysis
            lookback_start = end_date - timedelta(days=lookback_days)
            daily_costs = self._fetch_daily_costs(lookback_start, end_date)

            # Calculate average and trend
            total_lookback = sum(dc.cost for dc in daily_costs)
            average_daily = total_lookback / len(daily_costs) if daily_costs else 0
            trend = self._calculate_trend(daily_costs)

            return CostData(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                collection_timestamp=collection_timestamp,
                account_id="anthropic",  # Use provider as account_id
                total_cost=round(cost_data["total_cost"], 2),
                currency="USD",
                cost_by_service=cost_data["cost_by_service"],
                daily_costs=daily_costs,
                forecast=None,  # Anthropic doesn't provide forecasts
                trend=trend,
                average_daily_cost=round(average_daily, 2),
            )

        except Exception as e:
            logger.error(f"Failed to collect Anthropic costs: {e}")
            # Return empty data on failure (graceful degradation)
            return CostData(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                collection_timestamp=collection_timestamp,
                account_id="anthropic",
                total_cost=0.0,
                currency="USD",
                cost_by_service={},
                daily_costs=[],
                forecast=None,
                trend="unknown",
                average_daily_cost=0.0,
            )

    def _fetch_costs_for_day(self, target_date: date) -> dict:
        """Fetch costs for a single day.

        Args:
            target_date: The date to fetch costs for

        Returns:
            Dict with total_cost and cost_by_service
        """
        next_day = target_date + timedelta(days=1)

        params = {
            "starting_at": f"{target_date.isoformat()}T00:00:00Z",
            "ending_at": f"{next_day.isoformat()}T00:00:00Z",
        }

        headers = {
            "anthropic-version": ANTHROPIC_API_VERSION,
            "x-api-key": self._admin_api_key,
        }

        response = self._client.get(
            ANTHROPIC_COST_API_URL,
            params=params,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        # Parse cost data - amount is in CENTS as decimal string
        total_cost = Decimal("0")
        cost_by_service: dict[str, float] = {}

        for bucket in data.get("data", []):
            for item in bucket.get("results", []):
                # Amount is in cents - convert to dollars
                cost_cents = Decimal(str(item.get("amount", "0")))
                cost_dollars = cost_cents / Decimal("100")

                if cost_dollars >= Decimal("0.005"):  # Filter negligible costs (half cent)
                    # Use description, model, or fallback to "API Usage"
                    description = (
                        item.get("description")
                        or item.get("model")
                        or "API Usage"
                    )
                    # Prefix with Claude:: to identify as Anthropic service
                    service_name = f"Claude::{description}"

                    # Accumulate if same service appears multiple times
                    if service_name in cost_by_service:
                        cost_by_service[service_name] += float(cost_dollars)
                    else:
                        cost_by_service[service_name] = float(cost_dollars)
                    total_cost += cost_dollars

        return {
            "total_cost": float(total_cost),
            "cost_by_service": cost_by_service,
        }

    def _fetch_daily_costs(
        self, start_date: date, end_date: date
    ) -> list[DailyCost]:
        """Fetch daily cost breakdown for trend analysis.

        Args:
            start_date: Start of the period
            end_date: End of the period

        Returns:
            List of DailyCost objects
        """
        base_params = {
            "starting_at": f"{start_date.isoformat()}T00:00:00Z",
            "ending_at": f"{end_date.isoformat()}T00:00:00Z",
        }

        headers = {
            "anthropic-version": ANTHROPIC_API_VERSION,
            "x-api-key": self._admin_api_key,
        }

        # Aggregate daily costs across all pages
        daily_totals: dict[str, Decimal] = {}
        next_page = None

        while True:
            params = dict(base_params)
            if next_page:
                params["page"] = next_page

            response = self._client.get(
                ANTHROPIC_COST_API_URL,
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            for bucket in data.get("data", []):
                # Field is "starting_at" not "bucket_start_time"
                bucket_date = bucket.get("starting_at", "")[:10]  # YYYY-MM-DD
                if not bucket_date:
                    continue

                # Amount is in CENTS - convert to dollars
                total_cents = sum(
                    Decimal(str(item.get("amount", "0")))
                    for item in bucket.get("results", [])
                )
                total_dollars = total_cents / Decimal("100")

                if bucket_date in daily_totals:
                    daily_totals[bucket_date] += total_dollars
                else:
                    daily_totals[bucket_date] = total_dollars

            # Check for more pages
            if data.get("has_more") and data.get("next_page"):
                next_page = data["next_page"]
            else:
                break

        daily_costs = [
            DailyCost(date=d, cost=round(float(c), 4))
            for d, c in daily_totals.items()
        ]
        return sorted(daily_costs, key=lambda x: x.date)

    def _calculate_trend(self, daily_costs: list[DailyCost]) -> str:
        """Calculate cost trend from daily costs.

        Compares first half to second half of the period.
        """
        if len(daily_costs) < 2:
            return "unknown"

        mid = len(daily_costs) // 2
        first_half = sum(dc.cost for dc in daily_costs[:mid])
        second_half = sum(dc.cost for dc in daily_costs[mid:])

        # Normalize for different period lengths
        first_avg = first_half / mid if mid > 0 else 0
        second_avg = second_half / (len(daily_costs) - mid) if (len(daily_costs) - mid) > 0 else 0

        if first_avg == 0:
            return "unknown"

        change_pct = (second_avg - first_avg) / first_avg * 100

        if change_pct > 10:
            return "increasing"
        elif change_pct < -10:
            return "decreasing"
        else:
            return "stable"

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False