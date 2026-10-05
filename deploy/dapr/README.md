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

### Pillar 1: The Code Layer (MAF Event-Driven Actors)
- **Subclassing:** Agents subclass `autogen_core.RoutedAgent` (`GeminiPlannerActor`, `ERPActor`, `WMSActor`, `TMSActor`).
- **Event-Driven Handlers:** Functions are explicitly decorated with `@message_handler`. No synchronous loops or coupled RPCs.
- **Routing via `AgentId`:** Agents communicate strictly by targeting typed `AgentId` identifiers (e.g. `AgentId("ERP_Agent", "default")`, `AgentId("WMS_Agent", "default")`). The underlying runtime manages dispatch and serialization.

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

## 3. End-to-End A2A Message Passing Flow

```sequence
User -> GeminiPlanner: UserQueryMessage("Has Acme Corp laptop order shipped?")
GeminiPlanner -> DaprPubSub: Publish ERPOrderLookupRequest to topic 'erp-requests'
DaprPubSub -> ERPActor: Deliver via Service Bus to aca-agent-erp
ERPActor -> mcp_db_01: execute_read_query_db_01(SELECT from tbl_SalesOrders)
mcp_db_01 --> ERPActor: Order SO-10045, PO: PO-ACM-2026-9921
ERPActor --> GeminiPlanner: ERPOrderLookupResponse(Order SO-10045)

GeminiPlanner -> DaprPubSub: Publish WMSExecutionLookupRequest to topic 'wms-requests' ("I have order SO-10045...")
DaprPubSub -> WMSActor: Deliver via Service Bus to aca-agent-wms
WMSActor -> mcp_db_02: execute_read_query_db_02(SELECT from outbound_picks WHERE erp_order_ref = 'SO-10045')
mcp_db_02 --> WMSActor: Pick PK-8801, HU-8841-PLT, status_id = 5 (Loaded)
WMSActor --> GeminiPlanner: WMSExecutionLookupResponse(HU-8841-PLT, status_id = 5)

GeminiPlanner -> DaprPubSub: Publish TMSDispatchLookupRequest to topic 'tms-requests' (HU-8841-PLT)
DaprPubSub -> TMSActor: Deliver via Service Bus to aca-agent-tms
TMSActor -> mcp_db_03: execute_read_query_db_03(SELECT from Carrier_Manifests WHERE Handling_Unit_Ref = 'HU-8841-PLT')
mcp_db_03 --> TMSActor: Carrier Apex Freight Express, Tracking TRK-AFX-9948201, Status IN_TRANSIT
TMSActor --> GeminiPlanner: TMSDispatchLookupResponse(TRK-AFX-9948201, IN_TRANSIT)

GeminiPlanner -> User: Synthesized response with multi-domain proof
```

---

## 4. Local Verification vs Production Deployment

| Environment | Runtime Engine | Message Transport | State Persistence | Execution Command |
| :--- | :--- | :--- | :--- | :--- |
| **Local Sandbox / CI** | `SingleThreadedAgentRuntime` | In-Memory MAF Event Bus | In-Memory Object Store | `.venv/bin/python agents/run_maf_bus.py` |
| **Production Azure** | Distributed Container Apps | Azure Service Bus via Dapr Sidecar | Azure Cosmos DB / Redis | `az deployment group create -f deploy/dapr/azure-container-apps-agents.bicep` |
