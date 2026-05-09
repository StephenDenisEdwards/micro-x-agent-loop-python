# Tool: read_file

Read the contents of a file and return it as text.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute or relative path to the file to read |

## Behavior

- **Relative paths:** Resolved against `FILESYSTEM_WORKING_DIR`
- **Encoding:** UTF-8
- **Supported formats:** Plain text files and `.docx` documents
- **`.docx` support:** Extracted via `mammoth`
- **Containment:** Path must resolve (via `realpath`) to somewhere inside `FILESYSTEM_WORKING_DIR` or `FILESYSTEM_ALLOWED_DIRS`. Absolute paths outside the allowed roots are rejected with an error naming the env var. Symlinks pointing outside are caught by `realpath`. (`bash` is *not* gated this way — see [ISSUE-005](../../../issues/ISSUE-005-bash-tool-bypasses-path-policy.md).)

## Implementation

- Server: `mcp_servers/ts/packages/filesystem/src/tools/read-file.ts`
- Path resolution + containment: `resolveAllowed(policy, path, { mustExist: true })` from `paths.ts`
- `.docx` files are detected by extension and extracted via `mammoth`
- Large file output may be truncated by the agent's `MaxToolResultChars` limit

## Example

```
you> Read my CV
```

Claude calls:
```json
{
  "name": "read_file",
  "input": { "path": "CV.docx" }
}
```

If `WorkingDirectory` is `C:\Users\you\documents`, the tool reads `C:\Users\you\documents\CV.docx`.
