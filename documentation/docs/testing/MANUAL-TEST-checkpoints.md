# Checkpoints & Rewind — Manual Test Plan

Step-by-step walkthrough of every checkpoint and rewind feature. Run these from the project root directory using the interactive REPL.

## Feature Overview

The checkpoint system provides an undo capability for file mutations made by the agent. When the agent uses tools that modify files (e.g., `write_file`, `append_file`), the system automatically snapshots the affected files **before** the mutation occurs. The user can then rewind to any checkpoint, restoring all tracked files to their pre-mutation state.

### How it works

1. **Automatic checkpoint creation.** When the user submits a prompt and the LLM responds with tool calls that include mutating operations, a single checkpoint is created for that turn — before any tools execute. One checkpoint per turn, regardless of how many files are modified.

2. **File snapshotting.** Before each mutating tool executes, the system reads the target file(s) and stores their contents as binary blobs in the SQLite database (`.micro_x/memory.db`). If the file does not yet exist, the checkpoint records that fact so rewind can delete it later.

3. **Rewind.** The `/rewind <checkpoint_id>` command restores every file tracked by that checkpoint:
   - Files that **existed before** the checkpoint are restored to their original contents.
   - Files that **did not exist before** (i.e., were created by the agent) are deleted.
   - Files that cannot be restored (missing backup, permission error) are reported as failed — other files in the same checkpoint are still processed.

4. **Non-blocking.** Tracking failures never block tool execution. If a file cannot be snapshotted (e.g., permission denied), the tool still runs — a warning is logged and a `checkpoint.file_untracked` event is emitted.

### What gets tracked

By default (`CheckpointWriteToolsOnly=true`), only explicit file-write tools are tracked: `write_file`, `append_file`, and their namespaced variants (`filesystem__write_file`, etc.).

When `CheckpointWriteToolsOnly=false`, any tool marked as `is_mutating=True` is tracked, including bash commands. Bash mutation detection uses a best-effort command parser that recognises redirects (`>`, `>>`), `rm`, `mv`, `cp`, `touch`, `mkdir`, `sed -i`, `tee`, and similar patterns — but cannot detect mutations from arbitrary programs or complex shell constructs.

### User commands

| Command | Description |
|---------|-------------|
| `/checkpoint` | List recent checkpoints for the current session (default: 20) |
| `/checkpoint list [limit]` | List checkpoints with an optional limit |
| `/checkpoint rewind <id>` | Alias for `/rewind` |
| `/rewind <id>` | Restore all files tracked by the checkpoint to their pre-mutation state |

### Scope and limitations

- **Session-scoped.** Checkpoints belong to the active session. Switching sessions shows a different checkpoint history.
- **One level.** Checkpoints snapshot the file state at creation time — they do not form a chain. Rewinding to an older checkpoint does not undo intermediate checkpoints.
- **Working directory boundary.** Only files within the agent's working directory are tracked. Paths outside are silently skipped.
- **Large files.** File contents are stored as BLOBs in SQLite. Very large files (100MB+) may impact database size and performance.
- **Bash parsing is best-effort.** Complex shell constructs, variable expansions, and mutations via arbitrary programs are not detected.
- **Requires memory.** Both `MemoryEnabled` and `EnableFileCheckpointing` must be `true` in config.

> **Prerequisites**
> - Python 3.11+ with the agent installed (`pip install -e .`)
> - A working `config.json` with at least one LLM provider configured
> - `.env` with valid API keys
> - At least one MCP server with a mutating tool (e.g., `filesystem` with `write_file`)
> - `MemoryEnabled` and `EnableFileCheckpointing` set to `true` (see section 1)

> **Cleanup between test runs**
> Checkpoints are stored in `.micro_x/memory.db`. To start fresh:
> ```bash
> rm -f .micro_x/memory.db
> ```

---

## 1. Configuration

### Test 1.1: Enable checkpoints (minimal config)

Add the following to your config file:

```json
{
  "MemoryEnabled": true,
  "EnableFileCheckpointing": true
}
```

Start the agent:
```bash
python -m micro_x_agent_loop
```

**Expected:**
- Agent starts normally with no errors
- `.micro_x/memory.db` is created (or already exists)
- Checkpoints table exists in the database

### Test 1.2: Checkpoints disabled when memory is off

Set `MemoryEnabled` to `false` (or omit it):

```bash
python -m micro_x_agent_loop
```

Then run:
```
you> /checkpoint
```

**Expected:** Message: `Checkpoint commands require MemoryEnabled=true`

### Test 1.3: Checkpoints disabled when file checkpointing is off

Set `MemoryEnabled=true` but `EnableFileCheckpointing=false`:

```bash
python -m micro_x_agent_loop
```

