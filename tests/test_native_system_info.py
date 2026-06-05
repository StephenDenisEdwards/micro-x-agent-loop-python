"""Native system-info tools — ported from the .NET system-info MCP server.

Fast, deterministic, no network/LLM. Pins Tool-protocol conformance,
the fully-qualified names (must match the old MCP names so references
don't break), and that each tool returns non-error text.
"""

from __future__ import annotations

import unittest

from micro_x_agent_loop.native_tools import build_native_tools
from micro_x_agent_loop.native_tools.system_info import build_system_info_tools
from micro_x_agent_loop.tool import Tool


class NativeSystemInfoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tools = build_system_info_tools()

    def test_names_match_legacy_mcp_names(self) -> None:
        names = sorted(t.name for t in self.tools)
        self.assertEqual(
            names,
            ["system-info__disk_info", "system-info__network_info", "system-info__system_info"],
        )

    def test_protocol_conformance(self) -> None:
        for t in self.tools:
            self.assertIsInstance(t, Tool)
            self.assertFalse(t.is_mutating)
            self.assertEqual(t.input_schema.get("type"), "object")
            self.assertEqual(t.input_schema.get("properties"), {})
            self.assertEqual(t.predict_touched_paths({}), [])
            self.assertTrue(t.description)

    async def test_execute_returns_text(self) -> None:
        expected_head = {
            "system-info__system_info": "System Information",
            "system-info__disk_info": "Disk Information",
            "system-info__network_info": "Network Interfaces",
        }
        for t in self.tools:
            result = await t.execute({})
            self.assertFalse(result.is_error, f"{t.name} errored: {result.text}")
            self.assertTrue(result.text.startswith(expected_head[t.name]))

    def test_registry_includes_system_info(self) -> None:
        registered = {t.name for t in build_native_tools()}
        self.assertIn("system-info__system_info", registered)


if __name__ == "__main__":
    unittest.main()
