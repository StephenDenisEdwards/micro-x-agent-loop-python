# Design: Task Decomposition System

## Overview

The task decomposition system enables the agent to break complex user requests into discrete, trackable subtasks with dependency management, lifecycle hooks, multi-agent coordination, and real-time TUI display. It is exposed to the LLM as four pseudo-tools (`task_create`, `task_update`, `task_list`, `task_get`) that are handled inline within `TurnEngine` — no MCP server required.

The design follows the [task-decomposition-implementation-guide.md](../task-decomposition-implementation-guide.md) specification, adapted from file-based JSON storage to SQLite and from TypeScript to Python.

**Feature flag:** `TaskDecompositionEnabled` (default `false` in `config-base.json`).

## Package Structure

All task code lives in `src/micro_x_agent_loop/tasks/`:

| Module | Responsibility |
|--------|---------------|
| `models.py` | `Task`, `TaskStatus`, `ClaimResult`, `AgentStatus` dataclasses |
| `store.py` | SQLite-backed CRUD, dependency DAG, high-water-mark, claiming, agent status |
| `schemas.py` | 4 tool JSON schemas for the LLM API, `is_task_tool()` helper |
| `manager.py` | Tool call routing, result formatting, lifecycle hooks, mutation listeners |

## Data Model

### Task

```python
class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

@dataclass
class Task:
    id: str                          # Auto-incrementing numeric, string-typed for display
    subject: str                     # Brief imperative title
    description: str                 # Detailed requirements
    status: TaskStatus               # Lifecycle state
    blocks: list[str]                # IDs of tasks this task blocks
    blocked_by: list[str]            # IDs of tasks blocking this task
    active_form: str | None          # Present-continuous label for spinner UI
    owner: str | None                # Agent name/ID (multi-agent)
    metadata: dict[str, Any] | None  # Extensibility; _internal key hides from list
```

### Status Lifecycle

```
pending ──> in_progress ──> completed
   │
   └──> deleted (pseudo-status — permanent removal via task_update)
```

### Dependencies

Tasks form a DAG via bidirectional `blocks`/`blockedBy` edges. When task A blocks task B:
- A's `blocks` contains B's ID
- B's `blocked_by` contains A's ID

Both sides are always maintained in sync via `block_task()`. Deleting a task cascades — all references are removed from other tasks' edges.

When listing tasks, completed blockers are filtered from the `blocked_by` display so the agent sees which tasks are genuinely unblocked.

## Storage Layer

### Database

File: `.micro_x/tasks.db` (separate from `memory.db` and `broker.db`).

Connection: `sqlite3.connect(path, check_same_thread=False, isolation_level=None)` — manual transaction control via `BEGIN IMMEDIATE` for write serialization.

### Schema

```sql
CREATE TABLE tasks (
    id INTEGER NOT NULL,
    list_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'completed')),
    active_form TEXT,
    owner TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id, list_id)
);

CREATE TABLE task_dependencies (
    from_task_id INTEGER NOT NULL,
    to_task_id INTEGER NOT NULL,
    list_id TEXT NOT NULL,
    PRIMARY KEY (from_task_id, to_task_id, list_id)
);

CREATE TABLE high_water_marks (
    list_id TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
```

### List Isolation

Each session gets its own task list, keyed by `list_id = session_id`. Tasks from different sessions are fully isolated. The `list_id` appears in every query to enforce this boundary.

### High-Water-Mark

Prevents ID reuse after deletion. When creating a task:

```
next_id = max(hwm, max_existing_id) + 1
```

The HWM is updated on both create and delete. `reset_task_list()` preserves the HWM so new tasks after a reset continue from where IDs left off.

### TaskStore Methods

| Method | Description |
|--------|-------------|
| `create_task(list_id, subject, description, ...)` | In transaction: read HWM → compute next ID → insert → update HWM |
| `get_task(list_id, task_id)` | Read task + populate blocks/blocked_by from dependencies table |
| `list_tasks(list_id)` | All tasks ordered by ID, filters `metadata._internal` |
| `update_task(list_id, task_id, **updates)` | Field-level updates; metadata merge (null values delete keys) |
| `delete_task(list_id, task_id)` | Cascade: remove all dependency edges, update HWM, delete row |
| `block_task(list_id, from_id, to_id)` | Insert bidirectional edge into `task_dependencies` |
| `reset_task_list(list_id)` | Preserve HWM, delete all tasks + dependencies |
| `claim_task(list_id, task_id, agent_id, check_busy)` | Atomic claim with 5 checks (see Multi-Agent) |
| `get_agent_statuses(list_id, agent_ids)` | Idle/busy per agent based on task ownership |
| `unassign_agent_tasks(list_id, agent_id, reason)` | Reset exiting agent's open tasks to pending/unowned |

### Concurrency

