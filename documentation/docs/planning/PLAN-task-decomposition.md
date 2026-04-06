# Plan: Task Decomposition System

**Status:** All 8 Phases Completed
**Date:** 2026-04-06

**Goal:** Enable the agent to break complex work into trackable, dependency-aware subtasks with progress tracking, lifecycle hooks, multi-agent coordination, real-time UI, session persistence, and parallel execution via sub-agents.

**Reference:** [`task-decomposition-implementation-guide.md`](../task-decomposition-implementation-guide.md) — the full specification (Sections 1-14) from the Claude Code reference implementation.

---

## 1. Why Task Decomposition?

When the agent tackles complex multi-step work (e.g. "add authentication with JWT, tests, and docs"), it currently has no structured way to:

- **Plan the work** — decompose into discrete steps with clear dependencies
- **Track progress** — know which steps are done, in-progress, or blocked
- **Show the user** — make the agent's plan and progress visible
- **Coordinate** — in multi-agent scenarios, prevent two agents from working on the same task

The reference implementation (Claude Code) exposes four tools — `task_create`, `task_update`, `task_list`, `task_get` — that the agent calls during its reasoning loop to decompose, track, and coordinate work. Tasks form a dependency DAG (via `blocks`/`blockedBy` edges) and progress through `pending → in_progress → completed`.

---

## 2. Implementation Tiers

From the guide (Section 1.1):

| Tier | Phases | What it adds | Status |
|------|--------|-------------|--------|
| **MVP** | 1-3 | Single-agent task decomposition with deps, storage, error handling | **Completed** |
| **Enhancement** | 4 | Lifecycle hooks (taskCreated, taskCompleted) with blocking error rollback | **Completed** |
| **Multi-Agent** | 5 | Swarm support — atomic claiming, ownership, agent status, exit cleanup | **Completed** |
| **Polish** | 6 | Real-time TUI panel, auto-hide, slash commands | **Completed** |
| **Persistence** | 7 | Session resume restores tasks, mid-session switch preserves status | **Completed** |
| **Parallelism** | 8 | Parallel task execution via concurrent sub-agents, wave-based dispatch | **Completed** |

---

## 3. Phase 1-3: MVP (Completed)

### 3.1 Data Model (Phase 1)

**Files created:**
- `src/micro_x_agent_loop/tasks/__init__.py` — package init
- `src/micro_x_agent_loop/tasks/models.py` — `Task` dataclass, `TaskStatus` enum

```python
class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

@dataclass
class Task:
    id: str                          # Auto-incrementing, string-typed for display
    subject: str                     # Imperative title
    description: str                 # Detailed requirements
    status: TaskStatus
    blocks: list[str]                # IDs this task blocks
    blocked_by: list[str]            # IDs blocking this task
    active_form: str | None          # Present-continuous spinner text
    owner: str | None                # Agent name (multi-agent)
    metadata: dict[str, Any] | None  # Extensibility
```

### 3.2 Storage Layer (Phase 1)

**File:** `src/micro_x_agent_loop/tasks/store.py`

**Design decision:** The guide specifies file-based JSON with file locking. We use **SQLite** instead — consistent with codebase conventions (memory.db, broker.db), simpler concurrency via `BEGIN IMMEDIATE` transactions, no additional dependencies.

**Database:** `.micro_x/tasks.db` (separate from memory.db)

**Schema:**
- `tasks` — id, list_id, subject, description, status, active_form, owner, metadata_json, timestamps
- `task_dependencies` — from_task_id, to_task_id, list_id (bidirectional edges)
- `high_water_marks` — list_id, value (prevents ID reuse after deletion)

**Methods** (per guide Section 4.4):
- `create_task()` — in transaction: read HWM, compute next ID, insert, update HWM
- `get_task()` / `list_tasks()` — with dependency population from task_dependencies
- `update_task()` — field-level updates with metadata merge (null values delete keys)
- `delete_task()` — cascading: removes all dependency edges, updates HWM
- `block_task()` — bidirectional: inserts (from→to) edge
- `reset_task_list()` — preserves HWM, deletes all tasks + deps

