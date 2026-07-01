# Architecture Reference

Technical reference for contributors and operators.

## System Overview

Three Lambdas, one DynamoDB table, one S3 config/memory bucket.

```
EventBridge (collection, daily/weekly reports, weekly curator backstop)
        │
        ▼
┌─────────────────────────────────────────────┐
│           Cost Collector Lambda             │   actions dispatched by event:
│  - Collect (Cost Explorer & Budgets)        │     {} / report_type / backfill
│  - Detect anomalies, send Slack alerts      │     {"curate": true}
│  - Run the memory curator                   │     {"memory_action": ...}
└───────┬───────────────────────────┬─────────┘
        ▼                           ▼
   DynamoDB (single table)   Slack Webhooks (critical/heartbeat)
   + S3 memory bucket
        ▲
        │ async invoke {"curate": true}
        │
┌───────┴─────────────────────┐   ┌─────────────────────────────────┐
│   Slack Callback Lambda     │   │        Slack Events Lambda      │
│  - Feedback button clicks   │   │  - @mentions / DMs (Function URL)│
│    (Function URL)           │   │  - LLM tool-use: cost + memory   │
│  - Stores feedback          │   │    tools, multi-turn threads     │
│  - Triggers curator         │   │  - remember_fact -> triggers     │
└─────────────────────────────┘   │    curator                       │
                                   └─────────────────────────────────┘
```

Feedback (callback) and "remember this" (events) both async-invoke the collector
to run the curator, which folds signal into memory. See
[MEMORY-SYSTEM.md](MEMORY-SYSTEM.md).

## DynamoDB Schema

Uses single-table design with composite keys.

### Cost Snapshots

Stores periodic cost data for trend analysis and anomaly detection.

```
PK: SNAPSHOT#{date}           (e.g., "SNAPSHOT#2024-01-15")
SK: HOUR#{hour}#{account_id}  (e.g., "HOUR#14#123456789012")

Attributes:
  snapshot_id      string    UUID
  timestamp        string    ISO 8601
  account_id       string    AWS account ID
  date             string    YYYY-MM-DD
  hour             number    0-23
  period_type      string    "hourly" | "daily" | "weekly"
  total_cost       number    Decimal (stored as string)
  currency         string    "USD"
  cost_by_service  map       {service_name: cost}
  cost_by_account  map       {account_id: {name, cost}}
  budget_status    map       {monthly_budget, monthly_spent, monthly_percent, ...}
  forecast         map       {end_of_month, confidence}
  anomalies        list      [{service, amount, percent_change, severity}]
  ttl              number    Unix timestamp (90 days)
```

### Anomaly Feedback

Stores user responses to anomaly alerts.

```
PK: FEEDBACK#{date}     (e.g., "FEEDBACK#2024-01-15")
SK: ALERT#{alert_id}    (e.g., "ALERT#abc123")

Attributes:
  feedback_id       string    UUID
  alert_id          string    Links to original alert
  timestamp         string    ISO 8601
  user_id           string    Slack user ID
  user_name         string    Slack display name
  feedback_type     string    "expected" | "unexpected" | "investigating"
  affected_services list      [string]
  cost_impact       number    Dollar amount
  explanation       string    Optional user note
  duration_type     string    "one_time" | "ongoing" | "temporary"
  ttl               number    Unix timestamp (2 years)
```

### Change Log

Tracks acknowledged cost changes; read by the curator as additional signal.

```
PK: CHANGE#{service}              (e.g., "CHANGE#AmazonEC2")
SK: DATE#{date}#{change_id}       (e.g., "DATE#2024-01-15#xyz789")

Attributes:
  change_id          string    UUID
  service            string    AWS service name
  change_type        string    "new_service" | "cost_increase" | "cost_decrease"
  status             string    "active" | "resolved" | "expired"
  description        string    User or AI generated
  baseline_cost      number    Cost before change
  new_cost           number    Cost after change
  percent_change     number
  acknowledged_by    string    user_id
  ttl                number    Unix timestamp
```

### Learning Memory

Hot memory (injected into every anomaly check) and the deep-memory version
pointer. Deep-memory *concept files* live in S3, not DynamoDB. See
[MEMORY-SYSTEM.md](MEMORY-SYSTEM.md).

```
PK: MEMORY#HOT       SK: CURRENT
Attributes:
  text               string    Curated hot-memory text (lean, high-signal)
  updated_at         string    ISO 8601
  last_curated_at    string    Curator watermark (newest signal consolidated)

PK: MEMORY#VERSION   SK: CURRENT
Attributes:
  version            number    Bumped on each deep-memory write (re-sync pointer)
```

### Memory Candidates

Explicit "remember this" requests from the bot, pending curation.