Ask the agent to write a file, then list checkpoints:
```
you> Write "hello" to a file called /tmp/test-checkpoint.txt
you> /checkpoint
```

**Expected:** No checkpoints found — file checkpointing is disabled, so no snapshots are taken even though memory is on.

### Test 1.4: Write-tools-only mode (default)

Ensure config has:
```json
{
  "MemoryEnabled": true,
  "EnableFileCheckpointing": true,
  "CheckpointWriteToolsOnly": true
}
```

**Expected:** Only `write_file` and `append_file` tool calls trigger file tracking. Other mutating tools (like `bash`) are ignored for checkpoint purposes.

### Test 1.5: Track all mutating tools

```json
{
  "MemoryEnabled": true,
  "EnableFileCheckpointing": true,
  "CheckpointWriteToolsOnly": false
}
```

**Expected:** Any tool with `is_mutating=True` triggers file tracking, including bash commands that write to files.

---

## 2. Checkpoint Creation

### Test 2.1: Checkpoint created on file write

```
you> Write the text "version 1" to a file called test-checkpoint-demo.txt
```

Then:
```
you> /checkpoint
```

**Expected:**
- One checkpoint listed
- Entry shows the checkpoint ID, timestamp, tool name (`write_file` or `filesystem__write_file`), and a preview of your prompt
- Format: `[cp-xxxxxxxx] (id=<full-uuid>, created=<timestamp>, tools=write_file, prompt="Write the text...")`

### Test 2.2: One checkpoint per turn

Ask the agent to write multiple files in a single prompt:

```
you> Create three files: file-a.txt with "aaa", file-b.txt with "bbb", and file-c.txt with "ccc"
```

Then:
```
you> /checkpoint
```

**Expected:**
- Only **one** new checkpoint is created for this turn (not three)
- All three files are tracked under the same checkpoint
- The checkpoint's `tools` field may show multiple tool names

### Test 2.3: No checkpoint for read-only operations

```
you> Read the file pyproject.toml and tell me the project name.
```

Then:
```
you> /checkpoint
```

**Expected:** No new checkpoint created — read operations do not trigger checkpoints.

### Test 2.4: Checkpoint with file that already exists

Create a file first:
```bash
echo "original content" > test-existing-file.txt
```

Then:
```
you> Replace the contents of test-existing-file.txt with "modified content"
```

```
you> /checkpoint
```

**Expected:**
- Checkpoint created
- The original file content ("original content") is stored as a backup blob in the database
- The file on disk now contains "modified content"

### Test 2.5: Checkpoint with new file (did not exist before)

Ensure `test-brand-new.txt` does not exist, then:

```
you> Create a file called test-brand-new.txt with the text "brand new file"
```

```
you> /checkpoint
```

**Expected:**
- Checkpoint created
- The checkpoint records that the file did **not** exist before (`existed_before=0`)
- The file now exists on disk

---

## 3. Checkpoint Listing

### Test 3.1: List checkpoints (default limit)

After running several write operations across multiple prompts:

```
you> /checkpoint
```

**Expected:**
- Lists up to 20 most recent checkpoints (default limit)
- Ordered by most recent first
- Each entry shows: short ID, full ID, creation timestamp, tool names, prompt preview

### Test 3.2: List with explicit limit

```
you> /checkpoint list 5
```

**Expected:** At most 5 checkpoints listed.

### Test 3.3: List with explicit "list" keyword

```
you> /checkpoint list
```

**Expected:** Same as `/checkpoint` — lists up to 20 checkpoints.

### Test 3.4: Empty checkpoint list

Start a fresh session with no writes:

```bash
python -m micro_x_agent_loop --session fresh-test
```

```
you> /checkpoint
```

**Expected:** `No checkpoints found for current session.`

### Test 3.5: Checkpoints are session-scoped

Run writes in one session, then switch to another:

```
you> Write "session A data" to session-a-file.txt
you> /checkpoint
```

Note the checkpoint. Then start a new session:

```bash
python -m micro_x_agent_loop --session different-session
```

```
you> /checkpoint
```

**Expected:** No checkpoints — the new session has its own isolated checkpoint history.

---

## 4. Rewind — Restoring Files

### Test 4.1: Rewind restores modified file

```
you> Write "before rewind" to rewind-test.txt
```

Note the checkpoint ID from `/checkpoint`, then:

```
you> Replace the contents of rewind-test.txt with "after rewind"
```

Verify the file has changed:
```bash
cat rewind-test.txt
# Should show: after rewind
```

Now rewind:
```
you> /rewind <checkpoint_id>
```

**Expected:**
- Output shows `restored` status for `rewind-test.txt`
- File contents are back to "before rewind"

### Test 4.2: Rewind removes newly created file

Start from a state where `rewind-new-file.txt` does not exist:

