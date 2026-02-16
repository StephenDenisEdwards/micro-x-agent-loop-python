# Tool: bash

Execute shell commands on the local machine.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | Yes | The bash command to execute |

## Behavior

- **Windows:** Runs via `cmd.exe /c <command>`
- **macOS/Linux:** Runs via system shell
- **Timeout:** 30 seconds — process is killed if exceeded
- **Output:** Returns combined stdout + stderr
- **Exit code:** Non-zero exit codes are appended to the output
- **Working directory:** Uses `WorkingDirectory` from `config.json` if configured

## Implementation

- Source: `src/micro_x_agent_loop/tools/bash_tool.py`
- Uses `asyncio.create_subprocess_shell` for non-blocking execution
- `asyncio.wait_for` enforces the 30-second timeout
- On timeout, the process is killed and `[timed out after 30s]` is returned

## Example

```
you> List all Python files in the current directory
```

Claude calls:
```json
{
  "name": "bash",
  "input": { "command": "dir *.py /s" }
}
```

## Security

This tool executes arbitrary shell commands by design. The user accepts full responsibility for commands the agent runs.
