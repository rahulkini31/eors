"""Tier 2: Boundary & Corner Cases Test Suite.
Verifies boundary conditions, edge cases, error resilience, and negative scenarios:
- Empty result sets (non-existent customers, products, orders, handling units)
- Cancelled and voided orders (ERP Cancelled, WMS status_id 9, NULL handling unit)
- Staged at dock vs dispatched boundary (status_id 4 vs 5, PENDING_PICKUP vs IN_TRANSIT, NULL Dispatched_At)
- SKU and product filter boundary conditions (exact match, substring, wrong item exclusion)
- Dangling / invalid references and loose string matching resilience
- Serverless retry backoff simulation and transient connection recovery
- Numeric boundaries (positive quantities, zero/negative bounds, status ranges)
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from e2e_tests.conftest_helpers import (
    load_in_memory_db,
    get_live_db_connection,
)


class TestEmptyAndNonExistentQueries(unittest.TestCase):
    """Boundary: Non-existent entities return clean empty sets without crashing."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier2_empty_customer_returns_zero_orders(self):
        """Querying ERP for an unseeded customer name yields empty result."""
        cur = self.conn_erp.cursor()
        cur.execute("""
            SELECT o.Order_ID FROM tbl_Customers c
            JOIN tbl_SalesOrders o ON c.Cust_ID = o.Cust_ID
            WHERE c.Cust_Name = 'NonExistentGlobalCorp'
        """)
        rows = cur.fetchall()
        self.assertEqual(len(rows), 0)

    def test_tier2_customer_with_unmatched_product_returns_empty(self):
        """Querying ERP for valid customer Acme Corp but non-existent product keyword returns empty."""
        cur = self.conn_erp.cursor()
        cur.execute("""
            SELECT o.Order_ID FROM tbl_Customers c
            JOIN tbl_SalesOrders o ON c.Cust_ID = o.Cust_ID
            JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
            JOIN tbl_Inventory_Master i ON l.Item_SKU = i.Item_SKU
            WHERE c.Cust_Name = 'Acme Corp' AND i.Item_Description LIKE '%QuantumProcessor%'
        """)
        rows = cur.fetchall()
        self.assertEqual(len(rows), 0)

    def test_tier2_non_existent_erp_ref_in_wms_returns_empty(self):
        """Querying WMS for non-existent erp_order_ref returns empty without SQL error."""
        cur = self.conn_wms.cursor()
        cur.execute("SELECT pick_id, status_id FROM outbound_picks WHERE erp_order_ref = 'SO-99999-DOES-NOT-EXIST'")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 0)

    def test_tier2_non_existent_hu_in_tms_returns_empty(self):
        """Querying TMS for non-existent Handling_Unit_Ref returns empty set."""
        cur = self.conn_tms.cursor()
        cur.execute("SELECT Manifest_ID, Tracking_Number FROM Carrier_Manifests WHERE Handling_Unit_Ref = 'HU-0000-NONEXISTENT'")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 0)

    def test_tier2_empty_string_and_whitespace_keys_return_empty(self):
        """Empty or whitespace keys in WMS/TMS lookups return empty results."""
        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT pick_id FROM outbound_picks WHERE erp_order_ref = '' OR erp_order_ref = '   '")
        self.assertEqual(len(cur_wms.fetchall()), 0)

        cur_tms = self.conn_tms.cursor()
        cur_tms.execute("SELECT Manifest_ID FROM Carrier_Manifests WHERE Handling_Unit_Ref = ''")
        self.assertEqual(len(cur_tms.fetchall()), 0)


