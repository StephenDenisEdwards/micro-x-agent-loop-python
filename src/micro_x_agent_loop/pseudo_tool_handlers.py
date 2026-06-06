"""Pseudo-tool handlers — pluggable executors for tool calls handled
inline by the agent loop instead of being dispatched to MCP.

Each handler declares the set of tool names it claims via
``claimed_names``; ``PseudoToolRegistry`` builds a name→handler map at
construction time and raises on collisions. Adding a new pseudo tool
means writing a handler, declaring its names, and registering it — no
first-match-wins dispatch ambiguity.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from micro_x_agent_loop.sub_agent import SubAgentType
from micro_x_agent_loop.tasks.schemas import TASK_TOOL_NAMES
from micro_x_agent_loop.usage import estimate_cost

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel
    from micro_x_agent_loop.sub_agent import SubAgentRunner
    from micro_x_agent_loop.tasks.manager import TaskManager
    from micro_x_agent_loop.tool_search import ToolSearchManager
    from micro_x_agent_loop.turn_events import TurnEvents


class PseudoToolHandler(Protocol):
    """Handles a class of pseudo-tools dispatched inside the agent loop."""

    def claimed_names(self) -> frozenset[str]:
        """The exact tool names this handler claims. Used by the registry to
        detect collisions at construction and dispatch by name lookup."""
        ...

    async def execute_batch(self, blocks: list[dict]) -> list[dict]:
        """Execute matched blocks; return one tool_result dict per block."""
        ...


class PseudoToolRegistry:
    """Name-keyed registry that fails loudly on collisions.

    Replaces the previous first-match-wins list dispatch. Construction
    raises ``ValueError`` if two handlers claim the same tool name, so a
    future handler with overlapping claims cannot silently shadow another.
    """

    def __init__(self, handlers: list[PseudoToolHandler]) -> None:
        by_name: dict[str, PseudoToolHandler] = {}
        for handler in handlers:
            for name in handler.claimed_names():
                if name in by_name:
                    existing = type(by_name[name]).__name__
                    incoming = type(handler).__name__
                    raise ValueError(
                        f"PseudoToolRegistry: name {name!r} claimed by both "
                        f"{existing} and {incoming}",
                    )
                by_name[name] = handler
        self._by_name = by_name

    def get(self, name: str) -> PseudoToolHandler | None:
        """Return the handler that claims ``name``, or ``None`` for regular tools."""
        return self._by_name.get(name)


class ToolSearchHandler:
    _NAMES = frozenset({"tool_search"})

    def __init__(self, manager: ToolSearchManager) -> None:
        self._mgr = manager

    def claimed_names(self) -> frozenset[str]:
        return self._NAMES

    async def execute_batch(self, blocks: list[dict]) -> list[dict]:
        results: list[dict] = []
        for block in blocks:
            query = block["input"].get("query", "")
            text = await self._mgr.handle_tool_search(query)
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": text})
            logger.info(f"tool_search query={query!r} loaded={self._mgr.loaded_tool_count}")
        return results


class AskUserHandler:
    _NAMES = frozenset({"ask_user"})

    def __init__(self, channel: AgentChannel) -> None:
        self._channel = channel

    def claimed_names(self) -> frozenset[str]:
        return self._NAMES

    async def execute_batch(self, blocks: list[dict]) -> list[dict]:
        results: list[dict] = []
        for block in blocks:
            question = block["input"].get("question", "")
            options = block["input"].get("options")
            answer = await self._channel.ask_user(question, options)
            text = json.dumps({"answer": answer})
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": text})
            logger.info(f"ask_user question={question!r}")
        return results


class TaskToolHandler:
    def __init__(self, manager: TaskManager) -> None:
        self._mgr = manager

    def claimed_names(self) -> frozenset[str]:
        return TASK_TOOL_NAMES

    async def execute_batch(self, blocks: list[dict]) -> list[dict]:
        results: list[dict] = []
        for block in blocks:
            text = await self._mgr.handle_tool_call(block["name"], block["input"])
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": text})
            logger.info(f"task tool={block['name']}")
        return results


class SubAgentHandler:
    """Runs spawn_subagent calls concurrently and bridges sub-agent
    usage/completion into the parent's events/channel."""

    _NAMES = frozenset({"spawn_subagent"})

    def __init__(
        self,
        runner: SubAgentRunner,
        *,
        channel: AgentChannel | None,
        events: TurnEvents,
    ) -> None:
        self._runner = runner
        self._channel = channel
        self._events = events

    def claimed_names(self) -> frozenset[str]:
        return self._NAMES

    async def execute_batch(self, blocks: list[dict]) -> list[dict]:
        return list(await asyncio.gather(*(self._run_one(b) for b in blocks)))

    async def _run_one(self, block: dict) -> dict:
        tool_input = block["input"]
        task = tool_input.get("task", "")
        type_str = tool_input.get("type", "explore")
        try:
            agent_type = SubAgentType(type_str)
        except ValueError:
            agent_type = SubAgentType.EXPLORE

        if self._channel is not None:
            self._channel.emit_tool_started(block["id"], f"subagent:{agent_type.value}")

        try:
            result = await self._runner.run(task, agent_type)
            for usage in result.usage:
                self._events.on_api_call_completed(usage, f"subagent:{agent_type.value}")
            self._events.on_subagent_completed(
                agent_type=agent_type.value,
                task=task,
                result_summary=result.text[:500],
                turns=result.turns,
                timed_out=result.timed_out,
                cost_usd=sum(estimate_cost(u) for u in result.usage),
                api_calls=len(result.usage),
            )
            logger.info(
                f"spawn_subagent type={agent_type.value} turns={result.turns} "
                f"result_chars={len(result.text)} timed_out={result.timed_out}"
            )
            return {"type": "tool_result", "tool_use_id": block["id"], "content": result.text}
        except Exception as ex:
            logger.error(f"spawn_subagent failed: {ex}")
            return {
                "type": "tool_result",
                "tool_use_id": block["id"],
                "content": f"Sub-agent error: {ex}",
                "is_error": True,
            }
        finally:
            if self._channel is not None:
                self._channel.emit_tool_completed(block["id"], f"subagent:{agent_type.value}", False)
