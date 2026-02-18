import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.compaction import NoneCompactionStrategy, SummarizeCompactionStrategy
from micro_x_agent_loop.llm_client import create_client
from micro_x_agent_loop.logging_config import setup_logging
from micro_x_agent_loop.system_prompt import get_system_prompt
from micro_x_agent_loop.tool_registry import get_all


def load_config() -> dict:
    # Look for config.json in the current working directory (where run.bat runs from)
    config_path = Path.cwd() / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


async def main() -> None:
    load_dotenv()

    config = load_config()

    log_descriptions = setup_logging(
        level=config.get("LogLevel", "INFO"),
        consumers=config.get("LogConsumers"),
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY environment variable is required.")
        sys.exit(1)

    model = config.get("Model", "claude-sonnet-4-5-20250929")
    max_tokens = int(config.get("MaxTokens", 8192))
    temperature = float(config.get("Temperature", 1.0))
    max_tool_result_chars = int(config.get("MaxToolResultChars", 40_000))
    max_conversation_messages = int(config.get("MaxConversationMessages", 50))
    compaction_strategy_name = config.get("CompactionStrategy", "none").lower()
    compaction_threshold_tokens = int(config.get("CompactionThresholdTokens", 80_000))
    protected_tail_messages = int(config.get("ProtectedTailMessages", 6))
    working_directory = config.get("WorkingDirectory")
    google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
    google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    anthropic_admin_api_key = os.environ.get("ANTHROPIC_ADMIN_API_KEY")

    tools = get_all(working_directory, google_client_id, google_client_secret, anthropic_admin_api_key)

    if compaction_strategy_name == "summarize":
        compaction_strategy = SummarizeCompactionStrategy(
            client=create_client(api_key),
            model=model,
            threshold_tokens=compaction_threshold_tokens,
            protected_tail_messages=protected_tail_messages,
        )
    else:
        compaction_strategy = NoneCompactionStrategy()

    agent = Agent(
        AgentConfig(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=api_key,
            tools=tools,
            system_prompt=get_system_prompt(),
            max_tool_result_chars=max_tool_result_chars,
            max_conversation_messages=max_conversation_messages,
            compaction_strategy=compaction_strategy,
        )
    )

    print("micro-x-agent-loop (type 'exit' to quit)")
    print(f"Tools: {', '.join(t.name for t in tools)}")
    if working_directory:
        print(f"Working directory: {working_directory}")
    if compaction_strategy_name != "none":
        print(f"Compaction: {compaction_strategy_name} (threshold: {compaction_threshold_tokens:,} tokens, tail: {protected_tail_messages} messages)")
    if log_descriptions:
        print(f"Logging: {', '.join(log_descriptions)}")
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
            print()  # newline before spinner
            await agent.run(trimmed)
            print("\n")
        except Exception as ex:
            logger.error(f"Unhandled error: {ex}")


if __name__ == "__main__":
    asyncio.run(main())
