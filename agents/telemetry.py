"""OpenTelemetry Distributed Tracing & Observability Infrastructure for the Multi-Agent Framework (MAF).
Provides TracerProvider configuration, W3C TraceContext propagation, and custom span recording.
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Span, Tracer
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
    SpanExportResult
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.context import Context


# Custom in-memory exporter to capture trajectory spans for evaluation and UI
class InMemorySpanRecorder(SpanExporter):
    """Thread-safe in-memory span collector for trajectory evaluation, UI visualization, and analysis."""

    def __init__(self, max_history_traces: int = 100):
        self._current_spans: List[ReadableSpan] = []
        self._trace_history: Dict[str, List[ReadableSpan]] = {}
        self._max_history = max_history_traces

    def export(self, spans: List[ReadableSpan]) -> SpanExportResult:
        self._current_spans.extend(spans)
        for s in spans:
            trace_id = format(s.context.trace_id, "032x") if s.context else "unknown"
            if trace_id not in self._trace_history:
                # Maintain bounded history
                if len(self._trace_history) >= self._max_history:
                    oldest_key = next(iter(self._trace_history))
                    del self._trace_history[oldest_key]
                self._trace_history[trace_id] = []
            self._trace_history[trace_id].append(s)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def clear(self) -> None:
        """Clears the active session spans without purging historical traces."""
        self._current_spans.clear()

    def get_finished_spans(self) -> List[ReadableSpan]:
        return list(self._current_spans)

    def get_trajectory_graph(self) -> List[Dict[str, Any]]:
        """Formats collected spans into a chronological execution graph."""
        return self._format_spans(self._current_spans)

    def get_trace_by_id(self, trace_id: str) -> List[Dict[str, Any]]:
        """Retrieves and formats all spans for a specific trace ID."""
        spans = self._trace_history.get(trace_id, [])
        return self._format_spans(spans)

    def get_recent_traces_summary(self) -> List[Dict[str, Any]]:
        """Returns high-level summaries for all recorded traces."""
        summaries = []
        for tid, spans in reversed(list(self._trace_history.items())):
            if not spans:
                continue
            sorted_spans = sorted(spans, key=lambda x: x.start_time or 0)
            root_span = sorted_spans[0]
            start_ts = (root_span.start_time / 1_000_000_000) if root_span.start_time else 0.0
            
            # Find total duration
            end_ts = max((s.end_time or 0) for s in sorted_spans)
            duration_ms = ((end_ts - (root_span.start_time or 0)) / 1_000_000) if end_ts and root_span.start_time else 0.0

            # Inspect relevant attributes
            user_query = ""
            for s in sorted_spans:
                if s.attributes and "user.query" in s.attributes:
                    user_query = str(s.attributes["user.query"])
                    break

            summaries.append({
                "trace_id": tid,
                "root_span": root_span.name,
                "start_time": start_ts,
                "duration_ms": round(duration_ms, 2),
                "span_count": len(spans),
                "status": root_span.status.status_code.name,
                "user_query": user_query
            })
        return summaries

    def _format_spans(self, spans: List[ReadableSpan]) -> List[Dict[str, Any]]:
        if not spans:
            return []
        sorted_spans = sorted(spans, key=lambda x: x.start_time or 0)
        base_start = sorted_spans[0].start_time or 0

        graph = []
        for s in sorted_spans:
            trace_id = format(s.context.trace_id, "032x") if s.context else ""
            span_id = format(s.context.span_id, "016x") if s.context else ""
            parent_id = format(s.parent.span_id, "016x") if s.parent else None
            duration_ms = ((s.end_time - s.start_time) / 1_000_000) if s.end_time and s.start_time else 0.0
            offset_ms = ((s.start_time - base_start) / 1_000_000) if s.start_time and base_start else 0.0

            # Clean attributes for JSON serialization
            clean_attrs = {}
            if s.attributes:
                for k, v in s.attributes.items():
                    if isinstance(v, (str, int, float, bool)):
                        clean_attrs[k] = v
                    else:
                        clean_attrs[k] = str(v)

            graph.append({
                "name": s.name,
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_id,
                "status": s.status.status_code.name,
                "start_offset_ms": round(offset_ms, 2),
                "duration_ms": round(duration_ms, 2),
                "attributes": clean_attrs
            })
        return graph


# Global singletons
_tracer_provider: Optional[TracerProvider] = None
_in_memory_recorder: Optional[InMemorySpanRecorder] = None
_w3c_propagator = TraceContextTextMapPropagator()


def setup_telemetry(
    service_name: str = "eors-maf-swarm",
    enable_console_export: bool = False,
    enable_app_insights: bool = True
) -> TracerProvider:
    """Configures OpenTelemetry TracerProvider, processors, and exporters."""
    global _tracer_provider, _in_memory_recorder

    if _tracer_provider is not None:
        return _tracer_provider

    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "eors.agents",
        "service.version": "1.0.0",
        "deployment.environment": os.environ.get("ENVIRONMENT", "development")
    })

    provider = TracerProvider(resource=resource)

    # 1. In-Memory Recorder (always enabled for trajectory analysis)
    _in_memory_recorder = InMemorySpanRecorder()
    provider.add_span_processor(SimpleSpanProcessor(_in_memory_recorder))

    # 2. Console Exporter (for verbose local debugging)
    if enable_console_export or os.environ.get("OTEL_CONSOLE_EXPORT", "").lower() in ("true", "1"):
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    # 3. Azure Application Insights Exporter (if connection string is set)
    app_insights_conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if enable_app_insights and app_insights_conn:
        try:
            from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
            az_exporter = AzureMonitorTraceExporter.from_connection_string(app_insights_conn)
            provider.add_span_processor(BatchSpanProcessor(az_exporter))
            logging.info("Azure Application Insights OpenTelemetry exporter attached.")
        except Exception as e:
            logging.warning(f"Failed to attach Azure Application Insights exporter: {e}")

    # 4. OTLP Exporter (for Jaeger UI / OpenTelemetry Collector if endpoint configured)
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logging.info(f"OTLP Exporter attached pointing to {otlp_endpoint}")
        except Exception as e:
            logging.warning(f"Failed to attach OTLP exporter: {e}")

    # Set as global OpenTelemetry tracer provider
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    return provider


def get_tracer(instrumenting_module_name: str = "maf.actors") -> Tracer:
    """Returns an OpenTelemetry tracer for the given module name."""
    setup_telemetry()
    return trace.get_tracer(instrumenting_module_name)


def get_trajectory_recorder() -> InMemorySpanRecorder:
    """Returns the in-memory trajectory span recorder."""
    setup_telemetry()
    assert _in_memory_recorder is not None
    return _in_memory_recorder


# ============================================================================
# W3C Distributed Context Propagation Helpers
# ============================================================================
def inject_trace_context(carrier: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Injects current span's W3C traceparent and tracestate into a message carrier dictionary."""
    if carrier is None:
        carrier = {}
    _w3c_propagator.inject(carrier)
    return carrier


def extract_trace_context(carrier: Optional[Dict[str, str]]) -> Optional[Context]:
    """Extracts W3C trace context from an incoming message carrier dictionary."""
    if not carrier:
        return None
    return _w3c_propagator.extract(carrier)
