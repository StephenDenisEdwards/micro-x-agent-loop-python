from __future__ import annotations

import os
import tempfile
import unittest

from micro_x_agent_loop.tasks.manager import TaskManager
from micro_x_agent_loop.tasks.models import TaskStatus
from micro_x_agent_loop.tasks.store import TaskStore


class TestTaskManager(unittest.IsolatedAsyncioTestCase):
    """Tests for TaskManager tool-call handling and result formatting.

    Covers guide Sections 5.1-5.4 (result formatting) and Section 7
    (error handling — non-error responses for "not found").
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self._tmpdir, "tasks.db")
        self.store = TaskStore(db_path)
        self.list_id = "test-session"
        self.mgr = TaskManager(self.store, self.list_id)

    def tearDown(self) -> None:
        self.store.close()

    # ------------------------------------------------------------------
    # 5.1  task_create
    # ------------------------------------------------------------------

    async def test_create_basic(self) -> None:
        result = await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Fix auth bug",
                    "description": "Fix the JWT validation in login flow",
                },
            )
        self.assertEqual(result, "Task #1 created successfully: Fix auth bug")

    async def test_create_with_active_form(self) -> None:
        result = await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Run tests",
                    "description": "Execute full test suite",
                    "activeForm": "Running tests",
                },
            )
        self.assertIn("Task #1 created successfully", result)
        task = self.store.get_task(self.list_id, "1")
        assert task is not None
        self.assertEqual(task.active_form, "Running tests")

    async def test_create_with_metadata(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                    "metadata": {"priority": "high"},
                },
            )
        task = self.store.get_task(self.list_id, "1")
        assert task is not None
        assert task.metadata is not None
        self.assertEqual(task.metadata["priority"], "high")

    async def test_create_missing_fields(self) -> None:
        result = await self.mgr.handle_tool_call("task_create", {})
        self.assertIn("Error", result)

    # ------------------------------------------------------------------
    # 5.2  task_update
    # ------------------------------------------------------------------

    async def test_update_status(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "in_progress",
                },
            )
        self.assertEqual(result, "Updated task #1 status")

    async def test_update_multiple_fields(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "in_progress",
                    "owner": "alice",
                },
            )
        self.assertIn("status", result)
        self.assertIn("owner", result)

    async def test_update_delete(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "deleted",
                },
            )
        self.assertEqual(result, "Updated task #1 deleted")
        # Verify it's gone
        self.assertIsNone(self.store.get_task(self.list_id, "1"))

    async def test_update_add_blocks(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "A",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "B",
                    "description": "desc",
                },
            )
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "addBlocks": ["2"],
                },
            )
        self.assertIn("blocks", result)

        # Verify dependency
        t1 = self.store.get_task(self.list_id, "1")
        t2 = self.store.get_task(self.list_id, "2")
        assert t1 is not None and t2 is not None
        self.assertIn("2", t1.blocks)
        self.assertIn("1", t2.blocked_by)

    async def test_update_add_blocked_by(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "A",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "B",
                    "description": "desc",
                },
            )
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "2",
                    "addBlockedBy": ["1"],
                },
            )
        self.assertIn("blockedBy", result)

    async def test_update_no_fields(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                },
            )
        self.assertIn("unchanged", result)

    # ------------------------------------------------------------------
    # 7.1  Task not found — non-error responses (Section 13.3)
    # ------------------------------------------------------------------

    async def test_update_not_found(self) -> None:
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "999",
                    "status": "completed",
                },
            )
        self.assertEqual(result, "Task #999 not found")
        # Must NOT raise or return is_error — it's just text

    async def test_delete_not_found(self) -> None:
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "999",
                    "status": "deleted",
                },
            )
        self.assertEqual(result, "Task #999 not found")

    async def test_get_not_found(self) -> None:
        result = await self.mgr.handle_tool_call(
                "task_get",
                {
                    "taskId": "999",
                },
            )
        self.assertEqual(result, "Task not found")

    # ------------------------------------------------------------------
    # 5.3  task_list
    # ------------------------------------------------------------------

    async def test_list_empty(self) -> None:
        result = await self.mgr.handle_tool_call("task_list", {})
        self.assertEqual(result, "No tasks.")

    async def test_list_formatting(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Set up schema",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "completed",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Implement auth",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "2",
                    "status": "in_progress",
                    "owner": "alice",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Write tests",
                    "description": "desc",
                },
            )
        # Block task 3 by task 2
        self.store.block_task(self.list_id, "2", "3")

        result = await self.mgr.handle_tool_call("task_list", {})
        lines = result.split("\n")
        self.assertEqual(len(lines), 3)
        self.assertIn("#1 [completed] Set up schema", lines[0])
        self.assertIn("#2 [in_progress] Implement auth (alice)", lines[1])
        self.assertIn("#3 [pending] Write tests [blocked by #2]", lines[2])

    async def test_list_filters_completed_blockers(self) -> None:
        """Section 6.3 / 13.2: completed blockers are filtered from display."""
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "A",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "B",
                    "description": "desc",
                },
            )
        self.store.block_task(self.list_id, "1", "2")

        # Before completing A, B shows as blocked
        result = await self.mgr.handle_tool_call("task_list", {})
        self.assertIn("[blocked by #1]", result)

        # After completing A, B no longer shows as blocked
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "completed",
                },
            )
        result = await self.mgr.handle_tool_call("task_list", {})
        self.assertNotIn("[blocked by", result)

    async def test_list_filters_internal_tasks(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Visible",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Internal",
                    "description": "desc",
                    "metadata": {"_internal": True},
                },
            )
        result = await self.mgr.handle_tool_call("task_list", {})
        self.assertIn("Visible", result)
        self.assertNotIn("Internal", result)

    # ------------------------------------------------------------------
    # 5.4  task_get
    # ------------------------------------------------------------------

    async def test_get_full_details(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Implement auth",
                    "description": "Add JWT-based auth with login/logout endpoints",
                },
            )
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "in_progress",
                },
            )

        result = await self.mgr.handle_tool_call("task_get", {"taskId": "1"})
        self.assertIn("Task #1: Implement auth", result)
        self.assertIn("Status: in_progress", result)
        self.assertIn("Description: Add JWT-based auth", result)

    async def test_get_with_dependencies(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "A",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "B",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "C",
                    "description": "desc",
                },
            )
        self.store.block_task(self.list_id, "1", "2")
        self.store.block_task(self.list_id, "1", "3")

        result = await self.mgr.handle_tool_call("task_get", {"taskId": "1"})
        self.assertIn("Blocks: #2, #3", result)

    async def test_get_with_owner(self) -> None:
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "owner": "alice",
                },
            )
        result = await self.mgr.handle_tool_call("task_get", {"taskId": "1"})
        self.assertIn("Owner: alice", result)

    # ------------------------------------------------------------------
    # Unknown tool
    # ------------------------------------------------------------------

    async def test_unknown_tool(self) -> None:
        result = await self.mgr.handle_tool_call("task_unknown", {})
        self.assertIn("Unknown task tool", result)

    # ------------------------------------------------------------------
    # 13.4  Delete with cascade (via manager)
    # ------------------------------------------------------------------

    async def test_delete_cascades_via_manager(self) -> None:
        """Section 13.4: delete via task_update cascades dependency cleanup."""
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "A",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "B",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "2",
                    "addBlockedBy": ["1"],
                },
            )

        # Delete A
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "deleted",
                },
            )

        # B should have no blockers
        t2 = self.store.get_task(self.list_id, "2")
        assert t2 is not None
        self.assertEqual(t2.blocked_by, [])

    # ------------------------------------------------------------------
    # 13.5  ID non-reuse via manager
    # ------------------------------------------------------------------

    async def test_id_non_reuse_via_manager(self) -> None:
        """Section 13.5: after delete, next ID skips the deleted one."""
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "A",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "B",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "2",
                    "status": "deleted",
                },
            )
        result = await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "C",
                    "description": "desc",
                },
            )
        self.assertEqual(result, "Task #3 created successfully: C")


class TestTaskManagerHooks(unittest.IsolatedAsyncioTestCase):
    """Tests for lifecycle hooks (guide Section 8)."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self._tmpdir, "tasks.db")
        self.store = TaskStore(db_path)
        self.list_id = "test-session"
        self.mgr = TaskManager(self.store, self.list_id)

    def tearDown(self) -> None:
        self.store.close()

    # ------------------------------------------------------------------
    # Created hooks
    # ------------------------------------------------------------------

    async def test_created_hook_non_blocking(self) -> None:
        """Non-blocking hook: task creation succeeds."""
        received_args: list[tuple[str, str, str]] = []

        async def hook(task_id: str, subject: str, description: str) -> str | None:
            received_args.append((task_id, subject, description))
            return None

        self.mgr.register_created_hook(hook)
        result = await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Fix bug",
                    "description": "Fix the auth bug",
                },
            )
        self.assertIn("created successfully", result)
        # Hook received correct args
        self.assertEqual(len(received_args), 1)
        self.assertEqual(received_args[0], ("1", "Fix bug", "Fix the auth bug"))
        # Task exists
        self.assertIsNotNone(self.store.get_task(self.list_id, "1"))

    async def test_created_hook_blocking_rolls_back(self) -> None:
        """Blocking hook: task is deleted (rolled back), error returned."""

        async def blocking_hook(task_id: str, subject: str, description: str) -> str | None:
            return "Policy violation: too many tasks"

        self.mgr.register_created_hook(blocking_hook)
        result = await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        self.assertIn("Task creation blocked", result)
        self.assertIn("Policy violation", result)
        # Task was rolled back — should not exist
        self.assertIsNone(self.store.get_task(self.list_id, "1"))

    async def test_created_hooks_multiple_first_error_wins(self) -> None:
        """Multiple hooks: first blocking error wins, later hooks don't run."""
        call_order: list[str] = []

        async def hook_a(task_id: str, subject: str, description: str) -> str | None:
            call_order.append("a")
            return "Error from A"

        async def hook_b(task_id: str, subject: str, description: str) -> str | None:
            call_order.append("b")
            return None

        self.mgr.register_created_hook(hook_a)
        self.mgr.register_created_hook(hook_b)
        result = await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        self.assertIn("Error from A", result)
        # Hook B was never called because A blocked first
        self.assertEqual(call_order, ["a"])

    async def test_created_hook_id_reuse_after_rollback(self) -> None:
        """After rollback, the ID is consumed (HWM prevents reuse)."""

        async def blocking_hook(task_id: str, subject: str, description: str) -> str | None:
            return "blocked"

        self.mgr.register_created_hook(blocking_hook)
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "A",
                    "description": "desc",
                },
            )
        # ID 1 was consumed and rolled back

        # Remove the hook so the next create succeeds
        self.mgr._created_hooks.clear()
        result = await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "B",
                    "description": "desc",
                },
            )
        # Should get ID 2, not 1 (HWM prevents reuse)
        self.assertEqual(result, "Task #2 created successfully: B")

    # ------------------------------------------------------------------
    # Completed hooks
    # ------------------------------------------------------------------

    async def test_completed_hook_non_blocking(self) -> None:
        """Non-blocking hook: completion succeeds."""
        received_args: list[tuple[str, str, str]] = []

        async def hook(task_id: str, subject: str, description: str) -> str | None:
            received_args.append((task_id, subject, description))
            return None

        self.mgr.register_completed_hook(hook)
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Fix bug",
                    "description": "Fix the auth bug",
                },
            )
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "completed",
                },
            )
        self.assertIn("Updated task #1 status", result)
        # Hook received correct args
        self.assertEqual(len(received_args), 1)
        self.assertEqual(received_args[0], ("1", "Fix bug", "Fix the auth bug"))
        # Task is completed
        task = self.store.get_task(self.list_id, "1")
        assert task is not None
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    async def test_completed_hook_blocking_rejects(self) -> None:
        """Blocking hook: completion is rejected, task stays in_progress."""

        async def blocking_hook(task_id: str, subject: str, description: str) -> str | None:
            return "Tests are failing"

        self.mgr.register_completed_hook(blocking_hook)
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "in_progress",
                },
            )
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "completed",
                },
            )
        self.assertIn("completion blocked", result)
        self.assertIn("Tests are failing", result)
        # Task remains in_progress
        task = self.store.get_task(self.list_id, "1")
        assert task is not None
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    async def test_completed_hook_not_triggered_for_other_statuses(self) -> None:
        """Completed hooks only fire for status→completed, not in_progress."""
        hook_called = False

        async def hook(task_id: str, subject: str, description: str) -> str | None:
            nonlocal hook_called
            hook_called = True
            return None

        self.mgr.register_completed_hook(hook)
        await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "in_progress",
                },
            )
        self.assertFalse(hook_called)

    async def test_no_hooks_registered(self) -> None:
        """Without hooks, create and complete work normally."""
        result = await self.mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        self.assertIn("created successfully", result)
        result = await self.mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "completed",
                },
            )
        self.assertIn("Updated task #1 status", result)


if __name__ == "__main__":
    unittest.main()
