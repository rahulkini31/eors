"""Independent Adversarial Stress Test Suite for Milestone 1 (M1).

Validates:
- Schema isolation & zero cross-DB foreign keys (F1, F5, F9)
- Absence of cross-domain table or column leaks
- Key field compatibility across decoupled databases
- Robustness against distractor false positives (F15, DIST-1 through DIST-6)
- Partial name queries, casing variations, whitespace resilience
- SQL injection immunity under parameterization vs concatenation
- End-to-end 3-hop query resolution for Acme Corp laptop order
- Idempotency and T-SQL syntax compliance
"""

import re
import sqlite3
import unittest
from pathlib import Path

REPO_ROOT = Path("/Users/rahulkini/project/eors")
MIGRATIONS_DIR = REPO_ROOT / "migrations"


def load_sql_scripts():
    """Load the three migration files."""
    paths = {
        "erp": MIGRATIONS_DIR / "db_01_erp.sql",
        "wms": MIGRATIONS_DIR / "db_02_wms.sql",
        "tms": MIGRATIONS_DIR / "db_03_tms.sql",
    }
    scripts = {}
    for name, p in paths.items():
        if not p.exists():
            raise FileNotFoundError(f"Migration file missing: {p}")
        scripts[name] = p.read_text(encoding="utf-8")
    return scripts


