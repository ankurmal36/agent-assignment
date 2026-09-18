# 🏛️ Enterprise Production Agent Best Practices Guide

> **A Blueprint for Designing, Orchestrating, Securing, and Operating Production-Grade AI Agents with the Google Agent Development Kit (ADK)**

Building a prototype LLM wrapper takes minutes; engineering a **reliable, auditable, low-latency, and secure Enterprise Agent** requires disciplined software architecture across five foundational pillars (**AgentOps**):

1. **Tool & Interface Design (Contract-Driven Tooling)**
2. **Context Engineering & Multi-Tier Memory**
3. **Multi-Agent Orchestration, Model Routing & Safety Governance**
4. **Observability, Distributed Tracing & Privacy (PII Redaction)**
5. **Production Infrastructure, Secret Management & Continuous Evaluation (CI/CD)**

---

## 🧭 Architecture Blueprint

```mermaid
flowchart LR
    subgraph Pillar1["1. Tool & Interface Contracts"]
        Docstrings["LLM-Optimized Docstrings"]
        Pydantic["Strict Pydantic JSON Schemas (extra='forbid')"]
        Recovery["Guided Error Recovery (recovery_guidance)"]
    end

    subgraph Pillar2["2. Context & Memory"]
        Constitution["System Prompt Constitution"]
        Compaction["Sliding-Window & Summary Compaction"]
        HybridStore["SQLite State + Vector RAG Store"]
        AsyncMem["Non-Blocking AsyncMemoryWorker"]
    end

    subgraph Pillar3["3. Orchestration & Governance"]
        ADK["Google ADK Coordinator + Worker Sub-Agents"]
        Routing["Strategic Model Routing (Flash vs Pro)"]
        Guardrails["Input/Output Policy Guardrails"]
        HITL["Human-in-the-Loop (HITL) Code Stops"]
    end

    subgraph Pillar4["4. Observability & Privacy"]
        OTel["OpenTelemetry Parent/Child Spans"]
        IntentOutcome["INTENT vs OUTCOME JSON Logs"]
        DLP["Cloud DLP + Regex PII Redaction"]
    end

    subgraph Pillar5["5. Infrastructure & CI/CD"]
        GoldenEval["Golden Dataset Regression Suite"]
        Terraform["Terraform GCP IaC (Cloud Run + IAM)"]
        SecretMgr["Google Cloud Secret Manager"]
    end

    Pillar1 --> Pillar3
    Pillar2 --> Pillar3
    Pillar3 --> Pillar4
    Pillar4 --> Pillar5
```

---

## 🛠️ Pillar 1: Tool & Interface Design

Tools are the API boundary between stochastic LLM reasoning and deterministic enterprise systems.

### 1.1 Use Action-Specific, Unambiguous Tool Names
- **Anti-Pattern**: Generic, overloaded tools such as `manage_service(action, payload)` or `update_jira(data)`.
- **Best Practice**: Name tools with explicit domain verbs and target nouns so the model's tool-selection distribution is sharp:
  - `query_production_telemetry_metrics`
  - `search_sre_runbook_knowledge_base`
  - `analyze_cloud_cost_anomaly_report`
  - `create_critical_incident_ticket`
  - `execute_production_service_rollback`
  - `record_postmortem_action_item`

### 1.2 Write Comprehensive Docstrings for the Model
- **Best Practice**: Google ADK and modern function-calling runtimes serialize Python docstrings directly into the tool declaration prompt. Every tool docstring should state:
  1. **Purpose**: *When* and *why* the agent should call the tool.
  2. **Args**: Type constraints, valid ranges, and concrete examples (e.g., `'checkout-payment-service'`).
  3. **Returns**: Exact structure of the JSON payload on both success and failure.

### 1.3 Enforce Strict Input & Output JSON Schemas
- **Best Practice**: Validate all tool inputs and outputs with **Pydantic v2 `BaseModel`** using `ConfigDict(extra="forbid")` and constrained `Field(...)` rules (`min_length`, `ge`, `le`, `Literal`).
- Reject hallucinated parameters before they ever reach downstream APIs or databases (see [`sentinel_agent/tools/schemas.py`](sentinel_agent/tools/schemas.py)).

### 1.4 Return Guided Error Recovery Instead of Raising Exceptions
- **Anti-Pattern**: Allowing a `KeyError`, `ValueError`, or HTTP 500 to crash the agent turn.
- **Best Practice**: Catch validation and lookup failures inside the tool and return a structured recovery object:
  ```json
  {
    "status": "error",
    "tool_name": "query_production_telemetry_metrics",
    "error_code": "SERVICE_NOT_FOUND_IN_TELEMETRY",
    "recovery_guidance": "No telemetry stream found for 'foo'. Available monitored services: [checkout-payment-service, identity-auth-service, ml-inference-cluster].",
    "suggested_next_action": "Re-invoke query_production_telemetry_metrics using one of the available service names."
  }
  ```
  This enables the LLM to **self-correct autonomously** on the next step.

