"""Polling ingress loop for channel adapters that use polling mode."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from micro_x_agent_loop.broker.channels import ChannelAdapter
    from micro_x_agent_loop.broker.dispatcher import RunDispatcher
    from micro_x_agent_loop.broker.store import BrokerStore

_MAX_CONSECUTIVE_ERRORS = 10
_MAX_BACKOFF_SECONDS = 60


class PollingIngress:
    """Polls a channel adapter for new messages and dispatches matching triggers.

    Runs as a parallel asyncio task in BrokerService. Each polling adapter
    gets its own PollingIngress instance with its own interval and error backoff.
    """

    def __init__(
        self,
        adapter: ChannelAdapter,
        dispatcher: RunDispatcher,
        store: BrokerStore,
        *,
        poll_interval: int = 10,
    ) -> None:
        self._adapter = adapter
        self._dispatcher = dispatcher
        self._store = store
        self._poll_interval = poll_interval
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the polling loop until stop() is called."""
        channel = self._adapter.channel_name
        logger.info(f"Polling ingress started for {channel} (interval={self._poll_interval}s)")

        consecutive_errors = 0

        while not self._stop_event.is_set():
            try:
                messages = await self._adapter.poll_messages()
                consecutive_errors = 0

                for msg in messages:
                    if self._dispatcher.at_capacity:
                        logger.debug(f"At capacity, deferring {channel} messages")
                        break

                    run_id = self._store.create_run(
                        job_id=None,
                        trigger_source=channel,
                        prompt=msg.prompt,
                        session_id=msg.session_id,
                    )

                    self._dispatcher.dispatch(
                        run_id=run_id,
                        prompt=msg.prompt,
                        config_profile=msg.config_profile,
                        session_id=msg.session_id,
                        response_channel=channel,
                        response_target=msg.response_target or msg.sender_id,
                    )

                    logger.info(
                        f"Poll trigger from {channel}: run={run_id[:8]}, "
                        f"sender={msg.sender_id}, prompt={msg.prompt[:60]!r}"
                    )

            except Exception as ex:
                consecutive_errors += 1
                logger.error(f"Polling error for {channel} ({consecutive_errors}/{_MAX_CONSECUTIVE_ERRORS}): {ex}")
                if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    logger.critical(f"Polling for {channel} hit {_MAX_CONSECUTIVE_ERRORS} consecutive errors, stopping")
                    break

            wait_seconds = min(
                self._poll_interval * (2**consecutive_errors) if consecutive_errors else self._poll_interval,
                _MAX_BACKOFF_SECONDS,
            )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
            except TimeoutError:
                pass

        logger.info(f"Polling ingress stopped for {channel}")

    def stop(self) -> None:
        """Signal the polling loop to stop."""
        self._stop_event.set()
