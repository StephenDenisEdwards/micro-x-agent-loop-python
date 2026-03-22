"""Tests for AgentManager."""

from __future__ import annotations

import asyncio
import unittest

from micro_x_agent_loop.agent_channel import BufferedChannel
from micro_x_agent_loop.app_config import parse_app_config
from micro_x_agent_loop.server.agent_manager import AgentManager


def _make_config() -> dict:
    return {
        "Provider": "anthropic",
        "Model": "test-model",
        "MemoryEnabled": False,
    }


def _make_manager(max_sessions: int = 5, timeout_minutes: int = 30) -> AgentManager:
    app_config = parse_app_config(_make_config())
    return AgentManager(
        app_config=app_config,
        api_key="test-key",
        tools=[],
        max_sessions=max_sessions,
        session_timeout_minutes=timeout_minutes,
    )


class TestAgentManagerBasic(unittest.TestCase):
    def test_get_or_create_creates_agent(self) -> None:
        mgr = _make_manager()
        channel = BufferedChannel()

        async def go():
            agent = await mgr.get_or_create("s1", channel=channel)
            self.assertIsNotNone(agent)
            self.assertEqual(1, mgr.active_count)

        asyncio.run(go())

    def test_get_or_create_returns_same_agent(self) -> None:
        mgr = _make_manager()

        async def go():
            a1 = await mgr.get_or_create("s1")
            a2 = await mgr.get_or_create("s1")
            self.assertIs(a1, a2)
            self.assertEqual(1, mgr.active_count)

        asyncio.run(go())

    def test_destroy_removes_agent(self) -> None:
        mgr = _make_manager()

        async def go():
            await mgr.get_or_create("s1")
            self.assertEqual(1, mgr.active_count)
            result = await mgr.destroy("s1")
            self.assertTrue(result)
            self.assertEqual(0, mgr.active_count)

        asyncio.run(go())

    def test_destroy_nonexistent_returns_false(self) -> None:
        mgr = _make_manager()

        async def go():
            result = await mgr.destroy("no-such-session")
            self.assertFalse(result)

        asyncio.run(go())

    def test_list_sessions(self) -> None:
        mgr = _make_manager()

        async def go():
            await mgr.get_or_create("s1")
            await mgr.get_or_create("s2")
            sessions = mgr.list_sessions()
            self.assertEqual(2, len(sessions))
            ids = {s["session_id"] for s in sessions}
            self.assertEqual({"s1", "s2"}, ids)

        asyncio.run(go())

    def test_capacity_eviction(self) -> None:
        mgr = _make_manager(max_sessions=2)

        async def go():
            await mgr.get_or_create("s1")
            await mgr.get_or_create("s2")
            # s3 should evict the oldest (s1)
            await mgr.get_or_create("s3")
            self.assertEqual(2, mgr.active_count)
            ids = {s["session_id"] for s in mgr.list_sessions()}
            self.assertNotIn("s1", ids)
            self.assertIn("s2", ids)
            self.assertIn("s3", ids)

        asyncio.run(go())

    def test_shutdown_all(self) -> None:
        mgr = _make_manager()

        async def go():
            await mgr.get_or_create("s1")
            await mgr.get_or_create("s2")
            await mgr.shutdown_all()
            self.assertEqual(0, mgr.active_count)

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
