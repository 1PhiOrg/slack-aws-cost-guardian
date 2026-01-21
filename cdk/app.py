#!/usr/bin/env python3
"""CDK application entry point for Slack AWS Cost Guardian."""

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import aws_cdk as cdk

from cdk.stacks.storage_stack import StorageStack
from cdk.stacks.collector_stack import CollectorStack
from cdk.stacks.callback_stack import CallbackStack


def _get_version() -> str:
    """Read version from VERSION file."""
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "0.0.0"


def _get_git_commit() -> str:
    """Get short git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def main():
    """Create and synthesize the CDK application."""
    app = cdk.App()

    # Get version and build info
    version = _get_version()
    git_commit = _get_git_commit()
    deploy_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Get environment from context or environment variable
    environment = app.node.try_get_context("environment") or os.environ.get(
        "CONFIG_ENV", "dev"
    )

    # Check if Anthropic cost collection is enabled
    anthropic_costs_enabled = os.environ.get("ANTHROPIC_COSTS_ENABLED", "").lower() in (
        "true", "1", "yes"
    )

    # Get AWS environment
    aws_env = cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    )

    # Common tags for all resources
    tags = {
        "Project": "slack-aws-cost-guardian",
        "Environment": environment,
        "ManagedBy": "CDK",
    }

    # Create the storage stack
    storage_stack = StorageStack(
        app,
        f"CostGuardianStorage-{environment}",
        deploy_env=environment,
        env=aws_env,
    )

    # Apply tags to storage stack
    for key, value in tags.items():
        cdk.Tags.of(storage_stack).add(key, value)

    # Create the collector stack
    collector_stack = CollectorStack(
        app,
        f"CostGuardianCollector-{environment}",
        environment=environment,
        table=storage_stack.table,
        config_bucket=storage_stack.config_bucket,
        schedule_hours=[6, 12, 18, 0],  # 4x daily
        anthropic_costs_enabled=anthropic_costs_enabled,
        version=version,
        git_commit=git_commit,
        deploy_timestamp=deploy_timestamp,
        env=aws_env,
    )

    # Collector depends on storage
    collector_stack.add_dependency(storage_stack)

    # Apply tags to collector stack
    for key, value in tags.items():
        cdk.Tags.of(collector_stack).add(key, value)

    # Output useful values
    cdk.CfnOutput(
        storage_stack,
        "TableName",
        value=storage_stack.table_name,
        description="DynamoDB table name",
    )

    cdk.CfnOutput(
        storage_stack,
        "ConfigBucketName",
        value=storage_stack.config_bucket_name,
        description="S3 bucket for configuration",
    )

    cdk.CfnOutput(
        collector_stack,
        "CollectorFunctionArn",
        value=collector_stack.function_arn,
        description="Cost Collector Lambda ARN",
    )

    cdk.CfnOutput(
        collector_stack,
        "SlackSecretArn",
        value=collector_stack.slack_secret_arn,
        description="Secrets Manager ARN for Slack webhooks (populate after deployment)",
    )

    cdk.CfnOutput(
        collector_stack,
        "LLMSecretArn",
        value=collector_stack.llm_secret_arn,
        description="Secrets Manager ARN for LLM API keys (populate after deployment)",
    )

    # Create the callback stack for Slack button handling
    callback_stack = CallbackStack(
        app,
        f"CostGuardianCallback-{environment}",
        environment=environment,
        table=storage_stack.table,
        slack_secret=collector_stack.slack_secret,
        env=aws_env,
    )

    # Callback depends on collector (for slack_secret)
    callback_stack.add_dependency(collector_stack)

    # Apply tags to callback stack
    for key, value in tags.items():
        cdk.Tags.of(callback_stack).add(key, value)

    app.synth()


if __name__ == "__main__":
    main()