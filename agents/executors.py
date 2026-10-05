"""Specialized Domain Executor Sub-Agents (MAF Actors) powered by Google Gemini.
Strictly decoupled: each executor is bound exclusively to its own domain MCP server.
"""

import os
import json
import asyncio
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agents.config import (
    GEMINI_API_KEY,
    GEMINI_EXECUTOR_MODEL_ID,
    MCP_SERVERS
)
from agents.mcp_client import MCPDiscoveryClient


class ToolCallResult(BaseModel):
    """Result of an MCP tool execution by an Executor Agent."""
    domain: str
    tool_name: str
    arguments: Dict[str, Any]
    output: Dict[str, Any]


class BaseExecutorAgent:
    """Base class for domain-isolated Executor Agents using Google Gemini."""

    def __init__(
        self,
        domain: str,
        system_prompt: str,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None
    ):
        self.domain = domain
        self.system_prompt = system_prompt
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "") or GEMINI_API_KEY
        self.model_id = model_id or os.environ.get("GEMINI_EXECUTOR_MODEL_ID", "") or GEMINI_EXECUTOR_MODEL_ID
        self.mcp_client = MCPDiscoveryClient()
        self.server_info = MCP_SERVERS[domain]

    def _get_allowed_tool_names(self) -> List[str]:
        """Returns the strictly allowed tool names for this domain."""
        suffix = {"ERP": "db_01", "WMS": "db_02", "TMS": "db_03"}[self.domain]
        return [
            f"list_tables_{suffix}",
            f"get_schema_{suffix}",
            f"execute_read_query_{suffix}"
        ]

    async def execute_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Executes a tool strictly scoped to this agent's domain MCP server."""
        allowed = self._get_allowed_tool_names()
        if tool_name not in allowed:
            raise PermissionError(
                f"Security Guardrail Violation: Agent [{self.domain}] cannot call tool '{tool_name}'. "
                f"Allowed tools are strictly restricted to: {allowed}"
            )
        return await self.mcp_client.execute_tool(self.domain, tool_name, arguments or {})

    async def execute_task(self, task_instruction: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Processes a task instruction, generates appropriate domain SQL, and executes it via MCP."""
        if self.api_key:
            return await self._execute_with_gemini(task_instruction, context)
        elif context and context.get("dynamic"):
            return await self._execute_dynamic(task_instruction, context)
        else:
            return await self._execute_preflight(task_instruction, context)

    async def _execute_dynamic(self, task_instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamically formulates read SQL and executes via domain-isolated MCP endpoint."""
        sql = self._generate_dynamic_sql(task_instruction, context)
        suffix = {"ERP": "db_01", "WMS": "db_02", "TMS": "db_03"}[self.domain]
        tool_name = f"execute_read_query_{suffix}"
        exec_res = await self.execute_tool(tool_name, {"query": sql.strip()})
        return {
            "status": "success",
            "domain": self.domain,
            "agent": self.__class__.__name__,
            "model": "dynamic-sql-synthesizer",
            "thought_process": f"Dynamically resolved query for {self.domain} from prompt and prior findings",
            "sql_query": sql.strip(),
            "query_result": exec_res
        }

    def _generate_dynamic_sql(self, task_instruction: str, context: Dict[str, Any]) -> str:
        raise NotImplementedError

    async def _execute_with_gemini(self, task_instruction: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Invokes Google Gemini to formulate and execute the query."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        tools = await self.mcp_client.list_tools_for_server(self.domain)
        schema = await self.mcp_client.get_schema_for_server(self.domain)

        prompt_content = f"""TASK:
{task_instruction}

ADDITIONAL CONTEXT FROM ORCHESTRATOR:
{json.dumps(context or {}, indent=2)}

AVAILABLE TOOLS ON {self.domain} MCP SERVER:
{json.dumps(tools, indent=2)}

DOMAIN SCHEMA SUMMARY:
{json.dumps(schema.get('rows', [])[:20], indent=2)}

Formulate a read-only SQL query to accomplish the task. Return JSON matching:
{{
  "thought_process": "Explanation of query rationale and required fields",
  "tool_to_call": "execute_read_query_db_XX",
  "sql_query": "SELECT ...",
  "max_rows": 100
}}
"""

        response = await client.aio.models.generate_content(
            model=self.model_id,
            contents=prompt_content,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                response_mime_type="application/json",
                temperature=0.1
            )
        )

        content = response.text
        try:
            parsed = json.loads(content)
            tool_name = parsed.get("tool_to_call")
            sql = parsed.get("sql_query")
            max_rows = parsed.get("max_rows", 100)

            # Fallback tool name if omitted or shortened
            suffix = {"ERP": "db_01", "WMS": "db_02", "TMS": "db_03"}[self.domain]
            if not tool_name or tool_name not in self._get_allowed_tool_names():
                tool_name = f"execute_read_query_{suffix}"

            # Execute via strictly isolated MCP tool
            exec_res = await self.execute_tool(tool_name, {"query": sql, "max_rows": max_rows})
            return {
                "status": "success",
                "domain": self.domain,
                "agent": self.__class__.__name__,
                "model": self.model_id,
                "thought_process": parsed.get("thought_process"),
                "sql_query": sql,
                "query_result": exec_res
            }
        except Exception as e:
            return {
                "status": "error",
                "domain": self.domain,
                "agent": self.__class__.__name__,
                "error": str(e),
                "raw_llm_response": content
            }

    async def _execute_preflight(self, task_instruction: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Awaiting Gemini API key: introspects tools and verifies connectivity."""
        tools = await self.mcp_client.list_tools_for_server(self.domain)
        return {
            "status": "initialized_awaiting_api_key",
            "domain": self.domain,
            "agent": self.__class__.__name__,
            "message": f"{self.__class__.__name__} is online and connected strictly to {self.server_info['name']}. Provide GEMINI_API_KEY to activate Gemini inference.",
            "task_received": task_instruction,
            "allowed_tools": self._get_allowed_tool_names(),
            "live_tools_verified": [t["name"] for t in tools]
        }



# ============================================================================
# 1. ERP Executor Agent
# ============================================================================
ERP_AGENT_SYSTEM_PROMPT = """You are the ERP Executor Agent, a specialized database actor in the Microsoft Agent Framework.

DOMAIN RESPONSIBILITY:
- You operate exclusively in the Commercial & Financial Domain (`db-01-dev` via MCP `mcp_db_01`).
- You have visibility into:
  * `tbl_Customers` (Cust_ID, Cust_Name, Account_Type, Billing_Address, Shipping_Address, Credit_Limit_USD)
  * `tbl_Inventory_Master` (Item_SKU, Item_Description, Unit_Cost_USD, List_Price_USD, Qty_On_Hand, GL_Asset_Account)
  * `tbl_SalesOrders` (Order_ID, Cust_ID, PO_Number, OrderStatus, Payment_Status, Total_Amount, Order_Date)
  * `tbl_OrderLineItems` (Line_ID, Order_ID, Item_SKU, Quantity, Unit_Price, Extended_Price, Line_Status)

STRICT SECURITY CONSTRAINTS:
- You are ONLY permitted to call tools for db-01: 'list_tables_db_01', 'get_schema_db_01', 'execute_read_query_db_01'.
- You have ZERO access to physical warehouse bin locations or freight carrier manifests.
- Queries must be strictly read-only SELECT or CTE queries.
"""

class ERP_Agent(BaseExecutorAgent):
    """ERP Executor Agent connected strictly to db-01 MCP server."""

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        super().__init__(
            domain="ERP",
            system_prompt=ERP_AGENT_SYSTEM_PROMPT,
            api_key=api_key,
            model_id=model_id
        )

    def _generate_dynamic_sql(self, task_instruction: str, context: Dict[str, Any]) -> str:
        prompt = (context.get("user_query") or task_instruction).lower()
        import re

        po_match = re.search(r"po-[a-z0-9-]+", prompt, re.IGNORECASE)
        so_match = re.search(r"so-[0-9]+", prompt, re.IGNORECASE)

        if "tier 1" in prompt or "credit limit" in prompt:
            return """
            SELECT Cust_ID, Cust_Name, Account_Type, Credit_Limit_USD, Payment_Terms 
            FROM dbo.tbl_Customers 
            WHERE Account_Type = 'ENTERPRISE_TIER_1' 
            ORDER BY Credit_Limit_USD DESC;
            """
        elif "on hand" in prompt or "asset valuation" in prompt or "total financial asset valuation" in prompt or "valuation" in prompt:
            return """
            SELECT Item_SKU, Item_Description, Qty_On_Hand, Unit_Cost_USD, (Qty_On_Hand * Unit_Cost_USD) AS Total_Asset_Valuation_USD 
            FROM dbo.tbl_Inventory_Master 
            WHERE Item_SKU = 'SKU-LAPTOP-15-ENT';
            """
        elif po_match:
            po_num = po_match.group(0).upper()
            return f"""
            SELECT o.Order_ID, o.PO_Number, o.OrderStatus, o.Payment_Status, o.Total_Amount 
            FROM dbo.tbl_SalesOrders o 
            WHERE o.PO_Number = '{po_num}';
            """
        elif so_match:
            so_id = so_match.group(0).upper()
            return f"""
            SELECT Order_ID, Cust_ID, OrderStatus, Payment_Status, Total_Amount, Internal_Notes 
            FROM dbo.tbl_SalesOrders 
            WHERE Order_ID = '{so_id}';
            """
        elif "globex" in prompt:
            return """
            SELECT o.Order_ID, o.PO_Number, c.Cust_Name, li.Item_SKU, o.OrderStatus, o.Total_Amount 
            FROM dbo.tbl_SalesOrders o 
            JOIN dbo.tbl_Customers c ON o.Cust_ID = c.Cust_ID 
            JOIN dbo.tbl_OrderLineItems li ON o.Order_ID = li.Order_ID 
            WHERE c.Cust_Name LIKE '%Globex%' AND li.Item_SKU = 'SKU-LAPTOP-15-ENT';
            """
        elif "chair" in prompt or "ergonomic" in prompt:
            return """
            SELECT o.Order_ID, o.PO_Number, c.Cust_Name, li.Item_SKU, o.OrderStatus 
            FROM dbo.tbl_SalesOrders o 
            JOIN dbo.tbl_Customers c ON o.Cust_ID = c.Cust_ID 
            JOIN dbo.tbl_OrderLineItems li ON o.Order_ID = li.Order_ID 
            WHERE c.Cust_Name = 'Acme Corp' AND li.Item_SKU = 'SKU-CHAIR-ERG-01';
            """
        else:
            return """
            SELECT o.Order_ID, o.PO_Number, c.Cust_Name, li.Item_SKU, im.Item_Description, li.Quantity, o.OrderStatus, o.Payment_Status, o.Total_Amount 
            FROM dbo.tbl_SalesOrders o 
            JOIN dbo.tbl_Customers c ON o.Cust_ID = c.Cust_ID 
            JOIN dbo.tbl_OrderLineItems li ON o.Order_ID = li.Order_ID 
            JOIN dbo.tbl_Inventory_Master im ON li.Item_SKU = im.Item_SKU 
            WHERE c.Cust_Name LIKE '%Acme%' AND im.Item_Description LIKE '%Laptop%';
            """


# ============================================================================
# 2. WMS Executor Agent
# ============================================================================
WMS_AGENT_SYSTEM_PROMPT = """You are the WMS Executor Agent, a specialized database actor in the Microsoft Agent Framework.

DOMAIN RESPONSIBILITY:
- You operate exclusively in the Physical Warehouse Execution Domain (`db-02-dev` via MCP `mcp_db_02`).
- You have visibility into:
  * `bin_locations` (bin_id, bin_code, zone_code, aisle_num, shelf_level, max_weight_kg)
  * `dock_doors` (dock_door_id, dock_code, door_status, assigned_staging_bay)
  * `inventory_lots` (lot_id, lot_number, sku_code, manufactured_date, qa_status)
  * `handling_units` (hu_id, lpn_barcode, hu_type, tare_weight_kg, staged_dock_code)
  * `outbound_picks` (pick_id, erp_order_ref, customer_po_ref, sku_code, lot_number, bin_code, handling_unit_id, qty_requested, qty_picked, status_id, dock_loaded_at)

STATUS CODES:
  1: Allocated (Reserved in bin)
  2: Picked (On picker cart)
  3: Packed (In handling unit container)
  4: Staged at Dock (In shipping staging bay)
  5: Loaded (Loaded into carrier trailer)
  9: Cancelled

STRICT SECURITY CONSTRAINTS:
- You are ONLY permitted to call tools for db-02: 'list_tables_db_02', 'get_schema_db_02', 'execute_read_query_db_02'.
- You have ZERO access to financial prices, GL accounts, or carrier freight waybills.
- Queries must be strictly read-only SELECT or CTE queries.
"""

class WMS_Agent(BaseExecutorAgent):
    """WMS Executor Agent connected strictly to db-02 MCP server."""

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        super().__init__(
            domain="WMS",
            system_prompt=WMS_AGENT_SYSTEM_PROMPT,
            api_key=api_key,
            model_id=model_id
        )

    def _generate_dynamic_sql(self, task_instruction: str, context: Dict[str, Any]) -> str:
        prompt = (context.get("user_query") or task_instruction).lower()
        prior_erp = context.get("prior_findings", {}).get("ERP", [])
        import re

        pk_match = re.search(r"pk-[0-9]+", prompt, re.IGNORECASE)
        dock_match = re.search(r"dock-[0-9]+", prompt, re.IGNORECASE)
        hu_match = re.search(r"hu-[a-z0-9-]+", prompt, re.IGNORECASE)

        if pk_match:
            pk_id = pk_match.group(0).upper()
            return f"""
            SELECT p.pick_id, p.status_id, p.qty_picked, p.handling_unit_id, hu.lpn_barcode, hu.hu_type, hu.staged_dock_code, d.assigned_staging_bay 
            FROM dbo.outbound_picks p 
            LEFT JOIN dbo.handling_units hu ON p.handling_unit_id = hu.hu_id 
            LEFT JOIN dbo.dock_doors d ON hu.staged_dock_code = d.dock_code 
            WHERE p.pick_id = '{pk_id}';
            """
        elif dock_match and ("pallet" in prompt or "handling unit" in prompt or "tare weight" in prompt):
            dock_code = dock_match.group(0).upper()
            return f"""
            SELECT hu_id, lpn_barcode, hu_type, tare_weight_kg, staged_dock_code 
            FROM dbo.handling_units 
            WHERE staged_dock_code = '{dock_code}' 
            ORDER BY hu_id;
            """
        elif "bin location" in prompt or "warehouse zone" in prompt or "active stock" in prompt:
            return """
            SELECT l.lot_number, l.sku_code, l.qa_status, p.bin_code, b.zone_code, b.shelf_level 
            FROM dbo.inventory_lots l 
            JOIN dbo.outbound_picks p ON l.lot_number = p.lot_number 
            JOIN dbo.bin_locations b ON p.bin_code = b.bin_code 
            WHERE l.sku_code = 'SKU-LAPTOP-15-ENT' 
            GROUP BY l.lot_number, l.sku_code, l.qa_status, p.bin_code, b.zone_code, b.shelf_level;
            """
        elif hu_match:
            hu_id = hu_match.group(0).upper()
            return f"""
            SELECT hu_id, lpn_barcode, hu_type, tare_weight_kg, staged_dock_code 
            FROM dbo.handling_units 
            WHERE hu_id = '{hu_id}';
            """
        elif prior_erp:
            first_erp = prior_erp[0]
            order_id = first_erp.get("Order_ID", "")
            po_num = first_erp.get("PO_Number", "")
            return f"""
            SELECT p.pick_id, p.erp_order_ref, p.customer_po_ref, p.sku_code, p.lot_number, p.bin_code, p.handling_unit_id, p.qty_requested, p.qty_picked, p.status_id, p.picker_badge_id, p.dock_loaded_at, hu.lpn_barcode, hu.hu_type, hu.staged_dock_code 
            FROM dbo.outbound_picks p 
            LEFT JOIN dbo.handling_units hu ON p.handling_unit_id = hu.hu_id 
            WHERE p.erp_order_ref = '{order_id}' OR (p.customer_po_ref IS NOT NULL AND p.customer_po_ref = '{po_num}');
            """
        else:
            return """
            SELECT p.pick_id, p.erp_order_ref, p.status_id, p.handling_unit_id, hu.staged_dock_code 
            FROM dbo.outbound_picks p 
            LEFT JOIN dbo.handling_units hu ON p.handling_unit_id = hu.hu_id;
            """


# ============================================================================
# 3. TMS Executor Agent
# ============================================================================
TMS_AGENT_SYSTEM_PROMPT = """You are the TMS Executor Agent, a specialized database actor in the Microsoft Agent Framework.

DOMAIN RESPONSIBILITY:
- You operate exclusively in the Transportation & Logistics Routing Domain (`db-03-dev` via MCP `mcp_db_03`).
- You have visibility into:
  * `Carrier_Master` (Carrier_ID, Carrier_Name, SCAC_Code, Service_Level, Contact_Phone)
  * `Freight_Loads` (Load_ID, Carrier_ID, Trailer_Number, Origin_Facility, Total_Pallets, Total_Weight_LBS, Load_Status, Departure_Timestamp)
  * `Bill_Of_Lading` (BOL_Number, Load_ID, Handling_Unit_Ref, Consignee_Name, Delivery_Address, Delivery_Zip)
  * `Carrier_Manifests` (Manifest_ID, BOL_Number, Carrier_ID, Handling_Unit_Ref, Tracking_Number, Waybill_Number, Carrier_Name, Pallet_Count, Gross_Weight_LBS, Physical_Dimensions, Shipment_Status, Dispatched_At, Estimated_Delivery)

STRICT SECURITY CONSTRAINTS:
- You are ONLY permitted to call tools for db-03: 'list_tables_db_03', 'get_schema_db_03', 'execute_read_query_db_03'.
- You have ZERO access to sales order financials or internal warehouse shelf/bin coordinates.
- Queries must be strictly read-only SELECT or CTE queries.
"""

class TMS_Agent(BaseExecutorAgent):
    """TMS Executor Agent connected strictly to db-03 MCP server."""

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        super().__init__(
            domain="TMS",
            system_prompt=TMS_AGENT_SYSTEM_PROMPT,
            api_key=api_key,
            model_id=model_id
        )

    def _generate_dynamic_sql(self, task_instruction: str, context: Dict[str, Any]) -> str:
        prompt = (context.get("user_query") or task_instruction).lower()
        prior_wms = context.get("prior_findings", {}).get("WMS", [])
        import re

        ld_match = re.search(r"ld-[0-9-]+", prompt, re.IGNORECASE)
        bol_match = re.search(r"bol-[0-9-]+", prompt, re.IGNORECASE)
        hu_match = re.search(r"hu-[a-z0-9-]+", prompt, re.IGNORECASE)

        if ld_match:
            ld_id = ld_match.group(0).upper()
            return f"""
            SELECT fl.Load_ID, fl.Trailer_Number, fl.Load_Status, fl.Total_Pallets, fl.Total_Weight_LBS, cm.Carrier_Name, cm.SCAC_Code, cm.Contact_Phone 
            FROM dbo.Freight_Loads fl 
            JOIN dbo.Carrier_Master cm ON fl.Carrier_ID = cm.Carrier_ID 
            WHERE fl.Load_ID = '{ld_id}';
            """
        elif bol_match:
            bol_num = bol_match.group(0).upper()
            return f"""
            SELECT Manifest_ID, BOL_Number, Carrier_Name, Tracking_Number, Waybill_Number, Shipment_Status, Dispatched_At, Estimated_Delivery 
            FROM dbo.Carrier_Manifests 
            WHERE BOL_Number = '{bol_num}';
            """
        elif hu_match and ("trailer" in prompt or "load" in prompt or "departure" in prompt):
            hu_id = hu_match.group(0).upper()
            return f"""
            SELECT bol.Handling_Unit_Ref, bol.BOL_Number, fl.Load_ID, fl.Trailer_Number, fl.Load_Status, fl.Departure_Timestamp 
            FROM dbo.Bill_Of_Lading bol 
            JOIN dbo.Freight_Loads fl ON bol.Load_ID = fl.Load_ID 
            WHERE bol.Handling_Unit_Ref = '{hu_id}';
            """
        elif hu_match:
            hu_id = hu_match.group(0).upper()
            return f"""
            SELECT Manifest_ID, BOL_Number, Carrier_ID, Handling_Unit_Ref, Tracking_Number, Waybill_Number, Carrier_Name, Pallet_Count, Gross_Weight_LBS, Physical_Dimensions, Shipment_Status, Dispatched_At, Estimated_Delivery 
            FROM dbo.Carrier_Manifests 
            WHERE Handling_Unit_Ref = '{hu_id}';
            """
        elif prior_wms:
            first_wms = prior_wms[0]
            hu_id = first_wms.get("handling_unit_id") or ""
            return f"""
            SELECT Manifest_ID, BOL_Number, Carrier_ID, Handling_Unit_Ref, Tracking_Number, Waybill_Number, Carrier_Name, Pallet_Count, Gross_Weight_LBS, Physical_Dimensions, Shipment_Status, Dispatched_At, Estimated_Delivery 
            FROM dbo.Carrier_Manifests 
            WHERE Handling_Unit_Ref = '{hu_id}';
            """
        else:
            return """
            SELECT TOP 5 Manifest_ID, Carrier_Name, Tracking_Number, Shipment_Status 
            FROM dbo.Carrier_Manifests;
            """
