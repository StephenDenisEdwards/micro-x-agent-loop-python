"""Broker service — daemon lifecycle management."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

from loguru import logger

from micro_x_agent_loop.broker.scheduler import Scheduler
from micro_x_agent_loop.broker.store import BrokerStore

_DEFAULT_DB_PATH = ".micro_x/broker.db"
_DEFAULT_PID_PATH = ".micro_x/broker.pid"


class BrokerService:
    """Always-on broker that runs the scheduler and manages its lifecycle."""

    def __init__(
        self,
        *,
        db_path: str = _DEFAULT_DB_PATH,
        pid_path: str = _DEFAULT_PID_PATH,
        poll_interval: int = 5,
        max_concurrent_runs: int = 2,
    ) -> None:
        self._db_path = db_path
        self._pid_path = pid_path
        self._poll_interval = poll_interval
        self._max_concurrent_runs = max_concurrent_runs
        self._store: BrokerStore | None = None
        self._scheduler: Scheduler | None = None

    async def start(self) -> None:
        """Start the broker service in the foreground."""
        if self._is_already_running():
            logger.error("Broker is already running (PID file exists)")
            sys.exit(1)

        self._write_pid()

        self._store = BrokerStore(self._db_path)
        self._scheduler = Scheduler(
            self._store,
            poll_interval=self._poll_interval,
            max_concurrent_runs=self._max_concurrent_runs,
        )

        # Register signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    loop.add_signal_handler(sig, self._scheduler.stop)
                except NotImplementedError:
                    # Windows doesn't support add_signal_handler for all signals
                    pass

        logger.info(f"Broker service starting (db={self._db_path}, pid={os.getpid()})")

        try:
            await self._scheduler.start()
        finally:
            self._cleanup()

    def _write_pid(self) -> None:
        path = Path(self._pid_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()))

    def _remove_pid(self) -> None:
        path = Path(self._pid_path)
        if path.exists():
            path.unlink()

    def _is_already_running(self) -> bool:
        path = Path(self._pid_path)
        if not path.exists():
            return False
        try:
            pid = int(path.read_text().strip())
            # Check if the process is actually alive
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            # Stale PID file — previous broker crashed
            path.unlink(missing_ok=True)
            return False

    def _cleanup(self) -> None:
        self._remove_pid()
        if self._store:
            self._store.close()
        logger.info("Broker service stopped")

    @staticmethod
    def read_pid(pid_path: str = _DEFAULT_PID_PATH) -> int | None:
        """Read the broker PID from the PID file, or None if not running."""
        path = Path(pid_path)
        if not path.exists():
            return None
        try:
            pid = int(path.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            return None

    @staticmethod
    def stop_broker(pid_path: str = _DEFAULT_PID_PATH) -> bool:
        """Send SIGTERM/TerminateProcess to the running broker. Returns True if stopped."""
        path = Path(pid_path)
        if not path.exists():
            return False
        try:
            pid = int(path.read_text().strip())
            if sys.platform == "win32":
                os.kill(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
            # Remove PID file after sending signal
            path.unlink(missing_ok=True)
            return True
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            path.unlink(missing_ok=True)
            return False
