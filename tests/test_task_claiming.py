from __future__ import annotations

import os
import tempfile
import unittest

from micro_x_agent_loop.tasks.models import TaskStatus
from micro_x_agent_loop.tasks.store import TaskStore


class TestClaimTask(unittest.TestCase):
    """Tests for multi-agent task claiming (guide Section 9.1)."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self._tmpdir, "tasks.db")
        self.store = TaskStore(db_path)
        self.list_id = "test-session"

    def tearDown(self) -> None:
        self.store.close()

    # ------------------------------------------------------------------
    # Basic claim
    # ------------------------------------------------------------------

    def test_claim_success(self) -> None:
        self.store.create_task(self.list_id, "Task A", "desc")
        result = self.store.claim_task(self.list_id, "1", "alice")
        self.assertTrue(result.success)
        assert result.task is not None
        self.assertEqual(result.task.owner, "alice")
        self.assertEqual(result.task.status, TaskStatus.IN_PROGRESS)

    def test_claim_sets_in_progress(self) -> None:
        self.store.create_task(self.list_id, "Task A", "desc")
        self.store.claim_task(self.list_id, "1", "alice")
        task = self.store.get_task(self.list_id, "1")
        assert task is not None
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    # ------------------------------------------------------------------
    # Claim checks
    # ------------------------------------------------------------------

    def test_claim_not_found(self) -> None:
        result = self.store.claim_task(self.list_id, "999", "alice")
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "task_not_found")

    def test_claim_already_claimed_by_other(self) -> None:
        self.store.create_task(self.list_id, "Task A", "desc")
        self.store.claim_task(self.list_id, "1", "alice")
        result = self.store.claim_task(self.list_id, "1", "bob")
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "already_claimed")

    def test_claim_same_agent_reclaim_ok(self) -> None:
        """Same-agent re-claim is allowed (guide Section 9.1)."""
        self.store.create_task(self.list_id, "Task A", "desc")
        self.store.claim_task(self.list_id, "1", "alice")
        result = self.store.claim_task(self.list_id, "1", "alice")
        self.assertTrue(result.success)

    def test_claim_already_completed(self) -> None:
        self.store.create_task(self.list_id, "Task A", "desc")
        self.store.update_task(self.list_id, "1", status=TaskStatus.COMPLETED)
        result = self.store.claim_task(self.list_id, "1", "alice")
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "already_resolved")

    def test_claim_blocked(self) -> None:
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.block_task(self.list_id, "1", "2")  # A blocks B

        result = self.store.claim_task(self.list_id, "2", "alice")
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "blocked")
        assert result.blocked_by_tasks is not None
        self.assertIn("1", result.blocked_by_tasks)

    def test_claim_blocked_resolved(self) -> None:
        """Completed blockers don't prevent claiming."""
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.block_task(self.list_id, "1", "2")
        self.store.update_task(self.list_id, "1", status=TaskStatus.COMPLETED)

        result = self.store.claim_task(self.list_id, "2", "alice")
        self.assertTrue(result.success)

    # ------------------------------------------------------------------
    # Busy check (guide Section 9.2)
    # ------------------------------------------------------------------

    def test_claim_agent_busy(self) -> None:
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.claim_task(self.list_id, "1", "alice")

        result = self.store.claim_task(self.list_id, "2", "alice", check_busy=True)
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "agent_busy")
        assert result.busy_with_tasks is not None
        self.assertIn("1", result.busy_with_tasks)

    def test_claim_agent_busy_not_checked_by_default(self) -> None:
        """Without check_busy=True, agent can claim multiple tasks."""
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.claim_task(self.list_id, "1", "alice")

        result = self.store.claim_task(self.list_id, "2", "alice")
        self.assertTrue(result.success)