**Concurrency:** `isolation_level=None` + `BEGIN IMMEDIATE` for write serialization. Cross-process safety via SQLite file-level locking.

### 3.3 Tool Schemas (Phase 2)

**File:** `src/micro_x_agent_loop/tasks/schemas.py`

Four tool schemas as dicts (same pattern as `SPAWN_SUBAGENT_SCHEMA` in `sub_agent.py`):
- `TASK_CREATE_SCHEMA` — input: `{subject, description, activeForm?, metadata?}`
- `TASK_UPDATE_SCHEMA` — input: `{taskId, subject?, description?, activeForm?, status?, owner?, addBlocks?, addBlockedBy?, metadata?}`
- `TASK_LIST_SCHEMA` — input: `{}`
- `TASK_GET_SCHEMA` — input: `{taskId}`

Helpers: `TASK_TOOL_NAMES` frozenset, `is_task_tool()`, `ALL_TASK_SCHEMAS` list.

### 3.4 TaskManager (Phase 2)

**File:** `src/micro_x_agent_loop/tasks/manager.py`

Orchestrates tool calls, owns `TaskStore`. Routes via `match tool_name`.

**Result formatting** (per guide Sections 5.1-5.4):
- Create: `"Task #1 created successfully: Fix authentication bug"`
- Update: `"Updated task #1 status, owner"` / `"Updated task #1 deleted"`
- List: `"#1 [completed] Set up schema\n#2 [in_progress] Auth (alice)\n#3 [pending] Tests [blocked by #2]"`
- Get: `"Task #2: Auth\nStatus: in_progress\nDescription: ...\nBlocked by: #1\nBlocks: #3, #5"`

**Error handling** (per guide Section 7.1): "not found" returns descriptive string as normal `tool_result` content — never `is_error: True`, never an exception. This avoids sibling tool cancellation in parallel execution.

**Dependency filtering** (per guide Section 6.3): `blocked_by` in list results only shows non-completed blockers.

### 3.5 Agent Integration (Phase 3)

**Modified files:**
- `agent_config.py` — added `task_decomposition_enabled: bool = False`
- `app_config.py` — reads `TaskDecompositionEnabled` from config JSON
- `config-base.json` — added `"TaskDecompositionEnabled": false`
- `bootstrap.py` — passes flag through to AgentConfig
- `system_prompt.py` — added `_TASK_DECOMPOSITION_DIRECTIVE` (adapted from guide Section 11), injected when `task_decomposition_enabled=True` and `compact=False`
- `agent_builder.py` — creates `TaskStore` + `TaskManager` when enabled, added `task_manager` to `AgentComponents`
- `agent.py` — stores `task_manager`, passes to `TurnEngine`
- `turn_engine.py` — accepts `task_manager`, appends `ALL_TASK_SCHEMAS` to api_tools, classifies `task_blocks`, handles inline
- `server/agent_manager.py` — passes flag through for API server path

**Integration pattern:** Task tools are handled as **pseudo-tools** inline in `TurnEngine.run()`, same as `ask_user`, `tool_search`, and `spawn_subagent`. No MCP execution needed.

### 3.6 Tests

- `tests/test_task_store.py` — 24 tests covering CRUD, HWM, bidirectional deps, cascading delete, reset, concurrency, list isolation, internal task filtering
- `tests/test_task_manager.py` — 23 tests covering all 4 handlers, formatting, non-error handling, dependency filtering, delete cascade, ID non-reuse

All 47 new tests pass. Full suite: 1519 tests pass, zero regressions.

---

## 4. Phase 4: Lifecycle Hooks (Completed)

**Guide reference:** Section 8

**Goal:** Allow external systems to react to task creation and completion, with the ability to block (roll back) operations.

### 4.1 Implementation

**File modified:** `tasks/manager.py` only (no new files)

