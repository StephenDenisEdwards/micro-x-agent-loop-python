# TypeScript Codegen Template — Manual Test Plan

Step-by-step walkthrough of the TypeScript codegen template migration. These tests verify that the template infrastructure, code generation, test validation, and task execution all work end-to-end after migrating from the Python template to TypeScript.

## Feature Overview

The codegen system generates task apps — small, self-contained TypeScript projects that connect to MCP servers, process data, and produce output files. The system has two parts:

1. **The TypeScript template** (`codegen-templates/template-ts/`) — sealed infrastructure files that every generated task app inherits. These handle MCP server connections, config loading, tool wrappers, file utilities, and LLM access. Generated code imports from these files but never modifies them.

2. **The codegen MCP server** (`mcp_servers/python/codegen/main.py`) — a Python MCP server that exposes two tools: `generate_code` (copies the template, calls the LLM to generate TypeScript, validates via vitest) and `run_task` (executes the generated app via `npx tsx`).

### What changed from the Python template

| Aspect | Before (Python) | After (TypeScript) |
|--------|-----------------|-------------------|
| Template location | `tools/template-py/` | `codegen-templates/template-ts/` |
| Generated code language | Python (`.py`) | TypeScript (`.ts`) |
| Dependency management | Implicit venv (`VENV_PYTHON` path) | `package.json` + `npm install` |
| Test framework | `unittest` | `vitest` |
| Task execution | `python -m tools.<task_name>` | `npx tsx src/index.ts` |
| Pipe hang workaround | Temp files for stdout/stderr | `capture_output=True` (no workaround needed) |
| `sys.unraisablehook` hack | Required | Eliminated |

### How it works

1. **`generate_code(task_name, prompt)`** — copies `codegen-templates/template-ts/` to `tools/<task_name>/` (excluding `node_modules/`), reads `src/tools.ts` for the system prompt, runs a mini agentic loop where the LLM generates TypeScript files, writes them to `src/`, runs `npm install`, then validates with `npx vitest run` (fixing failures up to 3 times).

2. **`run_task(task_name)`** — checks that `src/task.ts` exists, runs `npm install` if `node_modules/` is missing, then executes `npx tsx src/index.ts` in the task directory with a configurable timeout.

> **Prerequisites**
> - Node.js 18+ and npm installed (already required for MCP servers)
> - Python 3.11+ with the agent installed (`pip install -e .`)
> - A working `config.json` with at least one LLM provider configured
> - `.env` with a valid `ANTHROPIC_API_KEY`
> - The codegen MCP server configured in `config.json` under `McpServers`

> **Cost awareness**
> Code generation tests make real LLM API calls. Each `generate_code` call costs approximately $0.02–$0.10 depending on prompt complexity and validation rounds. Budget approximately $0.50 for a full test run.

---

## 1. Template Infrastructure

These tests verify the TypeScript template itself, independent of the codegen server.

The template's sealed files import the shared runtime via the relative path `../../_runtime/src/...`. That path is calibrated for a **synced task app** (at `tools/<name>/src/`, where it resolves to `tools/_runtime/`), not for the template directory itself (`codegen-templates/template-ts/`). So most tests below run inside a **scratch sync** — the template copied into a real `tools/` location, where its imports actually resolve. This also mirrors how the template is used in production.

### Test 1.0: Set up a scratch sync

```bash
TEST_DIR=tools/_template_test
rm -rf $TEST_DIR
mkdir -p $TEST_DIR
cp -r codegen-templates/template-ts/. $TEST_DIR/
cd $TEST_DIR
npm install --silent
```

**Expected:** Copy completes, `npm install` succeeds with no errors. The scratch sync is now ready; subsequent tests 1.1–1.5 run inside `tools/_template_test/` unless stated otherwise.

### Test 1.1: Template type-checks cleanly

```bash
npx tsc --noEmit
```

**Expected:** No errors. All infrastructure files compile under strict TypeScript.

### Test 1.2: Template prints its own tool schema (`--describe`)

```bash
npx tsx src/index.ts --describe | python3 -m json.tool
```

