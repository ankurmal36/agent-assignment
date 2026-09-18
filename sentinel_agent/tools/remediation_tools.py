"""High-stakes SRE remediation tools with Human-in-the-Loop (HITL) approval hooks, SQLite persistence, and async memory indexing."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from sentinel_agent.storage.async_worker import async_memory_worker
from sentinel_agent.storage.database import db_manager
from sentinel_agent.telemetry.tracer import tracer
from sentinel_agent.tools.schemas import (
    CreateCriticalIncidentInput,
    ExecuteServiceRollbackInput,
    GuidedToolResponse,
    RecordPostmortemActionInput,
)

VALID_APPROVAL_TOKENS = {"APPROVED", "APPROVED-BY-SRE", "CONFIRM-ROLLBACK", "HUMAN-CONFIRMED"}


def create_critical_incident_ticket(
    service_name: str,
    severity: str,
    title: str,
    root_cause_hypothesis: str,
) -> dict[str, Any]:
    """Create and persist a critical SRE incident ticket in the SQLite incident database.

    Purpose:
        Opens a formal incident record (`INC-XXXXXXXX`) with severity classification (`P0`-`P3`) and
        grounded root-cause hypothesis so responders can track remediation and postmortem actions.

    Args:
        service_name: Name of the impacted production service (e.g., 'checkout-payment-service').
        severity: Incident severity level; must be one of 'P0', 'P1', 'P2', or 'P3'.
        title: Concise summary of the production incident (5 to 160 characters).
        root_cause_hypothesis: Grounded diagnostic hypothesis explaining why the outage occurred.

    Returns:
        A dictionary matching the GuidedToolResponse JSON schema containing the created `ticket_id` and record,
        or structured `recovery_guidance` if validation fails.
    """
    start_time = time.perf_counter()
    with tracer.start_span(
        "tool.create_critical_incident_ticket",
        attributes={"tool.service_name": service_name, "tool.severity": severity},
    ) as (_, trace_id, span_id):
        intent_rec = tracer.log_intent_before_execution(
            trace_id=trace_id,
            span_id=span_id,
            agent_name="RemediationExecutionAgent",
            action_name="create_critical_incident_ticket",
            planned_arguments={
                "service_name": service_name,
                "severity": severity,
                "title": title,
                "root_cause_hypothesis": root_cause_hypothesis,
            },
            rationale="Persist formal incident record in SQLite before executing production remediation.",
        )

        try:
            validated = CreateCriticalIncidentInput(
                service_name=service_name.strip(),
                severity=severity.strip().upper(),  # type: ignore[arg-type]
                title=title.strip(),
                root_cause_hypothesis=root_cause_hypothesis.strip(),
            )
        except ValidationError as exc:
            error_resp = GuidedToolResponse(
                status="error",
                tool_name="create_critical_incident_ticket",
                error_code="INVALID_INCIDENT_TICKET_SCHEMA",
                recovery_guidance=(
                    f"Incident ticket validation failed: {exc.errors()[0]['msg']}. "
                    "Ensure 'severity' is strictly one of ['P0', 'P1', 'P2', 'P3'], 'title' >= 5 chars, "
                    "and 'root_cause_hypothesis' >= 10 chars."
                ),
                suggested_next_action=(
                    "Retry create_critical_incident_ticket with severity='P1' and a complete hypothesis."
                ),
            ).model_dump()
            tracer.log_outcome_after_execution(
                intent_rec, error_resp, "VALIDATION_ERROR", start_time
            )
            return error_resp

        record = db_manager.create_incident(
            service_name=validated.service_name,
            severity=validated.severity,
            title=validated.title,
            root_cause_hypothesis=validated.root_cause_hypothesis,
        )
        success_resp = GuidedToolResponse(
            status="success",
            tool_name="create_critical_incident_ticket",
            data=record,
        ).model_dump()
        tracer.log_outcome_after_execution(intent_rec, success_resp, "SUCCESS", start_time)
        return success_resp


def execute_production_service_rollback(
    service_name: str,
    target_revision: str,
    reason: str,
    human_approval_token: str | None = None,
) -> dict[str, Any]:
    """Execute a high-stakes production revision rollback gated by a strict Human-in-the-Loop (HITL) check.

    Purpose:
        Reverts a degraded production microservice (e.g., 'checkout-payment-service') to a known-good
        revision (e.g., 'v2.13.4-stable'). Because production rollbacks mutate live traffic, this tool
        enforces a mandatory Human-in-the-Loop confirmation stop unless a valid `human_approval_token`
        is supplied.

    Args:
        service_name: Name of the production service to roll back.
        target_revision: Known-good revision identifier to restore (e.g., 'v2.13.4-stable').
        reason: Engineering justification for performing the rollback.
        human_approval_token: Explicit human confirmation token ('APPROVED-BY-SRE' or 'APPROVED'). If omitted,
            execution halts safely and returns `status='requires_human_approval'`.

    Returns:
        A dictionary matching the GuidedToolResponse JSON schema indicating either `requires_human_approval`
        (when awaiting human confirmation) or `success` (once approved).
    """
    start_time = time.perf_counter()
    with tracer.start_span(
        "tool.execute_production_service_rollback",
        attributes={
            "tool.service_name": service_name,
            "tool.target_revision": target_revision,
            "hitl.token_present": bool(human_approval_token),
        },
    ) as (_, trace_id, span_id):
        intent_rec = tracer.log_intent_before_execution(
            trace_id=trace_id,
            span_id=span_id,
            agent_name="RemediationExecutionAgent",
            action_name="execute_production_service_rollback",
            planned_arguments={
                "service_name": service_name,
                "target_revision": target_revision,
                "reason": reason,
                "human_approval_token": human_approval_token,
            },
            rationale="Roll back degraded production revision to restore service SLOs.",
        )

        try:
            validated = ExecuteServiceRollbackInput(
                service_name=service_name.strip(),
                target_revision=target_revision.strip(),
                reason=reason.strip(),
                human_approval_token=human_approval_token.strip() if human_approval_token else None,
            )
        except ValidationError as exc:
            error_resp = GuidedToolResponse(
                status="error",
                tool_name="execute_production_service_rollback",
                error_code="INVALID_ROLLBACK_ARGUMENTS",
                recovery_guidance=(
                    f"Rollback parameter validation failed: {exc.errors()[0]['msg']}. "
                    "Provide non-empty 'service_name', 'target_revision', and 'reason' (>=5 chars)."
                ),
                suggested_next_action=(
                    "Retry execute_production_service_rollback with target_revision='v2.13.4-stable'."
                ),
            ).model_dump()
            tracer.log_outcome_after_execution(
                intent_rec, error_resp, "VALIDATION_ERROR", start_time
            )
            return error_resp

        # Mandatory Human-in-the-Loop (HITL) Code Stop
        normalized_token = (validated.human_approval_token or "").upper()
        if normalized_token not in VALID_APPROVAL_TOKENS:
            hitl_resp = GuidedToolResponse(
                status="requires_human_approval",
                tool_name="execute_production_service_rollback",
                error_code="HITL_CONFIRMATION_REQUIRED",
                data={
                    "pending_action": "execute_production_service_rollback",
                    "service_name": validated.service_name,
                    "target_revision": validated.target_revision,
                    "reason": validated.reason,
                    "required_token": "APPROVED-BY-SRE",
                },
                recovery_guidance=(
                    "HIGH-STAKES ACTION PAUSED BY HUMAN-IN-THE-LOOP GATE: Rolling back production service "
                    f"'{validated.service_name}' to '{validated.target_revision}' requires explicit human approval. "
                    "Present the rollback plan to the human operator and ask them to confirm with token 'APPROVED-BY-SRE'."
                ),
                suggested_next_action=(
                    "Ask the user for approval, then call execute_production_service_rollback with "
                    "human_approval_token='APPROVED-BY-SRE'."
                ),
            ).model_dump()
            tracer.log_outcome_after_execution(intent_rec, hitl_resp, "PAUSED_FOR_HITL", start_time)
            return hitl_resp

        rollback_result = {
            "service_name": validated.service_name,
            "previous_revision": "v2.14.0-canary",
            "restored_revision": validated.target_revision,
            "approval_verified": normalized_token,
            "post_rollback_error_rate_percent": 0.15,
            "post_rollback_p99_latency_ms": 210.0,
            "rollback_status": "COMPLETED_HEALTHY",
        }
        success_resp = GuidedToolResponse(
            status="success",
            tool_name="execute_production_service_rollback",
            data=rollback_result,
        ).model_dump()
        tracer.log_outcome_after_execution(intent_rec, success_resp, "SUCCESS", start_time)
        return success_resp


def record_postmortem_action_item(
    incident_id: str,
    owner_team: str,
    remediation_summary: str,
    preventative_measure: str,
) -> dict[str, Any]:
    """Persist a postmortem action item in SQLite and asynchronously index it into the Vector RAG store.

    Purpose:
        Records long-term engineering follow-ups for an incident in SQLite and dispatches a non-blocking
        background job to `AsyncMemoryWorker` so future agent turns can retrieve this learning via RAG.

    Args:
        incident_id: Incident ticket ID (e.g., 'INC-1024').
        owner_team: Engineering team owning the follow-up item (e.g., 'Checkout-SRE').
        remediation_summary: Description of how the incident was mitigated (10 to 500 chars).
        preventative_measure: Architectural fix or policy test preventing recurrence (10 to 500 chars).

    Returns:
        A dictionary matching the GuidedToolResponse JSON schema containing the stored action item and
        background indexing job ID.
    """
    start_time = time.perf_counter()
    with tracer.start_span(
        "tool.record_postmortem_action_item",
        attributes={"tool.incident_id": incident_id, "tool.owner_team": owner_team},
    ) as (_, trace_id, span_id):
        intent_rec = tracer.log_intent_before_execution(
            trace_id=trace_id,
            span_id=span_id,
            agent_name="RemediationExecutionAgent",
            action_name="record_postmortem_action_item",
            planned_arguments={
                "incident_id": incident_id,
                "owner_team": owner_team,
                "remediation_summary": remediation_summary,
                "preventative_measure": preventative_measure,
            },
            rationale="Persist postmortem action item and trigger async vector indexing.",
        )

        try:
            validated = RecordPostmortemActionInput(
                incident_id=incident_id.strip(),
                owner_team=owner_team.strip(),
                remediation_summary=remediation_summary.strip(),
                preventative_measure=preventative_measure.strip(),
            )
        except ValidationError as exc:
            error_resp = GuidedToolResponse(
                status="error",
                tool_name="record_postmortem_action_item",
                error_code="INVALID_POSTMORTEM_SCHEMA",
                recovery_guidance=(
                    f"Postmortem validation failed: {exc.errors()[0]['msg']}. "
                    "Ensure 'incident_id' >= 4 chars and both 'remediation_summary' and "
                    "'preventative_measure' are at least 10 characters long."
                ),
                suggested_next_action="Retry record_postmortem_action_item with detailed summary strings.",
            ).model_dump()
            tracer.log_outcome_after_execution(
                intent_rec, error_resp, "VALIDATION_ERROR", start_time
            )
            return error_resp

        record = db_manager.record_postmortem_action(
            incident_id=validated.incident_id,
            owner_team=validated.owner_team,
            remediation_summary=validated.remediation_summary,
            preventative_measure=validated.preventative_measure,
        )
        bg_job_id = async_memory_worker.enqueue_postmortem_indexing(
            action_id=record["action_id"],
            incident_id=validated.incident_id,
            service_domain=validated.owner_team,
            remediation_summary=validated.remediation_summary,
            preventative_measure=validated.preventative_measure,
        )
        record["async_vector_indexing_job"] = bg_job_id

        success_resp = GuidedToolResponse(
            status="success",
            tool_name="record_postmortem_action_item",
            data=record,
        ).model_dump()
        tracer.log_outcome_after_execution(intent_rec, success_resp, "SUCCESS", start_time)
        return success_resp
