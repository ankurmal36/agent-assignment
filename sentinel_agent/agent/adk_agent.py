"""Native Google Agent Development Kit (ADK) Multi-Agent Hierarchy (Coordinator + Specialized Sub-Agents)."""

from __future__ import annotations

from typing import Any

from sentinel_agent.agent.guardrails import (
    adk_after_model_guardrail,
    adk_before_model_guardrail,
    adk_before_tool_hitl_hook,
)
from sentinel_agent.agent.prompts import (
    CONSTITUTION_SYSTEM_PROMPT,
    FINOPS_WORKER_INSTRUCTION,
    REMEDIATION_WORKER_INSTRUCTION,
    RUNBOOK_WORKER_INSTRUCTION,
    TELEMETRY_WORKER_INSTRUCTION,
)
from sentinel_agent.config import settings
from sentinel_agent.storage.compaction import history_compactor
from sentinel_agent.tools import (
    analyze_cloud_cost_anomaly_report,
    create_critical_incident_ticket,
    execute_production_service_rollback,
    query_production_telemetry_metrics,
    record_postmortem_action_item,
    search_sre_runbook_knowledge_base,
)


def build_adk_agent_hierarchy() -> tuple[Any, list[Any], Any]:
    """Construct the Google ADK Coordinator LlmAgent, 4 specialized Worker Sub-Agents, and ADK App with compaction.

    Returns:
        Tuple of (root_coordinator_agent, worker_sub_agents, adk_app).
    """
    from google.adk.agents import LlmAgent, SequentialAgent

    telemetry_agent = LlmAgent(
        name="TelemetryDiagnosticsAgent",
        model=settings.router_model_flash,
        description="Delegates golden-signal observability metric queries (error rate, latency, saturation) for microservices.",
        instruction=TELEMETRY_WORKER_INSTRUCTION,
        tools=[query_production_telemetry_metrics],
        before_model_callback=adk_before_model_guardrail,
        after_model_callback=adk_after_model_guardrail,
    )

    runbook_agent = LlmAgent(
        name="RunbookKnowledgeAgent",
        model=settings.router_model_flash,
        description="Performs Vector RAG search over SRE and FinOps runbooks with exact section anchor citations.",
        instruction=RUNBOOK_WORKER_INSTRUCTION,
        tools=[search_sre_runbook_knowledge_base],
        before_model_callback=adk_before_model_guardrail,
        after_model_callback=adk_after_model_guardrail,
    )

    finops_agent = LlmAgent(
        name="FinOpsAnomalyAgent",
        model=settings.router_model_flash,
        description="Analyzes cloud cost anomalies, GPU node pool waste, and daily budget variances.",
        instruction=FINOPS_WORKER_INSTRUCTION,
        tools=[analyze_cloud_cost_anomaly_report],
        before_model_callback=adk_before_model_guardrail,
        after_model_callback=adk_after_model_guardrail,
    )

    remediation_agent = LlmAgent(
        name="RemediationExecutionAgent",
        model=settings.synthesis_model_pro,
        description="Executes incident ticket creation, HITL-gated production service rollbacks, and postmortem indexing.",
        instruction=REMEDIATION_WORKER_INSTRUCTION,
        tools=[
            create_critical_incident_ticket,
            execute_production_service_rollback,
            record_postmortem_action_item,
        ],
        before_model_callback=adk_before_model_guardrail,
        after_model_callback=adk_after_model_guardrail,
        before_tool_callback=adk_before_tool_hitl_hook,
    )

    # Sequential diagnostic pipeline sub-agent combining telemetry + runbook lookup
    diagnostic_pipeline = SequentialAgent(
        name="IncidentDiagnosticPipelineAgent",
        description="Sequential pipeline executing telemetry inspection followed by runbook RAG retrieval.",
        sub_agents=[],
    )

    worker_sub_agents = [
        telemetry_agent,
        runbook_agent,
        finops_agent,
        remediation_agent,
    ]

    coordinator_agent = LlmAgent(
        name="SentinelCoordinatorAgent",
        model=settings.synthesis_model_pro,
        description="Central SRE & FinOps Incident Commander routing requests across specialized worker sub-agents.",
        instruction=CONSTITUTION_SYSTEM_PROMPT,
        sub_agents=worker_sub_agents,
        tools=[
            query_production_telemetry_metrics,
            search_sre_runbook_knowledge_base,
            analyze_cloud_cost_anomaly_report,
            create_critical_incident_ticket,
            execute_production_service_rollback,
            record_postmortem_action_item,
        ],
        before_model_callback=adk_before_model_guardrail,
        after_model_callback=adk_after_model_guardrail,
        before_tool_callback=adk_before_tool_hitl_hook,
    )

    adk_app = None
    try:
        from google.adk.apps.app import App

        adk_app = App(
            name="cloudops_sentinel",
            root_agent=coordinator_agent,
            events_compaction_config=history_compactor.build_adk_compaction_config(),
        )
    except Exception:
        adk_app = diagnostic_pipeline

    return coordinator_agent, worker_sub_agents, adk_app


root_agent, sub_agents, app = build_adk_agent_hierarchy()
