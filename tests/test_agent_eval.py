"""Golden Dataset Automated Regression Evaluation Harness for CloudOps Sentinel."""

from __future__ import annotations

import json
from pathlib import Path

from sentinel_agent.agent.adk_agent import build_adk_agent_hierarchy
from sentinel_agent.agent.core import CloudOpsSentinelOrchestrator

EVAL_DATASET_PATH = Path(__file__).resolve().parent / "eval_dataset.json"


def test_adk_hierarchy_and_compaction_wiring() -> None:
    """Verify native Google ADK Coordinator, 4 Worker Sub-Agents, and callbacks are properly wired."""
    coordinator, workers, adk_app = build_adk_agent_hierarchy()
    assert coordinator.name == "SentinelCoordinatorAgent"
    assert len(workers) == 4
    worker_names = {w.name for w in workers}
    assert worker_names == {
        "TelemetryDiagnosticsAgent",
        "RunbookKnowledgeAgent",
        "FinOpsAnomalyAgent",
        "RemediationExecutionAgent",
    }
    assert adk_app is not None


def test_golden_dataset_regression_suite() -> None:
    """Evaluate CloudOps Sentinel against all golden benchmark cases for routing, grounding, HITL, and guardrails."""
    cases = json.loads(EVAL_DATASET_PATH.read_text(encoding="utf-8"))
    orchestrator = CloudOpsSentinelOrchestrator()

    passed_count = 0
    for case in cases:
        result = orchestrator.handle_query(
            user_query=case["query"],
            session_id=f"eval-session-{case['case_id']}",
            human_approval_token=case.get("approval_token"),
        )
        assert result.status == case["expected_status"], (
            f"Case {case['case_id']} failed status check: got {result.status}, expected {case['expected_status']}"
        )
        assert result.selected_model == case["expected_model"], (
            f"Case {case['case_id']} failed model routing check: got {result.selected_model}"
        )
        assert result.intent_category == case["expected_intent"]
        assert result.latency_ms < 2000.0, f"Latency SLA breached on {case['case_id']}"

        for expected_sub in case["expected_substrings"]:
            assert expected_sub in result.response_text, (
                f"Case {case['case_id']} missing expected substring '{expected_sub}' in response:\n{result.response_text}"
            )
        passed_count += 1

    assert passed_count == len(cases)
