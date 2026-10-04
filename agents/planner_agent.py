"""Strategic Orchestrator Planner Agent for the Multi-Agent Framework (MAF).
Powered by Google Gemini and decoupled from direct database query tools.
"""

import os
import json
import asyncio
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agents.config import GEMINI_API_KEY, GEMINI_MODEL_ID, MCP_SERVERS
from agents.mcp_client import MCPDiscoveryClient

PLANNER_SYSTEM_PROMPT = """You are the Lead Strategic Orchestrator (Planner Agent) for an enterprise multi-database system.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. YOU DO NOT HAVE DIRECT ACCESS TO DATABASE QUERY TOOLS. You cannot run SQL queries or access raw database tables directly.
2. YOU HAVE ZERO HARDCODED PRIOR KNOWLEDGE of table schemas, column names, or relationships between systems.
3. YOUR FIRST ACTION UPON RECEIVING ANY USER REQUEST MUST BE:
   - Ping the three MCP servers (ERP, WMS, and TMS) to verify availability.
   - Call their 'list_tools' and 'get_schema' endpoints to dynamically inspect and learn the architecture and data models of all three systems.

YOUR CORE RESPONSIBILITIES:
1. Dynamic Introspection: Inspect the discovered tables and fields across ERP, WMS, and TMS. Identify domain semantics, status codes, and cross-domain correlation fields (e.g., loose references like order numbers, purchase orders, handling unit identifiers, barcodes).
2. Query Decomposition: Break down complex user requests (such as 'Has Acme Corp's laptop order shipped?') into an ordered sequence of discrete, single-database sub-tasks.
3. Formulate Strategic Execution Plan:
   - Phase 1 (Discovery & Schema Mapping): Document the discovered schema relationships and identify the entry domain.
   - Phase 2 (Step-by-Step Delegated Tasks): For each step, specify the exact target database, the objective for the specialized domain worker, the required filters, and the key outputs needed for downstream steps.
   - Phase 3 (Synthesis Strategy): Define how outputs from each domain must be combined to answer the user's question without hallucinations.
   - Phase 4 (Contingency & Validation): Anticipate potential traps (e.g. wrong product, cancelled order, staged vs dispatched status) and provide validation checks.

Always output structured, transparent execution plans ready to be executed by downstream specialized domain agents.
"""


class PlannerExecutionPlan(BaseModel):
    """Structured execution plan output produced by the Strategic Orchestrator."""
    discovered_architectures: Dict[str, Any] = Field(description="Summary of dynamically discovered servers and schemas")
    cross_domain_mappings: List[Dict[str, str]] = Field(description="Identified correlation fields connecting the domains")
    sub_tasks: List[Dict[str, Any]] = Field(description="Ordered sub-tasks assigned to specialized domain worker agents")
    synthesis_logic: str = Field(description="Instructions for synthesizing the multi-hop answers")
    anti_hallucination_guardrails: List[str] = Field(description="Validation checks against distractors or missing records")


class PlannerAgent:
    """The Primary Microsoft Agent Framework Actor using Google Gemini."""

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY
        self.model_id = model_id or GEMINI_MODEL_ID
        self.discovery_client = MCPDiscoveryClient()
        self.cached_architecture: Optional[Dict[str, Any]] = None

    async def ping_mcp_servers(self) -> Dict[str, Any]:
        """Pings the three live MCP servers."""
        return await self.discovery_client.ping_all_servers()

    async def discover_architectures(self) -> Dict[str, Any]:
        """Dynamically learns the architectures and tools of the 3 MCP servers."""
        self.cached_architecture = await self.discovery_client.discover_all_architectures()
        return self.cached_architecture

    async def plan(self, user_prompt: str) -> Dict[str, Any]:
        """Main orchestrator entrypoint:
        1. Dynamically pings and reads ERP, WMS, and TMS architectures.
        2. Synthesizes a strategic execution plan via Google Gemini (or generates the plan schema).
        """
        # Step 1: Introspect architectures dynamically (zero hardcoded assumptions)
        print(f"[Planner] Step 1: Introspecting live MCP architectures across ERP, WMS, and TMS...")
        architectures = await self.discover_architectures()
        pings = await self.ping_mcp_servers()

        print(f"[Planner] Step 2: Formulating strategic execution plan for prompt: '{user_prompt}'...")

        # If Gemini API Key is configured, invoke Gemini model
        if self.api_key:
            return await self._plan_with_gemini(user_prompt, architectures)
        else:
            print("[Planner] Notice: GEMINI_API_KEY is not yet set in environment. Returning discovered schema architecture and pre-flight plan.")
            return self._build_preflight_plan(user_prompt, architectures, pings)

    async def _plan_with_gemini(self, user_prompt: str, architectures: Dict[str, Any]) -> Dict[str, Any]:
        """Calls Google Gemini using google-genai SDK to generate the orchestrator plan."""
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

