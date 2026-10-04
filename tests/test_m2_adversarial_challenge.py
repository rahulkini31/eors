"""Independent Adversarial Stress Test Suite for Milestone 2 (M2).

Adversarially challenges:
- migrations/run_migrations.py
- verify_cross_db_challenge.py

Challenge Dimensions Tested:
1. Serverless Auto-Pause & Cold-Start Retry Logic (Error 40613, timeouts, backoff, non-transient fail-fast)
2. Microsoft Entra ID Authentication & Token Resolution Scenarios (cache, env var, SDK, CLI fallback, errors)
3. CLI Arguments, Parameter Validation & Execution Modes (--help, invalid args, --db choices, --dry-run, --mock, --offline)
4. Distractor Order Discrimination & Trap Avoidance (DIST-1 through DIST-6 isolation across ERP, WMS, TMS)
5. SQL Batch Parsing, Delimiter Handling & Edge Cases (GO variations, CRLF, comments, summary extraction)
6. End-to-End Synthesis, Assertion Strictness & Report Formatting
7. Live Azure SQL Target Verification against eosr-db-server.database.windows.net
"""

import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

REPO_ROOT = Path("/Users/rahulkini/project/eors").resolve()
sys.path.insert(0, str(REPO_ROOT))

import migrations.run_migrations as rm
import verify_cross_db_challenge as vcd
from e2e_tests.conftest_helpers import load_in_memory_db


