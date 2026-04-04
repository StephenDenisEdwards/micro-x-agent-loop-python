# Task Decomposition — Manual Test Plan

Step-by-step walkthrough of every task decomposition feature (Phases 1-6: data model, storage, agent integration, lifecycle hooks, multi-agent coordination, TUI display). Run these from the project root directory using the interactive REPL.

> **Prerequisites**
> - Python 3.11+ with the agent installed (`pip install -e .`)
> - A working `config.json` with at least one LLM provider configured
> - `.env` with valid API keys
> - `TaskDecompositionEnabled` set to `true` in your config (see section 1)

> **Cost awareness**
> Task decomposition tests make real LLM API calls. The pseudo-tools themselves (`task_create`, `task_update`, `task_list`, `task_get`) are handled inline — no MCP round-trip — but the LLM still generates tool-call tokens. Budget approximately $0.05-$0.30 for a full test run depending on models and prompt complexity.

---

## 1. Configuration

### Test 1.1: Enable task decomposition

Add the following to your `config.json` (or the file it points to via `ConfigFile`):

```json
{
  "TaskDecompositionEnabled": true
}
```

Start the agent:
```bash
python -m micro_x_agent_loop
```

**Expected:**
- Agent starts normally with no errors
- The system prompt includes the "Task Decomposition" directive (not directly visible, but the LLM will have access to `task_create`, `task_update`, `task_list`, `task_get`)
- SQLite database created at `.micro_x/tasks.db`

### Test 1.2: Task decomposition disabled (default)

Ensure `TaskDecompositionEnabled` is `false` or absent in config.

```bash
python -m micro_x_agent_loop
```

**Expected:**
- Agent starts normally
- The four task tools are **not** available to the LLM
- No `.micro_x/tasks.db` file is created (or not opened)
- Prompts that would benefit from decomposition are handled directly without task tracking

### Test 1.3: Verify config inheritance

If using a base config with `"Base": "config-base.json"`:

```json
{
  "Base": "config-base.json",
  "TaskDecompositionEnabled": true
}
```

**Expected:** The override applies correctly — task tools are available despite the base config having `TaskDecompositionEnabled: false`.

---

## 2. Basic Task CRUD (Single-Agent Workflow)

Start the agent with task decomposition enabled (test 1.1 config).

### Test 2.1: Agent creates tasks from a multi-step request

```
you> Build a Python CLI tool that reads a CSV file, validates the data, and writes a summary report. Break this into tasks first.
```

**Expected:**
- The agent calls `task_create` multiple times (3+ tasks)
- Each task has a clear imperative subject (e.g., "Implement CSV file reader")
- Each task has a description with requirements
- Terminal shows tool execution indicators for each `task_create` call
- Agent confirms the task list was created

### Test 2.2: Agent lists tasks

```
you> Show me the current task list.
```

**Expected:**
- The agent calls `task_list`
- Output shows all tasks with format: `#1 [pending] Subject`
- All tasks are in `pending` status initially
- No owners assigned yet

### Test 2.3: Agent works through tasks in order

```
you> Start working on the first task.
```

**Expected:**
- Agent calls `task_update` with `{"taskId": "1", "status": "in_progress"}` before starting work
- Agent performs the actual implementation
- Agent calls `task_update` with `{"taskId": "1", "status": "completed"}` after finishing
- Agent calls `task_list` to check what to do next
- Agent proceeds to the next pending task

### Test 2.4: Agent retrieves task details

```
you> Show me the full details of task #2.
```

**Expected:**
- Agent calls `task_get` with `{"taskId": "2"}`
- Output includes: subject, status, description, dependencies (if any), owner (if any)

### Test 2.5: Delete a task

```
you> Remove task #3 — we don't need that any more.
```

**Expected:**
- Agent calls `task_update` with `{"taskId": "3", "status": "deleted"}`
- Task is permanently removed
- Subsequent `task_list` no longer shows task #3
- Task ID #3 is never reused (high-water-mark prevents reuse)