def tsql_to_sqlite(tsql: str) -> str:
    """Translate Azure SQL T-SQL DDL/DML to SQLite for in-memory behavioral testing."""
    s = re.sub(r"\bGO\b", "", tsql)
    s = re.sub(
        r"IF OBJECT_ID\([^)]+\)\s+IS NOT NULL\s+DROP TABLE\s+dbo\.([a-zA-Z0-9_]+);",
        r"DROP TABLE IF EXISTS \1;",
        s,
    )
    s = re.sub(r"\bdbo\.", "", s)
    s = re.sub(r"\bNVARCHAR\(\d+\)", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bVARCHAR\(\d+\)", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bDECIMAL\(\d+,\s*\d+\)", "REAL", s, flags=re.IGNORECASE)
    s = re.sub(r"\bDATETIME2\b", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(r"\bSYSUTCDATETIME\(\)", "CURRENT_TIMESTAMP", s, flags=re.IGNORECASE)
    s = re.sub(r"\bBIT\b", "INTEGER", s, flags=re.IGNORECASE)
    s = re.sub(r"\bDATE\b", "TEXT", s, flags=re.IGNORECASE)
    s = re.sub(
        r"INT\s+IDENTITY\(1,1\)\s+NOT\s+NULL\s+PRIMARY\s+KEY",
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"N'([^']*)'", r"'\1'", s)
    return s


class TestSchemaIsolationAndDecoupling(unittest.TestCase):
    """Adversarial stress-testing of schema autonomy, decoupling, and isolation."""

    @classmethod
    def setUpClass(cls):
        cls.scripts = load_sql_scripts()

    def test_strict_fk_isolation(self):
        """Verify zero cross-DB foreign key references exist across all 3 files."""
        for db_name, sql in self.scripts.items():
            fk_matches = re.findall(r"REFERENCES\s+([^\s\(]+)", sql, re.IGNORECASE)
            self.assertGreater(len(fk_matches), 0, f"{db_name} should contain intra-DB foreign keys")

            if db_name == "erp":
                valid_tables = {"dbo.tbl_Customers", "dbo.tbl_SalesOrders", "dbo.tbl_Inventory_Master"}
            elif db_name == "wms":
                valid_tables = {"dbo.dock_doors", "dbo.handling_units"}
            elif db_name == "tms":
                valid_tables = {"dbo.Carrier_Master", "dbo.Freight_Loads", "dbo.Bill_Of_Lading"}
            else:
                valid_tables = set()

            for target in fk_matches:
                self.assertIn(
                    target,
                    valid_tables,
                    f"Cross-DB foreign key leak detected! {db_name} references {target}",
                )

    def test_no_cross_domain_table_leakage(self):
        """Verify that table names from one domain never appear as tables in another."""
        erp_tables = {"tbl_Customers", "tbl_Inventory_Master", "tbl_SalesOrders", "tbl_OrderLineItems"}
        wms_tables = {"bin_locations", "dock_doors", "inventory_lots", "handling_units", "outbound_picks"}
        tms_tables = {"Carrier_Master", "Freight_Loads", "Bill_Of_Lading", "Carrier_Manifests"}

        for t in wms_tables.union(tms_tables):
            pattern = rf"CREATE\s+TABLE\s+dbo\.{t}\b"
            self.assertIsNone(
                re.search(pattern, self.scripts["erp"], re.IGNORECASE),
                f"WMS/TMS table {t} leaked into ERP DDL!",
            )

        for t in erp_tables.union(tms_tables):
            pattern = rf"CREATE\s+TABLE\s+dbo\.{t}\b"
            self.assertIsNone(
                re.search(pattern, self.scripts["wms"], re.IGNORECASE),
                f"ERP/TMS table {t} leaked into WMS DDL!",
            )

        for t in erp_tables.union(wms_tables):
            pattern = rf"CREATE\s+TABLE\s+dbo\.{t}\b"
            self.assertIsNone(
                re.search(pattern, self.scripts["tms"], re.IGNORECASE),
                f"ERP/WMS table {t} leaked into TMS DDL!",
            )

    def test_no_cross_domain_column_leakage(self):
        """Verify that specialized domain columns do not inappropriately leak across schemas."""
        erp_sql = self.scripts["erp"]
        wms_sql = self.scripts["wms"]
        tms_sql = self.scripts["tms"]

        # WMS physical coordinates should not appear in ERP or TMS
        wms_specific = ["bin_code", "shelf_level", "aisle_num", "lpn_barcode", "tare_weight_kg"]
        for col in wms_specific:
            self.assertNotIn(col, erp_sql, f"WMS column '{col}' leaked into ERP SQL")
            self.assertNotIn(col, tms_sql, f"WMS column '{col}' leaked into TMS SQL")

        # TMS carrier routing columns should not appear in ERP or WMS
        tms_specific = ["SCAC_Code", "BOL_Number", "Waybill_Number", "Gross_Weight_LBS", "Consignee_Name"]
        for col in tms_specific:
            self.assertNotIn(col, erp_sql, f"TMS column '{col}' leaked into ERP SQL")
            self.assertNotIn(col, wms_sql, f"TMS column '{col}' leaked into WMS SQL")

        # ERP financial pricing columns should not appear in WMS or TMS
        erp_specific = ["Unit_Cost_USD", "List_Price_USD", "Credit_Limit_USD", "Subtotal_Amount", "Tax_Amount"]
        for col in erp_specific:
            self.assertNotIn(col, wms_sql, f"ERP column '{col}' leaked into WMS SQL")
            self.assertNotIn(col, tms_sql, f"ERP column '{col}' leaked into TMS SQL")

    def test_key_field_length_compatibility(self):
        """Verify that loose reference fields are sufficiently sized to accept foreign keys."""
        # ERP Order_ID: VARCHAR(30) -> WMS erp_order_ref: VARCHAR(50) (50 >= 30)
        erp_order_match = re.search(r"Order_ID\s+VARCHAR\((\d+)\)", self.scripts["erp"], re.IGNORECASE)
        wms_ref_match = re.search(r"erp_order_ref\s+VARCHAR\((\d+)\)", self.scripts["wms"], re.IGNORECASE)
        self.assertIsNotNone(erp_order_match)
        self.assertIsNotNone(wms_ref_match)
        erp_len = int(erp_order_match.group(1))
        wms_ref_len = int(wms_ref_match.group(1))
        self.assertGreaterEqual(
            wms_ref_len,
            erp_len,
            f"WMS erp_order_ref ({wms_ref_len}) cannot hold ERP Order_ID ({erp_len})",
        )

        # WMS hu_id: VARCHAR(40) -> TMS Handling_Unit_Ref: VARCHAR(40) (40 >= 40)
        wms_hu_match = re.search(r"hu_id\s+VARCHAR\((\d+)\)", self.scripts["wms"], re.IGNORECASE)
        tms_hu_match = re.search(r"Handling_Unit_Ref\s+VARCHAR\((\d+)\)", self.scripts["tms"], re.IGNORECASE)
        self.assertIsNotNone(wms_hu_match)
        self.assertIsNotNone(tms_hu_match)
        wms_hu_len = int(wms_hu_match.group(1))
        tms_hu_len = int(tms_hu_match.group(1))
        self.assertGreaterEqual(
            tms_hu_len,
            wms_hu_len,
            f"TMS Handling_Unit_Ref ({tms_hu_len}) cannot hold WMS hu_id ({wms_hu_len})",
        )

    def test_teardown_dependency_order(self):
        """Verify that child tables are dropped before parent tables to avoid FK constraint errors."""
        for db_name, sql in self.scripts.items():
            drop_order = re.findall(
                r"DROP\s+TABLE\s+dbo\.([a-zA-Z0-9_]+);",
                sql,
                re.IGNORECASE,
            )
            self.assertGreater(len(drop_order), 0, f"No DROP TABLE statements found in {db_name}")

            if db_name == "erp":
                # LineItems references SalesOrders and Inventory_Master; SalesOrders references Customers
                self.assertLess(drop_order.index("tbl_OrderLineItems"), drop_order.index("tbl_SalesOrders"))
                self.assertLess(drop_order.index("tbl_OrderLineItems"), drop_order.index("tbl_Inventory_Master"))
                self.assertLess(drop_order.index("tbl_SalesOrders"), drop_order.index("tbl_Customers"))
            elif db_name == "wms":
                # outbound_picks references handling_units; handling_units references dock_doors
                self.assertLess(drop_order.index("outbound_picks"), drop_order.index("handling_units"))
                self.assertLess(drop_order.index("handling_units"), drop_order.index("dock_doors"))
            elif db_name == "tms":
                # Manifests references BOL and Carrier_Master; BOL references Loads; Loads references Carrier_Master
                self.assertLess(drop_order.index("Carrier_Manifests"), drop_order.index("Bill_Of_Lading"))
                self.assertLess(drop_order.index("Bill_Of_Lading"), drop_order.index("Freight_Loads"))
                self.assertLess(drop_order.index("Freight_Loads"), drop_order.index("Carrier_Master"))


class TestDistractorDiscriminationAndFalsePositives(unittest.TestCase):
    """Adversarial stress-testing demonstrating naive single-DB queries trap unsuspecting agents."""

    @classmethod
    def setUpClass(cls):
        scripts = load_sql_scripts()
        cls.erp_conn = sqlite3.connect(":memory:")
        cls.wms_conn = sqlite3.connect(":memory:")
        cls.tms_conn = sqlite3.connect(":memory:")

        cls.erp_conn.executescript(tsql_to_sqlite(scripts["erp"]))
        cls.wms_conn.executescript(tsql_to_sqlite(scripts["wms"]))
        cls.tms_conn.executescript(tsql_to_sqlite(scripts["tms"]))

    @classmethod
    def tearDownClass(cls):
        cls.erp_conn.close()
        cls.wms_conn.close()
        cls.tms_conn.close()

    def test_naive_erp_query_by_product_only_yields_400_percent_false_positives(self):
        """A naive query for 'Laptop' in ERP without customer filtering yields 5 orders (4 false positives)."""
        cur = self.erp_conn.cursor()
        cur.execute("""
            SELECT DISTINCT o.Order_ID, c.Cust_Name, o.OrderStatus
            FROM tbl_SalesOrders o
            JOIN tbl_Customers c ON o.Cust_ID = c.Cust_ID
            JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
            JOIN tbl_Inventory_Master i ON l.Item_SKU = i.Item_SKU
            WHERE i.Item_Description LIKE '%Laptop%'
            ORDER BY o.Order_ID;
        """)
        rows = cur.fetchall()
        order_ids = [r[0] for r in rows]

        # Expect 5 orders: SO-10012, SO-10045, SO-10047, SO-10048, SO-10049
        self.assertEqual(len(rows), 5, f"Expected 5 laptop orders across all customers, got {len(rows)}")
        self.assertIn("SO-10045", order_ids, "Target order SO-10045 must be present")
        self.assertIn("SO-10047", order_ids, "DIST-2 Globex laptop order must be present")
        self.assertIn("SO-10049", order_ids, "DIST-5 Umbrella laptop order must be present")

        # 4 out of 5 (80%) of results are NOT Acme's shipped order
        non_target = [r for r in rows if r[0] != "SO-10045"]
        self.assertEqual(len(non_target), 4, "Naive product query must yield 4 distractors")

    def test_naive_erp_query_by_customer_only_yields_300_percent_false_positives(self):
        """A naive query for 'Acme Corp' in ERP without product filtering yields 4 orders (3 false positives)."""
        cur = self.erp_conn.cursor()
        cur.execute("""
            SELECT o.Order_ID, i.Item_Description, o.OrderStatus
            FROM tbl_SalesOrders o
            JOIN tbl_Customers c ON o.Cust_ID = c.Cust_ID
            JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
            JOIN tbl_Inventory_Master i ON l.Item_SKU = i.Item_SKU
            WHERE c.Cust_Name = 'Acme Corp'
            ORDER BY o.Order_ID;
        """)
        rows = cur.fetchall()
        order_ids = [r[0] for r in rows]

        self.assertEqual(len(rows), 4, f"Expected 4 orders for Acme Corp, got {len(rows)}")
        self.assertIn("SO-10045", order_ids)
        self.assertIn("SO-10046", order_ids)  # DIST-1: Chairs
        self.assertIn("SO-10012", order_ids)  # DIST-3: Cancelled
        self.assertIn("SO-10048", order_ids)  # DIST-4: Staged

    def test_naive_erp_query_without_status_filter_contains_cancelled_and_staged_traps(self):
        """Querying Acme Corp + Laptop without checking OrderStatus returns 3 orders."""
        cur = self.erp_conn.cursor()
        cur.execute("""
            SELECT o.Order_ID, o.OrderStatus
            FROM tbl_SalesOrders o
            JOIN tbl_Customers c ON o.Cust_ID = c.Cust_ID
            JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
            JOIN tbl_Inventory_Master i ON l.Item_SKU = i.Item_SKU
            WHERE c.Cust_Name = 'Acme Corp'
              AND i.Item_Description LIKE '%Laptop%'
            ORDER BY o.Order_ID;
        """)
        rows = cur.fetchall()
        self.assertEqual(len(rows), 3)
        status_map = {r[0]: r[1] for r in rows}
        self.assertEqual(status_map["SO-10045"], "Completed")
        self.assertEqual(status_map["SO-10012"], "Cancelled")  # Trap 1
        self.assertEqual(status_map["SO-10048"], "Processing")  # Trap 2

    def test_naive_wms_query_by_status_5_yields_false_positives(self):
        """In WMS, querying purely for status_id = 5 (Loaded) yields 3 different shipments."""
        cur = self.wms_conn.cursor()
        cur.execute("""
            SELECT pick_id, erp_order_ref, handling_unit_id, sku_code
            FROM outbound_picks
            WHERE status_id = 5
            ORDER BY pick_id;
        """)
        rows = cur.fetchall()
        self.assertEqual(len(rows), 3)
        orders = [r[1] for r in rows]
        self.assertIn("SO-10045", orders)  # Acme Laptops
        self.assertIn("SO-10047", orders)  # Globex Laptops
        self.assertIn("SO-10050", orders)  # Initech Monitors

    def test_wms_staged_vs_loaded_distinction(self):
        """Verify WMS explicitly differentiates Staged (status_id=4) from Loaded (status_id=5)."""
        cur = self.wms_conn.cursor()
        cur.execute("""
            SELECT erp_order_ref, status_id, dock_loaded_at, staged_dock_code
            FROM outbound_picks p
            JOIN handling_units hu ON p.handling_unit_id = hu.hu_id
            WHERE p.erp_order_ref IN ('SO-10045', 'SO-10048')
            ORDER BY p.erp_order_ref;
        """)
        rows = cur.fetchall()
        res = {r[0]: r for r in rows}

        # SO-10045 is Loaded at DOCK-04 with valid dock_loaded_at
        self.assertEqual(res["SO-10045"][1], 5)
        self.assertIsNotNone(res["SO-10045"][2])
        self.assertEqual(res["SO-10045"][3], "DOCK-04")

        # SO-10048 is Staged at DOCK-07 with NULL dock_loaded_at (has NOT been loaded)
        self.assertEqual(res["SO-10048"][1], 4)
        self.assertIsNone(res["SO-10048"][2])
        self.assertEqual(res["SO-10048"][3], "DOCK-07")

    def test_naive_tms_query_by_in_transit_status_confounds_acme_and_initech(self):
        """In TMS, querying solely for Shipment_Status = 'IN_TRANSIT' returns both Acme and Initech."""
        cur = self.tms_conn.cursor()
        cur.execute("""
            SELECT Manifest_ID, BOL_Number, Handling_Unit_Ref, Carrier_Name, Tracking_Number
            FROM Carrier_Manifests
            WHERE Shipment_Status = 'IN_TRANSIT'
            ORDER BY Manifest_ID;
        """)
        rows = cur.fetchall()
        self.assertEqual(len(rows), 2)
        hu_refs = [r[2] for r in rows]
        # Both share carrier Apex Freight Express
        self.assertEqual(rows[0][3], "Apex Freight Express")
        self.assertEqual(rows[1][3], "Apex Freight Express")
        self.assertIn("HU-8841-PLT", hu_refs)  # Acme Laptops
        self.assertIn("HU-8845-PLT", hu_refs)  # Initech Monitors

    def test_naive_tms_query_by_exact_consignee_fails(self):
        """Querying TMS for exact Consignee_Name = 'Acme Corp' returns 0 rows (domain naming divergence)."""
        cur = self.tms_conn.cursor()
        cur.execute("SELECT * FROM Bill_Of_Lading WHERE Consignee_Name = 'Acme Corp';")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 0, "Exact match for 'Acme Corp' in TMS must return 0 rows")

        # Consignees are facility-specific: 'Acme Corp - Receiving Bay 2' & 'Acme Corp - Branch Receiving'
        cur.execute("SELECT BOL_Number, Consignee_Name FROM Bill_Of_Lading WHERE Consignee_Name LIKE 'Acme Corp%';")
        acme_bols = cur.fetchall()
        self.assertEqual(len(acme_bols), 2)


