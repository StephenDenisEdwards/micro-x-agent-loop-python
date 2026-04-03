from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

from micro_x_agent_loop.tasks.models import Task, TaskStatus
from micro_x_agent_loop.tasks.store import TaskStore


class TestTaskStore(unittest.TestCase):
    """Tests for the SQLite-backed TaskStore.

    Covers the integration test scenarios from task-decomposition-implementation-guide.md
    Sections 13.1-13.6.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "tasks.db")
        self.store = TaskStore(self._db_path)
        self.list_id = "test-session"

    def tearDown(self) -> None:
        self.store.close()

    # ------------------------------------------------------------------
    # 13.1  Basic lifecycle
    # ------------------------------------------------------------------

    def test_create_task(self) -> None:
        task = self.store.create_task(self.list_id, "Write tests", "Add unit tests for auth module")
        self.assertEqual(task.id, "1")
        self.assertEqual(task.subject, "Write tests")
        self.assertEqual(task.description, "Add unit tests for auth module")
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertEqual(task.blocks, [])
        self.assertEqual(task.blocked_by, [])
        self.assertIsNone(task.owner)

    def test_get_task(self) -> None:
        self.store.create_task(self.list_id, "Write tests", "desc")
        task = self.store.get_task(self.list_id, "1")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.subject, "Write tests")

    def test_get_task_not_found(self) -> None:
        result = self.store.get_task(self.list_id, "999")
        self.assertIsNone(result)

    def test_list_tasks(self) -> None:
        self.store.create_task(self.list_id, "Task A", "desc a")
        self.store.create_task(self.list_id, "Task B", "desc b")
        tasks = self.store.list_tasks(self.list_id)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0].subject, "Task A")
        self.assertEqual(tasks[1].subject, "Task B")

    def test_update_task_status(self) -> None:
        self.store.create_task(self.list_id, "Write tests", "desc")
        updated = self.store.update_task(self.list_id, "1", status=TaskStatus.IN_PROGRESS)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.status, TaskStatus.IN_PROGRESS)

        completed = self.store.update_task(self.list_id, "1", status=TaskStatus.COMPLETED)
        assert completed is not None
        self.assertEqual(completed.status, TaskStatus.COMPLETED)

    def test_update_task_fields(self) -> None:
        self.store.create_task(self.list_id, "Original", "desc")
        updated = self.store.update_task(
            self.list_id, "1",
            subject="Updated",
            description="new desc",
            active_form="Updating",
            owner="alice",
        )
        assert updated is not None
        self.assertEqual(updated.subject, "Updated")
        self.assertEqual(updated.description, "new desc")
        self.assertEqual(updated.active_form, "Updating")
        self.assertEqual(updated.owner, "alice")

    def test_update_task_not_found(self) -> None:
        result = self.store.update_task(self.list_id, "999", subject="X")
        self.assertIsNone(result)

    def test_update_task_metadata_merge(self) -> None:
        self.store.create_task(self.list_id, "Task", "desc", metadata={"key1": "val1"})
        updated = self.store.update_task(self.list_id, "1", metadata={"key2": "val2"})
        assert updated is not None
        assert updated.metadata is not None
        self.assertEqual(updated.metadata["key1"], "val1")
        self.assertEqual(updated.metadata["key2"], "val2")

    def test_update_task_metadata_delete_key(self) -> None:
        self.store.create_task(self.list_id, "Task", "desc", metadata={"key1": "val1", "key2": "val2"})
        updated = self.store.update_task(self.list_id, "1", metadata={"key1": None})
        assert updated is not None
        assert updated.metadata is not None
        self.assertNotIn("key1", updated.metadata)
        self.assertEqual(updated.metadata["key2"], "val2")

    # ------------------------------------------------------------------
    # 13.1  Full lifecycle sequence
    # ------------------------------------------------------------------

    def test_full_lifecycle(self) -> None:
        """Section 13.1: create → list → update(in_progress) → get → update(completed) → list."""
        task = self.store.create_task(self.list_id, "Write tests", "Add unit tests for auth module")
        self.assertEqual(task.id, "1")

        tasks = self.store.list_tasks(self.list_id)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].status, TaskStatus.PENDING)

        self.store.update_task(self.list_id, "1", status=TaskStatus.IN_PROGRESS)
        got = self.store.get_task(self.list_id, "1")
        assert got is not None
        self.assertEqual(got.status, TaskStatus.IN_PROGRESS)

        self.store.update_task(self.list_id, "1", status=TaskStatus.COMPLETED)
        tasks = self.store.list_tasks(self.list_id)
        self.assertEqual(tasks[0].status, TaskStatus.COMPLETED)

    # ------------------------------------------------------------------
    # Auto-incrementing IDs
    # ------------------------------------------------------------------

    def test_auto_increment_ids(self) -> None:
        t1 = self.store.create_task(self.list_id, "Task 1", "desc")
        t2 = self.store.create_task(self.list_id, "Task 2", "desc")
        t3 = self.store.create_task(self.list_id, "Task 3", "desc")
        self.assertEqual(t1.id, "1")
        self.assertEqual(t2.id, "2")
        self.assertEqual(t3.id, "3")

    # ------------------------------------------------------------------
    # 13.5  ID non-reuse after delete (high water mark)
    # ------------------------------------------------------------------

    def test_id_non_reuse_after_delete(self) -> None:
        """Section 13.5: deleted IDs must never be reused."""
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.delete_task(self.list_id, "2")

        t3 = self.store.create_task(self.list_id, "C", "desc")
        self.assertEqual(t3.id, "3")  # NOT "2"

        # Verify task 2 no longer exists
        self.assertIsNone(self.store.get_task(self.list_id, "2"))

    # ------------------------------------------------------------------
    # 13.2  Dependency chain
    # ------------------------------------------------------------------

    def test_bidirectional_dependencies(self) -> None:
        """Section 6.1: block_task creates bidirectional edges."""
        self.store.create_task(self.list_id, "Task A", "desc")
        self.store.create_task(self.list_id, "Task B", "desc")

        result = self.store.block_task(self.list_id, "1", "2")
        self.assertTrue(result)

        t1 = self.store.get_task(self.list_id, "1")
        t2 = self.store.get_task(self.list_id, "2")
        assert t1 is not None and t2 is not None
        self.assertIn("2", t1.blocks)
        self.assertIn("1", t2.blocked_by)

    def test_dependency_chain(self) -> None:
        """Section 13.2: blocked_by filtering as tasks complete."""
        self.store.create_task(self.list_id, "Task A", "desc")
        self.store.create_task(self.list_id, "Task B", "desc")
        self.store.create_task(self.list_id, "Task C", "desc")

        self.store.block_task(self.list_id, "1", "2")  # A blocks B
        self.store.block_task(self.list_id, "2", "3")  # B blocks C

        tasks = self.store.list_tasks(self.list_id)
        self.assertEqual(len(tasks), 3)
        # Task B is blocked by A
        self.assertIn("1", tasks[1].blocked_by)
        # Task C is blocked by B
        self.assertIn("2", tasks[2].blocked_by)

    def test_block_task_nonexistent(self) -> None:
        self.store.create_task(self.list_id, "Task A", "desc")
        result = self.store.block_task(self.list_id, "1", "999")
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # 13.4  Delete with cascade
    # ------------------------------------------------------------------

    def test_delete_cascades_dependencies(self) -> None:
        """Section 13.4: deleting a task removes all dependency references."""
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.create_task(self.list_id, "C", "desc")

        self.store.block_task(self.list_id, "1", "2")  # A blocks B
        self.store.block_task(self.list_id, "1", "3")  # A blocks C

        # Verify deps before delete
        t2 = self.store.get_task(self.list_id, "2")
        t3 = self.store.get_task(self.list_id, "3")
        assert t2 is not None and t3 is not None
        self.assertIn("1", t2.blocked_by)
        self.assertIn("1", t3.blocked_by)

        # Delete task A
        result = self.store.delete_task(self.list_id, "1")
        self.assertTrue(result)

        # Verify task A is gone
        self.assertIsNone(self.store.get_task(self.list_id, "1"))

        # Verify references cleaned up
        t2 = self.store.get_task(self.list_id, "2")
        t3 = self.store.get_task(self.list_id, "3")
        assert t2 is not None and t3 is not None
        self.assertEqual(t2.blocked_by, [])
        self.assertEqual(t3.blocked_by, [])

    def test_delete_nonexistent(self) -> None:
        result = self.store.delete_task(self.list_id, "999")
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def test_reset_task_list(self) -> None:
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.block_task(self.list_id, "1", "2")

        self.store.reset_task_list(self.list_id)

        tasks = self.store.list_tasks(self.list_id)
        self.assertEqual(len(tasks), 0)

    def test_reset_preserves_hwm(self) -> None:
        """After reset, new tasks get IDs beyond the old maximum."""
        self.store.create_task(self.list_id, "A", "desc")
        self.store.create_task(self.list_id, "B", "desc")
        self.store.reset_task_list(self.list_id)

        t = self.store.create_task(self.list_id, "C", "desc")
        self.assertEqual(t.id, "3")  # HWM was 2, so next is 3

    # ------------------------------------------------------------------
    # Internal tasks filtering
    # ------------------------------------------------------------------

    def test_list_filters_internal_tasks(self) -> None:
        self.store.create_task(self.list_id, "Visible", "desc")
        self.store.create_task(self.list_id, "Internal", "desc", metadata={"_internal": True})

        tasks = self.store.list_tasks(self.list_id)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].subject, "Visible")

    # ------------------------------------------------------------------
    # List isolation
    # ------------------------------------------------------------------

    def test_list_id_isolation(self) -> None:
        """Tasks from different list_ids are isolated."""
        self.store.create_task("session-1", "Task S1", "desc")
        self.store.create_task("session-2", "Task S2", "desc")

        s1_tasks = self.store.list_tasks("session-1")
        s2_tasks = self.store.list_tasks("session-2")
        self.assertEqual(len(s1_tasks), 1)
        self.assertEqual(s1_tasks[0].subject, "Task S1")
        self.assertEqual(len(s2_tasks), 1)
        self.assertEqual(s2_tasks[0].subject, "Task S2")

    # ------------------------------------------------------------------
    # Active form and metadata
    # ------------------------------------------------------------------

    def test_create_with_active_form(self) -> None:
        task = self.store.create_task(
            self.list_id, "Run tests", "desc", active_form="Running tests"
        )
        self.assertEqual(task.active_form, "Running tests")

    def test_create_with_metadata(self) -> None:
        task = self.store.create_task(
            self.list_id, "Task", "desc", metadata={"priority": "high"}
        )
        assert task.metadata is not None
        self.assertEqual(task.metadata["priority"], "high")

    # ------------------------------------------------------------------
    # 13.6  Parallel creation (concurrency)
    # ------------------------------------------------------------------

    def test_parallel_creation_unique_ids(self) -> None:
        """Section 13.6: concurrent creates produce unique IDs.

        Each thread gets its own TaskStore (separate connection) to avoid
        SQLite's single-connection transaction limitation.  The stores share
        the same database file, so SQLite file-level locking serialises writes.
        """

        def _create_in_thread(i: int) -> Task:
            store = TaskStore(self._db_path)
            try:
                return store.create_task(self.list_id, f"Task {i}", f"desc {i}")
            finally:
                store.close()

        async def create_tasks() -> list[Task]:
            loop = asyncio.get_event_loop()
            tasks_created = await asyncio.gather(
                *[
                    loop.run_in_executor(None, _create_in_thread, i)
                    for i in range(5)
                ]
            )
            return list(tasks_created)

        created = asyncio.run(create_tasks())
        ids = {t.id for t in created}
        self.assertEqual(len(ids), 5)  # All unique
        self.assertEqual(ids, {"1", "2", "3", "4", "5"})


if __name__ == "__main__":
    unittest.main()
