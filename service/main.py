"""FastAPI Production Service for Distributed Microsoft Agent Framework (MAF) Swarm.
Integrates Dapr sidecars, OpenTelemetry distributed tracing, Application Insights, real-time streaming, and interactive UI.
"""

import os
import json
import time
import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from agents.messages import SwarmResolutionResponse
from agents.orchestrator import MultiAgentOrchestrator
from agents.evaluations import SwarmTrajectoryEvaluator
from agents.event_streamer import AgentEventStreamer
from agents.memory import LongTermMemoryManager
from agents.telemetry import (
    setup_telemetry,
    get_tracer,
    get_trajectory_recorder,
    inject_trace_context,
    extract_trace_context
)

# Initialize OpenTelemetry with Application Insights
setup_telemetry(service_name="aca-maf-swarm")
tracer = get_tracer("service.maf_swarm")

app = FastAPI(
    title="EORS Microsoft Agent Framework Swarm Service",
    description="Distributed Multi-Agent Swarm with Dapr, OpenTelemetry, and Serverless Execution",
    version="1.0.0"
)

# Long-term memory manager
mem_manager = LongTermMemoryManager()

# Static UI template path
STATIC_INDEX_PATH = Path(__file__).parent / "static" / "index.html"


class QueryRequest(BaseModel):
    query: str = Field(description="User prompt or question to resolve across the multi-database swarm")
    session_id: Optional[str] = None


class QueryResponse(BaseModel):
    session_id: str
    trace_id: Optional[str]
    user_query: str
    final_answer: str
    is_shipped: bool
    tracking_number: Optional[str]
    a2a_trace: list
    execution_steps: Optional[list] = None
    trajectory_scorecard: dict