```
you> Create a file called rewind-new-file.txt with "temporary content"
```

Note the checkpoint ID, then:
```
you> /rewind <checkpoint_id>
```

**Expected:**
- Output shows `removed` status for `rewind-new-file.txt`
- The file no longer exists on disk

### Test 4.3: Rewind via /checkpoint rewind alias

```
you> /checkpoint rewind <checkpoint_id>
```

**Expected:** Identical behaviour to `/rewind <checkpoint_id>`.

### Test 4.4: Rewind with non-existent checkpoint ID

```
you> /rewind not-a-real-checkpoint-id
```

**Expected:** Error message: `Rewind failed: Checkpoint does not exist: not-a-real-checkpoint-id`

### Test 4.5: Rewind is idempotent

Run `/rewind <checkpoint_id>` twice with the same ID:

```
you> /rewind <checkpoint_id>
you> /rewind <checkpoint_id>
```

**Expected:**
- First rewind: `restored` or `removed` statuses
- Second rewind: `restored` again (re-writes same content) or `skipped` (file already removed)
- No errors or crashes

### Test 4.6: Rewind multiple files from one checkpoint

After test 2.2 (three files created in one turn), rewind that checkpoint:

```
you> /rewind <checkpoint_id_from_test_2.2>
```

**Expected:**
- All three files (`file-a.txt`, `file-b.txt`, `file-c.txt`) are listed in the outcome
- Each shows `removed` status (they were newly created)
- All three files are deleted from disk

### Test 4.7: Rewind with missing usage

```
you> /rewind
```

**Expected:** Usage message: `Usage: /rewind <checkpoint_id>`

---

## 5. Working Directory Boundary

### Test 5.1: File within working directory is tracked

```
you> Write "inside workdir" to subdir/inside-test.txt
you> /checkpoint
```

**Expected:** Checkpoint created, file tracked successfully.

### Test 5.2: File outside working directory is skipped

Ask the agent to write a file outside the project root:

```
you> Write "outside" to /tmp/outside-workdir-test.txt
```

```
you> /checkpoint
```

**Expected:**
- Checkpoint may still be created (the turn had tool_use blocks)
- But the file at `/tmp/outside-workdir-test.txt` is **not** tracked in checkpoint_files
- Rewinding this checkpoint has no effect on the outside file

---

## 6. Bash Mutation Tracking

These tests require `CheckpointWriteToolsOnly=false`.

### Test 6.1: Bash redirect tracked

```json
{
  "MemoryEnabled": true,
  "EnableFileCheckpointing": true,
  "CheckpointWriteToolsOnly": false
}
```

```
you> Run this bash command: echo "hello from bash" > bash-redirect-test.txt
you> /checkpoint
```

**Expected:**
- Checkpoint created
- `bash-redirect-test.txt` is tracked (the bash command parser detected the `>` redirect)

### Test 6.2: Bash append tracked

```
you> Run: echo "appended" >> bash-redirect-test.txt
you> /checkpoint
```

**Expected:** File tracked via `>>` redirect detection.

### Test 6.3: Bash rm tracked

```
you> Run: touch bash-rm-test.txt && rm bash-rm-test.txt
```

**Expected:** The parser detects `rm` and attempts to track the target path.

### Test 6.4: Complex bash not tracked (limitation)

```
you> Run: python -c "open('sneaky.txt','w').write('surprise')"
```

**Expected:**
- The bash command parser **cannot** detect this mutation
- `sneaky.txt` is **not** tracked in the checkpoint
- This is a known limitation of best-effort bash parsing

---

## 7. Non-Blocking Error Handling

### Test 7.1: Tracking failure does not block tool execution

If a file tracking error occurs (e.g., permission issue reading the file for backup):

```
you> Write "test" to read-only-dir/test.txt
```

(Where `read-only-dir` has restrictive permissions)

**Expected:**
- The write tool still executes (tracking failures are non-blocking)
- A `checkpoint.file_untracked` event is emitted (visible in the events table)
- Agent continues normally

### Test 7.2: Rewind with missing backup blob

This is an edge case — if the database is corrupted or the backup_blob is NULL for a file that existed before:

**Expected:**
- Rewind reports `failed` status with detail `missing backup blob`
- Other files in the same checkpoint are still processed
- No crash

---

## 8. Session Interaction

### Test 8.1: Checkpoints persist across agent restarts

```
you> Write "persistent" to persist-test.txt
you> /checkpoint
```

Note the checkpoint ID. Exit the agent (Ctrl+C), then restart with the same session:

```bash
python -m micro_x_agent_loop --session <same-session-id>
```

```
you> /checkpoint
```

**Expected:** The checkpoint from the previous run is still listed.

### Test 8.2: Rewind after agent restart

