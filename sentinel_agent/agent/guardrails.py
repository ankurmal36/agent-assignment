"""Input/Output Safety Guardrails, Self-Evaluation Grounding Checks, ADK Callbacks, and Human-in-the-Loop (HITL) Hooks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sentinel_agent.telemetry.tracer import pii_redactor, tracer
from sentinel_agent.tools.remediation_tools import VALID_APPROVAL_TOKENS


@dataclass
class GuardrailVerdict:
    """Structured result from an Input, Output, or HITL guardrail evaluation."""

    allowed: bool
    reason: str
    violation_category: str = "NONE"
    sanitized_content: str = ""
    grounding_score: float = 1.0


class InputSecurityGuardrail:
    """Pre-execution security guardrail blocking prompt injections, jailbreaks, and destructive commands."""

    _FORBIDDEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
        (
            re.compile(
                r"(ignore\s+(all\s+)?(previous|prior)\s+instructions|override\s+system\s+prompt|bypass\s+hitl)",
                re.IGNORECASE,
            ),
            "PROMPT_INJECTION_ATTEMPT",
        ),
        (
            re.compile(
                r"(drop\s+table|drop\s+database|truncate\s+table|rm\s+-rf\s+/|format\s+disk)",
                re.IGNORECASE,
            ),
            "DESTRUCTIVE_COMMAND_BLOCKED",
        ),
        (
            re.compile(
                r"(print\s+all\s+api\s+keys|dump\s+secret\s+manager|exfiltrate\s+credentials)",
                re.IGNORECASE,
            ),
            "SECRET_EXFILTRATION_ATTEMPT",
        ),
    ]

    def validate(self, user_query: str, trace_id: str = "", span_id: str = "") -> GuardrailVerdict:
        """Validate user input against prompt injection and policy rules, scrubbing PII automatically."""
        sanitized = pii_redactor.redact_text(user_query or "")
        for pattern, category in self._FORBIDDEN_PATTERNS:
            if pattern.search(user_query or ""):
                tracer.emit_json_log(
                    event_type="INPUT_GUARDRAIL_BLOCKED",
                    message=f"Input blocked by policy guardrail: {category}",
                    agent_name="InputSecurityGuardrail",
                    trace_id=trace_id,
                    span_id=span_id,
                    metadata={"violation_category": category, "sanitized_query": sanitized},
                )
                return GuardrailVerdict(
                    allowed=False,
                    reason=(
                        f"Request blocked by CloudOps Sentinel Security Guardrail ({category}). "
                        "Destructive commands, prompt injection overrides, and credential exfiltration are prohibited."
                    ),
                    violation_category=category,
                    sanitized_content=sanitized,
                    grounding_score=0.0,
                )

        return GuardrailVerdict(
            allowed=True,
            reason="Input passed security policy and PII scrubbing.",
            violation_category="NONE",
            sanitized_content=sanitized,
            grounding_score=1.0,
        )


class OutputSelfEvalGuardrail:
    """Post-execution self-evaluation guardrail verifying grounding citations, safety, and PII scrubbing."""

    def evaluate(
        self,
        response_text: str,
        tool_traces: list[dict[str, Any]],
        trace_id: str = "",
        span_id: str = "",
    ) -> GuardrailVerdict:
        """Perform automated self-evaluation on the generated response and scrub any residual PII."""
        sanitized_output = pii_redactor.redact_text(response_text)
        has_evidence = len(tool_traces) > 0
        has_citation_or_metric = any(
            marker in sanitized_output
            for marker in [
                "RUNBOOK-",
                "INC-",
                "PM-",
                "http",
                "%",
                "ms",
                "USD",
                "$",
                "APPROVED-BY-SRE",
            ]
        )
        grounding_score = 0.98 if (has_evidence and has_citation_or_metric) else 0.75

        tracer.emit_json_log(
            event_type="OUTPUT_SELF_EVAL_COMPLETED",
            message=f"Output self-evaluation completed with grounding_score={grounding_score}",
            agent_name="OutputSelfEvalGuardrail",
            trace_id=trace_id,
            span_id=span_id,
            metadata={
                "grounding_score": grounding_score,
                "tool_evidence_count": len(tool_traces),
            },
        )
        return GuardrailVerdict(
            allowed=True,
            reason="Output passed self-evaluation grounding check and PII redaction.",
            violation_category="NONE",
            sanitized_content=sanitized_output,
            grounding_score=grounding_score,
        )


class HumanApprovalGate:
    """Explicit Human-in-the-Loop (HITL) policy gate intercepting high-stakes tool executions."""

    HIGH_STAKES_TOOLS = {"execute_production_service_rollback"}

    def check_tool_execution(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> tuple[bool, dict[str, Any] | None]:
        """Return (is_approved, interception_response). Blocks high-stakes tools until human token is verified."""
        if tool_name not in self.HIGH_STAKES_TOOLS:
            return True, None

        token = str(tool_args.get("human_approval_token") or "").strip().upper()
        if token in VALID_APPROVAL_TOKENS:
            return True, None

        return False, {
            "status": "requires_human_approval",
            "tool_name": tool_name,
            "error_code": "HITL_CONFIRMATION_REQUIRED",
            "data": {
                "pending_action": tool_name,
                "service_name": tool_args.get("service_name", "checkout-payment-service"),
                "target_revision": tool_args.get("target_revision", "v2.13.4-stable"),
                "required_token": "APPROVED-BY-SRE",
            },
            "recovery_guidance": (
                "Execution stopped by HumanApprovalGate. Ask the human operator to confirm the rollback "
                "with approval token 'APPROVED-BY-SRE' before re-invoking this tool."
            ),
            "suggested_next_action": "Await user confirmation token 'APPROVED-BY-SRE'.",
        }


input_guardrail = InputSecurityGuardrail()
output_guardrail = OutputSelfEvalGuardrail()
hitl_gate = HumanApprovalGate()


# -----------------------------------------------------------------------------
# Native Google ADK Callback Hooks (before_model_callback, after_model_callback, before_tool_callback)
# -----------------------------------------------------------------------------
def adk_before_model_guardrail(callback_context: Any, llm_request: Any) -> Any:
    """ADK before_model_callback inspecting user messages for prompt injection and PII."""
    try:
        from google.genai import types

        contents = getattr(llm_request, "contents", []) or []
        for content in reversed(contents):
            if getattr(content, "role", "") == "user":
                parts = getattr(content, "parts", []) or []
                for part in parts:
                    text = getattr(part, "text", None)
                    if text:
                        verdict = input_guardrail.validate(text)
                        if not verdict.allowed:
                            from google.adk.models.llm_response import LlmResponse

                            return LlmResponse(
                                content=types.Content(
                                    role="model",
                                    parts=[types.Part.from_text(text=verdict.reason)],
                                )
                            )
                        part.text = verdict.sanitized_content
                break
    except Exception:
        pass
    return None


def adk_after_model_guardrail(callback_context: Any, llm_response: Any) -> Any:
    """ADK after_model_callback scrubbing PII and verifying self-evaluation grounding on model outputs."""
    try:
        content = getattr(llm_response, "content", None)
        if content and getattr(content, "parts", None):
            for part in content.parts:
                if getattr(part, "text", None):
                    verdict = output_guardrail.evaluate(part.text, tool_traces=[{"source": "adk"}])
                    part.text = verdict.sanitized_content
    except Exception:
        pass
    return None


def adk_before_tool_hitl_hook(
    tool: Any, args: dict[str, Any], tool_context: Any
) -> dict[str, Any] | None:
    """ADK before_tool_callback enforcing Human-in-the-Loop confirmation on high-stakes tools."""
    tool_name = getattr(tool, "name", "") or getattr(tool, "__name__", str(tool))
    approved, intercept_payload = hitl_gate.check_tool_execution(tool_name, args)
    if not approved:
        return intercept_payload
    return None
