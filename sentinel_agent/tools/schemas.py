"""Strict Pydantic Input and Output JSON Schemas constraining all agent tool interfaces."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GuidedToolResponse(BaseModel):
    """Standardized output schema for all tools, including structured error recovery guidance."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error", "requires_human_approval"] = Field(
        description="Execution status of the tool call."
    )
    tool_name: str = Field(description="Exact name of the executed tool.")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured output payload when status is 'success' or 'requires_human_approval'.",
    )
    error_code: str | None = Field(
        default=None,
        description="Machine-readable error code when status is 'error' or 'requires_human_approval'.",
    )
    recovery_guidance: str | None = Field(
        default=None,
        description="Actionable instructions guiding the LLM on how to recover from the error without crashing.",
    )
    suggested_next_action: str | None = Field(
        default=None,
        description="Recommended follow-up tool or parameter adjustment for the LLM.",
    )


class QueryTelemetryInput(BaseModel):
    """Strict input schema for querying production service telemetry metrics."""

    model_config = ConfigDict(extra="forbid")

    service_name: str = Field(
        min_length=3,
        max_length=80,
        description="Target microservice identifier (e.g., 'checkout-payment-service', 'identity-auth-service', 'ml-inference-cluster').",
    )
    lookback_minutes: int = Field(
        default=30,
        ge=5,
        le=1440,
        description="Time window in minutes for aggregating error rates, latency, and saturation metrics (5 to 1440).",
    )


class SearchRunbookInput(BaseModel):
    """Strict input schema for semantic RAG retrieval across SRE and FinOps runbooks."""

    model_config = ConfigDict(extra="forbid")

    symptom_query: str = Field(
        min_length=3,
        max_length=300,
        description="Natural-language symptom or error query (e.g., 'HTTP 503 connection pool exhaustion on checkout').",
    )
    service_filter: str | None = Field(
        default=None,
        description="Optional service domain filter to boost relevant runbooks.",
    )
    top_k: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of grounded runbook citations to return.",
    )


class AnalyzeCostAnomalyInput(BaseModel):
    """Strict input schema for analyzing cloud billing spikes and FinOps anomalies."""

    model_config = ConfigDict(extra="forbid")

    service_name: str = Field(
        min_length=3,
        max_length=80,
        description="Cloud workload or cluster name to inspect for billing anomalies (e.g., 'ml-inference-cluster').",
    )
    budget_variance_threshold_percent: float = Field(
        default=25.0,
        ge=1.0,
        le=500.0,
        description="Percentage variance over daily baseline that triggers an anomaly alert.",
    )


class CreateCriticalIncidentInput(BaseModel):
    """Strict input schema for opening a critical SRE incident ticket."""

    model_config = ConfigDict(extra="forbid")

    service_name: str = Field(
        min_length=3,
        max_length=80,
        description="Impacted production service name.",
    )
    severity: Literal["P0", "P1", "P2", "P3"] = Field(
        description="Incident severity level ('P0', 'P1', 'P2', or 'P3')."
    )
    title: str = Field(
        min_length=5,
        max_length=160,
        description="Concise incident headline summarizing user impact.",
    )
    root_cause_hypothesis: str = Field(
        min_length=10,
        max_length=600,
        description="Initial diagnostic hypothesis grounded in telemetry and runbook evidence.",
    )


class ExecuteServiceRollbackInput(BaseModel):
    """Strict input schema for high-stakes production service rollback (requires HITL confirmation)."""

    model_config = ConfigDict(extra="forbid")

    service_name: str = Field(
        min_length=3,
        max_length=80,
        description="Target production service to roll back.",
    )
    target_revision: str = Field(
        min_length=2,
        max_length=60,
        description="Known-good stable revision tag to restore (e.g., 'v2.13.4-stable').",
    )
    reason: str = Field(
        min_length=5,
        max_length=400,
        description="Auditable engineering justification for executing the rollback.",
    )
    human_approval_token: str | None = Field(
        default=None,
        description="Explicit Human-in-the-Loop approval token (e.g., 'APPROVED-BY-SRE') required before execution.",
    )


class RecordPostmortemActionInput(BaseModel):
    """Strict input schema for recording postmortem action items and async vector memory indexing."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(
        min_length=4,
        max_length=40,
        description="Associated incident ticket ID (e.g., 'INC-1024').",
    )
    owner_team: str = Field(
        min_length=2,
        max_length=80,
        description="Engineering team responsible for the preventative action.",
    )
    remediation_summary: str = Field(
        min_length=10,
        max_length=500,
        description="Summary of how the incident was mitigated.",
    )
    preventative_measure: str = Field(
        min_length=10,
        max_length=500,
        description="Long-term architectural or guardrail fix to prevent recurrence.",
    )


TOOL_JSON_SCHEMAS: dict[str, dict[str, Any]] = {
    "query_production_telemetry_metrics": {
        "input_schema": QueryTelemetryInput.model_json_schema(),
        "output_schema": GuidedToolResponse.model_json_schema(),
    },
    "search_sre_runbook_knowledge_base": {
        "input_schema": SearchRunbookInput.model_json_schema(),
        "output_schema": GuidedToolResponse.model_json_schema(),
    },
    "analyze_cloud_cost_anomaly_report": {
        "input_schema": AnalyzeCostAnomalyInput.model_json_schema(),
        "output_schema": GuidedToolResponse.model_json_schema(),
    },
    "create_critical_incident_ticket": {
        "input_schema": CreateCriticalIncidentInput.model_json_schema(),
        "output_schema": GuidedToolResponse.model_json_schema(),
    },
    "execute_production_service_rollback": {
        "input_schema": ExecuteServiceRollbackInput.model_json_schema(),
        "output_schema": GuidedToolResponse.model_json_schema(),
    },
    "record_postmortem_action_item": {
        "input_schema": RecordPostmortemActionInput.model_json_schema(),
        "output_schema": GuidedToolResponse.model_json_schema(),
    },
}
