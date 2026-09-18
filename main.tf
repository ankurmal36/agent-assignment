# ==============================================================================
# Root Terraform Infrastructure as Code (IaC) Entrypoint for CloudOps Sentinel
# Provisions: Artifact Registry, Secret Manager, Least-Privilege Service Account,
# and Cloud Run v2 Service hosting the Google ADK Multi-Agent Application.
# ==============================================================================

terraform {
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

variable "project_id" {
  description = "Google Cloud Project ID hosting CloudOps Sentinel"
  type        = string
  default     = "cloudops-sentinel-prod"
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

output "cloud_run_service_url" {
  description = "Public HTTPS endpoint of the deployed CloudOps Sentinel ADK service"
  value       = google_cloud_run_v2_service.sentinel_service.uri
}

output "runtime_service_account_email" {
  description = "Least-privilege service account email bound to Secret Manager and Cloud DLP"
  value       = google_service_account.sentinel_runtime_sa.email
}
