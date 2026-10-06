"""Asynchronous client for interacting with the three MCP database servers via SSE."""

import asyncio
import json
import httpx
from typing import Any, Dict, List, Optional
from mcp import ClientSession
from mcp.client.sse import sse_client
from agents.config import MCP_SERVERS


class MCPDiscoveryClient:
    """Client for discovering tools, schemas, and executing queries on decoupled MCP servers."""

    _cached_tools: Dict[str, List[Dict[str, Any]]] = {}
    _cached_schemas: Dict[str, Dict[str, Any]] = {}
    _cached_architectures: Optional[Dict[str, Any]] = None

    def __init__(self, servers: Optional[Dict[str, Dict[str, str]]] = None):
        self.servers = servers or MCP_SERVERS

    async def ping_server(self, domain: str) -> Dict[str, Any]:
        """Pings a single MCP server's /health endpoint."""
        server_info = self.servers[domain]
        health_url = f"{server_info['base_url'].rstrip('/')}{server_info['health_endpoint']}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    return {"domain": domain, "status": "online", "details": resp.json()}
                return {"domain": domain, "status": "error", "code": resp.status_code}
        except Exception as e:
            return {"domain": domain, "status": "unreachable", "error": str(e)}

    async def ping_all_servers(self) -> Dict[str, Any]:
        """Pings all three MCP servers in parallel."""
        domains = list(self.servers.keys())
        tasks = [self.ping_server(d) for d in domains]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = {}
        for d, res in zip(domains, results):
            if isinstance(res, Exception):
                out[d] = {"domain": d, "status": "error", "error": str(res)}
            else:
                out[d] = res
        return out

    async def list_tools_for_server(self, domain: str, max_retries: int = 4, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Connects via SSE and returns the list of exposed tools for a specific domain server."""
        if not force_refresh and domain in MCPDiscoveryClient._cached_tools:
            return MCPDiscoveryClient._cached_tools[domain]

        server_info = self.servers[domain]
        sse_url = f"{server_info['base_url'].rstrip('/')}{server_info['sse_endpoint']}"
        last_error = None
        for attempt in range(max_retries):
            try:
                async with sse_client(sse_url) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools_response = await session.list_tools()
                        tools = [
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                                "input_schema": tool.inputSchema
                            }
                            for tool in tools_response.tools
                        ]
                        MCPDiscoveryClient._cached_tools[domain] = tools
                        return tools
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

    async def get_schema_for_server(self, domain: str, table_name: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Any]:
        """Calls get_schema_db_XX on the target domain server to dynamically inspect table structures."""
        if not table_name and not force_refresh and domain in MCPDiscoveryClient._cached_schemas:
            return MCPDiscoveryClient._cached_schemas[domain]

        tool_map = {
            "ERP": "get_schema_db_01",
            "WMS": "get_schema_db_02",
            "TMS": "get_schema_db_03"
        }
        tool_name = tool_map[domain]
        args = {"table_name": table_name} if table_name else {}
        schema = await self.execute_tool(domain, tool_name, args)
        if not table_name:
            MCPDiscoveryClient._cached_schemas[domain] = schema
        return schema

    async def _discover_single_domain(self, domain: str) -> tuple:
        """Discovers tools and schema for a single domain server."""
        ping_res = await self.ping_server(domain)
        tools = await self.list_tools_for_server(domain)
        schema = await self.get_schema_for_server(domain)
        return domain, {
            "server_name": self.servers[domain]["name"],
            "domain_description": self.servers[domain]["domain"],
            "status": ping_res.get("status"),
            "available_tools": [t["name"] for t in tools],
            "tool_definitions": tools,
            "database_schema": schema
        }

    async def discover_all_architectures(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Dynamically reads the architecture of ERP, WMS, and TMS in parallel without prior hardcoding."""
        if not force_refresh and MCPDiscoveryClient._cached_architectures:
            return MCPDiscoveryClient._cached_architectures

        tasks = [self._discover_single_domain(d) for d in self.servers]
        results = await asyncio.gather(*tasks)
        architectures = dict(results)
        MCPDiscoveryClient._cached_architectures = architectures
        return architectures
