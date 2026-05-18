"""Native in-process tools.

Core agent primitives implemented as in-process Python Tool-protocol
objects rather than out-of-process MCP servers. MCP is reserved for
external / third-party integrations; first-party core capabilities are
native (no subprocess, no stdio/SSE, faster, testable with plain pytest).
See ADR amending ADR-015.

``build_native_tools(config)`` returns the enabled native Tool objects,
appended to the MCP-proxied tool list at bootstrap and logged at startup
the same way MCP servers are.
"""

from __future__ import annotations

from typing import Any

from micro_x_agent_loop.native_tools.system_info import build_system_info_tools
from micro_x_agent_loop.tool import Tool

__all__ = ["build_native_tools"]


def build_native_tools(config: Any | None = None) -> list[Tool]:
    """Return all enabled native tools. ``config`` reserved for future
    per-tool gating; unused today (all native tools are read-only/safe)."""
    tools: list[Tool] = []
    tools.extend(build_system_info_tools())
    return tools
