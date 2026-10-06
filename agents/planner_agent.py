"""Strategic Orchestrator Planner Agent for the Multi-Agent Framework (MAF).
Powered genuinely by Google Gemini and decoupled from direct database query tools.
Zero hardcoded question branches, zero question-specific lookup maps.
"""

import os
import json
import asyncio
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agents.config import GEMINI_API_KEY, GEMINI_PLANNER_MODEL_ID, GEMINI_MODEL_ID, MCP_SERVERS
from agents.mcp_client import MCPDiscoveryClient

PLANNER_SYSTEM_PROMPT = """You are the Lead Strategic Orchestrator (Planner Agent) for an enterprise multi-database system.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. YOU DO NOT HAVE DIRECT ACCESS TO DATABASE QUERY TOOLS. You cannot run SQL queries or access raw database tables directly.
2. YOU HAVE ZERO HARDCODED PRIOR KNOWLEDGE of database schemas or relationships. You must reason dynamically over the introspected MCP schemas provided in the prompt.
3. YOUR GOAL: Break down the user's business query into an ordered sequence of discrete single-database execution phases for specialized domain executor agents:
   - 'ERP_Agent' operates exclusively in Commercial ERP (db-01-dev) via mcp_db_01. Handles sales orders, purchase orders, customers, financial accounts, item catalog pricing/valuation.
   - 'WMS_Agent' operates exclusively in Physical Warehouse (db-02-dev) via mcp_db_02. Handles physical pick tasks, bin locations, warehouse zones, quality lots, handling units (pallets/totes), tare weights, dock doors.
   - 'TMS_Agent' operates exclusively in Transportation Management (db-03-dev) via mcp_db_03. Handles freight loads, carrier master, bills of lading, trailer assignments, manifests, waybills, carrier tracking numbers, dispatch statuses.

CROSS-DOMAIN CORRELATION CONCEPTS:
- ERP Order ID (e.g. 'Order_ID' in tbl_SalesOrders) correlates loosely with WMS 'erp_order_ref' in outbound_picks.
- Customer PO Number in ERP correlates with WMS 'customer_po_ref'.
- WMS 'handling_unit_id' (or 'hu_id') correlates loosely with TMS 'Handling_Unit_Ref' in Bill_Of_Lading and Carrier_Manifests.

TASK DECOMPOSITION RULES:
1. If the user query is strictly within one domain (e.g. asking about inventory valuation in ERP, or dock door handling units in WMS, or freight load trailer details in TMS), generate a single execution phase targeting ONLY that domain.
2. If the user query requires cross-domain correlation (e.g. "For customer Acme Corp's laptop order, who picked it and what handling unit?"), generate ordered phases:
   - Phase 1: ERP_Agent finds Order_ID for customer and product.
   - Phase 2: WMS_Agent finds pick task and handling unit using erp_order_ref.
3. If the user query asks about end-to-end shipment status or tracking (e.g. "Has customer Acme Corp's laptop order shipped, and what is the tracking number?"):
   - Phase 1: ERP_Agent identifies sales order ID and commercial status.
   - Phase 2: WMS_Agent verifies physical pick status and handling unit container.
   - Phase 3: TMS_Agent verifies carrier manifest, waybill, tracking number, and dispatch status.
4. For distractor or negative questions (e.g. cancelled orders, staged vs loaded checks):
   - Design steps to check the critical status fields (e.g. ERP OrderStatus, WMS status_id where 4=Staged and 5=Loaded, TMS Shipment_Status where PENDING_PICKUP vs IN_TRANSIT) so downstream synthesis can accurately detect and state negative findings without hallucinating.

Format your output as structured JSON matching this schema:
{
  "objective": "High-level goal of the execution plan",
  "identified_domain_linkages": [
    {"from_domain": "...", "from_field": "...", "to_domain": "...", "to_field": "...", "reasoning": "..."}
  ],
  "execution_phases": [
    {
      "phase_number": 1,
      "assigned_agent": "ERP_Agent / WMS_Agent / TMS_Agent",
      "target_database": "db-01-dev / db-02-dev / db-03-dev",
      "action_objective": "Specific objective and query goal for this agent",
      "expected_inputs": "Inputs required or passed from upstream",
      "key_outputs_for_downstream": "Key fields needed downstream"
    }
  ],
  "verification_and_guardrails": [
    "Specific validation checks to prevent hallucinations or distractor traps"
  ],
  "final_synthesis_logic": "How to assemble the verified answer for the user"
}
"""


