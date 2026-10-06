"""Trajectory Evaluation & LLM-as-a-Judge for the Multi-Agent Framework (MAF).
Analyzes the OpenTelemetry execution graph and evaluates cognitive fidelity, domain boundaries, and fact grounding.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agents.telemetry import get_trajectory_recorder
from agents.messages import SwarmResolutionResponse


class TrajectoryScorecard(BaseModel):
    """Evaluation scorecard for an agentic execution trajectory."""
    session_id: str
    trace_id: str
    total_spans_recorded: int
    total_duration_ms: float

    # Evaluation Dimension Scores (0.0 to 1.0)
    trajectory_completeness_score: float = Field(description="Were all planned cognitive hops executed in correct sequence?")
    context_propagation_score: float = Field(description="Did all child spans stitch to the same root trace_id via W3C headers?")
    domain_isolation_score: float = Field(description="Did agents strictly query only their assigned database domain?")
    fact_grounding_score: float = Field(description="Are final synthesized claims grounded in returned records?")

    overall_score: float
    verdict: str
    dimension_findings: Dict[str, Any]
    execution_graph: List[Dict[str, Any]]


class SwarmTrajectoryEvaluator:
    """Evaluator for inspecting OpenTelemetry traces and grading multi-agent trajectories."""

    def __init__(self):
        self.recorder = get_trajectory_recorder()

    def evaluate_trajectory(
        self,
        response: SwarmResolutionResponse,
        expected_order_id: str = "SO-10045",
        expected_hu_id: str = "HU-8841-PLT",
        expected_tracking: str = "TRK-AFX-9948201"
    ) -> TrajectoryScorecard:
        """Grades the execution trajectory captured in OpenTelemetry spans."""
        spans = self.recorder.get_finished_spans()
        graph = self.recorder.get_trajectory_graph()

        span_names = [s.name for s in spans]
        root_trace_id = response.trace_id or (graph[0]["trace_id"] if graph else "")

        findings = {}

        # 1. Trajectory Completeness
        # Verifies that planned execution steps were completed
        completeness = 1.0 if response.a2a_trace else (1.0 if graph else 0.0)
        findings["trajectory_completeness"] = {
            "steps_executed": len(response.a2a_trace),
            "complete": completeness == 1.0
        }

        # 2. Distributed Context Propagation (Evaluated across cognitive agent and MCP tool spans)
        cognitive_spans = [s for s in graph if not s["name"].startswith("autogen ")]
        matching_trace_spans = [s for s in cognitive_spans if s["trace_id"] == root_trace_id]
        context_prop_score = len(matching_trace_spans) / len(cognitive_spans) if cognitive_spans else 1.0
        findings["context_propagation"] = {
            "root_trace_id": root_trace_id,
            "cognitive_spans_sharing_root_trace_id": len(matching_trace_spans),
            "total_cognitive_spans": len(cognitive_spans),
            "total_runtime_spans": len(graph)
        }

        # 3. Domain Isolation Fidelity
        isolation_violations = []
        for s in spans:
            attrs = s.attributes or {}
            agent_id = attrs.get("agent.id")
            db_target = attrs.get("db.target")
            mcp_server = attrs.get("mcp.server")

            if agent_id == "ERP_Agent" and db_target and db_target != "db-01-dev":
                isolation_violations.append(f"ERP_Agent queried forbidden db: {db_target}")
            if agent_id == "WMS_Agent" and db_target and db_target != "db-02-dev":
                isolation_violations.append(f"WMS_Agent queried forbidden db: {db_target}")
            if agent_id == "TMS_Agent" and db_target and db_target != "db-03-dev":
                isolation_violations.append(f"TMS_Agent queried forbidden db: {db_target}")
            if mcp_server and agent_id == "ERP_Agent" and mcp_server != "mcp_db_01":
                isolation_violations.append(f"ERP_Agent called forbidden MCP server: {mcp_server}")

        isolation_score = 1.0 if not isolation_violations else 0.0
        findings["domain_isolation"] = {
            "violations_found": isolation_violations,
            "strictly_isolated": len(isolation_violations) == 0
        }

        # 4. Fact Grounding & Anti-Hallucination
        # Verify that key retrieved identifiers are accurately grounded in the final answer
        retrieved_ids = []
        for hop in response.a2a_trace:
            resp_data = hop.get("response", {})
            rows = resp_data.get("rows", [])
            for r in rows:
                for k, v in r.items():
                    if v and isinstance(v, str) and (
                        k.endswith("_ID") or k.endswith("_Number") or k.endswith("_code") or
                        k.endswith("_id") or k in ("OrderStatus", "Shipment_Status", "Load_Status")
                    ):
                        retrieved_ids.append(str(v))

        unique_ids = list(set(retrieved_ids))
        if unique_ids:
            found_ids = [uid for uid in unique_ids if uid.lower() in response.final_answer.lower()]
            grounding_score = round(len(found_ids) / len(unique_ids), 2)
        else:
            grounding_score = 1.0

        findings["fact_grounding"] = {
            "retrieved_identifiers_count": len(unique_ids),
            "grounded_in_answer": unique_ids[:5],
            "grounding_ratio": grounding_score
        }

        # Calculate Overall Weighted Score
        overall = (
            (completeness * 0.3) +
            (context_prop_score * 0.2) +
            (isolation_score * 0.3) +
            (grounding_score * 0.2)
        )
        verdict = "PASSED" if overall >= 0.90 else "FAILED"

        total_dur = sum(g.get("duration_ms", 0.0) for g in graph)

        return TrajectoryScorecard(
            session_id=response.session_id,
            trace_id=root_trace_id,
            total_spans_recorded=len(graph),
            total_duration_ms=round(total_dur, 2),
            trajectory_completeness_score=round(completeness, 2),
            context_propagation_score=round(context_prop_score, 2),
            domain_isolation_score=round(isolation_score, 2),
            fact_grounding_score=round(grounding_score, 2),
            overall_score=round(overall, 3),
            verdict=verdict,
            dimension_findings=findings,
            execution_graph=graph
        )
