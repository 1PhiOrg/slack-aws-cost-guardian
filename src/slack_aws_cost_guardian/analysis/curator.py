"""
Learning-memory curator (P1).

Reads recent anomaly feedback and acknowledged changes, asks the LLM to fold the
durable signal into a lean "hot" memory, and writes the result back. This is the
closed loop: feedback the user gives on alerts becomes context the agent applies
to every future anomaly check. See docs/MEMORY-SYSTEM.md.

P1 maintains hot memory only; deep-memory concept writes arrive in P2.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from slack_aws_cost_guardian.llm.base import LLMMessage
from slack_aws_cost_guardian.llm.prompts import (
    CURATOR_SYSTEM_PROMPT,
    build_curator_prompt,
)
from slack_aws_cost_guardian.storage.deep_memory import render_concept

if TYPE_CHECKING:
    from slack_aws_cost_guardian.llm.client import LLMClient
    from slack_aws_cost_guardian.storage.deep_memory import DeepMemoryStore
    from slack_aws_cost_guardian.storage.dynamodb import DynamoDBStorage
    from slack_aws_cost_guardian.storage.models import AnomalyFeedback, ChangeLog


def summarize_feedback(feedback: list[AnomalyFeedback], limit: int = 50) -> str:
    """Render anomaly feedback into a compact, model-readable summary."""
    if not feedback:
        return ""
    # Most recent first, capped to keep the prompt lean.
    ordered = sorted(feedback, key=lambda f: f.timestamp, reverse=True)[:limit]
    lines = []
    for f in ordered:
        services = ", ".join(f.affected_services) or "unspecified service"
        note = (f.explanation or "").strip() or "(no note)"
        lines.append(
            f"- [{f.feedback_type.value}] {services}: {note} "
            f"(impact ${f.cost_impact:.2f}, {f.duration_type.value}, {f.date})"
        )
    return "\n".join(lines)


def summarize_changes(changes: list[ChangeLog], limit: int = 50) -> str:
    """Render acknowledged cost changes into a compact summary."""
    if not changes:
        return ""
    ordered = sorted(changes, key=lambda c: c.date, reverse=True)[:limit]
    lines = []
    for c in ordered:
        lines.append(
            f"- [{c.change_type.value}] {c.service}: {c.description} "
            f"({c.percent_change:+.0f}%, {c.status.value}, {c.date})"
        )
    return "\n".join(lines)


def summarize_candidates(candidates: list[dict]) -> str:
    """Render explicit 'remember this' candidates for the curator prompt."""
    if not candidates:
        return ""
    lines = []
    for c in candidates:
        summary = (c.get("summary") or "").strip()
        why = (c.get("why") or "").strip()
        line = f"- {summary}"
        if why:
            line += f" (why: {why})"
        lines.append(line)
    return "\n".join(lines)


def _newest_signal_ts(
    feedback: list[AnomalyFeedback],
    changes: list[ChangeLog],
    candidates: list[dict] | None = None,
) -> str | None:
    """
    Newest signal timestamp across feedback, changes, and candidates (ISO-8601,
    lexically comparable). Used as the curator watermark. Returns None if there
    is no signal.
    """
    stamps = [f.timestamp for f in feedback if f.timestamp]
    stamps += [c.acknowledged_at for c in changes if getattr(c, "acknowledged_at", None)]
    stamps += [c.get("created") for c in (candidates or []) if c.get("created")]
    return max(stamps) if stamps else None


def _extract_json(text: str) -> dict | None:
    """
    Parse a JSON object from an LLM response, tolerating markdown fences and
    surrounding prose. Returns None if no object can be parsed.
    """
    if not text:
        return None
    candidate = text.strip()
    # Strip a leading ```json / ``` fence if present.
    if candidate.startswith("```"):
        candidate = candidate.split("```", 2)
        candidate = candidate[1] if len(candidate) > 1 else text
        if candidate.lstrip().startswith("json"):
            candidate = candidate.lstrip()[4:]
    # Fall back to the outermost braces.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class MemoryCurator:
    """Folds recent feedback into the hot learning memory."""

    def __init__(
        self,
        storage: DynamoDBStorage,
        llm_client: LLMClient,
        feedback_days: int = 30,
        deep_store: DeepMemoryStore | None = None,
    ):
        """
        Args:
            storage: DynamoDB storage client.
            llm_client: Configured LLM client (a Haiku-class model is recommended
                for cost - the task is organize, not deep reasoning).
            feedback_days: How many days of feedback to consider.
            deep_store: Optional S3 deep-memory store. When provided, the curator
                also files durable-but-not-hot facts as concept files (P2). When
                None, it maintains hot memory only.
        """
        self.storage = storage
        self.llm_client = llm_client
        self.feedback_days = feedback_days
        self.deep_store = deep_store

    def _apply_concept_writes(self, concept_writes: list[dict]) -> dict[str, list]:
        """Write each concept file to the deep store. Best-effort per file."""
        written, skipped = [], []
        for w in concept_writes or []:
            path = w.get("path")
            if not path:
                skipped.append({"path": path, "reason": "no_path"})
                continue
            content = render_concept(w.get("frontmatter") or {}, w.get("body") or "")
            if self.deep_store.write_concept(path, content):
                written.append(path)
            else:
                skipped.append({"path": path, "reason": "unsafe_path"})
        return {"written": written, "skipped": skipped}

    def run(self, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
        """
        Run one curation pass.

        The curator is trigger-agnostic - it is normally invoked event-driven
        (right after feedback is given) with a scheduled backstop. A cheap
        watermark gate skips the LLM call entirely when there is no signal newer
        than the last pass, so any trigger is safe to fire often.

        Args:
            dry_run: If True, compute the new hot memory but do not persist it.
            force: If True, bypass the watermark gate (used by manual/test runs).

        Returns:
            A result dict describing what happened (suitable for a Lambda response
            and an audit log).
        """
        feedback = self.storage.get_recent_feedback(days=self.feedback_days)
        changes = self.storage.get_active_changes()
        candidates = self.storage.get_pending_candidates()
        current_hot = self.storage.get_hot_memory()
        newest = _newest_signal_ts(feedback, changes, candidates)
        watermark = self.storage.get_last_curated_at()

        result: dict[str, Any] = {
            "changed": False,
            "dry_run": dry_run,
            "forced": force,
            "feedback_count": len(feedback),
            "changes_count": len(changes),
            "candidate_count": len(candidates),
            "previous_chars": len(current_hot),
            "watermark": watermark,
        }

        if not feedback and not changes and not candidates:
            result["reason"] = "no_signal"
            return result

        # Gate: nothing new to consolidate since the last pass.
        if not force and watermark and newest and newest <= watermark:
            result["reason"] = "no_new_signal"
            return result

        # Load deep-memory context so the curator can update rather than duplicate.
        deep_index, deep_concepts = "", ""
        if self.deep_store is not None:
            try:
                deep_index = self.deep_store.read_index()
                concepts = self.deep_store.read_all_concepts()
                deep_concepts = "\n\n".join(
                    f"### {path}\n{body}" for path, body in concepts.items()
                )
            except Exception as e:  # deep read failure shouldn't block hot curation
                result["deep_read_error"] = str(e)

        user_prompt = build_curator_prompt(
            feedback_summary=summarize_feedback(feedback),
            changes_summary=summarize_changes(changes),
            current_hot_memory=current_hot,
            deep_index=deep_index,
            deep_concepts=deep_concepts,
            candidates_summary=summarize_candidates(candidates),
        )
        messages = [
            LLMMessage(role="system", content=CURATOR_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        try:
            response = self.llm_client.chat(messages)
        except Exception as e:  # graceful degradation - never crash the trigger
            result["reason"] = "llm_error"
            result["error"] = str(e)
            return result

        parsed = _extract_json(response.content)
        if parsed is None:
            # Don't advance the watermark - retry on the next trigger.
            result["reason"] = "unparseable_response"
            return result

        result["notes"] = (parsed.get("notes") or "").strip()

        new_hot = parsed.get("hot_memory_text")
        if new_hot is None:
            result["reason"] = "left_unchanged"
        elif str(new_hot).strip() == current_hot.strip():
            result["reason"] = "no_change"
        else:
            new_hot = str(new_hot).strip()
            result["new_chars"] = len(new_hot)
            if not dry_run:
                # put_hot_memory replaces the item; set_last_curated_at (below)
                # re-adds the watermark via a merge update, so order matters.
                self.storage.put_hot_memory(new_hot)
            result["changed"] = True
            result["new_hot_memory"] = new_hot

        # Deep memory (P2): file durable-but-not-hot facts as concept files and
        # keep INDEX.md in sync. Best-effort - never blocks hot consolidation.
        concept_writes = parsed.get("concept_writes") or []
        index_md = parsed.get("index_md")
        result["concept_writes_proposed"] = len(concept_writes)
        if self.deep_store is not None and not dry_run:
            try:
                applied = self._apply_concept_writes(concept_writes)
                wrote_any = bool(applied["written"])
                if index_md is not None:
                    self.deep_store.write_index(str(index_md))
                    wrote_any = True
                if wrote_any:
                    result["memory_version"] = self.storage.bump_memory_version()
                result["concepts_written"] = len(applied["written"])
                result["concepts_skipped"] = len(applied["skipped"])
                if applied["skipped"]:
                    result["skipped_detail"] = applied["skipped"]
                result["index_updated"] = index_md is not None
            except Exception as e:  # deep-write failure is non-fatal
                result["deep_write_error"] = str(e)

        # Candidates were consolidated into memory - delete them so they don't
        # re-feed on the next pass. (Feedback/changes are governed by the
        # watermark instead; candidates are one-shot.)
        if not dry_run and candidates:
            try:
                self.storage.delete_candidates(candidates)
                result["candidates_consumed"] = len(candidates)
            except Exception as e:
                result["candidate_delete_error"] = str(e)

        # Signal was consolidated - advance the watermark so the next trigger
        # is a cheap no-op until fresh feedback arrives.
        if not dry_run and newest:
            self.storage.set_last_curated_at(newest)

        return result