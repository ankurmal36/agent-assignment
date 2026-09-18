variable "project_id" {
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
