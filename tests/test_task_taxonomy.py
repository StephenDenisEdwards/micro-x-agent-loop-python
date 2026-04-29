"""Tests for task_taxonomy module."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.task_taxonomy import (
    CHEAP_TASK_TYPES,
    MAIN_TASK_TYPES,
    TaskType,
)


class TaskTypeTests(unittest.TestCase):
    def test_all_types_defined(self) -> None:
        expected = {
            "trivial",
            "conversational",
            "factual_lookup",
            "summarization",
            "code_generation",
            "code_review",
            "analysis",
            "tool_continuation",
            "creative",
        }
        self.assertEqual({t.value for t in TaskType}, expected)

    def test_cheap_and_main_are_disjoint(self) -> None:
        self.assertEqual(len(CHEAP_TASK_TYPES & MAIN_TASK_TYPES), 0)

    def test_all_types_in_cheap_or_main(self) -> None:
        self.assertEqual(CHEAP_TASK_TYPES | MAIN_TASK_TYPES, set(TaskType))

    def test_string_enum_value(self) -> None:
        self.assertEqual(TaskType.TRIVIAL, "trivial")
        self.assertEqual(TaskType("code_generation"), TaskType.CODE_GENERATION)
