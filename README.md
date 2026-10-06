# Enterprise Order Resolution System (EORS)
### Distributed Multi-Agent Architecture for Cross-Domain Enterprise Data Synthesis

---

## 1. Executive Overview

The **Enterprise Order Resolution System (EORS)** is a distributed, multi-agent AI system engineered to resolve complex, cross-domain business inquiries across decoupled enterprise data tiers. 

In modern enterprises, answering a fundamental operational question—such as:
> *"Has customer Acme Corp's expedited laptop order shipped, and what is its tracking number?"*

cannot be achieved by querying a single database or running a federated SQL join. Critical business truth is intentionally fragmented across isolated software silos, each maintained by different organizational units, distinct schema conventions, conflicting terminology, and independent security boundaries:
1. **Commercial ERP (Enterprise Resource Planning)**: Owns sales contracts, payment terms, item catalog valuation, and commercial order lifecycle.
2. **Physical Warehouse WMS (Warehouse Management System)**: Owns physical bin locations, picker badges, inventory lots, and pallet handling units.
3. **Freight Logistics TMS (Transportation Management System)**: Owns bills of lading, freight loads, trailer assignments, carrier manifests, and dispatch statuses.

EORS bridges these autonomous data silos using **genuine LLM multi-agent reasoning**, the **Model Context Protocol (MCP)**, **OpenTelemetry distributed tracing**, and **least-privilege security guardrails** without cross-database foreign keys or hardcoded query shortcuts.

---

## 2. System Architecture

```
                                  ┌────────────────────────────────┐
                                  │       Client Browser UI        │
                                  │   (Real-Time SSE Event Stream) │
                                  └───────────────┬────────────────┘
                                                  │ HTTP / SSE
                                                  ▼
                                  ┌────────────────────────────────┐
                                  │      FastAPI Swarm Gateway     │
                                  │    (aca-maf-swarm on Azure)    │
                                  └───────────────┬────────────────┘
                                                  │
                ┌─────────────────────────────────┴─────────────────────────────────┐
                │                                                                   │
                ▼                                                                   ▼
┌──────────────────────────────┐                                    ┌──────────────────────────────┐
│       Planning Agent         │                                    │       Audit Evaluator        │
│ • Zero direct database tools │                                    │ • In-memory trace audit      │
│ • Dynamic schema discovery   │                                    │ • Domain isolation checks    │
│ • Multi-hop execution plans  │                                    │ • Fact grounding verification│
└───────────────┬──────────────┘                                    └──────────────▲───────────────┘
                │                                                                   │
                │ Dispatches Sub-Tasks                                              │ Reads Spans & Rows
                ▼                                                                   │
┌────────────────────────────────────────────────────────────────────────┐          │
│                      Domain Executor Sub-Agents                        │          │
│                                                                        │          │
│   ┌─────────────────────┐ ┌─────────────────────┐ ┌────────────────┐   │          │
│   │   Executor (ERP)    │ │   Executor (WMS)    │ │ Executor (TMS) │   │          │
│   │ • Generates SQL     │ │ • Generates SQL     │ │• Generates SQL │   │          │
│   │ • Scoped: db-01-dev │ │ • Scoped: db-02-dev │ │• Scoped: db-03 │   │          │
│   └──────────┬──────────┘ └──────────┬──────────┘ └────────┬───────┘   │          │
└──────────────┼───────────────────────┼─────────────────────┼───────────┘          │
               │ SSE                   │ SSE                 │ SSE                  │
               ▼                       ▼                     ▼                      │
┌──────────────────────────┐ ┌──────────────────────────┐ ┌──────────────────────────┐   │
│   mcp-db-01 (FastMCP)    │ │   mcp-db-02 (FastMCP)    │ │   mcp-db-03 (FastMCP)    │   │
│ • UAMI: uami-mcp-db01    │ │ • UAMI: uami-mcp-db02    │ │ • UAMI: uami-mcp-db03    │   │
│ • Read-Only Validator    │ │ • Read-Only Validator    │ │ • Read-Only Validator    │   │
└──────────────┬───────────┘ └──────────┬───────────┘ └──────────┬───────────┘   │
               │ TLS (pytds)           │ TLS (pytds)         │ TLS (pytds)          │
               ▼                       ▼                     ▼                      │
┌──────────────────────────┐ ┌──────────────────────────┐ ┌──────────────────────────┐   │
│   db-01-dev (ERP SQL)    │ │   db-02-dev (WMS SQL)    │ │   db-03-dev (TMS SQL)    │   │
│ • tbl_SalesOrders        │ │ • outbound_picks         │ │ • Carrier_Manifests      │   │
│ • tbl_Customers          │ │ • handling_units         │ │ • Bill_Of_Lading         │   │
│ • tbl_OrderLineItems     │ │ • dock_doors             │ │ • Freight_Loads          │   │
└──────────────────────────┘ └──────────────────────────┘ └──────────────────────────┘   │
                                                                                            │
════════════════════════════════════════════════════════════════════════════════════════════╝
                             OpenTelemetry Distributed Tracing
                     (App Insights • W3C Trace Context • Azure Cosmos DB)
```

