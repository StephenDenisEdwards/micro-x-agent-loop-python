"""`/tool` — inspect / delete individual tools.

Covers: list, details, schema, config, and delete (generated codegen
tasks only). Helpers fan out from ``handle_tool``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from micro_x_agent_loop.commands.command_context import CommandContext
from micro_x_agent_loop.tool import Tool


async def handle_tool(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    parts = command.split()
    if len(parts) == 1:
        _print_tool_list(ctx)
        return
    if len(parts) == 3 and parts[1].lower() == "delete":
        await _delete_generated_tool(ctx, parts[2])
        return
    name_arg = parts[1]
    tool = _resolve_tool_name(ctx, name_arg)
    if tool is None:
        return
    if len(parts) == 2:
        _print_tool_details(ctx, tool)
        return
    sub = parts[2].lower()
    if sub == "schema":
        _print_tool_schema(ctx, tool)
        return
    if sub == "config":
        _print_tool_config(ctx, tool)
        return
    ctx.print(
        f"{p}Usage: /tool | /tool <name> | /tool <name> schema | /tool <name> config | /tool delete <name>"
    )


async def _delete_generated_tool(ctx: CommandContext, name_arg: str) -> None:
    p = ctx.line_prefix
    project_root = Path.cwd()
    manifest_path = project_root / "tools" / "manifest.json"
    if not manifest_path.exists():
        ctx.print(f"{p}No generated tool manifest found: {manifest_path}")
        return

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as ex:
        ctx.print(f"{p}Failed to read manifest: {ex}")
        return

    if not isinstance(manifest, dict):
        ctx.print(f"{p}Manifest format is invalid.")
        return

    task_name = _resolve_manifest_task_name(ctx, manifest, name_arg)
    if task_name is None:
        return

    entry = manifest.pop(task_name)
    try:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except Exception as ex:
        ctx.print(f"{p}Failed to update manifest: {ex}")
        return

    task_dir = _resolve_manifest_task_dir(ctx, project_root, task_name, entry)
    dir_removed = False
    if task_dir is not None and task_dir.exists():
        shutil.rmtree(task_dir)
        dir_removed = True

    deleted_tool_names = [
        tool_name
        for tool_name in list(ctx.tool_map)
        if tool_name == task_name or tool_name.startswith(f"{task_name}__")
    ]
    for tool_name in deleted_tool_names:
        ctx.tool_map.pop(tool_name, None)
    ctx.on_tools_deleted(deleted_tool_names)

    ctx.print(f"{p}Deleted generated task: {task_name}")
    ctx.print(f"{p}Manifest updated: {manifest_path}")
    if task_dir is not None:
        if dir_removed:
            ctx.print(f"{p}Removed task directory: {task_dir}")
        else:
            ctx.print(f"{p}Task directory not found: {task_dir}")


def _resolve_manifest_task_name(
    ctx: CommandContext,
    manifest: dict[str, dict],
    name_arg: str,
) -> str | None:
    p = ctx.line_prefix
    if name_arg in manifest:
        return name_arg

    matches: list[str] = []
    for task_name, entry in manifest.items():
        tool_name = str(entry.get("tool_name", task_name))
        proxy_name = f"{task_name}__{tool_name}"
        if name_arg in {tool_name, proxy_name}:
            matches.append(task_name)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ctx.print(f"{p}Ambiguous generated task name '{name_arg}'. Matches:")
        for task_name in sorted(matches):
            ctx.print(f"{p}  - {task_name}")
        return None

    ctx.print(f"{p}Generated task not found: {name_arg}")
    return None


def _resolve_manifest_task_dir(
    ctx: CommandContext,
    project_root: Path,
    task_name: str,
    entry: dict,
) -> Path | None:
    p = ctx.line_prefix
    server = entry.get("server", {})
    cwd = server.get("cwd") if isinstance(server, dict) else None
    if isinstance(cwd, str) and cwd.strip():
        candidate = (project_root / cwd).resolve()
    else:
        candidate = (project_root / "tools" / task_name).resolve()

    tools_root = (project_root / "tools").resolve()
    try:
        candidate.relative_to(tools_root)
    except ValueError:
        ctx.print(f"{p}Refusing to delete directory outside tools/: {candidate}")
        return None
    return candidate


def _resolve_tool_name(ctx: CommandContext, name_arg: str) -> Tool | None:
    p = ctx.line_prefix
    if name_arg in ctx.tool_map:
        return ctx.tool_map[name_arg]
    matches = [
        t for t in ctx.tool_map.values()
        if "__" in t.name and t.name.split("__", 1)[1] == name_arg
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ctx.print(f"{p}Ambiguous tool name '{name_arg}'. Matches:")
        for t in sorted(matches, key=lambda t: t.name):
            ctx.print(f"{p}  - {t.name}")
        return None
    ctx.print(f"{p}Tool not found: {name_arg}")
    return None


def _print_tool_list(ctx: CommandContext) -> None:
    p = ctx.line_prefix
    if not ctx.tool_map:
        ctx.print(f"{p}No tools loaded.")
        return
    groups: dict[str, list[str]] = {}
    for name in sorted(ctx.tool_map):
        if "__" in name:
            server, short = name.split("__", 1)
        else:
            server, short = "(built-in)", name
        groups.setdefault(server, []).append(short)
    for server in sorted(groups):
        ctx.print(f"{p}[{server}]")
        for short in sorted(groups[server]):
            ctx.print(f"{p}  - {short}")


def _print_tool_details(ctx: CommandContext, tool: Tool) -> None:
    p = ctx.line_prefix
    ctx.print(f"{p}Name: {tool.name}")
    ctx.print(f"{p}Description: {tool.description}")
    ctx.print(f"{p}Mutating: {tool.is_mutating}")


def _print_tool_schema(ctx: CommandContext, tool: Tool) -> None:
    p = ctx.line_prefix
    ctx.print(f"{p}Input schema:")
    ctx.print(json.dumps(tool.input_schema, indent=2))
    if hasattr(tool, "output_schema") and tool.output_schema is not None:
        ctx.print(f"{p}Output schema:")
        ctx.print(json.dumps(tool.output_schema, indent=2))


def _print_tool_config(ctx: CommandContext, tool: Tool) -> None:
    p = ctx.line_prefix
    fmt = ctx.tool_result_formatter.get_tool_format(tool.name)
    if fmt is not None:
        ctx.print(f"{p}ToolFormatting config for {tool.name}:")
        ctx.print(json.dumps(fmt, indent=2))
    else:
        ctx.print(f"{p}ToolFormatting config for {tool.name} (using default):")
        ctx.print(json.dumps(ctx.tool_result_formatter.default_format, indent=2))