Please formulate a strategic, step-by-step multi-agent execution plan. Format your output as structured JSON matching this schema:
{{
  "objective": "High-level goal",
  "identified_domain_linkages": [
    {{"from_domain": "...", "from_field": "...", "to_domain": "...", "to_field": "...", "reasoning": "..."}}
  ],
  "execution_phases": [
    {{
      "phase_number": 1,
      "assigned_agent": "ERP_Worker_Agent / WMS_Worker_Agent / TMS_Worker_Agent",
      "target_database": "db-01-dev / db-02-dev / db-03-dev",
      "action_objective": "What query/task this agent must perform",
      "expected_inputs": "...",
      "key_outputs_for_downstream": "..."
    }}
  ],
  "verification_and_guardrails": [
    "Checks against distractors, wrong products, cancelled orders, or staged vs shipped states"
  ],
  "final_synthesis_logic": "How to assemble the final response for the user"
}}
"""

        response = client.models.generate_content(
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
        except Exception:
            return {
                "status": "success",
                "model_used": self.model_id,
                "raw_response": response.text
            }

    def _build_preflight_plan(self, user_prompt: str, architectures: Dict[str, Any], pings: Dict[str, Any]) -> Dict[str, Any]:
        """Constructs an introspection-grounded pre-flight plan while waiting for Gemini API key."""
        # Introspect table lists from columns
        domain_tables = {}
        for domain, info in architectures.items():
            cols = info.get("database_schema", {}).get("rows", [])
            tables = sorted(list({c.get("TABLE_NAME") for c in cols if c.get("TABLE_NAME")}))
            domain_tables[domain] = {
                "server": info.get("server_name"),
                "status": pings.get(domain, {}).get("status"),
                "available_tools": info.get("available_tools"),
                "tables": tables,
                "total_columns_discovered": len(cols)
            }

        return {
            "status": "initialized_awaiting_api_key",
            "message": "Planner Agent initialized. All 3 MCP servers pinged and architectures discovered dynamically. Provide GEMINI_API_KEY to activate generative planning.",
            "user_prompt": user_prompt,
            "orchestrator_constraints": {
                "direct_database_query_access": False,
                "discovery_tools_available": ["ping_all_servers", "list_tools", "get_schema"],
                "hardcoded_schema_knowledge": False
            },
            "introspected_system_architecture": domain_tables,
            "strategic_dispatch_contract": [
                {
                    "step": 1,
                    "worker": "ERP Domain Worker Agent",
                    "target_database": "db-01-dev",
                    "domain": "Commercial System of Record",
                    "goal": "Identify customer and product order ID"
                },
                {
                    "step": 2,
                    "worker": "WMS Domain Worker Agent",
                    "target_database": "db-02-dev",
                    "domain": "Physical Warehouse Execution",
                    "goal": "Trace physical pick status and handling unit LPN"
                },
                {
                    "step": 3,
                    "worker": "TMS Domain Worker Agent",
                    "target_database": "db-03-dev",
                    "domain": "Logistics & Freight Movement",
                    "goal": "Resolve freight manifest, carrier, and tracking number"
                }
            ]
        }
