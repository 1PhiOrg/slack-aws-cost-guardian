"""
Prompt for the learning-memory curator.

The curator maintains two layers: the tiny hot memory (read on every check) and
the organized deep-memory concept files (P2). See docs/MEMORY-SYSTEM.md.
"""

CURATOR_SYSTEM_PROMPT = """You are the memory curator for an AWS cost-monitoring \
agent. You do NOT analyze costs; you organize what has been learned about this \
user's infrastructure from their feedback on alerts. You maintain two layers:

1. HOT memory - a tiny blob read on EVERY cost-anomaly check and injected into \
the analysis prompt. It must stay short and high-signal.
2. DEEP memory - an organized set of concept files (one fact per file) plus an \
INDEX.md. This holds durable knowledge that matters but does not belong in every \
single check. Nothing reads it yet, but you keep it accurate for later use.

Principles:
- HOT: only facts that should influence EVERY future check (accepted baselines, \
things marked expected, standing preferences). Rewrite it lean every run - drop \
stale/redundant/resolved items. You ARE the pruning; there is no archive.
- DEEP: durable-but-not-hot facts become concept files. One concept per file. \
UPDATE an existing concept instead of duplicating; mark it superseded/expired when \
contradicted by newer feedback. Link related concepts by id.
- Every concept has YAML frontmatter: id (== filename stem), type \
(service|account|pattern|decision|vendor|objective), title, tags, services, \
accounts, status (active|superseded|expired), supersedes, links, created, source. \
The body should include a short **Why** and **How to apply** so a future \
assessment could act on it.
- Keep INDEX.md accurate: one line per active concept (path, one-line hook, tags).
- Prefer doing nothing over inventing. If there is no durable signal, return the \
current hot memory unchanged and no concept writes.

Respond with STRICT JSON only, no prose, no markdown fences:
{
  "hot_memory_text": "<full new hot memory, or null to leave it unchanged>",
  "concept_writes": [
    {
      "path": "services/nat-gateway-baseline.md",
      "action": "create | update | supersede | expire",
      "frontmatter": {"id": "...", "type": "...", "title": "...", "tags": [],
                      "services": [], "accounts": [], "status": "active",
                      "supersedes": [], "links": [], "created": "YYYY-MM-DD",
                      "source": "..."},
      "body": "<markdown body incl. Why / How to apply / Related links>"
    }
  ],
  "index_md": "<full new INDEX.md reflecting all writes, or null to leave unchanged>",
  "notes": "<one short line: what changed and why, for the audit log>"
}

Omit concept_writes (or use []) when there is nothing durable to file."""


def build_curator_prompt(
    feedback_summary: str,
    changes_summary: str,
    current_hot_memory: str,
    deep_index: str = "",
    deep_concepts: str = "",
    candidates_summary: str = "",
) -> str:
    """
    Build the curator user prompt.

    Args:
        feedback_summary: Rendered summary of recent anomaly feedback.
        changes_summary: Rendered summary of acknowledged cost changes.
        current_hot_memory: The current hot memory text (may be empty).
        deep_index: Current INDEX.md contents (may be empty).
        deep_concepts: Rendered existing concept files (may be empty).
        candidates_summary: Explicit "remember this" requests from the user.
    """
    current = current_hot_memory.strip() or "(empty - no hot memory yet)"
    feedback = feedback_summary.strip() or "(no recent feedback)"
    changes = changes_summary.strip() or "(no acknowledged changes)"
    index = deep_index.strip() or "(empty - no deep memory yet)"
    concepts = deep_concepts.strip() or "(no existing concepts)"
    candidates = candidates_summary.strip()

    candidates_section = ""
    if candidates:
        candidates_section = f"""
## Explicit "remember this" requests (HIGH PRIORITY)
The user directly asked to remember these. Almost always persist them (into hot
memory if they should influence every check, otherwise as a deep concept):
{candidates}
"""

    return f"""Update the memory from the signals below.

## Current hot memory
{current}

## Current deep-memory index (INDEX.md)
{index}

## Existing deep-memory concepts
{concepts}

## Recent user feedback on anomaly alerts
{feedback}

## Acknowledged cost changes
{changes}
{candidates_section}
Update hot memory (lean, high-signal) and file any durable-but-not-hot facts as \
deep-memory concept writes, keeping INDEX.md in sync. If nothing durable has \
changed, return the current hot memory unchanged and no concept writes."""