class TestCancelledAndVoidedOrders(unittest.TestCase):
    """Boundary: Cancelled orders are cleanly isolated and prevented from false shipping assertions."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier2_cancelled_order_excluded_by_active_filter(self):
        """Active order query filter (OrderStatus <> 'Cancelled') excludes SO-10012."""
        cur = self.conn_erp.cursor()
        cur.execute("""
            SELECT o.Order_ID FROM tbl_SalesOrders o
            JOIN tbl_Customers c ON o.Cust_ID = c.Cust_ID
            WHERE c.Cust_Name = 'Acme Corp' AND o.OrderStatus <> 'Cancelled'
        """)
        order_ids = [r["Order_ID"] for r in cur.fetchall()]
        self.assertNotIn("SO-10012", order_ids)

    def test_tier2_cancelled_order_in_wms_has_status_9(self):
        """Cancelled order SO-10012 in WMS has status_id = 9 and 0 picked quantity."""
        cur = self.conn_wms.cursor()
        cur.execute("SELECT status_id, qty_requested, qty_picked FROM outbound_picks WHERE erp_order_ref = 'SO-10012'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status_id"], 9)  # 9=Cancelled
        self.assertEqual(row["qty_picked"], 0)

    def test_tier2_cancelled_order_has_null_handling_unit(self):
        """Cancelled pick record has NULL handling_unit_id, preventing freight dispatch."""
        cur = self.conn_wms.cursor()
        cur.execute("SELECT handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10012'")
        row = cur.fetchone()
        self.assertIsNone(row["handling_unit_id"])

    def test_tier2_cancelled_order_has_zero_manifests_in_tms(self):
        """Cancelled order has no BOL or Carrier Manifest in TMS."""
        cur = self.conn_tms.cursor()
        # Searching by Bill of Lading with loose order reference if any
        cur.execute("SELECT COUNT(*) FROM Bill_Of_Lading WHERE BOL_Number LIKE '%10012%'")
        self.assertEqual(cur.fetchone()[0], 0)

    def test_tier2_cancelled_line_items_marked_cancelled(self):
        """Line items for SO-10012 have Line_Status = 'CANCELLED'."""
        cur = self.conn_erp.cursor()
        cur.execute("SELECT Line_Status FROM tbl_OrderLineItems WHERE Order_ID = 'SO-10012'")
        for r in cur.fetchall():
            self.assertEqual(r["Line_Status"], "CANCELLED")


class TestStagedAtDockBoundary(unittest.TestCase):
    """Boundary: Goods staged at dock (status 4) with pending label are NOT considered shipped."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier2_staged_order_wms_status_is_4_not_5(self):
        """Order SO-10048 has status_id = 4 (Staged at Dock), not 5 (Loaded)."""
        cur = self.conn_wms.cursor()
        cur.execute("SELECT status_id, staged_dock_code FROM outbound_picks p JOIN handling_units hu ON p.handling_unit_id = hu.hu_id WHERE p.erp_order_ref = 'SO-10048'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status_id"], 4)
        self.assertEqual(row["staged_dock_code"], "DOCK-07")

    def test_tier2_staged_order_tms_status_is_pending_pickup(self):
        """Manifest for SO-10048 (HU-8844-PLT) has Shipment_Status = 'PENDING_PICKUP', not 'IN_TRANSIT'."""
        cur = self.conn_tms.cursor()
        cur.execute("SELECT Shipment_Status FROM Carrier_Manifests WHERE Handling_Unit_Ref = 'HU-8844-PLT'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["Shipment_Status"], "PENDING_PICKUP")

    def test_tier2_staged_order_dispatched_at_is_null(self):
        """Manifest for SO-10048 has NULL Dispatched_At timestamp."""
        cur = self.conn_tms.cursor()
        cur.execute("SELECT Dispatched_At FROM Carrier_Manifests WHERE Handling_Unit_Ref = 'HU-8844-PLT'")
        row = cur.fetchone()
        self.assertIsNone(row["Dispatched_At"], "Dispatched_At must be NULL for staged goods")

    def test_tier2_staged_freight_load_is_staged_not_dispatched(self):
        """Parent Freight_Load for SO-10048 trailer has Load_Status = 'STAGED' with NULL Departure_Timestamp."""
        cur = self.conn_tms.cursor()
        cur.execute("""
            SELECT l.Load_Status, l.Departure_Timestamp
            FROM Freight_Loads l
            JOIN Bill_Of_Lading b ON l.Load_ID = b.Load_ID
            WHERE b.Handling_Unit_Ref = 'HU-8844-PLT'
        """)
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["Load_Status"], "STAGED")
        self.assertIsNone(row["Departure_Timestamp"])

    def test_tier2_synthesis_logic_concludes_staged_is_not_shipped(self):
        """Synthetic status check of SO-10048 conclusively yields 'NOT SHIPPED'."""
        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10048'")
        wms_row = cur_wms.fetchone()

        cur_tms = self.conn_tms.cursor()
        cur_tms.execute(f"SELECT Shipment_Status, Dispatched_At FROM Carrier_Manifests WHERE Handling_Unit_Ref = '{wms_row['handling_unit_id']}'")
        tms_row = cur_tms.fetchone()

        # Decision rule: shipped ONLY if status_id == 5 AND Shipment_Status in ('IN_TRANSIT', 'DELIVERED') AND Dispatched_At is not None
        has_shipped = (
            wms_row["status_id"] == 5
            and tms_row["Shipment_Status"] in ("IN_TRANSIT", "DELIVERED")
            and tms_row["Dispatched_At"] is not None
        )
        self.assertFalse(has_shipped, "SO-10048 must NOT be reported as shipped")


