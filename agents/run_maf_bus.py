"""CLI Runner demonstrating the Microsoft Agent Framework (MAF) Asynchronous Message Bus.
Dispatches queries via AgentId routing and event-driven @message_handler actors.
"""

import sys
import os
import asyncio
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agents.bus_runtime import MAFMessageBusManager


async def main():
    query = "Has customer Acme Corp's laptop order shipped?"
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])

    bus_manager = MAFMessageBusManager()
    await bus_manager.initialize_and_start()

    try:
        response = await bus_manager.send_user_query(query)
        print("\n" + "=" * 75)
        print("📊 MAF ASYNCHRONOUS MESSAGE BUS TRACE")
        print("=" * 75)
        print(f"Session ID:   {response.session_id}")
        print(f"User Query:   {response.user_query}")
        print(f"Is Shipped:   {response.is_shipped}")
        print(f"Tracking #:   {response.tracking_number}")
        print("\nAgent-to-Agent (A2A) Message Handoffs:")
        for hop in response.a2a_trace:
            print(f"  Hop {hop['step']}: {hop['sender']} ──({hop['request_type']})──> {hop['recipient']}")
            print(f"         Data: {json.dumps(hop['response'])}")
        print("=" * 75)
    finally:
        await bus_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