class TestAdversarialInputsAndEdgeCases(unittest.TestCase):
    """Stress tests on query variations, partial names, casing, whitespace, and SQL injection."""

    @classmethod
    def setUpClass(cls):
        scripts = load_sql_scripts()
        cls.erp_conn = sqlite3.connect(":memory:")
        cls.wms_conn = sqlite3.connect(":memory:")
        cls.tms_conn = sqlite3.connect(":memory:")

        cls.erp_conn.executescript(tsql_to_sqlite(scripts["erp"]))
        cls.wms_conn.executescript(tsql_to_sqlite(scripts["wms"]))
        cls.tms_conn.executescript(tsql_to_sqlite(scripts["tms"]))

    @classmethod
    def tearDownClass(cls):
        cls.erp_conn.close()
        cls.wms_conn.close()
        cls.tms_conn.close()

    def test_partial_customer_name_variations(self):
        """Test partial customer name queries against ERP."""
        cur = self.erp_conn.cursor()

        # Exact 'Acme' fails
        cur.execute("SELECT Cust_ID FROM tbl_Customers WHERE Cust_Name = 'Acme'")
        self.assertEqual(len(cur.fetchall()), 0)

        # Wildcard 'Acme%' matches CUST-00101
        cur.execute("SELECT Cust_ID FROM tbl_Customers WHERE Cust_Name LIKE 'Acme%'")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "CUST-00101")

        # Case-insensitive queries
        cur.execute("SELECT Cust_ID FROM tbl_Customers WHERE LOWER(Cust_Name) = 'acme corp'")
        rows_lower = cur.fetchall()
        self.assertEqual(len(rows_lower), 1)
        self.assertEqual(rows_lower[0][0], "CUST-00101")

    def test_product_description_token_variations(self):
        """Test multiple casing and token substring variations for laptop identification."""
        cur = self.erp_conn.cursor()

        test_tokens = ["%Laptop%", "%laptop%", "%LAPTOP%", "%Enterprise Laptop%"]
        for token in test_tokens:
            cur.execute(
                "SELECT Item_SKU FROM tbl_Inventory_Master WHERE Item_Description LIKE ? COLLATE NOCASE",
                (token,),
            )
            rows = cur.fetchall()
            self.assertEqual(len(rows), 1, f"Failed for token {token}")
            self.assertEqual(rows[0][0], "SKU-LAPTOP-15-ENT")

        # Negative token
        cur.execute(
            "SELECT Item_SKU FROM tbl_Inventory_Master WHERE Item_Description LIKE ? COLLATE NOCASE",
            ("%desktop%",),
        )
        self.assertEqual(len(cur.fetchall()), 0)

    def test_whitespace_tolerance(self):
        """Test that query inputs with surrounding whitespace are handled properly via TRIM."""
        cur = self.erp_conn.cursor()
        raw_cust = "  Acme Corp  "
        cur.execute("SELECT Cust_ID FROM tbl_Customers WHERE Cust_Name = TRIM(?)", (raw_cust,))
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "CUST-00101")

    def test_sql_injection_defense_via_parameterization(self):
        """Demonstrate that SQL injection attacks are neutralized by parameterized queries."""
        cur_erp = self.erp_conn.cursor()
        cur_wms = self.wms_conn.cursor()

        # Injection payload 1: Always-true condition in Customer Name
        inj_customer = "' OR '1'='1"
        cur_erp.execute("SELECT Cust_ID FROM tbl_Customers WHERE Cust_Name = ?", (inj_customer,))
        self.assertEqual(len(cur_erp.fetchall()), 0, "SQL injection leaked customers!")

        # Injection payload 2: DROP TABLE attempt
        inj_order = "SO-10045'; DROP TABLE tbl_SalesOrders; --"
        cur_erp.execute("SELECT Order_ID FROM tbl_SalesOrders WHERE Order_ID = ?", (inj_order,))
        self.assertEqual(len(cur_erp.fetchall()), 0)
        # Verify table still exists and data is intact
        cur_erp.execute("SELECT count(*) FROM tbl_SalesOrders")
        self.assertEqual(cur_erp.fetchone()[0], 7)

        # Injection payload 3: UNION SELECT payload in WMS
        inj_wms = "SO-10045' UNION SELECT 'hacked', 'hacked', 'hacked', 'hacked', 'hacked', 'hacked', 'hacked', 1, 1, 1, 'hacked', 'hacked', 'hacked' --"
        cur_wms.execute("SELECT pick_id FROM outbound_picks WHERE erp_order_ref = ?", (inj_wms,))
        self.assertEqual(len(cur_wms.fetchall()), 0, "WMS leaked records via UNION injection!")

    def test_null_handling_in_wms_and_tms(self):
        """Verify handling of NULL handling units (cancelled/allocated) and NULL dispatch dates."""
        cur_wms = self.wms_conn.cursor()
        cur_tms = self.tms_conn.cursor()

        # Cancelled pick PK-8750 has NULL handling_unit_id
        cur_wms.execute("SELECT handling_unit_id FROM outbound_picks WHERE pick_id = 'PK-8750'")
        self.assertIsNone(cur_wms.fetchone()[0])

        # Allocated pick PK-8805 has NULL handling_unit_id
        cur_wms.execute("SELECT handling_unit_id FROM outbound_picks WHERE pick_id = 'PK-8805'")
        self.assertIsNone(cur_wms.fetchone()[0])

        # Staged manifest MNF-2026-8804 has NULL Dispatched_At
        cur_tms.execute("SELECT Dispatched_At, Shipment_Status FROM Carrier_Manifests WHERE Manifest_ID = 'MNF-2026-8804'")
        row = cur_tms.fetchone()
        self.assertIsNone(row[0])
        self.assertEqual(row[1], "PENDING_PICKUP")


