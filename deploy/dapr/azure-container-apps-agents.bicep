@description('Azure Region for resources')
param location string = resourceGroup().location

@description('Target Azure Container Apps Environment Name')
param environmentName string = 'cae-eors-dev'

@description('Azure Service Bus Namespace Name')
param serviceBusNamespaceName string = 'sb-eors-dev'

@description('Azure Cosmos DB Account Name')
param cosmosAccountName string = 'cosmos-eors-dev'

@description('ACR Login Server')
param acrLoginServer string = 'acreorsdev.azurecr.io'

@description('User Assigned Managed Identity Name')
param uamiName string = 'uami-maf-agents'

// 1. Reference User-Assigned Managed Identity
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: uamiName
}

// 2. Reference Existing Container Apps Environment
resource env 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

// 3. Dapr Pub/Sub Component (Azure Service Bus)
resource daprPubSub 'Microsoft.App/managedEnvironments/daprComponents@2024-03-01' = {
  parent: env
  name: 'agent-pubsub'
  properties: {
    componentType: 'pubsub.azure.servicebus.topics'
    version: 'v1'
    metadata: [
      {
        name: 'namespaceName'
        value: '${serviceBusNamespaceName}.servicebus.windows.net'
      }
      {
        name: 'azureClientId'
        value: uami.properties.clientId
      }
      {
        name: 'maxDeliveryCount'
        value: '5'
      }
      {
        name: 'enableDeadLettering'
        value: 'true'
      }
    ]
    scopes: [
      'agent-planner'
      'agent-erp'
      'agent-wms'
      'agent-tms'
    ]
  }
}

// 4. Dapr State Store Component (Azure Cosmos DB)
resource daprStateStore 'Microsoft.App/managedEnvironments/daprComponents@2024-03-01' = {
  parent: env
  name: 'agent-statestore'
  properties: {
    componentType: 'state.azure.cosmosdb'
    version: 'v1'
    metadata: [
      {
        name: 'url'
        value: 'https://${cosmosAccountName}.documents.azure.com:443/'
      }
      {
        name: 'database'
        value: 'AgentStateDB'
      }
      {
        name: 'collection'
        value: 'ActorMemory'
      }
      {
        name: 'partitionKey'
        value: '/id'
      }
      {
        name: 'azureClientId'
        value: uami.properties.clientId
      }
    ]
    scopes: [
      'agent-planner'
      'agent-erp'
      'agent-wms'
      'agent-tms'
    ]
  }
}

// ============================================================================
// 5. Container App: Gemini Strategic Planner Agent
// ============================================================================
resource plannerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'aca-agent-planner'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      dapr: {
        enabled: true
        appId: 'agent-planner'
        appPort: 8000
        appProtocol: 'http'
        enableApiLogging: true
      }
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
    }
    template: {
      containers: [
        {
          name: 'planner'
          image: '${acrLoginServer}/agent-planner:latest'
          env: [
            { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
            { name: 'DAPR_HTTP_PORT', value: '3500' }
            { name: 'DAPR_GRPC_PORT', value: '50001' }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 5
      }
    }
  }
}

// ============================================================================
// 6. Container App: ERP Executor Agent (Strictly bound to db-01-dev)
// ============================================================================
resource erpApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'aca-agent-erp'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      dapr: {
        enabled: true
        appId: 'agent-erp'
        appPort: 8000
        appProtocol: 'http'
      }
      ingress: {
        external: false
        targetPort: 8000
      }
    }
    template: {
      containers: [
        {
          name: 'erp-agent'
          image: '${acrLoginServer}/agent-erp:latest'
          env: [
            { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
            { name: 'MCP_ERP_URL', value: 'https://mcp-db-01.agreeablemeadow-194f1f73.southeastasia.azurecontainerapps.io' }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 5
        rules: [
          {
            name: 'service-bus-scale-rule'
            custom: {
              type: 'azure-servicebus'
              metadata: {
                topicName: 'erp-requests'
                subscriptionName: 'agent-erp-sub'
                namespace: serviceBusNamespaceName
                messageCount: '5'
              }
              auth: [
                {
                  secretRef: ''
                  triggerParameter: ''
                }
              ]
            }
          }
        ]
      }
    }
  }
}

// ============================================================================
// 7. Container App: WMS Executor Agent (Strictly bound to db-02-dev)
// ============================================================================
resource wmsApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'aca-agent-wms'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      dapr: {
        enabled: true
        appId: 'agent-wms'
        appPort: 8000
        appProtocol: 'http'
      }
      ingress: {
        external: false
        targetPort: 8000
      }
    }
    template: {
      containers: [
        {
          name: 'wms-agent'
          image: '${acrLoginServer}/agent-wms:latest'
          env: [
            { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
            { name: 'MCP_WMS_URL', value: 'https://mcp-db-02.agreeablemeadow-194f1f73.southeastasia.azurecontainerapps.io' }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 5
      }
    }
  }
}

// ============================================================================
// 8. Container App: TMS Executor Agent (Strictly bound to db-03-dev)
// ============================================================================
resource tmsApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'aca-agent-tms'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      dapr: {
        enabled: true
        appId: 'agent-tms'
        appPort: 8000
        appProtocol: 'http'
      }
      ingress: {
        external: false
        targetPort: 8000
      }
    }
    template: {
      containers: [
        {
          name: 'tms-agent'
          image: '${acrLoginServer}/agent-tms:latest'
          env: [
            { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
            { name: 'MCP_TMS_URL', value: 'https://mcp-db-03.agreeablemeadow-194f1f73.southeastasia.azurecontainerapps.io' }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 5
      }
    }
  }
}
