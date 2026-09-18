"""Persistent SQLite relational database for session state, incident tickets, postmortem notes, and rollback audit logs."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinel_agent.config import settings
from sentinel_agent.telemetry.tracer import pii_redactor


class PersistentSessionDatabase:
    """Thread-safe SQLite database backing conversational session state, incidents, and postmortem memory."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path or settings.sqlite_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS session_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model_used TEXT DEFAULT '',
                    token_estimate INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_summaries (
                    session_id TEXT PRIMARY KEY,
                    summary_text TEXT NOT NULL,
                    compacted_turns INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS incident_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    service_name TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    root_cause_hypothesis TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS postmortem_actions (
                    action_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    owner_team TEXT NOT NULL,
                    remediation_summary TEXT NOT NULL,
                    preventative_measure TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def append_session_message(
        self,
        session_id: str,
        role: str,
        content: str,
        model_used: str = "",
    ) -> dict[str, Any]:
        """Persist a PII-scrubbed turn into SQLite session state."""
        safe_content = pii_redactor.redact_text(content)
        token_estimate = max(1, len(safe_content.split()) * 4 // 3)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_messages (session_id, role, content, model_used, token_estimate, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, safe_content, model_used, token_estimate, now),
            )
            conn.commit()
        return {
            "session_id": session_id,
            "role": role,
            "content": safe_content,
            "token_estimate": token_estimate,
            "created_at": now,
        }

    def get_session_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve ordered conversation history for a session from SQLite."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT role, content, model_used, token_estimate, created_at
                FROM session_messages
                WHERE session_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (session_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def upsert_session_summary(
        self, session_id: str, summary_text: str, compacted_turns: int
    ) -> None:
        """Persist a compacted rolling summary for a session."""
        safe_summary = pii_redactor.redact_text(summary_text)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_summaries (session_id, summary_text, compacted_turns, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    compacted_turns = excluded.compacted_turns,
                    updated_at = excluded.updated_at
                """,
                (session_id, safe_summary, compacted_turns, now),
            )
            conn.commit()

    def get_session_summary(self, session_id: str) -> dict[str, Any] | None:
        """Fetch the rolling summary for a session if compaction has occurred."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "SELECT session_id, summary_text, compacted_turns, updated_at FROM session_summaries WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_incident(
        self,
        service_name: str,
        severity: str,
        title: str,
        root_cause_hypothesis: str,
    ) -> dict[str, Any]:
        """Persist a new incident ticket in SQLite."""
        ticket_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        safe_title = pii_redactor.redact_text(title)
        safe_hypothesis = pii_redactor.redact_text(root_cause_hypothesis)
        record = {
            "ticket_id": ticket_id,
            "service_name": service_name,
            "severity": severity.upper(),
            "title": safe_title,
            "root_cause_hypothesis": safe_hypothesis,
            "status": "OPEN",
            "created_at": now,
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO incident_tickets (ticket_id, service_name, severity, title, root_cause_hypothesis, status, created_at)
                VALUES (:ticket_id, :service_name, :severity, :title, :root_cause_hypothesis, :status, :created_at)
                """,
                record,
            )
            conn.commit()
        return record

    def list_incidents(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent incident tickets from SQLite."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM incident_tickets ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def record_postmortem_action(
        self,
        incident_id: str,
        owner_team: str,
        remediation_summary: str,
        preventative_measure: str,
    ) -> dict[str, Any]:
        """Persist a postmortem action item in SQLite."""
        action_id = f"PM-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "action_id": action_id,
            "incident_id": incident_id,
            "owner_team": pii_redactor.redact_text(owner_team),
            "remediation_summary": pii_redactor.redact_text(remediation_summary),
            "preventative_measure": pii_redactor.redact_text(preventative_measure),
            "created_at": now,
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO postmortem_actions (action_id, incident_id, owner_team, remediation_summary, preventative_measure, created_at)
                VALUES (:action_id, :incident_id, :owner_team, :remediation_summary, :preventative_measure, :created_at)
                """,
                record,
            )
            conn.commit()
        return record

    def list_postmortem_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recorded postmortem action items from SQLite."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM postmortem_actions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def export_state_snapshot(self) -> str:
        """Serialize current SQLite state summary as JSON for diagnostics."""
        return json.dumps(
            {
                "incidents": self.list_incidents(limit=10),
                "postmortems": self.list_postmortem_actions(limit=10),
            },
            indent=2,
        )


db_manager = PersistentSessionDatabase()