**Expected:** Valid JSON printed to stdout, exit code 0. The payload has:
- `server_name`: `"example_tool"` (the placeholder's `TOOL_NAME`)
- `tools`: a 1-element array describing the placeholder tool
- top-level `tool_name`, `description`, `input_schema` (the single-tool back-compat shim)

This confirms the template boots, loads its task module, and the multi-tool adapter handles the placeholder's legacy single-tool exports correctly.

> The default mode (no flags) starts a stdio MCP server and waits for client commands. `--describe` exits cleanly and is the right "did it boot?" smoke test.

### Test 1.3: Vitest runs the adapter unit tests

```bash
npx vitest run
```

**Expected:** All tests pass. At least 7 tests across one file (`src/index.test.ts`):
- 1 test for `loadJsonConfig` (ConfigFile + Base inheritance + env vars)
- 6 tests for `normalizeTools` (multi-tool adapter — see also test 9.1)

### Test 1.4: npm install creates self-contained node_modules

```bash
ls node_modules/@modelcontextprotocol/sdk
ls node_modules/zod
ls node_modules/zod-to-json-schema
ls node_modules/dotenv
```

**Expected:** All four directories exist. Dependencies are self-contained in `node_modules/`; no venv or external path needed. The Anthropic SDK is **not** a direct dependency of generated apps — it lives in `tools/_runtime/` (the shared runtime, which task apps reach via `../../_runtime/src/llm.ts`).

### Test 1.5: Config loading with ConfigFile indirection

Create a test config that uses `ConfigFile` to point at another file:

```bash
cat > /tmp/test-config.json <<'EOF'
{ "ConfigFile": "/tmp/test-config-target.json" }
EOF
cat > /tmp/test-config-target.json <<'EOF'
{ "McpServers": { "demo": { "command": "echo", "args": ["hi"] } } }
EOF
```

Then verify the template follows the indirection (use `--run` rather than `--describe`, because `--describe` only reads the static task module exports and never touches the config):

```bash
npx tsx src/index.ts --run --params '{}' --config /tmp/test-config.json 2>&1 | head -5
```

**Expected:**
```
Config: /tmp/test-config-target.json
{
  "message": "No task implemented. Edit src/task.ts."
}
```

The first line shows the resolved target path, NOT `/tmp/test-config.json`. The template correctly followed the `ConfigFile` pointer. The JSON below is the placeholder task's response — proves the run path executed end to end.

### Test 1.6: Tear down the scratch sync

```bash
cd ../..
rm -rf tools/_template_test /tmp/test-config.json /tmp/test-config-target.json
```

**Expected:** Cleanup completes silently. Subsequent sections start with a clean `tools/` tree.

---

## 2. Template Copy and Isolation

These tests verify that the codegen server correctly copies the template and protects infrastructure files.

### Test 2.1: Template copy excludes node_modules

From a Python REPL or script:

```python
import shutil
from pathlib import Path

src = Path("codegen-templates/template-ts")
dst = Path("/tmp/test-copy")
if dst.exists():
    shutil.rmtree(dst)
ignore = shutil.ignore_patterns("node_modules", "dist", "*.tsbuildinfo")
shutil.copytree(src, dst, ignore=ignore)

assert (dst / "package.json").exists()
assert (dst / "src" / "tools.ts").exists()
assert not (dst / "node_modules").exists()
print("PASS: template copied without node_modules")
```

**Expected:** Copy succeeds. `node_modules/` is excluded. All `src/` infrastructure files are present.

### Test 2.2: Duplicate task name gets suffix

```python
from mcp_servers.python.codegen.main import copy_template

# First copy
dir1, name1 = copy_template("test_dup")
print(f"First: {name1}")  # "test_dup"

# Second copy — should auto-increment
dir2, name2 = copy_template("test_dup")
print(f"Second: {name2}")  # "test_dup_2"

assert name1 == "test_dup"
assert name2 == "test_dup_2"
```

**Expected:** Second call creates `tools/test_dup_2/` instead of overwriting the first.

**Cleanup:**
```bash
rm -rf tools/test_dup tools/test_dup_2
```

---

## 3. File Parsing

### Test 3.1: Parse TypeScript files from LLM response

```python
from mcp_servers.python.codegen.main import parse_files

response = """=== task.ts ===
import { z } from "zod";
export const SERVERS: string[] = ["google"];
export const TOOL_NAME = "demo";
export const TOOL_DESCRIPTION = "Demo task.";
export const TOOL_INPUT_SCHEMA = {};
export async function handleTool(input, clients, profile, config) {
  return { ok: true };
}

=== collector.ts ===
export function collect(): string[] {
  return ["a", "b"];
}

=== collector.test.ts ===
import { describe, it, expect } from "vitest";
import { collect } from "./collector.js";
describe("collect", () => {
  it("returns items", () => { expect(collect()).toHaveLength(2); });
});
"""

files, skipped = parse_files(response)
assert "task.ts" in files
assert "collector.ts" in files
assert "collector.test.ts" in files
assert len(skipped) == 0
print(f"PASS: parsed {len(files)} files, skipped {len(skipped)}")
```

**Expected:** All three `.ts` files parsed correctly. No files skipped.

### Test 3.2: Infrastructure files are rejected

Covers every sealed file the LLM should never generate — per-task sealed files (`index.ts`, `config.ts`, `tool-loader.ts`, `tools.ts`, `tool-types.ts`) and shared runtime files (`mcp-client.ts`, `llm.ts`, `utils.ts`, `test-base.ts`, `tool-def.ts`). All ten must appear in the skipped list.

```python
response = """=== task.ts ===
export const SERVERS: string[] = [];

=== index.ts ===
// entry point — sealed
=== config.ts ===
// config loader — sealed (added with multi-tool support)
=== tool-loader.ts ===
// adapter — sealed (added with multi-tool support)
=== tools.ts ===
// per-task MCP wrappers — sealed
=== tool-types.ts ===
// per-task strict types — sealed
=== mcp-client.ts ===
// runtime — sealed
=== llm.ts ===
// runtime — sealed
=== utils.ts ===
// runtime — sealed
=== test-base.ts ===
// runtime — sealed
=== tool-def.ts ===
// runtime (added with multi-tool support) — sealed
"""

files, skipped = parse_files(response)
sealed = {"index.ts", "config.ts", "tool-loader.ts", "tools.ts", "tool-types.ts",
          "mcp-client.ts", "llm.ts", "utils.ts", "test-base.ts", "tool-def.ts"}
assert "task.ts" in files
assert sealed.isdisjoint(files), f"sealed files leaked into files: {sealed & files.keys()}"
assert sealed.issubset(skipped), f"sealed files not rejected: {sealed - set(skipped)}"
print(f"PASS: all {len(sealed)} sealed filenames rejected")
```

**Expected:** Only `task.ts` is accepted. All ten sealed filenames are in the skipped list.

### Test 3.3: Non-TypeScript files are rejected

```python
response = """=== task.ts ===
export const SERVERS: string[] = [];

=== readme.md ===
# This should be skipped

=== config.json ===
{}
"""

files, skipped = parse_files(response)
assert "task.ts" in files
assert "readme.md" in skipped
assert "config.json" in skipped
print(f"PASS: non-.ts files rejected ({skipped})")
```

**Expected:** Only `.ts` files are accepted. Markdown and JSON are skipped.

### Test 3.4: Path separators in filenames are rejected

```python
response = """=== task.ts ===
export const SERVERS: string[] = [];

=== src/task.ts ===
// LLM added src/ prefix

=== ../escape.ts ===
// Path traversal attempt
"""

files, skipped = parse_files(response)
assert "task.ts" in files
assert "src/task.ts" in skipped
assert "../escape.ts" in skipped
print(f"PASS: path separators rejected ({skipped})")
```

**Expected:** Filenames with `/` or `\` are rejected. Only flat filenames accepted.

### Test 3.5: Markdown fences are stripped

```python
response = """=== task.ts ===
```typescript
export const SERVERS: string[] = [];
export async function runTask(): Promise<void> {}
```
"""

files, skipped = parse_files(response)
code = files["task.ts"]
assert "```" not in code
assert "export const SERVERS" in code
print("PASS: markdown fences stripped")
```

**Expected:** Triple backtick fences are removed from the parsed content.

---

## 4. Code Generation (End-to-End)

These tests require the codegen MCP server to be running. Start the agent with the codegen server configured.

### Test 4.1: Generate a minimal task

```
you> Generate a task app called "hello_world" that prints "Hello from TypeScript!" and writes it to hello-output.txt.
```

**Expected:**
- The agent calls `generate_code` with task_name "hello_world"
- Progress messages show: copying template, generating code, npm install, validation
- Summary shows files written (at minimum `task.ts`)
- The task directory `tools/hello_world/` exists with `src/task.ts`
- `package.json` and infrastructure files are present

### Test 4.2: Generated task has correct exports

After test 4.1, verify the generated `task.ts` uses one of the two supported shapes (see `PLAN-codegen-multi-tool.md`):

```bash
grep -E "^export (const|async function)" tools/hello_world/src/task.ts
```

**Expected:** EITHER the legacy single-tool shape:
```
export const SERVERS: string[] = [...];
export const TOOL_NAME = "hello_world";
export const TOOL_DESCRIPTION = "...";
export const TOOL_INPUT_SCHEMA = { ... };
export async function handleTool(input, clients, profile, config) { ... }
```

OR the multi-tool shape:
```
export const SERVERS: string[] = [...];
export const TOOLS = defineTools([ ... ]);
```

The single-tool shape is the default; multi-tool only appears when the prompt explicitly described multiple related tools. There must be no `runTask` export — that was an earlier contract that no longer exists.

### Test 4.3: Generate with test files

```
you> Generate a task app called "scorer_demo" that:
- Defines a function scoreJob(job) that returns a number 0-100 based on whether the title contains "Senior" (+20), "Engineer" (+30), or "AI" (+50)
- Writes a test file for the scoring function
- The task itself just prints "Scorer ready"
```

**Expected:**
- Multiple files generated: `task.ts`, `scorer.ts`, `scorer.test.ts` (or similar)
- Validation runs and tests pass (shown in progress messages)
- Summary shows "Validation: PASSED"

### Test 4.4: npm install runs during generation

Check that `node_modules/` exists after generation:

```bash
ls tools/scorer_demo/node_modules/@modelcontextprotocol/sdk
```

**Expected:** The SDK directory exists. `npm install` ran successfully during the generation phase.

### Test 4.5: Generate with file reference

Create a criteria file:

```bash
echo "Must include: title, company, salary range" > /tmp/output-format.txt
```

```
you> Generate a task app called "format_demo" that reads jobs and formats them. See /tmp/output-format.txt for the output format requirements.
```

**Expected:**
- The codegen LLM uses `read_file` to read the criteria file (shown in progress messages: "Reading file: ...")
- Generated code follows the format specified in the file
- Multi-turn generation (2+ turns due to file reading)

**Cleanup:**
```bash
rm -rf tools/hello_world tools/scorer_demo tools/format_demo
```

---

## 5. Test Validation

### Test 5.1: Validation catches test failures

This is observable during test 4.3 if the initial generated tests don't pass. Watch the progress messages for:

```
Running 1 test file(s)...
  X failure(s) — asking LLM to fix (round 1/3)...
  Updated: scorer.test.ts
  All tests passed!
```

**Expected:** If tests fail on the first round, the server continues the conversation to fix them. Up to 3 rounds.

### Test 5.2: Vitest runs correctly in generated task

After a successful generation (e.g. from test 4.3):

```bash
cd tools/scorer_demo
npx vitest run
```

**Expected:** Tests pass independently (not just during the validation phase).

---

## 6. Task Execution

### Test 6.1: Run a generated task

After generating "hello_world" (test 4.1):

```
you> Run the hello_world task
```

**Expected:**
- Agent calls `run_task(task_name="hello_world")`
- Output shows "Hello from TypeScript!" or similar
- If the task writes a file, the file is created in the configured WorkingDirectory
- Exit code 0

### Test 6.2: Run task with MCP servers

Generate and run a task that uses real MCP servers (e.g., Gmail):

```
you> Generate a task app called "email_count" that searches Gmail for emails from the last 24 hours and prints how many were found. Use the "google" MCP server.
```

Then:

```
you> Run the email_count task
```

**Expected:**
- Task connects to the google MCP server
- Prints the email count
- Shuts down MCP servers gracefully
- No pipe hangs, no unraisablehook tracebacks

### Test 6.3: Run task auto-installs dependencies

Remove `node_modules/` from a generated task, then run it:

```bash
rm -rf tools/hello_world/node_modules
```

```
you> Run the hello_world task
```

**Expected:** The server detects missing `node_modules/` and runs `npm install` before execution. Task runs successfully.

### Test 6.4: Run task with timeout

```
you> Run a task with a very short timeout (e.g. 5 seconds) that takes a long time
```

Or directly test via the codegen server's `run_task` tool with `timeout_seconds=5`.

**Expected:**
- Task is killed after the timeout
- Result includes `timed_out: true`
- Error message mentions the timeout duration

### Test 6.5: Run non-existent task

```
you> Run a task called "does_not_exist"
```

**Expected:** Error message: "Task directory not found: tools/does_not_exist/"

### Test 6.6: Run task missing task.ts

Create a task directory without `src/task.ts`:

```bash
mkdir -p tools/broken_task/src
echo '{}' > tools/broken_task/package.json
```

```
you> Run the broken_task task
```

**Expected:** Error message: "src/task.ts not found in tools/broken_task/"

**Cleanup:**
```bash
rm -rf tools/broken_task tools/hello_world tools/email_count
```

---

## 7. Windows-Specific Regression Tests

These tests verify that the three original Windows issues are resolved.

### Test 7.1: No VENV_PYTHON dependency

Verify the codegen server code has no reference to `VENV_PYTHON`:

```bash
grep -r "VENV_PYTHON" mcp_servers/python/codegen/main.py
```

**Expected:** No matches. The `VENV_PYTHON` path hack is completely removed.

### Test 7.2: No pipe inheritance workaround in run_task

Verify `run_task` uses `capture_output=True` (not temp files):

```bash
grep "capture_output" mcp_servers/python/codegen/main.py
```

**Expected:** `capture_output=True` is used. No `tempfile.TemporaryFile()` workaround.

### Test 7.3: No sys.unraisablehook in template

Verify the TypeScript template has no equivalent of the Python hack:

```bash
grep -r "unraisablehook" codegen-templates/template-ts/
```

**Expected:** No matches. The Node.js runtime doesn't need this workaround.

### Test 7.4: Task execution doesn't hang (live test)

Generate and run a task that connects to at least one MCP server:

```
you> Generate and run a task called "server_test" that connects to the filesystem server and reads pyproject.toml, then prints the first line.
```

**Expected:**
- Task completes within a few seconds
- No hanging on stdout/stderr capture
- Process exits cleanly
- No orphan MCP server processes left running

Verify no orphan processes:

```bash
# On Windows
tasklist | findstr node
# On Linux/macOS
ps aux | grep node
```

**Expected:** No lingering node processes from the task execution.

---

## 8. Template File Verification

### Test 8.1: All infrastructure files present

```bash
for f in index.ts config.ts tool-loader.ts tools.ts tool-types.ts task.ts; do
  test -f codegen-templates/template-ts/src/$f && echo "OK: $f" || echo "MISSING: $f"
done
for f in mcp-client.ts llm.ts utils.ts test-base.ts tool-def.ts; do
  test -f tools/_runtime/src/$f && echo "OK: $f" || echo "MISSING: $f"
done
```

**Expected:** All files present. Per-task sealed files live in `codegen-templates/template-ts/src/`; the shared runtime (including the new `tool-def.ts` for multi-tool support) lives in `tools/_runtime/src/`.

### Test 8.2: Package.json has correct dependencies

```bash
node -e "const p = require('./codegen-templates/template-ts/package.json'); console.log(Object.keys(p.dependencies).sort().join(', ')); console.log(Object.keys(p.devDependencies).sort().join(', '))"
```

**Expected:**
- Dependencies: `@modelcontextprotocol/sdk, dotenv, zod, zod-to-json-schema`
- Dev dependencies: `@types/node, tsx, typescript, vitest`

Note: `@anthropic-ai/sdk` is **not** here — it lives in `tools/_runtime/package.json` (the shared runtime that task apps reach via `../../_runtime/src/llm.ts`). Each generated app's own `package.json` only needs the MCP SDK and Zod, not the LLM SDK.

### Test 8.3: Tools.ts covers all MCP wrappers

Count the exported async functions in `tools.ts`:

```bash
grep -c "^export async function" codegen-templates/template-ts/src/tools.ts
```

**Expected:** 50+ exported functions (current count is 58; was 40+ at original migration time). One per upstream MCP tool from gmail / linkedin / web / github / etc. The count grows whenever a new MCP server's wrapper is added.

### Test 8.4: MCP client handles connection and tool calls

This is implicitly tested by test 6.2 (running a task with MCP servers). The MCP client connects, calls tools, handles structured/text responses, and disconnects cleanly.

---

## 9. Multi-Tool Support

These tests verify the multi-tool extension — a task app can expose multiple related MCP tools from one server via a `TOOLS: ToolDef[]` export. The legacy single-tool shape (`TOOL_NAME` / `TOOL_DESCRIPTION` / `TOOL_INPUT_SCHEMA` / `handleTool`) continues to work unchanged. See `PLAN-codegen-multi-tool.md`.

### Test 9.1: Template adapter unit tests pass

```bash
cd codegen-templates/template-ts
npm test
```

**Expected:** All tests pass — at minimum:
- 1 test for `loadJsonConfig` (ConfigFile + Base inheritance + env vars)
- 6 tests for `normalizeTools` (TOOLS as-is, legacy synthesis, dir-basename fallback, duplicate-name throw, missing-both throw, missing-name throw)

### Test 9.2: Single-tool `--describe` keeps the back-compat shim

Pick an existing single-tool app (e.g. `tools/jobserve_rss_processor/`):

```bash
cd tools/jobserve_rss_processor
npx tsx src/index.ts --describe | python3 -m json.tool
```

**Expected:** Output has BOTH shapes — the new `tools: [...]` array AND the legacy top-level `tool_name` / `description` / `input_schema`:

```json
{
  "server_name": "jobserve_rss_processor",
  "tools": [
    { "tool_name": "...", "description": "...", "input_schema": {...} }
  ],
  "tool_name": "...",
  "description": "...",
  "input_schema": {...}
}
```

The duplicated singular fields appear ONLY when `tools.length === 1`. Older readers (anything still reading the top-level fields) continue to work for single-tool apps.

### Test 9.3: Generate a multi-tool task

```
you> Generate a task app called "note_app" that exposes two related MCP tools:
  - "add_note" that takes a title and body string and appends a markdown entry to notes.md
  - "list_notes" that reads notes.md and returns the titles
Both tools should share the same notes.md file. Use the multi-tool TOOLS shape.
```

**Expected:**
- The LLM produces a `task.ts` that imports `defineTools` from `../../_runtime/src/tool-def.js`
- Exports `TOOLS = defineTools([...])` with two entries
- May export `SERVER_NAME = "note_app"` (or omit it — dir basename is fine)
- Validation passes (any test files run via vitest)

### Test 9.4: Multi-tool `--describe` lists each tool

```bash
cd tools/note_app
npx tsx src/index.ts --describe | python3 -m json.tool
```

**Expected:**
- `server_name` is set
- `tools` array has 2 entries, one per defined tool
- Each entry has its own `tool_name`, `description`, `input_schema`
- NO top-level singular `tool_name` / `description` / `input_schema` (because `tools.length > 1`)

### Test 9.5: `--run --tool <name>` selects the right tool

```bash
cd tools/note_app
npx tsx src/index.ts --run --tool add_note --params '{"title":"test","body":"hello"}'
npx tsx src/index.ts --run --tool list_notes --params '{}'
```

**Expected:**
- First command appends a note; output JSON shows success.
- Second command returns the list including the new title.
- Running `--run` WITHOUT `--tool` on a multi-tool app prints an error: *"This app exposes 2 tools; pick one with --tool <name>. Available: add_note, list_notes"* and exits non-zero.
- Single-tool apps (e.g. `jobserve_rss_processor`) continue to accept `--run` without `--tool` (it defaults to the only tool).

### Test 9.6: Duplicate tool names throw at startup

Create a broken multi-tool `task.ts` in a scratch task:

```bash
mkdir -p tools/dup_test/src && cp codegen-templates/template-ts/src/{index,config,tool-loader,tools,tool-types}.ts tools/dup_test/src/ && cp codegen-templates/template-ts/package.json tools/dup_test/
cat > tools/dup_test/src/task.ts <<'EOF'
import { z } from "zod";
import { defineTools } from "../../_runtime/src/tool-def.js";
export const SERVERS: string[] = [];
export const TOOLS = defineTools([
  { name: "dup", description: "a", inputSchema: { x: z.string() },
    handler: async () => ({ ok: true }) },
  { name: "dup", description: "b", inputSchema: { y: z.string() },
    handler: async () => ({ ok: true }) },
]);
EOF
cd tools/dup_test && npm install --silent
npx tsx src/index.ts --describe
```

**Expected:** Process exits non-zero with stderr containing `TOOLS contains duplicate tool name: dup`. The collision is caught at startup, not at first tool call.

**Cleanup:**
```bash
rm -rf tools/dup_test
```

### Test 9.7: Manifest gets `tools[]` array for multi-tool apps

After generating `note_app` (test 9.3):

```bash
python3 -c "import json; m = json.load(open('tools/manifest.json')); print(json.dumps(m['note_app'], indent=2))"
```

**Expected:** The entry has a `tools: [...]` array with 2 entries (one per defined tool). The legacy top-level `tool_name` / `description` / `input_schema` fields are also present but may carry the SERVER name and only the first tool's schema (these are the back-compat shim and are not authoritative for multi-tool apps).

`codegen__list_tasks` should render the task with a nested per-tool listing:

```
1 task(s):
  note_app — ... (2 tools)
    add_note — ...
      - title: string (required) ...
      - body: string (required) ...
    list_notes — ...
```

### Test 9.8: Single-tool legacy apps still work end-to-end

Pick an existing legacy single-tool app and verify zero-edit back-compat:

```bash
cd tools/jobserve_email_processor
git diff src/task.ts  # confirm no edits since the multi-tool refactor
npm test
npx tsx src/index.ts --describe | python3 -c "import sys,json; d=json.load(sys.stdin); assert len(d['tools'])==1; assert 'tool_name' in d; print('PASS: legacy app unchanged, describe still has singular fields')"
```

**Expected:**
- `git diff` shows no changes to `task.ts` since the multi-tool feature shipped (only the sealed `index.ts`, `config.ts`, `tool-loader.ts` were re-synced from the template).
- Tests pass.
- Describe output has exactly 1 tool plus the legacy singular fields.

**Cleanup:**
```bash
rm -rf tools/note_app
```

---

## Cleanup

Remove any test task directories:

```bash
rm -rf tools/hello_world tools/scorer_demo tools/format_demo
rm -rf tools/email_count tools/server_test tools/broken_task
rm -rf tools/test_dup tools/test_dup_2
rm -rf tools/note_app tools/dup_test
rm -f /tmp/test-config.json /tmp/output-format.txt
```

---

## Test Summary Checklist

| # | Feature | Status |
|---|---------|--------|
| 1.0 | Scratch sync setup | |
| 1.1 | Template type-checks | |
| 1.2 | Template `--describe` smoke test | |
| 1.3 | Vitest runs adapter tests | |
| 1.4 | Self-contained node_modules | |
| 1.5 | ConfigFile indirection | |
| 1.6 | Scratch sync teardown | |
| 2.1 | Copy excludes node_modules | |
| 2.2 | Duplicate name auto-increment | |
| 3.1 | Parse TypeScript files | |
| 3.2 | Infrastructure files rejected | |
| 3.3 | Non-TypeScript rejected | |
| 3.4 | Path separators rejected | |
| 3.5 | Markdown fences stripped | |
| 4.1 | Generate minimal task | |
| 4.2 | Correct task exports | |
| 4.3 | Generate with tests | |
| 4.4 | npm install during generation | |
| 4.5 | Generate with file reference | |
| 5.1 | Validation catches failures | |
| 5.2 | Vitest runs independently | |
| 6.1 | Run generated task | |
| 6.2 | Run task with MCP servers | |
| 6.3 | Auto-install dependencies | |
| 6.4 | Task timeout | |
| 6.5 | Non-existent task error | |
| 6.6 | Missing task.ts error | |
| 7.1 | No VENV_PYTHON dependency | |
| 7.2 | No pipe workaround | |
| 7.3 | No unraisablehook hack | |
| 7.4 | No execution hang | |
| 8.1 | All infrastructure files present | |
| 8.2 | Correct dependencies | |
| 8.3 | Full tool wrapper coverage | |
| 8.4 | MCP client works end-to-end | |
| 9.1 | Template adapter unit tests pass | |
| 9.2 | Single-tool describe keeps back-compat shim | |
| 9.3 | Generate multi-tool task | |
| 9.4 | Multi-tool describe lists each tool | |
| 9.5 | --tool flag selects the right tool | |
| 9.6 | Duplicate tool names throw at startup | |
| 9.7 | Manifest gets tools[] for multi-tool | |
| 9.8 | Single-tool legacy apps still work | |
