"""Database connection and query executor using Microsoft Entra ID authentication and pytds."""

import os
import time
import certifi
import pytds
from typing import Any, Dict, List, Optional
from azure.identity import ManagedIdentityCredential, DefaultAzureCredential, AzureCliCredential

# Azure SQL database resource scope for Entra ID access tokens
AZURE_SQL_RESOURCE_SCOPE = "https://database.windows.net/.default"

_cached_credential = None


def get_azure_credential():
    """Returns the appropriate Azure credential based on runtime environment."""
    global _cached_credential
    if _cached_credential is not None:
        return _cached_credential

    client_id = os.environ.get("AZURE_CLIENT_ID")
    if client_id:
        try:
            _cached_credential = ManagedIdentityCredential(client_id=client_id)
        except Exception:
            _cached_credential = DefaultAzureCredential()
    else:
        try:
            _cached_credential = DefaultAzureCredential()
        except Exception:
            _cached_credential = AzureCliCredential()

    return _cached_credential


def get_access_token() -> str:
    """Fetch Entra ID access token for Azure SQL database."""
    credential = get_azure_credential()
    token = credential.get_token(AZURE_SQL_RESOURCE_SCOPE)
    return token.token


def get_db_connection(database_name: str) -> pytds.Connection:
    """Creates a TLS-encrypted pytds connection authenticated via Entra ID with retry for serverless wakeup."""
    server = os.environ.get("SQL_SERVER", "eosr-db-server.database.windows.net")
    max_retries = 6
    delay = 6.0
    last_ex = None

    for attempt in range(max_retries):
        try:
            return pytds.connect(
                server=server,
                database=database_name,
                access_token_callable=get_access_token,
                cafile=certifi.where(),
                validate_host=False,
                login_timeout=30,
                timeout=60,
                autocommit=True
            )
        except Exception as ex:
            last_ex = ex
            err_text = str(ex) or repr(ex)
            # If serverless database is currently paused and waking up, wait and retry
            if "not currently available" in err_text or "40613" in err_text or "timed out" in err_text:
                time.sleep(delay)
                delay += 4.0
                continue
            raise ex

    if last_ex:
        raise last_ex
    raise RuntimeError("Failed to connect to database.")


def execute_read(database_name: str, query: str, max_rows: int = 100) -> Dict[str, Any]:
    """Executes a read query against the designated database and returns structured results."""
    conn = get_db_connection(database_name)
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [col[0] for col in cursor.description] if cursor.description else []
        rows: List[Dict[str, Any]] = []
        for row in cursor.fetchmany(max_rows):
            rows.append({col: (str(val) if val is not None else None) for col, val in zip(columns, row)})
        return {
            "status": "success",
            "columns": columns,
            "row_count": len(rows),
            "rows": rows
        }
    finally:
        conn.close()


def get_database_schema(database_name: str, table_name: Optional[str] = None) -> Dict[str, Any]:
    """Returns schema columns of tables in the database."""
    if table_name:
        query = f"""
            SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table_name}'
              AND TABLE_SCHEMA NOT IN ('sys', 'information_schema')
            ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
        """
    else:
        query = """
            SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA NOT IN ('sys', 'information_schema')
            ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
        """
    return execute_read(database_name, query, max_rows=1000)