SQLite transactions (`BEGIN IMMEDIATE`) replace the file locking used in the reference implementation. Within a single agent process, task tool calls are handled inline (sequentially), so no intra-process races. Cross-process safety (multi-agent) is provided by SQLite's built-in file-level locking. The `claim_task()` method wraps all checks + assignment in a single transaction for atomicity.

## Tool Definitions

Four pseudo-tool schemas defined in `schemas.py` as plain dicts (same pattern as `SPAWN_SUBAGENT_SCHEMA` in `sub_agent.py`):

| Tool | Input | Description |
|------|-------|-------------|
| `task_create` | `{subject, description, activeForm?, metadata?}` | Create a new pending task |
| `task_update` | `{taskId, subject?, description?, activeForm?, status?, owner?, addBlocks?, addBlockedBy?, metadata?}` | Update fields, set dependencies, delete |
| `task_list` | `{}` | List all non-internal tasks with filtered blockers |
| `task_get` | `{taskId}` | Full details of a single task |

Helpers: `TASK_TOOL_NAMES` (frozenset), `is_task_tool(name)`, `ALL_TASK_SCHEMAS` (list of all 4).

## TaskManager

Orchestrates tool calls and owns the `TaskStore`. Constructed with `(store, list_id, agent_id?)`.

### Tool Call Routing

```python
async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
    match tool_name:
        case "task_create": return await self._handle_create(tool_input)
        case "task_update": return await self._handle_update(tool_input)
        case "task_list":   return self._handle_list(tool_input)
        case "task_get":    return self._handle_get(tool_input)
```

Returns a formatted string — never raises for user-facing errors.

### Result Formatting

| Tool | Format |
|------|--------|
| Create | `"Task #1 created successfully: Fix authentication bug"` |
| Update | `"Updated task #1 status, owner"` |
| Delete | `"Updated task #1 deleted"` |
| List | `"#1 [completed] Set up schema\n#2 [in_progress] Auth (alice)\n#3 [pending] Tests [blocked by #2]"` |
| Get | `"Task #2: Auth\nStatus: in_progress\nDescription: ...\nBlocked by: #1\nBlocks: #3, #5"` |
| Not found | `"Task #999 not found"` (normal content, NOT `is_error`) |

### Error Handling

**Critical design rule**: "not found" and other benign errors are returned as normal `tool_result` text content, never as error-typed responses. Error-typed results trigger sibling tool cancellation in parallel execution, which would abort other in-flight tool calls unnecessarily.

### Lifecycle Hooks

Two hook points:

```python
TaskHook = Callable[[str, str, str], Awaitable[str | None]]
#                    task_id, subject, description → optional blocking error
```

- **`_created_hooks`**: fire after `store.create_task()`. On blocking error, the task is deleted (rollback) and `"Task creation blocked: <error>"` is returned.
- **`_completed_hooks`**: fire *before* applying `status=completed`. On blocking error, the status change is rejected and `"Task #N completion blocked: <error>"` is returned.

