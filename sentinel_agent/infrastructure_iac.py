"""Programmatic Infrastructure as Code (Terraform HCL + CDKTF JSON + ADK CLI) for CloudOps Sentinel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TERRAFORM_MAIN_HCL = """terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "required_apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "dlp.googleapis.com",
    "aiplatform.googleapis.com"
  ])
  service            = each.key
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "sentinel_repo" {
  location      = var.region
  repository_id = "${var.service_name}-repo"
  description   = "Container registry for CloudOps Sentinel ADK Agent"
  format        = "DOCKER"
  depends_on    = [google_project_service.required_apis]
}

resource "google_service_account" "sentinel_runtime_sa" {
  account_id   = "${var.service_name}-sa"
  display_name = "CloudOps Sentinel ADK Runtime Service Account"
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = var.gemini_secret_id
  replication {
    auto {}
  }
  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_iam_member" "sentinel_secret_accessor" {
  secret_id = google_secret_manager_secret.gemini_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sentinel_runtime_sa.email}"
}

resource "google_project_iam_member" "sentinel_dlp_user" {
  project = var.project_id
  role    = "roles/dlp.user"
  member  = "serviceAccount:${google_service_account.sentinel_runtime_sa.email}"
}

resource "google_cloud_run_v2_service" "sentinel_service" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.sentinel_runtime_sa.email

    containers {
      image = var.container_image

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "USE_SECRET_MANAGER"
        value = "TRUE"
      }
      env {
        name  = "GEMINI_SECRET_ID"
        value = var.gemini_secret_id
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.sentinel_secret_accessor]
}
"""

TERRAFORM_VARIABLES_HCL = """variable "project_id" {
  description = "Google Cloud Project ID hosting CloudOps Sentinel"
  type        = string
}

variable "region" {
  description = "Primary GCP region for Cloud Run and Artifact Registry"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name"
  type        = string
  default     = "cloudops-sentinel"
}

variable "gemini_secret_id" {
  description = "Secret Manager ID storing the Gemini API key"
  type        = string
  default     = "sentinel-gemini-api-key"
}

variable "container_image" {
  description = "Full Artifact Registry container image URI"
  type        = string
  default     = "us-central1-docker.pkg.dev/cloudops-sentinel-prod/cloudops-sentinel-repo/sentinel:latest"
}
"""

TERRAFORM_OUTPUTS_HCL = """output "cloud_run_service_url" {
  description = "Public HTTPS endpoint of the deployed CloudOps Sentinel ADK service"
  value       = google_cloud_run_v2_service.sentinel_service.uri
}

output "runtime_service_account_email" {
  description = "Least-privilege service account email bound to Secret Manager and Cloud DLP"
  value       = google_service_account.sentinel_runtime_sa.email
}

output "artifact_registry_repository" {
  description = "Artifact Registry Docker repository ID"
  value       = google_artifact_registry_repository.sentinel_repo.name
}
"""


def build_terraform_json_manifest(
    project_id: str = "cloudops-sentinel-prod",
    region: str = "us-central1",
    service_name: str = "cloudops-sentinel",
) -> dict[str, Any]:
    """Generate a Terraform JSON configuration (`main.tf.json`) and ADK deployment manifest."""
    return {
        "terraform": {
            "required_version": ">= 1.5.0",
            "required_providers": {"google": {"source": "hashicorp/google", "version": "~> 5.0"}},
        },
        "provider": {"google": {"project": project_id, "region": region}},
        "resource": {
            "google_service_account": {
                "sentinel_runtime_sa": {
                    "account_id": f"{service_name}-sa",
                    "display_name": "CloudOps Sentinel ADK Runtime Service Account",
                }
            },
            "google_secret_manager_secret": {
                "gemini_api_key": {
                    "secret_id": "sentinel-gemini-api-key",
                    "replication": {"auto": {}},
                }
            },
            "google_cloud_run_v2_service": {
                "sentinel_service": {
                    "name": service_name,
                    "location": region,
                    "ingress": "INGRESS_TRAFFIC_ALL",
                }
            },
        },
        "adk_cli_commands": [
            "adk web sentinel_agent",
            "adk run sentinel_agent",
            "adk eval sentinel_agent tests/eval_dataset.json",
            f"adk deploy cloud_run --project={project_id} --region={region} --service_name={service_name} sentinel_agent",
        ],
    }


def export_terraform_files(target_dir: Path) -> dict[str, str]:
    """Write `main.tf`, `variables.tf`, `outputs.tf`, and `main.tf.json` to disk."""
    target_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "main.tf": TERRAFORM_MAIN_HCL,
        "variables.tf": TERRAFORM_VARIABLES_HCL,
        "outputs.tf": TERRAFORM_OUTPUTS_HCL,
        "main.tf.json": json.dumps(build_terraform_json_manifest(), indent=2),
    }
    for filename, content in files.items():
        (target_dir / filename).write_text(content, encoding="utf-8")
    return files
