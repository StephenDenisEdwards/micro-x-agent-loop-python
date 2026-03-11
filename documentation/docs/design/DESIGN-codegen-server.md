# Design: Code Generation MCP Server

## Motivation: Why Generate Code?

When a user asks the agent to process a batch of items — search Gmail for 50 job emails, score each one against criteria, and write a report — the agent loop handles it through serial tool calls. Each email requires an LLM turn: the model re-reads the full conversation, decides to call `gmail_read`, waits for the result, reasons about the next step, and repeats. For 50 emails this means 50+ turns, each re-sending the entire context window. The cost scales linearly with the number of items, the latency accumulates to minutes, and the model can lose track mid-way through the batch.

Generated code does the same work in a single process:

```typescript
const emails = await gmailSearch(clients, "from:jobserve", 50);
for (const id of emails) {
    const msg = await gmailRead(clients, id);
    // parse, score, collect — pure TypeScript, zero LLM cost
}
await writeFile("report.md", formatReport(results), config);
```

The loops, filtering, scoring, and formatting all run as deterministic TypeScript. The LLM is used once (to generate the code), not N times (to process each item).

| | Agent loop (serial tool calls) | Generated code |
|---|---|---|
| **Cost** | N LLM turns, full context re-sent each time | 1 generation call + 1 execution |
| **Speed** | Minutes (LLM latency × N) | Seconds (native code execution) |
| **Reliability** | Model may hallucinate, lose track, or change strategy mid-batch | Deterministic loops, consistent output |
| **Repeatability** | Must re-run the full agent conversation | Generated app is saved — re-run for free |

The LLM is good at deciding *what* to do. It is wasteful at doing the *same thing* 50 times in a row. Code generation uses the LLM for what it's best at (understanding requirements, writing code) and delegates repetitive execution to deterministic code.

## Problem: Why Isolate Code Generation?

The agent loop cannot reliably generate code from a template, regardless of model (Haiku, Sonnet, gpt-4o-mini, gpt-4o). The consistent failure modes are:

1. **Agent distraction** — 59 tool schemas from 9 MCP servers give the model too many choices. Instead of following a code generation recipe, it explores the codebase, creates documentation, rewrites infrastructure files, or runs the app.
2. **Competing instructions** — The system prompt says "be an agent, use tools." The code generation prompt says "follow this recipe, don't touch infrastructure." These conflict, and the system prompt wins.
3. **Context drift** — Multi-turn tool use pushes the original instructions out of the model's attention window. By the time the model has copied the template, read files, and is ready to write code, the recipe is buried under tool call results.
4. **Tool name collisions** — The MCP filesystem server exposes `write_file` and `read_file` tools. The template code has a `writeFile()` function. The model confuses MCP tool calls with template function calls.

These are structural problems with using an agent loop for code generation. They cannot be fixed by improving the prompt alone.

## Solution: Isolate Code Generation

Add a `codegen` MCP server that exposes two tools: `generate_code` and `run_task`. When `generate_code` is called, it:

1. Copies the TypeScript template directory to a new task directory
2. Reads the template's `tools.ts` and `test-base.ts` (the API surface and fixture shapes available to generated code)
3. Reads the user prompt (the task requirements)
4. Runs a **mini agentic loop** with a single `read_file` tool (typically 2-3 turns) so the LLM can read any files referenced by the prompt
5. Parses the response to extract TypeScript file contents
6. Writes the files to `src/`
7. Runs `npm install` to install dependencies
8. Validates via `vitest` (up to 3 fix rounds)
9. Returns a summary to the calling agent

The key insight: **code generation is not a full agent task, but it benefits from minimal tool access.** It's primarily a "context in, code out" transformation, but prompts often reference external files (criteria, schemas, examples). Rather than brittle regex-based auto-detection of referenced filenames, we give the LLM a single `read_file` tool so it can fetch what it needs. This is a constrained mini-loop (1 tool, focused system prompt, 10-turn hard limit), not the 59-tool chaos that motivated isolation.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Agent Loop                      │
│                                                  │
│  User: "generate a job search app"               │
│  Model: calls generate_code(                     │
│           task_name="job_search",                │
│           prompt="Search Gmail for JobServe..."  │
│         )                                        │
│  Result: "4 files written to tools/job_search/"  │
│  Model: calls run_task(task_name="job_search")   │
│  Result: "Report saved to todays-jobs-..."       │
│  Model: "Your job search report is ready."       │
│                                                  │
│  [59 tools available — but only 2 are needed]    │
└──────────────────────┬──────────────────────────┘
                       │ MCP stdio
                       ▼
