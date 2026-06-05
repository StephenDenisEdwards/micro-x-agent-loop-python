"""`/codegen-task-list [verbose]` — list generated codegen tasks from tools/manifest.json."""

from __future__ import annotations

import json
from pathlib import Path

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_codegen_task_list(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    parts = command.split()
    verbose = any(arg in ("verbose", "-v", "--verbose") for arg in parts[1:])

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

    if not isinstance(manifest, dict) or not manifest:
        ctx.print(f"{p}No tasks in manifest.")
        return

    rows: list[tuple[str, str, str, dict]] = []
    for task_name, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        created = str(entry.get("created", "—"))
        description = str(entry.get("description", "")).strip() or "(no description)"
        rows.append((task_name, created, description, entry))

    rows.sort(key=lambda row: (row[1], row[0]), reverse=True)

    ctx.print(f"{p}Codegen tasks ({len(rows)} in tools/manifest.json):")

    if not verbose:
        name_width = max(len(name) for name, _, _, _ in rows)
        date_width = max(len(created) for _, created, _, _ in rows)
        for name, created, description, _entry in rows:
            ctx.print(f"{p}  {name:<{name_width}}  {created:<{date_width}}  {description}")
        return

    for name, created, description, entry in rows:
        ctx.print(f"{p}")
        ctx.print(f"{p}{name}")
        ctx.print(f"{p}  Created:     {created}")
        ctx.print(f"{p}  Description: {description}")
        _print_codegen_task_params(ctx, entry)
        _print_codegen_task_profile(ctx, project_root, name, entry)


def _print_codegen_task_params(ctx: CommandContext, entry: dict) -> None:
    p = ctx.line_prefix
    schema = entry.get("input_schema")
    if not isinstance(schema, dict):
        ctx.print(f"{p}  Parameters:  (no input_schema)")
        return
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        ctx.print(f"{p}  Parameters:  (none)")
        return
    required = set(schema.get("required") or [])
    ctx.print(f"{p}  Parameters:")
    for param_name, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        param_type = str(spec.get("type", "any"))
        has_default = "default" in spec
        default_repr = json.dumps(spec.get("default")) if has_default else None
        required_tag = " (required)" if param_name in required else ""
        param_desc = str(spec.get("description", "")).strip()
        head = f"    - {param_name} ({param_type}){required_tag}"
        if default_repr is not None:
            head += f", default {default_repr}"
        ctx.print(f"{p}{head}")
        if param_desc:
            ctx.print(f"{p}        {param_desc}")


def _print_codegen_task_profile(
    ctx: CommandContext,
    project_root: Path,
    task_name: str,
    entry: dict,
) -> None:
    p = ctx.line_prefix
    server = entry.get("server", {})
    cwd = server.get("cwd") if isinstance(server, dict) else None
    if isinstance(cwd, str) and cwd.strip():
        task_dir = (project_root / cwd).resolve()
    else:
        task_dir = (project_root / "tools" / task_name).resolve()

    profile_path = task_dir / "profile.json"
    if not profile_path.exists():
        ctx.print(f"{p}  profile.json: (not found at {profile_path})")
        return
    try:
        profile_text = profile_path.read_text(encoding="utf-8").rstrip()
    except Exception as ex:
        ctx.print(f"{p}  profile.json: (failed to read: {ex})")
        return
    ctx.print(f"{p}  profile.json ({profile_path}):")
    for line in profile_text.splitlines():
        ctx.print(f"{p}    {line}")
