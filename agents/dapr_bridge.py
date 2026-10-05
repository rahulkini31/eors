"""Dapr Distributed Runtime Bridge for Microsoft Agent Framework (MAF).
Bridges MAF event-driven actors with Dapr sidecars, Azure Service Bus Pub/Sub, and Cosmos DB Durable State.
"""

import os
import json
import httpx
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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


class DaprServiceBusBroker:
    """Publishes and routes A2A messages through Azure Service Bus via Dapr Pub/Sub."""

    def __init__(
        self,
        dapr_http_port: int = 3500,
        pubsub_name: str = "agent-pubsub"
    ):
        self.base_url = f"http://localhost:{dapr_http_port}/v1.0/publish/{pubsub_name}"

    async def publish_a2a_message(
        self,
        topic: str,
        message_data: Dict[str, Any],
        correlation_id: str,
        sender_id: str,
        recipient_id: str
    ) -> bool:
        """Dispatches an A2A message into an Azure Service Bus topic.
        Attaches routing and correlation metadata to headers.
        """
        url = f"{self.base_url}/{topic}"
        headers = {
            "Content-Type": "application/cloudevents+json",
            "correlation-id": correlation_id,
            "sender-agent-id": sender_id,
            "recipient-agent-id": recipient_id
        }
        cloudevent = {
            "specversion": "1.0",
            "type": f"maf.a2a.{topic}",
            "source": sender_id,
            "id": correlation_id,
            "datacontenttype": "application/json",
            "data": message_data
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=cloudevent, headers=headers)
                return res.status_code in (200, 204)
        except Exception:
            return False


class DaprMessageEnvelope(BaseModel):
    """Represents a CloudEvent delivered by Dapr sidecar from Azure Service Bus."""
    id: str
    source: str
    type: str
    data: Dict[str, Any]
    service_bus_metadata: Dict[str, Any] = Field(default_factory=dict)
