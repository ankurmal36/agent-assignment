"""Google Cloud Secret Manager integration for secure credential retrieval without hardcoded keys."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("sentinel_agent.secret_manager")


class SecretManagerVault:
    """Retrieves secrets from Google Cloud Secret Manager with safe environment fallback."""

    def __init__(self, project_id: str | None = None, enabled: bool = False) -> None:
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID", "")
        self.enabled = enabled or (os.getenv("USE_SECRET_MANAGER", "FALSE").upper() == "TRUE")

    def get_secret(self, secret_id: str, env_var_fallback: str, version_id: str = "latest") -> str:
        """Fetch a secret payload from Google Cloud Secret Manager or fall back to environment variables.

        Args:
            secret_id: The Google Cloud Secret Manager identifier (e.g., 'sentinel-gemini-api-key').
            env_var_fallback: Environment variable name to check when running locally or in CI.
            version_id: Secret version to access (defaults to 'latest').

        Returns:
            The resolved secret string, or empty string if unavailable.
        """
        env_value = os.getenv(env_var_fallback, "").strip()
        if env_value:
            return env_value

        if not self.enabled or not self.project_id or self.project_id == "your-gcp-project-id":
            return ""

        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            resource_name = f"projects/{self.project_id}/secrets/{secret_id}/versions/{version_id}"
            response = client.access_secret_version(request={"name": resource_name})
            payload: str = response.payload.data.decode("UTF-8").strip()
            return payload
        except Exception as exc:
            logger.warning(
                "Secret Manager lookup skipped or failed for secret_id=%s: %s",
                secret_id,
                exc,
            )
            return ""
