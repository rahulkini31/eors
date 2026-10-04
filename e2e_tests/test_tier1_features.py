"""Tier 1: Feature Coverage Test Suite.
Verifies features F1 through F15 with >= 5 independent test cases per feature.
Covers schema definitions, domain semantics, naming conventions, status models,
metrics separation, external reference linking, migrations, Entra ID driver, and distractors.
"""

import os
import re
import unittest
from typing import Dict, Any

from e2e_tests.conftest_helpers import (
    MIGRATION_FILES,
    PROJECT_ROOT,
    load_in_memory_db,
    parse_migration_metadata,
)


class TestF1ERPLegacySchema(unittest.TestCase):
    """F1: ERP Legacy Schema — tables with legacy naming conventions (tbl_*)."""

    @classmethod
    def setUpClass(cls):
        cls.meta = parse_migration_metadata(MIGRATION_FILES["db-01-dev"])
        cls.conn = load_in_memory_db("db-01-dev")

    def test_f1_01_all_four_legacy_tables_exist(self):
        """Verify all 4 core ERP legacy tables are defined in db_01_erp.sql."""
        expected = {"tbl_Customers", "tbl_Inventory_Master", "tbl_SalesOrders", "tbl_OrderLineItems"}
        actual = set(self.meta["table_names"])
        self.assertTrue(expected.issubset(actual), f"Missing ERP tables: {expected - actual}")

    def test_f1_02_strict_tbl_prefix_convention(self):
        """Verify every table in ERP domain strictly adheres to the 'tbl_' naming convention."""
        for tname in self.meta["table_names"]:
            self.assertTrue(
                tname.startswith("tbl_"),
                f"Table {tname} in ERP violates legacy 'tbl_' prefix convention",
            )

    def test_f1_03_pascal_hungarian_column_naming(self):
        """Verify columns use PascalCase / Hungarian compound naming (Cust_ID, Item_SKU, Qty_On_Hand)."""
        expected_cols = {
            "tbl_Customers": ["Cust_ID", "Cust_Name", "Credit_Limit_USD", "Payment_Terms"],
            "tbl_Inventory_Master": ["Item_SKU", "Item_Description", "Qty_On_Hand", "Qty_Allocated"],
            "tbl_SalesOrders": ["Order_ID", "Cust_ID", "PO_Number", "OrderStatus", "Total_Amount"],
            "tbl_OrderLineItems": ["Line_ID", "Order_ID", "Item_SKU", "Quantity", "Extended_Price"],
        }
        for tname, cols in expected_cols.items():
            tcols = self.meta["tables"][tname]["column_names"]
            for c in cols:
                self.assertIn(c, tcols, f"Column {c} missing from ERP table {tname}")

    def test_f1_04_primary_keys_explicitly_declared(self):
        """Verify every ERP table defines a valid primary key."""
        expected_pks = {
            "tbl_Customers": "Cust_ID",
            "tbl_Inventory_Master": "Item_SKU",
            "tbl_SalesOrders": "Order_ID",
            "tbl_OrderLineItems": "Line_ID",
        }
        for tname, pk in expected_pks.items():
            pks = self.meta["tables"][tname]["primary_keys"]
            self.assertIn(pk, pks, f"Primary key {pk} not found for {tname}")

    def test_f1_05_internal_foreign_key_referential_integrity(self):
        """Verify internal relational integrity constraints within the ERP database."""
        fks = self.meta["tables"]["tbl_OrderLineItems"]["foreign_keys"]
        fk_targets = {(fk["column"], fk["ref_table"], fk["ref_column"]) for fk in fks}
        self.assertIn(("Order_ID", "tbl_SalesOrders", "Order_ID"), fk_targets)
        self.assertIn(("Item_SKU", "tbl_Inventory_Master", "Item_SKU"), fk_targets)


class TestF2ERPLogicalFinancialValuation(unittest.TestCase):
    """F2: ERP Logical & Financial Valuation — inventory tracked purely as financial assets."""

    @classmethod
    def setUpClass(cls):
        cls.meta = parse_migration_metadata(MIGRATION_FILES["db-01-dev"])
        cls.conn = load_in_memory_db("db-01-dev")

    def test_f2_01_logical_balance_columns_present(self):
        """Verify inventory balances are tracked logically via Qty_On_Hand and Qty_Allocated."""
        inv_cols = self.meta["tables"]["tbl_Inventory_Master"]["column_names"]
        self.assertIn("Qty_On_Hand", inv_cols)
        self.assertIn("Qty_Allocated", inv_cols)

    def test_f2_02_monetary_valuation_columns_present(self):
        """Verify valuation metrics Unit_Cost_USD and List_Price_USD exist on inventory master."""
        inv_cols = self.meta["tables"]["tbl_Inventory_Master"]["column_names"]
        self.assertIn("Unit_Cost_USD", inv_cols)
        self.assertIn("List_Price_USD", inv_cols)

    def test_f2_03_general_ledger_asset_account_tracked(self):
        """Verify General Ledger asset code (GL_Asset_Account) exists for accounting balance sheet."""
        inv_cols = self.meta["tables"]["tbl_Inventory_Master"]["column_names"]
        self.assertIn("GL_Asset_Account", inv_cols)

    def test_f2_04_sales_order_financial_totals_breakdown(self):
        """Verify sales orders break down subtotal, tax, shipping fee, and total amount with currency."""
        so_cols = self.meta["tables"]["tbl_SalesOrders"]["column_names"]
        for financial_col in ["Subtotal_Amount", "Tax_Amount", "Shipping_Fee", "Total_Amount", "Currency_Code"]:
            self.assertIn(financial_col, so_cols)

    def test_f2_05_no_physical_warehouse_coordinates_in_erp(self):
        """Verify ERP schema contains zero physical warehouse coordinates (bins, aisles, docks)."""
        forbidden_terms = ["bin", "aisle", "shelf", "dock", "pallet", "trailer", "lpn"]
        for tname in self.meta["table_names"]:
            for col in self.meta["tables"][tname]["column_names"]:
                for term in forbidden_terms:
                    self.assertNotIn(
                        term,
                        col.lower(),
                        f"ERP table {tname} illegally contains physical warehouse metric: {col}",
                    )


