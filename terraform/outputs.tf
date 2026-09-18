output "cloud_run_service_url" {
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
