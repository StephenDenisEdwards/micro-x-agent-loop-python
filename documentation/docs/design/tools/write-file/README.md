# Tool: write_file

Write content to a file, creating it and any parent directories if they don't exist.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute or relative path to the file to write |
| `content` | string | Yes | The content to write to the file |

## Behavior

- **Relative paths:** Resolved against `WorkingDirectory` from `config.json` if configured
- **Encoding:** UTF-8
- **Directory creation:** Parent directories are created automatically via `pathlib.Path.mkdir(parents=True, exist_ok=True)`
- **Overwrites:** If the file already exists, its contents are replaced

## Implementation

- Server: `mcp_servers/ts/packages/filesystem/src/tools/write-file.ts`
- Path resolution: same logic as `read_file` (relative to `FILESYSTEM_WORKING_DIR`)
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
