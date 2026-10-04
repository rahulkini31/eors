"""Tier 4: Real-World Application Scenarios Test Suite.
Verifies end-to-end multi-agent resolution workflows:
- Canonical scenario: Acme Corp laptop order shipping determination (ERP -> WMS -> TMS)
- Distractor scenarios: DIST-1 through DIST-6 validation and proper status classification
- Synthesized order status decision engine simulating multi-agent query pipeline
"""

import unittest
from typing import Any, Dict, Optional

from e2e_tests.conftest_helpers import (
    load_in_memory_db,
    get_live_db_connection,
    is_live_db_ready,
)


def run_agentic_order_resolution_pipeline(
    customer_name: str,
    product_keyword: str,
    conn_erp=None,
    conn_wms=None,
    conn_tms=None,
) -> Dict[str, Any]:
    """Simulates the autonomous multi-agent reasoning pipeline:
    1. ERP Agent finds candidate orders for customer matching product
    2. WMS Agent finds physical pick records and handling units
    3. TMS Agent finds freight manifests and dispatch status
    Returns structured ground-truth determination.
    """
    if conn_erp is None:
        conn_erp = load_in_memory_db("db-01-dev")
    if conn_wms is None:
        conn_wms = load_in_memory_db("db-02-dev")
    if conn_tms is None:
        conn_tms = load_in_memory_db("db-03-dev")

    # Step 1: Query ERP
    cur_erp = conn_erp.cursor()
    cur_erp.execute(f"""
        SELECT c.Cust_ID, c.Cust_Name, o.Order_ID, o.PO_Number, o.OrderStatus, l.Item_SKU, i.Item_Description, l.Quantity, o.Total_Amount
        FROM tbl_Customers c
        JOIN tbl_SalesOrders o ON c.Cust_ID = o.Cust_ID
        JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
        JOIN tbl_Inventory_Master i ON l.Item_SKU = i.Item_SKU
        WHERE c.Cust_Name = '{customer_name}'
          AND (i.Item_Description LIKE '%{product_keyword}%' OR l.Item_SKU LIKE '%{product_keyword}%')
          AND o.OrderStatus <> 'Cancelled'
        ORDER BY o.Order_Date DESC
    """)
    erp_rows = cur_erp.fetchall()
    if not erp_rows:
        return {
            "resolved": False,
            "reason": f"No active order found in ERP for customer '{customer_name}' with product '{product_keyword}'",
            "shipped": False,
            "order_id": None,
        }

    # Evaluate each active order candidate
    for erp_row in erp_rows:
        order_id = erp_row["Order_ID"]

        # Step 2: Query WMS for order_id
        cur_wms = conn_wms.cursor()
        cur_wms.execute(f"""
            SELECT p.pick_id, p.status_id, p.handling_unit_id, p.qty_requested, p.qty_picked, hu.staged_dock_code, p.dock_loaded_at
            FROM outbound_picks p
            LEFT JOIN handling_units hu ON p.handling_unit_id = hu.hu_id
            WHERE p.erp_order_ref = '{order_id}'
        """)
        wms_row = cur_wms.fetchone()
        if not wms_row:
            continue

        status_id = wms_row["status_id"]
        hu_id = wms_row["handling_unit_id"]

        # Physical state evaluation
        if status_id != 5 or not hu_id:
            # Not loaded or no container
            continue

        # Step 3: Query TMS for hu_id
        cur_tms = conn_tms.cursor()
        cur_tms.execute(f"""
            SELECT m.Manifest_ID, m.Carrier_Name, m.Tracking_Number, m.Waybill_Number, m.Shipment_Status, m.Dispatched_At
            FROM Carrier_Manifests m
            WHERE m.Handling_Unit_Ref = '{hu_id}'
        """)
        tms_row = cur_tms.fetchone()
        if not tms_row:
            continue

        shipment_status = tms_row["Shipment_Status"]
        dispatched_at = tms_row["Dispatched_At"]

        if shipment_status in ("IN_TRANSIT", "DELIVERED") and dispatched_at is not None:
            return {
                "resolved": True,
                "shipped": True,
                "order_id": order_id,
                "po_number": erp_row["PO_Number"],
                "customer": erp_row["Cust_Name"],
                "sku": erp_row["Item_SKU"],
                "quantity": erp_row["Quantity"],
                "total_amount": erp_row["Total_Amount"],
                "wms_status_id": status_id,
                "handling_unit_id": hu_id,
                "dock_code": wms_row["staged_dock_code"],
                "carrier_name": tms_row["Carrier_Name"],
                "tracking_number": tms_row["Tracking_Number"],
                "waybill_number": tms_row["Waybill_Number"],
                "shipment_status": shipment_status,
                "dispatched_at": dispatched_at,
            }

    # Active order exists but not shipped
    primary = erp_rows[0]
    return {
        "resolved": True,
        "shipped": False,
        "order_id": primary["Order_ID"],
        "customer": primary["Cust_Name"],
        "reason": "Order found in ERP but physical/logistics status indicates not yet dispatched",
    }