---

## 3. Task Dependencies

### Test 3.1: Establish dependencies after creation

```
you> I need three tasks: "Set up database schema", "Implement API endpoints", and "Write integration tests". The API depends on the schema, and tests depend on the API.
```

**Expected:**
- Agent creates 3 tasks
- Agent calls `task_update` with `addBlockedBy` to establish:
  - Task #2 (API) blocked by task #1 (schema)
  - Task #3 (tests) blocked by task #2 (API)
- `task_list` shows: `#2 [pending] Implement API endpoints [blocked by #1]` and `#3 [pending] Write integration tests [blocked by #2]`

### Test 3.2: Completed blockers are filtered from display

After completing task #1 from test 3.1:

```
you> Mark the database schema task as completed.
```

**Expected:**
- Agent marks task #1 as completed
- `task_list` shows task #2 **without** `[blocked by #1]` (completed blockers are filtered)
- Task #3 still shows `[blocked by #2]` (since #2 is not yet completed)

### Test 3.3: Bidirectional dependency edges

After test 3.1, inspect task details:

```
you> Show me the details of task #1.
```

**Expected:**
- Task #1 shows `Blocks: #2` (forward reference)
- Task #2 shows `Blocked by: #1` and `Blocks: #3`
- Task #3 shows `Blocked by: #2`

### Test 3.4: Cascade delete cleans up dependencies

```
you> Delete task #2.
```

**Expected:**
- Task #2 is deleted
- Task #3's `blocked_by` list no longer references #2 (dependency edges cascade-deleted)
- Task #1's `blocks` list no longer references #2

---

## 4. Task ID Management

### Test 4.1: IDs are sequential and never reused

```
you> Create three tasks: "Task A", "Task B", "Task C". Then delete task #2. Then create "Task D".
```

**Expected:**
- Initial tasks: #1, #2, #3
- After deleting #2: tasks #1, #3
- New task gets ID #4 (not #2) — the high-water-mark prevents ID reuse
- `task_list` shows #1, #3, #4

### Test 4.2: Reset preserves high-water-mark

If a `/session new` or equivalent resets the task list within the same list_id scope:

