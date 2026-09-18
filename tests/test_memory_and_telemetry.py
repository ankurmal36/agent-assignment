"""Unit tests for Context & Memory (SQLite, Vector RAG, Compaction, AsyncWorker) and Observability (OTel, Intent/Outcome, PII Redaction)."""

from __future__ import annotations

from pathlib import Path

from sentinel_agent.storage.async_worker import async_memory_worker
from sentinel_agent.storage.compaction import HistoryCompactor
from sentinel_agent.storage.database import PersistentSessionDatabase
from sentinel_agent.storage.vector_store import vector_store
from sentinel_agent.telemetry.tracer import pii_redactor, tracer


def test_pii_redaction_and_intent_outcome_capture() -> None:
    """Verify PIIRedactor scrubs emails, SSNs, phones, and API keys, and tracer records INTENT vs OUTCOME."""
    raw = (
        "Contact engineer jane.doe@google.com or 415-555-0199 with SSN 123-45-6789 "
        "and key AIzaSyD1234567890abcdefghijklmno"
    )
    scrubbed = pii_redactor.redact_text(raw)
    assert "jane.doe@google.com" not in scrubbed
    assert "415-555-0199" not in scrubbed
    assert "123-45-6789" not in scrubbed
    assert "AIzaSyD1234567890abcdefghijklmno" not in scrubbed
    assert "[REDACTED_EMAIL]" in scrubbed
    assert "[REDACTED_PHONE]" in scrubbed
    assert "[REDACTED_SSN]" in scrubbed
    assert "[REDACTED_API_KEY]" in scrubbed

    with tracer.start_span(
        "test.custom_operation", attributes={"user.email": "bob@example.com"}
    ) as (
        _,
        trace_id,
        span_id,
    ):
        rec = tracer.log_intent_before_execution(
            trace_id=trace_id,
            span_id=span_id,
            agent_name="TestAgent",
            action_name="verify_intent_outcome",
            planned_arguments={"target": "bob@example.com"},
            rationale="Testing dual-phase intent vs outcome capture",
        )
        tracer.log_outcome_after_execution(
            record=rec,
            actual_result={"result": "ok", "leaked_phone": "650-555-1234"},
            status="SUCCESS",
            start_time=0.0,
        )

    assert rec.intent_phase["phase"] == "INTENT"
    assert rec.intent_phase["planned_arguments"]["target"] == "[REDACTED_EMAIL]"
    assert rec.outcome_phase["phase"] == "OUTCOME"
    assert rec.outcome_phase["actual_result"]["leaked_phone"] == "[REDACTED_PHONE]"


def test_history_compaction_and_sqlite_persistence(tmp_path: Path) -> None:
    """Verify sliding-window history compaction summarizes evicted turns into SQLite."""
    temp_db = PersistentSessionDatabase(db_path=str(tmp_path / "test_state.db"))
    compactor = HistoryCompactor(database=temp_db, max_tokens=120, sliding_window_turns=4)

    session_id = "compact-test-session"
    for idx in range(8):
        temp_db.append_session_message(
            session_id=session_id,
            role="user" if idx % 2 == 0 else "assistant",
            content=f"Turn {idx}: Investigating latency and connection pool metrics on checkout service.",
            model_used="gemini-2.5-flash",
        )

    all_msgs = temp_db.get_session_messages(session_id)
    assert len(all_msgs) == 8

    compacted_result = compactor.compact_history(session_id, all_msgs)
    assert compacted_result["compacted"] is True
    assert len(compacted_result["active_messages"]) <= 4
    assert "Compacted Session Context Summary:" in compacted_result["summary"]

    stored_summary = temp_db.get_session_summary(session_id)
    assert stored_summary is not None
    assert stored_summary["compacted_turns"] >= 4


def test_async_memory_worker_and_vector_rag() -> None:
    """Verify AsyncMemoryWorker indexes postmortem learnings in background and makes them searchable via RAG."""
    job_id = async_memory_worker.enqueue_postmortem_indexing(
        action_id="PM-TEST99",
        incident_id="INC-9999",
        service_domain="checkout-payment-service",
        remediation_summary="Mitigated Kafka consumer lag spike by scaling partition workers.",
        preventative_measure="Added consumer lag autoscaling policy alert.",
    )
    assert job_id == "index_postmortem_PM-TEST99"
    async_memory_worker.flush()

    results = vector_store.search("Kafka consumer lag partition workers", top_k=3)
    assert len(results) >= 1
    assert any(r["doc_id"] == "POSTMORTEM-PM-TEST99" for r in results)
