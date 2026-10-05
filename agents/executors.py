"""Specialized Domain Executor Sub-Agents (MAF Actors) powered genuinely by Google Gemini.
Strictly decoupled: each executor is bound exclusively to its own domain MCP server.
Zero hardcoded SQL queries, zero question pattern matching, zero hardcoded entity constants.
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
        self.model_id = model_id or os.environ.get("GEMINI_EXECUTOR_MODEL_ID", "") or GEMINI_EXECUTOR_MODEL_ID or "gemini-3.8-flash"
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
        """Processes a task instruction, dynamically generates domain SQL via Gemini LLM, and executes it via MCP."""
        if not self.api_key:
            raise RuntimeError(
                f"GEMINI_API_KEY is required for genuine LLM SQL generation in {self.domain} agent. "
                "Hardcoded SQL shortcuts have been removed."
            )
        return await self._execute_with_gemini(task_instruction, context)

    async def _execute_with_gemini(self, task_instruction: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Invokes Google Gemini to formulate and execute the query dynamically based on introspected schema."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        tools = await self.mcp_client.list_tools_for_server(self.domain)
        schema = await self.mcp_client.get_schema_for_server(self.domain)

        cols = schema.get("rows", [])
        formatted_schema = [
            f"{c.get('TABLE_NAME')}.{c.get('COLUMN_NAME')} ({c.get('DATA_TYPE')})"
            for c in cols if c.get("TABLE_NAME") and c.get("COLUMN_NAME")
        ]

        prompt_content = f"""TASK OBJECTIVE:
{task_instruction}

ADDITIONAL CONTEXT & PRIOR FINDINGS FROM UPSTREAM AGENTS:
{json.dumps(context or {}, indent=2)}

AVAILABLE TOOLS ON {self.domain} MCP SERVER:
{json.dumps([t['name'] for t in tools], indent=2)}

FULL DOMAIN SCHEMA (TABLES & COLUMNS):
{json.dumps(formatted_schema, indent=2)}

INSTRUCTIONS FOR SQL FORMULATION:
1. Formulate a precise, read-only SQL query (SELECT / CTE) matching the task objective.
2. Filter strictly by entities or identifiers passed in the task or prior findings (e.g. order IDs, PO numbers, customer names, SKUs, handling units, load IDs).
3. Select all relevant fields needed to answer the question or pass downstream.
4. Output JSON matching:
{{
  "thought_process": "Explanation of query rationale, tables chosen, and filter conditions",
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


# ============================================================================
# 1. ERP Executor Agent
# ============================================================================
ERP_AGENT_SYSTEM_PROMPT = """You are the ERP Executor Agent, a specialized database actor in the Microsoft Agent Framework.

DOMAIN RESPONSIBILITY:
- You operate exclusively in the Commercial & Financial Domain (`db-01-dev` via MCP `mcp_db_01`).
- You have visibility into tables:
  * `tbl_Customers` (Cust_ID, Cust_Name, Account_Type, Billing_Address, Shipping_Address, Credit_Limit_USD, Payment_Terms)
  * `tbl_Inventory_Master` (Item_SKU, Item_Description, Unit_Cost_USD, List_Price_USD, Qty_On_Hand, GL_Asset_Account)
  * `tbl_SalesOrders` (Order_ID, Cust_ID, PO_Number, OrderStatus, Payment_Status, Total_Amount, Order_Date, Internal_Notes)
  * `tbl_OrderLineItems` (Line_ID, Order_ID, Item_SKU, Quantity, Unit_Price, Extended_Price, Line_Status)

STRICT CONSTRAINTS:
- You are ONLY permitted to call tools for db-01: 'list_tables_db_01', 'get_schema_db_01', 'execute_read_query_db_01'.
- You have ZERO access to physical warehouse bins or carrier waybills.
- Always output clean read-only SQL queries.
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


# ============================================================================
# 2. WMS Executor Agent
# ============================================================================
WMS_AGENT_SYSTEM_PROMPT = """You are the WMS Executor Agent, a specialized database actor in the Microsoft Agent Framework.

DOMAIN RESPONSIBILITY:
- You operate exclusively in the Physical Warehouse Execution Domain (`db-02-dev` via MCP `mcp_db_02`).
- You have visibility into tables:
  * `bin_locations` (bin_id, bin_code, zone_code, aisle_num, shelf_level, max_weight_kg)
  * `dock_doors` (dock_door_id, dock_code, door_status, assigned_staging_bay)
  * `inventory_lots` (lot_id, lot_number, sku_code, manufactured_date, qa_status)
  * `handling_units` (hu_id, lpn_barcode, hu_type, tare_weight_kg, staged_dock_code)
  * `outbound_picks` (pick_id, erp_order_ref, customer_po_ref, sku_code, lot_number, bin_code, handling_unit_id, qty_requested, qty_picked, status_id, picker_badge_id, dock_loaded_at)

STATUS CODES:
  1: Allocated (Reserved in bin)
  2: Picked (On picker cart)
  3: Packed (In handling unit container)
  4: Staged at Dock (In shipping staging bay)
  5: Loaded (Loaded into carrier trailer)
  9: Cancelled

STRICT CONSTRAINTS:
- You are ONLY permitted to call tools for db-02: 'list_tables_db_02', 'get_schema_db_02', 'execute_read_query_db_02'.
- You have ZERO access to financial prices or carrier waybills.
- Always output clean read-only SQL queries.
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


# ============================================================================
# 3. TMS Executor Agent
# ============================================================================
TMS_AGENT_SYSTEM_PROMPT = """You are the TMS Executor Agent, a specialized database actor in the Microsoft Agent Framework.

DOMAIN RESPONSIBILITY:
- You operate exclusively in the Transportation & Logistics Routing Domain (`db-03-dev` via MCP `mcp_db_03`).
- You have visibility into tables:
  * `Carrier_Master` (Carrier_ID, Carrier_Name, SCAC_Code, Service_Level, Contact_Phone)
  * `Freight_Loads` (Load_ID, Carrier_ID, Trailer_Number, Origin_Facility, Total_Pallets, Total_Weight_LBS, Load_Status, Departure_Timestamp)
  * `Bill_Of_Lading` (BOL_Number, Load_ID, Handling_Unit_Ref, Consignee_Name, Delivery_Address, Delivery_Zip)
  * `Carrier_Manifests` (Manifest_ID, BOL_Number, Carrier_ID, Handling_Unit_Ref, Tracking_Number, Waybill_Number, Carrier_Name, Pallet_Count, Gross_Weight_LBS, Physical_Dimensions, Shipment_Status, Dispatched_At, Estimated_Delivery)

STRICT CONSTRAINTS:
- You are ONLY permitted to call tools for db-03: 'list_tables_db_03', 'get_schema_db_03', 'execute_read_query_db_03'.
- You have ZERO access to sales order financials or warehouse bin coordinates.
- Always output clean read-only SQL queries.
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