class TestAgentStatuses(unittest.TestCase):
    """Tests for get_agent_statuses (guide Section 9.3)."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self._tmpdir, "tasks.db")
        self.store = TaskStore(db_path)
        self.list_id = "test-session"

    def tearDown(self) -> None:
        self.store.close()

    def test_idle_agents(self) -> None:
        statuses = self.store.get_agent_statuses(self.list_id, ["alice", "bob"])
        self.assertEqual(len(statuses), 2)
        self.assertEqual(statuses[0].status, "idle")
        self.assertEqual(statuses[1].status, "idle")

    def test_busy_agent(self) -> None:
        self.store.create_task(self.list_id, "Task", "desc")
        self.store.claim_task(self.list_id, "1", "alice")

        statuses = self.store.get_agent_statuses(self.list_id, ["alice", "bob"])
        alice = next(s for s in statuses if s.agent_id == "alice")
        bob = next(s for s in statuses if s.agent_id == "bob")
        self.assertEqual(alice.status, "busy")
        self.assertIn("1", alice.current_tasks)
        self.assertEqual(bob.status, "idle")

    def test_completed_task_not_busy(self) -> None:
        self.store.create_task(self.list_id, "Task", "desc")
        self.store.claim_task(self.list_id, "1", "alice")
        self.store.update_task(self.list_id, "1", status=TaskStatus.COMPLETED)

        statuses = self.store.get_agent_statuses(self.list_id, ["alice"])
        self.assertEqual(statuses[0].status, "idle")


class TestUnassignAgentTasks(unittest.TestCase):
    """Tests for unassign_agent_tasks (guide Section 9.5)."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self._tmpdir, "tasks.db")
        self.store = TaskStore(db_path)
        self.list_id = "test-session"

    def tearDown(self) -> None:
        self.store.close()

    def test_unassign_resets_to_pending(self) -> None:
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.claim_task(self.list_id, "1", "alice")
        self.store.claim_task(self.list_id, "2", "alice")

        unassigned, msg = self.store.unassign_agent_tasks(
            self.list_id,
            "alice",
            "terminated",
        )
        self.assertEqual(len(unassigned), 2)
        self.assertIn("alice was terminated", msg)
        self.assertIn('#1 "A"', msg)
        self.assertIn('#2 "B"', msg)

        # Both tasks should be pending with no owner
        for tid in ("1", "2"):
            task = self.store.get_task(self.list_id, tid)
            assert task is not None
            self.assertEqual(task.status, TaskStatus.PENDING)
            self.assertIsNone(task.owner)

    def test_unassign_skips_completed(self) -> None:
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.claim_task(self.list_id, "1", "alice")
        self.store.update_task(self.list_id, "1", status=TaskStatus.COMPLETED)
        self.store.claim_task(self.list_id, "2", "alice")

        unassigned, msg = self.store.unassign_agent_tasks(
            self.list_id,
            "alice",
            "shutdown",
        )
        self.assertEqual(len(unassigned), 1)
        self.assertEqual(unassigned[0].id, "2")

        # Completed task unchanged
        t1 = self.store.get_task(self.list_id, "1")
        assert t1 is not None
        self.assertEqual(t1.status, TaskStatus.COMPLETED)

    def test_unassign_no_tasks(self) -> None:
        unassigned, msg = self.store.unassign_agent_tasks(
            self.list_id,
            "alice",
            "shutdown",
        )
        self.assertEqual(len(unassigned), 0)
        self.assertIn("No tasks were unassigned", msg)

    def test_unassign_only_own_tasks(self) -> None:
        """Only tasks owned by the specified agent are unassigned."""
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.claim_task(self.list_id, "1", "alice")
        self.store.claim_task(self.list_id, "2", "bob")

        unassigned, _ = self.store.unassign_agent_tasks(
            self.list_id,
            "alice",
            "terminated",
        )
        self.assertEqual(len(unassigned), 1)
        # Bob's task untouched
        t2 = self.store.get_task(self.list_id, "2")
        assert t2 is not None
        self.assertEqual(t2.owner, "bob")


class TestAutoOwner(unittest.TestCase):
    """Tests for auto-owner assignment in TaskManager (guide Section 9.4)."""

    def setUp(self) -> None:
        import asyncio

        self._asyncio = asyncio
        self._tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self._tmpdir, "tasks.db")
        self.store = TaskStore(db_path)
        self.list_id = "test-session"

    def tearDown(self) -> None:
        self.store.close()

    def _run(self, coro: object) -> str:
        return self._asyncio.run(coro)  # type: ignore[arg-type]

    def test_auto_owner_on_in_progress(self) -> None:
        from micro_x_agent_loop.tasks.manager import TaskManager

        mgr = TaskManager(self.store, self.list_id, agent_id="alice")
        self._run(
            mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        )
        result = self._run(
            mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "in_progress",
                },
            )
        )
        self.assertIn("status", result)
        self.assertIn("owner", result)

        task = self.store.get_task(self.list_id, "1")
        assert task is not None
        self.assertEqual(task.owner, "alice")

    def test_no_auto_owner_without_agent_id(self) -> None:
        from micro_x_agent_loop.tasks.manager import TaskManager

        mgr = TaskManager(self.store, self.list_id)  # no agent_id
        self._run(
            mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        )
        self._run(
            mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "in_progress",
                },
            )
        )
        task = self.store.get_task(self.list_id, "1")
        assert task is not None
        self.assertIsNone(task.owner)

    def test_explicit_owner_overrides_auto(self) -> None:
        from micro_x_agent_loop.tasks.manager import TaskManager

        mgr = TaskManager(self.store, self.list_id, agent_id="alice")
        self._run(
            mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        )
        self._run(
            mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "in_progress",
                    "owner": "bob",
                },
            )
        )
        task = self.store.get_task(self.list_id, "1")
        assert task is not None
        self.assertEqual(task.owner, "bob")

    def test_no_auto_owner_if_already_owned(self) -> None:
        from micro_x_agent_loop.tasks.manager import TaskManager

        mgr = TaskManager(self.store, self.list_id, agent_id="alice")
        self._run(
            mgr.handle_tool_call(
                "task_create",
                {
                    "subject": "Task",
                    "description": "desc",
                },
            )
        )
        # Set owner first
        self._run(
            mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "owner": "bob",
                },
            )
        )
        # Now mark in_progress — should NOT override bob with alice
        self._run(
            mgr.handle_tool_call(
                "task_update",
                {
                    "taskId": "1",
                    "status": "in_progress",
                },
            )
        )
        task = self.store.get_task(self.list_id, "1")
        assert task is not None
        self.assertEqual(task.owner, "bob")


if __name__ == "__main__":
    unittest.main()
