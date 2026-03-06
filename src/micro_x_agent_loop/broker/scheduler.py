"""Cron scheduler that polls the job store and dispatches agent runs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from croniter import croniter
from loguru import logger

from micro_x_agent_loop.broker.runner import run_agent
from micro_x_agent_loop.broker.store import BrokerStore


def compute_next_run(cron_expr: str, tz_name: str = "UTC") -> str:
    """Compute the next run time as an ISO 8601 UTC string."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    cron = croniter(cron_expr, now_local)
    next_local = cron.get_next(datetime)
    return next_local.astimezone(UTC).isoformat()


class Scheduler:
    """Polls the job store and dispatches due jobs as agent subprocess runs."""

    def __init__(
        self,
        store: BrokerStore,
        *,
        poll_interval: int = 5,
        max_concurrent_runs: int = 2,
    ) -> None:
        self._store = store
        self._poll_interval = poll_interval
        self._max_concurrent_runs = max_concurrent_runs
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the scheduler loop until stop() is called."""
        logger.info(
            f"Scheduler started (poll={self._poll_interval}s, "
            f"max_concurrent={self._max_concurrent_runs})"
        )

        # Initialise next_run_at for any jobs that don't have one
        self._initialise_schedules()

        while not self._stop_event.is_set():
            try:
                await self._poll_and_dispatch()
            except Exception as ex:
                logger.error(f"Scheduler poll error: {ex}")

            # Clean up completed tasks
            done_keys = [k for k, t in self._running_tasks.items() if t.done()]
            for k in done_keys:
                del self._running_tasks[k]

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval,
                )
            except TimeoutError:
                pass

        # Wait for in-flight runs to finish
        if self._running_tasks:
            logger.info(f"Waiting for {len(self._running_tasks)} in-flight run(s)...")
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)

        logger.info("Scheduler stopped")

    def stop(self) -> None:
        """Signal the scheduler to stop after the current poll cycle."""
        self._stop_event.set()

    def _initialise_schedules(self) -> None:
        """Set next_run_at for enabled jobs that don't have one yet."""
        jobs = self._store.list_jobs(enabled_only=True)
        for job in jobs:
            if not job.get("next_run_at") and job.get("cron_expr"):
                next_run = compute_next_run(job["cron_expr"], job.get("timezone") or "UTC")
                self._store.update_job(job["id"], next_run_at=next_run)
                logger.info(f"Initialised schedule for job {job['name']!r}: next={next_run}")

    async def _poll_and_dispatch(self) -> None:
        """Check for due jobs and dispatch them."""
        now = datetime.now(UTC).isoformat()
        jobs = self._store.list_jobs(enabled_only=True)

        for job in jobs:
            next_run = job.get("next_run_at")
            if not next_run or next_run > now:
                continue

            # Check concurrency limit
            if len(self._running_tasks) >= self._max_concurrent_runs:
                logger.debug("Max concurrent runs reached, skipping dispatch")
                break

            # Check overlap policy
            if job["overlap_policy"] == "skip_if_running":
                if self._store.has_running_run(job["id"]):
                    logger.info(f"Skipping job {job['name']!r} — already running (overlap_policy=skip_if_running)")
                    # Still advance the schedule
                    self._advance_schedule(job)
                    continue

            # Dispatch the run
            self._dispatch_job(job)

    def _dispatch_job(self, job: dict) -> None:
        """Create a run record and spawn a subprocess task."""
        run_id = self._store.create_run(
            job_id=job["id"],
            trigger_source="cron",
            prompt=job["prompt_template"],
            session_id=job.get("session_id"),
        )
        self._store.update_job(job["id"], last_run_at=datetime.now(UTC).isoformat())
        self._advance_schedule(job)

        logger.info(f"Dispatching job {job['name']!r} (run_id={run_id[:8]})")

        task = asyncio.create_task(
            self._execute_run(run_id, job),
            name=f"broker-run-{run_id[:8]}",
        )
        self._running_tasks[run_id] = task

    async def _execute_run(self, run_id: str, job: dict) -> None:
        """Execute a single run and update its status."""
        try:
            result = await run_agent(
                prompt=job["prompt_template"],
                config=job.get("config_profile"),
                session_id=job.get("session_id"),
                timeout_seconds=job.get("timeout_seconds"),
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

    def _advance_schedule(self, job: dict) -> None:
        """Compute and store the next run time for a job."""
        cron_expr = job.get("cron_expr")
        if not cron_expr:
            return
        tz_name = job.get("timezone") or "UTC"
        next_run = compute_next_run(cron_expr, tz_name)
        self._store.update_job(job["id"], next_run_at=next_run)
