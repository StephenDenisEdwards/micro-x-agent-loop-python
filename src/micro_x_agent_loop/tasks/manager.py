from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from micro_x_agent_loop.tasks.models import TaskStatus
from micro_x_agent_loop.tasks.store import TaskStore

logger = logging.getLogger(__name__)

# Hook signature: (task_id, subject, description) -> optional blocking error
TaskHook = Callable[[str, str, str], Awaitable[str | None]]

# Mutation listener: called after any task mutation with the current task list
MutationListener = Callable[[], None]


class TaskManager:
    """Orchestrates task tool calls and formats results.

    Implements the four task tools from task-decomposition-implementation-guide.md
    Sections 5.1-5.4.  All methods return formatted strings (never raise for
    user-facing errors like "not found") — see guide Section 7.1.

    Lifecycle hooks (guide Section 8):
    - ``taskCreatedHooks`` fire after a task is created; blocking errors roll back
    - ``taskCompletedHooks`` fire when status changes to completed; blocking errors
      reject the status change
    """

    def __init__(self, store: TaskStore, list_id: str, agent_id: str | None = None) -> None:
        self._store = store
        self._list_id = list_id
        self._agent_id = agent_id
        self._created_hooks: list[TaskHook] = []
        self._completed_hooks: list[TaskHook] = []
        self._mutation_listeners: list[MutationListener] = []

    def register_created_hook(self, hook: TaskHook) -> None:
        """Register a hook that fires after task creation."""
        self._created_hooks.append(hook)

    def register_completed_hook(self, hook: TaskHook) -> None:
        """Register a hook that fires when a task is marked completed."""
        self._completed_hooks.append(hook)

    def register_mutation_listener(self, listener: MutationListener) -> None:
        """Register a listener notified after any task mutation."""
        self._mutation_listeners.append(listener)

    def _notify_mutation(self) -> None:
        """Notify all mutation listeners. Errors are silenced (guide Section 7.6)."""
        for listener in self._mutation_listeners:
            try:
                listener()
            except Exception:
                pass

    async def handle_tool_call(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Route a task tool call to the appropriate handler.

        Returns a formatted result string.  Never raises for benign errors
        (e.g. task not found) — these are returned as normal content to avoid
        sibling tool cancellation in parallel execution (guide Section 7.1).
        """
        match tool_name:
            case "task_create":
                return await self._handle_create(tool_input)
            case "task_update":
                return await self._handle_update(tool_input)
            case "task_list":
                return self._handle_list(tool_input)
            case "task_get":
                return self._handle_get(tool_input)
            case _:
                return f"Unknown task tool: {tool_name}"

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    async def _run_hooks(
        self, hooks: list[TaskHook], task_id: str, subject: str, description: str,
    ) -> str | None:
        """Execute hooks in order. Return the first blocking error, or ``None``."""
        for hook in hooks:
            error = await hook(task_id, subject, description)
            if error is not None:
                return error
        return None

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_create(self, inp: dict[str, Any]) -> str:
        """Section 5.1: create a task, return ``Task #N created successfully: <subject>``.

        Executes ``taskCreatedHooks`` after creation.  If any hook returns a
        blocking error, the task is deleted (rolled back) and the error is
        returned to the agent (guide Section 7.2).
        """
        subject: str = inp.get("subject", "")
        description: str = inp.get("description", "")
        active_form: str | None = inp.get("activeForm")
        metadata: dict[str, Any] | None = inp.get("metadata")

        if not subject or not description:
            return "Error: subject and description are required."

        task = self._store.create_task(
            self._list_id,
            subject=subject,
            description=description,
            active_form=active_form,
            metadata=metadata,
        )

        # Execute created hooks — rollback on blocking error (guide Section 8.3)
        if self._created_hooks:
            error = await self._run_hooks(
                self._created_hooks, task.id, task.subject, task.description,
            )
            if error is not None:
                self._store.delete_task(self._list_id, task.id)
                logger.warning("task_create id=%s rolled back: %s", task.id, error)
                return f"Task creation blocked: {error}"

        logger.info("task_create id=%s subject=%r", task.id, task.subject)
        self._notify_mutation()
        return f"Task #{task.id} created successfully: {task.subject}"

    async def _handle_update(self, inp: dict[str, Any]) -> str:
        """Section 5.2: update a task, return ``Updated task #N <fields>``.

        Executes ``taskCompletedHooks`` when status changes to completed.
        If any hook returns a blocking error, the status change is rejected
        (guide Section 7.2).
        """
        task_id: str = inp.get("taskId", "")
        if not task_id:
            return "Error: taskId is required."

        # Handle deletion as a special case (guide Section 3.3)
        status_str: str | None = inp.get("status")
        if status_str == "deleted":
            deleted = self._store.delete_task(self._list_id, task_id)
            if not deleted:
                return f"Task #{task_id} not found"
            logger.info("task_delete id=%s", task_id)
            self._notify_mutation()
            return f"Updated task #{task_id} deleted"

        # Verify task exists before updating
        existing = self._store.get_task(self._list_id, task_id)
        if existing is None:
            return f"Task #{task_id} not found"

        # Execute completed hooks BEFORE applying status change (guide Section 8.3)
        if status_str == "completed" and self._completed_hooks:
            error = await self._run_hooks(
                self._completed_hooks, task_id, existing.subject, existing.description,
            )
            if error is not None:
                logger.warning("task_update id=%s completion blocked: %s", task_id, error)
                return f"Task #{task_id} completion blocked: {error}"

        # Build update kwargs
        updates: dict[str, Any] = {}
        updated_fields: list[str] = []

        for field, key in [("subject", "subject"), ("description", "description"),
                           ("active_form", "activeForm"), ("owner", "owner")]:
            if key in inp:
                updates[field] = inp[key]
                updated_fields.append(key)

        if status_str is not None:
            updates["status"] = TaskStatus(status_str)
            updated_fields.append("status")
            # Auto-assign owner on in_progress if agent_id is set (guide Section 9.4)
            if (
                status_str == "in_progress"
                and self._agent_id is not None
                and "owner" not in inp
                and existing.owner is None
            ):
                updates["owner"] = self._agent_id
                updated_fields.append("owner")

        if "metadata" in inp:
            updates["metadata"] = inp["metadata"]
            updated_fields.append("metadata")

        if updates:
            self._store.update_task(self._list_id, task_id, **updates)

        # Handle addBlocks: this task blocks others
        add_blocks: list[str] = inp.get("addBlocks") or []
        for blocked_id in add_blocks:
            self._store.block_task(self._list_id, task_id, blocked_id)
        if add_blocks:
            updated_fields.append("blocks")

        # Handle addBlockedBy: others block this task
        add_blocked_by: list[str] = inp.get("addBlockedBy") or []
        for blocker_id in add_blocked_by:
            self._store.block_task(self._list_id, blocker_id, task_id)
        if add_blocked_by:
            updated_fields.append("blockedBy")

        if not updated_fields:
            return f"Task #{task_id} unchanged (no fields provided)"

        fields_str = ", ".join(updated_fields)
        logger.info("task_update id=%s fields=%s", task_id, fields_str)
        self._notify_mutation()
        return f"Updated task #{task_id} {fields_str}"

    def _handle_list(self, inp: dict[str, Any]) -> str:
        """Section 5.3: list tasks with resolved-blocker filtering."""
        tasks = self._store.list_tasks(self._list_id)
        if not tasks:
            return "No tasks."

        # Build set of completed task IDs for blocker filtering (guide Section 6.3)
        completed_ids: set[str] = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}

        lines: list[str] = []
        for task in tasks:
            line = f"#{task.id} [{task.status.value}] {task.subject}"
            if task.owner:
                line += f" ({task.owner})"
            # Only show non-completed blockers
            active_blockers = [bid for bid in task.blocked_by if bid not in completed_ids]
            if active_blockers:
                blocker_refs = ", ".join(f"#{bid}" for bid in active_blockers)
                line += f" [blocked by {blocker_refs}]"
            lines.append(line)

        return "\n".join(lines)

    def _handle_get(self, inp: dict[str, Any]) -> str:
        """Section 5.4: return full task details."""
        task_id: str = inp.get("taskId", "")
        if not task_id:
            return "Error: taskId is required."

        task = self._store.get_task(self._list_id, task_id)
        if task is None:
            return "Task not found"

        lines: list[str] = [
            f"Task #{task.id}: {task.subject}",
            f"Status: {task.status.value}",
            f"Description: {task.description}",
        ]
        if task.blocked_by:
            refs = ", ".join(f"#{bid}" for bid in task.blocked_by)
            lines.append(f"Blocked by: {refs}")
        if task.blocks:
            refs = ", ".join(f"#{bid}" for bid in task.blocks)
            lines.append(f"Blocks: {refs}")
        if task.owner:
            lines.append(f"Owner: {task.owner}")

        return "\n".join(lines)
