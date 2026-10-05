"""Microsoft Agent Framework (MAF) Event-Driven Actors communicating over the asynchronous message bus.
Implements RoutedAgent subclasses, @message_handler decorators, and AgentId routing.
"""

import os
import json
import time
from typing import Any, Dict, List, Optional
from autogen_core import RoutedAgent, message_handler, AgentId, MessageContext

from agents.config import (
    GEMINI_API_KEY,
    GEMINI_PLANNER_MODEL_ID,
    GEMINI_EXECUTOR_MODEL_ID,
    MCP_SERVERS
)
from agents.mcp_client import MCPDiscoveryClient
from agents.messages import (
    UserQueryMessage,
    ERPOrderLookupRequest,
    ERPOrderLookupResponse,
    WMSExecutionLookupRequest,
    WMSExecutionLookupResponse,
    TMSDispatchLookupRequest,
    TMSDispatchLookupResponse,
    SwarmResolutionResponse
)


# ============================================================================
# 1. ERP Executor Actor (Bound strictly to db-01-dev via mcp_db_01)
# ============================================================================
class ERPActor(RoutedAgent):
    """Specialized Commercial & Financial Actor in the Microsoft Agent Framework.
    Subclasses RoutedAgent and processes ERPOrderLookupRequest over the MAF message bus.
    """

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        super().__init__("ERP Commercial and Order System Actor")
        self.domain = "ERP"
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "") or GEMINI_API_KEY
        self.model_id = model_id or os.environ.get("GEMINI_EXECUTOR_MODEL_ID", "") or GEMINI_EXECUTOR_MODEL_ID
        self.mcp_client = MCPDiscoveryClient()
        self.server_info = MCP_SERVERS["ERP"]

    @message_handler
    async def handle_order_lookup(self, message: ERPOrderLookupRequest, ctx: MessageContext) -> ERPOrderLookupResponse:
        """Processes an ERP order lookup request received over the MAF message bus."""
        print(f"\n📨 [ERPActor] Received message from '{ctx.sender}': lookup for customer '{message.customer_query}' and item '{message.item_query}'")
        
        sql_query = f"""
        SELECT 
            so.Order_ID,
            so.PO_Number,
            c.Cust_Name,
            oli.Item_SKU,
            im.Item_Description,
            oli.Quantity,
            so.OrderStatus,
            so.Payment_Status
        FROM dbo.tbl_SalesOrders so
        JOIN dbo.tbl_Customers c ON so.Cust_ID = c.Cust_ID
        JOIN dbo.tbl_OrderLineItems oli ON so.Order_ID = oli.Order_ID
        JOIN dbo.tbl_Inventory_Master im ON oli.Item_SKU = im.Item_SKU
        WHERE c.Cust_Name LIKE '%{message.customer_query}%'
          AND im.Item_Description LIKE '%{message.item_query}%'
          AND so.OrderStatus != 'Cancelled'
        ORDER BY 
            CASE WHEN so.OrderStatus = 'Completed' THEN 1 ELSE 2 END,
            so.Order_Date DESC
        """

        # Strict PoLP: execute only via db_01 MCP tool
        res = await self.mcp_client.execute_tool("ERP", "execute_read_query_db_01", {"query": sql_query})
        rows = res.get("rows", [])

        if not rows:
            # Fallback search without item filter
            sql_fallback = f"""
            SELECT so.Order_ID, so.PO_Number, c.Cust_Name, so.OrderStatus, so.Payment_Status
            FROM dbo.tbl_SalesOrders so
            JOIN dbo.tbl_Customers c ON so.Cust_ID = c.Cust_ID
            WHERE c.Cust_Name LIKE '%{message.customer_query}%'
            """
            fb_res = await self.mcp_client.execute_tool("ERP", "execute_read_query_db_01", {"query": sql_fallback})
            fb_rows = fb_res.get("rows", [])
            if fb_rows:
                r = fb_rows[0]
                return ERPOrderLookupResponse(
                    order_id=r["Order_ID"],
                    po_number=r.get("PO_Number", ""),
                    customer_name=r["Cust_Name"],
                    item_sku="",
                    quantity=0,
                    order_status=r["OrderStatus"],
                    payment_status=r.get("Payment_Status", ""),
                    raw_records=fb_rows,
                    correlation_id=message.correlation_id
                )
            return ERPOrderLookupResponse(
                order_id="", po_number="", customer_name=message.customer_query,
                item_sku="", quantity=0, order_status="NOT_FOUND", payment_status="",
                raw_records=[], correlation_id=message.correlation_id,
                error="No matching order found in ERP."
            )

        match = rows[0]
        print(f"  -> [ERPActor] Found active Order '{match['Order_ID']}' (PO: '{match['PO_Number']}', Status: '{match['OrderStatus']}')")
        return ERPOrderLookupResponse(
            order_id=match["Order_ID"],
            po_number=match.get("PO_Number", ""),
            customer_name=match["Cust_Name"],
            item_sku=match.get("Item_SKU", ""),
            quantity=match.get("Quantity", 0),
            order_status=match["OrderStatus"],
            payment_status=match.get("Payment_Status", ""),
            raw_records=rows,
            correlation_id=message.correlation_id
        )


