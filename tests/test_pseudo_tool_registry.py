"""Tests for PseudoToolRegistry — the name-keyed dispatch registry."""

from __future__ import annotations

import unittest
from typing import Any

from micro_x_agent_loop.pseudo_tool_handlers import PseudoToolRegistry


class _StaticHandler:
    """Minimal PseudoToolHandler for testing. Claims a fixed set of names."""

    def __init__(self, names: set[str]) -> None:
        self._names = frozenset(names)

    def claimed_names(self) -> frozenset[str]:
        return self._names

    async def execute_batch(self, blocks: list[dict]) -> list[dict]:
        return [{"type": "tool_result", "tool_use_id": b["id"], "content": "ok"} for b in blocks]


class PseudoToolRegistryTests(unittest.TestCase):
    def test_empty_registry_returns_none_for_any_name(self) -> None:
        registry = PseudoToolRegistry([])
        self.assertIsNone(registry.get("ask_user"))
        self.assertIsNone(registry.get("anything"))

    def test_single_handler_resolves_by_each_claimed_name(self) -> None:
        h = _StaticHandler({"foo", "bar"})
        registry = PseudoToolRegistry([h])
        self.assertIs(h, registry.get("foo"))
        self.assertIs(h, registry.get("bar"))
        self.assertIsNone(registry.get("other"))

    def test_two_handlers_with_disjoint_claims_coexist(self) -> None:
        h1 = _StaticHandler({"foo"})
        h2 = _StaticHandler({"bar"})
        registry = PseudoToolRegistry([h1, h2])
        self.assertIs(h1, registry.get("foo"))
        self.assertIs(h2, registry.get("bar"))

    def test_overlapping_claims_raise_on_construction(self) -> None:
        h1 = _StaticHandler({"foo"})
        h2 = _StaticHandler({"foo"})
        with self.assertRaises(ValueError) as cm:
            PseudoToolRegistry([h1, h2])
        msg = str(cm.exception)
        self.assertIn("foo", msg)
        self.assertIn("_StaticHandler", msg)

    def test_partial_overlap_raises(self) -> None:
        h1 = _StaticHandler({"foo", "shared"})
        h2 = _StaticHandler({"bar", "shared"})
        with self.assertRaises(ValueError) as cm:
            PseudoToolRegistry([h1, h2])
        self.assertIn("shared", str(cm.exception))

    def test_collision_message_names_both_handler_types(self) -> None:
        class Alpha:
            def claimed_names(self) -> frozenset[str]:
                return frozenset({"x"})

            async def execute_batch(self, blocks: list[dict]) -> list[dict]:
                return []

        class Beta:
            def claimed_names(self) -> frozenset[str]:
                return frozenset({"x"})

            async def execute_batch(self, blocks: list[dict]) -> list[dict]:
                return []

        with self.assertRaises(ValueError) as cm:
            PseudoToolRegistry([Alpha(), Beta()])  # type: ignore[list-item]
        msg = str(cm.exception)
        self.assertIn("Alpha", msg)
        self.assertIn("Beta", msg)


if __name__ == "__main__":
    unittest.main()