Hooks execute in registration order. First blocking error short-circuits (later hooks don't run).

Registration: `register_created_hook(hook)`, `register_completed_hook(hook)`.

### Mutation Listeners

```python
MutationListener = Callable[[], None]
```

Called after every successful create, update, or delete. Listener errors are silenced — task mutations must succeed regardless of notification failures. Used by the TUI to refresh the TaskPanel.

Registration: `register_mutation_listener(listener)`.

### Auto-Owner Assignment

When `agent_id` is set and `status` changes to `in_progress`:
- If no explicit `owner` in the input AND the task currently has no owner
- The agent_id is auto-assigned as owner
- Prevents ownership confusion in multi-agent scenarios

## Multi-Agent Coordination

### Task Claiming

`claim_task(list_id, task_id, agent_id, check_busy=False)` performs atomic checks inside `BEGIN IMMEDIATE`:

1. **Task exists** → `task_not_found`
2. **Not completed** → `already_resolved`
3. **Not claimed by another agent** (same-agent re-claim OK) → `already_claimed`
4. **No unresolved blockers** → `blocked` (includes `blocked_by_tasks`)
5. **(Optional)** Agent not busy with other open tasks → `agent_busy` (includes `busy_with_tasks`)

On success: sets `owner=agent_id` and `status=in_progress`.

Returns `ClaimResult` with `success`, `reason`, `task`, and optional detail lists.

### Agent Status

`get_agent_statuses(list_id, agent_ids)` returns `AgentStatus` per agent:
- `"busy"` if the agent owns at least one non-completed task
- `"idle"` otherwise

### Unassign on Exit

`unassign_agent_tasks(list_id, agent_id, reason)`:
1. Finds all non-completed tasks owned by the agent
2. Resets each to `status=pending`, `owner=None`
3. Returns `(unassigned_tasks, notification_message)`

Message format: `"alice was terminated. 2 task(s) were unassigned: #1 "Task A", #3 "Task C". Use task_list to check availability and task_update with owner to reassign them."`

## Integration Points

### TurnEngine

In `turn_engine.py`, task tools are handled as pseudo-tools alongside `ask_user`, `tool_search`, and `spawn_subagent`:

1. **Tool schemas**: When `task_manager` is set, `ALL_TASK_SCHEMAS` are appended to `api_tools` before each LLM call
2. **Block classification**: Tool use blocks with names in `TASK_TOOL_NAMES` are classified as `task_blocks` (not sent to MCP)
3. **Inline handling**: Each task block is processed by `task_manager.handle_tool_call()`, result appended to `inline_results`

```python
for block in task_blocks:
    result_text = await self._task_manager.handle_tool_call(
        block["name"], block["input"],
    )
    inline_results.append({
        "type": "tool_result",
        "tool_use_id": block["id"],
        "content": result_text,
    })
```

### System Prompt

`_TASK_DECOMPOSITION_DIRECTIVE` is injected into the system prompt when `task_decomposition_enabled=True` and `compact=False`. It covers:
- When to use task decomposition (3+ steps, multi-step work, user requests)
- When NOT to use it (single trivial task, conversational)
- All 4 tool descriptions with field documentation and examples

### Agent Builder

When `task_decomposition_enabled=True`, the builder creates:
- `TaskStore` at `.micro_x/tasks.db`
- `TaskManager` with `list_id=session_id` (or `"default"`)
- Both passed through `AgentComponents` → `Agent` → `TurnEngine`

### Configuration

```json
{
  "TaskDecompositionEnabled": true
}
```

Flows through: `config-base.json` → `AppConfig.task_decomposition_enabled` → `AgentConfig.task_decomposition_enabled` → `bootstrap.py` / `agent_builder.py`.

## TUI Integration

### TaskPanel Widget

`tui/widgets/task_panel.py` — a `VerticalScroll` widget (same pattern as `ToolPanel`):

| Status | Icon | Color |
|--------|------|-------|
| pending | `○` | dim |
| in_progress | `●` | yellow |
| completed | `✓` | green |

Display rules:
- Max 10 tasks visible
- Internal tasks filtered
- Completed blockers filtered from `blocked_by` display
- Owner shown in dim parentheses
- Active blockers shown in red
- Hidden by default, auto-shows when tasks exist

### Update Flow

```
TaskManager._handle_create/update()
    → _notify_mutation()
        → MutationListener (registered by TUI)
            → store.list_tasks()
                → call_from_thread(task_panel.update_tasks, tasks)
```

### Slash Command

`/tasks` toggles the task panel visibility. Handled as a TUI-local command — intercepted in `_submit_slash_command()` before reaching the agent.

## Sequence Diagram

### Single-Agent Task Decomposition

```
User: "Add auth with JWT, tests, and docs"
    │
    ▼
Agent (LLM)
    │── task_create {subject: "Set up JWT deps", ...}           → #1
    │── task_create {subject: "Implement auth middleware", ...}  → #2
    │── task_create {subject: "Write tests", ...}               → #3
    │── task_update {taskId: "2", addBlockedBy: ["1"]}
    │── task_update {taskId: "3", addBlockedBy: ["2"]}
    │── task_update {taskId: "1", status: "in_progress"}
    │   [does the work]
    │── task_update {taskId: "1", status: "completed"}
    │── task_list {}
    │   → "#1 [completed] Set up JWT deps\n#2 [pending] Auth middleware\n#3 [pending] Tests [blocked by #2]"
    │   (blocker #1 filtered because completed)
    │── task_update {taskId: "2", status: "in_progress"}
    │   [continues...]
```

### Hook Rollback

```
task_create {subject: "Deploy to prod"}
    │
    ├─ store.create_task() → Task #5
    ├─ _run_hooks(_created_hooks, "5", "Deploy to prod", ...)
    │   └─ hook returns "Deployment freeze until Thursday"
    ├─ store.delete_task("5")  ← rollback
    └─ return "Task creation blocked: Deployment freeze until Thursday"
```

## Test Coverage

76 tests across 3 files:

| File | Tests | Coverage |
|------|-------|----------|
| `test_task_store.py` | 24 | CRUD, auto-increment, HWM, deps, cascade delete, reset, internal filtering, list isolation, parallel creation |
| `test_task_manager.py` | 31 | All 4 handlers, formatting, not-found non-error, dependency filtering, hooks (blocking/non-blocking/rollback/multiple), auto-owner |
| `test_task_claiming.py` | 21 | Claim checks (5 reasons), same-agent re-claim, busy check, agent statuses, unassign on exit, auto-owner with/without agent_id |
