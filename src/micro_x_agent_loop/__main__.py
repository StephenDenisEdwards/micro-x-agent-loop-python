import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.system_prompt import SYSTEM_PROMPT
from micro_x_agent_loop.tool_registry import get_all


def load_config() -> dict:
    config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


async def main() -> None:
    load_dotenv()

    config = load_config()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)

    model = config.get("Model", "claude-sonnet-4-5-20250929")
    max_tokens = int(config.get("MaxTokens", 8192))
    temperature = float(config.get("Temperature", 1.0))
    max_tool_result_chars = int(config.get("MaxToolResultChars", 40_000))
    max_conversation_messages = int(config.get("MaxConversationMessages", 50))
    documents_directory = config.get("DocumentsDirectory")
    working_directory = config.get("WorkingDirectory")
    google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
    google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    tools = get_all(documents_directory, working_directory, google_client_id, google_client_secret)

    agent = Agent(
        AgentConfig(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=api_key,
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            max_tool_result_chars=max_tool_result_chars,
            max_conversation_messages=max_conversation_messages,
        )
    )

    print("micro-x-agent-loop (type 'exit' to quit)")
    print(f"Tools: {', '.join(t.name for t in tools)}")
    print()

    while True:
        try:
            user_input = input("you> ")
        except (EOFError, KeyboardInterrupt):
            break

        trimmed = user_input.strip()

        if trimmed in ("exit", "quit"):
            break

        if not trimmed:
            continue

        try:
            print("\nassistant> ", end="", flush=True)
            await agent.run(trimmed)
            print("\n")
        except Exception as ex:
            print(f"\nError: {ex}\n", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