class TestCanonicalAcmeCorpLaptopResolutionScenario(unittest.TestCase):
    """End-to-end verification of the primary Acme Corp laptop challenge."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier4_canonical_acme_laptop_order_shipped_determination(self):
        """Core Agentic Challenge: Determining whether Acme Corp's laptop order has shipped."""
        result = run_agentic_order_resolution_pipeline(
            customer_name="Acme Corp",
            product_keyword="Laptop",
            conn_erp=self.conn_erp,
            conn_wms=self.conn_wms,
            conn_tms=self.conn_tms,
        )

        self.assertTrue(result["resolved"], "Pipeline failed to resolve order")
        self.assertTrue(result["shipped"], "Acme Corp laptop order should be identified as SHIPPED")
        self.assertEqual(result["order_id"], "SO-10045")
        self.assertEqual(result["po_number"], "PO-ACM-2026-9921")
        self.assertEqual(result["customer"], "Acme Corp")
        self.assertEqual(result["sku"], "SKU-LAPTOP-15-ENT")
        self.assertEqual(result["quantity"], 10)
        self.assertEqual(result["wms_status_id"], 5)
        self.assertEqual(result["handling_unit_id"], "HU-8841-PLT")
        self.assertEqual(result["dock_code"], "DOCK-04")
        self.assertEqual(result["carrier_name"], "Apex Freight Express")
        self.assertEqual(result["tracking_number"], "TRK-AFX-9948201")
        self.assertEqual(result["waybill_number"], "WB-884102")
        self.assertEqual(result["shipment_status"], "IN_TRANSIT")
        self.assertIsNotNone(result["dispatched_at"])


