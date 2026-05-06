# Manual Test Plan — Filesystem `grep` / `glob` + `PathPolicy`

**Code under test:**
- `mcp_servers/ts/packages/filesystem/src/tools/grep.ts`
- `mcp_servers/ts/packages/filesystem/src/tools/glob.ts`
- `mcp_servers/ts/packages/filesystem/src/paths.ts` (`loadPathPolicy`, `resolveAllowed`)
- `mcp_servers/ts/packages/filesystem/src/index.ts` (env-var wiring)

**Related issue:** [ISSUE-005](../issues/ISSUE-005-bash-tool-bypasses-path-policy.md) — bash bypasses the policy this doc validates.

---

## Prerequisites

- Node 20+ on PATH
- `npm install` has been run in `mcp_servers/ts/`
- The filesystem package has been built: `cd mcp_servers/ts/packages/filesystem && npm run build`
- A directory you control to use as `FILESYSTEM_WORKING_DIR` (the repo root works fine).

The tests below use a small JSON-RPC harness invoked via `node`. Each test is self-contained — copy the script, save to `/tmp/test.mjs`, run with the env vars shown, and compare output against the **Expected** block.

### Reusable harness

Save once as `/tmp/mcp_call.mjs`:

```js
import { spawn } from "node:child_process";

const SERVER = process.env.SERVER_PATH ?? "mcp_servers/ts/packages/filesystem/dist/index.js";
const REQUEST = JSON.parse(process.env.REQUEST);

const child = spawn("node", [SERVER], { stdio: ["pipe", "pipe", "inherit"] });
let buf = "";
child.stdout.on("data", (d) => {
  buf += d.toString();
  const lines = buf.split("\n"); buf = lines.pop() ?? "";
  for (const line of lines) {
    if (!line.trim()) continue;
    let msg; try { msg = JSON.parse(line); } catch { continue; }
    if (msg.id === 1) {
      child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 2, ...REQUEST }) + "\n");
    } else if (msg.id === 2) {
      console.log(JSON.stringify(msg.result, null, 2));
      child.kill();
    }
  }
});
child.stdin.write(JSON.stringify({
  jsonrpc: "2.0", id: 1, method: "initialize",
  params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "t", version: "0" } },
}) + "\n");
```

Run it (PowerShell example):

```powershell
$env:FILESYSTEM_WORKING_DIR = "C:\Users\steph\source\repos\micro-x-agent-loop-python"
$env:REQUEST = '{"method":"tools/list"}'
node /tmp/mcp_call.mjs
```

---

## Test 1 — Tools register

**Goal:** Confirm `grep` and `glob` show up alongside the existing tools.

**Steps:**

```powershell
$env:FILESYSTEM_WORKING_DIR = (Get-Location).Path
$env:REQUEST = '{"method":"tools/list"}'
node /tmp/mcp_call.mjs | Select-String '"name"'
```

**Expected:** the output contains `grep` and `glob` plus the existing `bash`, `read_file`, `write_file`, `append_file` (and `save_memory` if `USER_MEMORY_DIR` is set).

---

## Test 2 — `grep` files-with-matches mode

**Goal:** Default mode returns just paths, sorted by ripgrep's normal traversal.

**Steps:**

```powershell
$env:FILESYSTEM_WORKING_DIR = (Get-Location).Path
$env:REQUEST = '{"method":"tools/call","params":{"name":"grep","arguments":{"pattern":"registerGrep","path":"mcp_servers/ts/packages/filesystem/src","output_mode":"files_with_matches"}}}'
node /tmp/mcp_call.mjs
```

**Expected:**
- `isError` is absent or `false`.
- `structuredContent.results` lists at least `tools/grep.ts` and `index.ts`.
- `structuredContent.match_count` ≥ 2.
- `structuredContent.truncated` is `false`.

---

## Test 3 — `grep` content mode with line numbers

**Goal:** Content mode returns matching lines with `path:line:match` format.

**Steps:**

