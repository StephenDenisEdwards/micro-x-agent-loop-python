"""Tests for the WebSocket CLI client."""

from __future__ import annotations

import asyncio
import unittest

from micro_x_agent_loop.server.client import run_client


class TestClientConnectionErrors(unittest.TestCase):
    def test_connect_to_nonexistent_server(self) -> None:
        """Client should print an error and return when server is unreachable."""

        async def go() -> None:
            # Use a port that's almost certainly not running a server
            await run_client("http://127.0.0.1:19999")

        # Should not raise — just prints error and returns
        asyncio.run(go())

    def test_client_with_https_url(self) -> None:
        """Client should attempt wss:// for https:// URLs."""

        async def go() -> None:
            await run_client("https://127.0.0.1:19999")

        asyncio.run(go())


class TestClientArgParsing(unittest.TestCase):
    def test_parse_server_url(self) -> None:
        """Verify --server http://... is parsed as server args."""
        import sys
        original = sys.argv
        try:
            sys.argv = ["prog", "--server", "http://localhost:8321"]
            from micro_x_agent_loop.__main__ import _parse_cli_args
            args = _parse_cli_args()
            self.assertEqual(["http://localhost:8321"], args["server"])
        finally:
            sys.argv = original

    def test_parse_server_url_with_session(self) -> None:
        """Verify --session is parsed alongside --server."""
        import sys
        original = sys.argv
        try:
            sys.argv = ["prog", "--session", "my-session", "--server", "http://localhost:8321"]
            from micro_x_agent_loop.__main__ import _parse_cli_args
            args = _parse_cli_args()
            self.assertEqual(["http://localhost:8321"], args["server"])
            self.assertEqual("my-session", args["session"])
        finally:
            sys.argv = original


if __name__ == "__main__":
    unittest.main()
