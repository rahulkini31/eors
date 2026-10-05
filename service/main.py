"""FastAPI Production Service for Distributed Microsoft Agent Framework (MAF) Swarm.
Integrates Dapr sidecars, OpenTelemetry distributed tracing, Application Insights, and external state.
"""

import os
import json
import logging
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from agents.bus_runtime import MAFMessageBusManager
from agents.evaluations import SwarmTrajectoryEvaluator
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
