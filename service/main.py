"""FastAPI Production Service for Distributed Microsoft Agent Framework (MAF) Swarm.
Integrates Dapr sidecars, OpenTelemetry distributed tracing, Application Insights, real-time streaming, and interactive UI.
"""

import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from agents.bus_runtime import MAFMessageBusManager
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

# Global MAF runtime manager
bus_manager = MAFMessageBusManager()
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
    trajectory_scorecard: dict


@app.on_event("startup")
async def startup_event():
    """Initializes the MAF asynchronous message bus runtime on container startup."""
    logging.info("Starting up MAF Message Bus Manager...")
    await bus_manager.initialize_and_start()
    logging.info("MAF Message Bus Manager initialized successfully.")


@app.on_event("shutdown")
async def shutdown_event():
    """Stops the MAF runtime on container shutdown."""
    await bus_manager.shutdown()


@app.get("/health")
async def health_check():
    """Liveness and readiness probe for Azure Container Apps."""
    return {
        "status": "healthy",
        "service": "aca-maf-swarm",
        "runtime": "SingleThreadedAgentRuntime",
        "actors": ["GeminiPlanner", "ERP_Agent", "WMS_Agent", "TMS_Agent"],
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
            # Dispatch across MAF message bus
            resp = await bus_manager.send_user_query(req.query)

            # Evaluate execution trajectory using OpenTelemetry graph
            evaluator = SwarmTrajectoryEvaluator()
            scorecard = evaluator.evaluate_trajectory(resp)

            # Persist session context to long-term memory
            order_id = resp.a2a_trace[0]["response"].get("order_id") if resp.a2a_trace else None
            hu_id = resp.a2a_trace[1]["response"].get("handling_unit_id") if len(resp.a2a_trace) > 1 else None
            await mem_manager.persist_session_memory(
                session_id=resp.session_id,
                user_query=resp.user_query,
                order_id=order_id,
                customer_name="Acme Corp",
                handling_unit_id=hu_id,
                tracking_number=resp.tracking_number,
                is_shipped=resp.is_shipped,
                final_answer=resp.final_answer,
                trace_id=resp.trace_id
            )

            return QueryResponse(
                session_id=resp.session_id,
                trace_id=resp.trace_id,
                user_query=resp.user_query,
                final_answer=resp.final_answer,
                is_shipped=resp.is_shipped,
                tracking_number=resp.tracking_number,
                a2a_trace=resp.a2a_trace,
                trajectory_scorecard=scorecard.model_dump()
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
        # Bind queue in contextvars
        AgentEventStreamer.set_queue(queue)
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
                        "pipeline_start",
                        "System",
                        f"Initializing distributed MAF swarm for query: '{query}'",
                        {"trace_id": trace_id_str, "user_query": query}
                    )

                    # Execute query across MAF message bus
                    resp = await bus_manager.send_user_query(query)

                    # Evaluate execution trajectory
                    evaluator = SwarmTrajectoryEvaluator()
                    scorecard = evaluator.evaluate_trajectory(resp)

                    await AgentEventStreamer.emit(
                        "eval_scorecard",
                        "Evaluator",
                        f"Trajectory Scorecard: {scorecard.verdict} ({int(scorecard.overall_score * 100)}%)",
                        scorecard.model_dump()
                    )

                    # Persist session memory to Cosmos DB
                    order_id = resp.a2a_trace[0]["response"].get("order_id") if resp.a2a_trace else None
                    hu_id = resp.a2a_trace[1]["response"].get("handling_unit_id") if len(resp.a2a_trace) > 1 else None
                    await mem_manager.persist_session_memory(
                        session_id=resp.session_id,
                        user_query=resp.user_query,
                        order_id=order_id,
                        customer_name="Acme Corp",
                        handling_unit_id=hu_id,
                        tracking_number=resp.tracking_number,
                        is_shipped=resp.is_shipped,
                        final_answer=resp.final_answer,
                        trace_id=resp.trace_id or trace_id_str
                    )

                    # Emit completed event
                    await AgentEventStreamer.emit(
                        "completed",
                        "System",
                        "Swarm workflow execution and multi-domain synthesis completed.",
                        {
                            "session_id": resp.session_id,
                            "trace_id": resp.trace_id or trace_id_str,
                            "is_shipped": resp.is_shipped,
                            "tracking_number": resp.tracking_number,
                            "final_answer": resp.final_answer,
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

        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

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
