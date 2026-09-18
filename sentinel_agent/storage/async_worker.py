"""Asynchronous non-blocking background memory worker for embedding consolidation and session compaction."""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Callable
from typing import Any

from sentinel_agent.storage.compaction import history_compactor
from sentinel_agent.storage.database import db_manager
from sentinel_agent.storage.vector_store import vector_store
from sentinel_agent.telemetry.tracer import tracer


class AsyncMemoryWorker:
    """Non-blocking background worker executing memory consolidation, vector indexing, and history compaction."""

    def __init__(self) -> None:
        self._task_queue: queue.Queue[
            tuple[str, Callable[..., Any], tuple[Any, ...], dict[str, Any]]
        ] = queue.Queue()
        self.completed_jobs: list[dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._run_loop,
            name="SentinelAsyncMemoryWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_name, func, args, kwargs = self._task_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            with tracer.start_span(
                f"async_memory_job:{job_name}",
                attributes={"job.name": job_name, "execution.mode": "background_async"},
            ) as (_, trace_id, span_id):
                try:
                    result = func(*args, **kwargs)
                    self.completed_jobs.append(
                        {
                            "job_name": job_name,
                            "status": "COMPLETED",
                            "trace_id": trace_id,
                            "span_id": span_id,
                            "result": result,
                        }
                    )
                except Exception as exc:
                    self.completed_jobs.append(
                        {
                            "job_name": job_name,
                            "status": "FAILED",
                            "trace_id": trace_id,
                            "span_id": span_id,
                            "error": str(exc),
                        }
                    )
                finally:
                    self._task_queue.task_done()

    def submit_background_job(
        self, job_name: str, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> str:
        """Enqueue an expensive memory or vector indexing job without blocking the main agent turn."""
        self._task_queue.put((job_name, func, args, kwargs))
        return job_name

    async def consolidate_turn_async(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        model_used: str,
    ) -> dict[str, Any]:
        """Asynchronously persist conversation turns and trigger non-blocking sliding-window compaction."""

        def _persist_and_compact() -> dict[str, Any]:
            db_manager.append_session_message(session_id, "user", user_message, model_used)
            db_manager.append_session_message(
                session_id, "assistant", assistant_message, model_used
            )
            messages = db_manager.get_session_messages(session_id)
            return history_compactor.compact_history(session_id, messages)

        return await asyncio.to_thread(_persist_and_compact)

    def enqueue_postmortem_indexing(
        self,
        action_id: str,
        incident_id: str,
        service_domain: str,
        remediation_summary: str,
        preventative_measure: str,
    ) -> str:
        """Asynchronously embed a newly recorded postmortem into the Vector RAG knowledge base."""
        return self.submit_background_job(
            f"index_postmortem_{action_id}",
            vector_store.upsert_document,
            doc_id=f"POSTMORTEM-{action_id}",
            title=f"Postmortem Learning for {incident_id}",
            service_domain=service_domain,
            section_anchor=f"https://runbooks.internal.example/postmortems/{incident_id}#{action_id.lower()}",
            content=f"{remediation_summary}. Preventative measure: {preventative_measure}",
            remediation_steps=[remediation_summary, preventative_measure],
        )

    def flush(self, timeout: float = 5.0) -> None:
        """Wait for queued background memory tasks to complete (useful in deterministic tests)."""
        self._task_queue.join()


async_memory_worker = AsyncMemoryWorker()
