#!/usr/bin/env python3
"""Delete snapshots from DynamoDB to allow re-backfill with corrected data."""

import argparse
import boto3


def clear_snapshots(table_name: str, days: int = 30, dry_run: bool = True):
    """Delete recent snapshots from DynamoDB.

    Args:
        table_name: DynamoDB table name
        days: Delete snapshots from the last N days
        dry_run: If True, only show what would be deleted
    """
    from datetime import datetime, timedelta, UTC

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # Calculate cutoff date
    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()

    print(f"Scanning for snapshots from {cutoff} onwards...")

    # Scan for snapshots
    response = table.scan(
        FilterExpression="begins_with(PK, :pk) AND #d >= :cutoff",
        ExpressionAttributeNames={"#d": "date"},
        ExpressionAttributeValues={
            ":pk": "SNAPSHOT#",
            ":cutoff": cutoff,
        },
        ProjectionExpression="PK, SK, #d",
    )

    items = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.scan(
            FilterExpression="begins_with(PK, :pk) AND #d >= :cutoff",
            ExpressionAttributeNames={"#d": "date"},
            ExpressionAttributeValues={
                ":pk": "SNAPSHOT#",
                ":cutoff": cutoff,
            },
            ProjectionExpression="PK, SK, #d",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    print(f"Found {len(items)} snapshots to delete")

    if not items:
        print("Nothing to delete.")
        return

    # Show what will be deleted
    for item in sorted(items, key=lambda x: x.get("date", "")):
        print(f"  {item.get('date')}: {item.get('PK')}")

    if dry_run:
        print(f"\n[DRY RUN] Would delete {len(items)} snapshots.")
        print("Run with --execute to actually delete.")
        return

    # Delete items
    print(f"\nDeleting {len(items)} snapshots...")
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    print(f"Deleted {len(items)} snapshots.")


def get_table_name(env: str) -> str:
    """Get table name from CloudFormation stack."""
    cf = boto3.client("cloudformation")
    try:
        response = cf.describe_stacks(StackName=f"CostGuardianStorage-{env}")
        for output in response["Stacks"][0].get("Outputs", []):
            if output["OutputKey"] == "TableName":
                return output["OutputValue"]
    except Exception as e:
        print(f"Error getting table name: {e}")
    return f"cost-guardian-{env}"


def main():
    parser = argparse.ArgumentParser(description="Clear snapshots from DynamoDB")
    parser.add_argument("--env", default="dev", help="Environment (default: dev)")
    parser.add_argument("--days", type=int, default=30, help="Delete snapshots from last N days (default: 30)")
    parser.add_argument("--execute", action="store_true", help="Actually delete (default is dry-run)")
    args = parser.parse_args()

    table_name = get_table_name(args.env)
    print(f"Table: {table_name}")
    print(f"Environment: {args.env}")
    print(f"Days: {args.days}")
    print(f"Mode: {'EXECUTE' if args.execute else 'DRY RUN'}")
    print()

    clear_snapshots(table_name, days=args.days, dry_run=not args.execute)


if __name__ == "__main__":
    main()