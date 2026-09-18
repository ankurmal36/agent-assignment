"""Context Window Compaction: Token-budget truncation, rolling summarization, and Google ADK EventsCompactionConfig."""

from __future__ import annotations

from typing import Any

from sentinel_agent.config import settings
from sentinel_agent.storage.database import PersistentSessionDatabase, db_manager


class HistoryCompactor:
    """Manages conversational context bloat using sliding windows, token-budget truncation, and rolling summaries."""

    def __init__(
        self,
        database: PersistentSessionDatabase | None = None,
        max_tokens: int | None = None,
        sliding_window_turns: int | None = None,
    ) -> None:
        self.db = database or db_manager
        self.max_tokens = max_tokens or settings.max_context_tokens
        self.sliding_window_turns = sliding_window_turns or settings.sliding_window_turns

    @staticmethod
    def estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """Estimate token usage across a message list."""
        total = 0
        for msg in messages:
            content = str(msg.get("content", ""))
            total += int(msg.get("token_estimate") or max(1, len(content.split()) * 4 // 3))
        return total

    def compact_history(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Compact conversation history when turn count or token count exceeds configured thresholds.

        Older turns outside the active sliding window are distilled into a persistent rolling summary
        stored in SQLite so context stays bounded while preserving critical incident facts.
        """
        total_tokens = self.estimate_tokens(messages)
        if len(messages) <= self.sliding_window_turns and total_tokens <= self.max_tokens:
            existing_summary = self.db.get_session_summary(session_id)
            return {
                "compacted": False,
                "summary": existing_summary["summary_text"] if existing_summary else "",
                "active_messages": messages,
                "total_tokens_before": total_tokens,
                "total_tokens_after": total_tokens,
            }

        cutoff = max(1, len(messages) - self.sliding_window_turns)
        evicted_messages = messages[:cutoff]
        retained_messages = messages[cutoff:]

        # Enforce token budget on retained messages as well
        while (
            len(retained_messages) > 2 and self.estimate_tokens(retained_messages) > self.max_tokens
        ):
            evicted_messages.append(retained_messages.pop(0))

        bullet_points: list[str] = []
        for msg in evicted_messages[-6:]:
            role = msg.get("role", "user").upper()
            snippet = str(msg.get("content", ""))[:140].replace("\n", " ")
            bullet_points.append(f"[{role}] {snippet}")

        summary_text = "Compacted Session Context Summary: " + " | ".join(bullet_points)
        self.db.upsert_session_summary(
            session_id=session_id,
            summary_text=summary_text,
            compacted_turns=len(evicted_messages),
        )
        tokens_after = self.estimate_tokens(retained_messages)
        return {
            "compacted": True,
            "summary": summary_text,
            "evicted_turn_count": len(evicted_messages),
            "active_messages": retained_messages,
            "total_tokens_before": total_tokens,
            "total_tokens_after": tokens_after,
        }

    @staticmethod
    def build_adk_compaction_config(compaction_interval: int = 6, overlap_size: int = 2) -> Any:
        """Build a Google ADK EventsCompactionConfig when running inside an ADK App."""
        try:
            from google.adk.apps.app import EventsCompactionConfig

            return EventsCompactionConfig(
                compaction_interval=compaction_interval,
                overlap_size=overlap_size,
            )
        except Exception:
            return {
                "compaction_interval": compaction_interval,
                "overlap_size": overlap_size,
            }


history_compactor = HistoryCompactor()
