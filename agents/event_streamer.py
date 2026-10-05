"""Real-Time Event Streaming Infrastructure for Multi-Agent Swarm.
Broadcasts structured actor events from the MAF runtime loop to connected frontend SSE clients.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional


class AgentEventStreamer:
    """Publishes structured real-time events from MAF actors to connected frontend clients."""

    _active_queues: List[asyncio.Queue] = []
    _session_queues: Dict[str, asyncio.Queue] = {}

    @classmethod
    def register_queue(cls, queue: asyncio.Queue, session_id: Optional[str] = None):
        """Registers an SSE streaming queue."""
        if queue not in cls._active_queues:
            cls._active_queues.append(queue)
        if session_id:
            cls._session_queues[session_id] = queue

    @classmethod
    def unregister_queue(cls, queue: asyncio.Queue, session_id: Optional[str] = None):
        """Unregisters an SSE streaming queue."""
        if queue in cls._active_queues:
            cls._active_queues.remove(queue)
        if session_id:
            cls._session_queues.pop(session_id, None)

    @classmethod
    async def emit(
        cls,
        event_type: str,
        agent: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
        session_id: Optional[str] = None
    ):
        """Asynchronously emits an event to the registered SSE queues."""
        payload = {
            "type": event_type,
            "agent": agent,
            "message": message,
            "database": database,
            "data": data or {},
            "timestamp": round(time.time(), 3)
        }

        # Deliver to session-specific queue if specified, otherwise broadcast to active listeners
        target_queues = []
        if session_id and session_id in cls._session_queues:
            target_queues = [cls._session_queues[session_id]]
        else:
            target_queues = list(cls._active_queues)

        for q in target_queues:
            try:
                await q.put(payload)
            except Exception:
                pass
