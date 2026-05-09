# Tool: delete_file

Delete a single file. Refuses directories. Path-contained and checkpoint-tracked, so `/rewind` can restore the deletion.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute or relative path to the file to delete |

## Output (structured)

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Fully resolved (and `realpath`-ed) path that was deleted |
| `deleted` | bool | Always `true` on success |
| `size_bytes` | int | Size of the file at the moment it was deleted |

## Behavior

- **File-not-found.** Errors with `file not found: <path>`. Does not silently succeed — catches typos.
- **Directory refusal.** Errors with `refusing to delete directory: <path> — use bash (rm -r / rmdir) for directory removal`. Single-file scope only.
- **Not-a-regular-file refusal.** Errors. Will not unlink sockets, devices, named pipes.
- **Containment.** Path must resolve (via `realpath`) to inside `FILESYSTEM_WORKING_DIR` or `FILESYSTEM_ALLOWED_DIRS`. Symlinks pointing outside are rejected. (`bash` is *not* gated this way — see [ISSUE-005](../../../issues/ISSUE-005-bash-tool-bypasses-path-policy.md).)
- **Checkpoint snapshot.** Annotated `destructiveHint: true`; the agent's checkpoint flow snapshots the file *before* deletion via the existing `tool_input["path"]` path. `/rewind` restores the deleted file with its original contents.
- **Symlink behaviour.** `unlink` removes the symlink itself, not its target. Containment check via `realpath` runs first — a symlink pointing outside the workspace is refused before any unlink happens.

## When to use vs `bash rm`

| Need | Use |
|------|-----|
| Delete one file | `delete_file` |
| Delete one directory | `bash rmdir` (empty) or `bash rm -r` (non-empty) |
| Delete multiple files matching a pattern | `bash rm` (or `glob` + N `delete_file` calls in parallel) |
| Recursive cleanup of a tree | `bash rm -r` |

## Examples

Successful delete:

```json
{ "name": "delete_file", "input": { "path": "build/cache/stale.tmp" } }
```

Response:

```
deleted C:\...\build\cache\stale.tmp (4096 bytes)
```

Directory refusal:

```json
{ "name": "delete_file", "input": { "path": "build/cache" } }
```

Response:

```
refusing to delete directory: C:\...\build\cache — use bash (rm -r / rmdir) for directory removal
```

## Implementation

- Server: `mcp_servers/ts/packages/filesystem/src/tools/delete-file.ts`
- Path resolution + containment: `resolveAllowed(policy, path, { mustExist: false })` from `paths.ts`, then explicit `stat` for friendly file-not-found / directory messages
- Removal: `node:fs/promises#unlink`

## Mutation tracking (Python side)

`delete_file` is in `_MUTATING_TOOL_NAMES` (`src/micro_x_agent_loop/memory/facade.py`). The checkpoint manager snapshots the file at `tool_input["path"]` *before* the tool executes; `/rewind` restores it.
