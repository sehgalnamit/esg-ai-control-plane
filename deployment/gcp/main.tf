# Reference Terraform for deploying the ESG AI Control Plane demo app to
# Google Cloud Run. This is a DEPLOYABLE TEMPLATE, not a live resource -- it
# has not been applied (terraform apply) against any real GCP project as
# part of building this repository. See docs/GCP_DEPLOYMENT.md for how to
# actually apply it.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

variable "project_id" {
  description = "GCP project ID to deploy into."
  type        = string
}

variable "region" {
  description = "GCP region."
  type        = string
  default     = "asia-southeast1"
}

variable "container_image" {
  description = "Container image to deploy, e.g. a tag pushed to Artifact Registry."
  type        = string
  default     = "ghcr.io/sehgalnamit/esg-ai-control-plane:latest"
}

variable "typesafe_api_key" {
  description = "Optional TypeSafe Jev API key. Leave blank to use the offline LocalJevStandIn."
  type        = string
  default     = ""
  sensitive   = true
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_secret_manager_secret" "typesafe_api_key" {
  count     = var.typesafe_api_key != "" ? 1 : 0
  secret_id = "esg-ai-control-plane-typesafe-api-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "typesafe_api_key" {
  count       = var.typesafe_api_key != "" ? 1 : 0
  secret      = google_secret_manager_secret.typesafe_api_key[0].id
  secret_data = var.typesafe_api_key
}

resource "google_cloud_run_v2_service" "app" {
  name     = "esg-ai-control-plane"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = var.container_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      dynamic "env" {
        for_each = var.typesafe_api_key != "" ? [1] : []
        content {
          name = "TYPESAFE_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.typesafe_api_key[0].secret_id
              version = "latest"
            }
          }
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  name     = google_cloud_run_v2_service.app.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "service_url" {
  value = google_cloud_run_v2_service.app.uri
}
