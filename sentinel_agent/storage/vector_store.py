"""Persistent Vector RAG Store for SRE Runbooks and FinOps Playbooks with exact anchor deep-links."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from sentinel_agent.config import BASE_DIR, settings
from sentinel_agent.telemetry.tracer import pii_redactor


class RunbookVectorStore:
    """Hybrid Vector Store persisting embeddings to disk with cosine similarity search and citation anchors."""

    def __init__(self, index_path: str | None = None) -> None:
        self.index_path = Path(index_path or settings.vector_index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.documents: list[dict[str, Any]] = []
        self._load_or_seed_default_runbooks()

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9_]+", text.lower())

    def _compute_sparse_vector(self, text: str) -> dict[str, float]:
        tokens = self._tokenize(text)
        counts = Counter(tokens)
        norm = math.sqrt(sum(val * val for val in counts.values())) or 1.0
        return {tok: round(cnt / norm, 6) for tok, cnt in counts.items()}

    @staticmethod
    def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        shared = set(vec_a.keys()) & set(vec_b.keys())
        return round(sum(vec_a[k] * vec_b[k] for k in shared), 4)

    def _load_or_seed_default_runbooks(self) -> None:
        if self.index_path.exists():
            try:
                self.documents = json.loads(self.index_path.read_text(encoding="utf-8"))
                if self.documents:
                    return
            except Exception:
                pass

        seed_file = BASE_DIR / "sample_data" / "sre_runbooks.json"
        if seed_file.exists():
            raw_docs = json.loads(seed_file.read_text(encoding="utf-8"))
            for doc in raw_docs:
                self.upsert_document(
                    doc_id=doc["doc_id"],
                    title=doc["title"],
                    service_domain=doc["service_domain"],
                    section_anchor=doc["section_anchor"],
                    content=doc["content"],
                    remediation_steps=doc.get("remediation_steps", []),
                    persist=False,
                )
            self._persist()
        else:
            # Built-in fallback runbooks so the store is never empty
            default_docs = [
                {
                    "doc_id": "RUNBOOK-PAYMENT-503",
                    "title": "Checkout & Payment Gateway 5xx Latency Spike Runbook",
                    "service_domain": "checkout-payment-service",
                    "section_anchor": "https://runbooks.internal.example/sre/checkout-payment#connection-pool-exhaustion",
                    "content": (
                        "When checkout-payment-service experiences HTTP 503 errors and p99 latency > 1500ms "
                        "following a canary deployment, inspect Cloud SQL connection pool saturation and "
                        "execute a production service rollback to the previous stable revision."
                    ),
                    "remediation_steps": [
                        "Verify error rate and p99 latency via query_production_telemetry_metrics.",
                        "Open a P1/P0 incident via create_critical_incident_ticket.",
                        "Request Human-in-the-Loop approval and run execute_production_service_rollback.",
                    ],
                },
                {
                    "doc_id": "RUNBOOK-FINOPS-GPU-SPIKE",
                    "title": "Vertex AI & GKE GPU Autoscaler Cost Anomaly Playbook",
                    "service_domain": "ml-inference-cluster",
                    "section_anchor": "https://runbooks.internal.example/finops/gpu-cost-spike#idle-node-pool-scale-down",
                    "content": (
                        "If daily cloud spend on ml-inference-cluster exceeds the FinOps budget threshold by >40%, "
                        "check unattached A100/H100 GPU replica pools and orphan batch jobs."
                    ),
                    "remediation_steps": [
                        "Run analyze_cloud_cost_anomaly_report for ml-inference-cluster.",
                        "Cap max-nodes on spot GPU node pool and record a postmortem action item.",
                    ],
                },
            ]
            for doc in default_docs:
                self.upsert_document(
                    doc_id=doc["doc_id"],
                    title=doc["title"],
                    service_domain=doc["service_domain"],
                    section_anchor=doc["section_anchor"],
                    content=doc["content"],
                    remediation_steps=doc["remediation_steps"],
                    persist=False,
                )
            self._persist()

    def _persist(self) -> None:
        self.index_path.write_text(json.dumps(self.documents, indent=2), encoding="utf-8")

    def upsert_document(
        self,
        doc_id: str,
        title: str,
        service_domain: str,
        section_anchor: str,
        content: str,
        remediation_steps: list[str] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """Embed and persist a runbook or postmortem document into the vector store."""
        safe_content = pii_redactor.redact_text(content)
        combined_text = (
            f"{title} {service_domain} {safe_content} {' '.join(remediation_steps or [])}"
        )
        vector = self._compute_sparse_vector(combined_text)
        record = {
            "doc_id": doc_id,
            "title": title,
            "service_domain": service_domain,
            "section_anchor": section_anchor,
            "content": safe_content,
            "remediation_steps": remediation_steps or [],
            "vector": vector,
        }
        self.documents = [d for d in self.documents if d["doc_id"] != doc_id]
        self.documents.append(record)
        if persist:
            self._persist()
        return record

    def search(
        self, query: str, service_filter: str | None = None, top_k: int = 3
    ) -> list[dict[str, Any]]:
        """Retrieve top-k semantically matching runbooks with similarity scores and deep-link anchors."""
        query_vec = self._compute_sparse_vector(query)
        scored: list[dict[str, Any]] = []
        for doc in self.documents:
            if service_filter and service_filter.lower() not in doc["service_domain"].lower():
                # Boost rather than hard-exclude if service_filter is partial
                domain_bonus = 0.0
            else:
                domain_bonus = 0.15 if service_filter else 0.0
            sim = self._cosine_similarity(query_vec, doc.get("vector", {})) + domain_bonus
            if sim > 0:
                scored.append(
                    {
                        "doc_id": doc["doc_id"],
                        "title": doc["title"],
                        "service_domain": doc["service_domain"],
                        "section_anchor": doc["section_anchor"],
                        "exact_quote": doc["content"],
                        "remediation_steps": doc.get("remediation_steps", []),
                        "similarity_score": round(min(sim, 1.0), 4),
                    }
                )
        scored.sort(key=lambda item: item["similarity_score"], reverse=True)
        return scored[:top_k]


vector_store = RunbookVectorStore()
