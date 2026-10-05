"""MAF Asynchronous Message Bus Runtime Manager.
Hosts and orchestrates event-driven actors using SingleThreadedAgentRuntime.
"""

import asyncio
from typing import Optional
from autogen_core import SingleThreadedAgentRuntime, AgentId

from agents.actors import (
    GeminiPlannerActor,
    ERPActor,
    WMSActor,
    TMSActor
)
from agents.messages import UserQueryMessage, SwarmResolutionResponse


class MAFMessageBusManager:
    """Manages the lifecycle and routing of the Microsoft Agent Framework asynchronous message bus."""

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        planner_model_id: Optional[str] = None,
        executor_model_id: Optional[str] = None
    ):
        self.gemini_key = gemini_api_key
        self.planner_model_id = planner_model_id
        self.executor_model_id = executor_model_id
        self.runtime: Optional[SingleThreadedAgentRuntime] = None

    async def initialize_and_start(self) -> SingleThreadedAgentRuntime:
        """Initializes the SingleThreadedAgentRuntime and registers all four event-driven actors."""
        self.runtime = SingleThreadedAgentRuntime()

        # Register ERP Actor (db-01-dev)
        await ERPActor.register(
            self.runtime,
            type="ERP_Agent",
            factory=lambda: ERPActor(api_key=self.gemini_key, model_id=self.executor_model_id)
        )

        # Register WMS Actor (db-02-dev)
        await WMSActor.register(
            self.runtime,
            type="WMS_Agent",
            factory=lambda: WMSActor(api_key=self.gemini_key, model_id=self.executor_model_id)
        )

        # Register TMS Actor (db-03-dev)
        await TMSActor.register(
            self.runtime,
            type="TMS_Agent",
            factory=lambda: TMSActor(api_key=self.gemini_key, model_id=self.executor_model_id)
        )

        # Register Gemini Planner Orchestrator Actor
        await GeminiPlannerActor.register(
            self.runtime,
            type="GeminiPlanner",
            factory=lambda: GeminiPlannerActor(api_key=self.gemini_key, model_id=self.planner_model_id)
        )

        # Start the MAF event loop
        self.runtime.start()
        print("⚡ [MAF Message Bus] SingleThreadedAgentRuntime started.")
        print("  Registered Actors: [GeminiPlanner, ERP_Agent, WMS_Agent, TMS_Agent]")
        return self.runtime

    async def send_user_query(self, user_query: str) -> SwarmResolutionResponse:
        """Sends an inbound query to the Gemini Planner over the MAF message bus."""
        if self.runtime is None:
            await self.initialize_and_start()

        planner_id = AgentId("GeminiPlanner", "default")
        msg = UserQueryMessage(query=user_query)

        # Dispatch via the MAF runtime routing
        response = await self.runtime.send_message(msg, planner_id)
        return response

    async def shutdown(self):
        """Stops the runtime cleanly."""
        if self.runtime:
            await self.runtime.stop()
            print("🛑 [MAF Message Bus] SingleThreadedAgentRuntime stopped.")
            self.runtime = None
