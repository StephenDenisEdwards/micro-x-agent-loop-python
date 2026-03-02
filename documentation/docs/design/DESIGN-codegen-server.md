# Design: Code Generation MCP Server

## Problem

The agent loop cannot reliably generate code from a template, regardless of model (Haiku, Sonnet, gpt-4o-mini, gpt-4o). The consistent failure modes are:

1. **Agent distraction** — 59 tool schemas from 9 MCP servers give the model too many choices. Instead of following a code generation recipe, it explores the codebase, creates documentation, rewrites infrastructure files, or runs the app.
2. **Competing instructions** — The system prompt says "be an agent, use tools." The code generation prompt says "follow this recipe, don't touch infrastructure." These conflict, and the system prompt wins.
3. **Context drift** — Multi-turn tool use pushes the original instructions out of the model's attention window. By the time the model has copied the template, read files, and is ready to write code, the recipe is buried under tool call results.
4. **Tool name collisions** — The MCP filesystem server exposes `write_file` and `read_file` tools. The template code has a Python `write_file()` function. The model confuses MCP tool calls with Python function calls.

These are structural problems with using an agent loop for code generation. They cannot be fixed by improving the prompt alone.

## Solution: Isolate Code Generation

Add a `codegen` MCP server that exposes a single tool: `generate_code`. When called, it:

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
│           prompt_file="job-search-prompt.txt"    │
│         )                                        │
│  Result: "4 files written to tools/job_search/"  │
│  Model: "Your job search app is ready."          │
│                                                  │
│  [59 tools available — but only 1 is needed]     │
└──────────────────────┬──────────────────────────┘
                       │ MCP stdio
                       ▼
┌─────────────────────────────────────────────────┐
│              codegen MCP Server                  │
│                                                  │
│  generate_code(task_name, prompt_file)            │
│    1. shutil.copytree template → tools/{task_name}│
│    2. Read tools.py (API surface)                │
│    3. Read prompt_file (requirements)            │
│    4. Mini agentic loop with read_file tool      │
│       (LLM reads referenced files, 2-3 turns)   │
│    5. Parse response → {filename: content}       │
│    6. Write .py files to disk                    │
│    7. Return summary (incl. turn count)          │
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

### Pre-loaded Context Files

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
Generated 4 files for tools/job_search/:
  - collector.py
  - processor.py
  - scorer.py
  - task.py
Model: claude-sonnet-4-6 | Tokens: 5200 in, 18000 out | Turns: 3
Run with: python -m tools.job_search
```

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
1. User requirements: Full contents of the prompt file
2. Pre-loaded context files (if any)
3. Instruction: Read any referenced files, then generate
```

This is roughly 10-15K tokens of input. The model reads any additional files via `read_file`, then returns generated Python files in a parseable format. The server extracts the code blocks and writes them, skipping any infrastructure files the model might mistakenly include.

## Safety

- **Infrastructure protection:** The server skips any files named `__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, or `utils.py` even if the model returns them.
- **File type restriction:** Only `.py` files are written. Non-Python files are skipped.
- **Directory isolation:** Files are only written into `tools/{task_name}/`. The server cannot write elsewhere.
- **Template preservation:** The template is copied first, then only task-specific files are overwritten.
- **Path traversal protection:** `read_file` resolves paths relative to WORKING_DIR and uses `resolve()` + `relative_to()` to prevent `..` escape.
- **Loop bound:** Hard limit of 10 turns prevents runaway tool-call loops.

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
4. Runs the generated app
5. Returns the results

This is a future integration. The MCP server works independently of compiled mode.
