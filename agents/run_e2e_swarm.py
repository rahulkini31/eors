"""End-to-End Runner for the Multi-Agent Swarm.
Executes the core challenge: 'Has customer Acme Corp's laptop order shipped?'
Demonstrates live coordination between Strategic Planner and isolated Domain Executors.
"""

import sys
import os
import asyncio
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agents.orchestrator import MultiAgentOrchestrator


async def main():
    query = "Has customer Acme Corp's laptop order shipped?"
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])

    orchestrator = MultiAgentOrchestrator()
    result = await orchestrator.solve_query(query)

    print("\n" + "=" * 70)
    print("📊 EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Query:                  {result.user_query}")
    print(f"Total Execution Time:   {result.metadata['total_duration_ms']:.2f} ms")
    print(f"All MCP Servers Online: {result.all_servers_healthy}")
    print(f"Total Swarm Steps:      {len(result.execution_steps)}")
    for step in result.execution_steps:
        print(f"  Step {step.step_number} [{step.domain} - {step.agent_name}]: {len(step.records_returned)} rows ({step.duration_ms:.1f}ms)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
