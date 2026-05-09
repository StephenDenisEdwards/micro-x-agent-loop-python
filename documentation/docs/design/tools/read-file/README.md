# Tool: read_file

Read a file as `cat -n`-style line-numbered text. Use `offset` / `limit` to read a specific window.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute or relative path to the file to read |
| `offset` | int | No | 1-based line number to start reading from. Default: 1 |
| `limit` | int | No | Max lines to return. Default: 2000, hard max: 10000 |

## Output (structured)

| Field | Type | Description |
|-------|------|-------------|
| `content` | string | The line-numbered text returned (also delivered as the text content block) |
| `path` | string | The fully resolved (and `realpath`-ed) path actually read |
| `size_bytes` | int | UTF-8 byte length of the **decoded full file**, not just the returned slice |
| `total_lines` | int | Total lines in the file |
| `start_line` | int | First line number in the returned slice (0 if the slice is empty) |
| `end_line` | int | Last line number in the returned slice (0 if the slice is empty) |
| `truncated` | bool | True if `limit` cut the output short |

## Behavior

- **Output format:** `cat -n` style — 6-char right-padded line number, a tab, then the line content. One line per source line.
- **Relative paths:** Resolved against `FILESYSTEM_WORKING_DIR`.
- **Encoding:** UTF-8.
- **Supported formats:** Plain text files and `.docx` documents (`.docx` extracted via `mammoth`).
- **Binary refusal:** Files containing a null byte in the first 8 KB are rejected with a clear error. `.docx` is exempt from this check (it's a zip).
- **Truncation:** If the slice doesn't reach the end of the file, a `[truncated at line N of M — use offset=N+1 to continue, or raise limit]` marker is appended so the model knows there's more.
- **Empty file:** Returns `(file is empty)` with `total_lines: 0`.
- **Offset past end:** Returns `(offset N is past end of file — file has M lines)` with an empty slice.
- **Containment:** Path must resolve (via `realpath`) to somewhere inside `FILESYSTEM_WORKING_DIR` or `FILESYSTEM_ALLOWED_DIRS`. Absolute paths outside the allowed roots are rejected with an error naming the env var. Symlinks pointing outside are caught by `realpath`. (`bash` is *not* gated this way — see [ISSUE-005](../../../issues/ISSUE-005-bash-tool-bypasses-path-policy.md).)

## Cost note

Line numbers add ~5–7 tokens per line over the raw bytes. Negligible for most files; for the 2000-line default cap that's roughly +10–14 K tokens. Pass `offset` / `limit` for large files instead of paging through the full default.

## Implementation

- Server: `mcp_servers/ts/packages/filesystem/src/tools/read-file.ts`
- Path resolution + containment: `resolveAllowed(policy, path, { mustExist: true })` from `paths.ts`
- Binary detection: scan first 8 KB for `0x00`

## Examples

Read the first 2000 lines of a file:

```json
{ "name": "read_file", "input": { "path": "src/agent.py" } }
```

Read lines 100–149 of a large file:

```json
{ "name": "read_file", "input": { "path": "large.log", "offset": 100, "limit": 50 } }
```

Read a `.docx` document (`offset`/`limit` apply to extracted text):

```json
{ "name": "read_file", "input": { "path": "CV.docx" } }
```

Sample output for a small text file:

```
     1	hello
     2	world
     3	(end)
```

Truncated output (file has 5000 lines):

```
     1	first line
     ...
  2000	two-thousandth line

[truncated at line 2000 of 5000 — use offset=2001 to continue, or raise limit]
```
