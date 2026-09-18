"""Unit tests for Tool & Interface Design: docstrings, explicit Pydantic JSON schemas, and guided error recovery."""

from __future__ import annotations

from sentinel_agent.tools import (
    ALL_SENTINEL_TOOLS,
    TOOL_JSON_SCHEMAS,
    analyze_cloud_cost_anomaly_report,
    create_critical_incident_ticket,
    execute_production_service_rollback,
    query_production_telemetry_metrics,
    record_postmortem_action_item,
    search_sre_runbook_knowledge_base,
)


def test_all_tools_have_comprehensive_docstrings_and_json_schemas() -> None:
    """Verify every custom tool has a comprehensive docstring and explicit input/output JSON schema."""
    assert len(ALL_SENTINEL_TOOLS) == 6
    for tool_fn in ALL_SENTINEL_TOOLS:
        name = tool_fn.__name__
        assert tool_fn.__doc__ is not None and len(tool_fn.__doc__.strip()) > 120
        assert "Args:" in tool_fn.__doc__
        assert "Returns:" in tool_fn.__doc__
        assert name in TOOL_JSON_SCHEMAS
        assert "properties" in TOOL_JSON_SCHEMAS[name]["input_schema"]
        assert "properties" in TOOL_JSON_SCHEMAS[name]["output_schema"]


def test_guided_error_recovery_on_invalid_tool_inputs() -> None:
    """Verify tools return structured recovery_guidance and suggested_next_action instead of raising exceptions."""
    bad_telemetry = query_production_telemetry_metrics(service_name="x", lookback_minutes=2)
    assert bad_telemetry["status"] == "error"
    assert bad_telemetry["error_code"] == "INVALID_TELEMETRY_PARAMETERS"
    assert bad_telemetry["recovery_guidance"]
    assert bad_telemetry["suggested_next_action"]

    unknown_service = query_production_telemetry_metrics(service_name="non-existent-service")
    assert unknown_service["status"] == "error"
    assert unknown_service["error_code"] == "SERVICE_NOT_FOUND_IN_TELEMETRY"
    assert "checkout-payment-service" in unknown_service["recovery_guidance"]

    bad_runbook = search_sre_runbook_knowledge_base(symptom_query="ab", top_k=99)
    assert bad_runbook["status"] == "error"
    assert bad_runbook["error_code"] == "INVALID_RUNBOOK_SEARCH_QUERY"

    bad_cost = analyze_cloud_cost_anomaly_report(
        service_name="unknown-workload", budget_variance_threshold_percent=25.0
    )
    assert bad_cost["status"] == "error"
    assert bad_cost["error_code"] == "COST_REPORT_NOT_FOUND"

    bad_ticket = create_critical_incident_ticket(
        service_name="checkout-payment-service",
        severity="P9",
        title="x",
        root_cause_hypothesis="short",
    )
    assert bad_ticket["status"] == "error"
    assert bad_ticket["error_code"] == "INVALID_INCIDENT_TICKET_SCHEMA"

    bad_pm = record_postmortem_action_item(
        incident_id="I",
        owner_team="s",
        remediation_summary="short",
        preventative_measure="short",
    )
    assert bad_pm["status"] == "error"
    assert bad_pm["error_code"] == "INVALID_POSTMORTEM_SCHEMA"


def test_hitl_gate_on_production_rollback_tool() -> None:
    """Verify execute_production_service_rollback blocks without approval token and succeeds with token."""
    paused = execute_production_service_rollback(
        service_name="checkout-payment-service",
        target_revision="v2.13.4-stable",
        reason="Rollback canary 503 spike",
        human_approval_token=None,
    )
    assert paused["status"] == "requires_human_approval"
    assert paused["error_code"] == "HITL_CONFIRMATION_REQUIRED"
    assert "APPROVED-BY-SRE" in paused["recovery_guidance"]

    approved = execute_production_service_rollback(
        service_name="checkout-payment-service",
        target_revision="v2.13.4-stable",
        reason="Rollback canary 503 spike",
        human_approval_token="APPROVED-BY-SRE",
    )
    assert approved["status"] == "success"
    assert approved["data"]["restored_revision"] == "v2.13.4-stable"
