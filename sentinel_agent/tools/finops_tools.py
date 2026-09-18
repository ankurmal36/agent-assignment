"""Cloud FinOps cost anomaly diagnostic tool with Pydantic schema validation and guided recovery."""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import ValidationError

from sentinel_agent.config import BASE_DIR
from sentinel_agent.telemetry.tracer import tracer
from sentinel_agent.tools.schemas import AnalyzeCostAnomalyInput, GuidedToolResponse


def _load_cost_catalog() -> dict[str, Any]:
    snapshot_file = BASE_DIR / "sample_data" / "telemetry_snapshots.json"
    if snapshot_file.exists():
        return dict(json.loads(snapshot_file.read_text(encoding="utf-8")).get("cost_reports", {}))
    return {}


def analyze_cloud_cost_anomaly_report(
    service_name: str,
    budget_variance_threshold_percent: float = 25.0,
) -> dict[str, Any]:
    """Analyze daily cloud spend variance and identify FinOps optimization recommendations for a workload.

    Purpose:
        Compares current daily cloud billing spend against baseline budgets for a target service or GKE/Vertex
        cluster, pinpointing runaway SKUs (e.g., idle A100 GPU node pools) and daily dollar savings.

    Args:
        service_name: Target workload or cluster identifier (e.g., 'ml-inference-cluster' or 'checkout-payment-service').
        budget_variance_threshold_percent: Percentage variance threshold (1.0 to 500.0, default 25.0)
            above which an anomaly alert is flagged.

    Returns:
        A dictionary matching the GuidedToolResponse JSON schema containing cost anomaly breakdowns or
        structured `recovery_guidance` if validation fails or the workload is unrecognized.
    """
    start_time = time.perf_counter()
    with tracer.start_span(
        "tool.analyze_cloud_cost_anomaly_report",
        attributes={
            "tool.service_name": service_name,
            "tool.threshold_pct": budget_variance_threshold_percent,
        },
    ) as (_, trace_id, span_id):
        intent_rec = tracer.log_intent_before_execution(
            trace_id=trace_id,
            span_id=span_id,
            agent_name="FinOpsAnomalyAgent",
            action_name="analyze_cloud_cost_anomaly_report",
            planned_arguments={
                "service_name": service_name,
                "budget_variance_threshold_percent": budget_variance_threshold_percent,
            },
            rationale="Evaluate cloud billing variance against FinOps threshold and identify savings.",
        )

        try:
            validated = AnalyzeCostAnomalyInput(
                service_name=service_name.strip(),
                budget_variance_threshold_percent=budget_variance_threshold_percent,
            )
        except ValidationError as exc:
            error_resp = GuidedToolResponse(
                status="error",
                tool_name="analyze_cloud_cost_anomaly_report",
                error_code="INVALID_COST_ANOMALY_PARAMETERS",
                recovery_guidance=(
                    f"Validation error: {exc.errors()[0]['msg']}. "
                    "Provide a valid 'service_name' and 'budget_variance_threshold_percent' between 1.0 and 500.0."
                ),
                suggested_next_action=(
                    "Retry analyze_cloud_cost_anomaly_report with service_name='ml-inference-cluster' "
                    "and budget_variance_threshold_percent=25.0."
                ),
            ).model_dump()
            tracer.log_outcome_after_execution(
                intent_rec, error_resp, "VALIDATION_ERROR", start_time
            )
            return error_resp

        catalog = _load_cost_catalog()
        normalized = validated.service_name.lower()
        matched_key = next(
            (k for k in catalog if k == normalized or normalized in k or k in normalized),
            None,
        )

        if not matched_key:
            available = ", ".join(sorted(catalog.keys()))
            not_found_resp = GuidedToolResponse(
                status="error",
                tool_name="analyze_cloud_cost_anomaly_report",
                error_code="COST_REPORT_NOT_FOUND",
                recovery_guidance=(
                    f"No FinOps billing report found for workload '{validated.service_name}'. "
                    f"Workloads with active billing telemetry: [{available}]."
                ),
                suggested_next_action=(
                    f"Re-invoke analyze_cloud_cost_anomaly_report with one of: {available}."
                ),
            ).model_dump()
            tracer.log_outcome_after_execution(intent_rec, not_found_resp, "NOT_FOUND", start_time)
            return not_found_resp

        report = dict(catalog[matched_key])
        report["service_name"] = matched_key
        report["threshold_exceeded"] = (
            float(report["variance_percent"]) >= validated.budget_variance_threshold_percent
        )

        success_resp = GuidedToolResponse(
            status="success",
            tool_name="analyze_cloud_cost_anomaly_report",
            data=report,
        ).model_dump()
        tracer.log_outcome_after_execution(intent_rec, success_resp, "SUCCESS", start_time)
        return success_resp
