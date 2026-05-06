"""Generated task manifest — loads tools/manifest.json and creates on-demand tool placeholders.

Generated MCP servers are registered in tools/manifest.json by the codegen server.
This module loads the manifest and creates ManifestTool instances that connect
to the generated MCP server on first call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from micro_x_agent_loop.tool import Tool, ToolResult


class ManifestTool:
    """Tool placeholder from manifest.json — connects MCP server on first call.

    Implements the Tool protocol so it can be indexed by ToolSearchManager.
    When execute() is called, it triggers an on-demand MCP server connection
    via the provided connect callback, then delegates to the real McpToolProxy.
    """

    def __init__(
        self,
        task_name: str,
        tool_name: str,
        description: str,
        server_config: dict[str, Any],
        connect_fn: Any,  # async (server_name, config) -> list[Tool]
    ) -> None:
        self._task_name = task_name
        self._tool_name = tool_name
        self._proxy_name = f"{task_name}__{tool_name}"
        self._description = description
        self._server_config = server_config
        self._connect_fn = connect_fn
        self._real_tool: Tool | None = None

    @property
    def name(self) -> str:
        return self._proxy_name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        # Minimal schema — the real schema comes from the MCP server on connection.
        # This placeholder schema allows tool_search to index and the LLM to call.
        return {"type": "object", "properties": {}, "additionalProperties": True}

    @property
    def is_mutating(self) -> bool:
        return True  # Conservative default for generated tools

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        """Connect to the MCP server on first call, then delegate to the real tool."""
        if not self._real_tool:
            try:
                tools = await self._connect_fn(self._task_name, self._server_config)
            except Exception as e:
                logger.error(f"Failed to connect generated server '{self._task_name}': {e}")
                return ToolResult(
                    text=f"Error: failed to connect to generated server '{self._task_name}': {e}",
                    is_error=True,
                )
            # Find the tool by proxy name (server_name__tool_name)
            for t in tools:
                if t.name == self._proxy_name:
                    self._real_tool = t
                    break
            if not self._real_tool:
                available = [t.name for t in tools]
                logger.error(f"Tool '{self._proxy_name}' not found on connected server. Available: {available}")
                return ToolResult(
                    text=f"Error: tool '{self._proxy_name}' not found on connected server. "
                    f"Available: {', '.join(available)}",
                    is_error=True,
                )
            logger.info(f"On-demand connection established for '{self._proxy_name}'")
        return await self._real_tool.execute(tool_input)


def load_manifest(
    project_root: Path,
    connect_fn: Any,
) -> list[ManifestTool]:
    """Load tools/manifest.json and create ManifestTool placeholders.

    Args:
        project_root: Root directory containing tools/manifest.json.
        connect_fn: Async callback (server_name, config) -> list[Tool]
            used for on-demand MCP server connection.

    Returns:
        List of ManifestTool instances for valid manifest entries.
    """
    manifest_path = project_root / "tools" / "manifest.json"
    if not manifest_path.exists():
        return []

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to read manifest: {e}")
        return []

    tools: list[ManifestTool] = []
    for task_name, entry in manifest.items():
        server_config = entry.get("server", {})

        # Validate: task directory must exist
        cwd = server_config.get("cwd", "")
        task_dir = project_root / cwd
        if not task_dir.exists():
            logger.warning(f"Manifest entry '{task_name}': directory '{cwd}' not found, skipping")
            continue

        # Resolve cwd to absolute path. The Agent's resolved config is
        # forwarded to every spawned MCP server by McpManager._run_stdio.
        server_config = {
            **server_config,
            "cwd": str(task_dir.resolve()),
        }

        tool_name = entry.get("tool_name", task_name)
        description = entry.get("description", f"Generated task: {task_name}")

        tools.append(
            ManifestTool(
                task_name=task_name,
                tool_name=tool_name,
                description=description,
                server_config=server_config,
                connect_fn=connect_fn,
            )
        )
        logger.info(f"Manifest tool registered: {task_name}__{tool_name}")

    if tools:
        logger.info(f"Loaded {len(tools)} tool(s) from manifest")
    return tools
