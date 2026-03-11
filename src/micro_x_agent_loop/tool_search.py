from __future__ import annotations

import json
import re
from typing import Any

import tiktoken
from loguru import logger

from micro_x_agent_loop.constants import (
    TOOL_SEARCH_CONTEXT_WINDOWS,
    TOOL_SEARCH_DEFAULT_CONTEXT_WINDOW,
    TOOL_SEARCH_DEFAULT_THRESHOLD_PERCENT,
    TOOL_SEARCH_MAX_LOAD,
)
from micro_x_agent_loop.tool import Tool

_encoding = tiktoken.get_encoding("cl100k_base")

TOOL_SEARCH_SCHEMA: dict[str, Any] = {
    "name": "tool_search",
    "description": (
        "Search for available tools by keyword query. Returns matching tool names "
        "and descriptions. Use this to discover tools before calling them. "
        "After searching, the matching tools will become available for you to call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query to find relevant tools. Use keywords describing "
                    "the action you want to perform (e.g., 'read file', 'search web', "
                    "'send email', 'list repos')."
                ),
            },
        },
        "required": ["query"],
    },
}


def estimate_tool_schema_tokens(converted_tools: list[dict]) -> int:
    """Estimate the token count of all tool schemas combined."""
    total = 0
    for tool in converted_tools:
        total += len(_encoding.encode(tool.get("name", "")))
        total += len(_encoding.encode(tool.get("description", "")))
        total += len(_encoding.encode(json.dumps(tool.get("input_schema", {}))))
    return total


def _get_context_window(model: str) -> int:
    for prefix, window in TOOL_SEARCH_CONTEXT_WINDOWS.items():
        if model.startswith(prefix):
            return window
    return TOOL_SEARCH_DEFAULT_CONTEXT_WINDOW


def should_activate_tool_search(
    setting: str,
    converted_tools: list[dict],
    model: str,
    threshold_percent: int = TOOL_SEARCH_DEFAULT_THRESHOLD_PERCENT,
) -> bool:
    """Determine whether tool search should be active for this session."""
    if setting == "false":
        return False
    if setting == "true":
        return True

    match = re.match(r"auto(?::(\d+))?$", setting)
    if not match:
        logger.warning(f"Unknown ToolSearchEnabled value: {setting!r}, treating as false")
        return False

    if match.group(1):
        threshold_percent = int(match.group(1))

    tool_tokens = estimate_tool_schema_tokens(converted_tools)
    context_window = _get_context_window(model)
    threshold_tokens = int(context_window * threshold_percent / 100)

    active = tool_tokens > threshold_tokens
    logger.info(
        f"Tool search: {tool_tokens:,} tool tokens vs {threshold_tokens:,} threshold "
        f"({threshold_percent}% of {context_window:,}) — {'ACTIVE' if active else 'inactive'}"
    )
    return active


class ToolSearchManager:
    """Manages on-demand tool discovery within a turn.

    Lifecycle:
    - Created once per Agent with all tools and converted tools.
    - ``begin_turn()`` resets loaded tools at the start of each turn.
    - ``get_tools_for_api_call()`` returns the tool schemas to send to the LLM.
    - ``handle_tool_search()`` processes a tool_search call and returns results.
    """

    _MAX_LOAD = TOOL_SEARCH_MAX_LOAD

    def __init__(
        self,
        all_tools: list[Tool],
        converted_tools: list[dict],
    ) -> None:
        self._all_tools = all_tools
        self._all_converted_tools = converted_tools
        # Build index: name -> (Tool, converted_dict)
        self._tool_index: dict[str, tuple[Tool, dict]] = {}
        converted_by_name = {t["name"]: t for t in converted_tools}
        for tool in all_tools:
            conv = converted_by_name.get(tool.name)
            if conv:
                self._tool_index[tool.name] = (tool, conv)

        # Per-turn state
        self._loaded_tool_names: set[str] = set()

    def begin_turn(self) -> None:
        """Reset loaded tools at the start of a new turn."""
        self._loaded_tool_names.clear()

    def get_tools_for_api_call(self) -> list[dict]:
        """Get the tool schemas to send to the LLM for the current API call."""
        result = [TOOL_SEARCH_SCHEMA]
        for name in sorted(self._loaded_tool_names):
            pair = self._tool_index.get(name)
            if pair:
                result.append(pair[1])
        return result

    @staticmethod
    def is_tool_search_call(tool_name: str) -> bool:
        return tool_name == "tool_search"

    def handle_tool_search(self, query: str) -> str:
        """Execute a tool_search query and return matching tool descriptions.

        Also marks matched tools as loaded for the next API call.
        """
        query_lower = query.lower()
        query_terms = query_lower.split()

        matches: list[tuple[str, str, int]] = []  # (name, description, score)

        for name, (tool, _conv) in self._tool_index.items():
            name_lower = name.lower()
            desc_lower = (tool.description or "").lower()

            score = 0
            for term in query_terms:
                if term in name_lower:
                    score += 3
                if term in desc_lower:
                    score += 1

            if score > 0:
                matches.append((name, tool.description or "", score))

        # Sort by score descending, then name for stability
        matches.sort(key=lambda m: (-m[2], m[0]))

        for name, _desc, _score in matches[: self._MAX_LOAD]:
            self._loaded_tool_names.add(name)

        if not matches:
            return (
                f"No tools found matching '{query}'. "
                "Try broader search terms, or search for a specific action "
                "(e.g., 'file', 'web', 'email', 'code')."
            )

        lines = [f"Found {len(matches)} matching tool(s):\n"]
        for name, desc, _score in matches[: self._MAX_LOAD]:
            short_desc = desc[:200] + "..." if len(desc) > 200 else desc
            lines.append(f"- {name}: {short_desc}")

        if len(matches) > self._MAX_LOAD:
            lines.append(f"\n(Showing top {self._MAX_LOAD} of {len(matches)} matches)")

        lines.append("\nThese tools are now loaded. You can call them directly.")
        return "\n".join(lines)

    @property
    def loaded_tool_count(self) -> int:
        return len(self._loaded_tool_names)

    @property
    def total_tool_count(self) -> int:
        return len(self._all_tools)

    def remove_tools(self, tool_names: list[str]) -> None:
        """Remove tools from the search index after live deletion."""
        if not tool_names:
            return
        to_remove = set(tool_names)
        self._all_tools = [tool for tool in self._all_tools if tool.name not in to_remove]
        self._all_converted_tools = [
            tool for tool in self._all_converted_tools if tool.get("name") not in to_remove
        ]
        for name in to_remove:
            self._tool_index.pop(name, None)
            self._loaded_tool_names.discard(name)
