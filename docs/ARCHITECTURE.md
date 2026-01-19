# Architecture Reference

Technical reference for contributors and operators.

## System Overview

```
EventBridge (4x daily)     EventBridge (daily/weekly)
        │                           │
        ▼                           ▼
┌─────────────────────────────────────────────┐
│           Cost Collector Lambda             │
│  - Collects from Cost Explorer & Budgets    │
│  - Detects anomalies                        │
│  - Generates reports                        │
│  - Sends Slack notifications                │
└─────────────────────────────────────────────┘
        │                           │
        ▼                           ▼
   DynamoDB                 Slack Webhooks
   (single table)           (critical/heartbeat)
        │
        ▼
┌─────────────────────────────────────────────┐
│         Slack Callback Lambda               │
│  - Receives button clicks via Function URL │
│  - Stores feedback in DynamoDB              │
└─────────────────────────────────────────────┘
```

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

Tracks acknowledged cost changes for AI context (future use).

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

### Access Patterns

| Query | Key Condition |
|-------|---------------|
| Get snapshots for a date | PK = `SNAPSHOT#2024-01-15` |
| Get feedback for an alert | PK = `FEEDBACK#{date}`, SK = `ALERT#{alert_id}` |
| Get changes for a service | PK = `CHANGE#{service}` |

## IAM Permissions

### Cost Collector Lambda

```yaml
- ce:GetCostAndUsage
- ce:GetCostForecast
- budgets:ViewBudget
- budgets:DescribeBudgets
- dynamodb:PutItem
- dynamodb:Query
- dynamodb:Scan
- s3:GetObject (config bucket)
- secretsmanager:GetSecretValue
```

### Slack Callback Lambda

```yaml
- dynamodb:PutItem
- dynamodb:Query
- secretsmanager:GetSecretValue
```

## Secrets Management

Stored in AWS Secrets Manager:

```
cost-guardian-slack-{env}
├── webhook_url_critical    Slack webhook for critical alerts
├── webhook_url_heartbeat   Slack webhook for daily/reports
└── signing_secret          For verifying Slack callbacks

cost-guardian-llm-{env}
├── anthropic_api_key       Claude API key (optional)
└── openai_api_key          OpenAI API key (optional)
```

## Configuration

### S3 Config Bucket

```
s3://cost-guardian-config-{env}/
└── config/
    └── guardian-context.md   AI context about your infrastructure
```

### Environment Variables (Lambda)

```
TABLE_NAME          DynamoDB table name
CONFIG_BUCKET       S3 bucket for configuration
SLACK_SECRET_NAME   Secrets Manager secret for Slack
LLM_SECRET_NAME     Secrets Manager secret for LLM keys
CONFIG_ENV          Environment (dev/staging/prod)
```

## EventBridge Schedules

| Schedule | Payload | Purpose |
|----------|---------|---------|
| 0,6,12,18 UTC | `{}` | Cost collection & anomaly detection |
| 14:00 UTC (8am CT) | `{"report_type": "daily"}` | Daily summary |
| Monday 14:00 UTC | `{"report_type": "weekly"}` | Weekly summary |