"""Tests for the compact/extras surface in get_system_prompt — Phase 2 of
PLAN-gemma-model-support.  The `compact` parameter already existed; this
file verifies that:

  - the directives stripped by `compact=True` actually stay stripped
  - the directives present in `compact=False` stay present
  - `extras` lines appear in the final prompt after the core directives
  - defaults preserve every existing caller's output
"""

from __future__ import annotations

import unittest

from micro_x_agent_loop.system_prompt import get_system_prompt


class SystemPromptCompactBehaviourTests(unittest.TestCase):
    def test_compact_strips_fs_navigation_directive(self) -> None:
        full = get_system_prompt(compact=False)
        compact = get_system_prompt(compact=True)
        self.assertIn("Filesystem Navigation", full)
        self.assertNotIn("Filesystem Navigation", compact)

    def test_compact_strips_codegen_directive(self) -> None:
        full = get_system_prompt(compact=False)
        compact = get_system_prompt(compact=True)
        self.assertIn("Code Generation", full)
        self.assertNotIn("Code Generation", compact)

    def test_compact_strips_web_access_directive(self) -> None:
        full = get_system_prompt(compact=False)
        compact = get_system_prompt(compact=True)
        self.assertIn("Accessing web sites", full)
        self.assertNotIn("Accessing web sites", compact)

    def test_compact_strips_user_memory_guidance(self) -> None:
        full = get_system_prompt(compact=False, user_memory_enabled=True)
        compact = get_system_prompt(compact=True, user_memory_enabled=True)
        self.assertIn("User Memory Guidance", full)
        self.assertNotIn("User Memory Guidance", compact)

    def test_compact_strips_task_decomposition(self) -> None:
        full = get_system_prompt(compact=False, task_decomposition_enabled=True)
        compact = get_system_prompt(compact=True, task_decomposition_enabled=True)
        self.assertIn("Task Decomposition", full)
        self.assertNotIn("Task Decomposition", compact)

    def test_compact_default_is_false(self) -> None:
        """Calling without compact= preserves legacy callers (full prompt)."""
        default = get_system_prompt()
        explicit_full = get_system_prompt(compact=False)
        self.assertEqual(default, explicit_full)


class SystemPromptExtrasTests(unittest.TestCase):
    def test_no_extras_unchanged(self) -> None:
        base = get_system_prompt(compact=True)
        with_none = get_system_prompt(compact=True, extras=None)
        with_empty = get_system_prompt(compact=True, extras=[])
        self.assertEqual(base, with_none)
        self.assertEqual(base, with_empty)

    def test_extras_appended_after_core_directives(self) -> None:
        line = "Only call a tool when the user asks you to perform an action."
        prompt = get_system_prompt(compact=True, extras=[line])
        self.assertIn(line, prompt)
        self.assertTrue(
            prompt.rstrip().endswith(line),
            "extras should be appended at the end of the prompt",
        )

    def test_multiple_extras_each_appear(self) -> None:
        prompt = get_system_prompt(
            compact=True,
            extras=["First custom line.", "Second custom line."],
        )
        self.assertIn("First custom line.", prompt)
        self.assertIn("Second custom line.", prompt)

    def test_empty_strings_in_extras_skipped(self) -> None:
        prompt = get_system_prompt(compact=True, extras=["", "real line", ""])
        self.assertIn("real line", prompt)
        # No stray double-blank paragraphs from the empty strings.
        self.assertNotIn("\n\n\n\n", prompt)

    def test_extras_with_full_prompt_also_works(self) -> None:
        prompt = get_system_prompt(compact=False, extras=["x-extra"])
        self.assertIn("x-extra", prompt)
        # Core directives are still present alongside the extra.
        self.assertIn("Code Generation", prompt)


if __name__ == "__main__":
    unittest.main()