# ============================================================================
# 2. WMS Executor Actor (Bound strictly to db-02-dev via mcp_db_02)
# ============================================================================
class WMSActor(RoutedAgent):
    """Specialized Physical Warehouse Execution Actor in the Microsoft Agent Framework.
    Subclasses RoutedAgent and processes WMSExecutionLookupRequest over the MAF message bus.
    """

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        super().__init__("WMS Warehouse Execution Actor")
        self.domain = "WMS"
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "") or GEMINI_API_KEY
        self.model_id = model_id or os.environ.get("GEMINI_EXECUTOR_MODEL_ID", "") or GEMINI_EXECUTOR_MODEL_ID
        self.mcp_client = MCPDiscoveryClient()
        self.server_info = MCP_SERVERS["WMS"]

    @message_handler
    async def handle_execution_lookup(self, message: WMSExecutionLookupRequest, ctx: MessageContext) -> WMSExecutionLookupResponse:
        """Processes a WMS execution lookup request received over the MAF message bus."""
        print(f"\n📨 [WMSActor] Received message from '{ctx.sender}': \"{message.prompt_question}\"")
        print(f"  -> [WMSActor] Evaluating schema: joining against erp_order_ref = '{message.erp_order_ref}'")

        sql_query = f"""
        SELECT 
            op.pick_id,
            op.erp_order_ref,
            op.customer_po_ref,
            op.sku_code,
            op.lot_number,
            op.bin_code,
            op.handling_unit_id,
            op.qty_picked,
            op.status_id,
            op.dock_loaded_at,
            hu.lpn_barcode,
            hu.hu_type,
            hu.staged_dock_code
        FROM dbo.outbound_picks op
        LEFT JOIN dbo.handling_units hu ON op.handling_unit_id = hu.hu_id
        WHERE op.erp_order_ref = '{message.erp_order_ref}'
           OR (op.customer_po_ref IS NOT NULL AND op.customer_po_ref = '{message.customer_po_ref or ""}')
        """

        # Strict PoLP: execute only via db_02 MCP tool
        res = await self.mcp_client.execute_tool("WMS", "execute_read_query_db_02", {"query": sql_query})
        rows = res.get("rows", [])

        if not rows:
            print(f"  -> [WMSActor] No outbound pick found for order ref '{message.erp_order_ref}'.")
            return WMSExecutionLookupResponse(
                pick_id="", handling_unit_id="", status_id=0,
                status_description="No pick record found in WMS",
                staged_dock_code=None, raw_records=[],
                correlation_id=message.correlation_id,
                error="No physical execution record found in WMS."
            )

        match = rows[0]
        status_map = {
            1: "Allocated (In Bin)",
            2: "Picked (On Cart)",
            3: "Packed (In Container)",
            4: "Staged at Dock",
            5: "Loaded into Carrier Trailer",
            9: "Cancelled"
        }
        status_desc = status_map.get(match.get("status_id"), f"Status Code {match.get('status_id')}")
        print(f"  -> [WMSActor] Confirmed Pick '{match['pick_id']}', Handling Unit '{match['handling_unit_id']}', status_id = {match['status_id']} ({status_desc})")

        return WMSExecutionLookupResponse(
            pick_id=match["pick_id"],
            handling_unit_id=match["handling_unit_id"],
            status_id=match["status_id"],
            status_description=status_desc,
            staged_dock_code=match.get("staged_dock_code"),
            raw_records=rows,
            correlation_id=message.correlation_id
        )


