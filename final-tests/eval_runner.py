"""Automated evaluation and verification runner for the multi-agent test suite.
Executes ground truth SQL queries against live Azure SQL databases on eosr-db-server.database.windows.net.
"""

import os
import sys
import json
import time
import certifi
import pytds
from typing import Any, Dict, List, Optional
from azure.identity import DefaultAzureCredential, AzureCliCredential

# Azure SQL Token Scope
AZURE_SQL_RESOURCE_SCOPE = "https://database.windows.net/.default"
SQL_SERVER = os.environ.get("SQL_SERVER", "eosr-db-server.database.windows.net")

_cached_credential = None


def get_token() -> str:
    global _cached_credential
    if _cached_credential is None:
        try:
            _cached_credential = DefaultAzureCredential()
        except Exception:
            _cached_credential = AzureCliCredential()
    return _cached_credential.get_token(AZURE_SQL_RESOURCE_SCOPE).token


def execute_sql(database: str, query: str) -> List[Dict[str, Any]]:
    """Executes a SQL query on the target database with exponential backoff for serverless wakeup."""
    max_retries = 5
    delay = 5.0
    last_ex = None

    for attempt in range(max_retries):
        try:
            conn = pytds.connect(
                server=SQL_SERVER,
                database=database,
                access_token_callable=get_token,
                cafile=certifi.where(),
                validate_host=False,
                login_timeout=45,
                timeout=60,
                autocommit=True
            )
            try:
                cursor = conn.cursor()
                cursor.execute(query)
                if not cursor.description:
                    return []
                columns = [col[0] for col in cursor.description]
                rows = []
                for row in cursor.fetchall():
                    row_dict = {}
                    for col_name, val in zip(columns, row):
                        if val is None:
                            row_dict[col_name] = None
                        elif isinstance(val, (int, float, str, bool)):
                            row_dict[col_name] = str(val) if isinstance(val, (int, float)) else val
                        else:
                            row_dict[col_name] = str(val)
                    rows.append(row_dict)
                return rows
            finally:
                conn.close()
        except Exception as ex:
            last_ex = ex
            err_text = str(ex) or repr(ex)
            if "not currently available" in err_text or "40613" in err_text or "timed out" in err_text:
                time.sleep(delay)
                delay += 5.0
                continue
            raise ex

    if last_ex:
        raise last_ex
    raise RuntimeError("Failed to connect.")


def run_test_case(tc: Dict[str, Any]) -> Dict[str, Any]:
    """Runs a single test case from the benchmark suite."""
    tc_id = tc["id"]
    category = tc["category"]
    question = tc["question"]

    result = {
        "id": tc_id,
        "category": category,
        "question": question,
        "passed": True,
        "steps_executed": [],
        "errors": []
    }

    try:
        if "sql_query" in tc:
            # Single-domain query
            db = tc["target_database"]
            query = tc["sql_query"]
            t0 = time.time()
            rows = execute_sql(db, query)
            elapsed = time.time() - t0
            result["steps_executed"].append({
                "database": db,
                "sql": query,
                "elapsed_sec": round(elapsed, 2),
                "row_count": len(rows),
                "rows": rows
            })
            if len(rows) == 0:
                result["passed"] = False
                result["errors"].append("Query returned 0 rows.")

        elif "steps" in tc:
            # Multi-domain cross-database query
            for step in tc["steps"]:
                step_num = step["step"]
                db = step["database"]
                query = step["sql_query"]
                t0 = time.time()
                rows = execute_sql(db, query)
                elapsed = time.time() - t0
                result["steps_executed"].append({
                    "step": step_num,
                    "database": db,
                    "description": step.get("description", ""),
                    "sql": query,
                    "elapsed_sec": round(elapsed, 2),
                    "row_count": len(rows),
                    "rows": rows
                })

        return result

    except Exception as e:
        result["passed"] = False
        result["errors"].append(str(e))
        return result


def main():
    suite_path = os.path.join(os.path.dirname(__file__), "test_suite.json")
    with open(suite_path, "r", encoding="utf-8") as f:
        suite = json.load(f)

    test_cases = suite["questions"]
    print(f"================================================================================")
    print(f"  RUNNING BENCHMARK EVALUATION SUITE: {suite['test_suite_name']}")
    print(f"  Target Server: {SQL_SERVER} ({len(test_cases)} Test Cases)")
    print(f"================================================================================\n")

    passed_count = 0
    total_count = len(test_cases)
    start_time = time.time()

    for idx, tc in enumerate(test_cases, 1):
        print(f"[{idx}/{total_count}] Testing {tc['id']}: {tc['question'][:65]}...")
        res = run_test_case(tc)
        if res["passed"]:
            passed_count += 1
            print(f"       STATUS: PASSED ({len(res['steps_executed'])} query step(s))\n")
        else:
            print(f"       STATUS: FAILED")
            for err in res["errors"]:
                print(f"         Error: {err}")
            print()

    total_time = round(time.time() - start_time, 2)
    print(f"================================================================================")
    print(f"  SUMMARY: {passed_count}/{total_count} PASSED in {total_time}s (Success Rate: {round(passed_count/total_count*100, 1)}%)")
    print(f"================================================================================")

    if passed_count != total_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
