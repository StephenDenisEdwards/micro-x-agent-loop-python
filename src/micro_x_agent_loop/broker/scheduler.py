"""Cron scheduler that polls the job store and dispatches agent runs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from croniter import croniter
from loguru import logger

if TYPE_CHECKING:
    from micro_x_agent_loop.broker.dispatcher import RunDispatcher
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


_MAX_CONSECUTIVE_ERRORS = 10
_MAX_BACKOFF_SECONDS = 60


class Scheduler:
    """Polls the job store and dispatches due jobs via the shared RunDispatcher."""

    def __init__(
        self,
        store: BrokerStore,
        dispatcher: RunDispatcher,
        *,
        poll_interval: int = 5,
        recovery_policy: str = "skip",
    ) -> None:
        self._store = store
        self._dispatcher = dispatcher
        self._poll_interval = poll_interval
        self._recovery_policy = recovery_policy
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the scheduler loop until stop() is called."""
        logger.info(f"Scheduler started (poll={self._poll_interval}s)")

        self._initialise_schedules()

        consecutive_errors = 0

        while not self._stop_event.is_set():
            try:
                await self._poll_and_dispatch()
                consecutive_errors = 0
            except Exception as ex:
                consecutive_errors += 1
                logger.error(f"Scheduler poll error ({consecutive_errors}/{_MAX_CONSECUTIVE_ERRORS}): {ex}")
                if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    logger.critical(
                        f"Scheduler hit {_MAX_CONSECUTIVE_ERRORS} consecutive errors, shutting down"
                    )
                    self._stop_event.set()
                    break

            wait_seconds = min(
                self._poll_interval * (2 ** consecutive_errors) if consecutive_errors else self._poll_interval,
                _MAX_BACKOFF_SECONDS,
            )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
            except TimeoutError:
                pass

        logger.info("Scheduler stopped")

    def stop(self) -> None:
        """Signal the scheduler to stop after the current poll cycle."""
        self._stop_event.set()

    def _initialise_schedules(self) -> None:
        """Set next_run_at for enabled jobs that don't have one yet.

        Also applies missed-run recovery policy for jobs whose next_run_at is in the past.
        """
        jobs = self._store.list_jobs(enabled_only=True)
        now = datetime.now(UTC).isoformat()
        for job in jobs:
            cron_expr = job.get("cron_expr")
            if not cron_expr:
                continue
            tz_name = job.get("timezone") or "UTC"

            if not job.get("next_run_at"):
                next_run = compute_next_run(cron_expr, tz_name)
                self._store.update_job(job["id"], next_run_at=next_run)
                logger.info(f"Initialised schedule for job {job['name']!r}: next={next_run}")
            elif job["next_run_at"] < now:
                if self._recovery_policy == "run_once":
                    # Leave next_run_at in the past — the poll loop will pick it up and dispatch
                    logger.info(f"Recovery (run_once): missed job {job['name']!r} will run on next poll")
                else:
                    # Skip — advance to next future occurrence
                    next_run = compute_next_run(cron_expr, tz_name)
                    self._store.update_job(job["id"], next_run_at=next_run)
                    logger.info(f"Recovery (skip): advanced job {job['name']!r} to next={next_run}")

    async def _poll_and_dispatch(self) -> None:
        """Check for due jobs and dispatch them."""
        now = datetime.now(UTC).isoformat()
        jobs = self._store.list_jobs(enabled_only=True)

        for job in jobs:
            next_run = job.get("next_run_at")
            if not next_run or next_run > now:
                continue

            if self._dispatcher.at_capacity:
                logger.debug("Max concurrent runs reached, deferring remaining jobs")
                break

            # Overlap policy — atomic check-and-create for skip_if_running
            if job["overlap_policy"] == "skip_if_running":
                run_id = self._store.create_run_if_no_overlap(
                    job_id=job["id"],
                    trigger_source="cron",
                    prompt=job["prompt_template"],
                    session_id=job.get("session_id"),
                )
                if run_id is None:
                    logger.info(f"Skipping job {job['name']!r} — already running")
                    self._advance_schedule(job)
                    continue
            else:
                run_id = self._store.create_run(
                    job_id=job["id"],
                    trigger_source="cron",
                    prompt=job["prompt_template"],
                    session_id=job.get("session_id"),
                )

            self._store.update_job(job["id"], last_run_at=datetime.now(UTC).isoformat())
            self._advance_schedule(job)

            logger.info(f"Dispatching job {job['name']!r} (run_id={run_id[:8]})")

            self._dispatcher.dispatch(
                run_id=run_id,
                prompt=job["prompt_template"],
                job=job,
                config_profile=job.get("config_profile"),
                session_id=job.get("session_id"),
                timeout_seconds=job.get("timeout_seconds"),
                response_channel=job.get("response_channel", "log"),
                response_target=job.get("response_target"),
            )

        # Dispatch due retry runs
        retries = self._store.list_due_retries()
        for retry_run in retries:
            if self._dispatcher.at_capacity:
                break

            self._store.start_run(retry_run["id"])
            job = None
            if retry_run.get("job_id"):
                job = self._store.get_job(retry_run["job_id"])

            logger.info(
                f"Dispatching retry run {retry_run['id'][:8]} "
                f"(attempt {retry_run.get('attempt_number', '?')})"
            )

            self._dispatcher.dispatch(
                run_id=retry_run["id"],
                prompt=retry_run["prompt"],
                job=job,
                config_profile=job.get("config_profile") if job else None,
                session_id=retry_run.get("session_id"),
                timeout_seconds=job.get("timeout_seconds") if job else None,
                response_channel=job.get("response_channel", "log") if job else "log",
                response_target=job.get("response_target") if job else None,
            )

    def _advance_schedule(self, job: dict) -> None:
        """Compute and store the next run time for a job."""
        cron_expr = job.get("cron_expr")
        if not cron_expr:
            return
        tz_name = job.get("timezone") or "UTC"
        next_run = compute_next_run(cron_expr, tz_name)
        self._store.update_job(job["id"], next_run_at=next_run)
