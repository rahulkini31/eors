"""Real-Time Event Streaming Infrastructure for Multi-Agent Swarm.
Uses ContextVar to isolate per-request streaming event queues for Server-Sent Events (SSE).
"""

import asyncio
import contextvars
import time
from typing import Any, Dict, Optional


_stream_queue_var: contextvars.ContextVar[Optional[asyncio.Queue]] = contextvars.ContextVar(
    "agent_stream_queue", default=None
)


class AgentEventStreamer:
    """Publishes structured real-time events from MAF actors to connected frontend clients."""

    @classmethod
    def set_queue(cls, queue: Optional[asyncio.Queue]):
        """Sets the active streaming queue for the current async execution context."""
        _stream_queue_var.set(queue)

    @classmethod
    def get_queue(cls) -> Optional[asyncio.Queue]:
        """Gets the active streaming queue for the current async execution context."""
        return _stream_queue_var.get()

    @classmethod
    async def emit(
        cls,
        event_type: str,
        agent: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None
    ):
        """Asynchronously emits an event to the active SSE queue if one is registered."""
        queue = _stream_queue_var.get()
        if queue is not None:
            payload = {
                "type": event_type,
                "agent": agent,
                "message": message,
                "database": database,
                "data": data or {},
                "timestamp": round(time.time(), 3)
            }
            await queue.put(payload)
