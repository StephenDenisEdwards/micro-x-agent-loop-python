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

## Mutation Tracking

The bash tool declares `is_mutating=True` and implements `predict_touched_paths()` to support best-effort file mutation tracking for the checkpoint/rewind system.

**How it works:** Before execution, `predict_touched_paths()` delegates to `bash_command_parser.extract_mutated_paths(command)`, which parses the shell command to extract likely mutated file paths.

**Detected patterns:**

| Pattern | Example | What is tracked |
|---------|---------|-----------------|
| Output redirect | `echo hi > out.txt` | `out.txt` |
| Append redirect | `echo hi >> log.txt` | `log.txt` |
| File removal | `rm foo.txt` | `foo.txt` |
| Move/rename | `mv src.txt dst.txt` | Both paths |
| Copy | `cp src.txt dst.txt` | Destination only |
| Creation | `touch new.txt`, `mkdir dir` | Target path |
| Pipe to file | `cmd \| tee out.log` | `out.log` |
| In-place edit | `sed -i 's/a/b/' file.txt` | `file.txt` |
| Permission change | `chmod 755 script.sh` | `script.sh` |
| Chained commands | `mkdir a && touch a/b` | All targets |

Read-only commands (`ls`, `git status`, `cat`, `grep`, etc.) return `[]` — no files are snapshotted.

**Opt-in activation:** Bash mutation tracking is only active when `CheckpointWriteToolsOnly=false` in config. The default (`true`) tracks only `write_file` and `append_file`.

**Limitations:** This is heuristic parsing — it cannot track mutations from arbitrary programs, variable expansions, or complex shell constructs. It will never raise on unparseable input.

## Implementation

- Server: `mcp_servers/ts/packages/filesystem/src/tools/bash.ts`
- Mutation parser: `bash_command_parser.py` (Python client-side, for checkpoint tracking)
- Uses `child_process.execFile` for non-blocking execution
- 30-second timeout; process is killed if exceeded
- On timeout, `[timed out after 30s]` is returned

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