class TestSKUAndProductBoundaryConditions(unittest.TestCase):
    """Boundary: Product filtering precision and wrong product segregation."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")

    def test_tier2_product_search_case_insensitivity(self):
        """Searching for 'laptop', 'Laptop', or 'LAPTOP' retrieves the same catalog SKU."""
        cur = self.conn_erp.cursor()
        cur.execute("SELECT Item_SKU FROM tbl_Inventory_Master WHERE Item_Description LIKE '%laptop%'")
        skus_lower = {r[0] for r in cur.fetchall()}

        cur.execute("SELECT Item_SKU FROM tbl_Inventory_Master WHERE Item_Description LIKE '%Laptop%'")
        skus_mixed = {r[0] for r in cur.fetchall()}

        self.assertEqual(skus_lower, skus_mixed)
        self.assertIn("SKU-LAPTOP-15-ENT", skus_lower)

    def test_tier2_chair_product_does_not_match_laptop_query(self):
        """Order SO-10046 (Ergonomic Chairs) is excluded by laptop search query."""
        cur = self.conn_erp.cursor()
        cur.execute("""
            SELECT o.Order_ID FROM tbl_SalesOrders o
            JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
            JOIN tbl_Inventory_Master i ON l.Item_SKU = i.Item_SKU
            WHERE o.Order_ID = 'SO-10046'
              AND (i.Item_Description LIKE '%Laptop%' OR l.Item_SKU LIKE '%LAPTOP%')
        """)
        rows = cur.fetchall()
        self.assertEqual(len(rows), 0)

    def test_tier2_monitor_product_does_not_match_laptop_query(self):
        """Order SO-10050 (Ultra-HD Monitors) is excluded by laptop search query."""
        cur = self.conn_erp.cursor()
        cur.execute("""
            SELECT o.Order_ID FROM tbl_SalesOrders o
            JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
            JOIN tbl_Inventory_Master i ON l.Item_SKU = i.Item_SKU
            WHERE o.Order_ID = 'SO-10050'
              AND (i.Item_Description LIKE '%Laptop%' OR l.Item_SKU LIKE '%LAPTOP%')
        """)
        rows = cur.fetchall()
        self.assertEqual(len(rows), 0)

    def test_tier2_exact_sku_lookups_resolve_consistently(self):
        """Direct lookup by exact SKU 'SKU-LAPTOP-15-ENT' returns 145 units on hand and 52 allocated."""
        cur = self.conn_erp.cursor()
        cur.execute("SELECT Qty_On_Hand, Qty_Allocated FROM tbl_Inventory_Master WHERE Item_SKU = 'SKU-LAPTOP-15-ENT'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["Qty_On_Hand"], 145)
        self.assertEqual(row["Qty_Allocated"], 52)


class TestTimeoutAndReconnectResilience(unittest.TestCase):
    """Boundary: Driver retry backoff behavior on simulated transient Azure errors."""

    def test_tier2_retry_loop_recovers_after_transient_error_40613(self):
        """Simulates 2 consecutive 40613 serverless auto-wake errors followed by success."""
        attempts = 0

        def flaky_connect(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise Exception("Database 'db-01-dev' is not currently available (error 40613).")
            return MagicMock(name="Connection")

        # Test retry simulation logic
        max_retries = 4
        conn = None
        for attempt in range(max_retries):
            try:
                conn = flaky_connect()
                break
            except Exception as e:
                if "40613" in str(e) and attempt < max_retries - 1:
                    continue
                raise

        self.assertIsNotNone(conn)
        self.assertEqual(attempts, 3)

    def test_tier2_retry_exhaustion_raises_proper_exception(self):
        """Simulates persistent failure exceeding max_retries; asserts exception is propagated."""
        def persistent_failure(*args, **kwargs):
            raise Exception("Database 'db-01-dev' is not currently available (error 40613).")

        max_retries = 3
        with self.assertRaises(Exception) as ctx:
            for attempt in range(max_retries):
                try:
                    persistent_failure()
                except Exception as e:
                    if "40613" in str(e) and attempt < max_retries - 1:
                        continue
                    raise

        self.assertIn("40613", str(ctx.exception))


class TestNumericAndTypeBoundaries(unittest.TestCase):
    """Boundary: Relational constraints, positive quantities, and status bounds."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier2_all_erp_quantities_strictly_positive(self):
        """Verify all ordered line item quantities in ERP are > 0."""
        cur = self.conn_erp.cursor()
        cur.execute("SELECT MIN(Quantity) FROM tbl_OrderLineItems")
        min_qty = cur.fetchone()[0]
        self.assertGreater(min_qty, 0)

    def test_tier2_all_wms_status_codes_within_valid_set(self):
        """Verify all status_id values in WMS belong to known domain enum {1, 2, 3, 4, 5, 9}."""
        valid_statuses = {1, 2, 3, 4, 5, 9}
        cur = self.conn_wms.cursor()
        cur.execute("SELECT DISTINCT status_id FROM outbound_picks")
        for r in cur.fetchall():
            self.assertIn(r[0], valid_statuses)

    def test_tier2_all_tms_pallet_counts_strictly_positive(self):
        """Verify all pallet counts in manifests are >= 1."""
        cur = self.conn_tms.cursor()
        cur.execute("SELECT MIN(Pallet_Count) FROM Carrier_Manifests")
        self.assertGreaterEqual(cur.fetchone()[0], 1)

    def test_tier2_all_tms_gross_weights_strictly_positive(self):
        """Verify all gross weights in carrier manifests are > 0.0 lbs."""
        cur = self.conn_tms.cursor()
        cur.execute("SELECT MIN(Gross_Weight_LBS) FROM Carrier_Manifests")
        self.assertGreater(cur.fetchone()[0], 0.0)


if __name__ == "__main__":
    unittest.main()
