"""SRE & FinOps Runbook RAG search tool with Pydantic validation and guided recovery."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from sentinel_agent.storage.vector_store import vector_store
from sentinel_agent.telemetry.tracer import tracer
from sentinel_agent.tools.schemas import GuidedToolResponse, SearchRunbookInput


def search_sre_runbook_knowledge_base(
    symptom_query: str,
    service_filter: str | None = None,
    top_k: int = 3,
) -> dict[str, Any]:
    """Perform semantic Vector RAG search over official SRE and FinOps runbooks with exact citation anchors.

    Purpose:
        Searches the indexed SRE runbook and postmortem vector database to retrieve grounded remediation steps,
        exact quotes, and deep-link section URLs matching an observed production symptom.

    Args:
        symptom_query: Natural-language description of the incident symptom or error pattern
            (e.g., 'HTTP 503 connection pool exhaustion on checkout-payment-service').
        service_filter: Optional microservice domain filter (e.g., 'checkout-payment-service').
        top_k: Number of top runbook matches to return between 1 and 10 (defaults to 3).

    Returns:
        A dictionary matching the GuidedToolResponse JSON schema containing matched runbook citations or
        structured `recovery_guidance` if validation fails or no matches are found.
    """
    start_time = time.perf_counter()
    with tracer.start_span(
        "tool.search_sre_runbook_knowledge_base",
        attributes={"tool.symptom_query": symptom_query, "tool.top_k": top_k},
    ) as (_, trace_id, span_id):
        intent_rec = tracer.log_intent_before_execution(
            trace_id=trace_id,
            span_id=span_id,
            agent_name="RunbookKnowledgeAgent",
            action_name="search_sre_runbook_knowledge_base",
            planned_arguments={
                "symptom_query": symptom_query,
                "service_filter": service_filter,
                "top_k": top_k,
            },
            rationale="Retrieve grounded SRE runbook citations and remediation steps from Vector RAG store.",
        )

        try:
            validated = SearchRunbookInput(
                symptom_query=symptom_query.strip(),
                service_filter=service_filter,
                top_k=top_k,
            )
        except ValidationError as exc:
            error_resp = GuidedToolResponse(
                status="error",
                tool_name="search_sre_runbook_knowledge_base",
                error_code="INVALID_RUNBOOK_SEARCH_QUERY",
                recovery_guidance=(
                    f"Runbook query validation failed: {exc.errors()[0]['msg']}. "
                    "Provide a non-empty 'symptom_query' (3-300 chars) and 'top_k' between 1 and 10."
                ),
                suggested_next_action=(
                    "Retry search_sre_runbook_knowledge_base with a descriptive symptom such as "
                    "'503 latency spike connection pool' and top_k=3."
                ),
            ).model_dump()
            tracer.log_outcome_after_execution(
                intent_rec, error_resp, "VALIDATION_ERROR", start_time
            )
            return error_resp

        matches = vector_store.search(
            query=validated.symptom_query,
            service_filter=validated.service_filter,
            top_k=validated.top_k,
        )
        if not matches:
            empty_resp = GuidedToolResponse(
                status="error",
                tool_name="search_sre_runbook_knowledge_base",
                error_code="NO_MATCHING_RUNBOOKS_FOUND",
                recovery_guidance=(
                    f"No runbooks matched query '{validated.symptom_query}'. "
                    "Try broadening keywords (e.g., '503 rollback', 'redis memory', or 'gpu cost spike') "
                    "and omitting 'service_filter'."
                ),
                suggested_next_action="Call search_sre_runbook_knowledge_base with service_filter=None.",
            ).model_dump()
            tracer.log_outcome_after_execution(intent_rec, empty_resp, "EMPTY_RESULTS", start_time)
            return empty_resp

        success_resp = GuidedToolResponse(
            status="success",
            tool_name="search_sre_runbook_knowledge_base",
            data={
                "query": validated.symptom_query,
                "match_count": len(matches),
                "citations": matches,
            },
        ).model_dump()
        tracer.log_outcome_after_execution(intent_rec, success_resp, "SUCCESS", start_time)
        return success_resp
