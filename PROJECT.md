# Project: Azure SQL Multi-Agent Cross-Database Challenge (EORS)

## Architecture

The project implements three decoupled, autonomous Azure SQL databases on `eosr-db-server.database.windows.net` designed with intentionally conflicting schemas, naming conventions, and data representations. A multi-agent AI system synthesizes data across these autonomous systems without cross-database foreign keys.

```
                      [Multi-Agent System / Verification Runner]
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           │ (T-SQL via pytds)       │ (T-SQL via pytds)       │ (T-SQL via pytds)
           ▼                         ▼                         ▼
   [db-01-dev: ERP]          [db-02-dev: WMS]          [db-03-dev: TMS]
  - Legacy naming: tbl_*    - Modern: snake_case      - Logistics naming
  - Text statuses           - Integer status_id codes - Freight metrics (pallets, lbs)
  - Financial asset logic   - Physical bin/lot/HU     - Waybills & tracking numbers
  - Cust: Acme Corp         - External ref: erp_order - Bridging: Handling_Unit_Ref
           │                         │                         │
           └──── Order_ID ('SO-10045')─┴──── Handling_Unit_Ref ────────┘
                                            ('HU-8841-PLT')
```

### Authentication & Driver Architecture
- Target Server: `eosr-db-server.database.windows.net`
- Authentication: Microsoft Entra ID OAuth2 bearer tokens (`https://database.windows.net/.default`) obtained via `DefaultAzureCredential` / `AzureCliCredential` / `az account get-access-token`. Server enforces `azureADOnlyAuthentication: true`.
- Connection Driver: `python-tds` (`pytds` 1.17.1) pure-Python TDS 7.4 driver with `access_token_callable`. Zero dependency on C ODBC drivers (`unixodbc` / `msodbcsql18` not required).
- Serverless Resumption: Retry backoff with error `40613` detection to handle database cold-start auto-wake.

---

## Feature Inventory

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | ERP Legacy Schema | Tables `tbl_Customers`, `tbl_Inventory_Master`, `tbl_SalesOrders`, `tbl_OrderLineItems` with legacy naming conventions | M1 (DONE) | ORIGINAL_REQUEST §R1 |
| F2 | ERP Logical & Financial Valuation | Inventory tracked purely by logical balance (`Qty_On_Hand`, `Qty_Allocated`) and monetary value (`Unit_Cost_USD`, `Total_Amount`) | M1 (DONE) | ORIGINAL_REQUEST §R1 |
| F3 | ERP Text Order Statuses | String-based status values (`'Completed'`, `'Processing'`, `'Cancelled'`, `'On Hold'`) | M1 (DONE) | ORIGINAL_REQUEST §R1 |
| F4 | ERP Seed Data & Catalog | Customer "Acme Corp", "Enterprise Laptop 15-inch", Order `SO-10045` + distractor orders/customers | M1 (DONE) | ORIGINAL_REQUEST §R1 |
| F5 | WMS Physical Schema | Modern snake_case tables `bin_locations`, `dock_doors`, `inventory_lots`, `handling_units`, `outbound_picks` | M1 (DONE) | ORIGINAL_REQUEST §R2 |
| F6 | WMS Integer Status Codes | Numeric `status_id` codes (`1`=Allocated, `2`=Picked, `3`=Packed, `4`=Staged, `5`=Loaded, `9`=Cancelled) | M1 (DONE) | ORIGINAL_REQUEST §R2 |
| F7 | WMS Physical Constraints | Handling units (LPN barcodes), bin locations (`zone-aisle-shelf-bin`), lots, dock doors (`DOCK-04`, `DOCK-07`) | M1 (DONE) | ORIGINAL_REQUEST §R2 |
| F8 | WMS External Reference Linking | External linking via `erp_order_ref` (Order ID) and `customer_po_ref` without cross-DB foreign keys | M1 (DONE) | ORIGINAL_REQUEST §R2 |
| F9 | TMS Logistics Schema | Logistics tables `Carrier_Master`, `Freight_Loads`, `Bill_Of_Lading`, `Carrier_Manifests` | M1 (DONE) | ORIGINAL_REQUEST §R3 |
| F10 | TMS Physical Freight Metrics | Tracking `Pallet_Count`, `Gross_Weight_LBS`, `Physical_Dimensions`, `Stop_Sequence`, `Carrier_Name`, `Waybill_Number`, `Tracking_Number` | M1 (DONE) | ORIGINAL_REQUEST §R3 |
| F11 | TMS Handling Unit Linking | Carrier manifest linking via `Handling_Unit_Ref` without cross-DB foreign keys | M1 (DONE) | ORIGINAL_REQUEST §R3 |
| F12 | SQL Migration Scripts | Organized DDL/DML scripts in `migrations/` directory (`db_01_erp.sql`, `db_02_wms.sql`, `db_03_tms.sql`) | M1 (DONE) | ORIGINAL_REQUEST §R4 |
| F13 | Entra ID Migration Runner | Python migration runner `migrations/run_migrations.py` applying DDL/DML to all 3 DBs using Entra ID token auth with serverless resume retry | M2 (DONE) | ORIGINAL_REQUEST §R4 |
| F14 | Cross-DB Verification Script | Automated test script `verify_cross_db_challenge.py` executing 3-stage join query (ERP -> WMS -> TMS) verifying Acme Corp's laptop order tracking status and exiting with code 0 | M2 (DONE) | ORIGINAL_REQUEST §R4 |
| F15 | Adversarial Distractor Suite | 6 distractor scenarios (wrong product, wrong customer, cancelled order, staged pending pickup, allocated only, background traffic) preventing trivial heuristics | M1 (DONE) | ORIGINAL_REQUEST §R4 & Acceptance Criteria |
| F16 | Opaque-Box E2E Test Suite | Independent multi-tier test suite (Tiers 1-4) verifying schema isolation, data consistency, error handling, and query resolution | E2E Track (DONE) | ORIGINAL_REQUEST Acceptance Criteria |
| F17 | Adversarial Hardening | Tier 5 adversarial stress testing verifying edge cases, injection resistance, and robust cross-system synthesis | M3 (DONE) | Project Pattern Phase 2 |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Independent requirement-driven test suite (Tiers 1-4), test runner, and `TEST_READY.md` | none | DONE |
| M1 | Domain Schemas & Seed Data | SQL DDL & DML migrations (`migrations/db_01_erp.sql`, `migrations/db_02_wms.sql`, `migrations/db_03_tms.sql`) | none | DONE |
| M2 | Migration Runner & Cross-DB Verification | `migrations/run_migrations.py` with Entra ID auth & serverless retry; `verify_cross_db_challenge.py` connecting live to all 3 DBs | M1 | DONE |
| M3 | Final Milestone: E2E Pass & Hardening | Phase 1: 100% pass on E2E test suite (Tiers 1-4); Phase 2: Tier 5 adversarial coverage hardening | M2, E2E | DONE |

