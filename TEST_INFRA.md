# Test Infrastructure Specification (TEST_INFRA.md)

**Project**: Azure SQL Multi-Agent Cross-Database Challenge (EORS)  
**Author**: E2E Test Writer 1 (`e2e_test_writer_1`)  
**Suite Location**: `/Users/rahulkini/project/eors/e2e_tests/`  
**Target Server**: `eosr-db-server.database.windows.net` (`db-01-dev`, `db-02-dev`, `db-03-dev`)  
**Python Runtime**: `/Users/rahulkini/project/eors/.venv/bin/python3`  

---

## 1. Test Philosophy & Design Principles

The E2E test suite validates the autonomous multi-agent cross-database challenge using a strict **opaque-box, requirement-driven, multi-tiered** testing methodology.

### 1.1. Core Principles
1. **Opaque-Box Requirement Verification**: Tests evaluate system contracts, external keys, and domain semantics purely against specifications in `ORIGINAL_REQUEST.md` and `PROJECT.md`. Tests do not rely on private internal helper hacks or trivial facades.
2. **Progressive Testability**: The test harness operates seamlessly across implementation milestones:
   - **M1/M2 Boundary**: When migrations exist, tests execute against parsed schema ASTs and in-memory relational SQL engines.
   - **M2/Live Deployment**: When migrations have been applied to Azure SQL, the suite seamlessly connects to live databases via `pytds` and Entra ID authentication.
3. **Domain Isolation Enforcement**: The test suite guarantees that databases remain decoupled:
   - Zero cross-database foreign keys.
   - Zero cross-database catalog queries in DDL scripts.
   - Domain-specific metric separation (financial accounting in ERP, physical warehouse execution in WMS, logistics and transport routing in TMS).
4. **Adversarial Distractor Validation**: Validates that heuristic shortcuts fail against distractors (wrong customer, wrong product, cancelled order, staged but un-dispatched trailer, allocated stock, background noise). Multi-agent synthesis across all three systems is required to determine ground truth.

---

## 2. Test Architecture & Directory Structure

```
/Users/rahulkini/project/eors/
├── e2e_tests/
│   ├── __init__.py                     # Package definition
│   ├── conftest_helpers.py             # Shared fixtures, SQL parser, SQLite simulator, pytds live connector
│   ├── test_e2e_runner.py              # Unified runner with tier filtering, summary reporting, and timing
│   ├── test_tier1_features.py          # Tier 1: Feature coverage (F1-F15, >=5 test cases per feature, 76 total)
│   ├── test_tier2_boundaries.py        # Tier 2: Boundary & corner cases (25 total)
│   ├── test_tier3_combinations.py      # Tier 3: Cross-feature pairwise interactions (17 total)
│   └── test_tier4_scenarios.py         # Tier 4: Real-world application scenarios & multi-agent pipeline (9 total)
├── TEST_INFRA.md                       # Test infrastructure index (this document)
├── TEST_READY.md                       # Publication of test suite readiness
└── PROJECT.md                          # Master project specification
```

### 2.1. Authentication & Driver Architecture
- **Pure-Python TDS 7.4**: Utilizes `python-tds` (`pytds` 1.17.1) with TLS encryption. Zero dependency on system C ODBC drivers (`unixodbc` / `msodbcsql18`).
- **Microsoft Entra ID OAuth2**: Token acquisition with resource scope `https://database.windows.net/.default` via `azure-identity` (`DefaultAzureCredential` / `AzureCliCredential` / `ManagedIdentityCredential`).
- **Serverless Wakeup & Resilience**: Automatic retry backoff handling error code `40613` ("Database is not currently available") and connection timeouts during serverless database auto-resume.
- **In-Memory SQL Dual Engine**: Translates T-SQL DDL/DML into standard relational tables within in-memory SQLite instances to verify queries and join semantics deterministically in local/offline environments.

---

## 3. Test Runner Invocation

