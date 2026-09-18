"""Streamlit Interactive Command Center for CloudOps Sentinel (Google ADK Multi-Agent SRE & FinOps Commander)."""

from __future__ import annotations

import streamlit as st

from sentinel_agent.agent.core import CloudOpsSentinelOrchestrator
from sentinel_agent.storage.database import db_manager
from sentinel_agent.telemetry.tracer import tracer

st.set_page_config(
    page_title="CloudOps Sentinel | Google ADK Multi-Agent Commander",
    page_icon="🛡️",
    layout="wide",
)

if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = CloudOpsSentinelOrchestrator()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_hitl_query" not in st.session_state:
    st.session_state.pending_hitl_query = None

st.title("🛡️ CloudOps Sentinel — Autonomous SRE & FinOps Multi-Agent Commander")
st.caption(
    "Built with **Google Agent Development Kit (ADK)** • **Strategic Model Routing (`gemini-2.5-flash` / `gemini-2.5-pro`)** "
    "• **Vector RAG + SQLite** • **OpenTelemetry Tracing & PII Redaction** • **Human-in-the-Loop (HITL) Gate**"
)

col_chat, col_telemetry = st.columns([3, 2])

with col_chat:
    st.subheader("💬 Multi-Agent Incident Response Console")

    preset_cols = st.columns(3)
    selected_prompt: str | None = None
    if preset_cols[0].button("🚨 Diagnose 503 Checkout Outage"):
        selected_prompt = "Diagnose the HTTP 503 latency spike on checkout-payment-service and cite the SRE runbook."
    if preset_cols[1].button("💸 Analyze GPU Cost Anomaly"):
        selected_prompt = "Analyze the cloud cost anomaly report for ml-inference-cluster."
    if preset_cols[2].button("⏪ Rollback Checkout Service (HITL)"):
        selected_prompt = (
            "Execute a production rollback on checkout-payment-service to mitigate the P0 outage."
        )

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input(
        "Ask CloudOps Sentinel to diagnose telemetry, search runbooks, analyze FinOps costs, or execute rollbacks..."
    )
    active_query = selected_prompt or user_input

    if active_query:
        st.session_state.messages.append({"role": "user", "content": active_query})
        with st.chat_message("user"):
            st.markdown(active_query)

        result = st.session_state.orchestrator.handle_query(active_query)
        st.session_state.messages.append({"role": "assistant", "content": result.response_text})
        if result.status == "PAUSED_FOR_HUMAN_APPROVAL":
            st.session_state.pending_hitl_query = active_query
        else:
            st.session_state.pending_hitl_query = None

        with st.chat_message("assistant"):
            st.markdown(result.response_text)

    if st.session_state.pending_hitl_query:
        st.warning(
            "⚠️ **Human-in-the-Loop Approval Required**: A high-stakes production service rollback is paused awaiting human confirmation."
        )
        if st.button("✅ Approve Rollback (`APPROVED-BY-SRE`)", type="primary"):
            approved_result = st.session_state.orchestrator.handle_query(
                st.session_state.pending_hitl_query,
                human_approval_token="APPROVED-BY-SRE",
            )
            st.session_state.messages.append(
                {"role": "assistant", "content": approved_result.response_text}
            )
            st.session_state.pending_hitl_query = None
            st.rerun()

with col_telemetry:
    st.subheader("🔭 OpenTelemetry & Intent-vs-Outcome Traces")
    recent_traces = tracer.get_recent_traces(limit=6)
    if recent_traces:
        for rec in reversed(recent_traces):
            with st.expander(
                f"Span `{rec['action_name']}` ({rec['status']} • {rec['latency_ms']}ms)"
            ):
                st.json(rec)
    else:
        st.info("Run a query to inspect live OpenTelemetry spans and Intent-vs-Outcome JSON logs.")

    st.subheader("🗄️ Persistent SQLite Incident & Postmortem State")
    st.json(
        {
            "open_incidents": db_manager.list_incidents(limit=5),
            "postmortem_actions": db_manager.list_postmortem_actions(limit=5),
        }
    )
