// Reference Bicep template for deploying the ESG AI Control Plane demo app to
// Azure Container Apps. This is a DEPLOYABLE TEMPLATE, not a live resource --
// it has not been applied (az deployment group create) against any real
// subscription as part of building this repository. See
// docs/AZURE_DEPLOYMENT.md for how to actually apply it.

@description('Name prefix for all resources.')
param namePrefix string = 'esgaicp'

@description('Azure region.')
param location string = resourceGroup().location

@description('Container image to deploy, e.g. a tag pushed to a registry you control.')
param containerImage string = 'ghcr.io/sehgalnamit/esg-ai-control-plane:latest'

@description('Optional TypeSafe Jev API key. Leave blank to use the offline LocalJevStandIn.')
@secure()
param typesafeApiKey string = ''

var logAnalyticsName = '${namePrefix}-logs'
var keyVaultName = '${namePrefix}-kv'
var environmentName = '${namePrefix}-env'
var containerAppName = '${namePrefix}-app'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    accessPolicies: []
  }
}

resource keyVaultSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(typesafeApiKey)) {
  parent: keyVault
  name: 'typesafe-api-key'
  properties: {
    value: typesafeApiKey
  }
}

resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  properties: {
    managedEnvironmentId: containerAppEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
      }
    }
    template: {
      containers: [
        {
          name: 'app'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'TYPESAFE_API_KEY'
              value: typesafeApiKey
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
