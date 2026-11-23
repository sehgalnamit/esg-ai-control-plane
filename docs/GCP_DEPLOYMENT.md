# Deploying to GCP

> **Status: reference template, not applied.** The Terraform in
> `deployment/gcp/main.tf` was written and validated for syntax by
> inspection only. The `terraform` CLI was not available in the environment
> that built this repository, so `terraform validate` / `terraform apply`
> were never run against a real GCP project. Treat this as a documented,
> deployable starting point -- review it, adapt the project ID/region/image
> to your environment, and validate it yourself before applying it.

## What it provisions

- **Cloud Run v2 service** running the `app/main.py` FastAPI demo on port
  8000, scaled 0-3 instances (scales to zero when idle).
- **Secret Manager secret** for an optional `TYPESAFE_API_KEY`, only created
  if you supply one -- the app runs fully offline without it, using
  `LocalJevStandIn`.
- A public IAM binding (`roles/run.invoker` for `allUsers`) so the demo is
  reachable without authentication; tighten this for anything beyond a demo.

## Prerequisites

1. A GCP project with billing enabled and the [gcloud CLI](https://cloud.google.com/sdk/docs/install) / [Terraform](https://developer.hashicorp.com/terraform/install) installed, authenticated (`gcloud auth application-default login`).
2. The Cloud Run, Secret Manager, and Artifact Registry APIs enabled on the project.
3. A container image pushed somewhere Cloud Run can pull from (e.g. Artifact Registry, GitHub Container Registry).

## Steps

```bash
# 1. (Optional) build and push the container image yourself, e.g.:
docker build -t <region>-docker.pkg.dev/<project>/<repo>/esg-ai-control-plane:latest .
docker push <region>-docker.pkg.dev/<project>/<repo>/esg-ai-control-plane:latest

# 2. Initialize and validate the Terraform.
cd deployment/gcp
terraform init
terraform validate

# 3. Plan and apply.
terraform plan \
  -var="project_id=<your-project-id>" \
  -var="container_image=<region>-docker.pkg.dev/<project>/<repo>/esg-ai-control-plane:latest"

terraform apply \
  -var="project_id=<your-project-id>" \
  -var="container_image=<region>-docker.pkg.dev/<project>/<repo>/esg-ai-control-plane:latest"

# 4. Get the public URL.
terraform output service_url
```

## Notes

- Leaving `typesafe_api_key` unset is the expected default: the app falls
  back to `LocalJevStandIn`, a deterministic offline stand-in for the real
  TypeSafe Jev API (see the README's Evaluator section).
- For a production deployment, also consider: Cloud Monitoring/Logging
  dashboards, VPC Service Controls if the app will later read real
  per-subsidiary data sources, and Identity-Aware Proxy instead of a public
  `allUsers` invoker binding.