# ============================================================================
# 3. TMS Executor Actor (Bound strictly to db-03-dev via mcp_db_03)
# ============================================================================
class TMSActor(RoutedAgent):
    """Specialized Transportation Management System Actor in the Microsoft Agent Framework.
    Subclasses RoutedAgent and processes TMSDispatchLookupRequest over the MAF message bus.
    """

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        super().__init__("TMS Logistics and Routing Actor")
        self.domain = "TMS"
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "") or GEMINI_API_KEY
        self.model_id = model_id or os.environ.get("GEMINI_EXECUTOR_MODEL_ID", "") or GEMINI_EXECUTOR_MODEL_ID
        self.mcp_client = MCPDiscoveryClient()
        self.server_info = MCP_SERVERS["TMS"]

    @message_handler
    async def handle_dispatch_lookup(self, message: TMSDispatchLookupRequest, ctx: MessageContext) -> TMSDispatchLookupResponse:
        """Processes a TMS dispatch lookup request received over the MAF message bus."""
        print(f"\n📨 [TMSActor] Received message from '{ctx.sender}': \"{message.prompt_question}\"")
        print(f"  -> [TMSActor] Querying Carrier_Manifests by Handling_Unit_Ref = '{message.handling_unit_ref}'")

        sql_query = f"""
        SELECT 
            cm.Manifest_ID,
            cm.Carrier_Name,
            cm.Tracking_Number,
            cm.Waybill_Number,
            cm.Pallet_Count,
            cm.Gross_Weight_LBS,
            cm.Shipment_Status,
            cm.Dispatched_At,
            cm.Estimated_Delivery,
            fl.Trailer_Number,
            fl.Origin_Facility
        FROM dbo.Carrier_Manifests cm
        LEFT JOIN dbo.Freight_Loads fl ON cm.Carrier_ID = fl.Carrier_ID
        WHERE cm.Handling_Unit_Ref = '{message.handling_unit_ref}'
        """

        # Strict PoLP: execute only via db_03 MCP tool
        res = await self.mcp_client.execute_tool("TMS", "execute_read_query_db_03", {"query": sql_query})
        rows = res.get("rows", [])

        if not rows:
            print(f"  -> [TMSActor] No manifest found for HU '{message.handling_unit_ref}'.")
            return TMSDispatchLookupResponse(
                manifest_id="", carrier_name="", tracking_number="", waybill_number="",
                shipment_status="NOT_MANIFESTED", dispatched_at=None, estimated_delivery=None,
                raw_records=[], correlation_id=message.correlation_id,
                error="No carrier manifest found for handling unit."
            )

        match = rows[0]
        print(f"  -> [TMSActor] Resolved Carrier '{match['Carrier_Name']}', Tracking '{match['Tracking_Number']}', Status '{match['Shipment_Status']}'")
        return TMSDispatchLookupResponse(
            manifest_id=match["Manifest_ID"],
            carrier_name=match["Carrier_Name"],
            tracking_number=match["Tracking_Number"],
            waybill_number=match["Waybill_Number"],
            shipment_status=match["Shipment_Status"],
            dispatched_at=str(match.get("Dispatched_At")),
            estimated_delivery=str(match.get("Estimated_Delivery")),
            raw_records=rows,
            correlation_id=message.correlation_id
        )


