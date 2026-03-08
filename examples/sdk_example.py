"""Example usage of the micro-x-agent Python client SDK.

Prerequisites:
    1. Start the API server: python -m micro_x_agent_loop --server start
    2. Run this script: python examples/sdk_example.py
"""

from __future__ import annotations

import asyncio

from micro_x_agent_loop.server.sdk import AgentClient


async def main() -> None:
    async with AgentClient("http://localhost:8321") as client:
        # Check server health
        health = await client.health()
        print(f"Server: {health.status}, tools={health.tools}, memory={health.memory_enabled}")

        # -- Non-streaming chat --
        print("\n--- Non-streaming chat ---")
        reply = await client.chat("What is the capital of France?")
        print(f"Session: {reply.session_id}")
        print(f"Reply: {reply.text}")

        # -- Streaming chat --
        print("\n--- Streaming chat ---")
        async with client.stream("Count from 1 to 5, one number per line.") as stream:
            print(f"Session: {stream.session_id}")
            print("Response: ", end="")
            async for event in stream:
                if event["type"] == "text_delta":
                    print(event["text"], end="", flush=True)
                elif event["type"] == "tool_started":
                    print(f"\n  [tool: {event['tool']}]", end="")
                elif event["type"] == "tool_completed":
                    print(" done" if not event.get("error") else " error", end="")
                elif event["type"] == "turn_complete":
                    print()  # newline after response

        # -- Session management --
        print("\n--- Sessions ---")
        sessions = await client.list_sessions()
        print(f"Active sessions: {len(sessions)}")


if __name__ == "__main__":
    asyncio.run(main())