class TestF3ERPTextOrderStatuses(unittest.TestCase):
    """F3: ERP Text Order Statuses — string-based order and line status values."""

    @classmethod
    def setUpClass(cls):
        cls.meta = parse_migration_metadata(MIGRATION_FILES["db-01-dev"])
        cls.conn = load_in_memory_db("db-01-dev")

    def test_f3_01_order_status_is_string_type(self):
        """Verify tbl_SalesOrders.OrderStatus column is a VARCHAR/NVARCHAR string type."""
        cols = {c["name"]: c["type"] for c in self.meta["tables"]["tbl_SalesOrders"]["columns"]}
        self.assertIn("VARCHAR", cols["OrderStatus"])

    def test_f3_02_payment_status_is_string_type(self):
        """Verify tbl_SalesOrders.Payment_Status column is a VARCHAR string type."""
        cols = {c["name"]: c["type"] for c in self.meta["tables"]["tbl_SalesOrders"]["columns"]}
        self.assertIn("VARCHAR", cols["Payment_Status"])

    def test_f3_03_line_status_is_string_type(self):
        """Verify tbl_OrderLineItems.Line_Status is a VARCHAR string type."""
        cols = {c["name"]: c["type"] for c in self.meta["tables"]["tbl_OrderLineItems"]["columns"]}
        self.assertIn("VARCHAR", cols["Line_Status"])

    def test_f3_04_seed_order_statuses_are_descriptive_strings(self):
        """Verify seed data uses descriptive strings: Completed, Processing, Cancelled."""
        cur = self.conn.cursor()
        cur.execute("SELECT DISTINCT OrderStatus FROM tbl_SalesOrders")
        statuses = {r[0] for r in cur.fetchall()}
        self.assertIn("Completed", statuses)
        self.assertIn("Processing", statuses)
        self.assertIn("Cancelled", statuses)

    def test_f3_05_no_integer_status_codes_in_erp_orders(self):
        """Verify no integer status IDs exist in ERP order statuses."""
        cur = self.conn.cursor()
        cur.execute("SELECT OrderStatus FROM tbl_SalesOrders")
        for r in cur.fetchall():
            self.assertFalse(
                r[0].isdigit(),
                f"OrderStatus {r[0]} is an integer code, violating text status requirement",
            )


class TestF4ERPSeedDataAndCatalog(unittest.TestCase):
    """F4: ERP Seed Data & Catalog — Acme Corp, Enterprise Laptop 15-inch, SO-10045 + distractors."""

    @classmethod
    def setUpClass(cls):
        cls.conn = load_in_memory_db("db-01-dev")

    def test_f4_01_acme_corp_customer_record_exists(self):
        """Verify customer Acme Corp exists with ID CUST-00101 and Enterprise Tier 1 terms."""
        cur = self.conn.cursor()
        cur.execute("SELECT Cust_ID, Cust_Name, Account_Type FROM tbl_Customers WHERE Cust_Name = 'Acme Corp'")
        row = cur.fetchone()
        self.assertIsNotNone(row, "Customer 'Acme Corp' not found")
        self.assertEqual(row["Cust_ID"], "CUST-00101")
        self.assertEqual(row["Account_Type"], "ENTERPRISE_TIER_1")

    def test_f4_02_enterprise_laptop_catalog_item_exists(self):
        """Verify catalog item SKU-LAPTOP-15-ENT exists with 15-inch laptop description."""
        cur = self.conn.cursor()
        cur.execute("SELECT Item_SKU, Item_Description, Unit_Cost_USD, List_Price_USD FROM tbl_Inventory_Master WHERE Item_SKU = 'SKU-LAPTOP-15-ENT'")
        row = cur.fetchone()
        self.assertIsNotNone(row, "Item 'SKU-LAPTOP-15-ENT' not found")
        self.assertIn("15-inch", row["Item_Description"])
        self.assertEqual(row["List_Price_USD"], 1850.00)

    def test_f4_03_canonical_target_order_so10045_exists(self):
        """Verify target order SO-10045 exists for Acme Corp with PO PO-ACM-2026-9921 and Completed status."""
        cur = self.conn.cursor()
        cur.execute("SELECT Order_ID, Cust_ID, PO_Number, OrderStatus, Total_Amount FROM tbl_SalesOrders WHERE Order_ID = 'SO-10045'")
        row = cur.fetchone()
        self.assertIsNotNone(row, "Order 'SO-10045' not found")
        self.assertEqual(row["Cust_ID"], "CUST-00101")
        self.assertEqual(row["PO_Number"], "PO-ACM-2026-9921")
        self.assertEqual(row["OrderStatus"], "Completed")
        self.assertEqual(row["Total_Amount"], 20230.00)

    def test_f4_04_order_line_item_for_so10045_matches(self):
        """Verify line item for SO-10045 has Quantity = 10 for SKU-LAPTOP-15-ENT."""
        cur = self.conn.cursor()
        cur.execute("SELECT Order_ID, Item_SKU, Quantity, Unit_Price, Extended_Price, Line_Status FROM tbl_OrderLineItems WHERE Order_ID = 'SO-10045'")
        row = cur.fetchone()
        self.assertIsNotNone(row, "Line item for SO-10045 not found")
        self.assertEqual(row["Item_SKU"], "SKU-LAPTOP-15-ENT")
        self.assertEqual(row["Quantity"], 10)
        self.assertEqual(row["Extended_Price"], 18500.00)
        self.assertEqual(row["Line_Status"], "FULFILLED")

    def test_f4_05_distractor_customers_and_orders_seeded(self):
        """Verify distractor accounts Globex, Umbrella, and Initech exist in ERP."""
        cur = self.conn.cursor()
        cur.execute("SELECT Cust_Name FROM tbl_Customers")
        names = {r[0] for r in cur.fetchall()}
        self.assertIn("Globex Corporation", names)
        self.assertIn("Umbrella Corporation", names)
        self.assertIn("Initech LLC", names)


