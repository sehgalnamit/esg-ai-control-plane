# Deploying to Azure

> **Status: reference template, not applied.** The Bicep template in
> `deployment/azure/main.bicep` was written and validated for syntax by
> inspection only. The `az` CLI was not available in the environment that
> built this repository, so `az bicep build` / `az deployment group create`
> were never run against a real subscription. Treat this as a documented,
> deployable starting point -- review it, adapt resource names/SKUs to your
> environment, and validate it yourself before applying it.

## What it provisions

- **Azure Container Apps** (`Microsoft.App/containerApps`) running the
  `app/main.py` FastAPI demo on port 8000, scaled 1-3 replicas.
- **Log Analytics workspace** wired to the Container Apps environment for
  application logs.
- **Key Vault** to hold an optional `TYPESAFE_API_KEY` secret (only created
  if you supply one -- the app runs fully offline without it, using
  `LocalJevStandIn`).

## Prerequisites

1. An Azure subscription and the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) installed and logged in (`az login`).
2. A container image built and pushed somewhere `az` can pull from (e.g. GitHub Container Registry, Azure Container Registry). The template defaults to `ghcr.io/sehgalnamit/esg-ai-control-plane:latest` -- replace with your own tag.
3. A resource group to deploy into.

## Steps

```bash
# 1. Create a resource group (skip if you already have one).
az group create --name esg-ai-control-plane-rg --location southeastasia

# 2. (Optional) build and push the container image yourself, e.g.:
docker build -t <your-registry>/esg-ai-control-plane:latest .
docker push <your-registry>/esg-ai-control-plane:latest

# 3. Validate the Bicep template compiles.
az bicep build --file deployment/azure/main.bicep

# 4. Deploy it.
az deployment group create \
  --resource-group esg-ai-control-plane-rg \
  --template-file deployment/azure/main.bicep \
  --parameters containerImage=<your-registry>/esg-ai-control-plane:latest \
  --parameters typesafeApiKey=<optional-real-key-or-leave-blank>

# 5. Get the public URL.
az deployment group show \
  --resource-group esg-ai-control-plane-rg \
  --name main \
  --query properties.outputs.containerAppFqdn.value
```

## Notes

- Leaving `typesafeApiKey` blank is the expected default: the app falls back
  to `LocalJevStandIn`, a deterministic offline stand-in for the real
  TypeSafe Jev API (see the README's Evaluator section).
- For a production deployment, also consider: Azure Monitor alerting on the
  Log Analytics workspace, a managed identity for the Container App to read
  the Key Vault secret directly instead of passing it as a plain
  environment variable, and Azure Front Door / API Management in front of
  the Container App if you need WAF/rate-limiting.
