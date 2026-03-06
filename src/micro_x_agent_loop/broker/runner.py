"""Subprocess runner for dispatching one-shot agent executions."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from loguru import logger


@dataclass
class RunResult:
    """Result of a one-shot agent run."""
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def summary(self) -> str:
        """Extract a brief summary from stdout (last non-empty lines)."""
        lines = [line for line in self.stdout.strip().splitlines() if line.strip()]
        # Return last 5 lines as summary
        return "\n".join(lines[-5:]) if lines else "(no output)"


async def run_agent(
    *,
    prompt: str,
    config: str | None = None,
    session_id: str | None = None,
    timeout_seconds: int | None = None,
) -> RunResult:
    """Spawn the agent as a subprocess in one-shot autonomous mode.

    Args:
        prompt: The prompt to execute.
        config: Optional config file path.
        session_id: Optional session ID to resume.
        timeout_seconds: Optional run timeout.

    Returns:
        RunResult with exit code, stdout, and stderr.
    """
    cmd = [sys.executable, "-m", "micro_x_agent_loop", "--run", prompt]
    if config:
        cmd.extend(["--config", config])
    if session_id:
        cmd.extend(["--session", session_id])

    logger.info(f"Dispatching agent run: prompt={prompt[:80]!r}")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
        return RunResult(
            exit_code=process.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )
    except TimeoutError:
        logger.warning(f"Agent run timed out after {timeout_seconds}s, killing process")
        process.kill()
        await process.wait()
        return RunResult(
            exit_code=-1,
            stdout="",
            stderr=f"Run timed out after {timeout_seconds} seconds",
        )
    except Exception as ex:
        logger.error(f"Failed to spawn agent subprocess: {ex}")
        return RunResult(
            exit_code=-1,
            stdout="",
            stderr=str(ex),
        )