Hook type alias:
```python
TaskHook = Callable[[str, str, str], Awaitable[str | None]]
```

Hooks are async functions receiving `(task_id, subject, description)` and returning an optional blocking error string. Registration via `register_created_hook()` and `register_completed_hook()`.

Execution via `_run_hooks()` — runs hooks in order, returns the first blocking error (short-circuits). On blocking error:
- **TaskCreate**: the just-created task is deleted (rollback), returns `"Task creation blocked: <error>"`
- **TaskUpdate (→completed)**: hooks run *before* applying the status change, returns `"Task #N completion blocked: <error>"`

Also added `MutationListener` callback system (`register_mutation_listener()`, `_notify_mutation()`) for TUI integration (Phase 6). Listener errors are silenced per guide Section 7.6.

### 4.2 Tests

8 tests added to `tests/test_task_manager.py` (`TestTaskManagerHooks` class):
- Non-blocking hook: task creation/completion succeeds, hook receives correct args
- Blocking hook: task creation rolls back (task deleted), completion rejected (status unchanged)
- Multiple hooks: first blocking error wins, later hooks don't execute
- HWM prevents ID reuse after rollback
- Completed hooks not triggered for non-completed status changes
- No hooks registered: create and complete work normally

---

## 5. Phase 5: Multi-Agent Coordination (Completed)

**Guide reference:** Section 9

**Goal:** Enable multiple agents (via sub-agents or swarm) to claim, own, and coordinate tasks atomically.

### 5.1 Data Model Additions

Added to `tasks/models.py`:

```python
@dataclass
class ClaimResult:
    success: bool
    reason: str | None = None  # task_not_found, already_claimed, already_resolved, blocked, agent_busy
    task: Task | None = None
    busy_with_tasks: list[str] | None = None
    blocked_by_tasks: list[str] | None = None

@dataclass
class AgentStatus:
    agent_id: str
    name: str
    status: str  # "idle" | "busy"
    current_tasks: list[str]
```

### 5.2 TaskStore Methods

Added to `tasks/store.py`:

**`claim_task(list_id, task_id, agent_id, check_busy=False)`** — Atomic claim inside `BEGIN IMMEDIATE` transaction. Checks in order (guide Section 9.1):
1. Task exists → `task_not_found`
2. Not already completed → `already_resolved`
3. Not claimed by another agent (same-agent re-claim OK) → `already_claimed`
4. No unresolved blockers → `blocked` (with `blocked_by_tasks`)
5. (Optional) Agent not busy with other open tasks → `agent_busy` (with `busy_with_tasks`)

On success: sets `owner` and `status=in_progress`.

**`get_agent_statuses(list_id, agent_ids)`** — Returns idle/busy per agent. Busy = owns at least one non-completed task.

**`unassign_agent_tasks(list_id, agent_id, reason)`** — Resets all non-completed tasks owned by the agent to `pending` + `owner=None`. Returns unassigned tasks and a formatted notification message (e.g. `"alice was terminated. 2 task(s) were unassigned: #1 "Task A", #3 "Task C". Use task_list to check availability..."`).

### 5.3 TaskManager Auto-Owner

`TaskManager.__init__()` accepts optional `agent_id`. In `_handle_update()`, when status changes to `in_progress` and the task has no owner and no explicit `owner` in the input, the agent_id is auto-assigned as owner (guide Section 9.4).

### 5.4 Tests

21 tests in `tests/test_task_claiming.py` across 4 classes:

- **TestClaimTask** (10 tests): success, sets in_progress, not found, already claimed by other, same-agent re-claim OK, already completed, blocked, blocked-resolved, agent busy, busy not checked by default
- **TestAgentStatuses** (3 tests): idle agents, busy agent, completed task not busy
- **TestUnassignAgentTasks** (4 tests): resets to pending, skips completed, no tasks, only own tasks
- **TestAutoOwner** (4 tests): auto-owner on in_progress, no auto-owner without agent_id, explicit owner overrides, no auto-owner if already owned

---