**Expected:**
- All tasks are cleared
- The next task created still gets the next sequential ID (not #1)
- This prevents confusion when tasks from a prior context are referenced in conversation history

---

## 5. Error Handling

All errors return normal content (not error-typed responses) to avoid cancelling sibling tool calls in parallel execution.

### Test 5.1: Update non-existent task

```
you> Mark task #999 as completed.
```

**Expected:**
- Agent calls `task_update` with `{"taskId": "999", "status": "completed"}`
- Returns: `"Task #999 not found"`
- No crash or error-type response
- Agent handles gracefully and informs user

### Test 5.2: Get non-existent task

```
you> Show me the details of task #999.
```

**Expected:**
- Agent calls `task_get` with `{"taskId": "999"}`
- Returns: `"Task not found"`
- No crash

### Test 5.3: Create task without required fields

This is an LLM edge case — the model might send incomplete input. Verifiable via unit tests:

```bash
python -m pytest tests/test_task_manager.py -v -k "required"
```

**Expected:** Returns `"Error: subject and description are required."`

### Test 5.4: Update with no fields

```
you> Update task #1 but don't change anything.
```

**Expected:**
- If the agent sends `task_update` with only `taskId` and no other fields
- Returns: `"Task #1 unchanged (no fields provided)"`

### Test 5.5: Empty task list

```
you> List all tasks.
```

(When no tasks exist)

**Expected:**
- Returns: `"No tasks."`

---

## 6. Lifecycle Hooks

Hooks are programmatic (not user-invokable). Test via unit tests:

```bash
python -m pytest tests/test_task_manager.py -v -k "hook"
```

### Test 6.1: Created hook — blocking error rolls back

**Expected:** (verified by unit test)
- A `taskCreatedHook` that returns an error string causes the task to be deleted
- Result: `"Task creation blocked: <error message>"`
- The task does not appear in subsequent `task_list`

### Test 6.2: Completed hook — blocking error rejects status change

**Expected:** (verified by unit test)
- A `taskCompletedHook` that returns an error string prevents the status change
- Result: `"Task #N completion blocked: <error message>"`
- Task remains `in_progress`

### Test 6.3: Non-blocking hooks execute successfully

**Expected:** (verified by unit test)
- Hooks that return `None` allow the operation to proceed normally
- Multiple hooks execute in order; first blocking error short-circuits

---

## 7. Multi-Agent Coordination (Phase 5)

These features support future multi-agent scenarios. Test via unit tests:

```bash
python -m pytest tests/test_task_claiming.py -v
```

### Test 7.1: Atomic task claiming — 5 safety checks

**Expected:** (verified by 21 unit tests)

| Claim scenario | Expected result |
|---|---|
| Task doesn't exist | `reason: "task_not_found"` |
| Task already completed | `reason: "already_resolved"` |
| Task owned by different agent | `reason: "already_claimed"` |
| Task has unresolved blockers | `reason: "blocked"`, `blocked_by_tasks` populated |
| Agent already owns in-progress tasks | `reason: "agent_busy"`, `busy_with_tasks` populated |
| Same agent re-claims own task | `success: True` (allowed) |
| All checks pass | `success: True`, owner set, status set to `in_progress` |

### Test 7.2: Auto-owner assignment

Start the agent and give it a task:

```
you> Create a task "Test auto-owner" and start working on it.
```

**Expected:**
- When the agent marks the task as `in_progress`, the owner is automatically set to the agent's ID (if `agent_id` is configured on the TaskManager)
- `task_get` shows the owner field populated
- This only happens if no explicit `owner` is provided in the update and the task has no existing owner

### Test 7.3: Agent status tracking

**Expected:** (verified by unit tests)
- `get_agent_statuses()` returns `"busy"` for agents owning non-completed tasks
- Returns `"idle"` for agents with no active tasks

### Test 7.4: Unassign on agent exit

**Expected:** (verified by unit tests)
- `unassign_agent_tasks()` resets all non-completed tasks owned by an agent to `pending` with `owner=None`
- Returns the list of affected tasks and a notification message

---

## 8. TUI Display (Phase 6)

Start the agent in TUI mode with task decomposition enabled:

```bash
python -m micro_x_agent_loop --tui
```

### Test 8.1: Task panel auto-shows when tasks exist

```
you> Break this into tasks: implement login, implement logout, write tests.
```

**Expected:**
- The TaskPanel widget appears automatically when the first task is created
- Panel was hidden (`display: none`) before any tasks existed
- Panel shows all tasks with status icons

### Test 8.2: Status icons render correctly

**Expected:**
- `[dim]○[/dim]` — pending tasks (dim circle)
- `[yellow]●[/yellow]` — in_progress tasks (yellow filled circle)
- `[green]✓[/green]` — completed tasks (green check mark)

### Test 8.3: Task metadata in panel

**Expected:**
- Owner shown in dim parentheses after the subject: `● Implement login (agent-1)`
- Active blockers shown in red: `[blocked by #1]`
- Completed blockers are **not** shown

### Test 8.4: Live updates via mutation listener

```
you> Start working on task #1.
```

**Expected:**
- TaskPanel updates immediately when the agent marks #1 as `in_progress`
- No manual refresh needed — the mutation listener fires `call_from_thread()` to update the TUI
- Status icon changes from `○` to `●` in real time

### Test 8.5: Maximum visible tasks

Create more than 10 tasks:

```
you> Create 12 tasks numbered "Task 1" through "Task 12" with descriptions.
```

**Expected:**
- TaskPanel displays at most 10 tasks (`_MAX_VISIBLE_TASKS`)
- Remaining tasks are accessible via `task_list` but not shown in the panel

### Test 8.6: Toggle visibility with /tasks

```
you> /tasks
```

**Expected:**
- The `/tasks` command toggles the TaskPanel visibility
- First invocation hides the panel; second invocation shows it again
- This is handled locally by the TUI (not sent to the agent)

---

## 9. System Prompt Integration

### Test 9.1: Directive included when enabled

With `TaskDecompositionEnabled: true`, start the agent and ask:

```
you> What tools do you have for task management?
```

**Expected:**
- Agent describes `task_create`, `task_update`, `task_list`, `task_get`
- Agent understands when to use them (complex multi-step tasks, 3+ steps)
- Agent knows to skip decomposition for trivial tasks

### Test 9.2: Directive omitted when disabled

With `TaskDecompositionEnabled: false`:

```
you> What tools do you have for task management?
```

**Expected:**
- Agent does **not** mention task_create/update/list/get
- No task decomposition capability available

### Test 9.3: Proactive decomposition for complex requests

```
you> Refactor the authentication module to use JWT tokens, update all tests, update the API docs, and add migration scripts for existing sessions.
```

**Expected:**
- Agent proactively creates tasks without being explicitly asked (the directive says "use this tool proactively")
- Tasks are created before the agent starts any implementation
- Agent establishes dependencies between related tasks
- Agent works through tasks in ID order (lowest first)

### Test 9.4: No decomposition for simple requests

```
you> What time is it?
```

**Expected:**
- Agent does **not** create tasks — this is purely conversational
- Directive says to skip decomposition for trivial/single-step/conversational tasks

---

## 10. Turn Engine Integration

### Test 10.1: Task tools handled inline (not via MCP)

Run any task operation and observe:

**Expected:**
- Task tool calls are classified separately from regular tool blocks
- They execute inline within the turn engine (no MCP server round-trip)
- Results are injected directly as `tool_result` content blocks
- Regular MCP tool calls (if any) execute in parallel without interference

### Test 10.2: Task tools and MCP tools in same response

```
you> Create a task "Read the README" and also read the file README.md.
```

**Expected:**
- The LLM may emit both `task_create` and a filesystem read tool in the same response
- `task_create` is handled inline; filesystem read goes through MCP
- Both results return correctly — no interference
- Task errors do NOT cancel the filesystem read (non-error-typed responses)

---

## 11. Persistence and Session Isolation

### Test 11.1: Tasks persist across turns

Create tasks in one turn, verify they exist in the next:

```
you> Create three tasks: "Alpha", "Bravo", "Charlie".
you> List all tasks.
```

**Expected:**
- Tasks created in the first turn appear in the second turn's `task_list`
- SQLite database at `.micro_x/tasks.db` contains the rows

### Test 11.2: Tasks scoped to session (list isolation)

Start two separate sessions:

```bash
# Session 1
python -m micro_x_agent_loop --session test-session-1
# Create tasks...

# Session 2
python -m micro_x_agent_loop --session test-session-2
```

**Expected:**
- Tasks created in session 1 are **not** visible in session 2
- Each session uses its own `list_id` (the session ID)
- `task_list` in session 2 returns `"No tasks."`

### Test 11.3: Tasks survive agent restart

```bash
python -m micro_x_agent_loop --session task-persist-test
# Create tasks, then exit

python -m micro_x_agent_loop --session task-persist-test
# List tasks
```

**Expected:**
- Tasks from the prior run are still present (SQLite persistence)
- IDs continue from where they left off (high-water-mark preserved)

---

## 12. End-to-End Complex Scenario

### Test 12.1: Full lifecycle with dependencies

```
you> I need to add a caching layer to the application. This involves:
1. Design the cache interface
2. Implement Redis adapter
3. Implement in-memory adapter
4. Add cache middleware to the API
5. Write unit tests for both adapters
6. Write integration tests for the middleware
7. Update the configuration docs

Please plan and execute this work using tasks.
```

**Expected:**
- Agent creates 7 tasks with clear subjects and descriptions
- Agent establishes dependencies:
  - Adapters (#2, #3) blocked by interface design (#1)
  - Middleware (#4) blocked by at least one adapter
  - Unit tests (#5) blocked by adapters
  - Integration tests (#6) blocked by middleware
  - Docs (#7) blocked by middleware
- Agent marks each task `in_progress` before starting, `completed` after finishing
- Agent calls `task_list` between tasks to find next available work
- Agent works in ID order, respecting dependency constraints
- Final `task_list` shows all tasks as `[completed]`

### Test 12.2: Agent discovers follow-up work

During test 12.1, if the agent encounters unexpected issues:

**Expected:**
- Agent creates new tasks for follow-up work discovered during implementation
- New tasks get the next sequential IDs
- Agent does **not** mark a task as completed if implementation is partial or tests are failing

---

## 13. Unit Test Verification

Run the full task decomposition test suite:

```bash
python -m pytest tests/test_task_store.py tests/test_task_manager.py tests/test_task_claiming.py -v
```

**Expected:** All 76 tests pass:
- `test_task_store.py` — 24 tests (CRUD, HWM, dependencies, cascade, isolation)
- `test_task_manager.py` — 31 tests (handlers, formatting, errors, hooks, auto-owner)
- `test_task_claiming.py` — 21 tests (claim checks, agent status, unassign)

---

## Cleanup

After testing, you may want to:
- Reset `TaskDecompositionEnabled` to `false` in config if not needed
- Delete `.micro_x/tasks.db` to clear all task data
- Remove test sessions from `.micro_x/memory.db` if `MemoryEnabled` was on

---

## Test Summary Checklist

| # | Feature | Status |
|---|---------|--------|
| 1.1 | Enable task decomposition | |
| 1.2 | Task decomposition disabled (default) | |
| 1.3 | Config inheritance | |
| 2.1 | Agent creates tasks from multi-step request | |
| 2.2 | Agent lists tasks | |
| 2.3 | Agent works through tasks in order | |
| 2.4 | Agent retrieves task details | |
| 2.5 | Delete a task | |
| 3.1 | Establish dependencies after creation | |
| 3.2 | Completed blockers filtered from display | |
| 3.3 | Bidirectional dependency edges | |
| 3.4 | Cascade delete cleans up dependencies | |
| 4.1 | IDs sequential and never reused | |
| 4.2 | Reset preserves high-water-mark | |
| 5.1 | Update non-existent task | |
| 5.2 | Get non-existent task | |
| 5.3 | Create without required fields (unit test) | |
| 5.4 | Update with no fields | |
| 5.5 | Empty task list | |
| 6.1 | Created hook — blocking rollback (unit test) | |
| 6.2 | Completed hook — blocking rejection (unit test) | |
| 6.3 | Non-blocking hooks (unit test) | |
| 7.1 | Atomic claiming — 5 safety checks (unit test) | |
| 7.2 | Auto-owner assignment | |
| 7.3 | Agent status tracking (unit test) | |
| 7.4 | Unassign on agent exit (unit test) | |
| 8.1 | Task panel auto-shows | |
| 8.2 | Status icons render correctly | |
| 8.3 | Task metadata in panel | |
| 8.4 | Live updates via mutation listener | |
| 8.5 | Maximum visible tasks (10 cap) | |
| 8.6 | Toggle visibility with /tasks | |
| 9.1 | Directive included when enabled | |
| 9.2 | Directive omitted when disabled | |
| 9.3 | Proactive decomposition for complex requests | |
| 9.4 | No decomposition for simple requests | |
| 10.1 | Task tools handled inline (not MCP) | |
| 10.2 | Task tools and MCP tools in same response | |
| 11.1 | Tasks persist across turns | |
| 11.2 | Tasks scoped to session (list isolation) | |
| 11.3 | Tasks survive agent restart | |
| 12.1 | Full lifecycle with dependencies | |
| 12.2 | Agent discovers follow-up work | |
| 13 | All 76 unit tests pass | |