---

## 🧠 Pillar 2: Context Engineering & Multi-Tier Memory

Unbounded conversation histories degrade reasoning quality, inflate token costs, and exceed context limits.

### 2.1 Define an Immutable System Constitution
- **Best Practice**: Structure the system prompt as an explicit **Agent Constitution** ([`sentinel_agent/agent/prompts.py`](sentinel_agent/agent/prompts.py)) with:
  1. **Persona & Mission**
  2. **Evidence-First Grounding Rules** (mandatory `[DOC-ID](section_anchor)` citations)
  3. **Safety & HITL Boundaries** (never execute destructive actions without human approval)
  4. **Prompt Injection Resistance**
  5. **Standardized Output Template**

### 2.2 Implement Token-Aware History Compaction
- **Best Practice**: Combine a **sliding window** of recent verbatim turns (e.g., last `N=8` turns within a strict token budget) with a **rolling summary** of older evicted turns persisted in SQLite, plus native **Google ADK `EventsCompactionConfig`** ([`sentinel_agent/storage/compaction.py`](sentinel_agent/storage/compaction.py)).

### 2.3 Separate Relational State from Semantic Vector RAG Memory
- **Relational Store (`SQLite` / `Cloud SQL`)**: Store structured session messages, rolling summaries, incident tickets, and audit trails ([`sentinel_agent/storage/database.py`](sentinel_agent/storage/database.py)).
- **Semantic Vector Store (`RunbookVectorStore` / `Vertex AI Vector Search`)**: Store chunked runbooks and postmortem learnings with exact section anchor URLs (`section_anchor`) so the agent can quote authoritative guidance verbatim ([`sentinel_agent/storage/vector_store.py`](sentinel_agent/storage/vector_store.py)).

### 2.4 Offload Memory Consolidation to Non-Blocking Async Workers
- **Anti-Pattern**: Computing embeddings or summarizing long histories synchronously before returning the assistant's reply.
- **Best Practice**: Dispatch post-turn summarization and vector indexing to a background thread/queue (`AsyncMemoryWorker` in [`sentinel_agent/storage/async_worker.py`](sentinel_agent/storage/async_worker.py)) so user-facing latency remains sub-second.

---

## 🎼 Pillar 3: Multi-Agent Orchestration, Model Routing & Governance

Monolithic single-prompt agents struggle when given dozens of tools and conflicting domain instructions.

### 3.1 Decompose Complex Workflows with Multi-Agent Patterns in Google ADK
- **Best Practice**: Use a **Coordinator / Supervisor-Worker pattern** (`SentinelCoordinatorAgent`) backed by specialized Google ADK `LlmAgent` and `SequentialAgent` workers ([`sentinel_agent/agent/adk_agent.py`](sentinel_agent/agent/adk_agent.py)):
  - `TelemetryDiagnosticsAgent`: Golden-signal metric inspection
  - `RunbookKnowledgeAgent`: Vector RAG runbook search & citation
  - `FinOpsAnomalyAgent`: Cloud billing variance & GPU optimization
  - `RemediationExecutionAgent`: Incident creation, HITL-gated rollbacks, and postmortem logging

### 3.2 Apply Strategic Model Routing (`Flash` vs `Pro`)
- **Best Practice**: Route each request based on reasoning complexity ([`StrategicModelRouter`](sentinel_agent/agent/core.py)):
  - **Fast Tier (`gemini-2.5-flash`)**: Intent classification, single-tool metric triage, runbook RAG lookups, and FinOps cost variance reports (optimizing for low latency and cost).
  - **Reasoning Tier (`gemini-2.5-pro`)**: Multi-signal outage root-cause correlation and high-stakes production remediation planning (optimizing for accuracy and safety).

### 3.3 Enforce Defense-in-Depth Input & Output Guardrails
- **Pre-Model Input Guardrail (`before_model_callback`)**: Inspect incoming prompts for prompt injection (`ignore previous instructions`), secret exfiltration attempts, and destructive commands (`DROP TABLE`, `rm -rf`), and scrub PII before the prompt reaches the model ([`sentinel_agent/agent/guardrails.py`](sentinel_agent/agent/guardrails.py)).
- **Post-Model Output Self-Eval Guardrail (`after_model_callback`)**: Score response grounding against executed tool evidence (`grounding_score`) and scrub any residual PII before returning text to the user.