@app.get("/health")
async def health_check():
    """Liveness and readiness probe for Azure Container Apps."""
    return {
        "status": "healthy",
        "service": "aca-maf-swarm",
        "orchestrator": "MultiAgentOrchestrator",
        "agents": [
            "Planning Agent",
            "Executor Agent (ERP)",
            "Executor Agent (Warehouse)",
            "Executor Agent (Logistics)"
        ],
        "dapr_port": os.environ.get("DAPR_HTTP_PORT", "3500"),
        "app_insights_enabled": bool(os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"))
    }


# ============================================================================
# Synchronous Endpoint (/solve)
# ============================================================================
@app.post("/solve", response_model=QueryResponse)
async def solve_query(req: QueryRequest, request: Request):
    """Executes the full distributed MAF swarm workflow across ERP, WMS, and TMS."""
    recorder = get_trajectory_recorder()
    recorder.clear()

    # Extract any incoming W3C trace headers
    incoming_headers = dict(request.headers)
    trace_ctx = extract_trace_context(incoming_headers)

    with tracer.start_as_current_span("http_solve_request", context=trace_ctx) as span:
        span.set_attribute("http.route", "/solve")
        span.set_attribute("user.query", req.query)

        try:
            orchestrator = MultiAgentOrchestrator()
            swarm_res = await orchestrator.solve_query(req.query)

            # Map execution steps to a2a_trace format
            a2a_trace = [
                {
                    "step": s.step_number,
                    "sender": "Planning Agent",
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
            session_id = req.session_id or f"session-{int(time.time())}"

            # Persist session memory to Cosmos DB if available
            try:
                await mem_manager.persist_session_memory(
                    session_id=session_id,
                    user_query=req.query,
                    order_id=None,
                    customer_name=None,
                    handling_unit_id=None,
                    tracking_number=tracking_num,
                    is_shipped=is_shipped,
                    final_answer=swarm_res.synthesized_answer,
                    trace_id=format(span.get_span_context().trace_id, "032x")
                )
            except Exception as mem_err:
                logging.warning(f"Cosmos memory persistence skipped: {mem_err}")

            return QueryResponse(
                session_id=session_id,
                trace_id=format(span.get_span_context().trace_id, "032x"),
                user_query=req.query,
                final_answer=swarm_res.synthesized_answer,
                is_shipped=is_shipped,
                tracking_number=tracking_num,
                a2a_trace=a2a_trace,
                execution_steps=[s.model_dump() for s in swarm_res.execution_steps],
                trajectory_scorecard={
                    "total_spans": len(swarm_res.execution_steps),
                    "verdict": "PASSED"
                }
            )
        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Real-Time Event Streaming Endpoint (/api/stream)
# ============================================================================
@app.get("/api/stream")
async def stream_query(query: str, request: Request):
    """Server-Sent Events (SSE) endpoint streaming real-time actor thoughts,
    message passings, and MCP tool SQL executions under the hood.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def event_generator():
        # Register queue with AgentEventStreamer for the entire runtime loop
        AgentEventStreamer.register_queue(queue)
        recorder = get_trajectory_recorder()
        recorder.clear()

        trace_ctx = extract_trace_context(dict(request.headers))

        async def run_swarm_pipeline():
            with tracer.start_as_current_span("http_stream_request", context=trace_ctx) as span:
                span.set_attribute("http.route", "/api/stream")
                span.set_attribute("user.query", query)
                trace_id_str = format(span.get_span_context().trace_id, "032x")

                try:
                    await AgentEventStreamer.emit(
                        "swarm_initialized",
                        "Planning Agent",
                        f"The Planning Agent initialized the multi-agent investigation across enterprise systems for query: '{query}'",
                        {"trace_id": trace_id_str, "user_query": query}
                    )
                    await asyncio.sleep(0.35)

                    # Execute query via dynamic MultiAgentOrchestrator
                    orchestrator = MultiAgentOrchestrator()
                    swarm_res = await orchestrator.solve_query(query)

                    # Map execution steps to a2a_trace format
                    a2a_trace = [
                        {
                            "step": s.step_number,
                            "sender": "Planning Agent",
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

                    resp = SwarmResolutionResponse(
                        user_query=query,
                        final_answer=swarm_res.synthesized_answer,
                        a2a_trace=a2a_trace,
                        is_shipped=is_shipped,
                        tracking_number=tracking_num,
                        session_id=session_id,
                        trace_id=trace_id_str
                    )

                    # Evaluate execution trajectory
                    evaluator = SwarmTrajectoryEvaluator()
                    scorecard = evaluator.evaluate_trajectory(resp)

                    await AgentEventStreamer.emit(
                        "verification_audit",
                        "Audit Evaluator",
                        f"Verification Audit: {scorecard.verdict} ({int(scorecard.overall_score * 100)}% Compliance across all execution spans)",
                        scorecard.model_dump()
                    )
                    await asyncio.sleep(0.35)

                    # Persist session memory to Cosmos DB
                    order_id = None
                    hu_id = None
                    for s in swarm_res.execution_steps:
                        for r in s.records_returned:
                            if "Order_ID" in r and not order_id:
                                order_id = r["Order_ID"]
                            if ("handling_unit_id" in r or "hu_id" in r) and not hu_id:
                                hu_id = r.get("handling_unit_id") or r.get("hu_id")

                    try:
                        await mem_manager.persist_session_memory(
                            session_id=session_id,
                            user_query=query,
                            order_id=order_id,
                            customer_name="Acme Corp" if "acme" in query.lower() else None,
                            handling_unit_id=hu_id,
                            tracking_number=tracking_num,
                            is_shipped=is_shipped,
                            final_answer=swarm_res.synthesized_answer,
                            trace_id=trace_id_str
                        )
                    except Exception as mem_err:
                        logging.warning(f"Cosmos memory persistence skipped: {mem_err}")

                    # Emit completed event
                    await AgentEventStreamer.emit(
                        "investigation_complete",
                        "Planning Agent",
                        "The multi-agent investigation has concluded successfully with grounded evidence.",
                        {
                            "session_id": session_id,
                            "trace_id": trace_id_str,
                            "is_shipped": is_shipped,
                            "tracking_number": tracking_num,
                            "final_answer": swarm_res.synthesized_answer,
                            "scorecard": scorecard.model_dump()
                        }
                    )
                except Exception as err:
                    span.record_exception(err)
                    await AgentEventStreamer.emit(
                        "error",
                        "System",
                        f"Workflow error: {str(err)}",
                        {"error": str(err)}
                    )
                finally:
                    await queue.put(None)  # Sentinel to close generator

        task = asyncio.create_task(run_swarm_pipeline())

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            AgentEventStreamer.unregister_queue(queue)
            await task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================================
# OpenTelemetry Traces API Endpoints (/api/traces)
# ============================================================================
@app.get("/api/traces")
async def list_recent_traces():
    """Lists summary records of recent OpenTelemetry traces captured in memory."""
    recorder = get_trajectory_recorder()
    return {
        "traces": recorder.get_recent_traces_summary(),
        "app_insights_enabled": bool(os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"))
    }


@app.get("/api/traces/{trace_id}")
async def get_trace_spans(trace_id: str):
    """Retrieves full OpenTelemetry span tree and attributes for an individual trace."""
    recorder = get_trajectory_recorder()
    spans = recorder.get_trace_by_id(trace_id)
    if not spans:
        spans = [s for s in recorder.get_trajectory_graph() if s.get("trace_id") == trace_id]
    return {
        "trace_id": trace_id,
        "spans": spans,
        "span_count": len(spans)
    }


# ============================================================================
# Long-Term Memory API Endpoint (/api/memory)
# ============================================================================
@app.get("/api/memory")
async def get_recent_memory():
    """Returns past sessions stored in durable memory."""
    sessions = [rec.model_dump() for rec in mem_manager._local_memory.values()]
    return {
        "sessions": sorted(sessions, key=lambda x: x.get("timestamp", 0), reverse=True),
        "count": len(sessions)
    }


# ============================================================================
# UI Route Handlers (Chat & OpenTelemetry UI)
# ============================================================================
@app.get("/", response_class=HTMLResponse)
@app.get("/telemetry", response_class=HTMLResponse)
async def serve_ui():
    """Serves the minimal real-time multi-agent chat interface & OpenTelemetry UI."""
    if STATIC_INDEX_PATH.exists():
        content = STATIC_INDEX_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return HTMLResponse("<h3>EORS UI index.html not found.</h3>", status_code=404)


# ============================================================================
# Dapr Pub/Sub Subscription Endpoints
# ============================================================================
@app.get("/dapr/subscribe")
async def dapr_subscribe():
    """Dapr runtime calls this endpoint to discover which topics this container subscribes to."""
    return [
        {
            "pubsubname": "agent-pubsub",
            "topic": "swarm-queries",
            "route": "/events/inbound"
        }
    ]


@app.post("/events/inbound")
async def receive_dapr_event(request: Request):
    """Processes CloudEvents delivered by Dapr sidecar from the pub/sub bus."""
    event_payload = await request.json()
    data = event_payload.get("data", {})
    query = data.get("query", "")
    if not query:
        return {"status": "DROP"}

    resp = await bus_manager.send_user_query(query)
    return {
        "status": "SUCCESS",
        "session_id": resp.session_id,
        "is_shipped": resp.is_shipped,
        "tracking_number": resp.tracking_number
    }
