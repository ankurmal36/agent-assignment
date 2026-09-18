"""Typed configuration management for CloudOps Sentinel with Secret Manager injection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class SentinelSettings:
    """Centralized configuration settings loaded from Secret Manager and environment variables."""

    gcp_project_id: str = field(
        default_factory=lambda: os.getenv("GCP_PROJECT_ID", "cloudops-sentinel-prod")
    )
    gcp_location: str = field(default_factory=lambda: os.getenv("GCP_LOCATION", "us-central1"))
    use_secret_manager: bool = field(
        default_factory=lambda: os.getenv("USE_SECRET_MANAGER", "FALSE").upper() == "TRUE"
    )
    gemini_secret_id: str = field(
        default_factory=lambda: os.getenv("GEMINI_SECRET_ID", "sentinel-gemini-api-key")
    )
    enable_cloud_dlp: bool = field(
        default_factory=lambda: os.getenv("ENABLE_CLOUD_DLP", "FALSE").upper() == "TRUE"
    )
    router_model_flash: str = field(
        default_factory=lambda: os.getenv("ROUTER_MODEL_FLASH", "gemini-2.5-flash")
    )
    synthesis_model_pro: str = field(
        default_factory=lambda: os.getenv("SYNTHESIS_MODEL_PRO", "gemini-2.5-pro")
    )
    sqlite_db_path: str = field(
        default_factory=lambda: os.getenv(
            "SQLITE_DB_PATH", str(BASE_DIR / "data" / "sentinel_state.db")
        )
    )
    vector_index_path: str = field(
        default_factory=lambda: os.getenv(
            "VECTOR_INDEX_PATH", str(BASE_DIR / "data" / "runbook_vectors.json")
        )
    )
    max_context_tokens: int = field(
        default_factory=lambda: int(os.getenv("MAX_CONTEXT_TOKENS", "4096"))
    )
    sliding_window_turns: int = field(
        default_factory=lambda: int(os.getenv("SLIDING_WINDOW_TURNS", "8"))
    )
    otel_service_name: str = field(
        default_factory=lambda: os.getenv("OTEL_SERVICE_NAME", "cloudops-sentinel-agent")
    )
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    gemini_api_key: str = field(default="")

    def resolve_secrets(self) -> None:
        """Resolve secrets from Google Cloud Secret Manager after module initialization."""
        from sentinel_agent.storage.secret_manager import SecretManagerVault

        vault = SecretManagerVault(
            project_id=self.gcp_project_id,
            enabled=self.use_secret_manager,
        )
        if not self.gemini_api_key:
            self.gemini_api_key = vault.get_secret(
                secret_id=self.gemini_secret_id,
                env_var_fallback="GEMINI_API_KEY",
            )


settings = SentinelSettings()
settings.resolve_secrets()
