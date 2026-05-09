# Tool: bash

Execute shell commands on the local machine.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | Yes | The bash command to execute |

## Behavior

- **Windows:** Runs via `cmd.exe /c <command>`
- **macOS/Linux:** Runs via `/bin/sh -c <command>`
- **Timeout:** 30 seconds — process is killed if exceeded
- **Output:** Returns combined stdout + stderr
- **Exit code:** Non-zero exit codes are appended to the output
- **Working directory:** Uses `FILESYSTEM_WORKING_DIR` (the spawned process's `cwd`)

## Containment (accident prevention only — NOT adversarial sandboxing)

`bash` is the only filesystem tool that is not gated by `PathPolicy`. To catch obvious accidents, two opt-in env-var knobs apply *before* execution. **Both are string-level filters and trivially bypassable** by a determined or prompt-injected agent (`sh -c "..."`, env-var indirection, base64 pipelines, write-then-execute). Real isolation requires OS-level controls (containers, AppArmor, Windows Job Objects). See [ISSUE-005](../../../issues/ISSUE-005-bash-tool-bypasses-path-policy.md).

### `FILESYSTEM_BASH_PATH_GUARD` — default ON

When enabled, the command is tokenised (whitespace + `=` split, with quote chars stripped to expose paths inside them). Any token that looks like:

- a POSIX absolute path (`/...`), or
- a Windows drive-letter path (`C:\...`, `C:/...`), or
- a Windows UNC path (`\\server\share`), or
- a `..` traversal that resolves outside the workspace

is checked via `realpath` against `FILESYSTEM_WORKING_DIR` + `FILESYSTEM_ALLOWED_DIRS`. If any candidate lands outside, the command is refused with a clear error naming the env vars.

Set `FILESYSTEM_BASH_PATH_GUARD=false` (or `0` / `no` / `off`) to disable.

The default-on choice gives no-config users real protection against the common accident class (`cd ../..` → `rm -rf .`, `cat /etc/passwd` typo, etc.). Workflows that legitimately need to write outside the workspace via `bash` should add the destination to `FILESYSTEM_ALLOWED_DIRS` rather than disabling the guard.

### `FILESYSTEM_BASH_ALLOWED_COMMANDS` — opt-in, three modes

| Setting | Behaviour |
|---------|-----------|
| Unset | No filter — every command runs (default) |
| Empty string `""` | Deny-all kill switch |
| `git,npm,pytest,...` | Allowlist — only commands whose **first token** matches |

Pipes (`\| head`), chains (`&& rm`), subshells (`(rm ...)`), and command substitution (`$(...)`, backticks) are **not** decomposed and **not** checked. This is documented as a known gap, not a security claim — adding a real shell parser doesn't close the bypasses listed above either.

## What's already in place — not new

- **Cwd pinning.** Every command runs with `cwd: workingDir` regardless of inherited shell state. This was already true before Phase 4 of [PLAN-filesystem-navigation](../../../planning/PLAN-filesystem-navigation.md). It prevents inherited-shell-state leakage on the *initial* cwd; the model can still `cd` mid-command — that's what the path guard covers.

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