```powershell
$env:REQUEST = '{"method":"tools/call","params":{"name":"grep","arguments":{"pattern":"registerGlob","path":"mcp_servers/ts/packages/filesystem/src","output_mode":"content","line_numbers":true}}}'
node /tmp/mcp_call.mjs
```

**Expected:**
- Each line of `results` matches `<absolute path>:<number>:<match line>`.
- Includes a hit in `tools/glob.ts` and one in `index.ts`.

---

## Test 4 — `grep` with `glob` filter narrows the search

**Goal:** Confirm the `glob` argument is forwarded to ripgrep.

**Steps:**

```powershell
$env:REQUEST = '{"method":"tools/call","params":{"name":"grep","arguments":{"pattern":"registerGlob","path":"mcp_servers/ts/packages/filesystem/src","output_mode":"content","glob":"index.ts"}}}'
node /tmp/mcp_call.mjs
```

**Expected:** results contain hits only from `index.ts`, none from `tools/glob.ts` or other files.

---

## Test 5 — `grep` no-match returns no error

**Goal:** Ripgrep exits 1 on no matches; the wrapper must NOT treat that as an error.

**Steps:**

```powershell
$env:REQUEST = '{"method":"tools/call","params":{"name":"grep","arguments":{"pattern":"a-string-that-definitely-does-not-exist-xyz123","path":"mcp_servers/ts/packages/filesystem/src"}}}'
node /tmp/mcp_call.mjs
```

**Expected:**
- `isError` is absent or `false`.
- `content[0].text` is exactly `(no matches)`.
- `structuredContent.match_count` is `0`.

---

## Test 6 — `glob` finds files, sorted by mtime descending

**Goal:** Confirm pattern matching and the mtime sort.

**Steps:**

```powershell
$env:REQUEST = '{"method":"tools/call","params":{"name":"glob","arguments":{"pattern":"mcp_servers/ts/packages/filesystem/src/**/*.ts"}}}'
node /tmp/mcp_call.mjs
```

**Expected:**
- `structuredContent.paths` contains `paths.ts`, `index.ts`, `tools/grep.ts`, `tools/glob.ts`, etc.
- `structuredContent.total` ≥ 5.
- The most recently modified file appears first. Verify by touching one and re-running:

```powershell
(Get-Item mcp_servers\ts\packages\filesystem\src\paths.ts).LastWriteTime = (Get-Date)
node /tmp/mcp_call.mjs
```

`paths.ts` should now be the first entry.

---

## Test 7 — `head_limit` truncation message

**Goal:** When match count exceeds `head_limit`, the response signals truncation and tells the agent how to recover.

**Steps:**

```powershell
$env:REQUEST = '{"method":"tools/call","params":{"name":"grep","arguments":{"pattern":"the","path":"documentation","output_mode":"content","head_limit":5}}}'
node /tmp/mcp_call.mjs
```

**Expected:**
- `structuredContent.results` has at most 5 lines.
- `structuredContent.truncated` is `true`.
- `content[0].text` ends with `[truncated to 5 of N lines — narrow with glob/type or raise head_limit]`.

---

## Test 8 — Path policy denies absolute paths outside `FILESYSTEM_WORKING_DIR`

**Goal:** Without `FILESYSTEM_ALLOWED_DIRS`, an absolute path outside the working dir is rejected with a helpful error.

**Steps:**

```powershell
Remove-Item Env:FILESYSTEM_ALLOWED_DIRS -ErrorAction SilentlyContinue
$env:FILESYSTEM_WORKING_DIR = (Get-Location).Path
$env:REQUEST = '{"method":"tools/call","params":{"name":"grep","arguments":{"pattern":"anything","path":"C:\\Windows\\System32"}}}'
node /tmp/mcp_call.mjs
```

(Linux/macOS equivalent: `"path":"/etc"`.)

**Expected:**
- `isError` is `true`.
- `content[0].text` matches `grep error: Path "C:\Windows\System32" is outside the allowed roots. Allowed:\n  - <workingDir>\n(set FILESYSTEM_ALLOWED_DIRS to add more, separated by ";")` (or `:` on Linux/macOS).

