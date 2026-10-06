"""CLI Runner demonstrating the Multi-Agent Swarm Orchestrator.
Dispatches queries dynamically via Google Gemini reasoning across live ERP, WMS, and TMS MCP servers,
recording OpenTelemetry distributed traces and evaluating trajectories.
"""

import sys
import os
import asyncio
import json
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agents.orchestrator import MultiAgentOrchestrator
from agents.messages import SwarmResolutionResponse
from agents.telemetry import get_trajectory_recorder, get_tracer
from agents.evaluations import SwarmTrajectoryEvaluator
from agents.memory import LongTermMemoryManager


async def main():
    query = "Has customer Acme Corp's laptop order shipped?"
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])

    recorder = get_trajectory_recorder()
    recorder.clear()

    orchestrator = MultiAgentOrchestrator()
    swarm_res = await orchestrator.solve_query(query)

    # Map execution steps to a2a_trace format
    a2a_trace = [
        {
            "step": s.step_number,
            "sender": "PlannerAgent",
            "recipient": s.agent_name,
            "domain": s.domain,
            "objective": s.objective,
            "sql_executed": s.sql_executed,
            "response": {
                "row_count": len(s.records_returned),
                "rows": s.records_returned
            }
        }
        for s in swarm_res.execution_steps
    ]

    ans_lower = swarm_res.synthesized_answer.lower()
    is_shipped = ("yes" in ans_lower and "shipped" in ans_lower) or ("in_transit" in ans_lower)
    import re
    trk_match = re.search(r"trk-[a-z0-9-]+", ans_lower)
    tracking_num = trk_match.group(0).upper() if trk_match else None
    session_id = f"session-{int(time.time())}"

    response = SwarmResolutionResponse(
        user_query=query,
        final_answer=swarm_res.synthesized_answer,
        a2a_trace=a2a_trace,
        is_shipped=is_shipped,
        tracking_number=tracking_num,
        session_id=session_id,
        trace_id=f"trace-{int(time.time())}"
    )

    print("\n" + "=" * 75)
    print("📊 MULTI-AGENT SWARM EXECUTION TRACE")
    print("=" * 75)
    print(f"Session ID:   {response.session_id}")
    print(f"User Query:   {response.user_query}")
    print(f"Is Shipped:   {response.is_shipped}")
    print(f"Tracking #:   {response.tracking_number}")
    print("\nExecution Steps Across Domains:")
    for hop in response.a2a_trace:
        print(f"  Step {hop['step']}: {hop['sender']} ──> {hop['recipient']} ({hop['domain']})")
        print(f"       Objective: {hop['objective']}")
        print(f"       SQL:       {hop['sql_executed']}")
        print(f"       Rows:      {hop['response']['row_count']}")
    print("=" * 75)

    # Evaluate Trajectory with OpenTelemetry Execution Graph
    evaluator = SwarmTrajectoryEvaluator()
    scorecard = evaluator.evaluate_trajectory(response)

    print("\n" + "=" * 75)
    print("🔍 OPENTELEMETRY TRAJECTORY EVALUATION SCORECARD")
    print("=" * 75)
    print(f"Total Distributed Spans:   {scorecard.total_spans_recorded}")
    print(f"Execution Duration:        {scorecard.total_duration_ms:.1f} ms")
    print(f"Trajectory Completeness:   {scorecard.trajectory_completeness_score * 100:.1f}%")
    print(f"Context Propagation:       {scorecard.context_propagation_score * 100:.1f}%")
    print(f"Domain Isolation:          {scorecard.domain_isolation_score * 100:.1f}%")
    print(f"Fact Grounding:            {scorecard.fact_grounding_score * 100:.1f}%")
    print(f"Overall Weighted Score:    {scorecard.overall_score * 100:.1f}%")
    print(f"Trajectory Verdict:        {scorecard.verdict}")
    print("=" * 75)

    # Persist to Long-Term Durable Memory
    mem_mgr = LongTermMemoryManager()
    order_id = None
    hu_id = None
    for s in swarm_res.execution_steps:
        for r in s.records_returned:
            if "Order_ID" in r and not order_id:
                order_id = r["Order_ID"]
            if ("handling_unit_id" in r or "hu_id" in r) and not hu_id:
                hu_id = r.get("handling_unit_id") or r.get("hu_id")

    await mem_mgr.persist_session_memory(
        session_id=response.session_id,
        user_query=response.user_query,
        order_id=order_id,
        customer_name="Acme Corp" if "acme" in query.lower() else None,
        handling_unit_id=hu_id,
        tracking_number=response.tracking_number,
        is_shipped=response.is_shipped,
        final_answer=response.final_answer,
        trace_id=response.trace_id
    )
    print(f"💾 Checkpointed session {response.session_id} to durable long-term memory.")


if __name__ == "__main__":
    asyncio.run(main())
