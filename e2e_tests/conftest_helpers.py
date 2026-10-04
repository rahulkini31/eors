"""Shared test fixtures, migration parsers, in-memory relational simulators,
and live Azure SQL (pytds + Entra ID) connectors for the E2E test suite.
"""

import os
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MIGRATIONS_DIR = os.path.join(PROJECT_ROOT, "migrations")

MIGRATION_FILES = {
    "db-01-dev": os.path.join(MIGRATIONS_DIR, "db_01_erp.sql"),
    "db-02-dev": os.path.join(MIGRATIONS_DIR, "db_02_wms.sql"),
    "db-03-dev": os.path.join(MIGRATIONS_DIR, "db_03_tms.sql"),
}

# In-memory database caches
_in_memory_dbs: Dict[str, sqlite3.Connection] = {}


def tsql_to_sqlite(sql: str) -> str:
    """Translates standard T-SQL DDL and DML statements to SQLite dialect.
    Preserves table structure, columns, types, constraints, and seed data.
    """
    lines = []
    for line in sql.splitlines():
        trimmed = line.strip()
        # Drop GO batch separators
        if trimmed.upper() == "GO":
            continue
        # Drop T-SQL IF OBJECT_ID checks (handled natively by SQLite DROP TABLE IF EXISTS)
        if "IF OBJECT_ID" in line or "DROP TABLE" in line:
            continue
        lines.append(line)

    text = "\n".join(lines)
    # Strip dbo. prefix
    text = re.sub(r"\bdbo\.", "", text)
    # Replace IDENTITY primary key patterns
    text = re.sub(
        r"INT\s+IDENTITY\(\s*1\s*,\s*1\s*\)\s+NOT\s+NULL\s+PRIMARY\s+KEY",
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"IDENTITY\(\s*1\s*,\s*1\s*\)", "AUTOINCREMENT", text, flags=re.IGNORECASE)
    # Replace T-SQL functions and types
    text = re.sub(r"SYSUTCDATETIME\(\)", "CURRENT_TIMESTAMP", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDATETIME2\b", "TEXT", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNVARCHAR\b", "TEXT", text, flags=re.IGNORECASE)
    text = re.sub(r"\bVARCHAR\b", "TEXT", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDECIMAL\(\d+,\s*\d+\)", "REAL", text, flags=re.IGNORECASE)
    text = re.sub(r"\bBIT\b", "INTEGER", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDATE\b", "TEXT", text, flags=re.IGNORECASE)
    # Strip national character prefix N'...' only when preceding quote
    text = re.sub(r"(?<![A-Za-z0-9_])N'", "'", text)

    return text


def load_in_memory_db(db_key: str, reset: bool = False) -> sqlite3.Connection:
    """Loads a migration script into an in-memory SQLite database instance.
    `db_key` can be 'db-01-dev', 'db-02-dev', 'db-03-dev' or 'erp', 'wms', 'tms'.
    """
    normalized_key = db_key.lower()
    if "01" in normalized_key or "erp" in normalized_key:
        file_key = "db-01-dev"
    elif "02" in normalized_key or "wms" in normalized_key:
        file_key = "db-02-dev"
    elif "03" in normalized_key or "tms" in normalized_key:
        file_key = "db-03-dev"
    else:
        raise ValueError(f"Unknown database key: {db_key}")

    if not reset and file_key in _in_memory_dbs:
        return _in_memory_dbs[file_key]

    sql_path = MIGRATION_FILES[file_key]
    if not os.path.exists(sql_path):
        raise FileNotFoundError(f"Migration file not found: {sql_path}")

    with open(sql_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    sqlite_sql = tsql_to_sqlite(sql_content)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(sqlite_sql)

    _in_memory_dbs[file_key] = conn
    return conn


def parse_migration_metadata(file_path: str) -> Dict[str, Any]:
    """Parses a migration SQL file to extract structural metadata:
    tables created, columns per table, primary keys, foreign keys, and seed row counts.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find CREATE TABLE statements
    table_pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:dbo\.)?([A-Za-z0-9_]+)\s*\((.*?)\);",
        re.DOTALL | re.IGNORECASE,
    )
    tables: Dict[str, Dict[str, Any]] = {}

    for match in table_pattern.finditer(content):
        table_name = match.group(1)
        body = match.group(2)

        columns: List[Dict[str, Any]] = []
        foreign_keys: List[Dict[str, str]] = []
        primary_keys: List[str] = []

        # Split column definitions
        for raw_line in body.splitlines():
            line = raw_line.strip()
            # Strip trailing comments
            line = re.sub(r"--.*$", "", line).strip()
            if not line:
                continue
            if line.endswith(","):
                line = line[:-1].strip()

            # Check if line is a table-level constraint
            if re.match(r"^PRIMARY\s+KEY", line, re.IGNORECASE):
                pk_cols = re.findall(r"([A-Za-z0-9_]+)", line[11:])
                primary_keys.extend(pk_cols)
                continue
            if re.match(r"^FOREIGN\s+KEY", line, re.IGNORECASE):
                fk_match = re.search(
                    r"FOREIGN\s+KEY\s*\(([A-Za-z0-9_]+)\)\s*REFERENCES\s*(?:dbo\.)?([A-Za-z0-9_]+)\s*\(([A-Za-z0-9_]+)\)",
                    line,
                    re.IGNORECASE,
                )
                if fk_match:
                    foreign_keys.append({
                        "column": fk_match.group(1),
                        "ref_table": fk_match.group(2),
                        "ref_column": fk_match.group(3),
                    })
                continue

            # Standard column definition
            col_match = re.match(r"^([A-Za-z0-9_]+)\s+([A-Za-z0-9_]+(?:\([0-9,\s]+\))?)(.*)$", line)
            if col_match:
                col_name = col_match.group(1)
                col_type = col_match.group(2)
                col_rest = col_match.group(3)

                is_pk = "PRIMARY KEY" in col_rest.upper()
                if is_pk:
                    primary_keys.append(col_name)

                # Column-level REFERENCES
                ref_match = re.search(
                    r"REFERENCES\s+(?:dbo\.)?([A-Za-z0-9_]+)\s*\(([A-Za-z0-9_]+)\)",
                    col_rest,
                    re.IGNORECASE,
                )
                if ref_match:
                    foreign_keys.append({
                        "column": col_name,
                        "ref_table": ref_match.group(1),
                        "ref_column": ref_match.group(2),
                    })

                columns.append({
                    "name": col_name,
                    "type": col_type.upper(),
                    "not_null": "NOT NULL" in col_rest.upper(),
                    "is_pk": is_pk,
                })

        tables[table_name] = {
            "columns": columns,
            "column_names": [c["name"] for c in columns],
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys,
        }

    # Count INSERT statements per table
    insert_pattern = re.compile(
        r"INSERT\s+INTO\s+(?:dbo\.)?([A-Za-z0-9_]+)",
        re.IGNORECASE,
    )
    insert_counts: Dict[str, int] = {}
    for match in insert_pattern.finditer(content):
        tname = match.group(1)
        insert_counts[tname] = insert_counts.get(tname, 0) + 1

    return {
        "file_path": file_path,
        "tables": tables,
        "table_names": list(tables.keys()),
        "insert_counts": insert_counts,
        "raw_content": content,
    }


def get_live_db_connection(database_name: str, max_retries: int = 4, base_delay: float = 3.0):
    """Creates a TLS-encrypted pytds connection to Azure SQL authenticated via Microsoft Entra ID.
    Includes serverless wake-up retry logic for error 40613 / connection timeouts.
    Returns None if Azure identity credentials cannot be acquired in this environment.
    """
    try:
        import pytds
        import certifi
        from mcp_servers.common.db import get_access_token
    except Exception:
        return None

    server = os.environ.get("SQL_SERVER", "eosr-db-server.database.windows.net")
    delay = base_delay

    for attempt in range(max_retries):
        try:
            import contextlib
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                token = get_access_token()
            return pytds.connect(
                server=server,
                database=database_name,
                access_token_callable=lambda: token,
                cafile=certifi.where(),
                validate_host=False,
                login_timeout=15,
                timeout=30,
                autocommit=True,
            )
        except Exception as ex:
            err = str(ex) or repr(ex)
            if "40613" in err or "not currently available" in err or "timed out" in err:
                time.sleep(delay)
                delay += 3.0
                continue
            return None
    return None


def is_live_db_ready(database_name: str) -> bool:
    """Checks whether the live Azure SQL database is online AND has user tables migrated."""
    conn = get_live_db_connection(database_name, max_retries=1)
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA NOT IN ('sys', 'information_schema')"
        )
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return False