┌─────────────────────────────────────────────────┐
│              codegen MCP Server                  │
│                                                  │
│  generate_code(task_name, prompt)                 │
│    1. copytree template-ts → tools/{task_name}/  │
│       (excludes node_modules, dist)              │
│    2. Read src/tools.ts + test-base.ts (API)      │
│    3. Mini agentic loop with read_file tool      │
│       (infra files blocked server-side)          │
│    4. Parse === filename.ts === blocks           │
│    5. Write .ts files to src/                    │
│    6. npm install                                │
│    7. Validation: run vitest, fix failures (≤3x) │
│    8. Return summary (incl. validation results)  │
│                                                  │
│  run_task(task_name, timeout_seconds?)             │
│    1. Validate tools/{task_name}/src/task.ts      │
│    2. npm install (if node_modules missing)       │
│    3. npx tsx src/index.ts in task dir            │
│    4. Capture stdout/stderr, configurable timeout │
│    5. Return output                              │
│                                                  │
│  [1 tool (read_file). Infra files denied.        │
│   Max 10 turns. Validation: up to 3 test rounds.]│
└─────────────────────────────────────────────────┘
```

## Template Structure (`tools/template-ts/`)

The TypeScript template provides sealed infrastructure that generated code imports but never modifies.

| File | Purpose | Python Equivalent |
|------|---------|-------------------|
| `package.json` | Declares dependencies: `@anthropic-ai/sdk`, `@modelcontextprotocol/sdk`, `dotenv`, `tsx` (dev), `vitest` (dev) | *(implicit venv)* |
| `tsconfig.json` | TypeScript config: ES2022, Node16 modules, strict mode | — |
| `src/index.ts` | Entry point — load `.env`, read config, connect MCP servers, call `runTask()`, shut down | `__main__.py` |
| `src/mcp-client.ts` | MCP stdio client — connect, list tools, call tools with retry, return typed results | `mcp_client.py` |
| `src/tools.ts` | Typed wrappers around MCP tools — 90+ functions covering Gmail, Calendar, Contacts, LinkedIn, Web, Filesystem, GitHub, Anthropic Admin, Interview Assist, STT | `tools.py` |
| `src/llm.ts` | Anthropic Claude API helper — streaming, non-streaming, cost tracking | `llm.py` |
| `src/utils.ts` | `writeFile()`, `appendFile()` async helpers with config-aware path resolution | `utils.py` |
| `src/test-base.ts` | Test fixture factories: `makeJobserveJob()`, `makeLinkedinJob()`, `makeEmail()` | `test_base.py` |
| `src/task.ts` | Placeholder — replaced by generated code | `task.py` |

### Generated Files (replaced per task)

| File | Purpose |
|------|---------|
| `src/task.ts` | Must export `SERVERS: string[]` and `async function runTask(clients, config)` |
| `src/collector.ts` (optional) | Async functions calling `tools.ts` wrappers, return typed data |
| `src/scorer.ts` (optional) | Pure TypeScript scoring/ranking (no MCP, no LLM) |
| `src/processor.ts` (optional) | Report generation using template literals (no LLM) |
| `src/*.test.ts` | Unit tests using vitest — test pure functions only |

### Why TypeScript (ADR-019)

The original Python template had three systemic Windows runtime issues:

1. **Dependency mismatch** — Generated tasks needed packages from the project's `.venv`, not the codegen server's `uv` environment. Required hardcoded `VENV_PYTHON` path.
2. **Windows pipe inheritance hangs** — `subprocess.run(capture_output=True)` hung when grandchild MCP server processes inherited pipe handles. Required temp file workaround.
3. **`sys.unraisablehook` noise** — Asyncio subprocess cleanup on Windows fired tracebacks. Required monkey-patching.

TypeScript eliminates all three:
- `npm install` creates self-contained `node_modules/` — no venv gymnastics
- Node's `child_process` doesn't inherit parent pipe handles to grandchildren
- No asyncio teardown issues

## Why This Works

| Problem | How the server solves it |
|---------|------------------------|
| 59 tools distract the model | The generation call has one constrained tool (`read_file`). Model can read files but not explore, run, or modify anything. |
| System prompt conflicts | The server controls the prompt. No "be an agent" instruction. Focused system prompt for code generation only. |
| Context drift over turns | Typically 2-3 turns. System prompt stays in attention. Hard limit of 10 turns prevents runaway loops. |
| Tool name collisions | Only `read_file` exists — no overlap with TypeScript functions in the template. |
| Model goes off-script | The model can only read files or return text. It can't explore the codebase, run commands, or write files directly. |
| Prompt references external files | The LLM reads them itself via `read_file`, instead of brittle regex auto-detection. |
| Agent doesn't know how to run generated apps | `run_task` handles the correct invocation (`npx tsx src/index.ts` in the task directory). The agent doesn't need to know the project structure. |

## Mini Agentic Loop

### Rationale

The original single-shot design (zero tools) required the server to pre-inject all context into the prompt. When prompts reference other files (e.g. `job-search-prompt.txt` references `job-search-criteria.txt`), the server had to use regex-based auto-detection to find and read those files. This was brittle:

- Regex only catches quoted filenames — indirect references are missed
- The server guesses what the LLM needs instead of letting it decide
- Adding heuristics makes the server increasingly complex

The fix: give the LLM a single `read_file` tool so it can read referenced files itself. This is the same capability the agent would have in PROMPT mode, but constrained to a mini-loop.

### Constraints

| Constraint | Value | Rationale |
|-----------|-------|-----------|
| Tools available | 1 (`read_file`) | Minimum needed for file access. No write, no execute, no explore. |
| Max turns | 10 | Hard limit prevents runaway loops. Typical usage: 2-3 turns. |
| File access scope | WORKING_DIR only | Path traversal protection via `resolve()` + `relative_to()`. |
| Infrastructure deny | Server-side | `_execute_read_file` rejects any path whose filename is in INFRASTRUCTURE_FILES. Returns ACCESS_DENIED error. |
| System prompt | Fixed, focused | TypeScript code generation role only. No agent instructions. |

### Typical Flow

1. **Turn 1:** LLM receives system prompt + user requirements. Sees file references, calls `read_file` for each.
2. **Turn 2:** LLM receives file contents. May call `read_file` again if files reference other files.
3. **Turn 3:** LLM has all context, generates code with `end_turn`.

If the prompt has no file references, the loop completes in 1 turn (same as the old single-shot behavior).

Since the codegen LLM has `read_file`, it fetches any referenced files itself. The agent just passes the full prompt text — no need to create a prompt file or pre-inject context files.

## Tool Interface

### `generate_code`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_name` | string | yes | Snake_case name for the task (e.g. `job_search`). Used as the directory name under `tools/`. |
| `prompt` | string | yes | The full task requirements as text. If the prompt references files, the codegen LLM reads them automatically via `read_file`. |
| `model` | string | no | Model to use for generation. Default: `claude-sonnet-4-6`. |

**Returns:** Summary text with list of files written, token usage, and turn count.

**Structured result:**
```json
{
  "task_name": "job_search",
  "target_dir": "...",
  "files_written": ["task.ts", "collector.ts"],
  "files_skipped": [],
  "model": "claude-sonnet-4-6",
  "input_tokens": 5200,
  "output_tokens": 8000,
  "cache_creation_input_tokens": 4500,
  "cache_read_input_tokens": 0,
  "turns": 1,
  "validation": {
    "test_rounds": 1,
    "tests_passed": true,
    "test_files_generated": ["collector.test.ts", "scorer.test.ts"],
    "test_output": "...",
    "validation_input_tokens": 3000,
    "validation_output_tokens": 2000
  }
}
```

**Example call from agent:**
```json
{
  "task_name": "email_summary",
  "prompt": "List my past 50 emails and create an email-summary.md file summarising each one with a link to the original."
}
```

**Example response:**
```
Generated 2 files for tools/email_summary/src/:
  - collector.ts
  - task.ts
Model: claude-sonnet-4-6 | Tokens: 5200 in, 12000 out | Turns: 1
Run with: codegen__run_task(task_name="email_summary")
```

### `run_task`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_name` | string | yes | Name of a previously generated task (e.g. `job_search`). Must exist under `tools/<task_name>/`. |
| `timeout_seconds` | int | no | Maximum runtime in seconds. Default: 600. |

Runs `npx tsx src/index.ts` in the task directory with the specified timeout. Captures stdout and stderr. Automatically runs `npm install` if `node_modules/` doesn't exist.

**Structured result:**
```json
{
  "task_name": "email_summary",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "timed_out": false
}
```

**Why a dedicated tool instead of `filesystem__bash`:** Generated apps are TypeScript projects with ESM imports, MCP server connections, and config loading. They must be run via `npx tsx src/index.ts` from the task directory. The outer agent doesn't know this and will try `node task.ts`, which fails with import errors. `run_task` encapsulates the correct invocation.

## Generation Prompt Structure

The server splits the prompt into system and user messages:

**System prompt** (static per generation) — structured for strict discipline:
```
1. Role — one line: "You are a TypeScript code generator. Output only code files, no prose."
2. Non-negotiables — binary rules:
   - No tool calls unless user prompt references an unseen file
   - Infrastructure is sealed (do not inspect, read, or modify)
   - No prose output — only the file manifest
3. Runtime contract — what task.ts must export, available imports, tools.ts signatures inline
4. Import rules — all relative imports must use .js extension (Node16 ESM requirement)
5. API surface — tools.ts signatures + test-base.ts fixture factories (full source inline)
6. Rules — pure TypeScript for scoring/formatting, .ts only, Intl.DateTimeFormat for dates
7. Generation budget — under 800 lines total, max 10 tests/module, no internal JSDoc
8. Unit tests — vitest only, import from ./test-base.js, no mocking
9. Tool rules — explicit gate: only call read_file for files mentioned in user prompt
10. Output format — compact "=== filename ===" delimiters, no markdown fences, no text between files
```

**User message** (per request):
```
Requirements:

<the prompt text passed by the agent>
```

The user message is minimal — no tool-use instructions (covered by system prompt). This is roughly 10-15K tokens of input. The model reads any additional files via `read_file`, then returns generated TypeScript files using `=== filename ===` delimiters. The server extracts the code blocks, strips any markdown fences the LLM might add despite instructions, and writes them to `src/` — skipping any infrastructure files.

### Prompt Discipline Rationale

The prompt follows a proven pattern for constraining LLM output:
- **Non-negotiables first** — binary, testable rules at the top of the prompt get the strongest attention
- **No redundancy** — tool-use instructions appear once (system prompt), not repeated in the user message
- **Numeric caps** — "under 800 lines" and "max 10 tests" are unambiguous; "keep it concise" is not
- **Compact output format** — `=== filename ===` delimiters are shorter than `### FILE:` + triple-backtick blocks, and the "no markdown fences" instruction discourages the LLM from padding with formatting
- **Server-side enforcement** — the infrastructure file deny in `_execute_read_file` backs up the prompt instruction with a hard block, so even if the LLM ignores "do not read infrastructure", the server returns ACCESS_DENIED

## Safety

- **Infrastructure file deny (read):** `_execute_read_file` checks the filename against `INFRASTRUCTURE_FILES` before any filesystem access. Returns `ACCESS_DENIED` error, preventing the LLM from wasting turns reading template files.
- **Infrastructure protection (write):** The server skips any files named `index.ts`, `mcp-client.ts`, `llm.ts`, `tools.ts`, `utils.ts`, or `test-base.ts` even if the model returns them in its output.
- **Flat directory enforcement:** `parse_files()` rejects any filename containing `/` or `\`. All generated files must be flat in `src/` — subdirectory paths (e.g. `src/task.ts`) are skipped to prevent writes to non-existent directories.
- **File type restriction:** Only `.ts` files are written. Non-TypeScript files are skipped.
- **Directory isolation:** Files are only written into `tools/{task_name}/src/`. The server cannot write elsewhere.
- **Template preservation:** The template is copied first, then only task-specific files are overwritten.
- **Path traversal protection:** `read_file` resolves paths relative to WORKING_DIR and uses `resolve()` + `relative_to()` to prevent `..` escape.
- **Loop bound:** Hard limit of 10 turns prevents runaway tool-call loops.
- **Execution timeout:** `run_task` has a configurable timeout (default 600 seconds) to prevent runaway apps.

## Validation Phase

After writing generated files and installing dependencies, the server runs a validation phase:

1. Discover all `*.test.ts` files in the generated output
2. Run `npx vitest run` in the target directory (via `asyncio.to_thread` to avoid blocking the event loop)
3. If tests pass, validation is complete
4. If tests fail, continue the codegen conversation — append the test output and ask the LLM to fix
5. Repeat up to `MAX_TEST_ROUNDS` (3) times

The fix request uses the same `=== filename ===` output format. The LLM returns only the files that need changes, which are parsed and written over the originals in `src/`. Validation token usage is tracked separately and included in the structured result.

### Test Fixture Visibility

The system prompt includes the full source of `test-base.ts` alongside `tools.ts`. This is critical: the LLM must know the exact field names and value formats of `makeJobserveJob()`, `makeLinkedinJob()`, and `makeEmail()` to write passing tests.

Without fixture source in the prompt, the LLM knows the factory names (from import examples) but guesses the shapes — e.g., it might expect `job.url` when the field is `job.applyUrl`, or `"£600/day"` when the format is `"£600 PER DAY"`. This mismatch causes systematic test failures where each fix round the LLM adjusts its guesses based on error output, wasting 2-3 validation rounds before converging. Including the source eliminates the guessing entirely.

The general principle: **any type or factory the LLM is expected to use in generated code must have its full definition in the prompt, not just its name.** Sealed infrastructure should not be readable via `read_file`, but its API contract must be visible.

### Why Continue the Conversation

Rather than starting a fresh LLM call for fixes, the server appends to the existing conversation. This means the LLM has full context: the original requirements, any files it read, the code it generated, and the test failures. This produces better fixes than a cold-start repair prompt.

## Configuration

The server needs:

| Setting | Source | Example |
|---------|--------|---------|
| `ANTHROPIC_API_KEY` | Environment variable | (from `.env`) |
| `PROJECT_ROOT` | Environment variable or auto-detected | `C:\Users\steph\source\repos\micro-x-agent-loop-python` |
| `TEMPLATE_DIR` | Derived from PROJECT_ROOT | `{PROJECT_ROOT}/tools/template-ts` |
| `WORKING_DIR` | From agent config (passed as env) | `C:\Users\steph\source\repos\resources\documents` |

## Task Execution Flow

```
generate_code("job_search", prompt)
  → copy tools/template-ts/ to tools/job_search/ (excl. node_modules)
  → LLM generates TypeScript files (task.ts, collector.ts, scorer.ts, etc.)
  → write files to tools/job_search/src/
  → run npm install in tools/job_search/
  → run npx vitest run (validation)
  → if tests fail, ask LLM to fix, re-run (up to 3 rounds)

run_task("job_search")
  → npm install if node_modules missing
  → npx tsx src/index.ts in tools/job_search/
  → stdout/stderr captured via capture_output
```

## Future: Sub-Agent Alternative

If sub-agents are implemented in the agent loop, code generation could migrate from an MCP server to a sub-agent. This is now a natural migration path since codegen already uses a mini agentic loop with tool calls:

- The main agent spawns a sub-agent with a tailored system prompt and a single `read_file` tool
- The sub-agent receives the assembled context, reads any referenced files, and returns code
- The main agent writes the files

The principle is identical — **isolate the generation call from the main agent's context.** The codegen server's mini agentic loop is structurally similar to a sub-agent, making migration straightforward.

| Approach | Isolation boundary | Tools in generation path | Model decisions |
|----------|-------------------|------------------------|----------------|
| MCP server (current) | Separate process | 1 (`read_file`) | Minimal — read files, then generate |
| Sub-agent | Separate conversation | 1+ (configurable) | Some — sub-agent decides what to read and generate |

Both approaches could coexist: MCP server for simple "template → code" generation, sub-agents for more complex tasks requiring multi-turn reasoning.

## Relationship to Compiled Mode

The agent loop already detects "compiled mode" (batch processing, scoring, structured output). When compiled mode is detected, the agent could automatically call `generate_code` instead of attempting the task through the agent loop. This would be the natural trigger:

1. User sends a prompt
2. Agent loop detects compiled mode signals
3. Instead of looping with tools, calls `generate_code` once
4. Calls `run_task` to execute the generated app
5. Returns the results

This is a future integration. The MCP server works independently of compiled mode.
