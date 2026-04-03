from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tool schemas — same dict shape as SPAWN_SUBAGENT_SCHEMA in sub_agent.py
# ---------------------------------------------------------------------------

TASK_CREATE_SCHEMA: dict[str, Any] = {
    "name": "task_create",
    "description": (
        "Create a new task in the task list. Use this to break down complex "
        "work into discrete, trackable subtasks. Tasks are created with status "
        "'pending'. Use task_update to set dependencies (addBlocks/addBlockedBy) "
        "after creation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": (
                    "Brief, actionable title in imperative form "
                    "(e.g., 'Fix authentication bug in login flow')."
                ),
            },
            "description": {
                "type": "string",
                "description": "Detailed description of what needs to be done.",
            },
            "activeForm": {
                "type": "string",
                "description": (
                    "Present continuous form shown in spinner when in_progress "
                    "(e.g., 'Fixing authentication bug'). Falls back to subject if omitted."
                ),
            },
            "metadata": {
                "type": "object",
                "description": "Arbitrary metadata to attach to the task.",
            },
        },
        "required": ["subject", "description"],
    },
}

TASK_UPDATE_SCHEMA: dict[str, Any] = {
    "name": "task_update",
    "description": (
        "Update an existing task's status, details, ownership, or dependencies. "
        "Set status to 'in_progress' when starting work, 'completed' when done, "
        "or 'deleted' to permanently remove a task."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "taskId": {
                "type": "string",
                "description": "The ID of the task to update.",
            },
            "subject": {
                "type": "string",
                "description": "New subject for the task.",
            },
            "description": {
                "type": "string",
                "description": "New description for the task.",
            },
            "activeForm": {
                "type": "string",
                "description": "New spinner text (present continuous form).",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "deleted"],
                "description": "New status. Use 'deleted' to permanently remove the task.",
            },
            "owner": {
                "type": "string",
                "description": "New owner agent name.",
            },
            "addBlocks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs that cannot start until this task completes.",
            },
            "addBlockedBy": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs that must complete before this task can start.",
            },
            "metadata": {
                "type": "object",
                "description": "Metadata keys to merge (set a key to null to delete it).",
            },
        },
        "required": ["taskId"],
    },
}

TASK_LIST_SCHEMA: dict[str, Any] = {
    "name": "task_list",
    "description": (
        "List all tasks in the current task list. Returns a summary of each "
        "task including id, subject, status, owner, and active blockers. "
        "Use this to check progress and find available work."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

TASK_GET_SCHEMA: dict[str, Any] = {
    "name": "task_get",
    "description": (
        "Retrieve full details of a single task by ID, including its "
        "description, dependencies, and metadata."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "taskId": {
                "type": "string",
                "description": "The ID of the task to retrieve.",
            },
        },
        "required": ["taskId"],
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASK_TOOL_NAMES: frozenset[str] = frozenset({
    "task_create", "task_update", "task_list", "task_get",
})

ALL_TASK_SCHEMAS: list[dict[str, Any]] = [
    TASK_CREATE_SCHEMA,
    TASK_UPDATE_SCHEMA,
    TASK_LIST_SCHEMA,
    TASK_GET_SCHEMA,
]


def is_task_tool(name: str) -> bool:
    """Return ``True`` if *name* is one of the four task decomposition tools."""
    return name in TASK_TOOL_NAMES