class TestServerlessRetryLogic(unittest.TestCase):
    """Adversarially challenge the serverless auto-pause retry loops under simulated errors."""

    def setUp(self):
        # Reset cached tokens before each test
        rm._cached_token = None
        vcd._cached_token = None

    @patch("migrations.run_migrations.time.sleep")
    @patch("migrations.run_migrations.pytds.connect")
    @patch("migrations.run_migrations.resolve_entra_token")
    def test_run_migrations_retry_on_error_40613_recovers(self, mock_token, mock_connect, mock_sleep):
        """Simulate Azure SQL cold-start pause error 40613 on attempts 1 and 2, recovering on 3."""
        mock_token.return_value = "mock-token-abc"
        fake_conn = MagicMock()

        err_40613 = Exception("pytds.OperationalError: Database 'db-01-dev' is not currently available (error 40613).")
        # Fail twice with 40613, then succeed on 3rd attempt
        mock_connect.side_effect = [err_40613, err_40613, fake_conn]

        conn = rm.connect_azure_sql("db-01-dev", server="test-server", max_retries=5, initial_delay=6.0, backoff_factor=4.0)

        self.assertEqual(conn, fake_conn)
        self.assertEqual(mock_connect.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        # Verify backoff delays: initial 6.0, then 6.0 + 4.0 = 10.0
        mock_sleep.assert_has_calls([call(6.0), call(10.0)])

    @patch("verify_cross_db_challenge.time.sleep")
    @patch("verify_cross_db_challenge.pytds.connect")
    @patch("verify_cross_db_challenge.resolve_entra_token")
    def test_verify_cross_db_retry_on_error_40613_recovers(self, mock_token, mock_connect, mock_sleep):
        """Simulate error 40613 in verify_cross_db_challenge.connect_live with recovery."""
        mock_token.return_value = "mock-token-abc"
        fake_conn = MagicMock()
        err_40613 = Exception("Error 40613: Database is paused and resuming.")

        mock_connect.side_effect = [err_40613, fake_conn]

        conn = vcd.connect_live("db-02-dev", server="test-server", max_retries=4)

        self.assertEqual(conn, fake_conn)
        self.assertEqual(mock_connect.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)
        mock_sleep.assert_has_calls([call(5.0)])

    @patch("migrations.run_migrations.time.sleep")
    @patch("migrations.run_migrations.pytds.connect")
    @patch("migrations.run_migrations.resolve_entra_token")
    def test_run_migrations_retry_on_timeout_recovers(self, mock_token, mock_connect, mock_sleep):
        """Simulate connection timeout during database cold-start auto-wake."""
        mock_token.return_value = "mock-token-abc"
        fake_conn = MagicMock()
        timeout_err = TimeoutError("Connection timed out after 30 seconds")

        mock_connect.side_effect = [timeout_err, fake_conn]

        conn = rm.connect_azure_sql("db-03-dev", server="test-server", max_retries=3, initial_delay=4.0, backoff_factor=2.0)
        self.assertEqual(conn, fake_conn)
        self.assertEqual(mock_connect.call_count, 2)
        mock_sleep.assert_called_once_with(4.0)

    @patch("migrations.run_migrations.time.sleep")
    @patch("migrations.run_migrations.pytds.connect")
    @patch("migrations.run_migrations.resolve_entra_token")
    def test_run_migrations_retry_on_not_currently_available(self, mock_token, mock_connect, mock_sleep):
        """Simulate 'not currently available' text pattern without explicit 40613 number."""
        mock_token.return_value = "mock-token-abc"
        fake_conn = MagicMock()
        avail_err = Exception("The database is not currently available. Please try again.")

        mock_connect.side_effect = [avail_err, fake_conn]

        conn = rm.connect_azure_sql("db-01-dev", server="test-server", max_retries=3, initial_delay=3.0, backoff_factor=1.0)
        self.assertEqual(conn, fake_conn)
        self.assertEqual(mock_connect.call_count, 2)
        mock_sleep.assert_called_once_with(3.0)

    @patch("migrations.run_migrations.time.sleep")
    @patch("migrations.run_migrations.pytds.connect")
    @patch("migrations.run_migrations.resolve_entra_token")
    def test_run_migrations_retries_exhausted_raises(self, mock_token, mock_connect, mock_sleep):
        """When error 40613 persists through all attempts, ensure it raises exception."""
        mock_token.return_value = "mock-token-abc"
        persist_err = Exception("40613: Persistent auto-pause failure")
        mock_connect.side_effect = persist_err

        with self.assertRaises(Exception) as ctx:
            rm.connect_azure_sql("db-01-dev", server="test-server", max_retries=3, initial_delay=1.0, backoff_factor=1.0)

        self.assertIn("40613", str(ctx.exception))
        self.assertEqual(mock_connect.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("verify_cross_db_challenge.time.sleep")
    @patch("verify_cross_db_challenge.pytds.connect")
    @patch("verify_cross_db_challenge.resolve_entra_token")
    def test_verify_cross_db_retries_exhausted_raises(self, mock_token, mock_connect, mock_sleep):
        """When error 40613 persists through max_retries in connect_live, ensure it raises."""
        mock_token.return_value = "mock-token-abc"
        persist_err = Exception("40613: Target database unavailable")
        mock_connect.side_effect = persist_err

        with self.assertRaises(Exception) as ctx:
            vcd.connect_live("db-02-dev", server="test-server", max_retries=3)

        self.assertIn("40613", str(ctx.exception))
        self.assertEqual(mock_connect.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("migrations.run_migrations.time.sleep")
    @patch("migrations.run_migrations.pytds.connect")
    @patch("migrations.run_migrations.resolve_entra_token")
    def test_run_migrations_fail_fast_on_non_transient_error(self, mock_token, mock_connect, mock_sleep):
        """Non-transient errors (e.g. auth failure, bad password, missing DB) must fail fast without retry sleep."""
        mock_token.return_value = "mock-token-abc"
        auth_err = Exception("Login failed for user 'token-user'. Reason: Token expired.")
        mock_connect.side_effect = auth_err

        with self.assertRaises(Exception) as ctx:
            rm.connect_azure_sql("db-01-dev", server="test-server", max_retries=5)

        self.assertIn("Login failed for user", str(ctx.exception))
        self.assertEqual(mock_connect.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("verify_cross_db_challenge.time.sleep")
    @patch("verify_cross_db_challenge.pytds.connect")
    @patch("verify_cross_db_challenge.resolve_entra_token")
    def test_verify_cross_db_fail_fast_on_non_transient_error(self, mock_token, mock_connect, mock_sleep):
        """Non-transient errors in verify_cross_db_challenge must fail fast without sleeping."""
        mock_token.return_value = "mock-token-abc"
        perm_err = Exception("Cannot open database 'db-99-nonexistent' requested by the login.")
        mock_connect.side_effect = perm_err

        with self.assertRaises(Exception) as ctx:
            vcd.connect_live("db-99-nonexistent", server="test-server", max_retries=5)

        self.assertIn("Cannot open database", str(ctx.exception))
        self.assertEqual(mock_connect.call_count, 1)
        mock_sleep.assert_not_called()


class TestTokenResolutionAndAuthScenarios(unittest.TestCase):
    """Adversarially challenge Microsoft Entra ID token acquisition logic across all tiers."""

    def setUp(self):
        rm._cached_token = None
        vcd._cached_token = None
        self.orig_env = os.environ.get("AZURE_SQL_ACCESS_TOKEN")

    def tearDown(self):
        rm._cached_token = None
        vcd._cached_token = None
        if self.orig_env is not None:
            os.environ["AZURE_SQL_ACCESS_TOKEN"] = self.orig_env
        else:
            os.environ.pop("AZURE_SQL_ACCESS_TOKEN", None)

    def test_token_cache_reuse_migrations(self):
        """Ensure _cached_token is immediately returned without hitting env or external calls."""
        rm._cached_token = "pre-cached-token-1234"
        with patch.dict(os.environ, {}, clear=True):
            resolved = rm.resolve_entra_token()
            self.assertEqual(resolved, "pre-cached-token-1234")

    def test_token_cache_reuse_verifier(self):
        """Ensure _cached_token in verifier is returned directly."""
        vcd._cached_token = "pre-cached-verifier-token"
        with patch.dict(os.environ, {}, clear=True):
            resolved = vcd.resolve_entra_token()
            self.assertEqual(resolved, "pre-cached-verifier-token")

    def test_token_env_var_priority(self):
        """Ensure AZURE_SQL_ACCESS_TOKEN takes priority over SDK and az CLI."""
        os.environ["AZURE_SQL_ACCESS_TOKEN"] = "env-token-xyz-987"
        rm._cached_token = None
        resolved = rm.resolve_entra_token()
        self.assertEqual(resolved, "env-token-xyz-987")
        self.assertEqual(rm._cached_token, "env-token-xyz-987")

    def test_token_empty_env_var_falls_through(self):
        """Whitespace or empty env var is ignored and falls through to next tier."""
        os.environ["AZURE_SQL_ACCESS_TOKEN"] = "   "
        rm._cached_token = None

        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(stdout=json.dumps({"accessToken": "cli-token-abc"}), check=True)
            with patch("azure.identity.DefaultAzureCredential", side_effect=Exception("SDK unavailable")):
                resolved = rm.resolve_entra_token()
                self.assertEqual(resolved, "cli-token-abc")

    @patch("subprocess.run")
    def test_token_az_cli_subprocess_success(self, mock_sub):
        """Test subprocess fallback to az account get-access-token."""
        rm._cached_token = None
        os.environ.pop("AZURE_SQL_ACCESS_TOKEN", None)

        mock_sub.return_value = MagicMock(
            stdout=json.dumps({"accessToken": "jwt-cli-token-test-value"}),
            check=True,
        )

        with patch("azure.identity.DefaultAzureCredential", side_effect=Exception("No SDK creds")):
            with patch("azure.identity.AzureCliCredential", side_effect=Exception("No CLI creds")):
                token = rm.resolve_entra_token()
                self.assertEqual(token, "jwt-cli-token-test-value")
                self.assertEqual(os.environ.get("AZURE_SQL_ACCESS_TOKEN"), "jwt-cli-token-test-value")

    @patch("subprocess.run", side_effect=Exception("az CLI not installed"))
    def test_token_resolution_all_fail_raises(self, mock_sub):
        """When all tiers fail (env, SDK, CLI), RuntimeError must be raised."""
        rm._cached_token = None
        vcd._cached_token = None
        os.environ.pop("AZURE_SQL_ACCESS_TOKEN", None)

        with patch("azure.identity.DefaultAzureCredential", side_effect=Exception("SDK failed")):
            with patch("azure.identity.AzureCliCredential", side_effect=Exception("CLI failed")):
                with self.assertRaises(RuntimeError) as ctx:
                    rm.resolve_entra_token()
                self.assertIn("Unable to acquire", str(ctx.exception))

                with self.assertRaises(RuntimeError) as ctx_v:
                    vcd.resolve_entra_token()
                self.assertIn("Unable to acquire", str(ctx_v.exception))


class TestCLIArgumentsAndExecutionModes(unittest.TestCase):
    """Adversarially challenge CLI arguments, flags, and parameter bounds across both scripts."""

    def test_run_migrations_help(self):
        """run_migrations.py --help must exit 0 and document flags."""
        cmd = [sys.executable, str(REPO_ROOT / "migrations" / "run_migrations.py"), "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("--server", res.stdout)
        self.assertIn("--db", res.stdout)
        self.assertIn("--dry-run", res.stdout)

    def test_run_migrations_invalid_option(self):
        """run_migrations.py with invalid options must exit 2."""
        cmd = [sys.executable, str(REPO_ROOT / "migrations" / "run_migrations.py"), "--invalid-flag"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("unrecognized arguments", res.stderr)

    def test_run_migrations_invalid_db_choice(self):
        """run_migrations.py with invalid db name must be rejected by argparse choice validation."""
        cmd = [sys.executable, str(REPO_ROOT / "migrations" / "run_migrations.py"), "--db", "db-99-bogus"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("invalid choice", res.stderr)

    def test_run_migrations_dry_run_all_databases(self):
        """run_migrations.py --dry-run must parse all 3 files without live DB execution and exit 0."""
        cmd = [sys.executable, str(REPO_ROOT / "migrations" / "run_migrations.py"), "--dry-run"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertIn("[db-01-dev] -> Status: DRY_RUN_PASSED", output)
        self.assertIn("[db-02-dev] -> Status: DRY_RUN_PASSED", output)
        self.assertIn("[db-03-dev] -> Status: DRY_RUN_PASSED", output)
        self.assertIn("All migrations applied and verified successfully!", output)

    def test_run_migrations_dry_run_single_db_01(self):
        """run_migrations.py --db db-01-dev --dry-run must process only db-01-dev."""
        cmd = [
            sys.executable,
            str(REPO_ROOT / "migrations" / "run_migrations.py"),
            "--db",
            "db-01-dev",
            "--dry-run",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertIn("[db-01-dev]", output)
        self.assertNotIn("[db-02-dev]", output)
        self.assertNotIn("[db-03-dev]", output)

    def test_run_migrations_dry_run_single_db_02(self):
        """run_migrations.py --db db-02-dev --dry-run must process only db-02-dev."""
        cmd = [
            sys.executable,
            str(REPO_ROOT / "migrations" / "run_migrations.py"),
            "--db",
            "db-02-dev",
            "--dry-run",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertNotIn("[db-01-dev]", output)
        self.assertIn("[db-02-dev]", output)
        self.assertNotIn("[db-03-dev]", output)

    def test_run_migrations_dry_run_single_db_03(self):
        """run_migrations.py --db db-03-dev --dry-run must process only db-03-dev."""
        cmd = [
            sys.executable,
            str(REPO_ROOT / "migrations" / "run_migrations.py"),
            "--db",
            "db-03-dev",
            "--dry-run",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertNotIn("[db-01-dev]", output)
        self.assertNotIn("[db-02-dev]", output)
        self.assertIn("[db-03-dev]", output)

    def test_verify_challenge_help(self):
        """verify_cross_db_challenge.py --help must exit 0 and document flags."""
        cmd = [sys.executable, str(REPO_ROOT / "verify_cross_db_challenge.py"), "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("--server", res.stdout)
        self.assertIn("--mock", res.stdout)
        self.assertIn("--offline", res.stdout)

    def test_verify_challenge_invalid_flag(self):
        """verify_cross_db_challenge.py with unknown option must exit 2."""
        cmd = [sys.executable, str(REPO_ROOT / "verify_cross_db_challenge.py"), "--unsupported"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("unrecognized arguments", res.stderr)

    def test_verify_challenge_mock_mode_cli(self):
        """verify_cross_db_challenge.py --mock must execute offline relational fixtures and exit 0."""
        cmd = [sys.executable, str(REPO_ROOT / "verify_cross_db_challenge.py"), "--mock"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("FINAL VERIFICATION SYNTHESIS", res.stdout)
        self.assertIn("CONCLUSION: Customer 'Acme Corp' Laptop Order (SO-10045) HAS SHIPPED.", res.stdout)
        self.assertIn("Tracking Number:    TRK-AFX-9948201", res.stdout)

    def test_verify_challenge_offline_mode_alias_cli(self):
        """verify_cross_db_challenge.py --offline alias must execute identically and exit 0."""
        cmd = [sys.executable, str(REPO_ROOT / "verify_cross_db_challenge.py"), "--offline"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("FINAL VERIFICATION SYNTHESIS", res.stdout)
        self.assertIn("CONCLUSION: Customer 'Acme Corp' Laptop Order (SO-10045) HAS SHIPPED.", res.stdout)


class TestDistractorDiscriminationAndTraps(unittest.TestCase):
    """Adversarially challenge cross-domain query logic against distractor false positives (DIST-1 to DIST-6)."""

    @classmethod
    def setUpClass(cls):
        cls.adapter = vcd.DatabaseAdapter(mode="mock")

    def test_erp_stage1_matches_target_order(self):
        """Stage 1 strictly matches Acme Corp's Laptop order (SO-10045)."""
        order = vcd.query_stage1_erp(self.adapter)
        self.assertEqual(order["Order_ID"], "SO-10045")
        self.assertEqual(order["Cust_Name"], "Acme Corp")
        self.assertEqual(order["Item_SKU"], "SKU-LAPTOP-15-ENT")
        self.assertEqual(order["OrderStatus"], "Completed")
        self.assertEqual(float(order["Total_Amount"]), 20230.00)

    def test_erp_stage1_rejects_distractor_1_chairs(self):
        """DIST-1 (Acme Corp Ergonomic Chairs, SO-10046) must not be matched by laptop query."""
        sql = """
        SELECT so.Order_ID
        FROM dbo.tbl_SalesOrders so
        INNER JOIN dbo.tbl_Customers c ON so.Cust_ID = c.Cust_ID
        INNER JOIN dbo.tbl_OrderLineItems oli ON so.Order_ID = oli.Order_ID
        INNER JOIN dbo.tbl_Inventory_Master im ON oli.Item_SKU = im.Item_SKU
        WHERE c.Cust_Name = 'Acme Corp'
          AND (im.Item_Description LIKE '%Laptop%' OR oli.Item_SKU LIKE '%LAPTOP%')
          AND so.Order_ID = 'SO-10046'
        """
        rows = self.adapter.execute_query("db-01-dev", sql)
        self.assertEqual(len(rows), 0, "DIST-1 chair order was erroneously matched by laptop query!")

    def test_erp_stage1_rejects_distractor_2_globex(self):
        """DIST-2 (Globex Corp Laptops, SO-10047) must not be matched by Acme Corp customer filter."""
        sql = """
        SELECT so.Order_ID
        FROM dbo.tbl_SalesOrders so
        INNER JOIN dbo.tbl_Customers c ON so.Cust_ID = c.Cust_ID
        INNER JOIN dbo.tbl_OrderLineItems oli ON so.Order_ID = oli.Order_ID
        INNER JOIN dbo.tbl_Inventory_Master im ON oli.Item_SKU = im.Item_SKU
        WHERE c.Cust_Name = 'Acme Corp'
          AND so.Order_ID = 'SO-10047'
        """
        rows = self.adapter.execute_query("db-01-dev", sql)
        self.assertEqual(len(rows), 0, "DIST-2 Globex Corp order was erroneously matched by Acme Corp filter!")

    def test_erp_stage1_rejects_distractor_3_cancelled(self):
        """DIST-3 (Acme Corp Cancelled Order, SO-10012) must be rejected because OrderStatus is Cancelled."""
        sql = """
        SELECT so.Order_ID, so.OrderStatus
        FROM dbo.tbl_SalesOrders so
        INNER JOIN dbo.tbl_Customers c ON so.Cust_ID = c.Cust_ID
        INNER JOIN dbo.tbl_OrderLineItems oli ON so.Order_ID = oli.Order_ID
        INNER JOIN dbo.tbl_Inventory_Master im ON oli.Item_SKU = im.Item_SKU
        WHERE c.Cust_Name = 'Acme Corp'
          AND (im.Item_Description LIKE '%Laptop%' OR oli.Item_SKU LIKE '%LAPTOP%')
          AND so.OrderStatus = 'Completed'
          AND so.Order_ID = 'SO-10012'
        """
        rows = self.adapter.execute_query("db-01-dev", sql)
        self.assertEqual(len(rows), 0, "DIST-3 cancelled order was erroneously matched as Completed!")

    def test_erp_stage1_rejects_distractor_4_staged(self):
        """DIST-4 (Acme Corp Staged Order, SO-10048) has OrderStatus = 'Processing' and must not match."""
        sql = """
        SELECT so.Order_ID, so.OrderStatus
        FROM dbo.tbl_SalesOrders so
        INNER JOIN dbo.tbl_Customers c ON so.Cust_ID = c.Cust_ID
        INNER JOIN dbo.tbl_OrderLineItems oli ON so.Order_ID = oli.Order_ID
        INNER JOIN dbo.tbl_Inventory_Master im ON oli.Item_SKU = im.Item_SKU
        WHERE c.Cust_Name = 'Acme Corp'
          AND (im.Item_Description LIKE '%Laptop%' OR oli.Item_SKU LIKE '%LAPTOP%')
          AND so.OrderStatus = 'Completed'
          AND so.Order_ID = 'SO-10048'
        """
        rows = self.adapter.execute_query("db-01-dev", sql)
        self.assertEqual(len(rows), 0, "DIST-4 staged processing order was erroneously matched as Completed!")

    def test_erp_stage1_rejects_distractor_5_umbrella(self):
        """DIST-5 (Umbrella Corp Laptops, SO-10049) must not match Acme Corp."""
        sql = """
        SELECT so.Order_ID
        FROM dbo.tbl_SalesOrders so
        INNER JOIN dbo.tbl_Customers c ON so.Cust_ID = c.Cust_ID
        WHERE c.Cust_Name = 'Acme Corp' AND so.Order_ID = 'SO-10049'
        """
        rows = self.adapter.execute_query("db-01-dev", sql)
        self.assertEqual(len(rows), 0, "DIST-5 Umbrella Corp order was erroneously matched as Acme Corp!")

    def test_erp_stage1_rejects_distractor_6_initech(self):
        """DIST-6 (Initech Monitors, SO-10050) must not match Acme Corp or Laptop."""
        sql = """
        SELECT so.Order_ID
        FROM dbo.tbl_SalesOrders so
        INNER JOIN dbo.tbl_Customers c ON so.Cust_ID = c.Cust_ID
        WHERE c.Cust_Name = 'Acme Corp' AND so.Order_ID = 'SO-10050'
        """
        rows = self.adapter.execute_query("db-01-dev", sql)
        self.assertEqual(len(rows), 0, "DIST-6 Initech order was erroneously matched as Acme Corp!")

    def test_erp_stage1_fails_on_nonexistent_customer(self):
        """Querying an unknown customer must raise ValueError."""
        mock_adapter = MagicMock()
        mock_adapter.execute_query.return_value = []
        with patch.object(self.adapter, "execute_query", return_value=[]):
            with self.assertRaises(ValueError) as ctx:
                vcd.query_stage1_erp(self.adapter)
            self.assertIn("Stage 1 Failed", str(ctx.exception))

    def test_wms_stage2_resolves_target_pick(self):
        """Stage 2 resolves PK-8801 with status_id = 5 (Loaded) and HU-8841-PLT."""
        pick = vcd.query_stage2_wms(self.adapter, erp_order_id="SO-10045")
        self.assertEqual(pick["pick_id"], "PK-8801")
        self.assertEqual(pick["status_id"], 5)
        self.assertEqual(pick["handling_unit_id"], "HU-8841-PLT")
        self.assertEqual(pick["staged_dock_code"], "DOCK-04")
        self.assertEqual(pick["lpn_barcode"], "BC-LPN-8841029")

    def test_wms_stage2_distractor_picks_have_non_shipped_statuses(self):
        """Verify that distractor picks do NOT have status_id = 5 (Loaded) except finished trailers."""
        # DIST-1 (Chairs): status 2 (Picked)
        pick_dist1 = vcd.query_stage2_wms(self.adapter, erp_order_id="SO-10046")
        self.assertEqual(pick_dist1["status_id"], 2, "DIST-1 should have status_id 2 (Picked)")

        # DIST-4 (Staged at dock): status 4 (Staged)
        pick_dist4 = vcd.query_stage2_wms(self.adapter, erp_order_id="SO-10048")
        self.assertEqual(pick_dist4["status_id"], 4, "DIST-4 should have status_id 4 (Staged at Dock)")

        # DIST-3 (Cancelled): status 9 (Cancelled)
        pick_dist3 = vcd.query_stage2_wms(self.adapter, erp_order_id="SO-10012")
        self.assertEqual(pick_dist3["status_id"], 9, "DIST-3 should have status_id 9 (Cancelled)")
        self.assertIsNone(pick_dist3["handling_unit_id"])

        # DIST-5 (Allocated only): status 1 (Allocated)
        pick_dist5 = vcd.query_stage2_wms(self.adapter, erp_order_id="SO-10049")
        self.assertEqual(pick_dist5["status_id"], 1, "DIST-5 should have status_id 1 (Allocated)")
        self.assertIsNone(pick_dist5["handling_unit_id"])

    def test_wms_stage2_fails_on_nonexistent_order(self):
        """Querying nonexistent order in WMS raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            vcd.query_stage2_wms(self.adapter, erp_order_id="SO-99999-DOES-NOT-EXIST")
        self.assertIn("Stage 2 Failed", str(ctx.exception))

    def test_tms_stage3_resolves_target_manifest(self):
        """Stage 3 resolves MNF-2026-8801 with IN_TRANSIT and Apex Freight Express."""
        manifest = vcd.query_stage3_tms(self.adapter, handling_unit_id="HU-8841-PLT")
        self.assertEqual(manifest["Manifest_ID"], "MNF-2026-8801")
        self.assertEqual(manifest["Carrier_Name"], "Apex Freight Express")
        self.assertEqual(manifest["Tracking_Number"], "TRK-AFX-9948201")
        self.assertEqual(manifest["Waybill_Number"], "WB-884102")
        self.assertEqual(manifest["Shipment_Status"], "IN_TRANSIT")
        self.assertEqual(manifest["Consignee_Name"], "Acme Corp - Receiving Bay 2")

    def test_tms_stage3_distractor_handling_units(self):
        """Verify distractor handling units have appropriate non-target statuses and consignees."""
        # DIST-4 (Staged at dock): Shipment_Status is PENDING_PICKUP
        mnf_dist4 = vcd.query_stage3_tms(self.adapter, handling_unit_id="HU-8844-PLT")
        self.assertEqual(mnf_dist4["Shipment_Status"], "PENDING_PICKUP")
        self.assertIsNone(mnf_dist4["Dispatched_At"])

        # DIST-2 (Globex): Consignee is Globex Corporation Warehouse
        mnf_dist2 = vcd.query_stage3_tms(self.adapter, handling_unit_id="HU-8843-PLT")
        self.assertEqual(mnf_dist2["Consignee_Name"], "Globex Corporation Warehouse")
        self.assertEqual(mnf_dist2["Carrier_Name"], "Swift Global Logistics")

    def test_tms_stage3_fails_on_nonexistent_handling_unit(self):
        """Querying nonexistent handling unit in TMS raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            vcd.query_stage3_tms(self.adapter, handling_unit_id="HU-9999-NONEXISTENT")
        self.assertIn("Stage 3 Failed", str(ctx.exception))


class TestSQLBatchParserAndSanitization(unittest.TestCase):
    """Adversarially challenge T-SQL batch splitting, comment filtering, and formatting."""

    def test_split_sql_batches_standard_go(self):
        """Verify splitting on standard uppercase GO."""
        sql = "CREATE TABLE tbl_a (id INT);\nGO\nCREATE TABLE tbl_b (id INT);\nGO"
        batches = rm.split_sql_batches(sql)
        self.assertEqual(len(batches), 2)
        self.assertIn("tbl_a", batches[0])
        self.assertIn("tbl_b", batches[1])

    def test_split_sql_batches_case_insensitivity(self):
        """Verify case-insensitive splitting on 'go', 'Go', and 'GO'."""
        sql = "SELECT 1;\ngo\nSELECT 2;\nGo\nSELECT 3;\nGO"
        batches = rm.split_sql_batches(sql)
        self.assertEqual(len(batches), 3)

    def test_split_sql_batches_with_trailing_comments(self):
        """Verify GO followed by inline comment e.g. 'GO -- batch end' is split correctly."""
        sql = "SELECT 100;\nGO -- end of batch 1\nSELECT 200;\nGO   -- another comment"
        batches = rm.split_sql_batches(sql)
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0], "SELECT 100;")
        self.assertEqual(batches[1], "SELECT 200;")

    def test_split_sql_batches_crlf_windows_newlines(self):
        """Verify Windows CRLF line endings are split correctly without error."""
        sql = "SELECT 'line1';\r\nGO\r\nSELECT 'line2';\r\nGO\r\n"
        batches = rm.split_sql_batches(sql)
        self.assertEqual(len(batches), 2)

    def test_split_sql_batches_ignores_pure_comment_batches(self):
        """Verify batches containing only comments or blank whitespace are discarded."""
        sql = """
        -- Header comments
        -- More comments
        GO
        SELECT 42;
        GO
        -- Trailing comments only
        -- No SQL statements here
        GO
        """
        batches = rm.split_sql_batches(sql)
        self.assertEqual(len(batches), 1)
        self.assertIn("SELECT 42;", batches[0])

    def test_split_sql_batches_no_go(self):
        """A script with no GO delimiter must return exactly 1 batch."""
        sql = "SELECT 1;\nSELECT 2;\nSELECT 3;"
        batches = rm.split_sql_batches(sql)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0], sql)

    def test_get_batch_summary_skips_leading_comments(self):
        """get_batch_summary must skip comment lines and identify the first code statement."""
        batch = "-- Line 1 comment\n-- Line 2 comment\nCREATE TABLE dbo.test (id INT);"
        summary = rm.get_batch_summary(batch)
        self.assertEqual(summary, "CREATE TABLE dbo.test (id INT);")

    def test_get_batch_summary_truncates_long_lines(self):
        """get_batch_summary must truncate lines longer than max_chars with '...'."""
        long_line = "INSERT INTO dbo.very_long_table_name_with_extraordinary_length_and_columns VALUES (" + "1, " * 50 + ")"
        summary = rm.get_batch_summary(long_line, max_chars=40)
        self.assertTrue(summary.endswith("..."))
        self.assertEqual(len(summary), 43)  # 40 chars + 3 for '...'

    def test_apply_migration_missing_file_raises(self):
        """apply_migration on missing file must raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            rm.apply_migration(None, "db-01-dev", "/nonexistent/path/db.sql", dry_run=True)


class TestEndToEndSynthesisAndFormat(unittest.TestCase):
    """Adversarially challenge end-to-end report generation and assertion completeness."""

    def test_format_challenge_report_completeness(self):
        """Verify format_challenge_report generates all required domains and conclusion."""
        erp = {
            "Cust_ID": "CUST-00101",
            "Cust_Name": "Acme Corp",
            "Shipping_Address": "100 Industrial Pkwy",
            "Order_ID": "SO-10045",
            "PO_Number": "PO-ACM-2026-9921",
            "Order_Date": "2026-10-02",
            "OrderStatus": "Completed",
            "Payment_Status": "Paid",
            "Item_SKU": "SKU-LAPTOP-15-ENT",
            "Item_Description": "Enterprise Laptop 15-inch",
            "Quantity": 10,
            "Unit_Price": 1850.0,
            "Total_Amount": 20230.0,
        }
        wms = {
            "erp_order_ref": "SO-10045",
            "customer_po_ref": "PO-ACM-2026-9921",
            "pick_id": "PK-8801",
            "status_id": 5,
            "lot_number": "LOT-2026Q1-TECH",
            "bin_code": "Z1-A04-S02-B01",
            "qty_requested": 10,
            "qty_picked": 10,
            "handling_unit_id": "HU-8841-PLT",
            "lpn_barcode": "BC-LPN-8841029",
            "hu_type": "PALLET",
            "tare_weight_kg": 22.0,
            "staged_dock_code": "DOCK-04",
            "dock_loaded_at": "2026-10-04 10:45:00",
        }
        tms = {
            "Handling_Unit_Ref": "HU-8841-PLT",
            "BOL_Number": "BOL-2026-10045",
            "Consignee_Name": "Acme Corp - Receiving Bay 2",
            "Delivery_Address": "100 Industrial Pkwy",
            "Delivery_Zip": "78701",
            "Special_Instructions": "Liftgate required",
            "Carrier_Name": "Apex Freight Express",
            "Carrier_ID": "CARR-APEX",
            "Service_Level": "EXPEDITED_LTL",
            "Contact_Phone": "+1-800-555-0199",
            "Load_ID": "LD-2026-9041",
            "Trailer_Number": "TRL-8821-X",
            "Dispatched_At": "2026-10-04 11:30:00",
            "Estimated_Delivery": "2026-10-06 17:00:00",
            "Waybill_Number": "WB-884102",
            "Tracking_Number": "TRK-AFX-9948201",
            "Pallet_Count": 1,
            "Gross_Weight_LBS": 48.5,
            "Physical_Dimensions": "48x40x42 IN",
            "Shipment_Status": "IN_TRANSIT",
        }

        report = vcd.format_challenge_report(erp, wms, tms)
        self.assertIn("STAGE 1] ERP DOMAIN RESOLUTION", report)
        self.assertIn("STAGE 2] WMS DOMAIN RESOLUTION", report)
        self.assertIn("STAGE 3] TMS DOMAIN RESOLUTION", report)
        self.assertIn("FINAL VERIFICATION SYNTHESIS", report)
        self.assertIn("CONCLUSION: Customer 'Acme Corp' Laptop Order (SO-10045) HAS SHIPPED.", report)
        self.assertIn("Carrier:            Apex Freight Express", report)
        self.assertIn("Tracking Number:    TRK-AFX-9948201", report)
        self.assertIn("Waybill Number:     WB-884102", report)
        self.assertIn("Current Status:     IN_TRANSIT", report)

    def test_run_cross_db_verification_mock_end_to_end(self):
        """run_cross_db_verification in mock mode must succeed and return True."""
        result = vcd.run_cross_db_verification(mock=True)
        self.assertTrue(result)


class TestLiveAzureSQLExecution(unittest.TestCase):
    """Adversarially challenge live Azure SQL execution against eosr-db-server.database.windows.net."""

    def test_live_cross_db_verification(self):
        """Execute verify_cross_db_challenge live against Azure SQL when Entra ID auth is available."""
        token = None
        try:
            token = vcd.resolve_entra_token()
        except Exception as ex:
            self.skipTest(f"Live Entra ID token not available in test runner context: {ex}")

        if not token:
            self.skipTest("No token available for live testing.")

        result = vcd.run_cross_db_verification(server="eosr-db-server.database.windows.net", mock=False)
        self.assertTrue(result)

    def test_live_unified_e2e_runner(self):
        """Execute full E2E test runner and assert 100% pass rate."""
        cmd = [sys.executable, str(REPO_ROOT / "e2e_tests" / "test_e2e_runner.py")]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"E2E test runner failed: {res.stderr}")
        self.assertIn("100% PASS", res.stdout)
        self.assertIn("127/127", res.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