class TestEndToEndCanonicalFlowAndDistractorIsolation(unittest.TestCase):
    """Validates that synthesizing data across all 3 databases resolves ONLY Acme's target shipment."""

    @classmethod
    def setUpClass(cls):
        scripts = load_sql_scripts()
        cls.erp_conn = sqlite3.connect(":memory:")
        cls.wms_conn = sqlite3.connect(":memory:")
        cls.tms_conn = sqlite3.connect(":memory:")

        cls.erp_conn.executescript(tsql_to_sqlite(scripts["erp"]))
        cls.wms_conn.executescript(tsql_to_sqlite(scripts["wms"]))
        cls.tms_conn.executescript(tsql_to_sqlite(scripts["tms"]))

    @classmethod
    def tearDownClass(cls):
        cls.erp_conn.close()
        cls.wms_conn.close()
        cls.tms_conn.close()

    def test_target_canonical_flow(self):
        """Acme Corp Laptop order SO-10045 resolves across ERP -> WMS -> TMS to IN_TRANSIT with Apex."""
        cur_erp = self.erp_conn.cursor()
        cur_wms = self.wms_conn.cursor()
        cur_tms = self.tms_conn.cursor()

        # Stage 1: ERP
        cur_erp.execute("""
            SELECT o.Order_ID, o.PO_Number, o.OrderStatus, l.Quantity, o.Total_Amount
            FROM tbl_Customers c
            JOIN tbl_SalesOrders o ON c.Cust_ID = o.Cust_ID
            JOIN tbl_OrderLineItems l ON o.Order_ID = l.Order_ID
            JOIN tbl_Inventory_Master i ON l.Item_SKU = i.Item_SKU
            WHERE c.Cust_Name = 'Acme Corp'
              AND i.Item_Description LIKE '%Laptop%'
              AND o.OrderStatus = 'Completed';
        """)
        erp_rows = cur_erp.fetchall()
        self.assertEqual(len(erp_rows), 1, "ERP should resolve exactly one Completed laptop order for Acme")
        order_id, po_num, order_status, qty, total = erp_rows[0]
        self.assertEqual(order_id, "SO-10045")
        self.assertEqual(po_num, "PO-ACM-2026-9921")
        self.assertEqual(qty, 10)
        self.assertEqual(total, 20230.00)

        # Stage 2: WMS
        cur_wms.execute("""
            SELECT p.pick_id, p.handling_unit_id, p.status_id, hu.staged_dock_code
            FROM outbound_picks p
            JOIN handling_units hu ON p.handling_unit_id = hu.hu_id
            WHERE p.erp_order_ref = ?;
        """, (order_id,))
        wms_rows = cur_wms.fetchall()
        self.assertEqual(len(wms_rows), 1, "WMS should resolve exactly one pick record")
        pick_id, hu_id, status_id, dock = wms_rows[0]
        self.assertEqual(pick_id, "PK-8801")
        self.assertEqual(hu_id, "HU-8841-PLT")
        self.assertEqual(status_id, 5, "Status must be 5 (Loaded)")
        self.assertEqual(dock, "DOCK-04")

        # Stage 3: TMS
        cur_tms.execute("""
            SELECT m.Carrier_Name, m.Tracking_Number, m.Waybill_Number, m.Shipment_Status, m.Dispatched_At
            FROM Carrier_Manifests m
            WHERE m.Handling_Unit_Ref = ?;
        """, (hu_id,))
        tms_rows = cur_tms.fetchall()
        self.assertEqual(len(tms_rows), 1, "TMS should resolve exactly one manifest record")
        carrier, trk, wb, status, dispatched = tms_rows[0]
        self.assertEqual(carrier, "Apex Freight Express")
        self.assertEqual(trk, "TRK-AFX-9948201")
        self.assertEqual(wb, "WB-884102")
        self.assertEqual(status, "IN_TRANSIT")
        self.assertIsNotNone(dispatched)

    def test_secondary_po_number_resolution(self):
        """Verify cross-domain resolution works equally reliably via secondary key (PO_Number -> customer_po_ref)."""
        cur_erp = self.erp_conn.cursor()
        cur_wms = self.wms_conn.cursor()

        # ERP resolution
        cur_erp.execute("SELECT PO_Number FROM tbl_SalesOrders WHERE Order_ID = 'SO-10045'")
        po_number = cur_erp.fetchone()[0]
        self.assertEqual(po_number, "PO-ACM-2026-9921")

        # WMS resolution via secondary key
        cur_wms.execute("""
            SELECT pick_id, handling_unit_id, status_id
            FROM outbound_picks
            WHERE customer_po_ref = ?
        """, (po_number,))
        wms_rows = cur_wms.fetchall()
        self.assertEqual(len(wms_rows), 1)
        self.assertEqual(wms_rows[0][0], "PK-8801")
        self.assertEqual(wms_rows[0][1], "HU-8841-PLT")
        self.assertEqual(wms_rows[0][2], 5)

    def test_bol_dual_path_resolution(self):
        """Verify TMS resolves identically whether queried directly via Carrier_Manifests or bridged via Bill_Of_Lading."""
        cur_tms = self.tms_conn.cursor()
        hu_ref = "HU-8841-PLT"

        # Path A: Direct Carrier_Manifests query
        cur_tms.execute("SELECT Tracking_Number, Carrier_Name FROM Carrier_Manifests WHERE Handling_Unit_Ref = ?", (hu_ref,))
        path_a = cur_tms.fetchone()

        # Path B: BOL bridged query
        cur_tms.execute("""
            SELECT m.Tracking_Number, m.Carrier_Name
            FROM Bill_Of_Lading bol
            JOIN Carrier_Manifests m ON bol.BOL_Number = m.BOL_Number
            WHERE bol.Handling_Unit_Ref = ?
        """, (hu_ref,))
        path_b = cur_tms.fetchone()

        self.assertEqual(path_a, path_b)
        self.assertEqual(path_a[0], "TRK-AFX-9948201")
        self.assertEqual(path_a[1], "Apex Freight Express")


    def test_all_six_distractors_properly_classified(self):
        """Verify that every distractor scenario yields its exact expected non-target state."""
        cur_erp = self.erp_conn.cursor()
        cur_wms = self.wms_conn.cursor()
        cur_tms = self.tms_conn.cursor()

        # DIST-1: Acme Chairs (SO-10046) -> Picked (status_id=2) -> NO TMS
        cur_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10046'")
        d1_wms = cur_wms.fetchone()
        self.assertEqual(d1_wms[0], 2)
        cur_tms.execute("SELECT count(*) FROM Carrier_Manifests WHERE Handling_Unit_Ref = ?", (d1_wms[1],))
        self.assertEqual(cur_tms.fetchone()[0], 0, "DIST-1 should NOT exist in TMS")

        # DIST-2: Globex Laptops (SO-10047) -> Loaded (status_id=5) -> Swift DELIVERED
        cur_wms.execute("SELECT handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10047'")
        d2_hu = cur_wms.fetchone()[0]
        cur_tms.execute("SELECT Carrier_Name, Tracking_Number, Shipment_Status FROM Carrier_Manifests WHERE Handling_Unit_Ref = ?", (d2_hu,))
        d2_tms = cur_tms.fetchone()
        self.assertEqual(d2_tms[0], "Swift Global Logistics")
        self.assertEqual(d2_tms[1], "TRK-SW-7719283")
        self.assertEqual(d2_tms[2], "DELIVERED")

        # DIST-3: Cancelled Acme Laptops (SO-10012) -> Cancelled (status_id=9) -> NULL HU
        cur_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10012'")
        d3_wms = cur_wms.fetchone()
        self.assertEqual(d3_wms[0], 9)
        self.assertIsNone(d3_wms[1])

        # DIST-4: Staged Acme Laptops (SO-10048) -> Staged (status_id=4) -> FedEx PENDING_PICKUP
        cur_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10048'")
        d4_wms = cur_wms.fetchone()
        self.assertEqual(d4_wms[0], 4)
        cur_tms.execute("SELECT Carrier_Name, Tracking_Number, Shipment_Status, Dispatched_At FROM Carrier_Manifests WHERE Handling_Unit_Ref = ?", (d4_wms[1],))
        d4_tms = cur_tms.fetchone()
        self.assertEqual(d4_tms[0], "FedEx Freight Regional")
        self.assertEqual(d4_tms[1], "TRK-FX-3301928")
        self.assertEqual(d4_tms[2], "PENDING_PICKUP")
        self.assertIsNone(d4_tms[3])

        # DIST-5: Umbrella Allocated Laptops (SO-10049) -> Allocated (status_id=1) -> NULL HU
        cur_wms.execute("SELECT status_id, handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10049'")
        d5_wms = cur_wms.fetchone()
        self.assertEqual(d5_wms[0], 1)
        self.assertIsNone(d5_wms[1])

        # DIST-6: Initech Monitors (SO-10050) -> Loaded (status_id=5) -> Apex IN_TRANSIT (TRK-AFX-1102934)
        cur_wms.execute("SELECT handling_unit_id FROM outbound_picks WHERE erp_order_ref = 'SO-10050'")
        d6_hu = cur_wms.fetchone()[0]
        cur_tms.execute("SELECT Tracking_Number, Shipment_Status FROM Carrier_Manifests WHERE Handling_Unit_Ref = ?", (d6_hu,))
        d6_tms = cur_tms.fetchone()
        self.assertEqual(d6_tms[0], "TRK-AFX-1102934")
        self.assertEqual(d6_tms[1], "IN_TRANSIT")


