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
4. Makes a **single API call** to a capable model (e.g. Claude Sonnet) with **no tools attached**
5. Parses the response to extract Python file contents
6. Writes the files to disk
7. Returns a summary to the calling agent

The key insight: **code generation is not an agent task.** It's a "context in, code out" transformation. The model doesn't need tools — it needs a focused prompt with the right context. The MCP server provides the isolation boundary.

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
│    4. Single API call to Sonnet — NO TOOLS       │
│    5. Parse response → {filename: content}       │
│    6. Write .py files to disk                    │
│    7. Return summary                             │
│                                                  │
│  [Model sees: context only. Zero tool schemas.]  │
└─────────────────────────────────────────────────┘
```

## Why This Works

| Problem | How the server solves it |
|---------|------------------------|
| 59 tools distract the model | The generation call has zero tools. Model can only return text. |
| System prompt conflicts | The server controls the prompt. No "be an agent" instruction. |
| Context drift over turns | Single turn. All context in one message. |
| Tool name collisions | No tools at all. `write_file` is only a Python function in the prompt. |
| Model goes off-script | The model has no ability to go off-script. It can't call tools, explore, or run anything. |

## Tool Interface

### `generate_code`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_name` | string | yes | Snake_case name for the task (e.g. `job_search`). Used as the directory name under `tools/`. |
| `prompt_file` | string | yes | Filename of the user prompt in the working directory (e.g. `job-search-prompt.txt`). |
| `model` | string | no | Model to use for generation. Default: `claude-sonnet-4-6`. |

**Returns:** Summary text with list of files written and token usage.

**Example call from agent:**
```json
{
  "task_name": "job_search",
  "prompt_file": "job-search-prompt.txt"
}
```

**Example response:**
```
Generated 4 files in tools/job_search/:
  task.py (4813 chars)
  collector.py (15076 chars)
  scorer.py (12522 chars)
  processor.py (20937 chars)

Tokens: 3969 in, 16214 out
Run with: python -m tools.job_search
```

## Generation Prompt Structure

The server assembles a single prompt for the generation model:

```
1. Role: "You are a Python code generator."
2. Context: Template structure, which files are untouchable
3. API surface: Full contents of tools.py
4. Task requirements: Full contents of the user prompt file
5. Output format: "Return each file as ### FILE: <name>\n```python\n<code>\n```"
6. Constraints: No LLM calls for scoring/formatting, relative imports only, etc.
```

This is roughly 10-15K tokens of input. The model returns generated Python files in a parseable format. The server extracts the code blocks and writes them, skipping any infrastructure files the model might mistakenly include.

## Safety

- **Infrastructure protection:** The server skips any files named `__main__.py`, `mcp_client.py`, `llm.py`, `tools.py`, or `utils.py` even if the model returns them.
- **File type restriction:** Only `.py` files are written. Non-Python files are skipped.
- **Directory isolation:** Files are only written into `tools/{task_name}/`. The server cannot write elsewhere.
- **Template preservation:** The template is copied first, then only task-specific files are overwritten.

## Configuration

The server needs:

| Setting | Source | Example |
|---------|--------|---------|
| `ANTHROPIC_API_KEY` | Environment variable | (from `.env`) |
| `PROJECT_ROOT` | Environment variable or auto-detected | `C:\Users\steph\source\repos\micro-x-agent-loop-python` |
| `TEMPLATE_DIR` | Derived from PROJECT_ROOT | `{PROJECT_ROOT}/tools/template` |
| `WORKING_DIR` | From agent config (passed as env) | `C:\Users\steph\source\repos\resources\documents` |

## Future: Sub-Agent Alternative

If sub-agents are implemented in the agent loop, code generation could migrate from an MCP server to a sub-agent:

- The main agent spawns a sub-agent with a tailored system prompt and zero tools
- The sub-agent receives the assembled context and returns code
- The main agent writes the files

The principle is identical — **isolate the generation call from the main agent's context.** The difference is where the isolation boundary sits:

| Approach | Isolation boundary | Model decisions in generation path |
|----------|-------------------|-----------------------------------|
| MCP server | Separate process | Zero — all logic is Python code |
| Sub-agent | Separate conversation | Some — sub-agent decides what to generate |

The MCP server is safer because the generation path has zero model decision-making. A sub-agent reintroduces model choices (it could ask for clarification, iterate, etc.), which is valuable for complex tasks but risky for simple code generation.

Both approaches could coexist: MCP server for simple "template → code" generation, sub-agents for more complex tasks requiring multi-turn reasoning.

## Relationship to Compiled Mode

The agent loop already detects "compiled mode" (batch processing, scoring, structured output). When compiled mode is detected, the agent could automatically call `generate_code` instead of attempting the task through the agent loop. This would be the natural trigger:

1. User sends a prompt
2. Agent loop detects compiled mode signals
3. Instead of looping with tools, calls `generate_code` once
4. Runs the generated app
5. Returns the results

This is a future integration. The MCP server works independently of compiled mode.
