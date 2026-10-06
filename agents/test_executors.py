"""Verification test suite for ERP_Agent, WMS_Agent, and TMS_Agent MAF executors."""

import sys
import os
import asyncio
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agents.executors import ERP_Agent, WMS_Agent, TMS_Agent


class TestExecutors(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.erp_agent = ERP_Agent()
        self.wms_agent = WMS_Agent()
        self.tms_agent = TMS_Agent()

    async def test_domain_isolation_guardrail(self):
        """Verify that an agent is physically blocked from calling tools belonging to another domain."""
        print("\n[Test] Verifying cross-domain tool access prevention...")

        # ERP_Agent attempting to call WMS tool must fail
        with self.assertRaises(PermissionError):
            await self.erp_agent.execute_tool("get_schema_db_02")

        # WMS_Agent attempting to call TMS tool must fail
        with self.assertRaises(PermissionError):
            await self.wms_agent.execute_tool("execute_read_query_db_03", {"query": "SELECT 1"})

        # TMS_Agent attempting to call ERP tool must fail
        with self.assertRaises(PermissionError):
            await self.tms_agent.execute_tool("get_schema_db_01")

        print("  -> Passed: Cross-domain security guardrail strictly enforced!")

    async def test_erp_agent_live_execution(self):
        """Verify ERP_Agent live tool execution against mcp_db_01."""
        print("\n[Test] Testing ERP_Agent on db-01-dev...")
        tables = await self.erp_agent.execute_tool("get_schema_db_01")
        self.assertEqual(tables.get("status"), "success")
        table_names = [r["TABLE_NAME"] for r in tables.get("rows", [])]
        self.assertIn("tbl_Customers", table_names)
        self.assertIn("tbl_SalesOrders", table_names)

        # Query test
        query_res = await self.erp_agent.execute_tool(
            "execute_read_query_db_01",
            {"query": "SELECT Cust_ID, Cust_Name FROM dbo.tbl_Customers WHERE Cust_Name = 'Acme Corp'"}
        )
        self.assertEqual(query_res.get("status"), "success")
        self.assertEqual(len(query_res.get("rows", [])), 1)
        self.assertEqual(query_res["rows"][0]["Cust_ID"], "CUST-00101")
        print("  -> Passed: ERP_Agent resolved Acme Corp successfully!")

    async def test_wms_agent_live_execution(self):
        """Verify WMS_Agent live tool execution against mcp_db_02."""
        print("\n[Test] Testing WMS_Agent on db-02-dev...")
        tables = await self.wms_agent.execute_tool("get_schema_db_02")
        self.assertEqual(tables.get("status"), "success")
        table_names = [r["TABLE_NAME"] for r in tables.get("rows", [])]
        self.assertIn("outbound_picks", table_names)
        self.assertIn("handling_units", table_names)

        # Query test
        query_res = await self.wms_agent.execute_tool(
            "execute_read_query_db_02",
            {"query": "SELECT pick_id, handling_unit_id, status_id FROM dbo.outbound_picks WHERE pick_id = 'PK-8801'"}
        )
        self.assertEqual(query_res.get("status"), "success")
        self.assertEqual(len(query_res.get("rows", [])), 1)
        self.assertEqual(query_res["rows"][0]["handling_unit_id"], "HU-8841-PLT")
        print("  -> Passed: WMS_Agent resolved pick PK-8801 and HU-8841-PLT successfully!")

    async def test_tms_agent_live_execution(self):
        """Verify TMS_Agent live tool execution against mcp_db_03."""
        print("\n[Test] Testing TMS_Agent on db-03-dev...")
        tables = await self.tms_agent.execute_tool("get_schema_db_03")
        self.assertEqual(tables.get("status"), "success")
        table_names = [r["TABLE_NAME"] for r in tables.get("rows", [])]
        self.assertIn("Carrier_Manifests", table_names)
        self.assertIn("Freight_Loads", table_names)

        # Query test
        query_res = await self.tms_agent.execute_tool(
            "execute_read_query_db_03",
            {"query": "SELECT Carrier_Name, Tracking_Number, Shipment_Status FROM dbo.Carrier_Manifests WHERE Handling_Unit_Ref = 'HU-8841-PLT'"}
        )
        self.assertEqual(query_res.get("status"), "success")
        self.assertEqual(len(query_res.get("rows", [])), 1)
        self.assertEqual(query_res["rows"][0]["Tracking_Number"], "TRK-AFX-9948201")
        print("  -> Passed: TMS_Agent resolved tracking TRK-AFX-9948201 successfully!")

    async def test_preflight_awaiting_gemini_key(self):
        """Verify preflight task execution raises RuntimeError when GEMINI_API_KEY is missing."""
        print("\n[Test] Testing preflight task execution awaiting GEMINI_API_KEY...")
        agent = ERP_Agent(api_key="")
        with self.assertRaises(RuntimeError) as ctx:
            await agent.execute_task("Find Acme orders")
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))
        print("  -> Passed: Preflight verification correctly enforces GEMINI_API_KEY requirement!")


if __name__ == "__main__":
    unittest.main()
