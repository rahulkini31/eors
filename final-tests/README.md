# Final Multi-Agent Evaluation & Verification Test Suite

This directory (`final-tests/`) contains the complete benchmark evaluation suite designed to verify and grade multi-agent AI systems, swarms, and NL-to-SQL agents against the three decoupled Azure SQL databases:
- **`db-01-dev`** (ERP: Commercial & financial order management)
- **`db-02-dev`** (WMS: Physical warehouse execution & bin tracking)
- **`db-03-dev`** (TMS: Logistics routing, freight loads, and carrier tracking)

---

## Suite Directory Structure

| File | Purpose |
| :--- | :--- |
| **[`test_suite.json`](test_suite.json)** | Machine-readable benchmark dataset containing all 16 test cases, natural language prompts, step-by-step SQL queries, expected results, and grading criteria. |
| **[`qa_pairs.md`](qa_pairs.md)** | Comprehensive human-readable documentation with natural language questions, rationale, exact SQL queries, and answers. |
| **[`eval_runner.py`](eval_runner.py)** | Automated evaluation harness that executes every ground-truth SQL query against the live Azure SQL databases and verifies 100% pass rate. |

---

## Benchmark Categories & Test Cases

| Test Case ID | Category | Complexity | Natural Language Focus | Target DB |
| :--- | :--- | :--- | :--- | :--- |
| **TC-ERP-01** | Single-Domain ERP | Basic | Order value and status for Acme Corp PO | `db-01-dev` |
| **TC-ERP-02** | Single-Domain ERP | Basic | Enterprise laptop inventory on hand & financial asset valuation | `db-01-dev` |
| **TC-ERP-03** | Single-Domain ERP | Medium | Tier 1 Enterprise customers and credit limits | `db-01-dev` |
| **TC-WMS-01** | Single-Domain WMS | Basic | Active stock bin location, zone, and lot number | `db-02-dev` |
| **TC-WMS-02** | Single-Domain WMS | Medium | Physical status code, handling unit, and dock door for pick PK-8801 | `db-02-dev` |
| **TC-WMS-03** | Single-Domain WMS | Basic | Pallet handling units and tare weights at DOCK-04 | `db-02-dev` |
| **TC-TMS-01** | Single-Domain TMS | Medium | Carrier details, trailer number, and weight for freight load LD-2026-9041 | `db-03-dev` |
| **TC-TMS-02** | Single-Domain TMS | Basic | Carrier, tracking number, and status for BOL-2026-10045 | `db-03-dev` |
| **TC-CROSS-01** | Two-Domain Cross-DB | Advanced | Acme Corp laptop pick task ID, picker badge, and handling unit | ERP -> WMS |
| **TC-CROSS-02** | Two-Domain Cross-DB | Advanced | Warehouse physical status of Acme Corp ergonomic chairs order | ERP -> WMS |
| **TC-CROSS-03** | Two-Domain Cross-DB | Advanced | Freight trailer and departure status for handling unit HU-8841-PLT | WMS -> TMS |
| **TC-CORE-01** | Three-Domain Full Synthesis | Expert | **The Core Agentic Challenge**: Has customer Acme Corp's laptop order shipped, and what is the tracking number? | ERP -> WMS -> TMS |
| **TC-CORE-02** | Three-Domain Full Synthesis | Expert | End-to-end audit trail (order -> staging -> tracking) for PO-ACM-2026-9921 | ERP -> WMS -> TMS |
| **TC-DISTRACTOR-01** | Distractor & Adversarial | Hard | Cancelled order trap: Did Acme Corp SO-10012 ever get loaded onto a truck? | ERP -> WMS |
| **TC-DISTRACTOR-02** | Distractor & Adversarial | Hard | Customer disambiguation trap: Has Globex Corp's laptop order shipped? | ERP -> WMS -> TMS |
| **TC-DISTRACTOR-03** | Distractor & Adversarial | Hard | Staged vs Dispatched trap: Is PO-ACM-2026-9930 on a delivery truck? | ERP -> WMS -> TMS |

---

## How to Run the Verification Suite

Run the evaluation runner directly from your terminal using Python:

```bash
# Run all 16 benchmark test cases against the live Azure SQL databases
python final-tests/eval_runner.py
```

### Verification Output:
```
================================================================================
  RUNNING BENCHMARK EVALUATION SUITE: Azure SQL Cross-Database Multi-Agent Evaluation Benchmark
  Target Server: eosr-db-server.database.windows.net (16 Test Cases)
================================================================================

[1/16] Testing TC-ERP-01: What is the total order value and current order status for Acme C...
       STATUS: PASSED (1 query step(s))
...
[12/16] Testing TC-CORE-01: Has customer Acme Corp's laptop order shipped, and if so, what is...
       STATUS: PASSED (3 query step(s))
...
[16/16] Testing TC-DISTRACTOR-03: Is Acme Corp's branch office expedited order (PO-ACM-2026-9930) c...
       STATUS: PASSED (3 query step(s))

================================================================================
  SUMMARY: 16/16 PASSED in 48.32s (Success Rate: 100.0%)
================================================================================
```

---

## Evaluating Your Multi-Agent System

When your multi-agent swarm or orchestrator runs:
1. Provide the natural language **`question`** from `test_suite.json` to your agent.
2. The agent should route calls to the appropriate MCP servers (`mcp_db_01`, `mcp_db_02`, `mcp_db_03`).
3. Grade the agent's SQL queries against the ground truth **`sql_query`** / **`steps`** and assert that its final response matches the **`expected_result`**.
