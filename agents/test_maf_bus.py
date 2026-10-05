"""Unit and Integration Test Suite for the MAF Asynchronous Message Bus and Event-Driven Actors."""

import sys
import os
import asyncio
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from autogen_core import AgentId, SingleThreadedAgentRuntime
from agents.bus_runtime import MAFMessageBusManager
from agents.actors import ERPActor, WMSActor, TMSActor, GeminiPlannerActor
from agents.messages import (
    UserQueryMessage,
    ERPOrderLookupRequest,
    ERPOrderLookupResponse,
    WMSExecutionLookupRequest,
    WMSExecutionLookupResponse,
    TMSDispatchLookupRequest,
    TMSDispatchLookupResponse
)


class TestMAFMessageBus(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.bus_manager = MAFMessageBusManager()
        self.runtime = await self.bus_manager.initialize_and_start()

    async def asyncTearDown(self):
        await self.bus_manager.shutdown()

    async def test_erp_actor_direct_message(self):
        """Verify ERPActor processes ERPOrderLookupRequest over the MAF runtime."""
        print("\n[Test] Testing ERPActor message handler over MAF bus...")
        req = ERPOrderLookupRequest(
            customer_query="Acme",
            item_query="Laptop",
            correlation_id="test_erp_001"
        )
        resp: ERPOrderLookupResponse = await self.runtime.send_message(req, AgentId("ERP_Agent", "default"))
        self.assertIsInstance(resp, ERPOrderLookupResponse)
        self.assertEqual(resp.order_id, "SO-10045")
        self.assertEqual(resp.customer_name, "Acme Corp")
        self.assertEqual(resp.order_status, "Completed")
        print("  -> Passed: ERPActor successfully returned SO-10045 over MAF bus!")

    async def test_wms_actor_direct_message(self):
        """Verify WMSActor processes WMSExecutionLookupRequest over the MAF runtime."""
        print("\n[Test] Testing WMSActor message handler over MAF bus...")
        req = WMSExecutionLookupRequest(
            erp_order_ref="SO-10045",
            customer_po_ref="PO-ACM-2026-9921",
            correlation_id="test_wms_001",
            prompt_question="I have an ERP order reference 'SO-10045'. Do you have physical execution data for this?"
        )
        resp: WMSExecutionLookupResponse = await self.runtime.send_message(req, AgentId("WMS_Agent", "default"))
        self.assertIsInstance(resp, WMSExecutionLookupResponse)
        self.assertEqual(resp.pick_id, "PK-8801")
        self.assertEqual(resp.handling_unit_id, "HU-8841-PLT")
        self.assertEqual(resp.status_id, 5)
        print("  -> Passed: WMSActor successfully returned HU-8841-PLT and status_id=5 over MAF bus!")

    async def test_tms_actor_direct_message(self):
        """Verify TMSActor processes TMSDispatchLookupRequest over the MAF runtime."""
        print("\n[Test] Testing TMSActor message handler over MAF bus...")
        req = TMSDispatchLookupRequest(
            handling_unit_ref="HU-8841-PLT",
            correlation_id="test_tms_001",
            prompt_question="I have Handling Unit ID 'HU-8841-PLT'. Do you have carrier dispatch data?"
        )
        resp: TMSDispatchLookupResponse = await self.runtime.send_message(req, AgentId("TMS_Agent", "default"))
        self.assertIsInstance(resp, TMSDispatchLookupResponse)
        self.assertEqual(resp.manifest_id, "MNF-2026-8801")
        self.assertEqual(resp.tracking_number, "TRK-AFX-9948201")
        self.assertEqual(resp.shipment_status, "IN_TRANSIT")
        print("  -> Passed: TMSActor successfully returned TRK-AFX-9948201 and IN_TRANSIT over MAF bus!")

    async def test_full_a2a_orchestration_workflow(self):
        """Verify full multi-hop A2A workflow coordinated by GeminiPlannerActor."""
        print("\n[Test] Testing full A2A multi-hop orchestration: Planner -> ERP -> WMS -> TMS...")
        user_query = "Has customer Acme Corp's laptop order shipped?"
        resp = await self.bus_manager.send_user_query(user_query)

        self.assertTrue(resp.is_shipped)
        self.assertEqual(resp.tracking_number, "TRK-AFX-9948201")
        self.assertEqual(len(resp.a2a_trace), 3)

        # Verify exact A2A message sequence
        self.assertEqual(resp.a2a_trace[0]["recipient"], "ERP_Agent/default")
        self.assertEqual(resp.a2a_trace[0]["response"]["order_id"], "SO-10045")

        self.assertEqual(resp.a2a_trace[1]["recipient"], "WMS_Agent/default")
        self.assertEqual(resp.a2a_trace[1]["response"]["handling_unit_id"], "HU-8841-PLT")
        self.assertEqual(resp.a2a_trace[1]["response"]["status_id"], 5)

        self.assertEqual(resp.a2a_trace[2]["recipient"], "TMS_Agent/default")
        self.assertEqual(resp.a2a_trace[2]["response"]["tracking_number"], "TRK-AFX-9948201")

        print("  -> Passed: End-to-end A2A multi-hop workflow successfully completed over MAF message bus!")


if __name__ == "__main__":
    unittest.main()
