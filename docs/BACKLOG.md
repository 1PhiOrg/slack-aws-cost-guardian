# Backlog

Future enhancements and features for Slack AWS Cost Guardian.

## High Priority

### Interactive Bot Features (Phased Roadmap)

A three-phase approach to making Cost Guardian an interactive Slack bot that users can query directly.

#### Phase 1: Bot Identity + Direct Queries - COMPLETE ([#16](https://github.com/danjamk/slack-aws-cost-guardian/issues/16))

**Status:** Implemented and deployed.

Users can now @mention the bot or send DMs to ask cost questions:
- `@guardian what did we spend yesterday?`
- `@guardian show me EC2 costs for the last 7 days`
- `@guardian what's the trend for Secrets Manager this month?`

**Delivered:**
- Slack App with bot user and Events API
- LLM tool-use pattern for answering questions
- Cost tools: `get_daily_costs`, `get_service_trend`, `get_cost_summary`, `get_top_services`
- Events Lambda with deduplication (handles Slack retries)
- Provider-separated cost display (AWS vs Claude costs)

---

#### Phase 2: Thread-based Alert Investigation - DELIVERED ([#3](https://github.com/danjamk/slack-aws-cost-guardian/issues/3))

**Status:** Delivered as part of the learning-memory work. Multi-turn threaded
conversations, DynamoDB conversation state, and thread-aware handling shipped; the
bot now carries context across a Slack thread/DM and answers follow-ups with cost
tools + learned memory.

**Delivered:**
- Conversation state management in DynamoDB (`CONVO#` items, TTL)
- Multi-turn context handling in the LLM tool-use loop
- Thread-aware event handling

