import asyncio
import platform
from typing import Any


class BashTool:
    def __init__(self, working_directory: str | None = None):
        self._cwd = working_directory

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute a bash command and return its output (stdout + stderr)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
            },
            "required": ["command"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        command = tool_input["command"]

        try:
            if platform.system() == "Windows":
                proc = await asyncio.create_subprocess_shell(
                    f"cmd.exe /c {command}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._cwd,
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._cwd,
                )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return f"[timed out after 30s]"

            output = stdout.decode(errors="replace") + stderr.decode(errors="replace")

            if proc.returncode != 0:
                return f"{output}\n[exit code {proc.returncode}]"

            return output.rstrip()

        except Exception as ex:
            return f"Error executing command: {ex}"