---

## 3. Data Tier: Intentionally Conflicting Enterprise Schemas

The data layer consists of three autonomous Azure SQL databases hosted on `eosr-db-server.database.windows.net`. Cross-database foreign keys are prohibited; correlation is achieved strictly via business keys propagated dynamically by agents.

### Commercial ERP (`db-01-dev`)
* **Design Philosophy**: Legacy order-of-record and financial accounting.
* **Naming Conventions**: Strict `tbl_*` prefix, PascalCase, Hungarian-style columns (`Cust_ID`, `Item_SKU`, `Qty_On_Hand`).
* **Status Representation**: Free-form text strings (`OrderStatus = 'Processing'`, `'Completed'`, `'Cancelled'`).
* **Metrics Tracked**: Financial balance sheet figures, credit limits, list prices, taxes, and customer purchase orders (`PO_Number`).
* **Domain Blindspots**: Has zero awareness of warehouse bins, physical pallet tags, or carrier tracking numbers.

### Physical Warehouse WMS (`db-02-dev`)
* **Design Philosophy**: High-velocity physical fulfillment and spatial inventory control.
* **Naming Conventions**: Modern lower snake_case (`outbound_picks`, `handling_units`, `dock_doors`).
* **Status Representation**: Discrete integer lifecycle codes:
  * `1`: Allocated
  * `2`: Picked (on cart)
  * `4`: Staged at Dock Door
  * `5`: Loaded into Outbound Transport
  * `9`: Cancelled
* **Metrics Tracked**: Spatial bin coordinates (`Z1-A04-S02-B01`), handling unit identifiers (`HU-8841-PLT`), LPN barcodes, tare weights, and dock door staging bays.
* **Domain Blindspots**: Has zero awareness of customer billing, product pricing, or freight waybills.

### Freight Logistics TMS (`db-03-dev`)
* **Design Philosophy**: Over-the-road freight routing and multi-carrier dispatch.
* **Naming Conventions**: Transport logistics naming (`Carrier_Manifests`, `Bill_Of_Lading`, `Freight_Loads`).
* **Status Representation**: Uppercase transport status strings (`PENDING_PICKUP`, `IN_TRANSIT`, `DELIVERED`).
* **Metrics Tracked**: Waybill numbers (`WB-884102`), carrier tracking numbers (`TRK-AFX-9948201`), trailer assignments (`TRL-8821-X`), stop sequences, gross weight in lbs, and departure timestamps.
* **Domain Blindspots**: Has zero awareness of internal pick task IDs, warehouse bins, or customer payment terms.

---

## 4. Engineering Pillars & Implementation Details

### Pillar 1: Model Context Protocol (MCP) as the Security Perimeter
Direct database connectivity from the LLM or agent runtime is strictly disabled. Instead, each database is fronted by an independent Model Context Protocol (FastMCP) microservice deployed to Azure Container Apps over Server-Sent Events (SSE):
* `mcp-db-01` -> Bound exclusively to `db-01-dev` (ERP)
* `mcp-db-02` -> Bound exclusively to `db-02-dev` (WMS)
* `mcp-db-03` -> Bound exclusively to `db-03-dev` (TMS)

#### Security & Authentication
* **Zero Credential Storage**: Database connection strings and SQL passwords are completely absent from code, configuration, and environment variables.
* **Microsoft Entra ID Authentication**: Each MCP microservice uses a dedicated User-Assigned Managed Identity (UAMI):
  * `uami-mcp-db01` (`Client ID: 2b7c9e79...`)
  * `uami-mcp-db02` (`Client ID: 1559fdfb...`)
  * `uami-mcp-db03` (`Client ID: 2ce6f5f0...`)
