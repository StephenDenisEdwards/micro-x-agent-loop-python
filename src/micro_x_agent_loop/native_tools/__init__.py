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

from micro_x_agent_loop.native_tools.filesystem.bash_tool import build_bash_tool
from micro_x_agent_loop.native_tools.filesystem.memory_tool import build_save_memory_tool
from micro_x_agent_loop.native_tools.filesystem.paths import load_path_policy
from micro_x_agent_loop.native_tools.filesystem.read_tools import build_read_tools
from micro_x_agent_loop.native_tools.filesystem.write_tools import build_write_tools
from micro_x_agent_loop.native_tools.system_info import build_system_info_tools
from micro_x_agent_loop.tool import Tool

__all__ = ["build_native_tools"]

_DEFAULT_MEMORY_MAX_LINES = 200


def _build_filesystem_tools(fs_cfg: dict) -> list[Tool]:
    """Native filesystem tools from the top-level ``Filesystem`` config
    block (ADR-025 F6). Absent/empty config → no filesystem tools (the
    MCP filesystem server, if still configured, remains the provider)."""
    if not isinstance(fs_cfg, dict) or not fs_cfg.get("WorkingDir"):
        return []
    policy = load_path_policy(
        str(fs_cfg["WorkingDir"]),
        fs_cfg.get("AllowedDirs"),
        fs_cfg.get("ReadonlyDirs"),
    )
    tools: list[Tool] = []
    tools.extend(build_read_tools(policy))
    tools.extend(build_write_tools(policy))
    tools.extend(build_bash_tool(policy))
    memory_dir = fs_cfg.get("MemoryDir")
    if memory_dir:
        try:
            max_lines = int(fs_cfg.get("MemoryMaxLines", _DEFAULT_MEMORY_MAX_LINES))
        except (TypeError, ValueError):
            max_lines = _DEFAULT_MEMORY_MAX_LINES
        tools.extend(build_save_memory_tool(str(memory_dir), max_lines))
    return tools


def build_native_tools(config: Any | None = None) -> list[Tool]:
    """Return all enabled native tools, registered at bootstrap and logged
    at startup like MCP servers. ``config`` is the AppConfig; its
    ``filesystem_config`` (the top-level ``Filesystem`` block) drives the
    native filesystem tools (ADR-025)."""
    tools: list[Tool] = []
    tools.extend(build_system_info_tools())
    fs_cfg = getattr(config, "filesystem_config", None) or {}
    tools.extend(_build_filesystem_tools(fs_cfg))
    return tools
