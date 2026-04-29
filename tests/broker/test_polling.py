"""Tests for PollingIngress."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.broker.channels import TriggerRequest
from micro_x_agent_loop.broker.dispatcher import RunDispatcher
from micro_x_agent_loop.broker.polling import PollingIngress
from micro_x_agent_loop.broker.response_router import ResponseRouter
from micro_x_agent_loop.broker.runner import RunResult
from micro_x_agent_loop.broker.store import BrokerStore


def _make_store(tmp_dir: str) -> BrokerStore:
    return BrokerStore(str(Path(tmp_dir) / "broker.db"))


def _make_router() -> ResponseRouter:
    adapter = MagicMock()
    adapter.send_response = AsyncMock(return_value=True)
    return ResponseRouter({"log": adapter})


class PollingIngressStopTests(unittest.TestCase):
    def test_stop_sets_event(self) -> None:
        adapter = MagicMock()
        dispatcher = MagicMock()
        store = MagicMock()
        ingress = PollingIngress(adapter, dispatcher, store, poll_interval=1)
        self.assertFalse(ingress._stop_event.is_set())
        ingress.stop()
        self.assertTrue(ingress._stop_event.is_set())


class PollingIngressStartTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def test_start_dispatches_messages(self) -> None:
        """Polling loop dispatches a trigger and then stops."""

        async def go() -> None:
            ok_result = RunResult(exit_code=0, stdout="done", stderr="")
            adapter = MagicMock()
            adapter.channel_name = "telegram"

            req = TriggerRequest(
                prompt="hello",
                sender_id="user1",
                channel="telegram",
                response_target="chat1",
            )
            call_count = 0

            async def fake_poll():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return [req]
                return []

            adapter.poll_messages = fake_poll

            router = _make_router()
            dispatcher = RunDispatcher(self._store, router)

            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                AsyncMock(return_value=ok_result),
            ):
                ingress = PollingIngress(adapter, dispatcher, self._store, poll_interval=0)

                # Run for a very short time then stop
                async def stop_soon():
                    await asyncio.sleep(0.05)
                    ingress.stop()

                await asyncio.gather(ingress.start(), stop_soon())

            # At least one run should have been created
            runs = self._store.list_runs()
            self.assertGreaterEqual(len(runs), 1)

        asyncio.run(go())

    def test_start_stops_on_max_errors(self) -> None:
        """Loop stops after reaching the consecutive error limit."""

        async def go() -> None:
            adapter = MagicMock()
            adapter.channel_name = "telegram"
            adapter.poll_messages = AsyncMock(side_effect=Exception("poll fail"))

            dispatcher = MagicMock()
            dispatcher.at_capacity = False

            ingress = PollingIngress(adapter, dispatcher, self._store, poll_interval=0)
            # The loop should break after 10 consecutive errors without us stopping it
            await asyncio.wait_for(ingress.start(), timeout=5.0)

        asyncio.run(go())

    def test_start_skips_dispatch_when_at_capacity(self) -> None:
        """Messages are dropped when the dispatcher is at capacity."""

        async def go() -> None:
            adapter = MagicMock()
            adapter.channel_name = "http"

            req = TriggerRequest(
                prompt="hi",
                sender_id="u",
                channel="http",
            )
            poll_calls = 0

            async def fake_poll():
                nonlocal poll_calls
                poll_calls += 1
                if poll_calls == 1:
                    return [req]
                return []

            adapter.poll_messages = fake_poll

            dispatcher = MagicMock()
            dispatcher.at_capacity = True  # Always at capacity

            ingress = PollingIngress(adapter, dispatcher, self._store, poll_interval=0)

            async def stop_soon():
                await asyncio.sleep(0.05)
                ingress.stop()

            await asyncio.gather(ingress.start(), stop_soon())

            # No runs should have been dispatched
            dispatcher.dispatch.assert_not_called()

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
