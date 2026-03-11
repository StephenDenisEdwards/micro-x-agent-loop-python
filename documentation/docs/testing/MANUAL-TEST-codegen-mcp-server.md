# Codegen MCP Server Generation — Manual Test Plan (Steps 2 & 3)

**Status: Not yet tested** (2026-03-11)

Tests whether the codegen pipeline correctly generates MCP servers with typed input schemas, profile configuration, and manifest registration — and whether the agent can discover and call them on demand.

Depends on Step 1 (schema negotiation directive). See `MANUAL-TEST-codegen-parameterisation.md` for Step 1 tests.

## What to Look For

### Step 2: Generation

1. **Does `generate_code` produce a valid MCP server?** The generated `task.ts` should export `TOOL_NAME`, `TOOL_DESCRIPTION`, `TOOL_INPUT_SCHEMA`, and `handleTool`.
2. **Is `profile.json` generated correctly?** Values from the prompt should appear in the profile, not hardcoded in the code.
3. **Does `tools/manifest.json` get updated?** New entry with tool name, description, and server config.
4. **Do vitest tests still pass?** Tests should import `handleTool` directly, not spin up an MCP server.
5. **Does `run_task` still work?** Standalone execution via `--run` flag should produce output.

### Step 3: Discovery & Integration

6. **Does tool search find manifest tools?** Search by keyword should return generated tools.
7. **Does on-demand connection work?** Calling a manifest tool should trigger MCP server startup.
8. **Is the connection cached?** Second call in same session should not reconnect.
9. **Does the tool return structured results?** The agent should receive the `handleTool` return value.

---

## Test 1: Simple Email Summary — Full Pipeline

**Prompt:**
```
Generate a reusable app that reads my last N emails and creates an email-summary.md file summarising each one with sender, subject, date, and a one-line summary.
```

**Expected flow:**
1. Agent proposes params/profile split (Step 1 behaviour)
2. User confirms
3. Agent calls `generate_code` with the agreed contract
4. Generated `task.ts` exports:
   - `TOOL_NAME = "email_summary"`
   - `TOOL_INPUT_SCHEMA` with `count` (number, default 20) and `outputFile` (string)
   - `handleTool` that calls `gmailSearch`/`gmailRead`
5. `profile.json` is empty or not generated (no user-specific data)
6. `tools/manifest.json` has entry for `email_summary`
7. Vitest passes

**Follow-up: Run via `run_task`:**
```
Run the email_summary task
```
Should execute via `--run` mode and produce output.

**Follow-up: Discover via tool search:**
```
Search for email tools
```
Should find `email_summary__email_summary` in results.

---

## Test 2: Job Search with Profile — Complex Pipeline

**Prompt:**
```
Generate a reusable app from job-search-prompt-v3.txt
```

**Expected flow:**
1. Agent proposes params/profile split (complex — skills, rate, exclusions in profile)
2. User confirms
3. Generated `task.ts` has:
   - `TOOL_INPUT_SCHEMA` with `days`, `outputDir`
   - `handleTool` reads `profile.skills`, `profile.rate`, etc.
4. `profile.json` contains all user-specific data from the prompt
5. Manifest updated

**Key checks:**
- Profile values are read from `profile` parameter, not hardcoded
- `TOOL_INPUT_SCHEMA` uses Zod with `.default()` and `.describe()`
- `SERVERS` includes the correct upstream servers (e.g. `["google"]`)

---

## Test 3: Calendar Briefing — Minimal Profile

**Prompt:**
```
Generate a reusable app that fetches my calendar events for the next N days and creates a daily-briefing.md with each day's events formatted as a schedule, including event title, time, location, and attendees.
```

**Expected:**
- `TOOL_INPUT_SCHEMA`: `{ days: z.number().default(1), outputFile: z.string().default("daily-briefing.md") }`
- `profile.json`: empty or minimal (maybe `calendar_id`)
- `SERVERS`: `["google"]`

**Key check:** Does the LLM correctly use the new exports format instead of the old `runTask` format?

---

## Test 4: Standalone Execution (`run_task`)

After generating any app from Tests 1-3:
```
codegen__run_task(task_name="<task_name>")
```

**Expected:**
- Runs `npx tsx src/index.ts --run --config ...`
- Connects upstream MCP servers
- Calls `handleTool` with default parameters
- Prints JSON result to stdout
- Exits cleanly

