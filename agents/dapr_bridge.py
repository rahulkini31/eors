"""Dapr Distributed Runtime Bridge for Microsoft Agent Framework (MAF).
Bridges MAF event-driven actors with Dapr sidecars, Azure Service Bus Pub/Sub, and Cosmos DB Durable State.
"""

import httpx
from typing import Any, Dict


class DaprStateStoreManager:
    """Externalizes actor memory to Azure Cosmos DB or Redis via the Dapr state store API."""

    def __init__(
        self,
        dapr_http_port: int = 3500,
        store_name: str = "agent-statestore"
    ):
        self.base_url = f"http://localhost:{dapr_http_port}/v1.0/state/{store_name}"

    async def get_actor_state(self, actor_id: str) -> Dict[str, Any]:
        """Pulls current conversation context from Azure Cosmos DB before acting on a message."""
        url = f"{self.base_url}/{actor_id}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)
                if res.status_code == 200 and res.text:
                    return res.json()
                return {}
        except Exception as e:
            # Local fallback / sandbox mode
            return {"fallback": True, "error": str(e)}

    async def save_actor_state(self, actor_id: str, state_data: Dict[str, Any]) -> bool:
        """Checkpoints updated actor state and memory back to Azure Cosmos DB."""
        payload = [
            {
                "key": actor_id,
                "value": state_data
            }
        ]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(self.base_url, json=payload)
                return res.status_code in (200, 204)
        except Exception:
            return False