---

## Test 9 — `FILESYSTEM_ALLOWED_DIRS` opens an extra root

**Goal:** Adding a path to `FILESYSTEM_ALLOWED_DIRS` makes it accessible without changing `FILESYSTEM_WORKING_DIR`.

**Steps:**

```powershell
$env:FILESYSTEM_WORKING_DIR = (Get-Location).Path
$env:FILESYSTEM_ALLOWED_DIRS = "C:\Windows\System32"
$env:REQUEST = '{"method":"tools/call","params":{"name":"grep","arguments":{"pattern":"kernel","glob":"kernel32.dll","path":"C:\\Windows\\System32"}}}'
node /tmp/mcp_call.mjs
Remove-Item Env:FILESYSTEM_ALLOWED_DIRS
```

**Expected:**
- The "outside the allowed roots" error from Test 8 does **not** appear.
- The call may still surface OS-level access-denied messages in `content[0].text` (`Access is denied. (os error 5)` on locked subdirectories) — that is correct: the policy permits the request, the OS gates the actual read.

---

## Test 10 — Multi-root via `path.delimiter`

**Goal:** `FILESYSTEM_ALLOWED_DIRS` parses multiple roots with the OS delimiter (`;` Windows, `:` Linux/macOS).

**Steps (Windows):**

```powershell
$env:FILESYSTEM_WORKING_DIR = "C:\Users\steph\source\repos\micro-x-agent-loop-python"
$env:FILESYSTEM_ALLOWED_DIRS = "C:\Windows\System32;C:\Program Files"
$env:REQUEST = '{"method":"tools/list"}'
node /tmp/mcp_call.mjs
```

Then run the Test 9 command. Then change `path` to one inside `C:\Program Files` and re-run.

**Expected:** both extra roots are accepted; a path outside all three roots still triggers the Test 8 denial.

---

## Test 11 — Symlink cannot escape

**Goal:** A symlink inside `FILESYSTEM_WORKING_DIR` pointing outside it must be rejected — `realpath` resolution defeats prefix-only checks.

**Steps (Linux/macOS or Windows with admin shell):**

```bash
cd $FILESYSTEM_WORKING_DIR
ln -s /etc/passwd ./escape-link
```

```powershell
# Windows (admin elevated):
New-Item -ItemType SymbolicLink -Path .\escape-link -Target C:\Windows\System32\drivers\etc\hosts
```

```powershell
$env:REQUEST = '{"method":"tools/call","params":{"name":"grep","arguments":{"pattern":"root","path":"escape-link"}}}'
node /tmp/mcp_call.mjs
```

**Expected:**
- `isError` is `true`.
- The error message names "outside the allowed roots".
- The file is **not** read.

Cleanup: `rm escape-link` / `Remove-Item .\escape-link`.

---

## Test 12 — Agent prefers `grep` over `read_file` for searches

**Goal:** Validate the tool description nudges the model toward `grep` when the user asks "find X" without naming a file. Description-driven behaviour, so this is a soft assertion — re-run a few times if needed.

**Steps:**

1. Start the agent normally: `python -m micro_x_agent_loop`
2. Pick a string that exists in multiple files, e.g. `registerGlob`.
3. Prompt: `Find all references to registerGlob in this codebase.`

**Expected:**
- The first tool call is `grep` (not `read_file`).
- The call uses `output_mode: "files_with_matches"` or `"content"`, not a whole-file read.
- The agent does **not** call `read_file` on every match before answering — if it summarises directly from grep output, the description is doing its job.

If the agent reads files instead of grepping, the description needs further tightening — adjust in `mcp_servers/ts/packages/filesystem/src/tools/grep.ts` and rebuild.

---

## Regression checklist

After any change to `paths.ts`, `grep.ts`, `glob.ts`, or the env-var wiring in `index.ts`, re-run at minimum:

- Test 1 (registration)
- Test 2 (basic grep)
- Test 5 (no-match handling)
- Test 8 (denial)
- Test 9 (allowlist)

The full suite is worth running before any tagged release of the filesystem package.
