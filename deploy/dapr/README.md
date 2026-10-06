# Distributed Microsoft Agent Framework (MAF) Architecture on Azure

## 1. Overview & High-Level Architecture

This architecture bridges the application-level actor model of the **Microsoft Agent Framework (MAF)** with the distributed cloud infrastructure of **Azure Container Apps**, **Dapr (Distributed Application Runtime)**, **Azure Service Bus**, and **Azure Cosmos DB**.

```
                           +-----------------------------------+
                           |            USER PROMPT            |
                           | "Has customer Acme Corp's laptop  |
                           |          order shipped?"          |
                           +-----------------+-----------------+
                                             |
                                             v
                           +-----------------------------------+
                           |        aca-agent-planner          |
                           |     (Gemini Planner Actor)        |
                           |   [Dapr Sidecar : Port 3500]      |
                           +--------+-----------------+--------+
                                    |                 |
     1. ERPOrderLookupRequest       |                 | 3. TMSDispatchLookupRequest
     ("Acme Corp", "Laptop")        |                 | (Handling Unit "HU-8841-PLT")
                                    v                 v
+-----------------------------+        +-----------------------------+
|        aca-agent-erp        |        |        aca-agent-tms        |
|      (ERP Executor Actor)   |        |      (TMS Executor Actor)   |
|  [Dapr Sidecar : Port 3500] |        |  [Dapr Sidecar : Port 3500] |
+--------------+--------------+        +--------------+--------------+
               |                                      |
               | 2. Order ID "SO-10045"               |
               v                                      |
+-----------------------------+                       |
|        aca-agent-wms        |                       |
|      (WMS Executor Actor)   |                       |
|  [Dapr Sidecar : Port 3500] |                       |
+--------------+--------------+                       |
               |                                      |
               +--------------------------------------+
                 Handling Unit "HU-8841-PLT", status_id = 5
```

---

## 2. The Four Production Pillars

### Pillar 1: The Code Layer (Dynamic Multi-Agent Swarm)
- **Agent Architecture:** Agents consist of `PlannerAgent` (strategic decomposition and schema introspection) and specialized Domain Executors (`ERP_Agent`, `WMS_Agent`, `TMS_Agent`).
- **Dynamic LLM Reasoning:** Queries are dynamically formulated via Google Gemini zero-shot over live FastMCP schemas. No static templates or question branches.
- **Strict Domain Isolation:** Domain executors are isolated to their authorized MCP server and database (`ERP_Agent` -> `mcp_db_01`, `WMS_Agent` -> `mcp_db_02`, `TMS_Agent` -> `mcp_db_03`).

### Pillar 2: The Infrastructure Layer (Azure Container Apps & Dapr)
- Each agent runs inside an isolated **Azure Container App** process.
- Azure Container Apps injects a **Dapr sidecar** alongside each container.
- Python code interacts with `http://localhost:3500`, abstracting away physical IP routing, TLS certificates, and service discovery.

### Pillar 3: The Messaging Backbone (Azure Service Bus)
- Configured via Dapr component `pubsub.azure.servicebus.topics` ([`pubsub-servicebus.yaml`](file:///Users/rahulkini/project/eors/deploy/dapr/components/pubsub-servicebus.yaml)).
- **Resilience Against Crashes & Scale-to-Zero:** If `aca-agent-wms` crashes with Out-Of-Memory (OOM) or is scaled to zero replicas, messages remain safely stored in the Azure Service Bus subscription. When a container spins up, it consumes the queued message with delivery count and message ID tracking.
- **Dead-Lettering:** Poison messages are routed to the Dead Letter Queue (DLQ) after 5 failed attempts (`maxDeliveryCount = 5`).

### Pillar 4: Durable State (Externalizing Memory to Cosmos DB)
- Configured via Dapr component `state.azure.cosmosdb` ([`statestore-cosmos.yaml`](file:///Users/rahulkini/project/eors/deploy/dapr/components/statestore-cosmos.yaml)).
- Before an agent processes an incoming message, its conversational state is fetched from Cosmos DB (`GET /v1.0/state/agent-statestore/{actor-id}`).
- After replying, updated state is checkpointed back to Cosmos DB (`POST /v1.0/state/agent-statestore`).
- Enables cross-day conversation resumption and time-travel audit debugging.

---

## 3. End-to-End Dynamic Multi-Agent Execution Flow

```sequence
User -> PlannerAgent: Natural Language Prompt (e.g., "Has Acme Corp laptop order shipped?")
PlannerAgent -> MCP_Servers: Discover live schemas dynamically over SSE
PlannerAgent -> ERP_Agent: Dispatch Phase 1: Identify Sales Order ID and commercial status
ERP_Agent -> mcp_db_01: execute_read_query_db_01(Dynamic SELECT on tbl_SalesOrders)
mcp_db_01 --> ERP_Agent: Returns Order SO-10045 records
ERP_Agent --> PlannerAgent: Phase 1 findings returned

PlannerAgent -> WMS_Agent: Dispatch Phase 2: Correlate erp_order_ref 'SO-10045' to outbound pick
WMS_Agent -> mcp_db_02: execute_read_query_db_02(Dynamic SELECT on outbound_picks)
mcp_db_02 --> WMS_Agent: Returns Pick PK-8801, Handling Unit HU-8841-PLT, status_id = 5
WMS_Agent --> PlannerAgent: Phase 2 findings returned

PlannerAgent -> TMS_Agent: Dispatch Phase 3: Correlate Handling_Unit_Ref 'HU-8841-PLT' to freight
TMS_Agent -> mcp_db_03: execute_read_query_db_03(Dynamic SELECT on Carrier_Manifests)
mcp_db_03 --> TMS_Agent: Returns Carrier Apex Freight Express, Tracking TRK-AFX-9948201
TMS_Agent --> PlannerAgent: Phase 3 findings returned

PlannerAgent -> User: Grounded final synthesis with verified cross-domain facts
```

---

## 4. Local Verification vs Production Deployment

| Environment | Runtime Engine | Message Transport | State Persistence | Execution Command |
| :--- | :--- | :--- | :--- | :--- |
| **Local Sandbox / CI** | `SingleThreadedAgentRuntime` | In-Memory MAF Event Bus | In-Memory Object Store | `.venv/bin/python agents/run_maf_bus.py` |
| **Production Azure** | Distributed Container Apps | Azure Service Bus via Dapr Sidecar | Azure Cosmos DB / Redis | `az deployment group create -f deploy/dapr/azure-container-apps-agents.bicep` |
