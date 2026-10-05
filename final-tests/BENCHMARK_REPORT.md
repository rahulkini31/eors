# Azure SQL Cross-Database Multi-Agent Benchmark Evaluation Report

**Execution Timestamp**: 2026-10-05 11:39:51Z  
**Target System**: Enterprise Order Resolution System (EORS) Multi-Agent Swarm  
**Databases**: `db-01-dev` (ERP), `db-02-dev` (WMS), `db-03-dev` (TMS) on `eosr-db-server.database.windows.net`  
**MCP Architecture**: Live FastMCP Servers on Azure Container Apps over Server-Sent Events (SSE)  
**Isolation Mode**: Strict Prompt Isolation (Raw NL Question ONLY; zero metadata leakage)  

---

## 1. Executive Summary & Core Metrics

| Metric | Result |
| :--- | :--- |
| **Total Test Cases** | 16 |
| **Passed Test Cases** | 16 |
| **Failed Test Cases** | 0 |
| **Overall Accuracy (%)** | **100.0%** |
| **Total Evaluation Latency** | 133.34s |
| **Average Test Latency** | 8.33s |

---

## 2. Category Performance Breakdown

| Category | Total | Passed | Failed | Accuracy (%) | Avg Latency (s) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Single-Domain ERP** | 3 | 3 | 0 | **100.0%** | 8.68s |
| **Single-Domain WMS** | 3 | 3 | 0 | **100.0%** | 8.17s |
| **Single-Domain TMS** | 2 | 2 | 0 | **100.0%** | 8.25s |
| **Two-Domain Cross-DB (ERP -> WMS)** | 2 | 2 | 0 | **100.0%** | 8.14s |
| **Two-Domain Cross-DB (WMS -> TMS)** | 1 | 1 | 0 | **100.0%** | 7.96s |
| **Three-Domain Full Synthesis (ERP -> WMS -> TMS)** | 2 | 2 | 0 | **100.0%** | 8.47s |
| **Distractor & Adversarial** | 3 | 3 | 0 | **100.0%** | 8.36s |

---

## 3. Detailed Per-Test Audit & Scorecard Table

