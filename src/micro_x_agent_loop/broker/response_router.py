"""Routes completed run results to the appropriate channel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from micro_x_agent_loop.broker.channels import ChannelAdapter
    from micro_x_agent_loop.broker.runner import RunResult
    from micro_x_agent_loop.broker.store import BrokerStore


class ResponseRouter:
    """Routes run results to the originating or configured channel."""

    def __init__(self, adapters: dict[str, ChannelAdapter]) -> None:
        self._adapters = adapters

    async def route(
        self,
        run_id: str,
        channel: str,
        target: str | None,
        result: RunResult,
        store: BrokerStore,
    ) -> bool:
        """Route a run result. Updates the run record with delivery status.

        Falls back to 'log' channel if the configured channel fails or is unknown.
        """
        if channel == "none":
            return True

        adapter = self._adapters.get(channel)
        if adapter is None:
            logger.warning(f"Unknown response channel {channel!r} for run {run_id[:8]}, falling back to log")
            adapter = self._adapters.get("log")
            if adapter is None:
                return False

        try:
            sent = await adapter.send_response(target or "", result)
        except Exception as ex:
            logger.error(f"Response routing failed for run {run_id[:8]} on channel {channel!r}: {ex}")
            sent = False

        if sent:
            store.mark_response_sent(run_id)
            logger.info(f"Response sent for run {run_id[:8]} via {channel}")
        else:
            error_msg = f"Failed to send response via {channel}"
            store.mark_response_failed(run_id, error=error_msg)
            logger.warning(f"Response failed for run {run_id[:8]} via {channel}, falling back to log")
            # Fallback to log
            if channel != "log":
                log_adapter = self._adapters.get("log")
                if log_adapter:
                    await log_adapter.send_response("", result)

        return sent
