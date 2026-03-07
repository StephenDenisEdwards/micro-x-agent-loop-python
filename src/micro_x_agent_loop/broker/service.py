"""Broker service — daemon lifecycle management."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Any

from loguru import logger

from micro_x_agent_loop.broker.channels import build_adapters
from micro_x_agent_loop.broker.dispatcher import RunDispatcher
from micro_x_agent_loop.broker.polling import PollingIngress
from micro_x_agent_loop.broker.response_router import ResponseRouter
from micro_x_agent_loop.broker.scheduler import Scheduler
from micro_x_agent_loop.broker.store import BrokerStore

_DEFAULT_DB_PATH = ".micro_x/broker.db"
_DEFAULT_PID_PATH = ".micro_x/broker.pid"


class BrokerService:
    """Always-on broker that runs the scheduler, webhook server, and manages lifecycle."""

    def __init__(
        self,
        *,
        db_path: str = _DEFAULT_DB_PATH,
        pid_path: str = _DEFAULT_PID_PATH,
        poll_interval: int = 5,
        max_concurrent_runs: int = 2,
        webhook_enabled: bool = False,
        webhook_host: str = "127.0.0.1",
        webhook_port: int = 8321,
        channels_config: dict[str, Any] | None = None,
        recovery_policy: str = "skip",
        api_secret: str | None = None,
    ) -> None:
        self._db_path = db_path
        self._pid_path = pid_path
        self._poll_interval = poll_interval
        self._max_concurrent_runs = max_concurrent_runs
        self._webhook_enabled = webhook_enabled
        self._webhook_host = webhook_host
        self._webhook_port = webhook_port
        self._channels_config = channels_config or {}
        self._recovery_policy = recovery_policy
        self._api_secret = api_secret
        self._store: BrokerStore | None = None
        self._scheduler: Scheduler | None = None
        self._dispatcher: RunDispatcher | None = None
        self._polling_ingresses: list[PollingIngress] = []

    async def start(self) -> None:
        """Start the broker service in the foreground."""
        if not self._try_acquire_pid():
            raise RuntimeError("Broker is already running (PID file exists)")

        self._store = BrokerStore(self._db_path)

        # Build channel adapters and shared components
        adapters = build_adapters(self._channels_config)
        response_router = ResponseRouter(adapters)

        broker_url = f"http://{self._webhook_host}:{self._webhook_port}" if self._webhook_enabled else None
        self._dispatcher = RunDispatcher(
            self._store,
            response_router,
            max_concurrent_runs=self._max_concurrent_runs,
            broker_url=broker_url,
        )

        self._scheduler = Scheduler(
            self._store,
            self._dispatcher,
            poll_interval=self._poll_interval,
            recovery_policy=self._recovery_policy,
        )

        # Register signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    loop.add_signal_handler(sig, self._handle_shutdown)
                except NotImplementedError:
                    pass

        logger.info(f"Broker service starting (db={self._db_path}, pid={os.getpid()})")

        try:
            tasks: list[asyncio.Task] = []

            # Start the cron scheduler
            tasks.append(asyncio.create_task(self._scheduler.start(), name="scheduler"))

            # Start the webhook server if enabled
            if self._webhook_enabled:
                from micro_x_agent_loop.broker.webhook_server import WebhookServer

                webhook_server = WebhookServer(
                    self._store,
                    self._dispatcher,
                    adapters,
                    host=self._webhook_host,
                    port=self._webhook_port,
                    api_secret=self._api_secret,
                )
                tasks.append(asyncio.create_task(webhook_server.start(), name="webhook-server"))
                logger.info(f"Webhook server enabled on {self._webhook_host}:{self._webhook_port}")

            # Start polling ingress tasks for adapters that support polling
            for name, adapter in adapters.items():
                if adapter.supports_polling:
                    poll_interval = self._channels_config.get(name, {}).get("poll_interval", 10)
                    ingress = PollingIngress(
                        adapter,
                        self._dispatcher,
                        self._store,
                        poll_interval=poll_interval,
                    )
                    self._polling_ingresses.append(ingress)
                    tasks.append(asyncio.create_task(
                        ingress.start(), name=f"polling-{name}",
                    ))

            # Wait for the scheduler to finish (it runs until stop() is called)
            await tasks[0]

            # Cancel remaining tasks (webhook server)
            for task in tasks[1:]:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Wait for in-flight agent runs
            await self._dispatcher.wait_for_all()
        finally:
            self._cleanup()

    def _handle_shutdown(self) -> None:
        """Signal all components to stop gracefully."""
        if self._scheduler:
            self._scheduler.stop()
        for ingress in self._polling_ingresses:
            ingress.stop()

    def _try_acquire_pid(self) -> bool:
        """Atomically create PID file. Returns True if acquired, False if already running."""
        path = Path(self._pid_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            try:
                pid = int(path.read_text().strip())
                os.kill(pid, 0)
                return False
            except (ValueError, ProcessLookupError, OSError):
                logger.warning(f"Removing stale PID file (pid={path.read_text().strip()})")
                path.unlink(missing_ok=True)
            except PermissionError:
                return False

        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            return False

    def _remove_pid(self) -> None:
        path = Path(self._pid_path)
        path.unlink(missing_ok=True)

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
        """Send SIGTERM to the running broker. Returns True if stopped."""
        path = Path(pid_path)
        if not path.exists():
            return False
        try:
            pid = int(path.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            path.unlink(missing_ok=True)
            return True
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            path.unlink(missing_ok=True)
            return False
