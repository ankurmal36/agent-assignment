"""Production telemetry inspection tool with Pydantic schema validation and guided error recovery."""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import ValidationError

from sentinel_agent.config import BASE_DIR
from sentinel_agent.telemetry.tracer import tracer
from sentinel_agent.tools.schemas import GuidedToolResponse, QueryTelemetryInput


def _load_telemetry_catalog() -> dict[str, Any]:
    snapshot_file = BASE_DIR / "sample_data" / "telemetry_snapshots.json"
    if snapshot_file.exists():
        return dict(json.loads(snapshot_file.read_text(encoding="utf-8")).get("services", {}))
    return {}


def query_production_telemetry_metrics(
    service_name: str, lookback_minutes: int = 30
) -> dict[str, Any]:
    """Query real-time golden signals (error rate, p99 latency, CPU, DB pool saturation) for a production service.

    Purpose:
        Retrieves golden observability metrics and anomaly signals for a target microservice over a specified
        lookback window so the agent can diagnose root causes before proposing remediation.

    Args:
        service_name: Exact identifier of the production microservice (e.g., 'checkout-payment-service',
            'identity-auth-service', or 'ml-inference-cluster').
        lookback_minutes: Aggregation window in minutes between 5 and 1440 (defaults to 30).

    Returns:
        A dictionary matching the GuidedToolResponse JSON schema containing either golden metrics (`status='success'`)
        or structured `recovery_guidance` and `suggested_next_action` (`status='error'`).
    """
    start_time = time.perf_counter()
    with tracer.start_span(
        "tool.query_production_telemetry_metrics",
        attributes={"tool.service_name": service_name, "tool.lookback_minutes": lookback_minutes},
    ) as (_, trace_id, span_id):
        intent_rec = tracer.log_intent_before_execution(
            trace_id=trace_id,
            span_id=span_id,
            agent_name="TelemetryDiagnosticsAgent",
            action_name="query_production_telemetry_metrics",
            planned_arguments={"service_name": service_name, "lookback_minutes": lookback_minutes},
            rationale="Inspect golden telemetry signals to verify service health and identify root cause.",
        )

        try:
            validated = QueryTelemetryInput(
                service_name=service_name.strip(),
                lookback_minutes=lookback_minutes,
            )
        except ValidationError as exc:
            error_resp = GuidedToolResponse(
                status="error",
                tool_name="query_production_telemetry_metrics",
                error_code="INVALID_TELEMETRY_PARAMETERS",
                recovery_guidance=(
                    f"Input validation failed: {exc.errors()[0]['msg']}. "
                    "Ensure 'service_name' is at least 3 characters and 'lookback_minutes' is between 5 and 1440."
                ),
                suggested_next_action=(
                    "Retry query_production_telemetry_metrics with service_name='checkout-payment-service' "
                    "and lookback_minutes=30."
                ),
            ).model_dump()
            tracer.log_outcome_after_execution(
                intent_rec, error_resp, "VALIDATION_ERROR", start_time
            )
            return error_resp

        catalog = _load_telemetry_catalog()
        normalized = validated.service_name.lower()
        matched_key = next(
            (k for k in catalog if k == normalized or normalized in k or k in normalized),
            None,
        )

        if not matched_key:
            available = ", ".join(sorted(catalog.keys()))
            not_found_resp = GuidedToolResponse(
                status="error",
                tool_name="query_production_telemetry_metrics",
                error_code="SERVICE_NOT_FOUND_IN_TELEMETRY",
                recovery_guidance=(
                    f"No telemetry stream found for service '{validated.service_name}'. "
                    f"Available monitored services are: [{available}]."
                ),
                suggested_next_action=(
                    f"Re-invoke query_production_telemetry_metrics using one of: {available}."
                ),
            ).model_dump()
            tracer.log_outcome_after_execution(intent_rec, not_found_resp, "NOT_FOUND", start_time)
            return not_found_resp

        metrics = dict(catalog[matched_key])
        metrics["service_name"] = matched_key
        metrics["lookback_minutes"] = validated.lookback_minutes

        success_resp = GuidedToolResponse(
            status="success",
            tool_name="query_production_telemetry_metrics",
            data=metrics,
        ).model_dump()
        tracer.log_outcome_after_execution(intent_rec, success_resp, "SUCCESS", start_time)
        return success_resp
