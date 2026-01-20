# 1Phi AWS Cost Guardian Context

This document provides context for AI-powered cost analysis of the 1Phi AWS infrastructure.

## Organization Overview

**1Phi** is a healthcare technology startup building AI-powered healthcare provider search (1Sage) using national CMS claims data analytics, "Digital Twin" patient profiles, and agentic AI.

## AWS Account Structure

### Management Account (506334647071) - Primary for Cost Guardian deployment
- **Account ID**: 506334647071
- **Purpose**: Organization management, Databricks compute, shared services
- **Databricks**: Runs Vinci data processing pipeline
  - Processes CMS claims data (PUF files)
  - Generates provider analytics and metrics
  - Unity Catalog for data governance
  - Compute: Serverless SQL warehouses + job clusters
  - Storage: S3 buckets for raw data, Delta Lake tables

### Development Account (526932954566)
- **Purpose**: Development and staging for 1Sage application
- **Profile**: `1phi-development`
- **Region**: `us-east-1`

## Known Workloads by Account

### Management Account Workloads

| Service | Resource | Usage Pattern | Expected Cost Driver |
|---------|----------|---------------|---------------------|
| **Databricks** | Serverless SQL | Sporadic development queries | Pay-per-use, can spike during data exploration |
| **Databricks** | Job Clusters | Weekly/monthly batch processing | Significant when running full pipelines |
| **S3** | CMS data storage | Static, grows slowly | Storage costs, minimal egress |

### Development Account (526932954566) Workloads

| Service | Resource | Usage Pattern | Expected Cost Driver |
|---------|----------|---------------|---------------------|
| **Lambda** | sage2-dev-backend | Low during dev, spikes during testing | ARM64 Graviton2, 2GB memory, 15min timeout |
| **RDS** | sage-shared-data (PostgreSQL t4g.small) | Always-on | Instance hours (~$25/month), storage |
| **DynamoDB** | sage2-dev-sessions | Pay-per-request | Minimal in dev |
| **S3** | sage-embeddings-526932954566 | Static data, read-heavy | Storage (~$0.02/GB/month) |
| **S3** | sage-vinci-exports-526932954566 | Weekly updates from Vinci | Storage for data handoff |
| **ECR** | cdk-hnb659fds-container-assets-* | Docker images for Lambda | Storage, lifecycle policy keeps last 10 |
| **Secrets Manager** | sage2/dev/* | API credentials | ~$0.40/secret/month |
| **SSM Parameter Store** | /sage/* | Configuration | Free tier |
| **CloudWatch** | Lambda logs | Retention: 1 week (dev) | Minimal |

### AWS Marketplace Subscriptions

| Subscription | Purpose | Billing Pattern |
|--------------|---------|-----------------|
| **Qdrant Cloud** | Vector database for semantic search | Monthly subscription, usage-based |

## External Services (Not AWS)

These costs appear outside AWS but are part of the infrastructure:

| Service | Purpose | Typical Monthly Cost |
|---------|---------|---------------------|
| Anthropic (Claude API) | LLM for AI agents | Variable, depends on usage |
| LangSmith | LLM observability | Free tier or minimal |
| Clerk | User authentication | Free tier currently |

## Budget Expectations

### Development Account
- **Target monthly spend**: $50-100
- **Alert thresholds**:
  - Warning: 80% of $100 = $80
  - Critical: 100% of $100 = $100
- **Acceptable spikes**: During data pipeline runs (loading Qdrant collections)

### Management Account
- **Target monthly spend**: Variable based on Databricks usage
- **Alert thresholds**: To be determined based on baseline
- **Acceptable spikes**: During scheduled data processing jobs

## Known Spending Patterns

### Expected Patterns
1. **Weekly Vinci exports**: S3 costs spike slightly when new data is exported from Databricks
2. **Development cycles**: Lambda/RDS costs increase during active development
3. **Data pipeline runs**: EC2 spot instances or Fargate tasks for loading Qdrant (~1 hour)
4. **Qdrant collection rebuilds**: Can take 1-2 hours, creates temporary S3 egress

### Red Flags to Watch
1. **RDS storage growing unexpectedly**: Check for runaway queries or data issues
2. **Lambda duration spikes**: May indicate infinite loops or performance regression
3. **Databricks compute left running**: Job clusters should terminate after jobs
4. **NAT Gateway costs**: Should be minimal, any significant cost indicates misconfiguration
5. **Data transfer costs**: Unexpected egress may indicate security issue

## Cost Optimization Notes

### Already Implemented
- Lambda uses ARM64 (Graviton2) for cost efficiency
- ECR lifecycle policy limits images to last 10
- DynamoDB uses on-demand pricing
- CloudWatch log retention is 1 week for dev
- RDS uses t4g.small (burstable ARM)

### Potential Optimization Areas
- RDS could use Reserved Instance for prod
- Lambda could use Provisioned Concurrency if cold starts become an issue
- S3 Intelligent-Tiering for infrequently accessed data

## Environment Context

### Development Phase
The organization is currently in active development with:
- Primary developer: Dan
- Data engineer: Abdul (Databricks/Vinci)
- No production traffic yet
- Focus on feature development and data pipeline iteration

### Deployment Tooling
- AWS CDK for infrastructure
- `direnv` for AWS profile management
- UV package manager for Python
- Docker for Lambda deployment

## Notification Preferences

### Who to Notify
- All alerts: Dan (primary)
- Databricks-specific: Abdul (if separate channel needed)

### What to Include in Alerts
- Service breakdown with top cost drivers
- Day-over-day and week-over-week comparisons
- Specific resource identifiers (Lambda function names, RDS instance IDs)
- Actionable recommendations

## Scheduled Jobs Context

Currently no scheduled AWS jobs outside of Databricks. Future:
- Daily/weekly data sync from Vinci to Sage
- Scheduled embedding updates

## Notes for AI Analysis

When analyzing costs:
1. **Databricks in management account is expected to be the largest cost driver** when active
2. **Development account should be relatively stable and low cost**
3. **External services (Anthropic, Qdrant Cloud) are not visible in AWS Cost Explorer** but are part of total infrastructure cost
4. **Compare against these baselines**: Lambda ~$5/month, RDS ~$25/month, S3 ~$5/month in dev
5. **New accounts are expected** (production) so cross-account cost visibility is important
6. **Seasonal patterns**: Active development during business hours (US Central time)
