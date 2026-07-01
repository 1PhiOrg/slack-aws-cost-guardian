"""
Learned-memory tools for the Slack bot (P3a - read side).

These let the conversational bot consult deep memory (the OKF concept files the
curator writes) when answering questions - so feedback the user gave on past
alerts actually informs future answers. This is where deep memory, which is
write-only through P2, finally gets read. See docs/MEMORY-SYSTEM.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from slack_aws_cost_guardian.llm.tools.registry import ToolRegistry
    from slack_aws_cost_guardian.storage.deep_memory import DeepMemoryStore
    from slack_aws_cost_guardian.storage.dynamodb import DynamoDBStorage


def register_memory_tools(registry: ToolRegistry, deep_store: DeepMemoryStore) -> None:
    """Register the deep-memory navigation tools onto an existing registry."""

    def list_memory() -> dict[str, Any]:
        """List all learned-memory concepts and the index."""
        concepts = deep_store.list_concept_paths()
        return {
            "concept_count": len(concepts),
            "concepts": concepts,
            "index": deep_store.read_index(),
        }

    def search_memory(query: str) -> dict[str, Any]:
        """Case-insensitive substring search across concept paths and bodies."""
        q = (query or "").strip().lower()
        matches = []
        for path, body in deep_store.read_all_concepts().items():
            if not q or q in path.lower() or q in body.lower():
                matches.append({"path": path, "excerpt": body[:500]})
        return {"query": query, "match_count": len(matches), "matches": matches}

    def read_memory_concept(path: str) -> dict[str, Any]:
        """Read a single learned-memory concept file by path."""
        content = deep_store.read_concept(path)
        if not content:
            return {"path": path, "found": False}
        return {"path": path, "found": True, "content": content}

    registry.register("list_memory", list_memory)
    registry.register("search_memory", search_memory)
    registry.register("read_memory_concept", read_memory_concept)


def register_remember_tool(
    registry: ToolRegistry,
    storage: DynamoDBStorage,
    trigger_curator: Callable[[], None] | None = None,
) -> None:
    """
    Register the remember_fact tool (P3b-C - the write side of conversation).

    When the user asks the bot to remember something, it records a candidate that
    the curator will fold into memory. If trigger_curator is provided, it fires
    the curator immediately so the fact takes effect without waiting for the
    scheduled backstop.
    """

    def remember_fact(summary: str, why: str | None = None) -> dict[str, Any]:
        """Record a durable fact the user asked to remember."""
        storage.put_memory_candidate(
            summary=summary, why=why, source="slack_conversation"
        )
        if trigger_curator is not None:
            try:
                trigger_curator()
            except Exception as e:  # non-fatal - the backstop will still consume it
                return {"remembered": True, "summary": summary, "curator_triggered": False, "note": str(e)}
        return {"remembered": True, "summary": summary, "curator_triggered": trigger_curator is not None}

    registry.register("remember_fact", remember_fact)