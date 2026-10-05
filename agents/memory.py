"""Long-Term Memory and Durable Context Management for the Multi-Agent Framework.
Externalizes cross-session customer facts, resolved orders, and audit trajectories to Azure Cosmos DB / Redis.
"""

import os
import json
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agents.dapr_bridge import DaprStateStoreManager


class SessionMemoryRecord(BaseModel):
    """Durable record of a completed multi-agent conversation session."""
    session_id: str
    user_query: str
    timestamp: float
    order_id: Optional[str] = None
    customer_name: Optional[str] = None
    handling_unit_id: Optional[str] = None
    tracking_number: Optional[str] = None
    is_shipped: bool
    trace_id: Optional[str] = None
    final_answer: str


class LongTermMemoryManager:
    """Manages long-term externalized memory across swarm sessions using Dapr / Cosmos DB."""

    def __init__(self, dapr_store_name: str = "agent-statestore"):
        self.dapr_client = DaprStateStoreManager(store_name=dapr_store_name)
        # Local fallback store for sandbox / offline execution
        self._local_memory: Dict[str, SessionMemoryRecord] = {}

    async def persist_session_memory(
        self,
        session_id: str,
        user_query: str,
        order_id: Optional[str],
        customer_name: Optional[str],
        handling_unit_id: Optional[str],
        tracking_number: Optional[str],
        is_shipped: bool,
        final_answer: str,
        trace_id: Optional[str] = None
    ) -> SessionMemoryRecord:
        """Persists the session trajectory to durable memory."""
        record = SessionMemoryRecord(
            session_id=session_id,
            user_query=user_query,
            timestamp=time.time(),
            order_id=order_id,
            customer_name=customer_name,
            handling_unit_id=handling_unit_id,
            tracking_number=tracking_number,
            is_shipped=is_shipped,
            trace_id=trace_id,
            final_answer=final_answer
        )

        # 1. Update local cache
        self._local_memory[session_id] = record

        # 2. Checkpoint to Azure Cosmos DB via Dapr sidecar
        await self.dapr_client.save_actor_state(
            actor_id=f"session_mem_{session_id}",
            state_data=record.model_dump()
        )
        return record

    async def recall_session(self, session_id: str) -> Optional[SessionMemoryRecord]:
        """Recalls a specific past session by its unique session ID."""
        if session_id in self._local_memory:
            return self._local_memory[session_id]

        remote = await self.dapr_client.get_actor_state(f"session_mem_{session_id}")
        if remote and not remote.get("fallback"):
            return SessionMemoryRecord.model_validate(remote)
        return None

    async def search_memory_by_customer(self, customer_name: str) -> List[SessionMemoryRecord]:
        """Finds all past orders and tracking movements associated with a given customer."""
        matches = [
            rec for rec in self._local_memory.values()
            if rec.customer_name and customer_name.lower() in rec.customer_name.lower()
        ]
        return matches