## 6. Phase 6: Real-Time TUI (Completed)

**Guide reference:** Section 10

**Goal:** Show live task progress in the Textual TUI.

### 6.1 TaskPanel Widget

**File created:** `src/micro_x_agent_loop/tui/widgets/task_panel.py`

A Textual `VerticalScroll` widget rendering the current task list with Rich markup:

```
Tasks
○ #1 Set up database schema
● #2 Implement auth (alice)
✓ #3 Write tests
○ #4 Update docs [blocked by #2]
```

Display rules (per guide Section 10.2):
- Max 10 tasks (`_MAX_VISIBLE_TASKS`)
- Internal tasks (`metadata._internal`) filtered out
- Completed blockers filtered from `blockedBy` display
- Status icons: `○` pending (dim), `●` in_progress (yellow), `✓` completed (green)
- Owner shown in dim parentheses, active blockers in red
- Panel hidden by default (`display: none` in CSS), auto-shows when tasks exist

Methods:
- `update_tasks(tasks)` — replace and re-render the task list
- `set_visible(visible)` — explicitly show/hide

### 6.2 Update Mechanism

**In-process mutation callback**: `TaskManager._notify_mutation()` fires after every create, update, and delete. The TUI subscribes via `register_mutation_listener()` at construction time. The listener reads the current task list from the store and calls `TaskPanel.update_tasks()` via `call_from_thread()` for thread safety.

No file watcher or polling needed — SQLite is in-process and mutations are synchronous within the tool call.

### 6.3 Integration

**File modified:** `src/micro_x_agent_loop/tui/app.py`

- `TaskPanel` added to compose layout (between ChatLog and ToolPanel)
- CSS: shared `.task-panel-title` style with `.tool-panel-title`
- `/tasks` added to `_SLASH_COMMANDS` list for the command palette
- `_submit_slash_command()` intercepts `/tasks` as TUI-local (does not send to agent)
- `action_toggle_tasks()` toggles the task panel visibility
- `_on_task_mutation()` — mutation listener subscribed in `__init__`, reads task list from store, updates panel via `call_from_thread()`

### 6.4 Future Enhancements

Not implemented in this phase (can be added incrementally):
- **Auto-hide timer**: 5-second delay after all tasks complete, then reset and hide panel
- **AgentChannel extension**: `emit_task_updated()` for non-TUI channels (Terminal, Buffered, Broker)
- **`/task <id>` slash command**: show full task details in chat

---

## 7. Files Summary

### Created

| File | Phase | Purpose |
|------|-------|---------|
| `tasks/__init__.py` | 1 | Package init |
| `tasks/models.py` | 1, 5 | Task, TaskStatus, ClaimResult, AgentStatus |
| `tasks/store.py` | 1, 5 | TaskStore (SQLite CRUD, deps, HWM, claiming, agent status) |
| `tasks/schemas.py` | 2 | 4 tool schemas + helpers |
| `tasks/manager.py` | 2, 4, 5, 6 | TaskManager (routing, formatting, hooks, auto-owner, mutation listeners) |
| `tui/widgets/task_panel.py` | 6 | TaskPanel TUI widget |
| `tests/test_task_store.py` | 1 | 24 storage tests |
| `tests/test_task_manager.py` | 2, 4 | 31 manager + hook tests |
| `tests/test_task_claiming.py` | 5 | 21 multi-agent tests |

### Modified

| File | Phase | Change |
|------|-------|--------|
| `agent_config.py` | 3 | `task_decomposition_enabled` flag |
| `app_config.py` | 3 | Read `TaskDecompositionEnabled` |
| `config-base.json` | 3 | Default `false` |
| `bootstrap.py` | 3 | Pass flag through |
| `system_prompt.py` | 3 | `_TASK_DECOMPOSITION_DIRECTIVE` |
| `turn_engine.py` | 3 | Classify + handle task blocks inline |
| `agent_builder.py` | 3 | Create TaskStore + TaskManager |
| `agent.py` | 3 | Pass task_manager to TurnEngine |
| `server/agent_manager.py` | 3 | Pass flag for API path |
| `tui/app.py` | 6 | TaskPanel in layout, `/tasks` command, mutation listener |

