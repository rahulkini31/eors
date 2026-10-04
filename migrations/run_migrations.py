#!/usr/bin/env python3
"""Automated SQL Migration Runner for Azure SQL Databases.

Applies DDL and DML migrations to the three autonomous databases:
  - db-01-dev: ERP System of Record (migrations/db_01_erp.sql)
  - db-02-dev: WMS Warehouse Management System (migrations/db_02_wms.sql)
  - db-03-dev: TMS Transportation Management System (migrations/db_03_tms.sql)

Authentication:
  - Microsoft Entra ID OAuth2 token auth via pytds (1.17.1).
  - Multi-tier token resolution:
    1. AZURE_SQL_ACCESS_TOKEN environment variable
    2. DefaultAzureCredential / AzureCliCredential SDK
    3. az account get-access-token subprocess fallback

Resilience:
  - Serverless auto-pause retry loop with exponential backoff
    detecting error 40613, timeouts, and connection reset.
  - T-SQL batch splitting on GO lines.
  - Post-migration table and row count verification.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

import certifi
import pytds

# Default Azure SQL target server
DEFAULT_SQL_SERVER = "eosr-db-server.database.windows.net"
AZURE_SQL_RESOURCE_SCOPE = "https://database.windows.net/.default"

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MIGRATIONS_DIR = os.path.join(PROJECT_ROOT, "migrations")

DATABASE_MIGRATIONS = [
    {
        "database": "db-01-dev",
        "domain": "ERP (Enterprise Resource Planning)",
        "script": os.path.join(MIGRATIONS_DIR, "db_01_erp.sql"),
        "expected_tables": [
            "tbl_Customers",
            "tbl_Inventory_Master",
            "tbl_SalesOrders",
            "tbl_OrderLineItems",
        ],
    },
    {
        "database": "db-02-dev",
        "domain": "WMS (Warehouse Management System)",
        "script": os.path.join(MIGRATIONS_DIR, "db_02_wms.sql"),
        "expected_tables": [
            "bin_locations",
            "dock_doors",
            "inventory_lots",
            "handling_units",
            "outbound_picks",
        ],
    },
    {
        "database": "db-03-dev",
        "domain": "TMS (Transportation Management System)",
        "script": os.path.join(MIGRATIONS_DIR, "db_03_tms.sql"),
        "expected_tables": [
            "Carrier_Master",
            "Freight_Loads",
            "Bill_Of_Lading",
            "Carrier_Manifests",
        ],
    },
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("migration_runner")

_cached_token: Optional[str] = None


def resolve_entra_token() -> str:
    """Acquires Microsoft Entra ID access token using multi-tier resolution."""
    global _cached_token
    if _cached_token:
        return _cached_token

    # Tier 1: Environment variable
    env_token = os.environ.get("AZURE_SQL_ACCESS_TOKEN")
    if env_token and env_token.strip():
        logger.info("Acquired Entra ID token from AZURE_SQL_ACCESS_TOKEN environment variable.")
        _cached_token = env_token.strip()
        return _cached_token

    # Tier 2: Azure Identity SDK (DefaultAzureCredential / AzureCliCredential)
    try:
        from azure.identity import AzureCliCredential, DefaultAzureCredential

        try:
            cred = DefaultAzureCredential()
            token_obj = cred.get_token(AZURE_SQL_RESOURCE_SCOPE)
            if token_obj and token_obj.token:
                logger.info("Acquired Entra ID token via DefaultAzureCredential.")
                _cached_token = token_obj.token
                os.environ["AZURE_SQL_ACCESS_TOKEN"] = _cached_token
                return _cached_token
        except Exception as sdk_ex:
            logger.debug("DefaultAzureCredential attempt: %s", sdk_ex)

        try:
            cli_cred = AzureCliCredential()
            token_obj = cli_cred.get_token(AZURE_SQL_RESOURCE_SCOPE)
            if token_obj and token_obj.token:
                logger.info("Acquired Entra ID token via AzureCliCredential.")
                _cached_token = token_obj.token
                os.environ["AZURE_SQL_ACCESS_TOKEN"] = _cached_token
                return _cached_token
        except Exception as cli_ex:
            logger.debug("AzureCliCredential attempt: %s", cli_ex)
    except ImportError:
        logger.debug("azure-identity package not available for SDK resolution.")

    # Tier 3: Subprocess fallback to az CLI
    try:
        cmd = [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://database.windows.net",
            "-o",
            "json",
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(proc.stdout)
        token = data.get("accessToken")
        if token:
            logger.info("Acquired Entra ID token via az CLI subprocess.")
            _cached_token = token
            os.environ["AZURE_SQL_ACCESS_TOKEN"] = _cached_token
            return _cached_token
    except Exception as sub_ex:
        logger.error("Failed to acquire token via az CLI subprocess: %s", sub_ex)

    raise RuntimeError(
        "Unable to acquire Microsoft Entra ID access token. Please run 'az login' or export AZURE_SQL_ACCESS_TOKEN."
    )


def connect_azure_sql(
    database: str,
    server: str = DEFAULT_SQL_SERVER,
    max_retries: int = 8,
    initial_delay: float = 6.0,
    backoff_factor: float = 4.0,
) -> pytds.Connection:
    """Connects to an Azure SQL database using pytds and Entra ID bearer token.
    Handles serverless cold-start auto-wake (error 40613, connection timeouts).
    """
    token = resolve_entra_token()
    delay = initial_delay
    last_err: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Connecting to [%s] on %s (attempt %d/%d)...",
                database,
                server,
                attempt,
                max_retries,
            )
            conn = pytds.connect(
                server=server,
                database=database,
                access_token_callable=lambda: token,
                cafile=certifi.where(),
                validate_host=False,
                login_timeout=30,
                timeout=60,
                autocommit=True,
            )
            logger.info("Connected successfully to [%s].", database)
            return conn
        except Exception as ex:
            last_err = ex
            err_msg = str(ex) or repr(ex)
            # Detect serverless pause / waking up errors
            is_paused = (
                "40613" in err_msg
                or "not currently available" in err_msg.lower()
                or "timed out" in err_msg.lower()
                or "wantreaderror" in err_msg.lower()
                or "timeouterror" in err_msg.lower()
            )

            if is_paused and attempt < max_retries:
                logger.warning(
                    "Database [%s] is serverless and currently waking up (%s). Sleeping %.1fs before retry...",
                    database,
                    type(ex).__name__,
                    delay,
                )
                time.sleep(delay)
                delay += backoff_factor
                continue
            else:
                logger.error("Connection failed for [%s]: %s", database, err_msg)
                raise ex

    raise RuntimeError(f"Could not connect to [{database}] after {max_retries} attempts: {last_err}")


def split_sql_batches(sql_text: str) -> List[str]:
    """Splits a T-SQL migration script into executable batches delimited by GO statements."""
    # Split on lines containing only 'GO' (case-insensitive, optional comments/whitespace)
    raw_batches = re.split(r"^\s*GO\s*(?:--.*)?$", sql_text, flags=re.MULTILINE | re.IGNORECASE)
    cleaned_batches: List[str] = []

    for b in raw_batches:
        stripped = b.strip()
        # Verify the batch is not purely comments or whitespace
        non_comment_lines = [
            line for line in stripped.splitlines() if line.strip() and not line.strip().startswith("--")
        ]
        if non_comment_lines:
            cleaned_batches.append(stripped)

    return cleaned_batches


def get_batch_summary(batch: str, max_chars: int = 70) -> str:
    """Returns a short human-readable summary of a SQL batch for logging."""
    for line in batch.splitlines():
        line_s = line.strip()
        if line_s and not line_s.startswith("--"):
            if len(line_s) > max_chars:
                return line_s[:max_chars] + "..."
            return line_s
    return batch[:max_chars].strip()


def apply_migration(
    conn: pytds.Connection,
    database_name: str,
    sql_file_path: str,
    dry_run: bool = False,
) -> int:
    """Parses and executes a SQL migration file batch by batch against the target connection."""
    if not os.path.exists(sql_file_path):
        raise FileNotFoundError(f"Migration script not found: {sql_file_path}")

    with open(sql_file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    batches = split_sql_batches(sql_content)
    logger.info(
        "Applying [%s]: parsed %d T-SQL batches from %s",
        database_name,
        len(batches),
        os.path.basename(sql_file_path),
    )

    if dry_run:
        logger.info("[DRY RUN] Would execute %d batches on [%s]. Skipping.", len(batches), database_name)
        return len(batches)

    with conn.cursor() as cur:
        for idx, batch in enumerate(batches, 1):
            summary = get_batch_summary(batch)
            logger.info("  Batch %2d/%2d: %s", idx, len(batches), summary)
            t0 = time.time()
            try:
                cur.execute(batch)
                elapsed = time.time() - t0
                logger.debug("    Batch %d executed in %.3fs", idx, elapsed)
            except Exception as batch_err:
                logger.error("    Error executing batch %d in [%s]: %s", idx, database_name, batch_err)
                logger.error("    Batch SQL snippet:\n%s", batch[:300])
                raise batch_err

    logger.info("Successfully executed all %d batches on [%s].", len(batches), database_name)
    return len(batches)


def verify_database_schema(
    conn: pytds.Connection,
    database_name: str,
    expected_tables: List[str],
) -> Dict[str, int]:
    """Queries INFORMATION_SCHEMA and counts rows for each expected table to verify migration."""
    table_counts: Dict[str, int] = {}
    with conn.cursor() as cur:
        # Check tables in database
        cur.execute(
            """
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE' 
              AND TABLE_SCHEMA NOT IN ('sys', 'information_schema')
            ORDER BY TABLE_NAME
            """
        )
        existing_tables = [row[0] for row in cur.fetchall()]
        logger.info("[%s] Existing user tables: %s", database_name, existing_tables)

        for expected in expected_tables:
            # Check case-insensitively
            matched = next((t for t in existing_tables if t.lower() == expected.lower()), None)
            if not matched:
                logger.error("[%s] MISSING expected table: '%s'", database_name, expected)
                raise AssertionError(f"Table {expected} was not created in {database_name}!")

            # Count rows in each table
            cur.execute(f"SELECT COUNT(*) FROM dbo.{matched}")
            row_count = cur.fetchone()[0]
            table_counts[matched] = row_count
            logger.info("  Table '%s': %d rows", matched, row_count)

    return table_counts


def run_all_migrations(
    server: str = DEFAULT_SQL_SERVER,
    target_db: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """Executes the complete migration pipeline across all specified databases."""
    logger.info("==================================================================")
    logger.info(" Starting Azure SQL Migration Runner for EORS")
    logger.info(" Target Server: %s", server)
    logger.info(" Mode: %s", "DRY RUN" if dry_run else "LIVE EXECUTION")
    logger.info("==================================================================")

    targets = DATABASE_MIGRATIONS
    if target_db:
        targets = [m for m in DATABASE_MIGRATIONS if m["database"].lower() == target_db.lower()]
        if not targets:
            logger.error("Unknown target database '%s'. Valid choices: db-01-dev, db-02-dev, db-03-dev", target_db)
            return False

    overall_start = time.time()
    results: List[Tuple[str, str, Dict[str, int]]] = []

    for item in targets:
        db_name = item["database"]
        domain = item["domain"]
        script_path = item["script"]
        expected = item["expected_tables"]

        logger.info("\n------------------------------------------------------------------")
        logger.info(" Migrating: [%s] — %s", db_name, domain)
        logger.info(" Script:    %s", script_path)
        logger.info("------------------------------------------------------------------")

        if dry_run:
            apply_migration(None, db_name, script_path, dry_run=True)
            results.append((db_name, "DRY_RUN_PASSED", {}))
            continue

        conn = connect_azure_sql(database=db_name, server=server)
        try:
            apply_migration(conn, db_name, script_path, dry_run=False)
            table_counts = verify_database_schema(conn, db_name, expected)
            results.append((db_name, "SUCCESS", table_counts))
        finally:
            conn.close()
            logger.info("Connection closed for [%s].", db_name)

    elapsed_total = time.time() - overall_start

    logger.info("\n==================================================================")
    logger.info(" MIGRATION EXECUTION SUMMARY")
    logger.info(" Total duration: %.2fs", elapsed_total)
    logger.info("==================================================================")

    for db_name, status, counts in results:
        counts_str = ", ".join(f"{tbl}={cnt}" for tbl, cnt in counts.items()) if counts else "N/A"
        logger.info(" [%s] -> Status: %s | Tables: %s", db_name, status, counts_str)

    logger.info("==================================================================")
    logger.info(" All migrations applied and verified successfully!")
    logger.info("==================================================================")
    return True


def main():
    parser = argparse.ArgumentParser(description="Azure SQL Migration Runner (Entra ID + pytds)")
    parser.add_argument(
        "--server",
        default=os.environ.get("SQL_SERVER", DEFAULT_SQL_SERVER),
        help=f"Azure SQL server FQDN (default: {DEFAULT_SQL_SERVER})",
    )
    parser.add_argument(
        "--db",
        choices=["db-01-dev", "db-02-dev", "db-03-dev"],
        default=None,
        help="Migrate a single database (default: all three)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate SQL files without executing against database",
    )
    args = parser.parse_args()

    try:
        success = run_all_migrations(
            server=args.server,
            target_db=args.db,
            dry_run=args.dry_run,
        )
        sys.exit(0 if success else 1)
    except Exception as ex:
        logger.exception("Migration runner failed: %s", ex)
        sys.exit(1)


if __name__ == "__main__":
    main()
