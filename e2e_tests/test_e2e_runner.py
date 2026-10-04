#!/usr/bin/env python3
"""Unified E2E Test Runner for Azure SQL Multi-Agent Cross-Database Challenge (EORS).

Executes all test tiers (Tiers 1-4) and produces a comprehensive verification report:
- Tier 1: Feature Coverage (F1-F15)
- Tier 2: Boundary & Corner Cases
- Tier 3: Cross-Feature Pairwise Interactions
- Tier 4: Real-World Scenarios & Acme Corp Laptop Resolution
"""

import argparse
import os
import sys
import time
import unittest
from typing import Dict, List, Tuple

# Ensure project root is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import test suites
from e2e_tests import (
    test_tier1_features,
    test_tier2_boundaries,
    test_tier3_combinations,
    test_tier4_scenarios,
)
from e2e_tests.conftest_helpers import is_live_db_ready

TIER_MODULES = {
    1: ("Tier 1: Feature Coverage (F1-F15)", test_tier1_features),
    2: ("Tier 2: Boundary & Corner Cases", test_tier2_boundaries),
    3: ("Tier 3: Cross-Feature Interactions", test_tier3_combinations),
    4: ("Tier 4: Real-World Application Scenarios", test_tier4_scenarios),
}


class TierResultSummary:
    def __init__(self, tier_num: int, name: str):
        self.tier_num = tier_num
        self.name = name
        self.tests_run = 0
        self.passed = 0
        self.failed = 0
        self.errors = 0
        self.duration_sec = 0.0
        self.failures_details: List[str] = []


def run_tier(tier_num: int, name: str, module, verbose: bool = False) -> TierResultSummary:
    summary = TierResultSummary(tier_num, name)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(module)

    runner = unittest.TextTestRunner(
        verbosity=2 if verbose else 1,
        stream=sys.stdout if verbose else None,
    )

    t0 = time.time()
    result = runner.run(suite)
    summary.duration_sec = time.time() - t0

    summary.tests_run = result.testsRun
    summary.failed = len(result.failures)
    summary.errors = len(result.errors)
    summary.passed = summary.tests_run - summary.failed - summary.errors

    for test_case, trace in result.failures:
        summary.failures_details.append(f"[FAIL] {test_case}: {trace.splitlines()[-1] if trace else ''}")
    for test_case, trace in result.errors:
        summary.failures_details.append(f"[ERROR] {test_case}: {trace.splitlines()[-1] if trace else ''}")

    return summary


def print_banner(text: str):
    print("=" * 80)
    print(f" {text}")
    print("=" * 80)


def print_live_db_status():
    print("-" * 80)
    print(" Live Azure SQL Environment Check:")
    databases = ["db-01-dev", "db-02-dev", "db-03-dev"]
    for db in databases:
        ready = is_live_db_ready(db)
        status_str = "ONLINE & POPULATED" if ready else "OFFLINE / PENDING MIGRATION (using in-memory SQL fixture)"
        print(f"   [{db}] -> {status_str}")
    print("-" * 80)


def main():
    parser = argparse.ArgumentParser(description="Unified E2E Test Runner for EORS")
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        help="Run only the specified tier (1, 2, 3, or 4)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose test execution output",
    )
    args = parser.parse_args()

    print_banner("Azure SQL Multi-Agent Challenge — E2E Test Suite Runner")
    print_live_db_status()

    tiers_to_run = [args.tier] if args.tier else [1, 2, 3, 4]
    summaries: List[TierResultSummary] = []
    total_t0 = time.time()

    for t_num in tiers_to_run:
        name, mod = TIER_MODULES[t_num]
        print(f"\nExecuting {name}...")
        s = run_tier(t_num, name, mod, verbose=args.verbose)
        summaries.append(s)
        status_icon = "PASSED" if (s.failed == 0 and s.errors == 0) else "FAILED"
        print(f"  -> {status_icon}: {s.passed}/{s.tests_run} passed ({s.duration_sec:.3f}s)")

    total_duration = time.time() - total_t0

    # Aggregate metrics
    total_run = sum(s.tests_run for s in summaries)
    total_pass = sum(s.passed for s in summaries)
    total_fail = sum(s.failed for s in summaries)
    total_err = sum(s.errors for s in summaries)
    pass_rate = (total_pass / total_run * 100.0) if total_run > 0 else 0.0

    print("\n" + "=" * 80)
    print("                      E2E TEST SUITE EXECUTION SUMMARY")
    print("=" * 80)
    print(f" {'Tier':<8} {'Description':<42} {'Total':<8} {'Pass':<8} {'Fail/Err':<10} {'Time':<8}")
    print("-" * 80)

    for s in summaries:
        fail_err_str = f"{s.failed}/{s.errors}"
        print(f" Tier {s.tier_num:<3} {s.name:<42} {s.tests_run:<8} {s.passed:<8} {fail_err_str:<10} {s.duration_sec:<.3f}s")

    print("-" * 80)
    print(f" {'TOTAL':<51} {total_run:<8} {total_pass:<8} {total_fail + total_err:<10} {total_duration:<.3f}s")
    print(f" PASS RATE: {pass_rate:.1f}% ({total_pass}/{total_run})")
    print("=" * 80)

    # Print failure details if any
    any_failures = False
    for s in summaries:
        if s.failures_details:
            any_failures = True
            print(f"\nFailures in Tier {s.tier_num} ({s.name}):")
            for detail in s.failures_details:
                print(f"  {detail}")

    if any_failures:
        print("\n[RESULT] E2E TEST SUITE: FAILED")
        sys.exit(1)
    else:
        print("\n[RESULT] E2E TEST SUITE: 100% PASS (ALL TIERS VERIFIED)")
        sys.exit(0)


if __name__ == "__main__":
    main()
