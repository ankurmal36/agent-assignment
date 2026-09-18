"""Telemetry package exposing OpenTelemetry tracer, structured JSON logging, and PII redactor."""

from sentinel_agent.telemetry.tracer import (
    IntentOutcomeRecord,
    PIIRedactor,
    SentinelTelemetryTracer,
    pii_redactor,
    tracer,
)

__all__ = [
    "IntentOutcomeRecord",
    "PIIRedactor",
    "SentinelTelemetryTracer",
    "pii_redactor",
    "tracer",
]