class TestF5WMSPhysicalSchema(unittest.TestCase):
    """F5: WMS Physical Schema — modern snake_case tables for warehouse execution."""

    @classmethod
    def setUpClass(cls):
        cls.meta = parse_migration_metadata(MIGRATION_FILES["db-02-dev"])
        cls.conn = load_in_memory_db("db-02-dev")

    def test_f5_01_all_five_wms_tables_exist(self):
        """Verify all 5 WMS execution tables are defined in db_02_wms.sql."""
        expected = {"bin_locations", "dock_doors", "inventory_lots", "handling_units", "outbound_picks"}
        actual = set(self.meta["table_names"])
        self.assertTrue(expected.issubset(actual), f"Missing WMS tables: {expected - actual}")

    def test_f5_02_strict_snake_case_table_naming(self):
        """Verify every table name follows lowercase snake_case convention."""
        for tname in self.meta["table_names"]:
            self.assertEqual(
                tname,
                tname.lower(),
                f"Table {tname} in WMS violates snake_case convention",
            )
            self.assertFalse(tname.startswith("tbl_"), f"WMS table {tname} must not use legacy tbl_ prefix")

    def test_f5_03_strict_snake_case_column_naming(self):
        """Verify all column names in WMS tables follow lowercase snake_case convention."""
        for tname in self.meta["table_names"]:
            for col in self.meta["tables"][tname]["column_names"]:
                self.assertEqual(
                    col,
                    col.lower(),
                    f"Column {col} in WMS table {tname} violates lowercase snake_case convention",
                )

    def test_f5_04_wms_primary_keys_declared(self):
        """Verify each WMS table defines its expected primary key."""
        expected_pks = {
            "bin_locations": "bin_id",
            "dock_doors": "dock_door_id",
            "inventory_lots": "lot_id",
            "handling_units": "hu_id",
            "outbound_picks": "pick_id",
        }
        for tname, pk in expected_pks.items():
            self.assertIn(pk, self.meta["tables"][tname]["primary_keys"])

    def test_f5_05_no_financial_columns_in_wms(self):
        """Verify WMS schema contains zero financial or pricing metrics."""
        forbidden_financials = ["price", "cost", "tax", "usd", "revenue", "margin", "credit", "payment"]
        for tname in self.meta["table_names"]:
            for col in self.meta["tables"][tname]["column_names"]:
                for fin in forbidden_financials:
                    self.assertNotIn(
                        fin,
                        col.lower(),
                        f"WMS table {tname} illegally contains financial metric: {col}",
                    )


class TestF6WMSIntegerStatusCodes(unittest.TestCase):
    """F6: WMS Integer Status Codes — numeric status_id codes for physical warehouse states."""

    @classmethod
    def setUpClass(cls):
        cls.meta = parse_migration_metadata(MIGRATION_FILES["db-02-dev"])
        cls.conn = load_in_memory_db("db-02-dev")

    def test_f6_01_status_id_column_is_integer(self):
        """Verify outbound_picks.status_id is defined as an integer data type."""
        cols = {c["name"]: c["type"] for c in self.meta["tables"]["outbound_picks"]["columns"]}
        self.assertEqual(cols["status_id"], "INT")

    def test_f6_02_status_code_1_allocated_present(self):
        """Verify status_id = 1 (Allocated) exists in outbound_picks seed data."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM outbound_picks WHERE status_id = 1")
        self.assertGreater(cur.fetchone()[0], 0)

    def test_f6_03_status_code_2_picked_present(self):
        """Verify status_id = 2 (Picked) exists in outbound_picks seed data."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM outbound_picks WHERE status_id = 2")
        self.assertGreater(cur.fetchone()[0], 0)

    def test_f6_04_status_code_4_staged_at_dock_present(self):
        """Verify status_id = 4 (Staged at Dock) exists in outbound_picks seed data."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM outbound_picks WHERE status_id = 4")
        self.assertGreater(cur.fetchone()[0], 0)

    def test_f6_05_status_code_5_loaded_present(self):
        """Verify status_id = 5 (Loaded into trailer) exists for the target order."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM outbound_picks WHERE status_id = 5 AND erp_order_ref = 'SO-10045'")
        self.assertEqual(cur.fetchone()[0], 1)


