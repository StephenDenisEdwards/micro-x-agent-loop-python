"""Direct tests for ``cli.dispatch.dispatch`` — routing-only.

The dispatch function is a router: based on which `cli_args` key is set,
it delegates to one of several subsystems (job CLI, broker CLI, server,
oneshot, TUI, REPL). These tests verify the routing decisions without
actually starting any subsystem.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _empty_cli_args(**overrides) -> dict:
    base = {
        "job": None,
        "broker": None,
        "server": None,
        "run": None,
        "session": None,
        "tui": False,
        "config": None,
    }
    base.update(overrides)
    return base


class DispatchJobBranchTests(unittest.TestCase):
    def test_job_arg_routes_to_handle_job_command(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        mock_handler = AsyncMock()
        with patch(
            "micro_x_agent_loop.broker.cli.handle_job_command",
            mock_handler,
        ):
            asyncio.run(
                dispatch_module.dispatch(
                    _empty_cli_args(job=["list"]),
                    raw_config={},
                    config_source="config.json",
                )
            )
        mock_handler.assert_awaited_once()
        # First positional should be the job args
        args, _ = mock_handler.call_args
        self.assertEqual(["list"], args[0])


class DispatchBrokerBranchTests(unittest.TestCase):
    def test_broker_start_routes_to_run_server_with_broker_enabled(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        mock_run_server = AsyncMock()
        with patch("micro_x_agent_loop.server.app.run_server", mock_run_server):
            asyncio.run(
                dispatch_module.dispatch(
                    _empty_cli_args(broker=["start"], config="cfg.json"),
                    raw_config={},
                    config_source="cfg.json",
                )
            )
        mock_run_server.assert_awaited_once()
        kwargs = mock_run_server.call_args.kwargs
        self.assertTrue(kwargs.get("broker_enabled"))

    def test_broker_empty_args_also_routes_to_run_server(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        mock_run_server = AsyncMock()
        with patch("micro_x_agent_loop.server.app.run_server", mock_run_server):
            asyncio.run(
                dispatch_module.dispatch(
                    _empty_cli_args(broker=[]),
                    raw_config={},
                    config_source="cfg.json",
                )
            )
        mock_run_server.assert_awaited_once()

    def test_broker_other_subcommand_routes_to_handle_broker_command(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        mock_handler = AsyncMock()
        with patch(
            "micro_x_agent_loop.broker.cli.handle_broker_command",
            mock_handler,
        ):
            asyncio.run(
                dispatch_module.dispatch(
                    _empty_cli_args(broker=["status"]),
                    raw_config={},
                    config_source="cfg.json",
                )
            )
        mock_handler.assert_awaited_once()
        args, _ = mock_handler.call_args
        self.assertEqual(["status"], args[0])


class DispatchServerBranchTests(unittest.TestCase):
    def test_server_start_routes_to_run_server(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        mock_run_server = AsyncMock()
        with patch("micro_x_agent_loop.server.app.run_server", mock_run_server):
            asyncio.run(
                dispatch_module.dispatch(
                    _empty_cli_args(server=["start"]),
                    raw_config={},
                    config_source="cfg.json",
                )
            )
        mock_run_server.assert_awaited_once()

    def test_server_start_with_broker_flag_passes_through(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        mock_run_server = AsyncMock()
        with patch("micro_x_agent_loop.server.app.run_server", mock_run_server):
            asyncio.run(
                dispatch_module.dispatch(
                    _empty_cli_args(server=["start", "--broker"]),
                    raw_config={},
                    config_source="cfg.json",
                )
            )
        kwargs = mock_run_server.call_args.kwargs
        self.assertTrue(kwargs.get("broker_enabled"))

    def test_server_url_routes_to_run_client(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        mock_run_client = AsyncMock()
        with patch("micro_x_agent_loop.server.client.run_client", mock_run_client):
            asyncio.run(
                dispatch_module.dispatch(
                    _empty_cli_args(server=["http://example.com:8321"]),
                    raw_config={},
                    config_source="cfg.json",
                )
            )
        mock_run_client.assert_awaited_once()
        args, _ = mock_run_client.call_args
        self.assertEqual("http://example.com:8321", args[0])

    def test_server_unknown_command_prints_usage(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        mock_run_server = AsyncMock()
        mock_run_client = AsyncMock()
        with (
            patch("micro_x_agent_loop.server.app.run_server", mock_run_server),
            patch("micro_x_agent_loop.server.client.run_client", mock_run_client),
        ):
            # Capture print output
            with patch("builtins.print") as mock_print:
                asyncio.run(
                    dispatch_module.dispatch(
                        _empty_cli_args(server=["bogus"]),
                        raw_config={},
                        config_source="cfg.json",
                    )
                )
        mock_run_server.assert_not_awaited()
        mock_run_client.assert_not_awaited()
        # Some "Unknown server command" output landed
        printed = " ".join(call.args[0] for call in mock_print.call_args_list if call.args)
        self.assertIn("Unknown server command", printed)


class DispatchRunBranchTests(unittest.TestCase):
    def test_run_routes_to_run_oneshot(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        # parse_app_config + resolve_runtime_env must not blow up; minimal mocks.
        fake_app = MagicMock()
        fake_app.provider_name = "anthropic"
        fake_env = MagicMock()
        fake_env.provider_api_key = "fake-key"
        mock_oneshot = AsyncMock()

        # parse_app_config and resolve_runtime_env are imported at the top
        # of cli.dispatch, so patch them on that module.
        with (
            patch(
                "micro_x_agent_loop.cli.dispatch.parse_app_config",
                return_value=fake_app,
            ),
            patch(
                "micro_x_agent_loop.cli.dispatch.resolve_runtime_env",
                return_value=fake_env,
            ),
            patch(
                "micro_x_agent_loop.cli.dispatch.run_oneshot",
                mock_oneshot,
            ),
        ):
            asyncio.run(
                dispatch_module.dispatch(
                    _empty_cli_args(run="do the thing"),
                    raw_config={},
                    config_source="cfg.json",
                )
            )
        mock_oneshot.assert_awaited_once()
        kwargs = mock_oneshot.call_args.kwargs
        # 3rd positional should be the prompt
        args = mock_oneshot.call_args.args
        self.assertEqual("do the thing", args[2])
        self.assertIs(fake_app, args[0])
        self.assertIs(fake_env, args[1])
        self.assertIn("resolved_config", kwargs)

    def test_missing_api_key_exits(self) -> None:
        from micro_x_agent_loop.cli import dispatch as dispatch_module

        fake_app = MagicMock()
        fake_app.provider_name = "anthropic"
        fake_env = MagicMock()
        fake_env.provider_api_key = ""  # missing
        fake_env.provider_env_var = "ANTHROPIC_API_KEY"

        with (
            patch(
                "micro_x_agent_loop.cli.dispatch.parse_app_config",
                return_value=fake_app,
            ),
            patch(
                "micro_x_agent_loop.cli.dispatch.resolve_runtime_env",
                return_value=fake_env,
            ),
        ):
            with self.assertRaises(SystemExit):
                asyncio.run(
                    dispatch_module.dispatch(
                        _empty_cli_args(run="x"),
                        raw_config={},
                        config_source="cfg.json",
                    )
                )


if __name__ == "__main__":
    unittest.main()
