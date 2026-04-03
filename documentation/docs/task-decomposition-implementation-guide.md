# Task Decomposition Feature: Implementation Guide

This document provides a complete specification for adding a task decomposition system to an AI agent. The system enables the agent to break complex work into trackable, dependency-aware subtasks, track progress, and coordinate work across multiple agents.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Integration Contract](#2-integration-contract)
3. [Data Model](#3-data-model)
4. [Storage Layer](#4-storage-layer)
5. [Tool Definitions](#5-tool-definitions)
6. [Dependency Management](#6-dependency-management)
7. [Error Handling](#7-error-handling)
8. [Lifecycle Hooks](#8-lifecycle-hooks)
9. [Multi-Agent Coordination](#9-multi-agent-coordination)
10. [Real-Time UI](#10-real-time-ui)
11. [Agent Prompts (Verbatim)](#11-agent-prompts-verbatim)
12. [End-to-End Flow](#12-end-to-end-flow)
13. [Integration Test Scenarios](#13-integration-test-scenarios)
14. [Implementation Checklist](#14-implementation-checklist)
15. [Appendices](#appendix-a-task-file-example) — Task file example, directory layout, constants, where to look

---

## 1. Overview

The task decomposition system gives an AI agent the ability to:

- **Decompose** complex user requests into discrete, trackable subtasks
- **Track** each subtask through a `pending -> in_progress -> completed` lifecycle
- **Model dependencies** between tasks via `blocks`/`blockedBy` relationships (forming a DAG)
- **Coordinate** work across multiple agents in a swarm, with atomic task claiming and ownership
- **Visualize** progress to the user via a real-time terminal UI
- **Extend** behavior via lifecycle hooks that fire on task creation and completion

The system is exposed to the agent as four tools: **TaskCreate**, **TaskUpdate**, **TaskList**, and **TaskGet**. The agent calls these tools during its reasoning loop, the same way it calls file-editing or shell tools.

The reference implementation is in this codebase. See [Appendix D](#appendix-d-where-to-look) for a map of which files implement which concepts.

### 1.1 MVP vs Optional

Not everything in this document is required for a working system. The minimum viable implementation is:

| Tier | Sections | What it gets you |
|------|----------|-----------------|
| **MVP** | 3 (Data Model), 4 (Storage), 5 (Tools), 6 (Dependencies), 7 (Error Handling), 11 (Prompts) | A single agent that can decompose work into tasks, track progress, and model dependencies. Fully functional for solo use. |
| **Enhancement** | 8 (Hooks) | Extensibility — external systems can react to task creation/completion. Skip if you don't need plugin points yet. |
| **Multi-Agent** | 9 (Multi-Agent Coordination) | Swarm support — multiple agents claiming, coordinating, and recovering from failures. Skip if single-agent only. |
| **Polish** | 10 (Real-Time UI) | Live terminal display of task progress. Skip if your agent has no persistent UI, or defer until core works. |

The integration contract (Section 2) and error handling (Section 7) apply at every tier.

---

## 2. Integration Contract

This section defines what the host agent must provide for the task system to plug in. If your agent doesn't have these capabilities, you'll need to build or adapt them.

### 2.1 Tool Registration

The agent must support a **tool registry** where each tool declares:

- **Name**: A unique string identifier (e.g. `"task_create"`)
- **Input schema**: JSON Schema or equivalent for parameter validation
- **Output schema**: JSON Schema for the structured return value
- **Prompt**: System-level instructions injected into the agent's context explaining when and how to use the tool
- **Call handler**: An async function `(input, context) -> { data }` that executes the tool logic
- **Result formatter**: A function that converts the structured output into a human-readable string for the agent's conversation (the `mapToolResultToToolResultBlockParam` pattern)

The reference implementation uses `buildTool({ ... })` — see any `Task*Tool.ts` file for the pattern.

### 2.2 Tool Result Injection

When a tool returns, its result must be injected back into the agent's conversation as a `tool_result` content block. The result formatter controls what the agent "sees." This is how the agent knows a task was created successfully, or that an update failed.

Critical design choice: **non-fatal errors (like "task not found") must be returned as normal `tool_result` content, not as error responses.** Error-typed results can trigger sibling tool cancellation in parallel execution, which would abort other in-flight tool calls unnecessarily.

### 2.3 Application State

The tool implementations need a shared state object (called `AppState` in the reference) with at minimum:

- **`expandedView`**: A string controlling which UI panel is visible. TaskCreate and TaskUpdate set this to `'tasks'` to auto-show the task list.
- **`setAppState(updater)`**: A function that accepts a `(prev) => next` updater for atomic state transitions.

If your agent has no UI, you can stub `setAppState` as a no-op — the task system still works without it.

### 2.4 Tool Execution Context

Each tool's `call()` receives a context object that should include:

- **`setAppState`**: For UI state management (see above)
- **`abortController`**: For cancellation support (passed to hooks)
- **`agentId`**: Identifies which agent is calling (used for swarm features)

### 2.5 Deferred / Lazy Loading

In the reference implementation, task tools are registered as **deferred** (`shouldDefer: true`), meaning they aren't included in every API call. They're loaded into the agent's tool list on demand. This is an optimization — if your agent always includes all tools, you can skip this.

### 2.6 Concurrency Model

Task tools are marked **concurrency-safe** (`isConcurrencySafe: true`), meaning the agent runtime can execute multiple task tool calls in parallel (e.g. creating several tasks at once). File locking in the storage layer guarantees correctness. If your agent runtime doesn't support parallel tool execution, this is a no-op.

---

## 3. Data Model

### 3.1 Task Schema

Each task is a JSON object with the following shape:

```typescript
type TaskStatus = 'pending' | 'in_progress' | 'completed'

type Task = {
  id: string                          // Unique numeric ID (auto-incrementing, string-typed)
  subject: string                     // Brief, actionable title in imperative form
  description: string                 // Detailed description of what needs to be done
  activeForm?: string                 // Present-continuous label for spinner UI (e.g. "Running tests")
  owner?: string                      // Agent name/ID (for multi-agent scenarios)
  status: TaskStatus                  // Current lifecycle state
  blocks: string[]                    // IDs of tasks that cannot start until this one completes
  blockedBy: string[]                 // IDs of tasks that must complete before this one can start
  metadata?: Record<string, unknown>  // Arbitrary key-value data
}
```

### 3.2 Design Rationale

| Field | Purpose |
|-------|---------|
| `id` | String-typed numeric IDs for human readability (`#1`, `#2`). Auto-incremented with a high-water-mark file to prevent reuse after deletion. |
| `subject` | Short imperative title (e.g. "Fix authentication bug in login flow"). Displayed in list views and spinner. |
| `description` | Detailed requirements and context. Must contain enough information for another agent to complete the task without additional context. |
| `activeForm` | Optional present-continuous phrasing (e.g. "Fixing authentication bug") for a better spinner UX. Falls back to `subject` if omitted. |
| `owner` | Identifies which agent owns the task. `undefined` means unassigned and available for claiming. |
| `blocks` / `blockedBy` | Bidirectional dependency edges. Always maintained in sync: if task A blocks task B, then A.blocks contains B's ID and B.blockedBy contains A's ID. |
| `metadata` | Extensibility mechanism. Tasks with `metadata._internal = true` are hidden from the agent's TaskList view. |

### 3.3 Status Lifecycle

```
pending ──> in_progress ──> completed
   │                            
   └──> deleted (permanent removal, not a real status — handled as a special action)
```

- **`pending`**: Created but not yet started. The default status for all new tasks.
- **`in_progress`**: Actively being worked on. Only one agent should own a task at a time.
- **`completed`**: Work is finished. Completed tasks are kept briefly (5 seconds) for UI display, then the task list is reset.
- **`deleted`**: A pseudo-status used only in the TaskUpdate tool. Setting status to `deleted` permanently removes the task file and cascades to clean up all references in other tasks' `blocks`/`blockedBy` arrays.

---

## 4. Storage Layer

### 4.1 File-Based Persistence

Each task is stored as an individual JSON file on disk:

```
~/.claude/tasks/<taskListId>/<taskId>.json
```

The `taskListId` determines which task list a session uses. Resolution order:

1. `CLAUDE_CODE_TASK_LIST_ID` environment variable (explicit override)
2. In-process teammate context's team name (so teammates share the leader's list)
3. `CLAUDE_CODE_TEAM_NAME` environment variable (process-based teammates)
4. Leader-set team name (from team creation)
5. Session ID (fallback for standalone sessions)

### 4.2 Concurrency Safety

The system must handle concurrent access from multiple agents (swarm mode). This is achieved via **file locking**:

- **Task-list-level lock** (`<taskDir>/.lock`): Used for operations that need atomic reads across the entire list (e.g. `createTask` to determine the next ID, `claimTask` with busy check).
- **Task-file-level lock** (`<taskDir>/<id>.json`): Used for single-task mutations (`updateTask`, `claimTask` without busy check).

Lock configuration for ~10 concurrent agents:

```typescript
const LOCK_OPTIONS = {
  retries: {
    retries: 30,      // Total retry attempts
    minTimeout: 5,    // Min backoff (ms)
    maxTimeout: 100,  // Max backoff (ms)
  },
}
```

This gives ~2.6 seconds total wait budget, sufficient for ~10 concurrent agents where each critical section takes ~50-100ms.

### 4.3 High Water Mark

A `.highwatermark` file in each task list directory stores the highest task ID ever assigned. This prevents ID reuse after tasks are deleted or the list is reset. When creating a new task, the next ID is `max(highest_file_id, highwatermark) + 1`.

### 4.4 Core Storage Functions

```
createTask(taskListId, taskData) -> taskId
  Acquires list-level lock. Reads highest ID. Writes new task file. Returns new ID.

getTask(taskListId, taskId) -> Task | null
  Reads and validates task file against schema. Returns null for missing/invalid.

updateTask(taskListId, taskId, updates) -> Task | null
  Acquires task-file lock. Merges updates into existing task. Writes back.

deleteTask(taskListId, taskId) -> boolean
  Updates high-water-mark. Removes task file. Cascades: removes taskId from
  all other tasks' blocks/blockedBy arrays.

listTasks(taskListId) -> Task[]
  Reads all .json files in directory. Validates each. Returns array.

blockTask(taskListId, fromTaskId, toTaskId) -> boolean
  Bidirectional: adds toTaskId to fromTask.blocks, adds fromTaskId to toTask.blockedBy.

resetTaskList(taskListId) -> void
  Acquires list-level lock. Saves high water mark. Deletes all task files.
```

---

## 5. Tool Definitions

The agent interacts with the task system through four tools. Each tool definition includes an input schema, output schema, a prompt (system instructions for the agent), and result formatting.

### 5.1 TaskCreate

**Purpose**: Create a new task in the task list.

**Input Schema**:
```typescript
{
  subject: string       // Brief title for the task
  description: string   // What needs to be done
  activeForm?: string   // Present continuous form for spinner (e.g. "Running tests")
  metadata?: Record<string, unknown>  // Arbitrary metadata
}
```

**Behavior**:
1. Calls `createTask()` with status `pending`, no owner, empty `blocks`/`blockedBy`.
2. Executes `taskCreatedHooks`. If any hook returns a blocking error, the task is immediately deleted and an error is thrown.
3. Auto-expands the task list UI (sets `expandedView: 'tasks'` in app state).
4. Returns `{ task: { id, subject } }`.

**Result Formatting** (what the agent sees):
```
Task #1 created successfully: Fix authentication bug in login flow
```

### 5.2 TaskUpdate

**Purpose**: Update an existing task's status, details, ownership, or dependencies.

**Input Schema**:
```typescript
{
  taskId: string                   // The ID of the task to update
  subject?: string                 // New subject
  description?: string             // New description
  activeForm?: string              // New spinner text
  status?: 'pending' | 'in_progress' | 'completed' | 'deleted'
  owner?: string                   // New owner agent name
  addBlocks?: string[]             // Task IDs this task blocks
  addBlockedBy?: string[]          // Task IDs that block this task
  metadata?: Record<string, unknown>  // Metadata keys to merge (null values delete keys)
}
```

**Behavior**:
1. Validates the task exists.
2. If `status === 'deleted'`: calls `deleteTask()` and returns immediately.
3. If `status === 'completed'`: executes `taskCompletedHooks`. If any hook returns a blocking error, the update is rejected.
4. Applies field updates only for values that differ from current state.
5. In swarm mode: if `status` is `in_progress` and no owner is set, auto-assigns the calling agent as owner.
6. If ownership changes in swarm mode: sends a mailbox notification to the new owner.
7. Processes `addBlocks`/`addBlockedBy` via the bidirectional `blockTask()` function.
8. Returns `{ success, taskId, updatedFields, statusChange?, error? }`.

**Result Formatting** (what the agent sees):
```
Updated task #1 status, owner
```

For teammates completing tasks:
```
Updated task #1 status
Task completed. Call TaskList now to find your next available task or see if your work unblocked others.
```

### 5.3 TaskList

**Purpose**: List all tasks in the current task list.

**Input Schema**: `{}` (no parameters)

**Behavior**:
1. Reads all tasks, filters out internal tasks (those with `metadata._internal`).
2. For the `blockedBy` field, filters out completed tasks (only shows active blockers).
3. Returns a summary of each task: `{ id, subject, status, owner?, blockedBy[] }`.

**Result Formatting** (what the agent sees):
```
#1 [completed] Set up database schema
#2 [in_progress] Implement user authentication (alice)
#3 [pending] Write API endpoint tests [blocked by #2]
#4 [pending] Update documentation
```

### 5.4 TaskGet

**Purpose**: Retrieve full details of a single task by ID.

**Input Schema**:
```typescript
{
  taskId: string  // The ID of the task to retrieve
}
```

**Behavior**:
Returns the full task including description, blocks, and blockedBy.

**Result Formatting** (what the agent sees):
```
Task #2: Implement user authentication
Status: in_progress
Description: Add JWT-based auth with login/logout endpoints...
Blocked by: #1
Blocks: #3, #5
```

### 5.5 Tool Properties

All four tools share these properties:

| Property | Value | Reason |
|----------|-------|--------|
| `shouldDefer` | `true` | Tools are loaded lazily, not included in every API call |
| `isConcurrencySafe` | `true` | Multiple task tools can run in parallel safely (file locking handles races) |
| `isReadOnly` | `true` for TaskList/TaskGet, `false` for TaskCreate/TaskUpdate | Read-only tools can run without user approval in some permission modes |

---

## 6. Dependency Management

### 6.1 Bidirectional Consistency

Dependencies are always maintained in both directions. The `blockTask(taskListId, fromTaskId, toTaskId)` function:

1. Adds `toTaskId` to `fromTask.blocks` (if not already present)
2. Adds `fromTaskId` to `toTask.blockedBy` (if not already present)

This invariant ensures that reading either side of the relationship gives a complete picture.

### 6.2 Cascading on Delete

When a task is deleted, all references to it are removed from other tasks:

```
for each task in allTasks:
  remove deletedTaskId from task.blocks
  remove deletedTaskId from task.blockedBy
```

### 6.3 Filtered Display

When listing tasks, completed blockers are filtered out of the `blockedBy` display:

```typescript
blockedBy: task.blockedBy.filter(id => !resolvedTaskIds.has(id))
```

This lets the agent see which tasks are actually unblocked and ready to work on.

### 6.4 Blocker Checking in Claim

When an agent tries to claim a task, unresolved blockers are checked:

```typescript
const unresolvedTaskIds = new Set(
  allTasks.filter(t => t.status !== 'completed').map(t => t.id)
)
const blockedByTasks = task.blockedBy.filter(id => unresolvedTaskIds.has(id))
if (blockedByTasks.length > 0) {
  return { success: false, reason: 'blocked', blockedByTasks }
}
```

---

## 7. Error Handling

This section catalogues how the system handles every failure mode. Getting these right is critical — incorrect error handling causes tool cancellation cascades, zombie tasks, or silent data loss.

### 7.1 Task Not Found

**Where**: TaskUpdate, TaskGet, deleteTask, claimTask

**Pattern**: Return a **non-error tool result** with a descriptive message. Do NOT throw or return an error-typed response.

```typescript
// TaskUpdate: return success=false, not an exception
if (!existingTask) {
  return {
    data: {
      success: false,
      taskId,
      updatedFields: [],
      error: 'Task not found',
    },
  }
}
```

```typescript
// mapToolResultToToolResultBlockParam: format as normal content, not is_error
if (!success) {
  return {
    tool_use_id: toolUseID,
    type: 'tool_result',
    content: error || `Task #${taskId} not found`,  // NOT is_error: true
  }
}
```

**Why**: Error-typed tool results trigger sibling tool cancellation in parallel execution. "Task not found" is a benign condition (task list was already cleaned up, race with another agent) that the model can recover from.

### 7.2 Hook Blocking Errors

**Where**: TaskCreate (taskCreatedHooks), TaskUpdate (taskCompletedHooks)

**Pattern**: If any hook yields a `blockingError`, roll back the operation:

- **TaskCreate**: Delete the just-created task, then throw the error
- **TaskUpdate**: Don't apply the status change, return `success: false` with the error message

```typescript
// TaskCreate: rollback on hook failure
if (blockingErrors.length > 0) {
  await deleteTask(getTaskListId(), taskId)
  throw new Error(blockingErrors.join('\n'))
}
```

```typescript
// TaskUpdate: reject the status change
if (blockingErrors.length > 0) {
  return {
    data: {
      success: false,
      taskId,
      updatedFields: [],
      error: blockingErrors.join('\n'),
    },
  }
}
```

### 7.3 File System Errors

**Where**: getTask, listTasks, createTask, deleteTask

**Pattern**: Distinguish between "file doesn't exist" (expected, return null/false) and other errors (log and surface).

```typescript
// getTask: ENOENT is normal, other errors are logged
try {
  const content = await readFile(path, 'utf-8')
  // ...validate and return
} catch (e) {
  if (getErrnoCode(e) === 'ENOENT') return null  // Expected: task was deleted
  logError(e)                                      // Unexpected: disk error, permissions, etc.
  return null
}
```

### 7.4 Schema Validation Failures

**Where**: getTask (after reading from disk)

**Pattern**: If a task file fails schema validation, treat it as if it doesn't exist (return null). Log the validation error for debugging.

```typescript
const parsed = TaskSchema().safeParse(data)
if (!parsed.success) {
  logForDebugging(`Task ${taskId} failed schema validation: ${parsed.error.message}`)
  return null
}
```

### 7.5 Lock Acquisition Failures

**Where**: createTask, updateTask, claimTask, resetTaskList

**Pattern**: The lock library retries with exponential backoff (configured via `LOCK_OPTIONS`). If all retries are exhausted, the lock call throws. This propagates up as a tool error. The retry budget (~2.6s) is sized for ~10 concurrent agents; if you need more, increase `retries` or `maxTimeout`.

### 7.6 Notification Listener Errors

**Where**: `notifyTasksUpdated()`

**Pattern**: Wrap signal emission in try/catch so listener failures never propagate to callers. Task mutations must succeed from the caller's perspective even if UI notification fails.

```typescript
export function notifyTasksUpdated(): void {
  try {
    tasksUpdated.emit()
  } catch {
    // Ignore listener errors — task mutations must not fail due to notification issues
  }
}
```

### 7.7 Concurrent Delete During Cascade

**Where**: deleteTask (cascading reference removal)

**Pattern**: After deleting the task file, iterate all remaining tasks to remove references. If another agent deletes a task concurrently during this cascade, `updateTask` returns null — this is fine, the reference is already gone.

---

## 8. Lifecycle Hooks

### 8.1 Hook Points

Two hook points exist in the task lifecycle:

| Hook | Fires When | Called From |
|------|-----------|-------------|
| `taskCreatedHooks` | After a task is successfully created | `TaskCreateTool.call()` |
| `taskCompletedHooks` | When a task's status is set to `completed` | `TaskUpdateTool.call()` |

### 8.2 Hook Interface

Hooks are async generators that yield results containing optional `blockingError` strings:

```typescript
async function* executeTaskCreatedHooks(
  taskId: string,
  taskSubject: string,
  taskDescription?: string,
  teammateName?: string,
  teamName?: string,
  timeoutMs?: number,
  signal?: AbortSignal,
  ...
): AsyncGenerator<{ blockingError?: string }>
```

### 8.3 Blocking Behavior

- If any hook yields a `blockingError`, the operation is rolled back:
  - For `TaskCreate`: the newly created task is deleted
  - For `TaskUpdate`: the status change is not applied
- The error message is returned to the agent so it can understand what went wrong.
- Non-blocking results are silently consumed.

### 8.4 Hook Context

Hooks receive:
- `taskId`: The numeric task ID
- `taskSubject`: The task's subject line
- `taskDescription`: The task's full description
- `teammateName`: The agent's name (if in a team)
- `teamName`: The team name (if in a team)
- `signal`: An AbortSignal for cancellation

This lets hooks make decisions based on task content, agent identity, and team context.

---

## 9. Multi-Agent Coordination

### 9.1 Task Claiming

The `claimTask()` function provides atomic task assignment with several safety checks:

```typescript
type ClaimTaskResult = {
  success: boolean
  reason?: 'task_not_found' | 'already_claimed' | 'already_resolved' | 'blocked' | 'agent_busy'
  task?: Task
  busyWithTasks?: string[]   // When reason is 'agent_busy'
  blockedByTasks?: string[]  // When reason is 'blocked'
}
```

**Claim checks** (in order):
1. Task exists
2. Not already claimed by another agent (same-agent re-claim is OK)
3. Not already completed
4. No unresolved blockers
5. (Optional) Agent not busy with other open tasks

### 9.2 Two Locking Strategies

- **Task-level lock** (default): Locks only the individual task file. Faster but doesn't prevent TOCTOU races for the busy check.
- **List-level lock** (`checkAgentBusy: true`): Locks the entire task list. Reads all tasks atomically to check if the agent owns other open tasks before claiming. Prevents an agent from accidentally claiming two tasks.

### 9.3 Agent Status

```typescript
type AgentStatus = {
  agentId: string
  name: string
  agentType?: string
  status: 'idle' | 'busy'
  currentTasks: string[]
}
```

`getAgentStatuses(teamName)` reads the team config file for the member list, then cross-references against the task list to determine which agents are idle (no open tasks) vs busy (own at least one open task).

### 9.4 Ownership Lifecycle

1. **Task created** with `owner: undefined` (available).
2. **Agent claims** via `TaskUpdate` with `owner: "agent-name"` (or auto-set when marking `in_progress`).
3. **Mailbox notification** sent to new owner with task details (JSON message including taskId, subject, description, assignedBy, timestamp).
4. **Agent completes** via `TaskUpdate` with `status: "completed"`.
5. **On agent exit**: `unassignTeammateTasks()` resets all of that agent's open tasks to `pending` with `owner: undefined`, and builds a notification message listing unassigned tasks.

### 9.5 Task Unassignment on Agent Exit

```typescript
async function unassignTeammateTasks(
  teamName: string,
  teammateId: string,
  teammateName: string,
  reason: 'terminated' | 'shutdown'
): Promise<{
  unassignedTasks: Array<{ id: string; subject: string }>
  notificationMessage: string
}>
```

This function:
1. Finds all non-completed tasks owned by the exiting agent (checks both agent ID and name for backward compatibility)
2. Resets each to `{ owner: undefined, status: 'pending' }`
3. Returns a formatted notification message for the team lead, e.g.:
   > "alice was terminated. 2 task(s) were unassigned: #3 "Write tests", #5 "Update docs". Use TaskList to check availability and TaskUpdate with owner to reassign them to idle teammates."

---

## 10. Real-Time UI

### 10.1 Architecture

The UI subscribes to task changes via a singleton store pattern (`TasksV2Store`) that shares a single file system watcher across all UI consumers.

**Update sources** (in priority order):
1. **In-process signal** (`onTasksUpdated`): Immediate notification when the same process modifies tasks.
2. **File system watcher** (`fs.watch`): Detects cross-process changes (other agents in the swarm).
3. **Fallback polling** (every 5 seconds): Safety net for environments where `fs.watch` is unreliable.

**Debouncing**: All fetch triggers are debounced at 50ms to batch rapid changes.

### 10.2 Display Behavior

The task list component renders each task as a single line:

```
#1 [completed] Set up database schema
#2 [in_progress] Implement user authentication (alice)
#3 [pending] Write API endpoint tests [blocked by #2]
```

Display rules:
- Maximum 10 tasks shown (respects terminal height)
- Tasks with `metadata._internal = true` are hidden
- Completed tasks show with a check mark and completion timestamp
- Agents are color-coded per teammate
- `blockedBy` only shows active (non-completed) blockers

### 10.3 Auto-Hide Behavior

When all tasks reach `completed` status:
1. A 5-second timer starts
2. After 5 seconds, if all tasks are still completed, the task list is reset (files deleted, preserving high water mark) and the UI hides
3. If any new incomplete task appears during the 5-second window, the timer is cancelled

### 10.4 Expanded View Management

- `TaskCreate` and `TaskUpdate` auto-expand the task view (`expandedView: 'tasks'`)
- When the task list becomes hidden (all tasks done + timer elapsed), the expanded view collapses back

---

## 11. Agent Prompts (Verbatim)

The prompts below are injected into the agent's system context as part of each tool's definition. They are the primary mechanism for teaching the agent when and how to use task decomposition. **These should be included verbatim or adapted closely** — paraphrasing loses critical nuance around edge cases.

### 11.1 TaskCreate Prompt

The prompt is generated dynamically based on whether swarm mode is enabled. Below is the base version; the swarm-aware additions are shown in brackets.

```
Use this tool to create a structured task list for your current coding session. This helps you
track progress, organize complex tasks, and demonstrate thoroughness to the user.
It also helps the user understand the progress of the task and overall progress of their requests.

## When to Use This Tool

Use this tool proactively in these scenarios:

- Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
- Non-trivial and complex tasks - Tasks that require careful planning or multiple
  operations [and potentially assigned to teammates]
- Plan mode - When using plan mode, create a task list to track the work
- User explicitly requests todo list - When the user directly asks you to use the todo list
- User provides multiple tasks - When users provide a list of things to be done
  (numbered or comma-separated)
- After receiving new instructions - Immediately capture user requirements as tasks
- When you start working on a task - Mark it as in_progress BEFORE beginning work
- After completing a task - Mark it as completed and add any new follow-up tasks
  discovered during implementation

## When NOT to Use This Tool

Skip using this tool when:
- There is only a single, straightforward task
- The task is trivial and tracking it provides no organizational benefit
- The task can be completed in less than 3 trivial steps
- The task is purely conversational or informational

NOTE that you should not use this tool if there is only one trivial task to do. In this case
you are better off just doing the task directly.

## Task Fields

- **subject**: A brief, actionable title in imperative form
  (e.g., "Fix authentication bug in login flow")
- **description**: What needs to be done
- **activeForm** (optional): Present continuous form shown in the spinner when the task is
  in_progress (e.g., "Fixing authentication bug"). If omitted, the spinner shows the
  subject instead.

All tasks are created with status `pending`.

## Tips

- Create tasks with clear, specific subjects that describe the outcome
- After creating tasks, use TaskUpdate to set up dependencies (blocks/blockedBy) if needed
[- Include enough detail in the description for another agent to understand and complete
   the task]
[- New tasks are created with status 'pending' and no owner - use TaskUpdate with the
   `owner` parameter to assign them]
- Check TaskList first to avoid creating duplicate tasks
```

### 11.2 TaskUpdate Prompt

```
Use this tool to update a task in the task list.

## When to Use This Tool

**Mark tasks as resolved:**
- When you have completed the work described in a task
- When a task is no longer needed or has been superseded
- IMPORTANT: Always mark your assigned tasks as resolved when you finish them
- After resolving, call TaskList to find your next task

- ONLY mark a task as completed when you have FULLY accomplished it
- If you encounter errors, blockers, or cannot finish, keep the task as in_progress
- When blocked, create a new task describing what needs to be resolved
- Never mark a task as completed if:
  - Tests are failing
  - Implementation is partial
  - You encountered unresolved errors
  - You couldn't find necessary files or dependencies

**Delete tasks:**
- When a task is no longer relevant or was created in error
- Setting status to `deleted` permanently removes the task

**Update task details:**
- When requirements change or become clearer
- When establishing dependencies between tasks

## Fields You Can Update

- **status**: The task status (see Status Workflow below)
- **subject**: Change the task title (imperative form, e.g., "Run tests")
- **description**: Change the task description
- **activeForm**: Present continuous form shown in spinner when in_progress
  (e.g., "Running tests")
- **owner**: Change the task owner (agent name)
- **metadata**: Merge metadata keys into the task (set a key to null to delete it)
- **addBlocks**: Mark tasks that cannot start until this one completes
- **addBlockedBy**: Mark tasks that must complete before this one can start

## Status Workflow

Status progresses: `pending` → `in_progress` → `completed`

Use `deleted` to permanently remove a task.

## Staleness

Make sure to read a task's latest state using `TaskGet` before updating it.

## Examples

Mark task as in progress when starting work:
{"taskId": "1", "status": "in_progress"}

Mark task as completed after finishing work:
{"taskId": "1", "status": "completed"}

Delete a task:
{"taskId": "1", "status": "deleted"}

Claim a task by setting owner:
{"taskId": "1", "owner": "my-name"}

Set up task dependencies:
{"taskId": "2", "addBlockedBy": ["1"]}
```

### 11.3 TaskList Prompt

The prompt adapts based on swarm mode. Swarm additions shown in brackets.

```
Use this tool to list all tasks in the task list.

## When to Use This Tool

- To see what tasks are available to work on (status: 'pending', no owner, not blocked)
- To check overall progress on the project
- To find tasks that are blocked and need dependencies resolved
[- Before assigning tasks to teammates, to see what's available]
- After completing a task, to check for newly unblocked work or claim the next
  available task
- **Prefer working on tasks in ID order** (lowest ID first) when multiple tasks are
  available, as earlier tasks often set up context for later ones

## Output

Returns a summary of each task:
- **id**: Task identifier (use with TaskGet, TaskUpdate)
- **subject**: Brief description of the task
- **status**: 'pending', 'in_progress', or 'completed'
- **owner**: Agent ID if assigned, empty if available
- **blockedBy**: List of open task IDs that must be resolved first (tasks with blockedBy
  cannot be claimed until dependencies resolve)

Use TaskGet with a specific task ID to view full details including description and comments.

[## Teammate Workflow

When working as a teammate:
1. After completing your current task, call TaskList to find available work
2. Look for tasks with status 'pending', no owner, and empty blockedBy
3. **Prefer tasks in ID order** (lowest ID first) when multiple tasks are available,
   as earlier tasks often set up context for later ones
4. Claim an available task using TaskUpdate (set `owner` to your name), or wait for
   leader assignment
5. If blocked, focus on unblocking tasks or notify the team lead]
```

### 11.4 TaskGet Prompt

```
Use this tool to retrieve a task by its ID from the task list.

## When to Use This Tool

- When you need the full description and context before starting work on a task
- To understand task dependencies (what it blocks, what blocks it)
- After being assigned a task, to get complete requirements

## Output

Returns full task details:
- **subject**: Task title
- **description**: Detailed requirements and context
- **status**: 'pending', 'in_progress', or 'completed'
- **blocks**: Tasks waiting on this one to complete
- **blockedBy**: Tasks that must complete before this one can start

## Tips

- After fetching a task, verify its blockedBy list is empty before beginning work.
- Use TaskList to see all tasks in summary form.
```

---

## 12. End-to-End Flow

### 12.1 Single-Agent Flow

```
User: "Add authentication to the API with JWT, tests, and documentation"

Agent:
  1. TaskCreate { subject: "Set up JWT dependencies", description: "..." }        -> #1
  2. TaskCreate { subject: "Implement auth middleware", description: "..." }       -> #2
  3. TaskCreate { subject: "Add login/logout endpoints", description: "..." }     -> #3
  4. TaskCreate { subject: "Write authentication tests", description: "..." }     -> #4
  5. TaskCreate { subject: "Update API documentation", description: "..." }       -> #5
  6. TaskUpdate { taskId: "2", addBlockedBy: ["1"] }     // middleware needs deps
  7. TaskUpdate { taskId: "3", addBlockedBy: ["2"] }     // endpoints need middleware
  8. TaskUpdate { taskId: "4", addBlockedBy: ["3"] }     // tests need endpoints
  9. TaskUpdate { taskId: "5", addBlockedBy: ["4"] }     // docs need tests
  10. TaskUpdate { taskId: "1", status: "in_progress" }  // Start first task
  11. [Does the work...]
  12. TaskUpdate { taskId: "1", status: "completed" }
  13. TaskList {}                                         // See what's unblocked
  14. TaskUpdate { taskId: "2", status: "in_progress" }
  15. [Continues through remaining tasks...]
```

### 12.2 Multi-Agent Flow

```
Leader:
  1. Creates tasks #1-#5 with dependencies
  2. Creates team with agents alice and bob

Alice:
  1. TaskList {} -> sees #1 is available (no blockers, no owner)
  2. TaskUpdate { taskId: "1", status: "in_progress" }  // auto-sets owner
  3. [Does the work...]
  4. TaskUpdate { taskId: "1", status: "completed" }
  5. TaskList {} -> sees #2 is now unblocked
  6. Claims and works on #2

Bob:
  1. TaskList {} -> sees #1 is claimed by alice, nothing unblocked for him
  2. [Waits or works on unblocked tasks if any]
  3. TaskList {} -> sees #4 is now unblocked (after alice completed its blocker chain)
  4. Claims and works on #4

If Alice crashes:
  Leader calls unassignTeammateTasks("alice")
  -> alice's in-progress tasks reset to pending, unowned
  -> Bob or new agent can claim them
```

---

## 13. Integration Test Scenarios

These scenarios describe exact tool call sequences and expected results. Use them to verify your implementation works correctly end-to-end.

### 13.1 Basic Lifecycle

Tests the core create-update-list-complete flow.

```
Step 1: TaskCreate { subject: "Write tests", description: "Add unit tests for auth module" }
  Expected result: "Task #1 created successfully: Write tests"
  Expected file: <taskDir>/1.json exists with status "pending"

Step 2: TaskList {}
  Expected result: "#1 [pending] Write tests"

Step 3: TaskUpdate { taskId: "1", status: "in_progress" }
  Expected result: "Updated task #1 status"
  Expected file: 1.json now has status "in_progress"

Step 4: TaskGet { taskId: "1" }
  Expected result includes:
    "Task #1: Write tests"
    "Status: in_progress"
    "Description: Add unit tests for auth module"

Step 5: TaskUpdate { taskId: "1", status: "completed" }
  Expected result: "Updated task #1 status"
  Expected file: 1.json now has status "completed"

Step 6: TaskList {}
  Expected result: "#1 [completed] Write tests"
```

### 13.2 Dependency Chain

Tests that blockedBy filtering works correctly as tasks complete.

```
Step 1: TaskCreate { subject: "Task A" ... } -> #1
Step 2: TaskCreate { subject: "Task B" ... } -> #2
Step 3: TaskCreate { subject: "Task C" ... } -> #3
Step 4: TaskUpdate { taskId: "2", addBlockedBy: ["1"] }
Step 5: TaskUpdate { taskId: "3", addBlockedBy: ["2"] }

Step 6: TaskList {}
  Expected:
    "#1 [pending] Task A"
    "#2 [pending] Task B [blocked by #1]"
    "#3 [pending] Task C [blocked by #2]"

Step 7: TaskUpdate { taskId: "1", status: "completed" }

Step 8: TaskList {}
  Expected:
    "#1 [completed] Task A"
    "#2 [pending] Task B"              <-- #1 no longer shown as blocker (it's completed)
    "#3 [pending] Task C [blocked by #2]"   <-- #2 still blocks #3

Step 9: Verify file state:
  2.json: blockedBy still contains "1" on disk (raw)
  But TaskList filters it because task #1 is completed
```

### 13.3 Task Not Found (Non-Error)

Tests that missing tasks don't cause error-typed responses.

```
Step 1: TaskUpdate { taskId: "999", status: "completed" }
  Expected result content: "Task #999 not found"
  Expected result type: tool_result (NOT is_error: true)
  Expected: no exception thrown, no sibling tool cancellation

Step 2: TaskGet { taskId: "999" }
  Expected result content: "Task not found"
```

### 13.4 Delete with Cascade

Tests that deleting a task cleans up references in other tasks.

```
Step 1: TaskCreate { subject: "A" ... } -> #1
Step 2: TaskCreate { subject: "B" ... } -> #2
Step 3: TaskCreate { subject: "C" ... } -> #3
Step 4: TaskUpdate { taskId: "2", addBlockedBy: ["1"] }
Step 5: TaskUpdate { taskId: "3", addBlockedBy: ["1"] }

  Verify: 1.json has blocks: ["2", "3"]
  Verify: 2.json has blockedBy: ["1"]
  Verify: 3.json has blockedBy: ["1"]

Step 6: TaskUpdate { taskId: "1", status: "deleted" }
  Expected result: "Updated task #1 deleted"

  Verify: 1.json no longer exists
  Verify: 2.json has blockedBy: []   <-- reference cleaned up
  Verify: 3.json has blockedBy: []   <-- reference cleaned up
  Verify: .highwatermark contains "1" or higher
```

### 13.5 ID Non-Reuse After Delete

Tests the high-water-mark system.

```
Step 1: TaskCreate { subject: "A" ... } -> #1
Step 2: TaskCreate { subject: "B" ... } -> #2
Step 3: TaskUpdate { taskId: "2", status: "deleted" }
Step 4: TaskCreate { subject: "C" ... } -> #3  (NOT #2)

  Verify: .highwatermark >= 2
  Verify: 3.json exists, 2.json does not
```

### 13.6 Parallel Creation (Concurrency)

Tests that concurrent task creation produces unique IDs.

```
Step 1: Fire 5 concurrent TaskCreate calls simultaneously
  Expected: All 5 succeed with IDs #1 through #5 (in some order)
  Expected: No duplicate IDs
  Expected: No file corruption
  Verify: .highwatermark is not necessary (files exist) but if checked, >= 5
```

---

## 14. Implementation Checklist

### MVP (Phases 1-3) — Single-agent task decomposition

#### Phase 1: Core Data Model & Storage
- [ ] Define `Task` type with all fields (id, subject, description, activeForm, owner, status, blocks, blockedBy, metadata)
- [ ] Define `TaskStatus` enum: `pending | in_progress | completed`
- [ ] Implement file-based storage: one JSON file per task in `<configDir>/tasks/<taskListId>/`
- [ ] Implement auto-incrementing ID generation with high-water-mark file
- [ ] Implement file locking for concurrent access (both list-level and task-level)
- [ ] Implement `createTask`, `getTask`, `updateTask`, `deleteTask`, `listTasks`
- [ ] Implement `blockTask` with bidirectional consistency
- [ ] Implement cascading delete (remove references from other tasks)
- [ ] Implement `resetTaskList` with high-water-mark preservation

#### Phase 2: Tools
- [ ] Implement `TaskCreate` tool with input validation and auto-expand
- [ ] Implement `TaskUpdate` tool with status transitions, deletion, and dependency management
- [ ] Implement `TaskList` tool with internal-task filtering and resolved-blocker filtering
- [ ] Implement `TaskGet` tool with full task detail retrieval
- [ ] Write tool prompts (use Section 11 verbatim or adapt closely)
- [ ] Implement result formatting (`mapToolResultToToolResultBlockParam`) — non-error for "not found"

#### Phase 3: Agent Integration
- [ ] Register tools in the agent's tool registry
- [ ] Add feature flag / enablement check (e.g. `isTodoV2Enabled()`)
- [ ] Wire tool results into the agent's conversation context as `tool_result` blocks
- [ ] Verify: run the integration test scenarios from Section 13

### Enhancement (Phase 4) — Extensibility

#### Phase 4: Lifecycle Hooks
- [ ] Implement `taskCreatedHooks` execution in TaskCreate
- [ ] Implement `taskCompletedHooks` execution in TaskUpdate
- [ ] Implement blocking error handling (rollback on hook failure — see Section 7.2)
- [ ] Provide hook context (taskId, subject, description, agent name, team name)

### Multi-Agent (Phase 5) — Swarm support

#### Phase 5: Multi-Agent Support
- [ ] Implement `claimTask` with atomic checks (exists, not claimed, not resolved, not blocked)
- [ ] Implement `claimTaskWithBusyCheck` using list-level lock
- [ ] Implement auto-owner-assignment on `in_progress` status change
- [ ] Implement mailbox notifications on ownership change
- [ ] Implement `getAgentStatuses` (idle/busy based on task ownership)
- [ ] Implement `unassignTeammateTasks` for agent exit cleanup
- [ ] Add swarm-aware prompt sections (bracketed text in Section 11)

### Polish (Phase 6) — Real-time UI

#### Phase 6: Real-Time UI
- [ ] Implement singleton store with file watcher + in-process signal + fallback polling
- [ ] Implement debounced fetching (50ms batch window)
- [ ] Implement task list rendering with status, owner, and blocker display
- [ ] Implement auto-hide after 5 seconds when all tasks complete
- [ ] Implement expanded view management (auto-expand on create/update, collapse on hide)

---

## Appendix A: Task File Example

```json
{
  "id": "3",
  "subject": "Add login/logout endpoints",
  "description": "Create POST /auth/login and POST /auth/logout endpoints using the JWT middleware from task #2. Login should accept email/password, validate against the users table, and return a signed JWT. Logout should invalidate the token.",
  "activeForm": "Adding login/logout endpoints",
  "owner": "alice",
  "status": "in_progress",
  "blocks": ["4", "5"],
  "blockedBy": ["2"],
  "metadata": {}
}
```

## Appendix B: Task List Directory Layout

```
~/.claude/tasks/
  my-session-id/
    .lock                  # List-level lock file
    .highwatermark         # Highest ID ever assigned (e.g. "7")
    1.json                 # Task #1
    2.json                 # Task #2
    3.json                 # Task #3
  my-team-name/
    .lock
    .highwatermark
    1.json
    2.json
```

## Appendix C: Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| Lock retries | 30 | Max retry attempts for file lock acquisition |
| Lock min timeout | 5ms | Minimum backoff between retries |
| Lock max timeout | 100ms | Maximum backoff between retries |
| Debounce interval | 50ms | Batch window for UI updates |
| Fallback poll interval | 5000ms | Safety-net polling for fs.watch misses |
| Hide delay | 5000ms | Time after all-complete before UI hides |
| Stopped display | 3000ms | Duration to show killed tasks before eviction |
| Poll interval | 1000ms | Main polling loop for background task output |

---

## Appendix D: Where to Look

This maps each concept in this guide to its entry-point file in the reference implementation. All paths are relative to the repository root. When implementing, read these files to understand the exact patterns, edge cases, and integration points.

| Concept | Entry Point | What to look for |
|---------|-------------|------------------|
| Task schema & status types | `src/utils/tasks.ts` | `TaskSchema`, `TaskStatusSchema`, `TASK_STATUSES` near the top |
| All CRUD operations | `src/utils/tasks.ts` | `createTask`, `getTask`, `updateTask`, `deleteTask`, `listTasks` |
| File locking & concurrency | `src/utils/tasks.ts` | `LOCK_OPTIONS`, `ensureTaskListLockFile`, and how each function acquires/releases locks |
| High water mark | `src/utils/tasks.ts` | `readHighWaterMark`, `writeHighWaterMark`, `HIGH_WATER_MARK_FILE` |
| Dependency management | `src/utils/tasks.ts` | `blockTask` (bidirectional), cascading cleanup in `deleteTask` |
| Task claiming & agent status | `src/utils/tasks.ts` | `claimTask`, `claimTaskWithBusyCheck`, `getAgentStatuses`, `unassignTeammateTasks` |
| Task list ID resolution | `src/utils/tasks.ts` | `getTaskListId` — the priority chain for determining which list to use |
| TaskCreate tool | `src/tools/TaskCreateTool/` | `TaskCreateTool.ts` (behavior), `prompt.ts` (agent guidance), `constants.ts` (tool name) |
| TaskUpdate tool | `src/tools/TaskUpdateTool/` | `TaskUpdateTool.ts` (behavior), `prompt.ts` (agent guidance), `constants.ts` (tool name) |
| TaskList tool | `src/tools/TaskListTool/` | `TaskListTool.ts` (behavior), `prompt.ts` (agent guidance), `constants.ts` (tool name) |
| TaskGet tool | `src/tools/TaskGetTool/` | `TaskGetTool.ts` (behavior), `prompt.ts` (agent guidance), `constants.ts` (tool name) |
| Tool registration pattern | Any `Task*Tool.ts` | `buildTool({ ... })` call — shows how tools declare schemas, prompts, permissions, and result formatting |
| Lifecycle hooks | `src/utils/hooks.ts` | Search for `executeTaskCreatedHooks` and `executeTaskCompletedHooks` — async generators yielding `{ blockingError? }` |
| Background task framework | `src/utils/task/framework.ts` | `registerTask`, `updateTaskState`, `pollTasks`, `generateTaskAttachments` — manages task lifecycle in AppState |
| Task output streaming | `src/utils/task/diskOutput.ts` | `getTaskOutputPath`, `getTaskOutputDelta` |
| Real-time UI store | `src/hooks/useTasksV2.ts` | `TasksV2Store` class — singleton with `fs.watch`, debouncing, fallback polling, auto-hide timer |
| Task list rendering | `src/components/TaskListV2.tsx` | Status indicators, owner display, blocked-by, agent colors, terminal-aware truncation |
| In-process notifications | `src/utils/signal.ts` | `createSignal()` pub/sub primitive — used by `onTasksUpdated` |
| Teammate identity | `src/utils/teammate.ts` | `getAgentName`, `getAgentId`, `getTeamName`, `isTeamLead` |
| Mailbox notifications | `src/utils/teammateMailbox.ts` | `writeToMailbox` — how task assignments notify agents |
| Feature flag | `src/utils/tasks.ts` | `isTodoV2Enabled` — controls whether task tools are available |
| Background task types | `src/Task.ts`, `src/tasks/types.ts` | `TaskType`, `TaskStatus`, `TaskStateBase`, and the `TaskState` union type |
