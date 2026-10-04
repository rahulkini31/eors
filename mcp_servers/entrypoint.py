"""Container entrypoint script that boots the configured MCP database server."""

import os
import sys

server_module = os.environ.get("MCP_SERVER_MODULE", "mcp_db_01.server")

print(f"Booting MCP server module: {server_module}")
if server_module == "mcp_db_01.server":
    import mcp_db_01.server as srv
    srv.mcp.run(transport="sse")
elif server_module == "mcp_db_02.server":
    import mcp_db_02.server as srv
    srv.mcp.run(transport="sse")
elif server_module == "mcp_db_03.server":
    import mcp_db_03.server as srv
    srv.mcp.run(transport="sse")
else:
    raise ValueError(f"Unknown server module: {server_module}")
