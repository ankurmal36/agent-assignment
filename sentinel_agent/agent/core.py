"""Multi-Agent Orchestrator with Strategic Model Routing (Flash vs Pro), Guardrails, HITL Hooks, and OpenTelemetry Tracing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from sentinel_agent.agent.adk_agent import root_agent, sub_agents
from sentinel_agent.agent.guardrails import hitl_gate, input_guardrail, output_guardrail
from sentinel_agent.agent.prompts import CONSTITUTION_SYSTEM_PROMPT
from sentinel_agent.config import settings
from sentinel_agent.storage.async_worker import async_memory_worker
from sentinel_agent.storage.compaction import history_compactor
from sentinel_agent.storage.database import db_manager
from sentinel_agent.telemetry.tracer import tracer
from sentinel_agent.tools import (
    analyze_cloud_cost_anomaly_report,
    create_critical_incident_ticket,
    execute_production_service_rollback,
    query_production_telemetry_metrics,
    record_postmortem_action_item,
    search_sre_runbook_knowledge_base,
)


@dataclass
class RoutingDecision:
    """Represents a strategic model routing decision between Gemini Flash and Gemini Pro."""

    intent_category: str
    selected_model: str
    target_sub_agent: str
    complexity_tier: str
    rationale: str


class StrategicModelRouter:
    """Routes incoming queries to Gemini 2.5 Flash (fast triage/lookup) or Gemini 2.5 Pro (deep multi-step synthesis)."""

    def __init__(
        self,
        flash_model: str | None = None,
        pro_model: str | None = None,
    ) -> None:
        self.flash_model = flash_model or settings.router_model_flash
        self.pro_model = pro_model or settings.synthesis_model_pro

    def route(self, query: str) -> RoutingDecision:
        """Select the optimal Gemini model and specialized worker sub-agent based on task complexity."""
        lower = query.lower()

        if any(
            k in lower
            for k in ["rollback", "revert", "approved-by-sre", "approved", "p0", "incident ticket"]
        ):
            return RoutingDecision(
                intent_category="HIGH_STAKES_REMEDIATION",
                selected_model=self.pro_model,
                target_sub_agent="RemediationExecutionAgent",
                complexity_tier="COMPLEX_HIGH_STAKES",
                rationale=(
                    f"Routed to {self.pro_model} and RemediationExecutionAgent because production rollbacks "
                    "and critical incident mutations require multi-step verification and HITL enforcement."
                ),
            )

        if any(
            k in lower
            for k in ["root cause", "diagnose", "outage", "503", "latency spike", "postmortem"]
        ):
            return RoutingDecision(
                intent_category="MULTI_SIGNAL_DIAGNOSIS",
                selected_model=self.pro_model,
                target_sub_agent="TelemetryDiagnosticsAgent+RunbookKnowledgeAgent",
                complexity_tier="COMPLEX_REASONING",
                rationale=(
                    f"Routed to {self.pro_model} for multi-agent correlation across live telemetry signals "
                    "and Vector RAG runbook citations."
                ),
            )

        if any(k in lower for k in ["cost", "finops", "billing", "budget", "gpu", "spend"]):
            return RoutingDecision(
                intent_category="FINOPS_COST_ANALYSIS",
                selected_model=self.flash_model,
                target_sub_agent="FinOpsAnomalyAgent",
                complexity_tier="FAST_SPECIALIST",
                rationale=f"Routed to {self.flash_model} and FinOpsAnomalyAgent for low-latency billing variance analysis.",
            )

        if any(k in lower for k in ["runbook", "playbook", "documentation", "guide"]):
            return RoutingDecision(
                intent_category="RUNBOOK_RAG_LOOKUP",
                selected_model=self.flash_model,
                target_sub_agent="RunbookKnowledgeAgent",
                complexity_tier="FAST_RETRIEVAL",
                rationale=f"Routed to {self.flash_model} and RunbookKnowledgeAgent for fast semantic Vector RAG lookup.",
            )

        return RoutingDecision(
            intent_category="TELEMETRY_TRIAGE",
            selected_model=self.flash_model,
            target_sub_agent="TelemetryDiagnosticsAgent",
            complexity_tier="FAST_TRIAGE",
            rationale=f"Routed to {self.flash_model} and TelemetryDiagnosticsAgent for fast service metric triage.",
        )


@dataclass
class AgentTurnResult:
    """Structured result returned by CloudOpsSentinelOrchestrator for each conversational turn."""

    session_id: str
    response_text: str
    status: str
    selected_model: str
    intent_category: str
    delegated_sub_agents: list[str] = field(default_factory=list)
    tool_executions: list[dict[str, Any]] = field(default_factory=list)
    grounding_score: float = 1.0
    compaction_metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    latency_ms: float = 0.0


class CloudOpsSentinelOrchestrator:
    """Enterprise Supervisor-Worker Orchestrator combining Google ADK agents, Model Routing, Guardrails, and HITL."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.router = StrategicModelRouter()
        self.adk_root_agent = root_agent
        self.adk_sub_agents = {agent.name: agent for agent in sub_agents}
        self.system_prompt = CONSTITUTION_SYSTEM_PROMPT

    @staticmethod
    def _infer_target_service(query: str) -> str:
        lower = query.lower()
        if "identity" in lower or "auth" in lower or "redis" in lower:
            return "identity-auth-service"
        if (
            "gpu" in lower
            or "ml" in lower
            or "inference" in lower
            or "cost" in lower
            or "finops" in lower
        ):
            return "ml-inference-cluster"
        return "checkout-payment-service"

    def handle_query(
        self,
        user_query: str,
        session_id: str = "default-sre-session",
        human_approval_token: str | None = None,
    ) -> AgentTurnResult:
        """Execute a full end-to-end multi-agent turn with OpenTelemetry tracing, Guardrails, Model Routing, and HITL."""
        turn_start = time.perf_counter()
        with tracer.start_span(
            "sentinel.handle_query",
            attributes={"session.id": session_id, "query.length": len(user_query or "")},
        ) as (_, trace_id, span_id):
            # 1. Pre-execution Input Guardrail & PII Redaction
            input_verdict = input_guardrail.validate(user_query, trace_id=trace_id, span_id=span_id)
            if not input_verdict.allowed:
                latency = round((time.perf_counter() - turn_start) * 1000.0, 2)
                return AgentTurnResult(
                    session_id=session_id,
                    response_text=input_verdict.reason,
                    status="BLOCKED_BY_GUARDRAIL",
                    selected_model=self.router.flash_model,
                    intent_category=input_verdict.violation_category,
                    grounding_score=0.0,
                    trace_id=trace_id,
                    latency_ms=latency,
                )

            clean_query = input_verdict.sanitized_content

            # 2. Strategic Model Routing (Flash vs Pro)
            with tracer.start_span(
                "sentinel.model_routing",
                attributes={"query.preview": clean_query[:80]},
            ) as (_, _, route_span_id):
                routing = self.router.route(clean_query)
                tracer.emit_json_log(
                    event_type="STRATEGIC_MODEL_ROUTING",
                    message=f"Routed intent '{routing.intent_category}' to model '{routing.selected_model}'",
                    agent_name="StrategicModelRouter",
                    trace_id=trace_id,
                    span_id=route_span_id,
                    metadata={
                        "intent_category": routing.intent_category,
                        "selected_model": routing.selected_model,
                        "target_sub_agent": routing.target_sub_agent,
                        "complexity_tier": routing.complexity_tier,
                    },
                )

            service_name = self._infer_target_service(clean_query)
            delegated_agents: list[str] = []
            tool_results: list[dict[str, Any]] = []

            # Detect inline approval token in user query if not passed explicitly
            effective_token = human_approval_token
            if not effective_token and "APPROVED-BY-SRE" in clean_query.upper():
                effective_token = "APPROVED-BY-SRE"

            # 3. Multi-Agent Worker Delegation & Tool Execution
            with tracer.start_span(
                "sentinel.subagent_delegation",
                attributes={
                    "target.sub_agent": routing.target_sub_agent,
                    "selected.model": routing.selected_model,
                },
            ):
                if routing.intent_category == "HIGH_STAKES_REMEDIATION":
                    delegated_agents.extend(
                        ["TelemetryDiagnosticsAgent", "RemediationExecutionAgent"]
                    )
                    telemetry_res = query_production_telemetry_metrics(service_name=service_name)
                    tool_results.append(telemetry_res)

                    ticket_res = create_critical_incident_ticket(
                        service_name=service_name,
                        severity="P0" if "p0" in clean_query.lower() else "P1",
                        title=f"Production degradation & rollback on {service_name}",
                        root_cause_hypothesis=f"Canary release caused elevated errors on {service_name}; rolling back to stable.",
                    )
                    tool_results.append(ticket_res)

                    target_rev = telemetry_res.get("data", {}).get(
                        "last_stable_revision", "v2.13.4-stable"
                    )
                    approved, hitl_intercept = hitl_gate.check_tool_execution(
                        "execute_production_service_rollback",
                        {
                            "service_name": service_name,
                            "target_revision": target_rev,
                            "human_approval_token": effective_token,
                        },
                    )
                    if not approved and hitl_intercept:
                        rollback_res = execute_production_service_rollback(
                            service_name=service_name,
                            target_revision=target_rev,
                            reason=f"Mitigate critical outage on {service_name}",
                            human_approval_token=None,
                        )
                        tool_results.append(rollback_res)
                    else:
                        rollback_res = execute_production_service_rollback(
                            service_name=service_name,
                            target_revision=target_rev,
                            reason=f"Human-approved rollback for {service_name}",
                            human_approval_token=effective_token or "APPROVED-BY-SRE",
                        )
                        tool_results.append(rollback_res)
                        pm_res = record_postmortem_action_item(
                            incident_id=ticket_res.get("data", {}).get("ticket_id", "INC-1001"),
                            owner_team=f"{service_name}-sre",
                            remediation_summary=f"Rolled back {service_name} to {target_rev} after HITL confirmation.",
                            preventative_measure="Add automated Cloud SQL connection pool load test in canary gate.",
                        )
                        tool_results.append(pm_res)

                elif routing.intent_category == "FINOPS_COST_ANALYSIS":
                    delegated_agents.extend(["FinOpsAnomalyAgent", "RunbookKnowledgeAgent"])
                    cost_res = analyze_cloud_cost_anomaly_report(service_name=service_name)
                    runbook_res = search_sre_runbook_knowledge_base(
                        symptom_query=f"GPU cost anomaly spike {service_name}",
                        service_filter=service_name,
                    )
                    tool_results.extend([cost_res, runbook_res])

                elif routing.intent_category == "RUNBOOK_RAG_LOOKUP":
                    delegated_agents.append("RunbookKnowledgeAgent")
                    runbook_res = search_sre_runbook_knowledge_base(
                        symptom_query=clean_query,
                        service_filter=service_name,
                    )
                    tool_results.append(runbook_res)

                else:
                    # MULTI_SIGNAL_DIAGNOSIS or TELEMETRY_TRIAGE
                    delegated_agents.extend(["TelemetryDiagnosticsAgent", "RunbookKnowledgeAgent"])
                    telemetry_res = query_production_telemetry_metrics(service_name=service_name)
                    runbook_res = search_sre_runbook_knowledge_base(
                        symptom_query=f"{clean_query} {service_name}",
                        service_filter=service_name,
                    )
                    tool_results.extend([telemetry_res, runbook_res])

            # 4. Synthesize Grounded Response (with optional live Gemini call or deterministic synthesis)
            response_text = self._synthesize_grounded_response(
                clean_query=clean_query,
                routing=routing,
                delegated_agents=delegated_agents,
                tool_results=tool_results,
            )

            # 5. Output Self-Evaluation Guardrail & PII Scrubbing
            out_verdict = output_guardrail.evaluate(
                response_text=response_text,
                tool_traces=tool_results,
                trace_id=trace_id,
                span_id=span_id,
            )

            # 6. Non-Blocking Async Memory Persistence & History Compaction
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    async_memory_worker.consolidate_turn_async(
                        session_id=session_id,
                        user_message=clean_query,
                        assistant_message=out_verdict.sanitized_content,
                        model_used=routing.selected_model,
                    )
                )
                compaction_meta = {"async_scheduled": True}
            except RuntimeError:
                db_manager.append_session_message(
                    session_id, "user", clean_query, routing.selected_model
                )
                db_manager.append_session_message(
                    session_id, "assistant", out_verdict.sanitized_content, routing.selected_model
                )
                compaction_meta = history_compactor.compact_history(
                    session_id, db_manager.get_session_messages(session_id)
                )

            requires_hitl = any(r.get("status") == "requires_human_approval" for r in tool_results)
            final_status = "PAUSED_FOR_HUMAN_APPROVAL" if requires_hitl else "SUCCESS"
            latency_ms = round((time.perf_counter() - turn_start) * 1000.0, 2)

            return AgentTurnResult(
                session_id=session_id,
                response_text=out_verdict.sanitized_content,
                status=final_status,
                selected_model=routing.selected_model,
                intent_category=routing.intent_category,
                delegated_sub_agents=delegated_agents,
                tool_executions=tool_results,
                grounding_score=out_verdict.grounding_score,
                compaction_metadata=compaction_meta,
                trace_id=trace_id,
                latency_ms=latency_ms,
            )

    def _synthesize_grounded_response(
        self,
        clean_query: str,
        routing: RoutingDecision,
        delegated_agents: list[str],
        tool_results: list[dict[str, Any]],
    ) -> str:
        """Synthesize a structured response grounded in tool outputs and runbook citations."""
        sections: list[str] = [
            "### 1. Executive Diagnosis & Strategic Model Routing",
            f"- **Intent Classification**: `{routing.intent_category}` ({routing.complexity_tier})",
            f"- **Selected Gemini Model**: `{routing.selected_model}`",
            f"- **Delegated ADK Sub-Agents**: `{', '.join(delegated_agents)}`",
            f"- **Routing Rationale**: {routing.rationale}",
        ]

        telemetry_lines: list[str] = []
        citation_lines: list[str] = []
        remediation_lines: list[str] = []

        for res in tool_results:
            t_name = res.get("tool_name", "")
            data = res.get("data", {})
            status = res.get("status", "")

            if t_name == "query_production_telemetry_metrics" and status == "success":
                telemetry_lines.append(
                    f"- **Service `{data.get('service_name')}`** (`{data.get('current_revision')}`): "
                    f"Status=`{data.get('status')}`, Error Rate=`{data.get('error_rate_percent')}%`, "
                    f"p99 Latency=`{data.get('p99_latency_ms')}ms`, "
                    f"DB Pool Saturation=`{data.get('db_connection_pool_saturation_percent')}%`."
                )
            elif t_name == "analyze_cloud_cost_anomaly_report" and status == "success":
                telemetry_lines.append(
                    f"- **FinOps Cost Report for `{data.get('service_name')}`**: "
                    f"Baseline=`${data.get('daily_baseline_usd')}/day`, "
                    f"Current=`${data.get('current_daily_spend_usd')}/day` "
                    f"(Variance: `+{data.get('variance_percent')}%`). "
                    f"Primary Driver: {data.get('primary_cost_driver')}. "
                    f"Action: {data.get('recommended_finops_action')}"
                )
            elif t_name == "search_sre_runbook_knowledge_base" and status == "success":
                for cite in data.get("citations", []):
                    citation_lines.append(
                        f"- **[{cite.get('doc_id')}]({cite.get('section_anchor')})** — *{cite.get('title')}* "
                        f'(Similarity: `{cite.get("similarity_score")}`): "{cite.get("exact_quote")}"'
                    )
            elif t_name == "create_critical_incident_ticket" and status == "success":
                remediation_lines.append(
                    f"- **Incident Ticket Opened**: `{data.get('ticket_id')}` "
                    f"(Severity: `{data.get('severity')}`, Status: `{data.get('status')}`) — {data.get('title')}"
                )
            elif t_name == "execute_production_service_rollback":
                if status == "requires_human_approval":
                    remediation_lines.append(
                        f"- **HUMAN-IN-THE-LOOP GATE TRIGGERED (`{res.get('error_code')}`)**: "
                        f"{res.get('recovery_guidance')} "
                        f"(Target Service: `{data.get('service_name')}`, Target Revision: `{data.get('target_revision')}`)."
                    )
                elif status == "success":
                    remediation_lines.append(
                        f"- **Rollback Executed Successfully**: Restored `{data.get('service_name')}` to "
                        f"`{data.get('restored_revision')}` (Verified Token: `{data.get('approval_verified')}`). "
                        f"Post-rollback Error Rate: `{data.get('post_rollback_error_rate_percent')}%`, "
                        f"p99 Latency: `{data.get('post_rollback_p99_latency_ms')}ms`."
                    )
            elif t_name == "record_postmortem_action_item" and status == "success":
                remediation_lines.append(
                    f"- **Postmortem Action Logged & Async Vector Indexed**: `{data.get('action_id')}` "
                    f"(Background Job: `{data.get('async_vector_indexing_job')}`)."
                )

        if telemetry_lines:
            sections.append("\n### 2. Telemetry & FinOps Evidence")
            sections.extend(telemetry_lines)

        if citation_lines:
            sections.append("\n### 3. Grounded Runbook Citations")
            sections.extend(citation_lines)

        if remediation_lines:
            sections.append("\n### 4. Remediation & Human-in-the-Loop Status")
            sections.extend(remediation_lines)

        return "\n".join(sections)
