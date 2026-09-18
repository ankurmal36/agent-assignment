"""Export all custom Pydantic-validated tools and JSON schemas for CloudOps Sentinel."""

from sentinel_agent.tools.finops_tools import analyze_cloud_cost_anomaly_report
from sentinel_agent.tools.remediation_tools import (
    create_critical_incident_ticket,
    execute_production_service_rollback,
    record_postmortem_action_item,
)
from sentinel_agent.tools.runbook_tools import search_sre_runbook_knowledge_base
from sentinel_agent.tools.schemas import (
    TOOL_JSON_SCHEMAS,
    AnalyzeCostAnomalyInput,
    CreateCriticalIncidentInput,
    ExecuteServiceRollbackInput,
    GuidedToolResponse,
    QueryTelemetryInput,
    RecordPostmortemActionInput,
    SearchRunbookInput,
)
from sentinel_agent.tools.telemetry_tools import query_production_telemetry_metrics

ALL_SENTINEL_TOOLS = [
    query_production_telemetry_metrics,
    search_sre_runbook_knowledge_base,
    analyze_cloud_cost_anomaly_report,
    create_critical_incident_ticket,
    execute_production_service_rollback,
    record_postmortem_action_item,
]

__all__ = [
    "ALL_SENTINEL_TOOLS",
    "TOOL_JSON_SCHEMAS",
    "AnalyzeCostAnomalyInput",
    "CreateCriticalIncidentInput",
    "ExecuteServiceRollbackInput",
    "GuidedToolResponse",
    "QueryTelemetryInput",
    "RecordPostmortemActionInput",
    "SearchRunbookInput",
    "analyze_cloud_cost_anomaly_report",
    "create_critical_incident_ticket",
    "execute_production_service_rollback",
    "query_production_telemetry_metrics",
    "record_postmortem_action_item",
    "search_sre_runbook_knowledge_base",
]
