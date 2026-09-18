"""Observability, OpenTelemetry Distributed Tracing, Structured JSON Logging, Intent vs Outcome Capture, and PII Redaction."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from sentinel_agent.config import settings


class InMemorySpanCollector(SpanExporter):
    """Collects OpenTelemetry spans in memory for runtime inspection and automated evaluation suites."""

    def __init__(self) -> None:
        self.exported_spans: list[dict[str, Any]] = []

    def export(self, spans: Any) -> SpanExportResult:
        for span in spans:
            ctx = span.get_span_context()
            parent_id = f"{span.parent.span_id:016x}" if span.parent else None
            self.exported_spans.append(
                {
                    "name": span.name,
                    "trace_id": f"{ctx.trace_id:032x}",
                    "span_id": f"{ctx.span_id:016x}",
                    "parent_span_id": parent_id,
                    "start_time_ns": span.start_time,
                    "end_time_ns": span.end_time,
                    "attributes": dict(span.attributes or {}),
                }
            )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


class PIIRedactor:
    """Scrubs sensitive PII and credentials from logs and memory using regex rules and optional Google Cloud DLP."""

    _PATTERNS: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
        (
            re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
            "[REDACTED_PHONE]",
        ),
        (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[REDACTED_CARD]"),
        (
            re.compile(
                r"\b(?:AIza[0-9A-Za-z\-_]{20,}|sk-[0-9A-Za-z]{20,}|ya29\.[0-9A-Za-z\-_]+)\b"
            ),
            "[REDACTED_API_KEY]",
        ),
    ]

    def __init__(self, project_id: str | None = None, use_cloud_dlp: bool = False) -> None:
        self.project_id = project_id or settings.gcp_project_id
        self.use_cloud_dlp = use_cloud_dlp or settings.enable_cloud_dlp

    def redact_text(self, text: str) -> str:
        """Scrub sensitive PII tokens from a string using Cloud DLP (if enabled) and deterministic regex patterns."""
        if not text:
            return text

        scrubbed = text
        for pattern, replacement in self._PATTERNS:
            scrubbed = pattern.sub(replacement, scrubbed)

        if self.use_cloud_dlp and self.project_id:
            try:
                from google.cloud import dlp_v2

                dlp_client = dlp_v2.DlpServiceClient()
                parent = f"projects/{self.project_id}/locations/global"
                inspect_config = {
                    "info_types": [
                        {"name": "EMAIL_ADDRESS"},
                        {"name": "PHONE_NUMBER"},
                        {"name": "US_SOCIAL_SECURITY_NUMBER"},
                        {"name": "CREDIT_CARD_NUMBER"},
                    ]
                }
                deidentify_config = {
                    "info_type_transformations": {
                        "transformations": [
                            {"primitive_transformation": {"replace_with_info_type_config": {}}}
                        ]
                    }
                }
                response = dlp_client.deidentify_content(
                    request={
                        "parent": parent,
                        "inspect_config": inspect_config,
                        "deidentify_config": deidentify_config,
                        "item": {"value": scrubbed},
                    }
                )
                scrubbed = response.item.value
            except Exception:
                # Fallback cleanly to regex scrubbing when offline or without Cloud DLP credentials
                pass

        return scrubbed

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively scrub PII from dictionary values before logging or persistence."""
        sanitized: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = self.redact_text(value)
            elif isinstance(value, dict):
                sanitized[key] = self.redact_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self.redact_text(item)
                    if isinstance(item, str)
                    else (self.redact_dict(item) if isinstance(item, dict) else item)
                    for item in value
                ]
            else:
                sanitized[key] = value
        return sanitized


class StructuredJsonFormatter(logging.Formatter):
    """Formats Python log records as structured JSON objects with OpenTelemetry trace correlation and PII scrubbing."""

    def __init__(self, redactor: PIIRedactor) -> None:
        super().__init__()
        self.redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.redactor.redact_text(record.getMessage()),
            "event_type": getattr(record, "event_type", "AGENT_EVENT"),
            "trace_id": getattr(record, "trace_id", ""),
            "span_id": getattr(record, "span_id", ""),
            "agent_name": getattr(record, "agent_name", "SentinelCoordinatorAgent"),
        }
        extra_meta = getattr(record, "metadata", None)
        if isinstance(extra_meta, dict):
            payload["metadata"] = self.redactor.redact_dict(extra_meta)
        return json.dumps(payload, ensure_ascii=False)


@dataclass
class IntentOutcomeRecord:
    """Explicitly pairs an agent's intended action BEFORE execution with its actual outcome AFTER execution."""

    record_id: str
    trace_id: str
    span_id: str
    agent_name: str
    action_name: str
    intent_phase: dict[str, Any]
    outcome_phase: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    status: str = "PENDING"


