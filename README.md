# Slack AWS Cost Guardian

> AI-powered AWS cost monitoring with Slack alerts

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![AWS CDK](https://img.shields.io/badge/AWS_CDK-v2-orange.svg)](https://aws.amazon.com/cdk/)

Detect spending anomalies, track budgets, and get intelligent analysis delivered directly to Slack.

## Features

- **Anomaly Detection** - AI-powered identification of unusual spending patterns
- **Daily & Weekly Reports** - Automated summaries with budget tracking and forecasts
- **Interactive Slack Alerts** - Acknowledge costs as expected/unexpected directly from Slack
- **Budget Threshold Alerts** - Warnings at 80% and critical alerts at 100% of budget
- **AI Analysis** - Claude or GPT explains what's driving cost changes

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)

### 1. Clone and Setup

```bash
git clone https://github.com/your-org/slack-aws-cost-guardian.git
cd slack-aws-cost-guardian
make setup
```

This creates a virtual environment, installs dependencies, and creates `.env` from the template.

### 2. Configure Environment

Edit `.env` with your values:

```bash
# Required: Slack webhooks
SLACK_WEBHOOK_CRITICAL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SLACK_WEBHOOK_HEARTBEAT=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Required for interactive buttons
SLACK_SIGNING_SECRET=your-signing-secret

# Optional: AI analysis (recommended)
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

**Creating Slack Webhooks:**
1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Create a new app or select existing
3. Enable "Incoming Webhooks"
4. Create webhooks for two channels (e.g., `#aws-alerts` and `#aws-alerts-critical`)

### 3. Deploy

```bash
source .venv/bin/activate
make deploy
```

This deploys:
- DynamoDB table for cost snapshots and feedback
- Lambda function for cost collection
- EventBridge schedules (4x daily collection, daily/weekly reports)
- S3 bucket for configuration

### 4. Verify

```bash
make validate
```

Checks that all components are correctly configured.

### 5. Test

```bash
# Dry run - collect costs without storing or alerting
make test-collect

# Send a test anomaly alert to Slack
make test-alert

# Generate a daily report
make test-daily
```

## Usage

### Available Commands

Run `make help` to see all commands grouped by workflow:

```
Getting Started
  setup                 Set up development environment

Infrastructure
  synth                 Synthesize CDK stacks
  diff                  Show what would change
  deploy                Deploy all stacks
  destroy               Destroy all stacks

Configuration
  setup-slack           Configure Slack webhooks
  setup-llm             Configure LLM API key
  update-context        Upload guardian context to S3
  validate              Verify deployment is configured

Testing Alerts
  test-collect          Dry-run cost collection
  test-alert            Send test anomaly alert
  test-full             Full collection with storage
  test-daily            Send daily summary report
  test-weekly           Send weekly summary report

Data Management
  backfill              Backfill historical data
  scan-snapshots        List recent snapshots

Operations
  logs                  Tail Lambda logs
```

### Backfilling Historical Data

For accurate anomaly detection, backfill historical cost data:

```bash
make backfill BACKFILL_DAYS=30
```

### Multi-Environment Deployment

```bash
# Deploy to staging
make deploy ENV=staging

# Deploy to production
make deploy ENV=prod
```

## Architecture

```
EventBridge (scheduled) → Lambda → Cost Explorer API
                            ↓
                       DynamoDB (snapshots)
                            ↓
                    Anomaly Detection
                            ↓
                      LLM Analysis
                            ↓
                    Slack Notification
                            ↓
                    User Feedback → DynamoDB
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed technical reference.

## Configuration

### Guardian Context

Customize the AI's understanding of your infrastructure by editing `config/guardian-context.md`:

```markdown
# My AWS Infrastructure

## Known Services
- Production web servers on EC2 (m5.large)
- PostgreSQL on RDS
- S3 for static assets

## Expected Patterns
- Higher traffic on weekends
- Monthly batch jobs on 1st of month
```

Upload changes:
```bash
make update-context
```

### Budget Settings

Edit `config/settings.yaml` to adjust thresholds:

```yaml
budgets:
  monthly:
    amount: 1000
    warning_threshold: 80
    critical_threshold: 100

anomaly_detection:
  thresholds:
    percent_change: 50
    std_deviations: 2.5
```

## Development

```bash
# Run tests
make test

# Run tests with coverage
make test-cov

# Clean build artifacts
make clean
```

## Troubleshooting

### No data in daily report

Run backfill to populate historical data:
```bash
make backfill BACKFILL_DAYS=7
```

### Slack buttons not working

Ensure `SLACK_SIGNING_SECRET` is set in `.env` and redeploy:
```bash
make deploy
```

### LLM analysis missing

Check that `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is configured:
```bash
make validate
```

## Future Roadmap

See [docs/BACKLOG.md](docs/BACKLOG.md) for planned features:
- AWS Budgets API integration
- Agentic Slack conversations with tool use
- Multi-account support
- Cost optimization recommendations

## License

MIT License - see [LICENSE](LICENSE) for details.