After test 8.1, modify the file externally:

```bash
echo "modified externally" > persist-test.txt
```

Then rewind:
```
you> /rewind <checkpoint_id_from_8.1>
```

**Expected:**
- File restored to "persistent" (the content at checkpoint time)
- Rewind works correctly even though it was created in a previous agent session

### Test 8.3: Session deletion cascades checkpoints

Create a session with checkpoints, then delete it:

```bash
python -m micro_x_agent_loop --session delete-me
```

```
you> Write "doomed" to doomed-file.txt
you> /checkpoint
```

Exit, then in a different session:
```
you> /session delete delete-me
```

**Expected:** Checkpoints for the deleted session are cascade-deleted from the database.

---

## 9. Integration with API Server

### Test 9.1: Checkpoint created via REST chat

Start the server with memory and checkpoints enabled:

```bash
python -m micro_x_agent_loop --server start
```

```bash
curl -X POST http://127.0.0.1:8321/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"Write 'server test' to server-checkpoint-test.txt\", \"session_id\": \"server-cp-test\"}"
```

Then connect via CLI to check:

```bash
python -m micro_x_agent_loop --session server-cp-test
```

```
you> /checkpoint
```

**Expected:** Checkpoint exists from the REST API interaction.

### Test 9.2: Rewind via CLI after server-created checkpoint

Using the checkpoint from test 9.1:

```
you> /rewind <checkpoint_id>
```

**Expected:** File restored or removed as expected — rewind works regardless of how the checkpoint was created.

---

## 10. Cost and Performance

### Test 10.1: Checkpoint overhead is minimal

Time a write operation with and without checkpoints enabled:

1. With `EnableFileCheckpointing=true`: ask the agent to write a small file
2. With `EnableFileCheckpointing=false`: ask the same

**Expected:** No noticeable latency difference — checkpoint creation is a synchronous SQLite INSERT, well under 10ms for typical files.

### Test 10.2: Large file backup

Write a moderately large file (~1MB):

```
you> Create a file called large-test.txt containing 10000 lines of "This is line N" where N is the line number.
```

```
you> /checkpoint
```

**Expected:**
- Checkpoint created successfully
- The full file content is stored as a BLOB in the database
- Database size increases accordingly
- Note: very large files (100MB+) may impact database performance — this is a known limitation

---

## Cleanup

Remove test files created during testing:

```bash
rm -f test-checkpoint-demo.txt test-existing-file.txt test-brand-new.txt
rm -f rewind-test.txt rewind-new-file.txt
rm -f file-a.txt file-b.txt file-c.txt
rm -f bash-redirect-test.txt bash-rm-test.txt sneaky.txt
rm -f persist-test.txt doomed-file.txt server-checkpoint-test.txt large-test.txt
rm -rf subdir/
```

Optionally reset the database:
```bash
rm -f .micro_x/memory.db
```

Reset config overrides (e.g., restore `CheckpointWriteToolsOnly` to `true`).

---

## Test Summary Checklist

| # | Feature | Status |
|---|---------|--------|
| 1.1 | Enable checkpoints (minimal) | |
| 1.2 | Disabled when memory is off | |
| 1.3 | Disabled when file checkpointing is off | |
| 1.4 | Write-tools-only mode | |
| 1.5 | Track all mutating tools | |
| 2.1 | Checkpoint on file write | |
| 2.2 | One checkpoint per turn | |
| 2.3 | No checkpoint for reads | |
| 2.4 | Existing file backup | |
| 2.5 | New file tracking | |
| 3.1 | List checkpoints (default) | |
| 3.2 | List with limit | |
| 3.3 | List with explicit keyword | |
| 3.4 | Empty checkpoint list | |
| 3.5 | Session-scoped checkpoints | |
| 4.1 | Rewind modified file | |
| 4.2 | Rewind removes new file | |
| 4.3 | /checkpoint rewind alias | |
| 4.4 | Non-existent checkpoint ID | |
| 4.5 | Rewind is idempotent | |
| 4.6 | Rewind multiple files | |
| 4.7 | Missing usage | |
| 5.1 | File inside working directory | |
| 5.2 | File outside working directory | |
| 6.1 | Bash redirect tracked | |
| 6.2 | Bash append tracked | |
| 6.3 | Bash rm tracked | |
| 6.4 | Complex bash not tracked | |
| 7.1 | Non-blocking tracking failure | |
| 7.2 | Missing backup blob | |
| 8.1 | Persist across restarts | |
| 8.2 | Rewind after restart | |
| 8.3 | Session deletion cascade | |
| 9.1 | Checkpoint via REST API | |
| 9.2 | Rewind after server checkpoint | |
| 10.1 | Minimal overhead | |
| 10.2 | Large file backup | |
