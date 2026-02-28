# Tool: read_file

Read the contents of a file and return it as text.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute or relative path to the file to read |

## Behavior

- **Relative paths:** Resolved against `WorkingDirectory` from `config.json` if configured
- **Encoding:** UTF-8
- **Supported formats:** Plain text files and `.docx` documents
- **`.docx` support:** Uses `python-docx` to extract paragraph text

## Implementation

- Server: `mcp_servers/ts/packages/filesystem/src/tools/read-file.ts`
- Path resolution: relative paths resolved against `FILESYSTEM_WORKING_DIR` env var
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
