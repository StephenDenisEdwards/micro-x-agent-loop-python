"""Sub-agent runner — creates lightweight, disposable agent instances for focused tasks.

Sub-agents run in their own context window with restricted tool sets and optionally
cheaper models. They execute a single task and return a summary, protecting the parent
agent's context from exploratory noise.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger

from micro_x_agent_loop.agent_channel import BufferedChannel
from micro_x_agent_loop.app_config import resolve_runtime_env
from micro_x_agent_loop.constants import (
    DEFAULT_SUBAGENT_MAX_TOKENS,
    DEFAULT_SUBAGENT_MAX_TURNS,
    DEFAULT_SUBAGENT_TIMEOUT,
)
from micro_x_agent_loop.provider import create_provider
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.turn_events import BaseTurnEvents
from micro_x_agent_loop.usage import UsageResult

# ---------------------------------------------------------------------------
# Agent type definitions
# ---------------------------------------------------------------------------


class SubAgentType(Enum):
    EXPLORE = "explore"
    SUMMARIZE = "summarize"
    GENERAL = "general"


@dataclass
class SubAgentTypeConfig:
    """Configuration for a sub-agent type."""
    system_prompt: str
    read_only: bool = False
    no_tools: bool = False
    max_turns: int = DEFAULT_SUBAGENT_MAX_TURNS
    max_tokens: int = DEFAULT_SUBAGENT_MAX_TOKENS
    timeout: int = DEFAULT_SUBAGENT_TIMEOUT


_TYPE_CONFIGS: dict[SubAgentType, SubAgentTypeConfig] = {
    SubAgentType.EXPLORE: SubAgentTypeConfig(
        system_prompt=(
            "You are a research assistant. Your job is to find information using the "
            "available tools and return a concise, well-organized summary. "
            "Focus on answering the specific question asked. "
            "Include key facts, names, paths, numbers, and IDs in your response. "
            "Do not include raw tool output — synthesize and summarize."
        ),
        read_only=True,
    ),
    SubAgentType.SUMMARIZE: SubAgentTypeConfig(
        system_prompt=(
            "You are a summarization assistant. Distill the provided content into "
            "a concise summary preserving all decision-relevant information: "
            "key facts, names, numbers, IDs, paths, and errors. "
            "Use bullet points for clarity."
        ),
        no_tools=True,
        max_turns=1,
    ),
    SubAgentType.GENERAL: SubAgentTypeConfig(
        system_prompt=(
            "You are a capable assistant performing a focused subtask. "
            "Complete the task using the available tools and return a clear summary "
            "of what you did and what you found."
        ),
    ),
}


# Well-known read-only tool name patterns (prefix matches)
_READ_ONLY_PATTERNS = frozenset({
    "read_file", "list_directory", "search_files", "get_file_info",
    "bash",  # bash is included but sub-agent prompt discourages mutations
    "web_fetch", "web_search",
    "grep", "glob", "find",
    "get_", "list_", "search_", "read_", "fetch_",
})

# Tool names that are always excluded from read-only sub-agents
_MUTATING_PATTERNS = frozenset({
    "write_file", "append_file", "create_directory", "move_file",
    "delete", "remove", "rename", "update_", "set_", "put_",
    "create_", "post_", "send_", "publish_",
})


def _is_read_only_tool(tool: Tool) -> bool:
    """Determine if a tool should be available to read-only sub-agents."""
    name = tool.name.lower()
    # Check the raw tool name and the part after the server prefix
    parts = name.split("__")
    leaf = parts[-1] if len(parts) > 1 else name

    # Exclude known mutating patterns
    for pattern in _MUTATING_PATTERNS:
        if leaf.startswith(pattern) or leaf == pattern.rstrip("_"):
            return False

    # Check the tool's own is_mutating flag
    if tool.is_mutating:
        return False

    return True


def _filter_tools(
    all_tools: list[Tool],
    type_config: SubAgentTypeConfig,
) -> list[Tool]:
    """Filter parent tools based on sub-agent type restrictions."""
    if type_config.no_tools:
        return []
    if type_config.read_only:
        return [t for t in all_tools if _is_read_only_tool(t)]
    return list(all_tools)


# ---------------------------------------------------------------------------
# Sub-agent tool schema (presented to the parent LLM)
# ---------------------------------------------------------------------------

SPAWN_SUBAGENT_SCHEMA: dict[str, Any] = {
    "name": "spawn_subagent",
    "description": (
        "Delegate a focused task to a sub-agent with its own context window. "
        "Use this for exploratory work (searching files, reading docs, web research) "
        "to avoid polluting your main context. The sub-agent runs to completion and "
        "returns a summary. Types: 'explore' (cheap, read-only — default), "
        "'summarize' (cheap, no tools), 'general' (full capability)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Clear description of what the sub-agent should do and what to return.",
            },
            "type": {
                "type": "string",
                "enum": ["explore", "summarize", "general"],
                "description": (
                    "Agent type: 'explore' (cheap, read-only — default), "
                    "'summarize' (cheap, no tools), 'general' (full capability)."
                ),
            },
        },
        "required": ["task"],
    },
}


# ---------------------------------------------------------------------------
# Sub-agent event collector
# ---------------------------------------------------------------------------


class _SubAgentEvents(BaseTurnEvents):
    """Lightweight TurnEvents that collects messages and aggregates usage."""

    def __init__(self, messages: list[dict]) -> None:
        self._messages = messages
        self.total_usage: list[UsageResult] = []

    def on_append_message(self, role: str, content: str | list[dict]) -> str | None:
        self._messages.append({"role": role, "content": content})
        return None

    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None:
        self.total_usage.append(usage)


# ---------------------------------------------------------------------------
# SubAgentRunner
# ---------------------------------------------------------------------------


@dataclass
class SubAgentResult:
    """Result from a sub-agent execution."""
    text: str
    usage: list[UsageResult] = field(default_factory=list)
    turns: int = 0
    timed_out: bool = False


class SubAgentRunner:
    """Creates and runs lightweight, disposable sub-agent instances."""

    def __init__(
        self,
        *,
        parent_tools: list[Tool],
        provider_name: str,
        api_key: str,
        parent_model: str,
        sub_agent_provider: str = "",
        sub_agent_model: str = "",
        timeout: int = DEFAULT_SUBAGENT_TIMEOUT,
        max_turns: int = DEFAULT_SUBAGENT_MAX_TURNS,
        max_tokens: int = DEFAULT_SUBAGENT_MAX_TOKENS,
        max_tool_result_chars: int = 40_000,
    ) -> None:
        self._parent_tools = parent_tools
        self._provider_name = provider_name
        self._api_key = api_key
        self._parent_model = parent_model
        self._sub_agent_provider = sub_agent_provider
        self._sub_agent_model = sub_agent_model
        self._timeout = timeout
        self._max_turns = max_turns
        self._max_tokens = max_tokens
        self._max_tool_result_chars = max_tool_result_chars

    async def run(self, task: str, agent_type: SubAgentType = SubAgentType.EXPLORE) -> SubAgentResult:
        """Execute a sub-agent task and return the result."""
        from micro_x_agent_loop.turn_engine import TurnEngine  # lazy to avoid circular import

        type_config = _TYPE_CONFIGS[agent_type]

        # Determine model: general inherits parent, others use sub_agent_model
        if agent_type == SubAgentType.GENERAL:
            model = self._parent_model
        else:
            model = self._sub_agent_model

        # Filter tools
        tools = _filter_tools(self._parent_tools, type_config)

        # Create provider (no prompt caching for sub-agents — short-lived)
        if agent_type == SubAgentType.GENERAL:
            sa_provider_name, sa_api_key = self._provider_name, self._api_key
        else:
            sa_provider_name = self._sub_agent_provider
            sa_api_key = resolve_runtime_env(sa_provider_name).provider_api_key
        provider = create_provider(sa_provider_name, sa_api_key)
        converted_tools = provider.convert_tools(tools)
        tool_map = {t.name: t for t in tools}

        # Build lightweight TurnEngine
        messages: list[dict] = []
        events = _SubAgentEvents(messages)

        max_tokens = self._max_tokens or type_config.max_tokens
        max_turns = self._max_turns or type_config.max_turns
        timeout = self._timeout or type_config.timeout

        engine = TurnEngine(
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            temperature=0.3,  # Lower temperature for focused tasks
            system_prompt=type_config.system_prompt,
            converted_tools=converted_tools,
            tool_map=tool_map,
            max_tool_result_chars=self._max_tool_result_chars,
            max_tokens_retries=1,
            events=events,
            channel=BufferedChannel(),
            formatter=ToolResultFormatter(),
        )

        logger.info(
            f"Sub-agent starting: type={agent_type.value} model={model} "
            f"tools={len(tools)} timeout={timeout}s max_turns={max_turns}"
        )

        turns = 0
        timed_out = False

        try:
            # Wrap in a turn-limited loop since TurnEngine.run() handles a
            # full turn (multiple LLM calls until stop_reason != tool_use).
            # We add a timeout around the whole thing.
            async def _run_with_turn_limit() -> None:
                nonlocal turns
                await engine.run(messages=messages, user_message=task)
                turns = len([m for m in messages if m["role"] == "assistant"])

            await asyncio.wait_for(_run_with_turn_limit(), timeout=timeout)

        except TimeoutError:
            timed_out = True
            logger.warning(f"Sub-agent timed out after {timeout}s (type={agent_type.value})")
        except Exception as ex:
            logger.error(f"Sub-agent error: {ex}")
            return SubAgentResult(
                text=f"Sub-agent error: {ex}",
                usage=events.total_usage,
                turns=turns,
            )

        # Extract the final assistant message as the result
        result_text = self._extract_final_response(messages)
        if timed_out and result_text:
            result_text += "\n\n[Note: Sub-agent timed out before completing all work.]"
        elif timed_out:
            result_text = "Sub-agent timed out before producing a response."

        logger.info(
            f"Sub-agent completed: type={agent_type.value} turns={turns} "
            f"result_chars={len(result_text)} api_calls={len(events.total_usage)}"
        )

        return SubAgentResult(
            text=result_text,
            usage=events.total_usage,
            turns=turns,
            timed_out=timed_out,
        )

    @staticmethod
    def _extract_final_response(messages: list[dict]) -> str:
        """Extract the last assistant text from the message history."""
        for msg in reversed(messages):
            if msg["role"] != "assistant":
                continue
            content = msg["content"]
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
                if texts:
                    return "\n".join(texts)
        return ""