| Test ID | Category | Question | Expected Values | Agent Returned Values | Match Verdict | Latency (s) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-ERP-01** | Single-Domain ERP | What is the total order value and current order status for Acme Corp's purchase order PO-ACM-2026-9921? | key_fields: ['Order_ID', 'OrderStatus', 'Total_Amount'], expected_order_id: SO-10045, expected_status: Completed | Order_ID: SO-10045, OrderStatus: Completed, Total_Amount: 20230.00 | ✅ PASS | 9.8s |
| **TC-ERP-02** | Single-Domain ERP | How many enterprise 15-inch laptops are currently on hand in inventory, and what is their total financial asset valuation? | key_fields: ['Qty_On_Hand', 'Total_Asset_Valuation_USD'], expected_qty: 145, expected_valuation: 174000.00 | Qty_On_Hand: 145, Total_Asset_Valuation_USD: 174000.00 | ✅ PASS | 8.25s |
| **TC-ERP-03** | Single-Domain ERP | List all customers who hold Enterprise Tier 1 accounts along with their credit limits, ordered from highest to lowest credit limit. | row_count: 3, top_customer: Globex Corporation | row_count: 3, top_customer: Globex Corporation, ranking_order: Globex > Cyberdyne > Acme | ✅ PASS | 8.0s |
| **TC-WMS-01** | Single-Domain WMS | Which bin location, warehouse zone, and quality lot number contain active stock for Enterprise Laptops (SKU-LAPTOP-15-ENT)? | expected_bin: Z1-A04-S02-B01, expected_lot: LOT-2026Q1-TECH | bin_code: Z1-A04-S02-B01, lot_number: LOT-2026Q1-TECH | ✅ PASS | 7.94s |
| **TC-WMS-02** | Single-Domain WMS | What is the physical execution status code, quantity picked, handling unit, and dock door assignment for pick task PK-8801? | status_code: 5, handling_unit: HU-8841-PLT, dock_door: DOCK-04 | status_id: 5, handling_unit: HU-8841-PLT, dock_door: DOCK-04 | ✅ PASS | 7.93s |
| **TC-WMS-03** | Single-Domain WMS | List all pallet handling units currently positioned at DOCK-04 and their tare weights. | row_count: 3, includes_hu: HU-8841-PLT | row_count: 3, includes_hu: HU-8841-PLT | ✅ PASS | 8.64s |
| **TC-TMS-01** | Single-Domain TMS | What carrier name, trailer number, and total load weight are assigned to freight load LD-2026-9041? | carrier_name: Apex Freight Express, trailer_number: TRL-8821-X, load_status: DISPATCHED | carrier_name: Apex Freight Express, trailer_number: TRL-8821-X, load_status: DISPATCHED | ✅ PASS | 8.13s |
| **TC-TMS-02** | Single-Domain TMS | What is the carrier, tracking number, and current shipment status for Bill of Lading BOL-2026-10045? | tracking_number: TRK-AFX-9948201, carrier_name: Apex Freight Express, shipment_status: IN_TRANSIT | tracking_number: TRK-AFX-9948201, carrier_name: Apex Freight Express, shipment_status: IN_TRANSIT | ✅ PASS | 8.37s |
| **TC-CROSS-01** | Two-Domain Cross-DB (ERP -> WMS) | For customer Acme Corp's laptop order, what is the physical pick task ID, who picked it, and which handling unit was it packed into? | pick_id: PK-8801, handling_unit_id: HU-8841-PLT, status_id: 5 | pick_id: PK-8801, handling_unit_id: HU-8841-PLT, status_id: 5 | ✅ PASS | 8.04s |
| **TC-CROSS-02** | Two-Domain Cross-DB (ERP -> WMS) | What is the physical status of Acme Corp's ergonomic chairs order in the warehouse? | status_id: 2, is_loaded: False | status_id: 2, is_loaded: False | ✅ PASS | 8.25s |
| **TC-CROSS-03** | Two-Domain Cross-DB (WMS -> TMS) | Which carrier freight load and trailer is handling unit HU-8841-PLT loaded onto, and what is the trailer departure status? | load_id: LD-2026-9041, trailer_number: TRL-8821-X, load_status: DISPATCHED | load_id: LD-2026-9041, trailer_number: TRL-8821-X, load_status: DISPATCHED | ✅ PASS | 7.96s |
| **TC-CORE-01** | Three-Domain Full Synthesis (ERP -> WMS -> TMS) | Has customer Acme Corp's laptop order shipped, and if so, what is the carrier and tracking number? | shipped_boolean: True, carrier: Apex Freight Express, tracking_number: TRK-AFX-9948201, status: IN_TRANSIT | shipped: True, carrier: Apex Freight Express, tracking_number: TRK-AFX-9948201, status: IN_TRANSIT | ✅ PASS | 8.65s |
| **TC-CORE-02** | Three-Domain Full Synthesis (ERP -> WMS -> TMS) | What is the complete end-to-end audit trail (from financial order, to warehouse staging, to freight tracking) for customer purchase order PO-ACM-2026-9921? | all_stages_resolved: True, lineage: SO-10045 -> HU-8841-PLT -> TRK-AFX-9948201 | all_stages_resolved: True, lineage: SO-10045 -> HU-8841-PLT -> TRK-AFX-9948201 | ✅ PASS | 8.29s |
| **TC-DISTRACTOR-01** | Distractor & Adversarial | Did Acme Corp order SO-10012 ever get picked or loaded onto a delivery truck? | was_picked: False, is_cancelled: True | was_picked: False, is_cancelled: True | ✅ PASS | 8.23s |
| **TC-DISTRACTOR-02** | Distractor & Adversarial | Has Globex Corporation's laptop order shipped, and which carrier handled it? | carrier_name: Swift Global Logistics, tracking_number: TRK-SW-7719283, must_not_be: Apex Freight Express | carrier_name: Swift Global Logistics, tracking_number: TRK-SW-7719283, must_not_be_apex: Passed | ✅ PASS | 8.29s |
| **TC-DISTRACTOR-03** | Distractor & Adversarial | Is Acme Corp's branch office expedited order (PO-ACM-2026-9930) currently on a delivery truck? | on_delivery_truck: False, wms_status_id: 4, tms_status: PENDING_PICKUP | on_delivery_truck: False, wms_status_id: 4, tms_status: PENDING_PICKUP | ✅ PASS | 8.56s |

---

## 4. Multi-Hop Trace Analysis & Domain Isolation Verification

### 4.1 Strict Prompt Isolation Verification
- All 16 evaluation questions were ingested as raw natural language strings directly from `final-tests/test_suite.json`.
- Zero metadata leakage occurred: target database names, schema table names, SQL templates, and expected answers were completely excluded from the prompt input.
- Each test case instantiated a clean, decoupled `MultiAgentOrchestrator` session to guarantee zero conversational context leakage.

### 4.2 Dynamic Domain Routing & Live Execution
- The Strategic Planner Agent dynamically introspected the live MCP servers over SSE to discover table and column schemas without hardcoding.
- The swarm dynamically classified requests into Single-Domain ERP, Single-Domain WMS, Single-Domain TMS, 2-Domain Cross-DB, and 3-Domain Full Synthesis execution phases.
- Specialized Domain Executors (`ERP_Agent`, `WMS_Agent`, `TMS_Agent`) formulated read-only SQL queries and executed them strictly against their authorized MCP endpoints (`execute_read_query_db_01`, `execute_read_query_db_02`, `execute_read_query_db_03`).

### 4.3 Adversarial & Distractor Parity Grading
- **TC-DISTRACTOR-01 (Cancelled Order)**: Successfully verified that cancelled order SO-10012 was refunded in ERP and never picked in WMS (`was_picked = false`).
- **TC-DISTRACTOR-02 (Customer Disambiguation)**: Correctly resolved Globex Corporation's order to Swift Global Logistics (`TRK-SW-7719283`), avoiding the Acme Corp carrier (Apex Freight Express).
- **TC-DISTRACTOR-03 (Staged vs Dispatched)**: Correctly identified that PO-ACM-2026-9930 is staged at Dock 7 (`status_id = 4`) and pending carrier pickup, refusing to hallucinate that it is on a delivery truck (`on_delivery_truck = false`).

---
*Report generated automatically by `final-tests/benchmark_eval_runner.py`.*