"""Subprocess runner for dispatching one-shot agent executions."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from loguru import logger

_DEFAULT_TIMEOUT_SECONDS = 3600  # 1 hour
_MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MB


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


def _truncate_output(data: bytes, label: str) -> str:
    """Decode output bytes, truncating if over the size limit."""
    if len(data) > _MAX_OUTPUT_BYTES:
        logger.warning(f"Agent {label} truncated: {len(data):,} bytes > {_MAX_OUTPUT_BYTES:,} limit")
        data = data[:_MAX_OUTPUT_BYTES]
    return data.decode("utf-8", errors="replace")


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
        timeout_seconds: Optional run timeout (defaults to 1 hour).

    Returns:
        RunResult with exit code, stdout, and stderr.
    """
    effective_timeout = timeout_seconds if timeout_seconds is not None else _DEFAULT_TIMEOUT_SECONDS

    cmd = [sys.executable, "-m", "micro_x_agent_loop", "--run", prompt]
    if config:
        cmd.extend(["--config", config])
    if session_id:
        cmd.extend(["--session", session_id])

    logger.info(
        f"Dispatching agent run: prompt={prompt[:80]!r}, "
        f"config={config!r}, session={session_id!r}, timeout={effective_timeout}s"
    )

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=effective_timeout,
        )
        return RunResult(
            exit_code=process.returncode or 0,
            stdout=_truncate_output(stdout_bytes, "stdout"),
            stderr=_truncate_output(stderr_bytes, "stderr"),
        )
    except TimeoutError:
        logger.warning(f"Agent run timed out after {effective_timeout}s, killing process")
        process.kill()
        await process.wait()
        return RunResult(
            exit_code=-1,
            stdout="",
            stderr=f"Run timed out after {effective_timeout} seconds",
        )
    except Exception as ex:
        logger.error(f"Failed to spawn agent subprocess: {ex}")
        return RunResult(
            exit_code=-1,
            stdout="",
            stderr=str(ex),
        )
