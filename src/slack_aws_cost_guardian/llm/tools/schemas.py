"""Tool schemas and system prompts for cost queries."""

from __future__ import annotations

from slack_aws_cost_guardian.llm.base import LLMTool

# System prompt for cost query assistant
COST_QUERY_SYSTEM_PROMPT = """You are Cost Guardian, an AI assistant that helps users understand their cloud spending.

You have access to tools that can query cost data from multiple sources:
- **AWS costs**: All AWS services (EC2, RDS, Lambda, S3, etc.)
- **Anthropic/Claude API costs**: Tracked as services prefixed with "Claude::" (e.g., "Claude::API Usage")

Use these tools to answer questions about:
- Daily and historical costs (AWS and Anthropic combined)
- Service-level cost breakdowns
- Cost trends over time
- Account-level cost allocation

You also have access to LEARNED MEMORY: durable facts about this user's
infrastructure captured from their feedback on past alerts (accepted baselines,
known patterns, decisions about what is/isn't worth worrying about). Consult it
when it would improve your answer - use list_memory to see what's known,
search_memory to find relevant concepts, and read_memory_concept to read one.
Prefer these learned facts over generic assumptions, and cite them when relevant
(e.g. "you previously marked this as expected").

When the user asks you to remember something ("remember this", "note that X is
expected", etc.), use the remember_fact tool: distill the durable fact from the
conversation into a clear self-contained statement and save it. Confirm what you
saved. Do not claim you cannot write to memory - you can, via remember_fact.

When answering:
1. Use the appropriate tool(s) to fetch the data needed
2. Consult learned memory when the question touches something the user may have
   given feedback on before
3. Present costs clearly with currency (USD)
4. Provide context when helpful (comparisons to averages, trends)
5. Keep responses concise but informative
6. Look for "Claude::" prefixed services when asked about Anthropic/Claude costs
7. If you can't answer a question with the available tools, explain what information you'd need

Format costs as: $X.XX (e.g., $142.50)
Format percentages as: X% (e.g., 15%)

Be helpful and proactive - if a user asks about "yesterday", use the tool appropriately.
If there's an error fetching data, explain it clearly and suggest alternatives.
"""

# Tool definitions compatible with both Claude and OpenAI
COST_TOOLS: list[LLMTool] = [
    LLMTool(
        name="get_daily_costs",
        description="Get cost summary for a specific date or date range. Returns total cost, breakdown by service, and daily trends.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format, or 'yesterday', 'today', or relative like '7_days_ago'",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Optional, defaults to start_date for single day.",
                },
                "account_id": {
                    "type": "string",
                    "description": "Filter to specific AWS account ID. Optional.",
                },
            },
            "required": ["start_date"],
        },
    ),
    LLMTool(
        name="get_service_trend",
        description="Get cost trend for a specific AWS service over time. Shows daily costs and calculates trend direction.",
        parameters={
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "AWS service name (e.g., 'Amazon Elastic Compute Cloud - Compute', 'Amazon Relational Database Service', 'AWS Lambda'). Use the full service name.",
                },
                "period": {
                    "type": "string",
                    "enum": ["7d", "14d", "30d"],
                    "description": "Time period: 7d (week), 14d (two weeks), 30d (month)",
                },
                "account_id": {
                    "type": "string",
                    "description": "Filter to specific AWS account ID. Optional.",
                },
            },
            "required": ["service", "period"],
        },
    ),
    LLMTool(
        name="get_account_breakdown",
        description="Get cost breakdown by AWS account for a date range. Useful for multi-account organizations.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format, or 'yesterday', '7_days_ago', etc.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Optional.",
                },
            },
            "required": ["start_date"],
        },
    ),
    LLMTool(
        name="get_top_services",
        description="Get the top N services by cost for a date range. Returns services sorted by cost descending.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format, or 'yesterday', '7_days_ago', etc.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Optional.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of top services to return. Default 10, max 20.",
                },
            },
            "required": ["start_date"],
        },
    ),
]

# Learned-memory navigation tools (P3a). Registered alongside COST_TOOLS when the
# bot has a deep-memory store available.
MEMORY_TOOLS: list[LLMTool] = [
    LLMTool(
        name="list_memory",
        description="List all learned-memory concepts and show the index. Use this first to see what durable facts have been captured about this user's infrastructure.",
        parameters={"type": "object", "properties": {}},
    ),
    LLMTool(
        name="search_memory",
        description="Search learned memory for concepts relevant to a topic (service name, keyword, pattern). Returns matching concepts with excerpts.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for (e.g. a service name like 'NAT' or a topic like 'baseline').",
                },
            },
            "required": ["query"],
        },
    ),
    LLMTool(
        name="read_memory_concept",
        description="Read the full contents of one learned-memory concept file by its path (as returned by list_memory or search_memory).",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Concept path, e.g. 'services/nat-gateway-baseline.md'.",
                },
            },
            "required": ["path"],
        },
    ),
    LLMTool(
        name="remember_fact",
        description="Save a durable fact to memory when the user asks you to remember something (e.g. 'remember this', 'note that X is expected'). Distill the fact from the conversation into a clear, self-contained statement. The fact is folded into memory by the curator and will inform future cost assessments.",
        parameters={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "The durable fact to remember, as a clear self-contained statement (e.g. 'Cost Explorer charges ~$0.05/week from cost-query API usage; this is expected overhead, not an anomaly').",
                },
                "why": {
                    "type": "string",
                    "description": "Optional short reason/context for why this is true or was decided.",
                },
            },
            "required": ["summary"],
        },
    ),
]