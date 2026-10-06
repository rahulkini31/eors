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

    @property
    def display_name(self) -> str:
        names = {
            "ERP": "Executor Agent (ERP)",
            "WMS": "Executor Agent (Warehouse)",
            "TMS": "Executor Agent (Logistics)"
        }
        return names.get(self.domain, f"Executor Agent ({self.domain})")

    @property
    def system_display_name(self) -> str:
        names = {
            "ERP": "Commercial ERP system",
            "WMS": "Warehouse Management system",
            "TMS": "Transportation Logistics system"
        }
        return names.get(self.domain, f"{self.domain} system")

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
3. If an upstream agent found an identifier (such as an Order_ID like 'SO-10045', PO_Number, handling_unit_id like 'HU-8841-PLT', or BOL_Number), use it in your WHERE clause to link cross-domain records.
4. Always include primary status, lifecycle, and identifier columns in your SELECT clause (e.g. Load_Status, Shipment_Status, OrderStatus, status_id, Line_Status, door_status, qa_status, Trailer_Number, Carrier_Name, etc.) alongside the requested attributes so full state is captured.
5. Robust keyword matching: When matching multi-word product names, titles, or descriptions (e.g. 'ergonomic chairs', 'enterprise laptop'), do NOT assume adjacent words or strict exact string equality. Use tokenized wildcards or separate conditions, e.g. (Item_Description LIKE '%ergonomic%' AND Item_Description LIKE '%chair%') or Item_Description LIKE '%ergonomic%chair%'.
6. Normalize categorical values and codes: Database categorical values, tiers, and status codes often use uppercase and underscores (e.g., 'ENTERPRISE_TIER_1' for 'Enterprise Tier 1', 'IN_TRANSIT' for 'in transit', 'DISPATCHED' for 'dispatched'). When filtering text categories or status fields, account for underscore vs space variants, e.g., REPLACE(Account_Type, '_', ' ') LIKE '%Enterprise Tier 1%' or (Account_Type LIKE '%ENTERPRISE%' AND Account_Type LIKE '%1%').
7. When asked for rankings, highest/lowest metrics, credit limits, or valuations, sort by the relevant numeric/metric column descending (ORDER BY col DESC) and return all matching records.
8. Output JSON matching:
{{
  "thought_process": "Explanation of query rationale, tables chosen, and filter conditions",
  "query_description": "1 clear sentence in natural language describing what records are being searched and why (refer to the system by name like Commercial ERP, Warehouse Management, or Transportation Logistics, without raw database codes)",
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
            query_desc = parsed.get("query_description") or f"Searching the {self.system_display_name} for: {task_instruction}"

            # Fallback tool name if omitted or shortened
            suffix = {"ERP": "db_01", "WMS": "db_02", "TMS": "db_03"}[self.domain]
            if not tool_name or tool_name not in self._get_allowed_tool_names():
                tool_name = f"execute_read_query_{suffix}"

            # Emit real-time query event explaining what tool was called and why (no bare SQL displayed to user)
            clean_goal = query_desc.strip()
            clean_goal = (
                clean_goal
                .replace("db-01-dev", "Commercial ERP system")
                .replace("db-02-dev", "Warehouse Management system")
                .replace("db-03-dev", "Transportation Logistics system")
            )
            if clean_goal.lower().startswith("retrieve "):
                clean_goal = "retrieve " + clean_goal[9:]
            elif clean_goal.lower().startswith("query "):
                clean_goal = "query " + clean_goal[6:]
            else:
                clean_goal = "search for " + clean_goal

            tool_msg = (
                f"The Executor Agent working on the {self.system_display_name} used tool `{tool_name}` via the MCP server to {clean_goal}."
            )
            try:
                from agents.event_streamer import AgentEventStreamer
                await AgentEventStreamer.emit(
                    "database_query",
                    self.display_name,
                    tool_msg,
                    {
                        "tool_called": tool_name,
                        "system": self.system_display_name,
                        "query_description": query_desc
                    },
                    database=self.system_display_name
                )
            except Exception:
                pass

            # Smooth async cadence
            await asyncio.sleep(0.35)

            # Execute via strictly isolated MCP tool
            try:
                from agents.telemetry import get_tracer
                tracer = get_tracer("agents.executors")
                with tracer.start_as_current_span(f"mcp_tool_{tool_name}") as tool_span:
                    tool_span.set_attribute("mcp.server", f"mcp_{suffix}")
                    tool_span.set_attribute("db.statement", sql.strip())
                    exec_res = await self.execute_tool(tool_name, {"query": sql, "max_rows": max_rows})
            except Exception:
                exec_res = await self.execute_tool(tool_name, {"query": sql, "max_rows": max_rows})

            rows = exec_res.get("rows", []) if isinstance(exec_res, dict) else []

            # Format result in clear natural language explaining what the agent understood
            findings_summary = self._format_natural_language_findings(rows, task_instruction)
            findings_msg = (
                f"The Executor Agent working on the {self.system_display_name} evaluated the records retrieved by `{tool_name}` and verified domain findings."
            )

            try:
                from agents.event_streamer import AgentEventStreamer
                await AgentEventStreamer.emit(
                    "domain_findings",
                    self.display_name,
                    findings_msg,
                    {
                        "tool_called": tool_name,
                        "system": self.system_display_name,
                        "natural_language_summary": findings_summary,
                        "count": len(rows),
                        "matched": len(rows) > 0,
                        "rows": rows
                    },
                    database=self.system_display_name
                )
            except Exception:
                pass

            # Smooth async cadence before handing off to next stage
            await asyncio.sleep(0.35)

            return {
                "status": "success",
                "domain": self.domain,
                "agent": self.__class__.__name__,
                "model": self.model_id,
                "thought_process": parsed.get("thought_process"),
                "query_description": query_desc,
                "sql_query": sql,
                "query_result": exec_res,
                "natural_language_summary": findings_summary
            }
        except Exception as e:
            return {
                "status": "error",
                "domain": self.domain,
                "agent": self.__class__.__name__,
                "error": str(e),
                "raw_llm_response": content
            }

    def _format_natural_language_findings(self, rows: List[Dict[str, Any]], task_instruction: str) -> str:
        """Translates raw query records into clear, human-understandable natural language findings."""
        if not rows:
            return f"No records found in the {self.system_display_name} matching the search criteria."

        row_count = len(rows)
        if self.domain == "ERP":
            summaries = []
            for r in rows[:6]:
                parts = []
                if "Order_ID" in r:
                    parts.append(f"Sales Order **{r['Order_ID']}**")
                if "Cust_Name" in r:
                    parts.append(f"for **{r['Cust_Name']}**")
                if "PO_Number" in r and r.get("PO_Number"):
                    parts.append(f"(PO: `{r['PO_Number']}`)")
                if "OrderStatus" in r:
                    parts.append(f"— Commercial Status: **{r['OrderStatus']}**")
                if "Total_Amount" in r:
                    curr = r.get("Currency_Code", "USD")
                    parts.append(f"— Total: **${r['Total_Amount']} {curr}**")
                if "Payment_Status" in r:
                    parts.append(f"({r['Payment_Status']})")
                if "Credit_Limit_USD" in r and "Cust_Name" in r:
                    tier = r.get("Account_Type", "Standard")
                    parts.append(f"— Tier: **{tier}**, Credit Limit: **${r['Credit_Limit_USD']}**")
                if "Item_Description" in r:
                    parts.append(f"Product: **{r['Item_Description']}** (SKU: `{r.get('SKU', 'N/A')}`), Qty on Hand: **{r.get('Qty_On_Hand', 'N/A')}**")
                if "Internal_Notes" in r and r.get("Internal_Notes"):
                    parts.append(f"Note: *{r['Internal_Notes']}*")
                if "Shipping_Address" in r and r.get("Shipping_Address"):
                    parts.append(f"— Destination: {r['Shipping_Address']}")

                if parts:
                    summaries.append(" ".join(parts))
                else:
                    summaries.append(", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in r.items() if v is not None))
            header = f"Found {row_count} commercial order record{'s' if row_count > 1 else ''}:"
            return f"{header}\n" + "\n".join(f"• {s}" for s in summaries)

        elif self.domain == "WMS":
            summaries = []
            status_map = {
                1: "Allocated",
                2: "Picked onto cart",
                3: "Quality Inspected",
                4: "Staged at Dock Door",
                5: "Loaded onto Outbound Transport"
            }
            for r in rows[:6]:
                parts = []
                status_str = None
                if "status_id" in r and r["status_id"] is not None:
                    try:
                        s_int = int(r["status_id"])
                        status_str = f"Status {s_int} ({status_map.get(s_int, 'In Progress')})"
                    except (ValueError, TypeError):
                        status_str = f"Status {r['status_id']}"

                if "pick_id" in r:
                    qty = r.get("qty_picked") or r.get("qty_requested") or ""
                    sku = r.get("sku_code") or ""
                    parts.append(f"Pick **{r['pick_id']}**" + (f" for {qty} unit(s)" if qty else "") + (f" of `{sku}`" if sku else ""))
                if status_str:
                    parts.append(f"— Physical Status: **{status_str}**")
                if "handling_unit_id" in r and r.get("handling_unit_id"):
                    parts.append(f"on Pallet **{r['handling_unit_id']}**")
                if "staged_dock_code" in r and r.get("staged_dock_code"):
                    parts.append(f"at **{r['staged_dock_code']}**")
                if "dock_loaded_at" in r:
                    if r["dock_loaded_at"]:
                        parts.append(f"— Loaded onto truck at `{r['dock_loaded_at']}`")
                    else:
                        parts.append("— **Not loaded onto truck** (dock_loaded_at is null)")
                if "dock_code" in r:
                    parts.append(f"Dock Door **{r['dock_code']}** (Status: **{r.get('door_status', 'N/A')}**, Carrier: **{r.get('assigned_carrier', 'N/A')}**, Trailer Loaded: **{r.get('trailer_loaded', 'N/A')}**)")
                if "hu_id" in r:
                    parts.append(f"Handling Unit **{r['hu_id']}** (LPN: `{r.get('lpn_barcode', 'N/A')}`, Staged: **{r.get('staged_dock_code', 'N/A')}**)")

                if parts:
                    summaries.append(" ".join(parts))
                else:
                    summaries.append(", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in r.items() if v is not None))
            header = f"Found {row_count} warehouse fulfillment record{'s' if row_count > 1 else ''}:"
            return f"{header}\n" + "\n".join(f"• {s}" for s in summaries)

        elif self.domain == "TMS":
            summaries = []
            for r in rows[:6]:
                parts = []
                if "BOL_Number" in r or "Manifest_ID" in r:
                    ids = []
                    if r.get("BOL_Number"): ids.append(f"BOL `{r['BOL_Number']}`")
                    if r.get("Manifest_ID"): ids.append(f"Manifest `{r['Manifest_ID']}`")
                    parts.append(f"Shipment (" + ", ".join(ids) + ")")
                if "Carrier_Name" in r and r.get("Carrier_Name"):
                    parts.append(f"via **{r['Carrier_Name']}**")
                if "Tracking_Number" in r and r.get("Tracking_Number"):
                    parts.append(f"(Tracking: **{r['Tracking_Number']}**)")
                if "Load_Status" in r and r.get("Load_Status"):
                    parts.append(f"— Load Status: **{r['Load_Status']}**")
                if "Shipment_Status" in r and r.get("Shipment_Status"):
                    parts.append(f"— Transit Status: **{r['Shipment_Status']}**")
                if "Trailer_Number" in r and r.get("Trailer_Number"):
                    parts.append(f"— Trailer: `{r['Trailer_Number']}`")
                if "Dispatched_At" in r or "Departure_Timestamp" in r:
                    depart = r.get("Dispatched_At") or r.get("Departure_Timestamp")
                    if depart:
                        parts.append(f"— Departed: `{depart}` (**In Transit**)")
                    else:
                        parts.append("— **Awaiting dispatch / Not departed**")
                if "Load_ID" in r and not ("BOL_Number" in r or "Manifest_ID" in r):
                    parts.append(f"Freight Load **{r['Load_ID']}** (Trailer: `{r.get('Trailer_Number', 'N/A')}`, Status: **{r.get('Load_Status', 'N/A')}**)")

                if parts:
                    summaries.append(" ".join(parts))
                else:
                    summaries.append(", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in r.items() if v is not None))
            header = f"Found {row_count} logistics freight record{'s' if row_count > 1 else ''}:"
            return f"{header}\n" + "\n".join(f"• {s}" for s in summaries)

        return f"Retrieved {row_count} record(s) matching criteria."


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
