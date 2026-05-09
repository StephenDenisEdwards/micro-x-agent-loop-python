# Tool: edit_file

Surgical exact-string edit to an existing file. Replaces `old_string` with `new_string`; uniqueness is enforced unless `replace_all=true`.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute or relative path to the file to edit |
| `old_string` | string | Yes | Exact text to find. Include enough surrounding context to be unique |
| `new_string` | string | Yes | Replacement text |
| `replace_all` | bool | No | Replace every occurrence of `old_string`. Default: `false` (require uniqueness) |

## Output (structured)

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Fully resolved (and `realpath`-ed) path that was edited |
| `replacements` | int | Number of replacements actually made |

## Behavior

- **Exact-string only.** No regex, no fuzzy matching. The model must provide enough surrounding context in `old_string` for the match to be unique (or set `replace_all=true`).
- **Uniqueness check.** If `old_string` appears multiple times and `replace_all=false`, the call fails with the match count and a hint: *"add surrounding context or set replace_all=true"*.
- **No-op refusal.** If `old_string == new_string` the call fails immediately rather than rewriting the file unchanged.
- **Empty `old_string` refusal.** Always rejected — there is no sensible interpretation.
- **File-not-found.** Errors with `file not found: <path>`. Does **not** auto-create the file. Use `write_file` to create.
- **Not a regular file.** Errors. Will not edit directories, sockets, devices.
- **Line endings.** Detects the file's existing EOL convention (CRLF vs LF) by scanning the first 64 KB. `old_string` and `new_string` are normalised to that EOL before matching, and the file is written back with the same EOL. **Critical on Windows** — without this, an LF `old_string` would not match a CRLF file.
- **UTF-8 BOM.** Preserved on write if the original file had one.
- **Binary refusal.** Files containing a null byte in the first 8 KB are refused with a clear error.
- **Size limit.** Files larger than 5 MB (default) are refused. Override via `FILESYSTEM_EDIT_MAX_BYTES` env var.
- **Atomic write.** Writes to a same-directory `.<base>.<uuid>.tmp` file, `fsync`s, then `rename`s over the original. A crash between write and rename leaves the original intact.
- **Mode preservation.** Best-effort — the new file inherits the original's permission bits (`mode & 0o777`).
- **Containment.** Path must resolve (via `realpath`) to inside `FILESYSTEM_WORKING_DIR` or `FILESYSTEM_ALLOWED_DIRS`. Symlinks pointing outside are rejected. (`bash` is *not* gated this way — see [ISSUE-005](../../../issues/ISSUE-005-bash-tool-bypasses-path-policy.md).)
- **Mutation tracking.** Annotated `destructiveHint: true`; the agent's checkpoint system snapshots the file before the edit so `/rewind` can restore it.

## When to use vs the other write tools

| Need | Use |
|------|-----|
| Change a few lines in an existing file | `edit_file` |
| Create a new file | `write_file` |
| Replace the entire contents of a file | `write_file` |
| Add lines to the end of an existing file | `append_file` |
| Anything regex / sed-like | Combine `read_file` (for line numbers) + `edit_file` for each change. Do **not** use `bash sed` / `awk` |

## Examples

Single-occurrence edit:

```json
{
  "name": "edit_file",
  "input": {
    "path": "src/agent.py",
    "old_string": "def run(self, prompt):\n    return self._loop(prompt)",
    "new_string": "def run(self, prompt: str) -> str:\n    return self._loop(prompt)"
  }
}
```

Successful response:

```
edited C:\...\src\agent.py: 1 replacement
```

Non-unique `old_string`:

```
old_string is not unique (4 matches) in C:\...\src\agent.py — add surrounding context or set replace_all=true
```

Bulk rename within a file:

```json
{
  "name": "edit_file",
  "input": {
    "path": "src/api.py",
    "old_string": "user_id",
    "new_string": "account_id",
    "replace_all": true
  }
}
```

## Implementation

- Server: `mcp_servers/ts/packages/filesystem/src/tools/edit-file.ts`
- Path resolution + containment: `resolveAllowed(policy, path, { mustExist: false })` from `paths.ts`, then explicit `stat` for the friendly file-not-found message
- EOL detection: first 64 KB scanned for `\r\n`
- BOM detection: first three bytes match `EF BB BF`
- Binary detection: first 8 KB scanned for `0x00`
- Atomic write: `fs.open` → `writeFile` → `sync` → `close` → `rename`

## Mutation tracking (Python side)

`edit_file` is in `_MUTATING_TOOL_NAMES` (`src/micro_x_agent_loop/memory/facade.py`). The checkpoint manager snapshots the file at `tool_input["path"]` before execution; `/rewind` restores it.