class TestDistractorScenariosResolution(unittest.TestCase):
    """Verifies that all 6 distractor scenarios are properly categorized."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier4_dist1_acme_chair_order_not_shipped(self):
        """DIST-1: Acme Corp office chair order is NOT shipped (still in picking stage)."""
        result = run_agentic_order_resolution_pipeline(
            customer_name="Acme Corp",
            product_keyword="Chair",
            conn_erp=self.conn_erp,
            conn_wms=self.conn_wms,
            conn_tms=self.conn_tms,
        )
        self.assertTrue(result["resolved"])
        self.assertFalse(result["shipped"], "Acme Corp chair order must NOT be reported as shipped")
        self.assertEqual(result["order_id"], "SO-10046")

    def test_tier4_dist2_globex_laptop_order_attributed_to_globex(self):
        """DIST-2: Globex Corp laptop order is shipped/delivered to Globex, NOT Acme Corp."""
        result = run_agentic_order_resolution_pipeline(
            customer_name="Globex Corporation",
            product_keyword="Laptop",
            conn_erp=self.conn_erp,
            conn_wms=self.conn_wms,
            conn_tms=self.conn_tms,
        )
        self.assertTrue(result["resolved"])
        self.assertTrue(result["shipped"])
        self.assertEqual(result["order_id"], "SO-10047")
        self.assertEqual(result["customer"], "Globex Corporation")
        self.assertEqual(result["carrier_name"], "Swift Global Logistics")
        self.assertEqual(result["tracking_number"], "TRK-SW-7719283")
        self.assertEqual(result["shipment_status"], "DELIVERED")

    def test_tier4_dist3_cancelled_order_reported_not_shipped(self):
        """DIST-3: Cancelled historical order SO-10012 is NOT reported as shipped."""
        cur_erp = self.conn_erp.cursor()
        cur_erp.execute("SELECT OrderStatus FROM tbl_SalesOrders WHERE Order_ID = 'SO-10012'")
        self.assertEqual(cur_erp.fetchone()[0], "Cancelled")

        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT status_id FROM outbound_picks WHERE erp_order_ref = 'SO-10012'")
        self.assertEqual(cur_wms.fetchone()[0], 9)

    def test_tier4_dist4_staged_acme_laptop_order_not_shipped(self):
        """DIST-4: Staged Acme Corp laptop order SO-10048 has NOT departed (pending trailer pickup)."""
        cur_wms = self.conn_wms.cursor()
        cur_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10048'")
        wms_row = cur_wms.fetchone()
        self.assertEqual(wms_row["status_id"], 4)

        cur_tms = self.conn_tms.cursor()
        cur_tms.execute(f"SELECT Shipment_Status, Dispatched_At FROM Carrier_Manifests WHERE Handling_Unit_Ref = '{wms_row['handling_unit_id']}'")
        tms_row = cur_tms.fetchone()
        self.assertEqual(tms_row["Shipment_Status"], "PENDING_PICKUP")
        self.assertIsNone(tms_row["Dispatched_At"])

    def test_tier4_dist5_umbrella_laptop_order_not_shipped(self):
        """DIST-5: Umbrella Corp laptop order is in Allocated state (status 1) and NOT shipped."""
        result = run_agentic_order_resolution_pipeline(
            customer_name="Umbrella Corporation",
            product_keyword="Laptop",
            conn_erp=self.conn_erp,
            conn_wms=self.conn_wms,
            conn_tms=self.conn_tms,
        )
        self.assertTrue(result["resolved"])
        self.assertFalse(result["shipped"])
        self.assertEqual(result["order_id"], "SO-10049")

    def test_tier4_dist6_initech_monitors_background_traffic(self):
        """DIST-6: Initech monitors order SO-10050 is shipped to Initech, distinct from Acme Corp."""
        result = run_agentic_order_resolution_pipeline(
            customer_name="Initech LLC",
            product_keyword="Monitor",
            conn_erp=self.conn_erp,
            conn_wms=self.conn_wms,
            conn_tms=self.conn_tms,
        )
        self.assertTrue(result["resolved"])
        self.assertTrue(result["shipped"])
        self.assertEqual(result["order_id"], "SO-10050")
        self.assertEqual(result["customer"], "Initech LLC")
        self.assertEqual(result["sku"], "SKU-MONITOR-27-UHD")
        self.assertEqual(result["tracking_number"], "TRK-AFX-1102934")


class TestMultiAgentSynthesisEngine(unittest.TestCase):
    """Verifies edge cases within the synthesized resolution logic."""

    @classmethod
    def setUpClass(cls):
        cls.conn_erp = load_in_memory_db("db-01-dev")
        cls.conn_wms = load_in_memory_db("db-02-dev")
        cls.conn_tms = load_in_memory_db("db-03-dev")

    def test_tier4_unknown_customer_returns_unresolved(self):
        """Pipeline returns resolved=False when customer does not exist."""
        result = run_agentic_order_resolution_pipeline(
            customer_name="Cyberdyne Systems",
            product_keyword="Laptop",
            conn_erp=self.conn_erp,
            conn_wms=self.conn_wms,
            conn_tms=self.conn_tms,
        )
        self.assertFalse(result["resolved"])
        self.assertFalse(result["shipped"])

    def test_tier4_unknown_product_returns_unresolved(self):
        """Pipeline returns resolved=False when product is not ordered by customer."""
        result = run_agentic_order_resolution_pipeline(
            customer_name="Acme Corp",
            product_keyword="ServerRack",
            conn_erp=self.conn_erp,
            conn_wms=self.conn_wms,
            conn_tms=self.conn_tms,
        )
        self.assertFalse(result["resolved"])
        self.assertFalse(result["shipped"])


if __name__ == "__main__":
    unittest.main()
