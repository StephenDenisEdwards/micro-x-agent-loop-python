# Design: Code Generation MCP Server

## Problem

The agent loop cannot reliably generate code from a template, regardless of model (Haiku, Sonnet, gpt-4o-mini, gpt-4o). The consistent failure modes are:

1. **Agent distraction** — 59 tool schemas from 9 MCP servers give the model too many choices. Instead of following a code generation recipe, it explores the codebase, creates documentation, rewrites infrastructure files, or runs the app.
2. **Competing instructions** — The system prompt says "be an agent, use tools." The code generation prompt says "follow this recipe, don't touch infrastructure." These conflict, and the system prompt wins.
3. **Context drift** — Multi-turn tool use pushes the original instructions out of the model's attention window. By the time the model has copied the template, read files, and is ready to write code, the recipe is buried under tool call results.
4. **Tool name collisions** — The MCP filesystem server exposes `write_file` and `read_file` tools. The template code has a Python `write_file()` function. The model confuses MCP tool calls with Python function calls.

These are structural problems with using an agent loop for code generation. They cannot be fixed by improving the prompt alone.

## Solution: Isolate Code Generation

Add a `codegen` MCP server that exposes two tools: `generate_code` and `run_task`. When `generate_code` is called, it:

1. Copies the template directory to a new task directory
2. Reads the template's `tools.py` (the API surface available to generated code)
3. Reads the user prompt file (the task requirements)
4. Runs a **mini agentic loop** with a single `read_file` tool (typically 2-3 turns) so the LLM can read any files referenced by the prompt
5. Parses the response to extract Python file contents
6. Writes the files to disk
7. Returns a summary to the calling agent

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
│    1. shutil.copytree template → tools/{task_name}│
│    2. Read tools.py (API surface)                │
│    3. Mini agentic loop with read_file tool      │
│       (LLM reads referenced files, 2-3 turns)   │
│    4. Parse response → {filename: content}       │
│    5. Write .py files to disk                    │
│    6. Return summary (incl. turn count)          │
│                                                  │
│  run_task(task_name)                              │
│    1. Validate tools/{task_name}/task.py exists   │
│    2. python -m tools.{task_name} from PROJECT_ROOT│
│    3. Capture stdout/stderr, 300s timeout        │
│    4. Return output                              │
│                                                  │
│  [Model sees: 1 tool (read_file). Max 10 turns.] │
└─────────────────────────────────────────────────┘
```

## Why This Works

| Problem | How the server solves it |
|---------|------------------------|
| 59 tools distract the model | The generation call has one constrained tool (`read_file`). Model can read files but not explore, run, or modify anything. |
| System prompt conflicts | The server controls the prompt. No "be an agent" instruction. Focused system prompt for code generation only. |
| Context drift over turns | Typically 2-3 turns. System prompt stays in attention. Hard limit of 10 turns prevents runaway loops. |
| Tool name collisions | Only `read_file` exists — no overlap with Python functions in the template. |
| Model goes off-script | The model can only read files or return text. It can't explore the codebase, run commands, or write files directly. |
| Prompt references external files | The LLM reads them itself via `read_file`, instead of brittle regex auto-detection. |
| Agent doesn't know how to run generated apps | `run_task` handles the correct invocation (`python -m tools.<name>` from PROJECT_ROOT). The agent doesn't need to know the package structure. |

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
| System prompt | Fixed, focused | Code generation role only. No agent instructions. |

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
  "files_written": ["task.py", "collector.py"],
  "files_skipped": [],
  "model": "claude-sonnet-4-6",
  "input_tokens": 5200,
  "output_tokens": 18000,
  "turns": 3
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
Generated 2 files for tools/email_summary/:
  - collector.py
  - task.py
Model: claude-sonnet-4-6 | Tokens: 5200 in, 12000 out | Turns: 1
Run with: codegen__run_task(task_name="email_summary")
```

### `run_task`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_name` | string | yes | Name of a previously generated task (e.g. `job_search`). Must exist under `tools/<task_name>/`. |

Runs `python -m tools.<task_name>` from PROJECT_ROOT with a 300-second timeout. Captures stdout and stderr.

**Structured result:**
```json
{
  "task_name": "email_summary",
  "exit_code": 0,
  "stdout": "...",
  "stderr": ""
}
```

**Why a dedicated tool instead of `filesystem__bash`:** Generated apps are Python packages with relative imports, MCP server connections, and config loading. They must be run as modules (`python -m tools.<name>`) from PROJECT_ROOT. The outer agent doesn't know this and will try `python task.py`, which fails with import errors. `run_task` encapsulates the correct invocation.

## Generation Prompt Structure

The server splits the prompt into system and user messages:

**System prompt** (static per generation):
```
1. Role: "You are a Python code generator."
2. Context: Template structure, which files are untouchable
3. API surface: Full contents of tools.py
4. Task requirements format: What task.py must export
5. Rules: No LLM calls for scoring, relative imports, etc.
6. Instruction: Read referenced files before generating
7. Output format: "Return each file as ### FILE: <name>\n```python\n<code>\n```"
```

**User message** (per request):
```
1. User requirements: The prompt text passed by the agent
2. Instruction: Read any referenced files, then generate
```

This is roughly 10-15K tokens of input. The model reads any additional files via `read_file`, then returns generated Python files in a parseable format. The server extracts the code blocks and writes them, skipping any infrastructure files the model might mistakenly include.

## Safety

- **Infrastructure protection:** The server skips any files named `__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, or `utils.py` even if the model returns them.
- **File type restriction:** Only `.py` files are written. Non-Python files are skipped.
- **Directory isolation:** Files are only written into `tools/{task_name}/`. The server cannot write elsewhere.
- **Template preservation:** The template is copied first, then only task-specific files are overwritten.
- **Path traversal protection:** `read_file` resolves paths relative to WORKING_DIR and uses `resolve()` + `relative_to()` to prevent `..` escape.
- **Loop bound:** Hard limit of 10 turns prevents runaway tool-call loops.
- **Execution timeout:** `run_task` has a 300-second timeout to prevent runaway apps.

## Configuration

The server needs:

| Setting | Source | Example |
|---------|--------|---------|
| `ANTHROPIC_API_KEY` | Environment variable | (from `.env`) |
| `PROJECT_ROOT` | Environment variable or auto-detected | `C:\Users\steph\source\repos\micro-x-agent-loop-python` |
| `TEMPLATE_DIR` | Derived from PROJECT_ROOT | `{PROJECT_ROOT}/tools/template` |
| `WORKING_DIR` | From agent config (passed as env) | `C:\Users\steph\source\repos\resources\documents` |

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