---

## Interface Contracts

### ERP (`db-01-dev`) ↔ WMS (`db-02-dev`)
- **Shared Key**: Order Identifier
  - ERP: `tbl_SalesOrders.Order_ID` (`VARCHAR(30)`), e.g., `'SO-10045'`
  - WMS: `outbound_picks.erp_order_ref` (`VARCHAR(50)`), e.g., `'SO-10045'`
- **Secondary Key**: Customer PO Number
  - ERP: `tbl_SalesOrders.PO_Number` (`VARCHAR(50)`), e.g., `'PO-ACM-2026-9921'`
  - WMS: `outbound_picks.customer_po_ref` (`VARCHAR(50)`), e.g., `'PO-ACM-2026-9921'`
- **Decoupling Constraint**: NO foreign key constraint between databases. Loose string matching only.

### WMS (`db-02-dev`) ↔ TMS (`db-03-dev`)
- **Shared Key**: Handling Unit Identifier / License Plate Number (LPN)
  - WMS: `handling_units.hu_id` (`VARCHAR(40)`), e.g., `'HU-8841-PLT'`
  - TMS: `Carrier_Manifests.Handling_Unit_Ref` (`VARCHAR(40)`), e.g., `'HU-8841-PLT'`
  - TMS: `Bill_Of_Lading.Handling_Unit_Ref` (`VARCHAR(40)`), e.g., `'HU-8841-PLT'`
- **Decoupling Constraint**: NO foreign key constraint between databases. Loose string matching only.

### Canonical Order Flow (Acme Corp Laptop Order)
1. **ERP Resolution**:
   - Query: Customer `'Acme Corp'` + Product description `'%Laptop%'`
   - Yields: Order `SO-10045`, Status `'Completed'`, Item `SKU-LAPTOP-15-ENT`, Qty 10
2. **WMS Resolution**:
   - Query: `erp_order_ref = 'SO-10045'`
   - Yields: `status_id = 5` (Loaded), `handling_unit_id = 'HU-8841-PLT'`, `staged_dock_code = 'DOCK-04'`
3. **TMS Resolution**:
   - Query: `Handling_Unit_Ref = 'HU-8841-PLT'`
   - Yields: `Carrier_Name = 'Apex Freight Express'`, `Tracking_Number = 'TRK-AFX-9948201'`, `Waybill_Number = 'WB-884102'`, `Shipment_Status = 'IN_TRANSIT'`

---

## Code Layout

```
/Users/rahulkini/project/eors/
├── migrations/
│   ├── db_01_erp.sql               # ERP DDL and seed DML (M1 - DONE)
│   ├── db_02_wms.sql               # WMS DDL and seed DML (M1 - DONE)
│   ├── db_03_tms.sql               # TMS DDL and seed DML (M1 - DONE)
│   └── run_migrations.py           # Automated migration runner via pytds + Entra ID (M2 - DONE)
├── verify_cross_db_challenge.py    # Automated cross-database verification script (M2 - DONE)
├── e2e_tests/                      # Requirement-driven opaque-box test suite (E2E Track - DONE)
│   ├── test_e2e_runner.py          # Unified test runner
│   ├── test_tier1_features.py      # Tier 1: Feature coverage
│   ├── test_tier2_boundaries.py    # Tier 2: Boundaries & edge cases
│   ├── test_tier3_combinations.py  # Tier 3: Cross-feature combinations
│   └── test_tier4_scenarios.py     # Tier 4: Real-world application scenarios
├── TEST_INFRA.md                   # Test infrastructure index (DONE)
├── TEST_READY.md                   # Published when E2E test suite is complete (DONE)
└── PROJECT.md                      # Project master index (ALL MILESTONES DONE)
```