**Remaining (split out):** the "Investigate" button on anomaly alerts is tracked
separately as [#24](https://github.com/danjamk/slack-aws-cost-guardian/issues/24).

---

#### Phase 3: Advanced Investigation Tools ([#18](https://github.com/danjamk/slack-aws-cost-guardian/issues/18))
Extended tool library for deep cost investigation.

**New tools:**
- `get_recent_changes(service, hours)` - CloudTrail events that explain cost changes
- `get_resource_info(resource_id)` - Describe EC2, RDS, Lambda with cost estimates
- `compare_periods(period1, period2)` - Detailed period-over-period analysis
- `get_usage_breakdown(service)` - Break down costs by usage type

**Example interactions:**
- "What changed in EC2 in the last 24 hours?"
- "Describe the instance that's costing us the most"
- "Compare this week to last week"

**Prerequisites:** Phase 1 complete; Phase 2 recommended

---

### Two-Layer Learning Memory - DELIVERED ([#23](https://github.com/danjamk/slack-aws-cost-guardian/issues/23))

**Status:** P0–P3b shipped and validated end-to-end. Cost Guardian learns from
alert feedback and plain-English conversation, remembers durable facts (hot +
deep memory), and applies them to every future check. File-based, no vector DB.

**Delivered:**
- **Hot memory** — `MEMORY#HOT` DynamoDB item, injected into every anomaly check.
- **Deep memory** — OKF-style `memory/` concept files + `INDEX.md` in S3.
- **Curator** — event-driven consolidation (feedback / changes / "remember"
  requests) with a watermark gate; weekly gated backstop.
- **Bot reads memory** (navigation tools) and **writes it** (`remember_fact`).
- **Model** default updated to `claude-sonnet-4-6`.

**Remaining (split out):** P4 — context expansion via MCP — is tracked as
[#25](https://github.com/danjamk/slack-aws-cost-guardian/issues/25).

Design: [`docs/MEMORY-SYSTEM.md`](MEMORY-SYSTEM.md)

---

### Investigate Button on Alerts ([#24](https://github.com/danjamk/slack-aws-cost-guardian/issues/24))
Add an "Investigate" button to anomaly alerts that opens a threaded investigation
(now cheap — multi-turn threads landed with the memory work). The remaining UX
piece of the original #3. See [`docs/MEMORY-SYSTEM.md`](MEMORY-SYSTEM.md) (P3b).

---

### Context Expansion via MCP — P4 ([#25](https://github.com/danjamk/slack-aws-cost-guardian/issues/25))
Let the conversation bot reach live external context (GitHub code/issues, then any
hosted MCP as a config slot) via the Messages API MCP connector, to explain cost
changes. Conversation-path only. [#18](https://github.com/danjamk/slack-aws-cost-guardian/issues/18)
(CloudTrail "what changed?") is the AWS-native complement. Design:
[`docs/MEMORY-SYSTEM.md`](MEMORY-SYSTEM.md) (Phase 4).

---

### AWS Budgets Integration ([#2](https://github.com/danjamk/slack-aws-cost-guardian/issues/2))
Integrate with AWS Budgets API to leverage existing budget configurations and alerts.

**Goals:**
- Read budget definitions from AWS Budgets instead of config file
- Sync budget thresholds and alert preferences
- Consolidate alerting so AWS Budgets and Cost Guardian share the same notification channel
- Avoid duplicate alerts between native AWS Budget notifications and Cost Guardian

**Considerations:**
- AWS Budgets already has SNS-based alerting - decide whether to replace or augment
- May need to disable native Budget alerts to avoid duplication
- Could import budget history for trend analysis

---

## Medium Priority

### CloudWatch Alarms for System Health ([#4](https://github.com/danjamk/slack-aws-cost-guardian/issues/4))
Add operational monitoring for the Cost Guardian system itself.

**Candidates:**
- Lambda error rate alarm
- Lambda duration approaching timeout
- No successful invocations in X hours
- DynamoDB throttling

**Considerations:**
- Daily reports already serve as implicit health check
- Where to send alerts if Slack is broken? (SNS email fallback)

---

### Multi-Account Support ([#5](https://github.com/danjamk/slack-aws-cost-guardian/issues/5))
Monitor costs across multiple AWS accounts (AWS Organizations).

**Goals:**
- Aggregate costs from member accounts
- Per-account anomaly detection
- Cross-account cost allocation tags

**Requirements:**
- Cross-account IAM roles
- Account-aware storage schema
- Account filtering in reports

---

### Cost Optimization Recommendations ([#6](https://github.com/danjamk/slack-aws-cost-guardian/issues/6))
Proactive suggestions for reducing costs based on usage patterns.

**Ideas:**
- Idle resource detection (EC2, RDS, EBS)
- Reserved Instance / Savings Plan coverage gaps
- Right-sizing recommendations
- Unused Elastic IPs, old snapshots

---

### Historical Trend Dashboard ([#7](https://github.com/danjamk/slack-aws-cost-guardian/issues/7))
Web-based dashboard for visualizing cost trends.

**Options:**
- Simple static HTML generated to S3
- CloudWatch dashboard with custom metrics
- Integration with Grafana

---

## Low Priority / Nice to Have

### Slack App Distribution ([#8](https://github.com/danjamk/slack-aws-cost-guardian/issues/8))
Package as installable Slack app for easier onboarding.

- OAuth flow for workspace installation
- App Home tab with configuration
- Slash commands (`/cost today`, `/cost service ec2`)

---

### Email Digest Option ([#9](https://github.com/danjamk/slack-aws-cost-guardian/issues/9))
Alternative delivery channel for users without Slack.

- SES integration
- HTML email templates
- Weekly PDF report attachment

---

### Forecast Accuracy Tracking ([#10](https://github.com/danjamk/slack-aws-cost-guardian/issues/10))
Track how accurate cost forecasts are over time.

- Compare forecasted vs actual at end of month
- Adjust forecasting model based on accuracy
- Surface forecast confidence in reports

---

### Custom Alert Rules ([#11](https://github.com/danjamk/slack-aws-cost-guardian/issues/11))
User-defined alerting beyond standard anomaly detection.

- "Alert if EC2 exceeds $X/day"
- "Alert if any new service appears"
- "Alert if specific tag has costs"

---

## Completed

- [x] Phase 1: Infrastructure (DynamoDB, Lambda, EventBridge)
- [x] Phase 2: LLM Integration (Anthropic/OpenAI with graceful degradation)
- [x] Phase 3: Slack Callbacks (interactive buttons with feedback)
- [x] Phase 4: Daily/Weekly Reports (scheduled summaries with AI insights)
- [x] Budget threshold alerts (80% warning, 100% critical)
- [x] Historical data backfill command
- [x] Configuration validation (`make validate`)
- [x] Anthropic Claude API cost collection ([#13](https://github.com/danjamk/slack-aws-cost-guardian/issues/13))
- [x] **Interactive Bot - Phase 1**: Bot identity + direct queries ([#16](https://github.com/danjamk/slack-aws-cost-guardian/issues/16))
  - @mention and DM support
  - LLM tool-use for cost queries
  - Provider-separated cost display (AWS vs Claude)
- [x] **Interactive Bot - Phase 2**: Multi-turn threaded conversations ([#3](https://github.com/danjamk/slack-aws-cost-guardian/issues/3))
  - Conversation state in DynamoDB; thread-aware, context-carrying answers
- [x] **Two-Layer Learning Memory** (P0–P3b) ([#23](https://github.com/danjamk/slack-aws-cost-guardian/issues/23))
  - Hot + deep memory, event-driven curator, bot read/write of learned facts
  - See [`docs/MEMORY-SYSTEM.md`](MEMORY-SYSTEM.md)