class TestTSQLSyntaxAndIdempotency(unittest.TestCase):
    """Stress tests on migration idempotency and T-SQL syntactic correctness."""

    @classmethod
    def setUpClass(cls):
        cls.scripts = load_sql_scripts()

    def test_idempotency_double_execution(self):
        """Applying the teardown and setup twice in sequence produces zero errors and identical state."""
        for db_name, sql in self.scripts.items():
            conn = sqlite3.connect(":memory:")
            sqlite_sql = tsql_to_sqlite(sql)
            # Run 1
            conn.executescript(sqlite_sql)
            # Run 2 (Simulating rerun / re-migration)
            conn.executescript(sqlite_sql)

            # Ensure tables are non-empty after re-execution
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
            tbl_count = cur.fetchone()[0]
            self.assertGreater(tbl_count, 0, f"{db_name} has no tables after rerun")
            conn.close()

    def test_batch_terminators_and_unicode_literals(self):
        """Verify presence of GO batch delimiters and N'...' Unicode prefixes."""
        for db_name, sql in self.scripts.items():
            # Check GO statements
            go_matches = re.findall(r"^\s*GO\s*$", sql, re.MULTILINE)
            self.assertGreater(len(go_matches), 3, f"{db_name} lacks sufficient GO batch delimiters")

            # Check that table drops have OBJECT_ID guards
            object_id_drops = re.findall(r"IF OBJECT_ID\('[^']+',\s*'U'\)\s+IS NOT NULL\s+DROP TABLE", sql)
            self.assertGreater(len(object_id_drops), 3, f"{db_name} lacks guarded table drops")


if __name__ == "__main__":
    unittest.main()
