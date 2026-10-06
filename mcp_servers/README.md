# Dedicated MCP Database Servers

Three dedicated Model Context Protocol (MCP) servers deployed as independent Azure Container Apps to isolate access to three Azure SQL databases (`db-01-dev`, `db-02-dev`, and `db-03-dev`) on server `eosr-db-server.database.windows.net`.

## Security & Architecture Highlights

1. **No Database Parameter (Eliminates Hallucination)**:
   - Database connection is strictly hardcoded in the server environment.
   - Tools accept zero database parameters.
2. **Protocol-Level Read-Only Guardrails**:
   - Pydantic v2 input validation models.
   - Strict AST/token-level regex validation prohibiting all mutating and administrative commands (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `EXEC`, `MERGE`, etc.).
3. **Database Engine PoLP Guardrail**:
   - Each container app is bound to a dedicated User-Assigned Managed Identity (UAMI).
   - SQL Contained Users exist only in their respective databases with membership strictly limited to the `db_datareader` role.
4. **Serverless Process Sandboxing**:
   - Deployed on Azure Container Apps Serverless Consumption profile.
   - Minimum replicas configured to `0` (scale-to-zero when idle, spin up to 1 on incoming request).

---

## Deployed Endpoints & Identities

| MCP Server | Database | Attached UAMI | Client ID | ACA Endpoint (SSE) | Health URL |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`mcp_db_01`** | `db-01-dev` | `uami-mcp-db01` | `2b7c9e79-740f-4f78-8bec-84893dd28426` | `https://mcp-db-01.agreeablemeadow-194f1f73.southeastasia.azurecontainerapps.io/sse` | `.../health` |
| **`mcp_db_02`** | `db-02-dev` | `uami-mcp-db02` | `1559fdfb-ac13-4ebe-95b5-d7d9c4928c10` | `https://mcp-db-02.agreeablemeadow-194f1f73.southeastasia.azurecontainerapps.io/sse` | `.../health` |
| **`mcp_db_03`** | `db-03-dev` | `uami-mcp-db03` | `2ce6f5f0-a179-4faa-bbeb-79915b397e06` | `https://mcp-db-03.agreeablemeadow-194f1f73.southeastasia.azurecontainerapps.io/sse` | `.../health` |

---

## Exposed Tools per Server

### `mcp_db_01`
- `get_schema_db_01(table_name?: str)`: Returns column schema information in `db-01-dev`.
- `execute_read_query_db_01(query: str, max_rows: int = 100)`: Executes validated read-only SQL queries in `db-01-dev`.

### `mcp_db_02`
- `get_schema_db_02(table_name?: str)`: Returns column schema information in `db-02-dev`.
- `execute_read_query_db_02(query: str, max_rows: int = 100)`: Executes validated read-only SQL queries in `db-02-dev`.

### `mcp_db_03`
- `get_schema_db_03(table_name?: str)`: Returns column schema information in `db-03-dev`.
- `execute_read_query_db_03(query: str, max_rows: int = 100)`: Executes validated read-only SQL queries in `db-03-dev`.
