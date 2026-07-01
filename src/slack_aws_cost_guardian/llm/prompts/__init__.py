"""LLM prompts for cost analysis."""

from slack_aws_cost_guardian.llm.prompts.system_prompt import SYSTEM_PROMPT
from slack_aws_cost_guardian.llm.prompts.analysis_prompts import (
    build_anomaly_analysis_prompt,
    build_daily_report_prompt,
    build_weekly_report_prompt,
)
from slack_aws_cost_guardian.llm.prompts.curator_prompt import (
    CURATOR_SYSTEM_PROMPT,
    build_curator_prompt,
)

__all__ = [
    "SYSTEM_PROMPT",
    "build_anomaly_analysis_prompt",
    "build_daily_report_prompt",
    "build_weekly_report_prompt",
    "CURATOR_SYSTEM_PROMPT",
    "build_curator_prompt",
]