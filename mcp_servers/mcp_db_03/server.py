"""Dedicated MCP Server for db-03-dev.
Exposes strictly scoped, read-only tools with hardcoded database context.
"""

import os
import sys
from typing import Any, Dict, Optional
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

# Ensure mcp_servers root is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from common.db import execute_read, get_database_schema
from common.validator import TableQueryInput, ReadQueryInput

# Database is strictly bound to db-03-dev
DATABASE_NAME = os.environ.get("SQL_DATABASE", "db-03-dev")
SERVER_NAME = "mcp_db_03"
PORT = int(os.environ.get("PORT", 8000))

mcp = FastMCP(SERVER_NAME, host="0.0.0.0", port=PORT)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({
        "status": "healthy",
        "server": SERVER_NAME,
        "database": DATABASE_NAME
    })


@mcp.tool(name="get_schema_db_03", description="Returns column schemas for tables in db-03-dev. Optionally filter by table_name.")
def get_schema_db_03(table_name: Optional[str] = None) -> Dict[str, Any]:
    """Returns the schema of authorized tables."""
    try:
        # Validate input via Pydantic v2
        validated = TableQueryInput(table_name=table_name)
        return get_database_schema(DATABASE_NAME, table_name=validated.table_name)
    except Exception as e:
        return {"status": "error", "error": str(e) or repr(e)}


@mcp.tool(name="execute_read_query_db_03", description="Executes a validated read-only SQL query against db-03-dev. Mutating queries are strictly rejected.")
def execute_read_query_db_03(query: str, max_rows: int = 100) -> Dict[str, Any]:
    """Accepts a SQL string and executes it after strict protocol-level read-only validation."""
    try:
        # Validate query via Pydantic v2 schema and read-only protocol rules
        validated = ReadQueryInput(query=query, max_rows=max_rows)
        return execute_read(DATABASE_NAME, validated.query, max_rows=validated.max_rows)
    except Exception as e:
        return {"status": "error", "error": str(e) or repr(e)}


if __name__ == "__main__":
    print(f"Starting {SERVER_NAME} on port {PORT} bound strictly to {DATABASE_NAME}...")
    mcp.run(transport="sse")
