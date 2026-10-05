"""Asynchronous client for interacting with the three MCP database servers via SSE."""

import json
import httpx
from typing import Any, Dict, List, Optional
from mcp import ClientSession
from mcp.client.sse import sse_client
from agents.config import MCP_SERVERS


class MCPDiscoveryClient:
    """Client for discovering tools, schemas, and executing queries on decoupled MCP servers."""

    def __init__(self, servers: Optional[Dict[str, Dict[str, str]]] = None):
        self.servers = servers or MCP_SERVERS

    async def ping_server(self, domain: str) -> Dict[str, Any]:
        """Pings a single MCP server's /health endpoint."""
        server_info = self.servers[domain]
        health_url = f"{server_info['base_url'].rstrip('/')}{server_info['health_endpoint']}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    return {"domain": domain, "status": "online", "details": resp.json()}
                return {"domain": domain, "status": "error", "code": resp.status_code}
        except Exception as e:
            return {"domain": domain, "status": "unreachable", "error": str(e)}

    async def ping_all_servers(self) -> Dict[str, Any]:
        """Pings all three MCP servers."""
        results = {}
        for domain in self.servers:
            results[domain] = await self.ping_server(domain)
        return results

    async def list_tools_for_server(self, domain: str, max_retries: int = 4) -> List[Dict[str, Any]]:
        """Connects via SSE and returns the list of exposed tools for a specific domain server."""
        server_info = self.servers[domain]
        sse_url = f"{server_info['base_url'].rstrip('/')}{server_info['sse_endpoint']}"
        last_error = None
        for attempt in range(max_retries):
            try:
                async with sse_client(sse_url) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools_response = await session.list_tools()
                        return [
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "input_schema": tool.inputSchema
                            }
                            for tool in tools_response.tools
                        ]
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt + 1)
        raise RuntimeError(f"Failed to list tools from {domain} after {max_retries} attempts: {last_error}") from last_error

    async def execute_tool(self, domain: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None, max_retries: int = 4) -> Dict[str, Any]:
        """Executes a specific tool on the target domain MCP server via SSE."""
        if domain not in self.servers:
            raise ValueError(f"Unknown domain: {domain}. Must be one of: {list(self.servers.keys())}")

        server_info = self.servers[domain]
        sse_url = f"{server_info['base_url'].rstrip('/')}{server_info['sse_endpoint']}"
        args = arguments or {}
        last_error = None

        for attempt in range(max_retries):
            try:
                async with sse_client(sse_url) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        call_res = await session.call_tool(tool_name, args)
                        if call_res.content and len(call_res.content) > 0:
                            raw_text = call_res.content[0].text
                            try:
                                parsed = json.loads(raw_text)
                                if isinstance(parsed, dict) and parsed.get("status") == "error" and attempt < max_retries - 1:
                                    last_error = parsed.get("error", "database error")
                                    await asyncio.sleep(2 ** attempt + 2)
                                    continue
                                return parsed
                            except Exception:
                                return {"status": "success", "raw": raw_text}
                        return {"status": "empty"}
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt + 1)
        raise RuntimeError(f"Failed to execute {tool_name} on {domain} after {max_retries} attempts: {last_error}") from last_error

    async def get_schema_for_server(self, domain: str, table_name: Optional[str] = None) -> Dict[str, Any]:
        """Calls get_schema_db_XX on the target domain server to dynamically inspect table structures."""
        tool_map = {
            "ERP": "get_schema_db_01",
            "WMS": "get_schema_db_02",
            "TMS": "get_schema_db_03"
        }
        tool_name = tool_map[domain]
        args = {"table_name": table_name} if table_name else {}
        return await self.execute_tool(domain, tool_name, args)

    async def discover_all_architectures(self) -> Dict[str, Any]:
        """Dynamically reads the architecture of ERP, WMS, and TMS without prior hardcoding."""
        architectures = {}
        for domain in self.servers:
            ping_res = await self.ping_server(domain)
            tools = await self.list_tools_for_server(domain)
            schema = await self.get_schema_for_server(domain)
            architectures[domain] = {
                "server_name": self.servers[domain]["name"],
                "domain_description": self.servers[domain]["domain"],
                "status": ping_res.get("status"),
                "available_tools": [t["name"] for t in tools],
                "tool_definitions": tools,
                "database_schema": schema
            }
        return architectures
