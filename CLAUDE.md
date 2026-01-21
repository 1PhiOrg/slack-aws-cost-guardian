# Slack AWS Cost Guardian

## Project Overview
AI-powered AWS cost monitoring with Slack integration. Detects spending anomalies, provides intelligent analysis, and delivers actionable insights to Slack.

## Tech Stack
- **Language**: Python 3.12
- **Infrastructure**: AWS CDK v2
- **Storage**: DynamoDB (single-table design)
- **Compute**: AWS Lambda (ARM64)
- **AI**: Claude API (Anthropic), with abstraction for OpenAI
- **Notifications**: Slack webhooks with interactive buttons
- **Package Manager**: uv

## Important Rules
- **NEVER deploy infrastructure directly** - always let the user run deployments
- **NEVER execute git commit/push commands** - provide commands for the user to run
- **Always use Makefile commands** instead of CDK commands directly (e.g., `make deploy` not `cdk deploy`)

## Workflow Commands

| User Request | Action |
|--------------|--------|
| "commit", "make a commit" | Run `/commit` skill |
| "PR", "pull request" | Run `/pr` skill |

## Version Management

The project uses semantic versioning stored in the `VERSION` file.

**Before committing significant changes**, remind the user to consider bumping the version:
- `make bump` - Interactive version bump menu
- `make bump-patch` - Bug fixes (0.1.0 → 0.1.1)
- `make bump-minor` - New features (0.1.0 → 0.2.0)
- `make bump-major` - Breaking changes (0.1.0 → 1.0.0)

**On deploy**, the version and git commit are embedded in the Lambda and a notification is sent to Slack.

## Key Files
- `docs/ARCHITECTURE.md` - Technical reference (DynamoDB schema, IAM, secrets)
- `docs/BACKLOG.md` - Future features and roadmap
- `src/slack_aws_cost_guardian/` - Main Python package
- `cdk/` - CDK infrastructure code
- `config/guardian-context.md` - AI context about the user's infrastructure

## Configuration

Secrets are managed via `.env` file (copy from `.env.example`):
```bash
cp .env.example .env
# Edit .env with your values
```

The `.env` file contains:
- `ENV` - Deployment environment (dev/staging/prod)
- `SLACK_WEBHOOK_CRITICAL` / `SLACK_WEBHOOK_HEARTBEAT` - Slack webhook URLs
- `SLACK_SIGNING_SECRET` - For verifying button callbacks
- `ANTHROPIC_API_KEY` - Claude API key for AI analysis (optional)
- `OPENAI_API_KEY` - OpenAI API key as alternative (optional)

`make deploy` automatically syncs `.env` values to AWS Secrets Manager.

## Development Commands
```bash
# First time setup
make setup

# Activate environment
source .venv/bin/activate

# Run tests
make test

# Version management
make version        # Show current version
make bump           # Interactive version bump

# Deploy (also configures secrets from .env)
make deploy

# Validate deployment
make validate

# Show deployment info (including version)
make info

# Test alerts
make test-collect   # Dry run
make test-alert     # Send test anomaly
make test-daily     # Send daily report
make test-weekly    # Send weekly report

# View all commands
make help
```

## Project Status
All core features implemented:
- Cost collection from AWS Cost Explorer
- Anomaly detection with configurable thresholds
- AI-powered analysis (Claude/OpenAI)
- Interactive Slack alerts with feedback buttons
- Daily and weekly summary reports
- Budget threshold alerts (80%/100%)
- Historical data backfill

See `docs/BACKLOG.md` for future enhancements.