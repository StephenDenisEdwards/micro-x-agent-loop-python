"""Shared run dispatcher for cron scheduler and webhook triggers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from micro_x_agent_loop.broker.runner import run_agent

if TYPE_CHECKING:
    from micro_x_agent_loop.broker.response_router import ResponseRouter
    from micro_x_agent_loop.broker.store import BrokerStore


class RunDispatcher:
    """Dispatches agent runs and routes responses on completion.

    Used by both the cron scheduler and the webhook server to avoid
    duplicating dispatch + response routing logic.
    """

    def __init__(
        self,
        store: BrokerStore,
        response_router: ResponseRouter,
        *,
        max_concurrent_runs: int = 2,
    ) -> None:
        self._store = store
        self._response_router = response_router
        self._max_concurrent_runs = max_concurrent_runs
        self._running_tasks: dict[str, asyncio.Task] = {}

    @property
    def active_run_count(self) -> int:
        self._cleanup_done_tasks()
        return len(self._running_tasks)

    @property
    def at_capacity(self) -> bool:
        return self.active_run_count >= self._max_concurrent_runs

    def _cleanup_done_tasks(self) -> None:
        done_keys = [k for k, t in self._running_tasks.items() if t.done()]
        for k in done_keys:
            del self._running_tasks[k]

    def dispatch(
        self,
        *,
        run_id: str,
        prompt: str,
        job: dict | None = None,
        config_profile: str | None = None,
        session_id: str | None = None,
        timeout_seconds: int | None = None,
        response_channel: str = "log",
        response_target: str | None = None,
    ) -> asyncio.Task:
        """Spawn an agent subprocess task for an already-created run record.

        The run record must already exist in the store (created by caller).
        Returns the asyncio task.
        """
        # Store response routing info on the run
        self._store.set_run_response_info(
            run_id,
            response_channel=response_channel,
            response_target=response_target,
        )

        task = asyncio.create_task(
            self._execute_run(
                run_id=run_id,
                prompt=prompt,
                config_profile=config_profile,
                session_id=session_id,
                timeout_seconds=timeout_seconds,
                response_channel=response_channel,
                response_target=response_target,
            ),
            name=f"broker-run-{run_id[:8]}",
        )
        self._running_tasks[run_id] = task
        return task

    async def _execute_run(
        self,
        *,
        run_id: str,
        prompt: str,
        config_profile: str | None,
        session_id: str | None,
        timeout_seconds: int | None,
        response_channel: str,
        response_target: str | None,
    ) -> None:
        """Execute a single run, update status, and route response."""
        try:
            result = await run_agent(
                prompt=prompt,
                config=config_profile,
                session_id=session_id,
                timeout_seconds=timeout_seconds,
            )
            if result.ok:
                self._store.complete_run(run_id, result_summary=result.summary)
                logger.info(f"Run {run_id[:8]} completed successfully")
            else:
                error = result.stderr or f"Exit code {result.exit_code}"
                self._store.fail_run(run_id, error_text=error)
                logger.warning(f"Run {run_id[:8]} failed: {error[:200]}")
        except Exception as ex:
            self._store.fail_run(run_id, error_text=str(ex))
            logger.error(f"Run {run_id[:8]} exception: {ex}")
            from micro_x_agent_loop.broker.runner import RunResult

            result = RunResult(exit_code=-1, stdout="", stderr=str(ex))

        # Route response
        await self._response_router.route(
            run_id=run_id,
            channel=response_channel,
            target=response_target,
            result=result,
            store=self._store,
        )

    async def wait_for_all(self) -> None:
        """Wait for all in-flight runs to complete. Called during shutdown."""
        self._cleanup_done_tasks()
        if not self._running_tasks:
            return
        logger.info(f"Waiting for {len(self._running_tasks)} in-flight run(s)...")
        results = await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)
        for run_id, result in zip(self._running_tasks, results, strict=False):
            if isinstance(result, Exception):
                logger.error(f"In-flight run {run_id[:8]} failed during shutdown: {result}")
        self._running_tasks.clear()