class SentinelTelemetryTracer:
    """Unified OpenTelemetry distributed tracer, Intent/Outcome recorder, and Structured JSON logger."""

    def __init__(self) -> None:
        self.redactor = PIIRedactor()
        self.span_collector = InMemorySpanCollector()
        resource = Resource.create({"service.name": settings.otel_service_name})
        self.provider = TracerProvider(resource=resource)
        self.provider.add_span_processor(SimpleSpanProcessor(self.span_collector))
        trace.set_tracer_provider(self.provider)
        self.otel_tracer = trace.get_tracer(settings.otel_service_name)

        self.logger = logging.getLogger("sentinel_agent.telemetry")
        self.logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
        self.logger.propagate = False
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(StructuredJsonFormatter(self.redactor))
            self.logger.addHandler(handler)

        self.intent_outcome_history: list[IntentOutcomeRecord] = []
        self.structured_json_logs: list[dict[str, Any]] = []

    def emit_json_log(
        self,
        event_type: str,
        message: str,
        agent_name: str = "SentinelCoordinatorAgent",
        trace_id: str = "",
        span_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Emit a structured JSON log record with PII scrubbing and append to the inspectable buffer."""
        safe_message = self.redactor.redact_text(message)
        safe_metadata = self.redactor.redact_dict(metadata or {})
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "agent_name": agent_name,
            "trace_id": trace_id,
            "span_id": span_id,
            "message": safe_message,
            "metadata": safe_metadata,
        }
        self.structured_json_logs.append(log_entry)
        self.logger.info(
            safe_message,
            extra={
                "event_type": event_type,
                "agent_name": agent_name,
                "trace_id": trace_id,
                "span_id": span_id,
                "metadata": safe_metadata,
            },
        )
        return log_entry

    @contextmanager
    def start_span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> Iterator[tuple[Any, str, str]]:
        """Start an OpenTelemetry span and yield (span, trace_id, span_id)."""
        with self.otel_tracer.start_as_current_span(name) as span:
            if attributes:
                safe_attrs = self.redactor.redact_dict(attributes)
                for k, v in safe_attrs.items():
                    if isinstance(v, (str, int, float, bool)):
                        span.set_attribute(k, v)
                    else:
                        span.set_attribute(k, json.dumps(v))
            ctx = span.get_span_context()
            trace_id = f"{ctx.trace_id:032x}"
            span_id = f"{ctx.span_id:016x}"
            yield span, trace_id, span_id

    def log_intent_before_execution(
        self,
        trace_id: str,
        span_id: str,
        agent_name: str,
        action_name: str,
        planned_arguments: dict[str, Any],
        rationale: str,
    ) -> IntentOutcomeRecord:
        """Record the agent's explicit INTENT before executing a tool or sub-agent delegation."""
        safe_args = self.redactor.redact_dict(planned_arguments)
        safe_rationale = self.redactor.redact_text(rationale)
        record = IntentOutcomeRecord(
            record_id=str(uuid.uuid4()),
            trace_id=trace_id,
            span_id=span_id,
            agent_name=agent_name,
            action_name=action_name,
            intent_phase={
                "phase": "INTENT",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "planned_action": action_name,
                "planned_arguments": safe_args,
                "rationale": safe_rationale,
            },
        )
        self.intent_outcome_history.append(record)
        self.emit_json_log(
            event_type="INTENT_CAPTURED",
            message=f"[{agent_name}] Intended action: {action_name}",
            agent_name=agent_name,
            trace_id=trace_id,
            span_id=span_id,
            metadata=record.intent_phase,
        )
        return record

    def log_outcome_after_execution(
        self,
        record: IntentOutcomeRecord,
        actual_result: dict[str, Any],
        status: str,
        start_time: float,
    ) -> IntentOutcomeRecord:
        """Record the agent's actual OUTCOME after executing a tool or sub-agent delegation."""
        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        safe_result = self.redactor.redact_dict(actual_result)
        record.latency_ms = latency_ms
        record.status = status
        record.outcome_phase = {
            "phase": "OUTCOME",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "latency_ms": latency_ms,
            "actual_result": safe_result,
        }
        self.emit_json_log(
            event_type="OUTCOME_CAPTURED",
            message=f"[{record.agent_name}] Completed action: {record.action_name} ({status}) in {latency_ms}ms",
            agent_name=record.agent_name,
            trace_id=record.trace_id,
            span_id=record.span_id,
            metadata=record.outcome_phase,
        )
        return record

    def get_recent_traces(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return serialized Intent-vs-Outcome trace records for UI observability dashboards."""
        return [asdict(item) for item in self.intent_outcome_history[-limit:]]


tracer = SentinelTelemetryTracer()
pii_redactor = tracer.redactor
