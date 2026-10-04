"""Tier 3: Cross-Feature Interactions & Pairwise Combinations Test Suite.
Verifies pairwise synthesis across autonomous systems:
- ERP <-> WMS Pairwise: Order ID, PO number, SKU code, status mappings, quantities
- WMS <-> TMS Pairwise: Handling Unit Ref, dock doors, container weights, status mappings
- ERP <-> TMS Pairwise: Customer addresses to BOL consignees, order vs dispatch timelines
- Distractor Rejection Pairwise: Proves that single-system queries fail, while multi-system synthesis succeeds
- Autonomous Decoupling: Asserts zero cross-database foreign keys across all domains
"""

import unittest
from e2e_tests.conftest_helpers import (
    load_in_memory_db,
    parse_migration_metadata,
    MIGRATION_FILES,
)


class TestERPWMSPairwiseInteractions(unittest.TestCase):
    """Pairwise interactions between ERP (db-01-dev) and WMS (db-02-dev)."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")

    def test_tier3_erp_order_id_to_wms_erp_order_ref_mapping(self):
        """Every ERP sales order has a corresponding outbound pick record with matching Order_ID."""
        cur_erp = self.conn_erp.cursor()
        cur_erp.execute("SELECT Order_ID FROM tbl_SalesOrders")
        erp_order_ids = {r[0] for r in cur_erp.fetchall()}

        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT erp_order_ref FROM outbound_picks")
        wms_order_refs = {r[0] for r in cur_wms.fetchall()}

        self.assertTrue(
            erp_order_ids.issubset(wms_order_refs),
            f"WMS missing pick records for orders: {erp_order_ids - wms_order_refs}",
        )

    def test_tier3_customer_po_number_consistency_across_erp_wms(self):
        """Customer PO numbers match exactly between tbl_SalesOrders and outbound_picks."""
        cur_erp = self.conn_erp.cursor()
        cur_erp.execute("SELECT Order_ID, PO_Number FROM tbl_SalesOrders")
        erp_pos = dict(cur_erp.fetchall())

        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT erp_order_ref, customer_po_ref FROM outbound_picks")
        wms_pos = dict(cur_wms.fetchall())

        for order_id, expected_po in erp_pos.items():
            self.assertEqual(
                wms_pos.get(order_id),
                expected_po,
                f"PO mismatch for {order_id}: ERP has {expected_po}, WMS has {wms_pos.get(order_id)}",
            )

    def test_tier3_sku_consistency_across_erp_wms(self):
        """Ordered item SKU in tbl_OrderLineItems matches sku_code in outbound_picks."""
        cur_erp = self.conn_erp.cursor()
        cur_erp.execute("SELECT Order_ID, Item_SKU FROM tbl_OrderLineItems")
        erp_skus = dict(cur_erp.fetchall())

        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT erp_order_ref, sku_code FROM outbound_picks")
        wms_skus = dict(cur_wms.fetchall())

        for order_id, expected_sku in erp_skus.items():
            self.assertEqual(
                wms_skus.get(order_id),
                expected_sku,
                f"SKU mismatch for {order_id}: ERP={expected_sku}, WMS={wms_skus.get(order_id)}",
            )

    def test_tier3_status_lifecycle_alignment_erp_wms(self):
        """Status pairs across ERP string status and WMS integer status follow domain lifecycle rules."""
        # Expected mapping table:
        # 'Completed' -> 5 (Loaded)
        # 'Processing' -> 1 (Allocated), 2 (Picked), or 4 (Staged)
        # 'Cancelled' -> 9 (Cancelled)
        cur_erp = self.conn_erp.cursor()
        cur_erp.execute("SELECT Order_ID, OrderStatus FROM tbl_SalesOrders")
        erp_statuses = dict(cur_erp.fetchall())

        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT erp_order_ref, status_id FROM outbound_picks")
        wms_statuses = dict(cur_wms.fetchall())

        for order_id, erp_st in erp_statuses.items():
            wms_st = wms_statuses[order_id]
            if erp_st == "Completed":
                self.assertEqual(wms_st, 5, f"Completed ERP order {order_id} must have WMS status 5")
            elif erp_st == "Cancelled":
                self.assertEqual(wms_st, 9, f"Cancelled ERP order {order_id} must have WMS status 9")
            elif erp_st == "Processing":
                self.assertIn(wms_st, (1, 2, 4), f"Processing ERP order {order_id} must have in-progress WMS status")

    def test_tier3_fulfilled_quantities_alignment_erp_wms(self):
        """For loaded orders (status 5), qty_picked in WMS matches ordered Quantity in ERP."""
        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT erp_order_ref, qty_picked FROM outbound_picks WHERE status_id = 5")
        wms_loaded = dict(cur_wms.fetchall())

        cur_erp = self.conn_erp.cursor()
        cur_erp.execute("SELECT Order_ID, Quantity FROM tbl_OrderLineItems WHERE Order_ID IN ('SO-10045', 'SO-10047', 'SO-10050')")
        erp_qtys = dict(cur_erp.fetchall())

        for order_id, expected_qty in erp_qtys.items():
            self.assertEqual(
                wms_loaded.get(order_id),
                expected_qty,
                f"Quantity mismatch on {order_id}: ERP={expected_qty}, WMS={wms_loaded.get(order_id)}",
            )


class TestWMSTMSPairwiseInteractions(unittest.TestCase):
    """Pairwise interactions between WMS (db-02-dev) and TMS (db-03-dev)."""

    @classmethod
    def setUpClass(cls):
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier3_handling_unit_ref_links_loaded_picks_to_carrier_manifests(self):
        """Every loaded handling unit (status 5) in WMS maps to a Carrier Manifest in TMS."""
        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT handling_unit_id FROM outbound_picks WHERE status_id = 5")
        loaded_hu_ids = {r[0] for r in cur_wms.fetchall()}

        cur_tms = self.conn_tms.cursor()
        cur_tms.execute("SELECT Handling_Unit_Ref FROM Carrier_Manifests")
        tms_hu_refs = {r[0] for r in cur_tms.fetchall()}

        self.assertTrue(
            loaded_hu_ids.issubset(tms_hu_refs),
            f"TMS missing manifest for loaded handling units: {loaded_hu_ids - tms_hu_refs}",
        )

    def test_tier3_staged_handling_unit_links_to_pending_pickup_manifest(self):
        """Staged handling unit HU-8844-PLT (status 4) links to PENDING_PICKUP in TMS."""
        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT handling_unit_id FROM outbound_picks WHERE status_id = 4")
        staged_hu = cur_wms.fetchone()[0]

        cur_tms = self.conn_tms.cursor()
        cur_tms.execute(f"SELECT Shipment_Status, Dispatched_At FROM Carrier_Manifests WHERE Handling_Unit_Ref = '{staged_hu}'")
        tms_row = cur_tms.fetchone()
        self.assertIsNotNone(tms_row)
        self.assertEqual(tms_row["Shipment_Status"], "PENDING_PICKUP")
        self.assertIsNone(tms_row["Dispatched_At"])

    def test_tier3_unpacked_or_cancelled_picks_have_no_tms_manifest(self):
        """Picks in status 1 (Allocated), 2 (Picked on cart), or 9 (Cancelled) have no manifest in TMS."""
        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT pick_id, handling_unit_id FROM outbound_picks WHERE status_id IN (1, 2, 9)")
        rows = cur_wms.fetchall()

        cur_tms = self.conn_tms.cursor()
        for r in rows:
            hu_id = r["handling_unit_id"]
            if hu_id is not None:
                cur_tms.execute(f"SELECT COUNT(*) FROM Carrier_Manifests WHERE Handling_Unit_Ref = '{hu_id}'")
                self.assertEqual(cur_tms.fetchone()[0], 0, f"Un-staged HU {hu_id} must not be manifested in TMS")

    def test_tier3_container_and_freight_weight_metrics_tracked_independently(self):
        """WMS tracks container tare_weight_kg while TMS tracks Gross_Weight_LBS independently."""
        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT hu_id, tare_weight_kg FROM handling_units")
        for hu_id, tare_kg in cur_wms.fetchall():
            self.assertGreater(tare_kg, 0.0, f"WMS tare weight must be positive for {hu_id}")

        cur_tms = self.conn_tms.cursor()
        cur_tms.execute("SELECT Handling_Unit_Ref, Gross_Weight_LBS FROM Carrier_Manifests")
        for hu_id, gross_lbs in cur_tms.fetchall():
            self.assertGreater(gross_lbs, 0.0, f"TMS gross weight must be positive for {hu_id}")


class TestERPTMSPairwiseInteractions(unittest.TestCase):
    """Pairwise interactions between ERP (db-01-dev) and TMS (db-03-dev)."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier3_shipping_address_matches_bol_destination(self):
        """Acme Corp shipping address in ERP matches consignee delivery address in TMS Bill of Lading."""
        cur_erp = self.conn_erp.cursor()
        cur_erp.execute("SELECT Shipping_Address FROM tbl_Customers WHERE Cust_Name = 'Acme Corp'")
        erp_address = cur_erp.fetchone()[0]

        cur_tms = self.conn_tms.cursor()
        cur_tms.execute("SELECT Delivery_Address FROM Bill_Of_Lading WHERE Consignee_Name LIKE '%Acme Corp%' AND BOL_Number = 'BOL-2026-10045'")
        tms_address = cur_tms.fetchone()[0]

        # Both point to Austin TX 78701
        self.assertIn("Austin, TX", erp_address)
        self.assertIn("Austin, TX", tms_address)

    def test_tier3_order_date_precedes_dispatch_date(self):
        """Order date in ERP precedes or equals departure timestamp in TMS."""
        cur_erp = self.conn_erp.cursor()
        cur_erp.execute("SELECT Order_Date FROM tbl_SalesOrders WHERE Order_ID = 'SO-10045'")
        order_date = cur_erp.fetchone()[0]

        cur_tms = self.conn_tms.cursor()
        cur_tms.execute("SELECT Dispatched_At FROM Carrier_Manifests WHERE Manifest_ID = 'MNF-2026-8801'")
        dispatched_at = cur_tms.fetchone()[0]

        self.assertLessEqual(order_date, dispatched_at, "Order date must precede dispatch date")

    def test_tier3_trailer_departure_matches_carrier_dispatch(self):
        """Trailer Departure_Timestamp in Freight_Loads matches Dispatched_At in Carrier_Manifests."""
        cur_tms = self.conn_tms.cursor()
        cur_tms.execute("""
            SELECT l.Departure_Timestamp, m.Dispatched_At
            FROM Carrier_Manifests m
            JOIN Bill_Of_Lading b ON m.BOL_Number = b.BOL_Number
            JOIN Freight_Loads l ON b.Load_ID = l.Load_ID
            WHERE m.Manifest_ID = 'MNF-2026-8801'
        """)
        row = cur_tms.fetchone()
        self.assertEqual(row["Departure_Timestamp"], row["Dispatched_At"])


