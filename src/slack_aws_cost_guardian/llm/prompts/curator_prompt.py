"""
Prompt for the learning-memory curator (P1).

The curator keeps the tiny "hot" memory accurate and lean. In P1 it only
maintains the hot memory text; deep-memory concept writes (P2) are not yet
emitted. See docs/MEMORY-SYSTEM.md.
"""

CURATOR_SYSTEM_PROMPT = """You are the memory curator for an AWS cost-monitoring \
agent. You maintain a tiny "hot" memory that is read on EVERY cost-anomaly check \
and injected into the analysis prompt, so it must stay short and high-signal. You \
do NOT analyze costs; you organize what has been learned about this user's \
infrastructure from their feedback on alerts.

Principles:
- Hot memory is a small working set. Only durable facts that should influence \
EVERY future cost check belong there (accepted baselines, things the user has \
marked expected, standing preferences about what is/isn't worth surfacing).
- Rewrite it lean every run: drop anything stale, redundant, resolved, or too \
specific to a single past day. You ARE the pruning - there is no archive.
- Prefer a short, scannable set of plain statements over a log of events.
- Fold new feedback into existing statements rather than appending duplicates.
- Expire anything contradicted by newer feedback.
- Prefer doing nothing over inventing. If there is no durable signal, return the \
current hot memory unchanged.

Respond with STRICT JSON only, no prose, no markdown fences:
{
  "hot_memory_text": "<full new hot memory, or null to leave it unchanged>",
  "notes": "<one short line: what changed and why, for the audit log>"
}"""


def build_curator_prompt(
    feedback_summary: str,
    changes_summary: str,
    current_hot_memory: str,
) -> str:
    """
    Build the curator user prompt.

    Args:
        feedback_summary: Rendered summary of recent anomaly feedback.
        changes_summary: Rendered summary of acknowledged cost changes.
        current_hot_memory: The current hot memory text (may be empty).
    """
    current = current_hot_memory.strip() or "(empty - no hot memory yet)"
    feedback = feedback_summary.strip() or "(no recent feedback)"
    changes = changes_summary.strip() or "(no acknowledged changes)"

    return f"""Update the hot memory from the signals below.

## Current hot memory
{current}

## Recent user feedback on anomaly alerts
{feedback}

## Acknowledged cost changes
{changes}

Produce the new hot memory. Keep it lean and high-signal. If nothing durable has \
changed, return the current hot memory unchanged (or null)."""