"""Storage layer exposing persistent SQLite state, Vector RAG store, History Compactor, Async Worker, and Secret Manager."""

from __future__ import annotations

from typing import Any

from sentinel_agent.storage.secret_manager import SecretManagerVault

__all__ = [
    "AsyncMemoryWorker",
    "HistoryCompactor",
    "PersistentSessionDatabase",
    "RunbookVectorStore",
    "SecretManagerVault",
    "async_memory_worker",
    "db_manager",
    "history_compactor",
    "vector_store",
]


def __getattr__(name: str) -> Any:
    if name in {"AsyncMemoryWorker", "async_memory_worker"}:
        from sentinel_agent.storage import async_worker

        return getattr(async_worker, name)
    if name in {"HistoryCompactor", "history_compactor"}:
        from sentinel_agent.storage import compaction

        return getattr(compaction, name)
    if name in {"PersistentSessionDatabase", "db_manager"}:
        from sentinel_agent.storage import database

        return getattr(database, name)
    if name in {"RunbookVectorStore", "vector_store"}:
        from sentinel_agent.storage import vector_store as vs

        return getattr(vs, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