### 3.1. Unified Runner (Recommended)
Run all 127 test cases across all four tiers with formatted execution summary:
```bash
/Users/rahulkini/project/eors/.venv/bin/python3 /Users/rahulkini/project/eors/e2e_tests/test_e2e_runner.py
```

### 3.2. Tier-Specific Execution
Execute individual tiers using the `--tier` flag:
```bash
# Tier 1: Feature Coverage (F1-F15)
/Users/rahulkini/project/eors/.venv/bin/python3 e2e_tests/test_e2e_runner.py --tier 1

# Tier 2: Boundary & Corner Cases
/Users/rahulkini/project/eors/.venv/bin/python3 e2e_tests/test_e2e_runner.py --tier 2

# Tier 3: Cross-Feature Pairwise Interactions
/Users/rahulkini/project/eors/.venv/bin/python3 e2e_tests/test_e2e_runner.py --tier 3

# Tier 4: Real-World Scenarios
/Users/rahulkini/project/eors/.venv/bin/python3 e2e_tests/test_e2e_runner.py --tier 4
```

### 3.3. Verbose Mode
Display individual test method execution:
```bash
/Users/rahulkini/project/eors/.venv/bin/python3 e2e_tests/test_e2e_runner.py -v
```

### 3.4. Standard Python Unittest Discovery
```bash
/Users/rahulkini/project/eors/.venv/bin/python3 -m unittest discover -s e2e_tests -p "test_tier*.py"
```

---

## 4. Feature Coverage Mapping Matrix