### 3.4 Gate High-Stakes Mutations with Human-in-the-Loop (HITL) Hooks
- **Best Practice**: Never allow an autonomous agent to mutate production infrastructure (e.g., `execute_production_service_rollback`) without an explicit **code stop**.
- Implement both a tool-level check and an ADK `before_tool_callback` (`adk_before_tool_hitl_hook`) that halts execution with `status="requires_human_approval"` until a verified human operator token (`APPROVED-BY-SRE`) is supplied.

---

## 🔭 Pillar 4: Observability, Distributed Tracing & Data Privacy

In production, you cannot improve or audit an agent whose internal reasoning and tool calls are opaque.

### 4.1 Emit Structured JSON Logs (Zero Bare `print()` Calls)
- **Best Practice**: Format every log event as single-line structured JSON (`StructuredJsonFormatter` in [`sentinel_agent/telemetry/tracer.py`](sentinel_agent/telemetry/tracer.py)) containing `timestamp`, `level`, `event_type`, `agent_name`, `trace_id`, `span_id`, and `metadata`.

### 4.2 Capture Explicit `INTENT` vs. `OUTCOME` Pairs
- **Best Practice**: Log a two-phase audit trail around every tool and sub-agent execution:
  1. **Pre-Execution `INTENT` (`log_intent_before_execution`)**: Records the agent's planned action, arguments, and engineering rationale *before* the side effect occurs.
  2. **Post-Execution `OUTCOME` (`log_outcome_after_execution`)**: Records the actual return payload, status (`SUCCESS`, `PAUSED_FOR_HITL`, `VALIDATION_ERROR`), and wall-clock `latency_ms` *after* execution.

### 4.3 Instrument End-to-End OpenTelemetry Distributed Tracing
- **Best Practice**: Use `opentelemetry-api` and `opentelemetry-sdk` (`TracerProvider`) to create hierarchical parent-child spans (`sentinel.handle_query` $\rightarrow$ `sentinel.model_routing` $\rightarrow$ `sentinel.subagent_delegation` $\rightarrow$ `tool.<name>`) so every tool call shares a unified `trace_id`.

### 4.4 Scrub Sensitive Data with Active PII Redaction
- **Best Practice**: Pass all log messages, span attributes, and SQLite/Vector memory writes through an active `PIIRedactor` combining **Google Cloud Data Loss Prevention (`google-cloud-dlp`)** and deterministic regex patterns for emails, phone numbers, SSNs, credit card numbers, and API keys (`[REDACTED_EMAIL]`, `[REDACTED_SSN]`, `[REDACTED_API_KEY]`).

---

## 🏗️ Pillar 5: Production Infrastructure, Secret Management & CI/CD

### 5.1 Benchmark Every Commit Against a Golden Evaluation Dataset
- **Best Practice**: Maintain a curated golden dataset ([`tests/eval_dataset.json`](tests/eval_dataset.json)) and automated evaluation suite ([`tests/test_agent_eval.py`](tests/test_agent_eval.py)) that assert:
  - Expected model routing (`gemini-2.5-flash` vs `gemini-2.5-pro`)
  - Expected intent & sub-agent delegation trajectory
  - Mandatory grounding citations in responses
  - HITL blocking on unapproved rollbacks and execution on approved tokens
  - Guardrail blocking on prompt-injection attacks
  - End-to-end latency SLAs

### 5.2 Provision Cloud Resources Declaratively with Terraform (IaC)
- **Best Practice**: Codify all cloud infrastructure in Terraform ([`terraform/main.tf`](terraform/main.tf), [`terraform/variables.tf`](terraform/variables.tf), [`terraform/outputs.tf`](terraform/outputs.tf), and [`sentinel_agent/infrastructure_iac.py`](sentinel_agent/infrastructure_iac.py)):
  - Least-privilege Runtime Service Account (`google_service_account`)
  - Container Artifact Registry (`google_artifact_registry_repository`)
  - Secret Manager Vault & IAM bindings (`google_secret_manager_secret_iam_member`)
  - Serverless Cloud Run v2 deployment (`google_cloud_run_v2_service`)

### 5.3 Inject Credentials via Google Cloud Secret Manager
- **Anti-Pattern**: Hardcoding keys in source files or committing `.env` files to Git.
- **Best Practice**: Fetch runtime secrets programmatically via `google-cloud-secret-manager` ([`sentinel_agent/storage/secret_manager.py`](sentinel_agent/storage/secret_manager.py)) or mount them directly as Cloud Run secret environment variables, keeping only a sanitized `.env.example` in version control.
