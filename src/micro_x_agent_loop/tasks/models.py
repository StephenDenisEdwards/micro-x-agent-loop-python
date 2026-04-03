from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    """Lifecycle states for a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class Task:
    """A single decomposed task.

    Fields mirror the reference specification (task-decomposition-implementation-guide.md
    Section 3.1).  ``id`` is string-typed for human-readable display (``#1``, ``#2``).
    """

    id: str
    subject: str
    description: str
    status: TaskStatus
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    active_form: str | None = None
    owner: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ClaimResult:
    """Result of attempting to claim a task (guide Section 9.1)."""

    success: bool
    reason: str | None = None  # task_not_found, already_claimed, already_resolved, blocked, agent_busy
    task: Task | None = None
    busy_with_tasks: list[str] | None = None
    blocked_by_tasks: list[str] | None = None


@dataclass
class AgentStatus:
    """Status of an agent relative to the task list (guide Section 9.3)."""

    agent_id: str
    name: str
    status: str  # "idle" | "busy"
    current_tasks: list[str] = field(default_factory=list)