**What to watch for:**
- Does `--run` mode work correctly?
- Does the generated app find its `profile.json`?
- Are upstream MCP connections established and shut down properly?

---

## Test 5: MCP Server Mode (Direct)

After generating an app, manually test MCP server mode:
```bash
cd tools/<task_name>
npx tsx src/index.ts
```

**Expected:**
- Server starts on stdio (no output to stdout — MCP transport)
- Logging goes to stderr
- Responds to MCP `tools/list` and `tools/call` requests

**Note:** This is a low-level test. The primary integration test is via the agent (Test 7).

---

## Test 6: Manifest Validation

After generating 2+ apps, check `tools/manifest.json`:

**Expected format:**
```json
{
  "email_summary": {
    "tool_name": "email_summary",
    "description": "...",
    "created": "2026-03-11",
    "server": {
      "transport": "stdio",
      "command": "npx",
      "args": ["tsx", "src/index.ts", "--config", "../../config.json"],
      "cwd": "tools/email_summary/"
    }
  },
  "job_search": { ... }
}
```

**What to check:**
- Each entry has `tool_name`, `description`, `created`, `server` with `transport`, `command`, `args`, `cwd`
- `tool_name` matches the `TOOL_NAME` export from task.ts
- `description` matches the `TOOL_DESCRIPTION` export
- Multiple entries coexist without overwriting

---

## Test 7: Tool Search Discovery

Start a fresh agent session with manifest tools available.

**Prompt:**
```
Search for tools related to email
```
(or use tool_search if in tool-search mode)

**Expected:**
- Tool search results include manifest tools (e.g. `email_summary__email_summary`)
- Description matches what was generated

**Follow-up:**
```
Call the email summary tool with count=5
```

**Expected:**
- Agent calls `email_summary__email_summary` with `{ "count": 5 }`
- ManifestTool triggers on-demand MCP server connection
- Generated server starts, connects upstream MCP servers
- `handleTool` executes, returns structured result
- Agent receives and presents the result

---

## Test 8: On-Demand Connection Caching

In the same session as Test 7, call the tool again:
```
Run the email summary again with count=10
```

**Expected:**
- Second call does NOT trigger a new MCP server connection
- Uses the cached `McpToolProxy` from the first call
- Faster execution (no startup overhead)

---

## Test 9: Stale Manifest Entry

1. Generate an app (e.g. `test_stale`)
2. Verify it appears in `tools/manifest.json`
3. Manually delete `tools/test_stale/` directory
4. Start a new agent session

**Expected:**
- `load_manifest()` logs a warning about missing directory
- The stale entry is skipped — not added to tool search
- No crash or error

---

## Test 10: Profile Editing Between Runs

1. Generate a job search app with profile
2. Run it once (via `run_task` or tool call)
3. Edit `tools/job_search/profile.json` — change a skill or rate
4. Run again

**Expected:**
- Second run uses the updated profile values
- No regeneration needed
- Results reflect the profile change

---

## Test 11: Backward Compatibility — Old-Style Apps

If any old-style apps exist (using `runTask` instead of `handleTool`):

**Expected:**
- `run_task` with `--run` flag should fail gracefully or the old `index.ts` ignores the flag
- Old apps should not appear in the manifest (they were generated before manifest support)

**Note:** This is a low-priority edge case. Old apps can be regenerated.

---

## Scoring

| Criterion | Pass | Fail |
|-----------|------|------|
| Generated task.ts has new exports | `TOOL_NAME`, `TOOL_INPUT_SCHEMA`, `handleTool` | Old `runTask` format |
| TOOL_INPUT_SCHEMA uses Zod | Flat raw shape with `.default()`, `.describe()` | JSON schema, no Zod, or `z.object()` |
| profile.json generated correctly | User-specific values from prompt | Empty when profile was agreed, or values hardcoded in code |
| Manifest updated | Entry with tool_name, description, server config | No manifest entry, or corrupt format |
| Vitest passes | Tests import `handleTool`, test pure logic | Tests fail, or test MCP server registration |
| `run_task --run` works | Standalone execution, JSON output | Starts MCP server instead, or hangs |
| Tool search finds manifest tools | Keywords match name/description | Not indexed, or wrong name |
| On-demand connection works | First call connects, subsequent calls cached | Connection failure, or reconnects every call |
| Profile changes take effect | Re-run reflects edited profile.json | Profile cached or hardcoded |