| Feature | Feature Name | Test Module | Test Class | Test Count | Key Invariants Verified |
|:---|:---|:---|:---|:---:|:---|
| **F1** | ERP Legacy Schema | `test_tier1_features.py` | `TestF1ERPLegacySchema` | 5 | All 4 tables exist, `tbl_` prefix, PascalCase/Hungarian columns, primary keys, internal FKs. |
| **F2** | ERP Logical & Financial Valuation | `test_tier1_features.py` | `TestF2ERPLogicalFinancialValuation` | 5 | Logical balance columns (`Qty_On_Hand`), financial columns (`Unit_Cost_USD`), GL accounts, order totals, zero physical bins. |
| **F3** | ERP Text Order Statuses | `test_tier1_features.py` | `TestF3ERPTextOrderStatuses` | 5 | String column types, descriptive strings (`Completed`, `Processing`, `Cancelled`), rejection of numeric status IDs. |
| **F4** | ERP Seed Data & Catalog | `test_tier1_features.py` | `TestF4ERPSeedDataAndCatalog` | 5 | Customer Acme Corp (`CUST-00101`), `SKU-LAPTOP-15-ENT`, Order `SO-10045`, line items (10 units), distractor accounts seeded. |
| **F5** | WMS Physical Schema | `test_tier1_features.py` | `TestF5WMSPhysicalSchema` | 5 | Modern snake_case tables (`bin_locations`, `dock_doors`, `inventory_lots`, `handling_units`, `outbound_picks`), primary keys, zero financial columns. |
| **F6** | WMS Integer Status Codes | `test_tier1_features.py` | `TestF6WMSIntegerStatusCodes` | 5 | `status_id` is INT; verifies presence of states 1 (Allocated), 2 (Picked), 4 (Staged), 5 (Loaded). |
| **F7** | WMS Physical Constraints | `test_tier1_features.py` | `TestF7WMSPhysicalConstraints` | 5 | Coordinates in `bin_locations`, `dock_doors` active status, lot QA status, LPN barcodes in `handling_units`, execution timestamps. |
| **F8** | WMS External Reference Linking | `test_tier1_features.py` | `TestF8WMSExternalReferenceLinking` | 5 | `erp_order_ref` and `customer_po_ref` present, zero cross-DB FK, target `PK-8801` links to `SO-10045` and `HU-8841-PLT`. |
| **F9** | TMS Logistics Schema | `test_tier1_features.py` | `TestF9TMSLogisticsSchema` | 5 | Upper snake case / PascalCase naming, primary keys, internal foreign keys (BOL -> Loads, Manifests -> BOL), zero warehouse coordinates. |
| **F10** | TMS Physical Freight Metrics | `test_tier1_features.py` | `TestF10TMSPhysicalFreightMetrics` | 5 | `Pallet_Count`, `Gross_Weight_LBS`, `Physical_Dimensions`, `Waybill_Number`, `Tracking_Number`, SCAC codes. |
| **F11** | TMS Handling Unit Linking | `test_tier1_features.py` | `TestF11TMSHandlingUnitLinking` | 5 | `Handling_Unit_Ref` present, zero cross-DB FK, `MNF-2026-8801` links to `HU-8841-PLT`, resolves carrier Apex and tracking. |
| **F12** | SQL Migration Scripts | `test_tier1_features.py` | `TestF12SQLMigrationScripts` | 5 | All 3 scripts exist in `migrations/`, idempotent drop table logic, `GO` batches, zero foreign catalog references, DDL + DML. |
| **F13** | Entra ID Migration Runner | `test_tier1_features.py` | `TestF13EntraIDMigrationRunner` | 5 | Resource scope configuration, pytds driver availability (1.17.1), `access_token_callable` interface, error 40613 retry handling, server hostname. |
| **F14** | Cross-DB Verification Script | `test_tier1_features.py` | `TestF14CrossDBVerificationLogic` | 5 | Step 1 ERP resolution, Step 2 WMS resolution, Step 3 TMS resolution, confirmed ground truth shipping determination, decoupled query flow. |
| **F15** | Adversarial Distractor Suite | `test_tier1_features.py` | `TestF15AdversarialDistractorSuite` | 6 | Isolation of DIST-1 (Chairs), DIST-2 (Globex), DIST-3 (Cancelled), DIST-4 (Staged pending pickup), DIST-5 (Allocated), DIST-6 (Background noise). |
| **T2** | Boundary & Corner Cases | `test_tier2_boundaries.py` | Multiple classes | 25 | Empty sets, cancelled orders, staged at dock, product search substring bounds, serverless retry simulation, positive numeric boundaries. |
| **T3** | Cross-Feature Interactions | `test_tier3_combinations.py` | Multiple classes | 17 | ERP<->WMS pairwise status, PO matching, SKU matching; WMS<->TMS HU matching; ERP<->TMS consignee address and timeline matching; distractor traps; decoupling integrity. |
| **T4** | Real-World Application Scenarios | `test_tier4_scenarios.py` | Multiple classes | 9 | Canonical Acme Corp resolution pipeline, DIST-1..DIST-6 status classification, multi-agent query synthesis engine. |

---

## 5. Test Suite Metrics Summary

```
================================================================================
                      E2E TEST SUITE EXECUTION SUMMARY
================================================================================
 Tier     Description                                Total    Pass     Fail/Err   Time    
--------------------------------------------------------------------------------
 Tier 1   Tier 1: Feature Coverage (F1-F15)          76       76       0/0        0.013s
 Tier 2   Tier 2: Boundary & Corner Cases            25       25       0/0        0.001s
 Tier 3   Tier 3: Cross-Feature Interactions         17       17       0/0        0.002s
 Tier 4   Tier 4: Real-World Application Scenarios   9        9        0/0        0.001s
--------------------------------------------------------------------------------
 TOTAL                                               127      127      0          0.018s
 PASS RATE: 100.0% (127/127)
================================================================================
```

---

## 6. Pass/Fail Thresholds & Quality Gates

1. **Pass Rate Threshold**: 100% pass across all 127 tests is required. Zero test failures or unhandled errors are permitted.
2. **Schema Decoupling Guarantee**: Any test identifying a cross-database foreign key constraint immediately fails the suite.
3. **Distractor Rejection Verification**: Any test allowing an un-shipped distractor (such as DIST-4 staged at dock or DIST-1 office chairs) to be reported as "shipped" immediately fails the suite.
4. **Execution Latency**: Local test suite execution must complete in under 5.0 seconds.