---

## 8. Configuration

Enable via `config.json` or variant:

```json
{
  "TaskDecompositionEnabled": true
}
```

Default: `false` in `config-base.json`.

---

## Phase 7: Session Persistence (Completed)

**Date:** 2026-04-06

Tasks persist across session boundaries. When a session is resumed (via `--session`, `/session resume`, or TUI sidebar), the agent sees existing tasks and can continue.

### Changes

| File | Change |
|------|--------|
| `agent.py` | `_inject_task_summary()` — appends synthetic user message with task state on resume |
| `agent.py` | `_on_session_reset()` — updates `TaskManager._list_id` on mid-session switch |
| `tasks/manager.py` | `format_task_summary()` — returns formatted task list for injection |
| `tui/app.py` | `_refresh_task_panel()` — called on resume/new/fork to sync TUI TaskPanel |

### Key decisions

- **No automatic status reset** — `in_progress` tasks keep their status on resume. The LLM can evaluate whether to continue or restart. Resetting would cause data loss when switching between sessions.
- **Injected as user message** — the task summary is appended as a synthetic `user` role message so it appears naturally in the conversation and the LLM responds to it.
- **TaskPanel refresh on switch** — all three TUI session operations (resume, new, fork) call `_refresh_task_panel()` to update the sidebar.

---

## Phase 8: Parallel Execution via Sub-Agents (Completed)

**Date:** 2026-04-06

Independent tasks execute concurrently using the existing sub-agent infrastructure. No architecture changes — this is purely a prompt directive update.

### Changes

| File | Change |
|------|--------|
| `system_prompt.py` | Extended `_TASK_DECOMPOSITION_DIRECTIVE` with "Parallel Execution via Sub-Agents" section |

### How it works

The directive guides the LLM through wave-based parallel execution:

1. **Decompose** — create all tasks with dependency edges
2. **Identify** — call `task_list`, find all unblocked pending tasks
3. **Dispatch** — spawn concurrent sub-agents (one per independent task) in a single turn
4. **Collect** — mark tasks complete as sub-agents return
5. **Next wave** — check for newly unblocked tasks, repeat
6. **Synthesize** — combine results once all tasks are complete

Sub-agent type selection:
- `explore` for research/read-only tasks (cheap, Haiku)
- `general` for coding/file-writing tasks (same model, full tools)
- `summarize` for pure text transformation (cheapest, no tools)

### Why prompt-only

The dependency DAG (`TaskStore`), concurrent sub-agent execution (`SubAgentRunner` via `asyncio.gather`), and task status tracking (`TaskManager`) already exist. The missing piece was telling the LLM to use them together. No new code paths, no shared task state between agents — the parent orchestrates, sub-agents execute, the parent updates status.

---

## 9. Testing Strategy

### Automated
- **76 task-specific tests** across 3 test files:
  - `test_task_store.py` — 24 tests (CRUD, HWM, deps, cascade, reset, concurrency, isolation)
  - `test_task_manager.py` — 31 tests (4 handlers, formatting, errors, hooks, rollback)
  - `test_task_claiming.py` — 21 tests (claim checks, agent status, unassign, auto-owner)
- **Full suite: 1550 tests passing**, zero regressions
- Covers all guide integration test scenarios (Sections 13.1-13.6)

### Manual verification
1. Set `"TaskDecompositionEnabled": true` in config
2. Start agent: `python -m micro_x_agent_loop`
3. Give a complex multi-step task (e.g., "Add user authentication with JWT, tests, and documentation")
4. Verify: agent creates tasks, tracks progress, marks completed
5. Verify: task list shows in responses with correct formatting
6. Verify: dependencies are respected (blocked tasks not started early)
7. TUI mode (`--tui`): verify TaskPanel appears and updates live, `/tasks` toggles visibility