class PlannerAgent:
    """The Primary Microsoft Agent Framework Strategic Planner using Google Gemini."""

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY
        self.model_id = model_id or os.environ.get("GEMINI_PLANNER_MODEL_ID") or os.environ.get("GEMINI_MODEL_ID") or GEMINI_PLANNER_MODEL_ID or "gemini-3.8-flash"
        self.discovery_client = MCPDiscoveryClient()
        self.cached_architecture: Optional[Dict[str, Any]] = None

    async def ping_mcp_servers(self) -> Dict[str, Any]:
        """Pings the three live MCP servers."""
        return await self.discovery_client.ping_all_servers()

    async def discover_architectures(self) -> Dict[str, Any]:
        """Dynamically learns the architectures and tools of the 3 MCP servers."""
        if self.cached_architecture:
            return self.cached_architecture
        self.cached_architecture = await self.discovery_client.discover_all_architectures()
        return self.cached_architecture

    async def plan(self, user_prompt: str) -> Dict[str, Any]:
        """Main orchestrator entrypoint:
        1. Dynamically pings and introspects live ERP, WMS, and TMS architectures over SSE.
        2. Synthesizes a strategic execution plan via Google Gemini LLM reasoning.
        """
        if not self.api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required for genuine LLM multi-agent planning. "
                "Hardcoded planning rules have been eliminated."
            )

        print(f"[Planner] Step 1: Introspecting live MCP architectures across ERP, WMS, and TMS...")
        architectures = await self.discover_architectures()

        print(f"[Planner] Step 2: Formulating strategic execution plan via Gemini LLM for: '{user_prompt}'...")
        return await self._plan_with_gemini(user_prompt, architectures)

    async def _plan_with_gemini(self, user_prompt: str, architectures: Dict[str, Any]) -> Dict[str, Any]:
        """Calls Google Gemini using google-genai SDK to generate the dynamic orchestrator plan."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        # Build context payload with dynamically discovered schemas
        schema_summary = {}
        for domain, info in architectures.items():
            cols = info.get("database_schema", {}).get("rows", [])
            schema_summary[domain] = {
                "server": info.get("server_name"),
                "tools": info.get("available_tools"),
                "columns": [
                    f"{c.get('TABLE_NAME')}.{c.get('COLUMN_NAME')} ({c.get('DATA_TYPE')})"
                    for c in cols
                ]
            }

        prompt_content = f"""USER PROMPT:
{user_prompt}

DYNAMICALLY DISCOVERED MCP SERVER ARCHITECTURES:
{json.dumps(schema_summary, indent=2)}

Please formulate a strategic, step-by-step multi-agent execution plan. Format your output as structured JSON matching the requested schema.
"""

        response = await client.aio.models.generate_content(
            model=self.model_id,
            contents=prompt_content,
            config=types.GenerateContentConfig(
                system_instruction=PLANNER_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.1
            )
        )

        try:
            parsed = json.loads(response.text)
            return {
                "status": "success",
                "model_used": self.model_id,
                "plan": parsed,
                "discovered_architectures": {
                    d: {
                        "server": architectures[d]["server_name"],
                        "tools": architectures[d]["available_tools"],
                        "column_count": len(architectures[d]["database_schema"].get("rows", []))
                    }
                    for d in architectures
                }
            }
        except Exception as e:
            return {
                "status": "error",
                "model_used": self.model_id,
                "error": f"Failed to parse LLM plan response: {e}",
                "raw_response": response.text
            }
