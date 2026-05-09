# Tool: write_file

Write content to a file, creating it and any parent directories if they don't exist.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute or relative path to the file to write |
| `content` | string | Yes | The content to write to the file |

## Behavior

- **Relative paths:** Resolved against `FILESYSTEM_WORKING_DIR`
- **Encoding:** UTF-8
- **Directory creation:** Parent directories are created automatically
- **Overwrites:** If the file already exists, its contents are replaced
- **Containment:** Path must resolve (via `realpath`) to somewhere inside `FILESYSTEM_WORKING_DIR` or `FILESYSTEM_ALLOWED_DIRS`. Absolute paths outside the allowed roots are rejected with an error naming the env var. Symlinks pointing outside are caught by `realpath`. (`bash` is *not* gated this way — see [ISSUE-005](../../../issues/ISSUE-005-bash-tool-bypasses-path-policy.md).)

## Implementation

- Server: `mcp_servers/ts/packages/filesystem/src/tools/write-file.ts`
- Path resolution + containment: `resolveAllowed(policy, path, { mustExist: false })` from `paths.ts`
- Auto-creates parent directories

## Example

```
you> Create a file called notes.txt with a summary of our conversation
```

Claude calls:
```json
{
  "name": "write_file",
  "input": {
    "path": "notes.txt",
    "content": "Summary of conversation..."
  }
}
```
