"""`/memory` — list, edit, and reset user-memory files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_memory(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    if not ctx.user_memory_enabled or not ctx.user_memory_dir:
        ctx.print(f"{p}User memory commands require UserMemoryEnabled=true")
        return

    parts = command.split()
    memory_dir = Path(ctx.user_memory_dir)

    if len(parts) == 1:
        memory_file = memory_dir / "MEMORY.md"
        if not memory_file.exists():
            ctx.print(f"{p}No memory file found ({memory_file})")
            return
        content = memory_file.read_text(encoding="utf-8")
        ctx.print(f"{p}Contents of MEMORY.md:\n{content}")
        return

    if len(parts) == 2 and parts[1] == "list":
        if not memory_dir.exists():
            ctx.print(f"{p}No memory files found")
            return
        files = sorted(q.name for q in memory_dir.iterdir() if q.suffix == ".md")
        if not files:
            ctx.print(f"{p}No memory files found")
            return
        ctx.print(f"{p}Memory files:")
        for name in files:
            ctx.print(f"{p}  - {name}")
        return

    if len(parts) == 2 and parts[1] == "edit":
        memory_file = memory_dir / "MEMORY.md"
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if not editor:
            ctx.print(f"{p}No $EDITOR set. Edit manually: {memory_file}")
            return
        memory_dir.mkdir(parents=True, exist_ok=True)
        if not memory_file.exists():
            memory_file.write_text("", encoding="utf-8")
        try:
            subprocess.run([editor, str(memory_file)], check=True)
            ctx.print(f"{p}Editor closed.")
        except Exception as ex:
            ctx.print(f"{p}Failed to open editor: {ex}")
        return

    if len(parts) >= 2 and parts[1] == "reset":
        if not memory_dir.exists():
            ctx.print(f"{p}No memory directory to reset")
            return
        if len(parts) == 2:
            files = [q.name for q in memory_dir.iterdir() if q.suffix == ".md"]
            if not files:
                ctx.print(f"{p}No memory files to reset")
                return
            ctx.print(
                f"{p}This will delete {len(files)} memory file(s). "
                "Run '/memory reset confirm' to proceed."
            )
            return
        if len(parts) == 3 and parts[2] == "confirm":
            deleted = 0
            for q in memory_dir.iterdir():
                if q.suffix == ".md":
                    q.unlink()
                    deleted += 1
            if deleted:
                ctx.print(f"{p}Deleted {deleted} memory file(s).")
            else:
                ctx.print(f"{p}No memory files to delete.")
            return

    ctx.print(f"{p}Usage: /memory | /memory list | /memory edit | /memory reset")
