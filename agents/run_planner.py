import os
import sys
import json
import asyncio
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agents.planner_agent import PlannerAgent


async def main():
    parser = argparse.ArgumentParser(description="Strategic Orchestrator Planner Agent (MAF + Google Gemini)")
    parser.add_argument("prompt", nargs="?", default="Has customer Acme Corp's laptop order shipped?", help="User prompt to formulate plan for")
    parser.add_argument("--api-key", default=None, help="Google Gemini API Key (or set GEMINI_API_KEY environment variable)")
    parser.add_argument("--model", default=None, help="Google Gemini Model ID (default: gemini-2.5-flash)")
    args = parser.parse_args()

    print("================================================================================")
    print("  INITIALIZING STRATEGIC ORCHESTRATOR PLANNER AGENT")
    print("  Framework: Microsoft Agent Framework (MAF) Actor")
    print("  Model: Google Gemini")
    print("  Database Direct Access: RESTRICTED / DISABLED")
    print("================================================================================\n")

    planner = PlannerAgent(api_key=args.api_key, model_id=args.model)
    result = await planner.plan(args.prompt)

    print("\n================================================================================")
    print("  PLANNER ORCHESTRATION RESULT")
    print("================================================================================\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
