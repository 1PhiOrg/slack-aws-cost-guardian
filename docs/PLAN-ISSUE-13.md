# Implementation Plan: Issue #13 - Claude API Cost Integration

## Overview

Integrate Anthropic Claude API cost reporting into the Slack AWS Cost Guardian. The system will collect costs from the Anthropic Cost API alongside AWS costs, enabling unified cost monitoring and anomaly detection across multiple cloud services.

**Goal**: Report Claude API costs in daily/weekly summaries and detect anomalies, while architecting for future services (Databricks, OpenAI, etc.).

## References

- [Anthropic Usage and Cost API Documentation](https://platform.claude.com/docs/en/build-with-claude/usage-cost-api)
- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- Issue #13: https://github.com/danjamk/slack-aws-cost-guardian/issues/13

---

## Prerequisites

### Anthropic Organization Account Required

The Anthropic Admin API (used for cost collection) is **unavailable for individual accounts**. You must have an organization account to use this feature.

**To set up an organization:**
1. Go to [Anthropic Console](https://console.anthropic.com) → Settings → Organization
2. Create a new organization (or join an existing one)
3. Ensure you have the **admin role** in the organization

**To generate an Admin API key:**
1. Go to Console → Settings → Admin Keys
2. Create a new Admin API key (will start with `sk-ant-admin-...`)
3. Add it to your `.env` file as `ANTHROPIC_ADMIN_API_KEY`

**Note**: The Admin API key is separate from regular API keys used for Claude conversations. Your existing `ANTHROPIC_API_KEY` (for LLM analysis) can remain unchanged.

### Backward Compatibility

This implementation is backward compatible with existing DynamoDB data:
- The new `provider` field defaults to `"aws"` for existing records
- No data migration or table recreation is required
- Existing AWS cost snapshots will continue to work

---

## Key Decisions

### 1. API Key Strategy

The Anthropic Admin API requires a separate **Admin API key** (`sk-ant-admin...`) that differs from regular API keys. This aligns with the issue requirement that "the API key for this app AND the API key for costs may be different."

**Configuration approach**:
- `ANTHROPIC_API_KEY` - Existing key for LLM analysis (regular API key)
- `ANTHROPIC_ADMIN_API_KEY` - New key for cost collection (Admin API key)

### 2. Cost API vs Usage API

Anthropic provides two endpoints:
- `/v1/organizations/usage_report/messages` - Token counts by model/workspace
- `/v1/organizations/cost_report` - Costs in USD (cents)

**Decision**: Use the **Cost API** as the primary source since we want dollar amounts for reporting. Store token usage as metadata for detailed analysis.

### 3. Data Granularity

- Cost API only supports daily granularity (`bucket_width=1d`)
- Aligns well with our existing daily cost collection pattern
- Query yesterday's costs (same as AWS Cost Explorer)

### 4. Multi-Service Architecture

Introduce a `provider` concept to distinguish cost sources:
- `aws` - AWS services (EC2, RDS, Lambda, etc.)
- `anthropic` - Claude API costs
- Future: `openai`, `databricks`, etc.

---

## Implementation Steps

### Phase 1: Configuration Updates

#### 1.1 Update Secrets Schema

**File**: `src/slack_aws_cost_guardian/config/schema.py`

Add new configuration for Anthropic cost collection:

```python
class AnthropicCostSourceConfig(BaseModel):
    """Configuration for Anthropic cost collection."""
    enabled: bool = False
    admin_api_key_secret_key: str = "anthropic_admin_api_key"  # Key within secrets

class CollectionSourcesConfig(BaseModel):
    """Configuration for all collection sources."""
    cost_explorer: CostExplorerSourceConfig = Field(default_factory=CostExplorerSourceConfig)
    budgets: BudgetsSourceConfig = Field(default_factory=BudgetsSourceConfig)
    anthropic: AnthropicCostSourceConfig = Field(default_factory=AnthropicCostSourceConfig)  # NEW
```

#### 1.2 Update Secrets Manager

**File**: Update `.env.example` and deployment scripts

Add to `.env.example`:
```bash
# Anthropic Admin API key for cost collection (starts with sk-ant-admin...)
# Different from ANTHROPIC_API_KEY which is for LLM analysis
ANTHROPIC_ADMIN_API_KEY=sk-ant-admin-xxxxx
```

Update `cost-guardian-llm-{env}` secret to include:
```json
{
  "anthropic_api_key": "sk-ant-...",
  "anthropic_admin_api_key": "sk-ant-admin-...",
  "openai_api_key": "sk-..."
}
```

#### 1.3 Update CDK Stack

**File**: `cdk/stacks/cost_guardian_stack.py`

Update the secret sync in deployment to handle the new key.

---

### Phase 2: Create Anthropic Cost Collector

#### 2.1 Create New Collector Module

**File**: `src/slack_aws_cost_guardian/collectors/anthropic_costs.py`

```python
"""Anthropic API cost collector using the Admin Cost API."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from .base import CostCollector, CostData

logger = logging.getLogger(__name__)

ANTHROPIC_COST_API_URL = "https://api.anthropic.com/v1/organizations/cost_report"
ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicCostCollector(CostCollector):
    """Collector for Anthropic Claude API costs."""

    def __init__(self, admin_api_key: str):
        """Initialize the Anthropic cost collector.

        Args:
            admin_api_key: Anthropic Admin API key (sk-ant-admin-...)
        """
        self._admin_api_key = admin_api_key
        self._client = httpx.Client(timeout=30.0)

    @property
    def collector_name(self) -> str:
        return "anthropic"

    @property
    def provider(self) -> str:
        return "anthropic"

    def collect(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> CostData:
        """Collect Anthropic API costs for the specified period.

        Args:
            start_date: Start of collection period (defaults to yesterday)
            end_date: End of collection period (defaults to today)

        Returns:
            CostData with Anthropic costs
        """
        # Default to yesterday's costs (matches AWS pattern)
        if end_date is None:
            end_date = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if start_date is None:
            start_date = end_date - timedelta(days=1)

        logger.info(
            f"Collecting Anthropic costs from {start_date.isoformat()} "
            f"to {end_date.isoformat()}"
        )

        try:
            cost_data = self._fetch_costs(start_date, end_date)
            daily_costs = self._fetch_daily_costs(start_date, end_date)

            return CostData(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                account_id="anthropic",  # Use provider as account_id
                total_cost=cost_data["total_cost"],
                cost_by_service=cost_data["cost_by_service"],
                daily_costs=daily_costs,
                forecast=None,  # Anthropic doesn't provide forecasts
                trend=self._calculate_trend(daily_costs),
            )

        except Exception as e:
            logger.error(f"Failed to collect Anthropic costs: {e}")
            # Return empty data on failure (graceful degradation)
            return CostData(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                account_id="anthropic",
                total_cost=Decimal("0"),
                cost_by_service={},
                daily_costs=[],
                forecast=None,
                trend=0.0,
            )

    def _fetch_costs(
        self, start_date: datetime, end_date: datetime
    ) -> dict[str, Any]:
        """Fetch costs from Anthropic Cost API."""
        params = {
            "starting_at": start_date.strftime("%Y-%m-%dT00:00:00Z"),
            "ending_at": end_date.strftime("%Y-%m-%dT00:00:00Z"),
            "group_by[]": "description",  # Group by cost type (token usage, etc.)
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

        # Parse cost data - costs are in cents as decimal strings
        total_cost = Decimal("0")
        cost_by_service = {}

        for bucket in data.get("data", []):
            for item in bucket.get("results", []):
                # Cost is in cents, convert to dollars
                cost_cents = Decimal(str(item.get("cost", "0")))
                cost_dollars = cost_cents / Decimal("100")

                description = item.get("description", "Unknown")
                service_name = f"Claude::{description}"

                cost_by_service[service_name] = float(cost_dollars)
                total_cost += cost_dollars

        return {
            "total_cost": total_cost,
            "cost_by_service": cost_by_service,
        }

    def _fetch_daily_costs(
        self, start_date: datetime, end_date: datetime
    ) -> list[dict]:
        """Fetch daily cost breakdown for trend analysis."""
        # Extend lookback for baseline comparison
        lookback_start = start_date - timedelta(days=14)

        params = {
            "starting_at": lookback_start.strftime("%Y-%m-%dT00:00:00Z"),
            "ending_at": end_date.strftime("%Y-%m-%dT00:00:00Z"),
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

        daily_costs = []
        for bucket in data.get("data", []):
            bucket_date = bucket.get("bucket_start_time", "")[:10]  # YYYY-MM-DD
            total_cents = sum(
                Decimal(str(item.get("cost", "0")))
                for item in bucket.get("results", [])
            )
            daily_costs.append({
                "date": bucket_date,
                "cost": float(total_cents / Decimal("100")),
            })

        return sorted(daily_costs, key=lambda x: x["date"])

    def _calculate_trend(self, daily_costs: list[dict]) -> float:
        """Calculate cost trend as percentage change."""
        if len(daily_costs) < 2:
            return 0.0

        recent = daily_costs[-1]["cost"]
        previous = daily_costs[-2]["cost"] if daily_costs[-2]["cost"] > 0 else 0.01

        return ((recent - previous) / previous) * 100

    def close(self):
        """Close the HTTP client."""
        self._client.close()
```

---

### Phase 3: Update Storage Models

#### 3.1 Add Provider Field to Models

**File**: `src/slack_aws_cost_guardian/storage/models.py`

Add `provider` field to track cost source:

```python
class CostSnapshot(BaseModel):
    """Cost snapshot stored in DynamoDB."""
    # ... existing fields ...

    # NEW: Provider identification for multi-service support
    provider: str = "aws"  # "aws", "anthropic", "openai", "databricks", etc.
```

#### 3.2 Update DynamoDB Key Schema

Modify sort key to include provider for multi-service queries:

```python
# Current: SK = HOUR#{hour}#{account_id}
# New:     SK = HOUR#{hour}#{provider}#{account_id}
```

This allows querying:
- All snapshots for a date: `PK = SNAPSHOT#2024-01-15`
- Snapshots for a provider: `SK begins_with HOUR#14#anthropic`

---

### Phase 4: Update Cost Collector Handler

#### 4.1 Integrate Anthropic Collector

**File**: `src/slack_aws_cost_guardian/handlers/cost_collector.py`

```python
def _collect_all_costs(config: GuardianConfig) -> dict:
    """Collect costs from all enabled sources."""

    results = {
        "aws": None,
        "anthropic": None,
    }

    # Collect AWS costs (existing)
    if config.collection.sources.cost_explorer.enabled:
        aws_collector = CostExplorerCollector(...)
        results["aws"] = aws_collector.collect()

    # Collect Anthropic costs (NEW)
    if config.collection.sources.anthropic.enabled:
        admin_key = _get_anthropic_admin_key(config)
        if admin_key:
            anthropic_collector = AnthropicCostCollector(admin_key)
            results["anthropic"] = anthropic_collector.collect()
            anthropic_collector.close()

    return results
```

#### 4.2 Merge Costs for Reporting

Create combined snapshot with all provider costs:

```python
def _merge_cost_data(results: dict) -> CostData:
    """Merge costs from multiple providers into unified view."""

    total_cost = Decimal("0")
    combined_cost_by_service = {}

    for provider, data in results.items():
        if data is None:
            continue

        total_cost += Decimal(str(data.total_cost))

        # Prefix services with provider for clarity
        for service, cost in data.cost_by_service.items():
            key = f"{provider}::{service}" if provider != "aws" else service
            combined_cost_by_service[key] = cost

    return CostData(
        total_cost=total_cost,
        cost_by_service=combined_cost_by_service,
        # ... other fields
    )
```

---

### Phase 5: Update Reports and Notifications

#### 5.1 Update Slack Formatter

**File**: `src/slack_aws_cost_guardian/notifications/slack/formatter.py`

Add provider grouping to cost breakdowns:

```python
def _format_cost_by_provider(cost_by_service: dict) -> list[dict]:
    """Group costs by provider for display."""

    providers = {
        "aws": {"name": "AWS", "services": {}, "total": 0},
        "anthropic": {"name": "Claude API", "services": {}, "total": 0},
    }

    for service, cost in cost_by_service.items():
        if service.startswith("anthropic::") or service.startswith("Claude::"):
            provider = "anthropic"
            service_name = service.replace("anthropic::", "").replace("Claude::", "")
        else:
            provider = "aws"
            service_name = service

        providers[provider]["services"][service_name] = cost
        providers[provider]["total"] += cost

    return [p for p in providers.values() if p["total"] > 0]
```

#### 5.2 Update Report Templates

Update daily/weekly report formats to show:

```
Daily Cost Report - Jan 15, 2025
================================
Total: $127.45

AWS Services: $112.30
  EC2          $45.20
  RDS          $32.10
  Lambda       $18.00
  Other        $17.00

Claude API: $15.15
  Token Usage  $14.50
  Web Search   $0.65
```

---

### Phase 6: Update Anomaly Detection

#### 6.1 Per-Provider Baselines

**File**: `src/slack_aws_cost_guardian/analysis/anomaly_detector.py`

Modify anomaly detection to maintain separate baselines per provider:

```python
def detect_anomalies(
    current_costs: dict[str, float],
    historical_costs: list[dict],
    provider: str = "aws",
) -> list[AnomalyInfo]:
    """Detect cost anomalies for a specific provider."""

    # Filter historical data to same provider
    provider_history = [
        h for h in historical_costs
        if h.get("provider", "aws") == provider
    ]

    # Apply provider-specific thresholds
    thresholds = _get_provider_thresholds(provider)

    # ... existing anomaly detection logic
```

This prevents Claude API cost spikes from affecting AWS baseline calculations.

---

### Phase 7: Testing

#### 7.1 Unit Tests

**File**: `tests/collectors/test_anthropic_costs.py`

```python
def test_anthropic_collector_parses_costs():
    """Test parsing of Anthropic cost API response."""
    pass

def test_anthropic_collector_handles_empty_response():
    """Test graceful handling of no cost data."""
    pass

def test_anthropic_collector_converts_cents_to_dollars():
    """Test cost conversion from cents to dollars."""
    pass
```

#### 7.2 Integration Tests

**File**: `tests/integration/test_multi_provider.py`

```python
def test_merged_costs_include_all_providers():
    """Test that merged costs include AWS and Anthropic."""
    pass

def test_anomaly_detection_per_provider():
    """Test that anomalies are detected per provider."""
    pass
```

#### 7.3 Manual Testing

Add Makefile targets:

```makefile
test-anthropic:
	@echo "Testing Anthropic cost collection..."
	python -c "from slack_aws_cost_guardian.collectors.anthropic_costs import AnthropicCostCollector; ..."
```

---

## Configuration Summary

### New Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_ADMIN_API_KEY` | Admin API key for cost collection | Yes (if enabled) |

### Config File Updates

```yaml
collection:
  sources:
    cost_explorer:
      enabled: true
    budgets:
      enabled: true
    anthropic:           # NEW
      enabled: true
```

### Secrets Manager Updates

Update `cost-guardian-llm-{env}` to include `anthropic_admin_api_key`.

---

## Rollout Plan

1. **Deploy configuration changes** - Add new config options (disabled by default)
2. **Deploy collector code** - New Anthropic collector module
3. **Test in dev** - Enable Anthropic collection in dev environment
4. **Validate reports** - Check daily/weekly reports show Claude costs
5. **Enable in production** - Set `anthropic.enabled: true`

---

## Future Considerations

### Adding More Providers

The architecture supports additional providers by:

1. Creating `collectors/{provider}_costs.py` implementing `CostCollector`
2. Adding `{Provider}CostSourceConfig` to schema
3. Adding provider to handler's collector list
4. Updating Slack formatter for new provider

### Potential Future Providers

- **OpenAI**: Similar Admin API for cost tracking
- **Databricks**: Unity Catalog billing APIs
- **Vercel**: Billing API for serverless costs
- **Supabase**: Project billing endpoints

### Cross-Provider Analytics

Future enhancement: Correlate cost spikes across providers (e.g., "Claude costs up 50% on same day as Lambda spike - likely increased AI workload").

---

## Files to Create/Modify

### New Files
- `src/slack_aws_cost_guardian/collectors/anthropic_costs.py`
- `tests/collectors/test_anthropic_costs.py`
- `tests/integration/test_multi_provider.py`

### Modified Files
- `src/slack_aws_cost_guardian/config/schema.py`
- `src/slack_aws_cost_guardian/storage/models.py`
- `src/slack_aws_cost_guardian/handlers/cost_collector.py`
- `src/slack_aws_cost_guardian/analysis/anomaly_detector.py`
- `src/slack_aws_cost_guardian/notifications/slack/formatter.py`
- `src/slack_aws_cost_guardian/analysis/report_builder.py`
- `.env.example`
- `Makefile`

---

## Acceptance Criteria

- [ ] Anthropic costs appear in daily cost reports
- [ ] Anthropic costs appear in weekly cost summaries
- [ ] Anomalies detected separately for AWS and Anthropic
- [ ] Configuration allows enabling/disabling Anthropic collection
- [ ] Graceful degradation if Anthropic API unavailable
- [ ] Admin API key stored securely in Secrets Manager
- [ ] Architecture documented for adding future providers