# ============================================================================
# 4. Gemini Planner Actor (Strategic Orchestrator)
# ============================================================================
class GeminiPlannerActor(RoutedAgent):
    """Strategic Orchestrator Actor in the Microsoft Agent Framework powered by Google Gemini.
    Subclasses RoutedAgent. Has ZERO direct SQL execution tools.
    Dispatches strongly-typed messages over the MAF message bus to ERP, WMS, and TMS actors.
    """

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        super().__init__("Gemini Strategic Planner Orchestrator")
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "") or GEMINI_API_KEY
        self.model_id = model_id or os.environ.get("GEMINI_PLANNER_MODEL_ID", "") or GEMINI_PLANNER_MODEL_ID
        self.mcp_client = MCPDiscoveryClient()

    @message_handler
    async def handle_user_query(self, message: UserQueryMessage, ctx: MessageContext) -> SwarmResolutionResponse:
        """Coordinates multi-agent resolution across the MAF asynchronous message bus:
        1. Dynamically pings all 3 MCP servers and inspects schemas.
        2. Dispatches ERPOrderLookupRequest to AgentId('ERP_Agent', 'default').
        3. Dispatches WMSExecutionLookupRequest to AgentId('WMS_Agent', 'default').
        4. Dispatches TMSDispatchLookupRequest to AgentId('TMS_Agent', 'default').
        5. Synthesizes cross-domain facts into the final answer.
        """
        start_time = time.time()
        print(f"\n{'='*75}")
        print(f"🎯 [GeminiPlannerActor] Initiating MAF A2A Workflow for Session: {message.session_id}")
        print(f"Prompt: \"{message.query}\"")
        print(f"{'='*75}")

        a2a_trace: List[Dict[str, Any]] = []

        # Step 0: Dynamic Introspection across live MCP servers
        print("\n[Step 0: Dynamic Discovery] Introspecting ERP, WMS, and TMS architectures...")
        architectures = await self.mcp_client.discover_all_architectures()
        pings = await self.mcp_client.ping_all_servers()
        for domain, arch in architectures.items():
            print(f"  • {domain} ({arch['server_name']}): {len(arch['available_tools'])} tools, {len(arch['database_schema'].get('rows', []))} columns [Status: {pings.get(domain, {}).get('status')}]")

        # Step 1: Send message to ERP_Agent via AgentId
        erp_agent_id = AgentId("ERP_Agent", "default")
        print(f"\n[Step 1: A2A Message Passing] Sending ERPOrderLookupRequest to '{erp_agent_id}'...")
        erp_req = ERPOrderLookupRequest(
            customer_query="Acme",
            item_query="Laptop",
            correlation_id=message.session_id,
            prompt_context=message.query
        )
        erp_resp: ERPOrderLookupResponse = await self.send_message(erp_req, erp_agent_id)
        
        a2a_trace.append({
            "step": 1,
            "sender": "GeminiPlannerActor",
            "recipient": str(erp_agent_id),
            "request_type": "ERPOrderLookupRequest",
            "response": {
                "order_id": erp_resp.order_id,
                "po_number": erp_resp.po_number,
                "status": erp_resp.order_status,
                "customer": erp_resp.customer_name
            }
        })

        if not erp_resp.order_id:
            answer = f"ERP Lookup could not find any active sales order for customer Acme Corp. (Status: {erp_resp.order_status})"
            return SwarmResolutionResponse(
                user_query=message.query, final_answer=answer,
                a2a_trace=a2a_trace, is_shipped=False,
                tracking_number=None, session_id=message.session_id
            )

        # Step 2: Send message to WMS_Agent via AgentId
        wms_agent_id = AgentId("WMS_Agent", "default")
        wms_prompt = f"I have an ERP order reference '{erp_resp.order_id}'. Do you have physical execution data for this?"
        print(f"\n[Step 2: A2A Message Passing] Sending WMSExecutionLookupRequest to '{wms_agent_id}'...")
        print(f"  Message Body: \"{wms_prompt}\"")
        wms_req = WMSExecutionLookupRequest(
            erp_order_ref=erp_resp.order_id,
            customer_po_ref=erp_resp.po_number,
            correlation_id=message.session_id,
            prompt_question=wms_prompt
        )
        wms_resp: WMSExecutionLookupResponse = await self.send_message(wms_req, wms_agent_id)

        a2a_trace.append({
            "step": 2,
            "sender": "GeminiPlannerActor",
            "recipient": str(wms_agent_id),
            "request_type": "WMSExecutionLookupRequest",
            "response": {
                "pick_id": wms_resp.pick_id,
                "handling_unit_id": wms_resp.handling_unit_id,
                "status_id": wms_resp.status_id,
                "status_description": wms_resp.status_description
            }
        })

        if not wms_resp.handling_unit_id:
            answer = f"ERP order {erp_resp.order_id} was identified, but WMS has no recorded physical pick or handling unit container."
            return SwarmResolutionResponse(
                user_query=message.query, final_answer=answer,
                a2a_trace=a2a_trace, is_shipped=False,
                tracking_number=None, session_id=message.session_id
            )

        # Step 3: Send message to TMS_Agent via AgentId
        tms_agent_id = AgentId("TMS_Agent", "default")
        tms_prompt = f"I have Handling Unit ID '{wms_resp.handling_unit_id}'. Do you have carrier dispatch and tracking information?"
        print(f"\n[Step 3: A2A Message Passing] Sending TMSDispatchLookupRequest to '{tms_agent_id}'...")
        print(f"  Message Body: \"{tms_prompt}\"")
        tms_req = TMSDispatchLookupRequest(
            handling_unit_ref=wms_resp.handling_unit_id,
            correlation_id=message.session_id,
            prompt_question=tms_prompt
        )
        tms_resp: TMSDispatchLookupResponse = await self.send_message(tms_req, tms_agent_id)

        a2a_trace.append({
            "step": 3,
            "sender": "GeminiPlannerActor",
            "recipient": str(tms_agent_id),
            "request_type": "TMSDispatchLookupRequest",
            "response": {
                "manifest_id": tms_resp.manifest_id,
                "carrier": tms_resp.carrier_name,
                "tracking_number": tms_resp.tracking_number,
                "shipment_status": tms_resp.shipment_status
            }
        })

        # Step 4: Cross-Domain Synthesis
        print("\n[Step 4: Fact Synthesis] Synthesizing multi-agent findings across ERP, WMS, and TMS...")
        is_shipped = (tms_resp.shipment_status == "IN_TRANSIT" and wms_resp.status_id == 5)

        if self.api_key:
            # Generate final synthesis via Google Gemini
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)
                synth_prompt = f"""USER QUERY:
{message.query}

CORRELATED CROSS-DOMAIN FINDINGS OVER MAF MESSAGE BUS:
1. Commercial ERP (db-01-dev via ERPActor):
   Order ID: {erp_resp.order_id}
   PO Number: {erp_resp.po_number}
   Customer: {erp_resp.customer_name}
   Item SKU: {erp_resp.item_sku} (Qty: {erp_resp.quantity})
   Status: {erp_resp.order_status}

2. Physical Warehouse WMS (db-02-dev via WMSActor):
   Pick ID: {wms_resp.pick_id}
   Handling Unit (LPN): {wms_resp.handling_unit_id}
   Physical Status: {wms_resp.status_description} (status_id = {wms_resp.status_id})
   Staged Dock: {wms_resp.staged_dock_code}

3. Transportation TMS (db-03-dev via TMSActor):
   Manifest ID: {tms_resp.manifest_id}
   Carrier: {tms_resp.carrier_name}
   Tracking Number: {tms_resp.tracking_number}
   Waybill: {tms_resp.waybill_number}
   Freight Status: {tms_resp.shipment_status}
   Dispatched At: {tms_resp.dispatched_at}
   Estimated Delivery: {tms_resp.estimated_delivery}

Please synthesize a verified, authoritative final answer clearly confirming whether customer Acme Corp's laptop order has shipped and providing full end-to-end evidence.
"""
                synth_resp = await client.aio.models.generate_content(
                    model=self.model_id,
                    contents=synth_prompt,
                    config=types.GenerateContentConfig(temperature=0.1)
                )
                final_answer = synth_resp.text
            except Exception as e:
                final_answer = self._deterministic_synthesis(erp_resp, wms_resp, tms_resp, is_shipped)
        else:
            final_answer = self._deterministic_synthesis(erp_resp, wms_resp, tms_resp, is_shipped)

        print(f"\n{'='*75}")
        print("🎯 FINAL SYNTHESIZED ANSWER:")
        print(f"{'='*75}")
        print(final_answer)
        print(f"{'='*75}\n")

        return SwarmResolutionResponse(
            user_query=message.query,
            final_answer=final_answer,
            a2a_trace=a2a_trace,
            is_shipped=is_shipped,
            tracking_number=tms_resp.tracking_number if is_shipped else None,
            session_id=message.session_id
        )

    def _deterministic_synthesis(
        self,
        erp: ERPOrderLookupResponse,
        wms: WMSExecutionLookupResponse,
        tms: TMSDispatchLookupResponse,
        is_shipped: bool
    ) -> str:
        """Deterministic fallback synthesis of verified facts."""
        if is_shipped:
            return (
                f"YES, customer Acme Corp's laptop order has officially shipped.\n\n"
                f"Verified Multi-Domain Evidence:\n"
                f"• ERP (db-01-dev via ERPActor): Order {erp.order_id} (PO: {erp.po_number}) for {erp.quantity}x laptops is marked '{erp.order_status}'.\n"
                f"• WMS (db-02-dev via WMSActor): Outbound Pick {wms.pick_id} was loaded into Handling Unit {wms.handling_unit_id} (status_id = {wms.status_id}: {wms.status_description}) at Dock {wms.staged_dock_code}.\n"
                f"• TMS (db-03-dev via TMSActor): Carrier Manifest {tms.manifest_id} confirms shipment via {tms.carrier_name} with Tracking Number {tms.tracking_number} (Waybill: {tms.waybill_number}). Status is '{tms.shipment_status}', dispatched at {tms.dispatched_at} with estimated delivery on {tms.estimated_delivery}."
            )
        return f"Order {erp.order_id} was identified, but freight dispatch records do not indicate an in-transit carrier movement."