class TestF7WMSPhysicalConstraints(unittest.TestCase):
    """F7: WMS Physical Constraints — bin locations, dock doors, inventory lots, handling units."""

    @classmethod
    def setUpClass(cls):
        cls.conn = load_in_memory_db("db-02-dev")

    def test_f7_01_bin_coordinates_tracked(self):
        """Verify bin_locations tracks zone, aisle, shelf level, and max weight capacity."""
        cur = self.conn.cursor()
        cur.execute("SELECT bin_code, zone_code, aisle_num, shelf_level, max_weight_kg FROM bin_locations WHERE bin_code = 'Z1-A04-S02-B01'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["zone_code"], "ZONE-TECH-MEZZ")
        self.assertEqual(row["aisle_num"], 4)

    def test_f7_02_dock_doors_defined(self):
        """Verify staging dock doors DOCK-04 and DOCK-07 exist and are ACTIVE."""
        cur = self.conn.cursor()
        cur.execute("SELECT dock_code, door_status FROM dock_doors WHERE dock_code IN ('DOCK-04', 'DOCK-07')")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertEqual(r["door_status"], "ACTIVE")

    def test_f7_03_inventory_lots_quality_traceability(self):
        """Verify inventory lots track lot number, manufactured date, and QA status."""
        cur = self.conn.cursor()
        cur.execute("SELECT lot_number, sku_code, qa_status FROM inventory_lots WHERE lot_number = 'LOT-2026Q1-TECH'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["sku_code"], "SKU-LAPTOP-15-ENT")
        self.assertEqual(row["qa_status"], "PASSED")

    def test_f7_04_handling_units_lpn_barcode(self):
        """Verify handling units track LPN barcode, container type, tare weight, and staged dock."""
        cur = self.conn.cursor()
        cur.execute("SELECT hu_id, lpn_barcode, hu_type, staged_dock_code FROM handling_units WHERE hu_id = 'HU-8841-PLT'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["lpn_barcode"], "BC-LPN-8841029")
        self.assertEqual(row["hu_type"], "PALLET")
        self.assertEqual(row["staged_dock_code"], "DOCK-04")

    def test_f7_05_execution_timestamps_recorded(self):
        """Verify outbound_picks records pick_completed_at and dock_loaded_at for target order."""
        cur = self.conn.cursor()
        cur.execute("SELECT pick_completed_at, dock_loaded_at FROM outbound_picks WHERE pick_id = 'PK-8801'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row["pick_completed_at"])
        self.assertIsNotNone(row["dock_loaded_at"])


class TestF8WMSExternalReferenceLinking(unittest.TestCase):
    """F8: WMS External Reference Linking — erp_order_ref and customer_po_ref without cross-DB FK."""

    @classmethod
    def setUpClass(cls):
        cls.meta = parse_migration_metadata(MIGRATION_FILES["db-02-dev"])
        cls.conn = load_in_memory_db("db-02-dev")

    def test_f8_01_erp_order_ref_column_present(self):
        """Verify erp_order_ref column exists on outbound_picks."""
        cols = self.meta["tables"]["outbound_picks"]["column_names"]
        self.assertIn("erp_order_ref", cols)

    def test_f8_02_customer_po_ref_column_present(self):
        """Verify customer_po_ref column exists on outbound_picks."""
        cols = self.meta["tables"]["outbound_picks"]["column_names"]
        self.assertIn("customer_po_ref", cols)

    def test_f8_03_no_cross_database_foreign_key_declared(self):
        """Verify erp_order_ref has NO foreign key constraint to another database."""
        fks = self.meta["tables"]["outbound_picks"]["foreign_keys"]
        for fk in fks:
            self.assertNotEqual(
                fk["column"],
                "erp_order_ref",
                "erp_order_ref illegally has a foreign key constraint (cross-DB FK forbidden)",
            )

    def test_f8_04_target_pick_maps_to_so10045(self):
        """Verify pick PK-8801 links to erp_order_ref SO-10045 and PO PO-ACM-2026-9921."""
        cur = self.conn.cursor()
        cur.execute("SELECT erp_order_ref, customer_po_ref, sku_code, handling_unit_id FROM outbound_picks WHERE pick_id = 'PK-8801'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["erp_order_ref"], "SO-10045")
        self.assertEqual(row["customer_po_ref"], "PO-ACM-2026-9921")
        self.assertEqual(row["handling_unit_id"], "HU-8841-PLT")

    def test_f8_05_distractor_picks_have_distinct_erp_references(self):
        """Verify distractor picks link to their respective distinct ERP orders."""
        cur = self.conn.cursor()
        cur.execute("SELECT pick_id, erp_order_ref FROM outbound_picks WHERE pick_id IN ('PK-8802', 'PK-8803', 'PK-8804')")
        mapping = {r["pick_id"]: r["erp_order_ref"] for r in cur.fetchall()}
        self.assertEqual(mapping["PK-8802"], "SO-10046")
        self.assertEqual(mapping["PK-8803"], "SO-10047")
        self.assertEqual(mapping["PK-8804"], "SO-10048")


class TestF9TMSLogisticsSchema(unittest.TestCase):
    """F9: TMS Logistics Schema — transport and freight routing tables."""

    @classmethod
    def setUpClass(cls):
        cls.meta = parse_migration_metadata(MIGRATION_FILES["db-03-dev"])
        cls.conn = load_in_memory_db("db-03-dev")

    def test_f9_01_all_four_tms_tables_exist(self):
        """Verify all 4 TMS tables are defined in db_03_tms.sql."""
        expected = {"Carrier_Master", "Freight_Loads", "Bill_Of_Lading", "Carrier_Manifests"}
        actual = set(self.meta["table_names"])
        self.assertTrue(expected.issubset(actual), f"Missing TMS tables: {expected - actual}")

    def test_f9_02_logistics_naming_conventions_used(self):
        """Verify table names follow logistics PascalCase / Upper_Snake_Case naming."""
        for tname in self.meta["table_names"]:
            self.assertTrue(
                tname[0].isupper(),
                f"TMS table {tname} violates PascalCase / Upper_Snake_Case convention",
            )
            self.assertFalse(tname.startswith("tbl_"), f"TMS table {tname} must not use legacy tbl_ prefix")

    def test_f9_03_tms_primary_keys_declared(self):
        """Verify each TMS table defines its expected primary key."""
        expected_pks = {
            "Carrier_Master": "Carrier_ID",
            "Freight_Loads": "Load_ID",
            "Bill_Of_Lading": "BOL_Number",
            "Carrier_Manifests": "Manifest_ID",
        }
        for tname, pk in expected_pks.items():
            self.assertIn(pk, self.meta["tables"][tname]["primary_keys"])

    def test_f9_04_internal_relational_integrity_within_tms(self):
        """Verify internal foreign keys link manifests to BOLs and BOLs to loads."""
        bol_fks = self.meta["tables"]["Bill_Of_Lading"]["foreign_keys"]
        mnf_fks = self.meta["tables"]["Carrier_Manifests"]["foreign_keys"]
        self.assertTrue(any(fk["ref_table"] == "Freight_Loads" for fk in bol_fks))
        self.assertTrue(any(fk["ref_table"] == "Bill_Of_Lading" for fk in mnf_fks))

    def test_f9_05_no_warehouse_bin_coordinates_or_profit_margins_in_tms(self):
        """Verify TMS schema does not contain warehouse bins or customer profit margins."""
        forbidden = ["bin_code", "shelf", "margin", "profit", "unit_cost"]
        for tname in self.meta["table_names"]:
            for col in self.meta["tables"][tname]["column_names"]:
                for f in forbidden:
                    self.assertNotIn(f, col.lower())


class TestF10TMSPhysicalFreightMetrics(unittest.TestCase):
    """F10: TMS Physical Freight Metrics — pallets, gross weight, waybill, tracking number."""

    @classmethod
    def setUpClass(cls):
        cls.meta = parse_migration_metadata(MIGRATION_FILES["db-03-dev"])
        cls.conn = load_in_memory_db("db-03-dev")

    def test_f10_01_pallet_count_and_weight_metrics_present(self):
        """Verify Carrier_Manifests tracks Pallet_Count and Gross_Weight_LBS."""
        cols = self.meta["tables"]["Carrier_Manifests"]["column_names"]
        self.assertIn("Pallet_Count", cols)
        self.assertIn("Gross_Weight_LBS", cols)

    def test_f10_02_physical_dimensions_tracked(self):
        """Verify Physical_Dimensions exists for freight space calculation."""
        cols = self.meta["tables"]["Carrier_Manifests"]["column_names"]
        self.assertIn("Physical_Dimensions", cols)

    def test_f10_03_waybill_and_tracking_number_tracked(self):
        """Verify Waybill_Number and Tracking_Number exist on manifests."""
        cols = self.meta["tables"]["Carrier_Manifests"]["column_names"]
        self.assertIn("Waybill_Number", cols)
        self.assertIn("Tracking_Number", cols)

    def test_f10_04_carrier_scac_and_service_level_tracked(self):
        """Verify SCAC_Code and Service_Level exist in Carrier_Master."""
        cols = self.meta["tables"]["Carrier_Master"]["column_names"]
        self.assertIn("SCAC_Code", cols)
        self.assertIn("Service_Level", cols)

    def test_f10_05_target_manifest_metrics_seeded_accurately(self):
        """Verify target manifest MNF-2026-8801 has realistic freight dimensions and weight."""
        cur = self.conn.cursor()
        cur.execute("SELECT Pallet_Count, Gross_Weight_LBS, Physical_Dimensions, Waybill_Number, Tracking_Number FROM Carrier_Manifests WHERE Manifest_ID = 'MNF-2026-8801'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["Pallet_Count"], 1)
        self.assertEqual(row["Gross_Weight_LBS"], 48.50)
        self.assertEqual(row["Physical_Dimensions"], "48x40x42 IN")
        self.assertEqual(row["Tracking_Number"], "TRK-AFX-9948201")
        self.assertEqual(row["Waybill_Number"], "WB-884102")


class TestF11TMSHandlingUnitLinking(unittest.TestCase):
    """F11: TMS Handling Unit Linking — Handling_Unit_Ref linking without cross-DB FK."""

    @classmethod
    def setUpClass(cls):
        cls.meta = parse_migration_metadata(MIGRATION_FILES["db-03-dev"])
        cls.conn = load_in_memory_db("db-03-dev")

    def test_f11_01_handling_unit_ref_in_carrier_manifests(self):
        """Verify Handling_Unit_Ref column exists on Carrier_Manifests."""
        cols = self.meta["tables"]["Carrier_Manifests"]["column_names"]
        self.assertIn("Handling_Unit_Ref", cols)

    def test_f11_02_handling_unit_ref_in_bill_of_lading(self):
        """Verify Handling_Unit_Ref column exists on Bill_Of_Lading."""
        cols = self.meta["tables"]["Bill_Of_Lading"]["column_names"]
        self.assertIn("Handling_Unit_Ref", cols)

    def test_f11_03_no_cross_database_fk_on_handling_unit_ref(self):
        """Verify Handling_Unit_Ref has NO foreign key constraint across databases."""
        fks = self.meta["tables"]["Carrier_Manifests"]["foreign_keys"]
        for fk in fks:
            self.assertNotEqual(
                fk["column"],
                "Handling_Unit_Ref",
                "Handling_Unit_Ref illegally has a foreign key constraint (cross-DB FK forbidden)",
            )

    def test_f11_04_target_manifest_links_to_hu8841plt(self):
        """Verify manifest MNF-2026-8801 links to Handling_Unit_Ref HU-8841-PLT."""
        cur = self.conn.cursor()
        cur.execute("SELECT Handling_Unit_Ref, Carrier_Name, Tracking_Number, Shipment_Status FROM Carrier_Manifests WHERE Handling_Unit_Ref = 'HU-8841-PLT'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["Carrier_Name"], "Apex Freight Express")
        self.assertEqual(row["Tracking_Number"], "TRK-AFX-9948201")
        self.assertEqual(row["Shipment_Status"], "IN_TRANSIT")

    def test_f11_05_bol_links_to_consignee_acme_corp(self):
        """Verify Bill_Of_Lading for HU-8841-PLT links to Consignee Acme Corp."""
        cur = self.conn.cursor()
        cur.execute("SELECT Consignee_Name, Delivery_Address FROM Bill_Of_Lading WHERE Handling_Unit_Ref = 'HU-8841-PLT'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertIn("Acme Corp", row["Consignee_Name"])
        self.assertIn("Austin, TX", row["Delivery_Address"])


class TestF12SQLMigrationScripts(unittest.TestCase):
    """F12: SQL Migration Scripts — organized DDL/DML scripts in migrations/."""

    def test_f12_01_all_three_migration_files_exist(self):
        """Verify db_01_erp.sql, db_02_wms.sql, and db_03_tms.sql all exist."""
        for db, path in MIGRATION_FILES.items():
            self.assertTrue(os.path.exists(path), f"Migration file missing for {db}: {path}")

    def test_f12_02_idempotent_drop_table_logic_present(self):
        """Verify each migration script includes idempotent drop logic."""
        for db, path in MIGRATION_FILES.items():
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("OBJECT_ID", content, f"{path} missing IF OBJECT_ID drop check")
            self.assertIn("DROP TABLE", content, f"{path} missing DROP TABLE statement")

    def test_f12_03_t_sql_batch_separators_used(self):
        """Verify GO batch separators are used for T-SQL migration batching."""
        for db, path in MIGRATION_FILES.items():
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("GO", content, f"{path} missing T-SQL GO batch separator")

    def test_f12_04_strict_schema_isolation_guarantee(self):
        """Verify no migration script queries or references another database catalog."""
        cross_db_terms = ["db-01-dev", "db-02-dev", "db-03-dev", "db_01", "db_02", "db_03"]
        for db, path in MIGRATION_FILES.items():
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line_no, line in enumerate(lines, 1):
                clean_line = re.sub(r"--.*$", "", line).strip()
                for term in cross_db_terms:
                    self.assertNotIn(
                        term,
                        clean_line,
                        f"Migration {path}:{line_no} illegally references foreign DB '{term}'",
                    )

    def test_f12_05_ddl_and_dml_sections_both_present(self):
        """Verify each migration script contains both CREATE TABLE and INSERT statements."""
        for db, path in MIGRATION_FILES.items():
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("CREATE TABLE", content, f"{path} missing CREATE TABLE")
            self.assertIn("INSERT INTO", content, f"{path} missing INSERT INTO")


class TestF13EntraIDMigrationRunner(unittest.TestCase):
    """F13: Entra ID Migration Runner — token auth, pytds driver, serverless retry."""

    def test_f13_01_entra_id_auth_scope_defined(self):
        """Verify Entra ID scope is https://database.windows.net/.default."""
        from mcp_servers.common.db import AZURE_SQL_RESOURCE_SCOPE
        self.assertEqual(AZURE_SQL_RESOURCE_SCOPE, "https://database.windows.net/.default")

    def test_f13_02_pytds_driver_version_compatible(self):
        """Verify python-tds (pytds) pure-Python TDS 7.4 driver is installed."""
        import pytds
        import importlib.metadata
        self.assertTrue(hasattr(pytds, "connect"))
        version = importlib.metadata.version("python-tds")
        self.assertEqual(version, "1.17.1")

    def test_f13_03_access_token_callable_interface_supported(self):
        """Verify pytds.connect signature supports access_token_callable."""
        import inspect
        import pytds
        sig = inspect.signature(pytds.connect)
        self.assertIn("access_token_callable", sig.parameters)

    def test_f13_04_serverless_wakeup_retry_error_codes(self):
        """Verify retry logic handles Azure SQL serverless auto-wake error code 40613."""
        from mcp_servers.common.db import get_db_connection
        import inspect
        src = inspect.getsource(get_db_connection)
        self.assertIn("40613", src)
        self.assertIn("not currently available", src)

    def test_f13_05_target_server_hostname_configured(self):
        """Verify target server defaults to eosr-db-server.database.windows.net."""
        from mcp_servers.common.db import get_db_connection
        import inspect
        src = inspect.getsource(get_db_connection)
        self.assertIn("eosr-db-server.database.windows.net", src)


class TestF14CrossDBVerificationLogic(unittest.TestCase):
    """F14: Cross-DB Verification Script Logic — 3-hop join query (ERP -> WMS -> TMS)."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_f14_01_stage1_erp_order_resolution(self):
        """Step 1: Resolve customer 'Acme Corp' and item '%Laptop%' to order SO-10045."""
        cur = self.conn_erp.cursor()
        cur.execute("""
            SELECT o.Order_ID, o.PO_Number, o.OrderStatus
            FROM tbl_Customers c
            JOIN tbl_SalesOrders o ON c.Cust_ID = o.Cust_ID
            JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
            JOIN tbl_Inventory_Master i ON l.Item_SKU = i.Item_SKU
            WHERE c.Cust_Name = 'Acme Corp'
              AND (i.Item_Description LIKE '%Laptop%' OR l.Item_SKU LIKE '%LAPTOP%')
              AND o.OrderStatus <> 'Cancelled'
            ORDER BY o.Total_Amount DESC
        """)
        rows = cur.fetchall()
        self.assertGreaterEqual(len(rows), 1)
        target = rows[0]
        self.assertEqual(target["Order_ID"], "SO-10045")
        self.assertEqual(target["OrderStatus"], "Completed")

    def test_f14_02_stage2_wms_pick_and_hu_resolution(self):
        """Step 2: Resolve erp_order_ref 'SO-10045' in WMS to pick PK-8801 and HU-8841-PLT."""
        cur = self.conn_wms.cursor()
        cur.execute("""
            SELECT pick_id, status_id, handling_unit_id, staged_dock_code
            FROM outbound_picks
            LEFT JOIN handling_units ON outbound_picks.handling_unit_id = handling_units.hu_id
            WHERE erp_order_ref = 'SO-10045'
        """)
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["pick_id"], "PK-8801")
        self.assertEqual(row["status_id"], 5)  # Loaded
        self.assertEqual(row["handling_unit_id"], "HU-8841-PLT")
        self.assertEqual(row["staged_dock_code"], "DOCK-04")

    def test_f14_03_stage3_tms_carrier_and_tracking_resolution(self):
        """Step 3: Resolve Handling_Unit_Ref 'HU-8841-PLT' in TMS to carrier and tracking number."""
        cur = self.conn_tms.cursor()
        cur.execute("""
            SELECT m.Carrier_Name, m.Tracking_Number, m.Waybill_Number, m.Shipment_Status, m.Dispatched_At
            FROM Carrier_Manifests m
            JOIN Bill_Of_Lading bol ON m.BOL_Number = bol.BOL_Number
            WHERE m.Handling_Unit_Ref = 'HU-8841-PLT'
        """)
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["Carrier_Name"], "Apex Freight Express")
        self.assertEqual(row["Tracking_Number"], "TRK-AFX-9948201")
        self.assertEqual(row["Waybill_Number"], "WB-884102")
        self.assertEqual(row["Shipment_Status"], "IN_TRANSIT")
        self.assertIsNotNone(row["Dispatched_At"])

    def test_f14_04_confirmed_ground_truth_shipped_status(self):
        """Verify the synthesized business status conclusively proves the laptop order HAS SHIPPED."""
        # 1. ERP order is Completed
        cur_erp = self.conn_erp.cursor()
        cur_erp.execute("SELECT OrderStatus FROM tbl_SalesOrders WHERE Order_ID = 'SO-10045'")
        self.assertEqual(cur_erp.fetchone()["OrderStatus"], "Completed")

        # 2. WMS physical status is Loaded (5)
        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT status_id FROM outbound_picks WHERE erp_order_ref = 'SO-10045'")
        self.assertEqual(cur_wms.fetchone()["status_id"], 5)

        # 3. TMS transport status is IN_TRANSIT with valid tracking
        cur_tms = self.conn_tms.cursor()
        cur_tms.execute("SELECT Shipment_Status, Tracking_Number, Dispatched_At FROM Carrier_Manifests WHERE Handling_Unit_Ref = 'HU-8841-PLT'")
        tms_row = cur_tms.fetchone()
        self.assertEqual(tms_row["Shipment_Status"], "IN_TRANSIT")
        self.assertTrue(tms_row["Tracking_Number"].startswith("TRK-"))
        self.assertIsNotNone(tms_row["Dispatched_At"])

    def test_f14_05_cross_domain_synthesis_without_federated_queries(self):
        """Verify 3-step synthesis executes as autonomous single-DB queries without distributed joins."""
        # Query 1 against ERP only
        erp_res = self.conn_erp.execute("SELECT Order_ID FROM tbl_SalesOrders WHERE Order_ID = 'SO-10045'").fetchone()
        order_key = erp_res[0]

        # Query 2 against WMS only using order_key string
        wms_res = self.conn_wms.execute(f"SELECT handling_unit_id FROM outbound_picks WHERE erp_order_ref = '{order_key}'").fetchone()
        hu_key = wms_res[0]

        # Query 3 against TMS only using hu_key string
        tms_res = self.conn_tms.execute(f"SELECT Tracking_Number FROM Carrier_Manifests WHERE Handling_Unit_Ref = '{hu_key}'").fetchone()
        self.assertEqual(tms_res[0], "TRK-AFX-9948201")


class TestF15AdversarialDistractorSuite(unittest.TestCase):
    """F15: Adversarial Distractor Suite — verifies isolation of DIST-1 through DIST-6."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_f15_01_dist1_wrong_product_isolation(self):
        """DIST-1: Acme Corp ordered Chairs (SO-10046) -> status 2 (Picked on cart), NOT in TMS."""
        # WMS check
        wms_row = self.conn_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10046'").fetchone()
        self.assertEqual(wms_row["status_id"], 2)  # Picked
        hu_id = wms_row["handling_unit_id"]

        # TMS check: should NOT exist in Carrier_Manifests
        tms_row = self.conn_tms.execute(f"SELECT COUNT(*) FROM Carrier_Manifests WHERE Handling_Unit_Ref = '{hu_id}'").fetchone()
        self.assertEqual(tms_row[0], 0, "DIST-1 chairs must not be manifested in TMS")

    def test_f15_02_dist2_wrong_customer_isolation(self):
        """DIST-2: Globex Corp ordered Laptops (SO-10047) -> Delivered to Globex, NOT Acme."""
        # ERP check: Customer is Globex
        erp_row = self.conn_erp.execute("""
            SELECT c.Cust_Name FROM tbl_Customers c JOIN tbl_SalesOrders o ON c.Cust_ID = o.Cust_ID WHERE o.Order_ID = 'SO-10047'
        """).fetchone()
        self.assertEqual(erp_row["Cust_Name"], "Globex Corporation")

        # TMS check: Consignee in BOL is Globex
        bol_row = self.conn_tms.execute("SELECT Consignee_Name FROM Bill_Of_Lading WHERE Handling_Unit_Ref = 'HU-8843-PLT'").fetchone()
        self.assertIn("Globex", bol_row["Consignee_Name"])

    def test_f15_03_dist3_cancelled_order_isolation(self):
        """DIST-3: Cancelled Acme Laptop Order (SO-10012) -> status 9 in WMS, NULL HU, NOT in TMS."""
        erp_row = self.conn_erp.execute("SELECT OrderStatus FROM tbl_SalesOrders WHERE Order_ID = 'SO-10012'").fetchone()
        self.assertEqual(erp_row["OrderStatus"], "Cancelled")

        wms_row = self.conn_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10012'").fetchone()
        self.assertEqual(wms_row["status_id"], 9)
        self.assertIsNone(wms_row["handling_unit_id"])

    def test_f15_04_dist4_staged_at_dock_not_shipped(self):
        """DIST-4: Acme Corp Laptops Staged (SO-10048) -> status 4 in WMS, PENDING_PICKUP in TMS, Dispatched_At is NULL."""
        wms_row = self.conn_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10048'").fetchone()
        self.assertEqual(wms_row["status_id"], 4)  # Staged at Dock

        tms_row = self.conn_tms.execute("SELECT Shipment_Status, Dispatched_At FROM Carrier_Manifests WHERE Handling_Unit_Ref = 'HU-8844-PLT'").fetchone()
        self.assertEqual(tms_row["Shipment_Status"], "PENDING_PICKUP")
        self.assertIsNone(tms_row["Dispatched_At"], "DIST-4 Dispatched_At must be NULL (not departed)")

    def test_f15_05_dist5_allocated_only_isolation(self):
        """DIST-5: Umbrella Corp Laptops (SO-10049) -> status 1 in WMS, NO HU, NOT in TMS."""
        wms_row = self.conn_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10049'").fetchone()
        self.assertEqual(wms_row["status_id"], 1)  # Allocated
        self.assertIsNone(wms_row["handling_unit_id"])

    def test_f15_06_dist6_background_noise_isolation(self):
        """DIST-6: Initech Monitors (SO-10050) -> separate customer, separate SKU, shared trailer."""
        erp_row = self.conn_erp.execute("""
            SELECT c.Cust_Name, l.Item_SKU FROM tbl_Customers c
            JOIN tbl_SalesOrders o ON c.Cust_ID = o.Cust_ID
            JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
            WHERE o.Order_ID = 'SO-10050'
        """).fetchone()
        self.assertEqual(erp_row["Cust_Name"], "Initech LLC")
        self.assertEqual(erp_row["Item_SKU"], "SKU-MONITOR-27-UHD")


if __name__ == "__main__":
    unittest.main()
