"""CLI Runner demonstrating the Microsoft Agent Framework (MAF) Asynchronous Message Bus.
Dispatches queries via AgentId routing, event-driven @message_handler actors, OpenTelemetry tracing, and memory.
"""

import sys
import os
import asyncio
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agents.bus_runtime import MAFMessageBusManager
from agents.telemetry import get_trajectory_recorder
from agents.evaluations import SwarmTrajectoryEvaluator
from agents.memory import LongTermMemoryManager


async def main():
    query = "Has customer Acme Corp's laptop order shipped?"
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])

    recorder = get_trajectory_recorder()
    recorder.clear()

    bus_manager = MAFMessageBusManager()
    await bus_manager.initialize_and_start()

    try:
        response = await bus_manager.send_user_query(query)

        print("\n" + "=" * 75)
        print("📊 MAF ASYNCHRONOUS MESSAGE BUS TRACE")
        print("=" * 75)
        print(f"Session ID:   {response.session_id}")
        print(f"Trace ID:     {response.trace_id}")
        print(f"User Query:   {response.user_query}")
        print(f"Is Shipped:   {response.is_shipped}")
        print(f"Tracking #:   {response.tracking_number}")
        print("\nAgent-to-Agent (A2A) Message Handoffs:")
        for hop in response.a2a_trace:
            print(f"  Hop {hop['step']}: {hop['sender']} ──({hop['request_type']})──> {hop['recipient']}")
            print(f"         Data: {json.dumps(hop['response'])}")
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
        order_id = response.a2a_trace[0]["response"].get("order_id") if response.a2a_trace else None
        hu_id = response.a2a_trace[1]["response"].get("handling_unit_id") if len(response.a2a_trace) > 1 else None
        await mem_mgr.persist_session_memory(
            session_id=response.session_id,
            user_query=response.user_query,
            order_id=order_id,
            customer_name="Acme Corp",
            handling_unit_id=hu_id,
            tracking_number=response.tracking_number,
            is_shipped=response.is_shipped,
            final_answer=response.final_answer,
            trace_id=response.trace_id
        )
        print(f"💾 Checkpointed session {response.session_id} to durable long-term memory.")

    finally:
        await bus_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