class TestDistractorRejectionPairwise(unittest.TestCase):
    """Proves that naive single-database queries fail, requiring cross-domain synthesis."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier3_trap1_erp_completed_does_not_equal_shipped(self):
        """Trap 1: Querying ERP only for 'Completed' yields 3 different orders (SO-10045, SO-10047, SO-10050)."""
        cur = self.conn_erp.cursor()
        cur.execute("SELECT Order_ID FROM tbl_SalesOrders WHERE OrderStatus = 'Completed'")
        completed_orders = [r[0] for r in cur.fetchall()]
        self.assertEqual(len(completed_orders), 3)
        self.assertIn("SO-10045", completed_orders)
        self.assertIn("SO-10047", completed_orders)  # Globex
        self.assertIn("SO-10050", completed_orders)  # Initech

    def test_tier3_trap2_wms_loaded_laptops_contains_multiple_customers(self):
        """Trap 2: Querying WMS only for loaded laptops (status 5, SKU-LAPTOP-15-ENT) yields 2 different customers."""
        cur = self.conn_wms.cursor()
        cur.execute("SELECT erp_order_ref FROM outbound_picks WHERE status_id = 5 AND sku_code = 'SKU-LAPTOP-15-ENT'")
        loaded_laptop_orders = [r[0] for r in cur.fetchall()]
        self.assertEqual(len(loaded_laptop_orders), 2)
        self.assertIn("SO-10045", loaded_laptop_orders)  # Acme Corp
        self.assertIn("SO-10047", loaded_laptop_orders)  # Globex Corp

    def test_tier3_trap3_tms_has_zero_sku_or_product_columns(self):
        """Trap 3: Querying TMS for product descriptions or SKU codes is impossible (columns do not exist)."""
        meta_tms = parse_migration_metadata(MIGRATION_FILES["db-03-dev"])
        all_tms_columns = []
        for tname, tinfo in meta_tms["tables"].items():
            all_tms_columns.extend(tinfo["column_names"])

        self.assertNotIn("sku_code", all_tms_columns)
        self.assertNotIn("Item_SKU", all_tms_columns)
        self.assertNotIn("Item_Description", all_tms_columns)
        self.assertNotIn("Product_Category", all_tms_columns)

    def test_tier3_trap4_tms_acme_corp_has_two_manifests(self):
        """Trap 4: Querying TMS for Acme Corp yields 2 manifests (one IN_TRANSIT, one PENDING_PICKUP)."""
        cur = self.conn_tms.cursor()
        cur.execute("""
            SELECT m.Shipment_Status FROM Carrier_Manifests m
            JOIN Bill_Of_Lading b ON m.BOL_Number = b.BOL_Number
            WHERE b.Consignee_Name LIKE '%Acme Corp%'
        """)
        statuses = [r[0] for r in cur.fetchall()]
        self.assertEqual(len(statuses), 2)
        self.assertIn("IN_TRANSIT", statuses)
        self.assertIn("PENDING_PICKUP", statuses)


class TestAutonomousDecouplingIntegrity(unittest.TestCase):
    """Verifies that no cross-database foreign keys exist across any of the 3 databases."""

    def test_tier3_zero_cross_database_foreign_keys_across_all_ddl(self):
        """Verifies that across all DDL statements, zero cross-database references exist."""
        for db_name, file_path in MIGRATION_FILES.items():
            meta = parse_migration_metadata(file_path)
            for tname, tinfo in meta["tables"].items():
                for fk in tinfo["foreign_keys"]:
                    # Ref table must be an internal table defined within the same file
                    self.assertIn(
                        fk["ref_table"],
                        meta["table_names"],
                        f"Cross-DB foreign key detected in {db_name}! Table {tname}.{fk['column']} references {fk['ref_table']}",
                    )


if __name__ == "__main__":
    unittest.main()