* **Read-Only AST AST Validator**: Every SQL statement submitted to an MCP server passes through an AST-based validator ([`mcp_servers/common/validator.py`](file:///Users/rahulkini/project/eors/mcp_servers/common/validator.py)) that strictly allows `SELECT` and `WITH ... SELECT` queries while rejecting mutating keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `EXEC`, `MERGE`, multi-statement semicolons).

#### Minimal Tool Surface
To prevent hallucinations and eliminate dead code, each MCP server exposes exactly two tools:
1. `get_schema_db_XX(table_name?: str)`: Dynamically inspects column definitions and data types from `INFORMATION_SCHEMA.COLUMNS`.
2. `execute_read_query_db_XX(query: str, max_rows: int = 100)`: Executes validated read-only SQL queries against the bound database.

---

### Pillar 2: Strategic Orchestration & Agent Swarm

The system adopts Microsoft Agent Framework (MAF) architectural patterns, orchestrating tasks across specialized agents rather than relying on a single monolithic prompt:

```
[User Query]
     │
     ▼
[Phase 0: Dynamic Introspection]
     │  Planning Agent connects via SSE to mcp-db-01, 02, 03.
     │  Discovers table names and column definitions in real time.
     ▼
[Phase 1: Strategic Planning]
     │  Planning Agent (Google Gemini) reasons over discovered schemas.
     │  Constructs ordered multi-hop execution plan with cross-domain key linkages.
     ▼
[Phase 2: Domain Execution Loop]
     │  Phase 2a: Executor (ERP) generates SQL -> calls execute_read_query_db_01 -> yields Order_ID.
     │  Phase 2b: Executor (WMS) uses Order_ID -> calls execute_read_query_db_02 -> yields Handling_Unit_Ref.
     │  Phase 2c: Executor (TMS) uses Handling_Unit_Ref -> calls execute_read_query_db_03 -> yields Tracking_Number.
     ▼
[Phase 3: Evidence Synthesis]
     │  Orchestrator synthesizes raw database records into pure natural language reasoning.
     ▼
[Phase 4: Trajectory Audit & Memory Checkpoint]
        SwarmTrajectoryEvaluator scores execution graph -> Saves to Azure Cosmos DB.
```

#### Domain Isolation Guardrails
Each domain executor agent ([`agents/executors.py`](file:///Users/rahulkini/project/eors/agents/executors.py)) is equipped with code-level isolation guardrails:
* An agent assigned to ERP cannot physically call tools belonging to WMS or TMS.
* Calling an unauthorized tool raises a fatal `PermissionError`:
  ```python
  if tool_name not in self._get_allowed_tool_names():
      raise PermissionError(f"Security Guardrail Violation: Agent [{self.domain}] cannot call '{tool_name}'")
  ```

---

### Pillar 3: Distributed Observability & OpenTelemetry

Every cognitive hop and network request is instrumented with OpenTelemetry distributed tracing:
* **W3C Distributed Trace Context**: Inbound HTTP requests extract `traceparent` headers, stitching ACA ingress, orchestrator planning, executor tool executions, and MCP queries to a shared `root_trace_id`.
* **Telemetry Exporters**: Distributed spans are dual-exported:
  1. Azure Monitor OpenTelemetry Exporter (`azure-monitor-opentelemetry-exporter`) -> Streamed to Azure Application Insights (`appi-eors-dev`) and Log Analytics.
  2. In-Memory Trajectory Recorder (`InMemorySpanExporter`) -> Retained locally for real-time trajectory auditing.
* **Semantic Span Attributes**: Every span records `agent.id`, `db.target`, `mcp.server`, `sql.query`, `execution.phase`, and duration metrics.

---

### Pillar 4: Autonomous Trajectory Audit Evaluator

Before any resolution is served to the user or committed to durable state, the [`SwarmTrajectoryEvaluator`](file:///Users/rahulkini/project/eors/agents/evaluations.py) audits the execution trajectory.

The Auditor operates with **Zero Database Privileges**—it does not connect to Azure SQL, avoiding extra database load. Instead, it audits the OpenTelemetry trace graph and in-flight tool payloads across four weighted dimensions:

$$\text{Overall Score} = (0.30 \times \text{Completeness}) + (0.30 \times \text{Domain Isolation}) + (0.20 \times \text{Fact Grounding}) + (0.20 \times \text{Context Propagation})$$

1. **Domain Isolation (30%)**: Verifies that `agent.id` spans strictly match their designated `db.target` and `mcp.server`. Any cross-domain leakage results in an immediate `0.0` score.
2. **Trajectory Completeness (30%)**: Verifies that all phases identified by the Planning Agent executed successfully without dropped hops.
3. **Fact Grounding & Anti-Hallucination (20%)**: Extracts raw entity identifiers returned by SQL results (`Order_ID`, `PO_Number`, `handling_unit_id`, `Tracking_Number`, `OrderStatus`, `Shipment_Status`) and asserts their presence in the final synthesized text.
4. **Context Propagation (20%)**: Verifies that 100% of cognitive spans share the active `root_trace_id`.

**Verdict Threshold**: A trajectory must achieve $\ge 90\%$ (0.90) compliance to receive a `PASSED` audit verdict.

---

### Pillar 5: Real-Time Event Streaming & Cognitive UX

EORS streams agent reasoning and tool executions in real time over Server-Sent Events (SSE):
* **No Database Name Leaks**: Internal infrastructure identifiers (such as `db-01-dev`) are sanitized to user-friendly architectural names: *Commercial ERP System*, *Warehouse Management System*, and *Transportation Logistics System*.
* **Explainable Reasoning Tokens**: The agent stream emits the exact tool called, the rationale for the call, and what the agent learned in plain natural language.
* **Pure Natural Language Synthesis**: The final response presents conversational chain-of-thought tokens that directly answer the query without robotic markdown headers or raw JSON dumps.

---

### Pillar 6: Durable Long-Term Memory (Cosmos DB via Dapr)

Cross-session context, resolved order histories, and audit scorecards are externalized to **Azure Cosmos DB** via the Dapr State Store API ([`agents/memory.py`](file:///Users/rahulkini/project/eors/agents/memory.py) and [`agents/dapr_bridge.py`](file:///Users/rahulkini/project/eors/agents/dapr_bridge.py)):
* When a query resolves customer facts (e.g. Acme Corp's corporate shipping dock, preferred carrier, or past order lineages), the memory manager checkpoints the session state.
* Future sessions can recall historical order lineages without re-scanning historical tables from scratch.

---

## 5. Adversarial Distractor & Trap Architecture

To verify that the AI swarm performs genuine reasoning rather than simplistic keyword guessing, the dataset and test suite include six adversarial distractor scenarios:

| Distractor ID | Scenario Description | Expected AI System Behavior |
| :--- | :--- | :--- |
| **DIST-1: Wrong Product** | Acme Corp ordered Office Chairs (`SO-10046`). WMS status is `2` (Picked on cart); no handling unit or manifest exists. | Identifies order as in picking; explicitly rejects shipping assertion. |
| **DIST-2: Wrong Customer** | Globex Corporation ordered Laptops (`SO-10047`), which shipped under Waybill `WB-884103`. | Accurately identifies shipment belongs to Globex Corp, NOT Acme Corp. |
| **DIST-3: Cancelled Order** | Historical Acme Corp laptop order (`SO-10012`). ERP status is `Cancelled`; WMS status is `9`. | Detects order cancellation; rejects shipping assertion without hallucinating. |
| **DIST-4: Staged vs. Dispatched Trap** | Acme Corp expedited laptop order (`SO-10048`, `PO-ACM-2026-9930`). WMS status is `4` (Staged at Dock 7); TMS status is `PENDING_PICKUP`; `Dispatched_At = NULL`. | Confirms pallet is picked and staged at dock door, but explicitly states it is **not on a delivery truck** and not yet dispatched. |
| **DIST-5: Allocated Only** | Umbrella Corp laptop order (`SO-10049`). WMS status is `1` (Allocated); no pick completed. | Reports order allocated in inventory but unpicked. |
| **DIST-6: Background Freight Traffic** | Initech LLC monitor order (`SO-10050`) sharing carrier trailer `TRL-8821-X`. | Isolates trailer sharing without conflating consignees or line items. |

---

## 6. Technology Stack Summary

* **AI & Agent Orchestration**: Google Gemini 2.5/3.8 Flash, Microsoft Agent Framework Architecture, FastMCP (Model Context Protocol).
* **Enterprise Data Tier**: Azure SQL Serverless (`GP_S_Gen5`), Python TDS (`pytds`), Microsoft Entra ID Managed Identity.
* **Hosting & Runtime**: Azure Container Apps (ACA), Azure Container Registry (ACR), Docker (Python 3.11-slim).
* **Observability & APM**: OpenTelemetry SDK/API, Azure Application Insights, Azure Log Analytics.
* **Durable State & Memory**: Azure Cosmos DB, Dapr Distributed Runtime (State Management).
* **Web Gateway & Streaming**: FastAPI, Uvicorn, Server-Sent Events (SSE), Tailwind CSS, Vanilla JS.