```
PK: MEMCANDIDATE#PENDING
SK: TS#{timestamp}#{uuid}

Attributes:
  summary            string    The durable fact to remember
  why                string    Optional reason/context
  source             string    e.g. "slack_conversation"
  created            string    ISO 8601
  ttl                number    Unix timestamp (30 days)
```

### Conversation State

Per-thread multi-turn history for the bot (thread key = `channel:thread_ts`, or
the DM channel).

```
PK: CONVO#{thread_key}   SK: STATE
Attributes:
  turns              list      [{role, content}] (last ~20, text only)
  updated_at         string    ISO 8601
  ttl                number    Unix timestamp (7 days)
```

### Event Dedup

Slack retries events if not acked in 3s; this record dedupes across instances.

```
PK: EVENT#{event_id}   SK: PROCESSED
Attributes:
  timestamp          string    ISO 8601
  ttl                number    Unix timestamp (5 min)
```

### Access Patterns

| Query | Key Condition |
|-------|---------------|
| Get snapshots for a date | PK = `SNAPSHOT#2024-01-15` |
| Get feedback for an alert | PK = `FEEDBACK#{date}`, SK = `ALERT#{alert_id}` |
| Get changes for a service | PK = `CHANGE#{service}` |
| Get hot memory / version | PK = `MEMORY#HOT` / `MEMORY#VERSION`, SK = `CURRENT` |
| Get pending candidates | PK = `MEMCANDIDATE#PENDING` |
| Get conversation history | PK = `CONVO#{thread_key}`, SK = `STATE` |

## IAM Permissions

### Cost Collector Lambda

```yaml
- ce:GetCostAndUsage, ce:GetCostForecast
- budgets:ViewBudget, budgets:DescribeBudgets, budgets:DescribeBudget
- dynamodb: read/write (table)
- s3: read/write (config bucket - reads context, writes deep memory under memory/)
- secretsmanager:GetSecretValue
```

### Slack Callback Lambda

```yaml
- dynamodb: read/write (table)
- secretsmanager:GetSecretValue
- lambda:InvokeFunction (collector - to trigger the curator on feedback)
```

### Slack Events Lambda

```yaml
- dynamodb: read/write (table - cost data, dedup, conversation state, candidates)
- s3: read (config bucket - context + deep memory)
- ce:GetCostAndUsage, ce:GetCostForecast (real-time bot queries)
- secretsmanager:GetSecretValue
- lambda:InvokeFunction (collector - to trigger the curator on remember_fact)
```

## Secrets Management

A **single unified secret** in AWS Secrets Manager, synced from `.env` on deploy:

```
cost-guardian/{env}/config
├── webhook_url_critical      Slack webhook for critical alerts
├── webhook_url_heartbeat     Slack webhook for daily/reports
├── signing_secret            For verifying Slack callbacks/events
├── bot_token                 Slack bot token (@mentions/DMs)
├── anthropic_api_key         Claude API key (optional)
├── anthropic_admin_api_key   For Anthropic cost collection (optional)
└── openai_api_key            OpenAI API key (optional)
```

## Configuration

### S3 Config Bucket

```
s3://cost-guardian-config-{env}/
├── config/
│   └── guardian-context.md    AI context about your infrastructure
└── memory/                    Deep learning memory (OKF concept files)
    ├── INDEX.md               Navigable index of concepts
    └── <type>/<id>.md         One concept per file (frontmatter + body)
```

### Environment Variables (Lambda)

| Variable | Collector | Callback | Events |
|----------|:---------:|:--------:|:------:|
| `TABLE_NAME` | ✓ | ✓ | ✓ |
| `CONFIG_SECRET_NAME` | ✓ | ✓ | ✓ |
| `CONFIG_BUCKET` | ✓ | | ✓ |
| `CONFIG_ENV` | ✓ | | ✓ |
| `COLLECTOR_FUNCTION_NAME` | | ✓ | ✓ |
| `ANTHROPIC_COSTS_ENABLED`, `APP_VERSION`, `GIT_COMMIT`, `DEPLOY_TIMESTAMP` | ✓ | | |

## EventBridge Schedules

| Schedule | Payload | Purpose |
|----------|---------|---------|
| collection hours (config) | `{}` | Cost collection & anomaly detection |
| daily hour (config) | `{"report_type": "daily"}` | Daily summary |
| Monday, weekly hour (config) | `{"report_type": "weekly"}` | Weekly summary |
| Monday, curator hour (config) | `{"curate": true}` | Memory curator backstop (gated) |

Report/curator schedules are toggleable and hour-configurable via `config.yaml`
(`reports.*`, `memory.curator.*`). The curator primarily runs event-driven (on
feedback / `remember_fact`); this weekly pass is a gated backstop.