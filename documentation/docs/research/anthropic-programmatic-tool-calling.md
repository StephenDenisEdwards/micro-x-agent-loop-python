# Anthropic Programmatic Tool Calling (PTC) — Research

**Date:** 2026-03-11
**Status:** Complete
**Subject:** Anthropic's Programmatic Tool Calling feature — architecture, API flow, comparison to our codegen approach

---

## 1. Overview

Programmatic Tool Calling (PTC) allows Claude to write Python code that orchestrates multiple tool calls within a sandboxed code execution container, rather than requiring a full API round-trip and inference pass for each tool invocation. Only the script's final output enters Claude's context window — intermediate results stay in the sandbox.

Released as part of Anthropic's "advanced tool use" features. Available on Claude Opus 4.6, Sonnet 4.6, Sonnet 4.5, and Opus 4.5 via the Claude API and Microsoft Foundry. Requires the code execution tool to be enabled. Not eligible for Zero Data Retention (ZDR).

**Sources:**
- [Programmatic tool calling — Claude API Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling)
- [Introducing advanced tool use — Anthropic Engineering](https://www.anthropic.com/engineering/advanced-tool-use)

---

## 2. Motivation

Traditional tool calling creates two bottlenecks:

1. **Context pollution** — When Claude processes large datasets (logs, customer records, emails), all intermediate tool results accumulate in the context window regardless of relevance. A 10MB log analysis or multi-table data fetch consumes massive token budgets and displaces important information.

2. **Inference overhead** — Each tool invocation requires a full model inference pass. For a 20-tool workflow, this means 20 separate inference passes plus Claude parsing each result and synthesising conclusions through natural language. Both slow and error-prone.

These are the same problems that motivated our codegen approach (see `DESIGN-codegen-server.md` → "Motivation: Why Generate Code?").

---

## 3. How It Works

### API Flow

1. **Opt-in:** Tools declare `"allowed_callers": ["code_execution_20260120"]` in their schema to permit programmatic invocation.

2. **Code generation:** Claude generates a Python script (with async/await, loops, conditionals, data transformations) that orchestrates tool calls.

3. **Sandboxed execution:** The script runs in Anthropic's code execution container. When the script calls a tool, the API pauses execution and returns the tool request to the caller's server.

4. **Tool result injection:** The caller provides the tool result via the API. The result is processed by the script (not consumed by the model). The script resumes.

5. **Final output only:** Only the script's `print()` output enters Claude's context window. All intermediate data stays in the sandbox.

### API Example

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=4096,
    messages=[
        {
            "role": "user",
            "content": "Query sales data for the West, East, and Central regions, "
                       "then tell me which region had the highest revenue",
        }
    ],
    tools=[
        # Enable code execution
        {"type": "code_execution_20260120", "name": "code_execution"},
        # Tool with programmatic calling enabled
        {
            "name": "query_database",
            "description": "Execute a SQL query against the sales database.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query to execute"}
                },
                "required": ["sql"],
            },
            # This is the key — allows the code execution container to call this tool
            "allowed_callers": ["code_execution_20260120"],
        },
    ],
)
```

### Generated Code Example (Budget Compliance)

Traditional approach: 20 separate model round-trips, 2,000+ expense line items (50KB+) entering context.

PTC approach — Claude generates:
```python
team = await get_team_members("engineering")
levels = list(set(m["level"] for m in team))
budget_results = await asyncio.gather(*[
    get_budget_by_level(level) for level in levels
])
budgets = {level: budget for level, budget in zip(levels, budget_results)}
expenses = await asyncio.gather(*[
    get_expenses(m["id"], "Q3") for m in team
])
# Filter and aggregate locally — only exceeding employees reach Claude
exceeded = [
    {"name": m["name"], "spent": exp["total"], "budget": budgets[m["level"]]["limit"]}
    for m, exp in zip(team, expenses)
    if exp["total"] > budgets[m["level"]]["limit"]
]
print(json.dumps(exceeded))
```

Only 2-3 exceeded employees reach Claude, not 2,000+ expense items.

---

## 4. Performance

| Metric | Improvement |
|--------|------------|
| Token consumption | 37% reduction on complex research tasks (43,588 → 27,297 avg) |
| Inference passes | N-1 eliminated for N tool calls in a single code block |
| Knowledge retrieval accuracy | 25.6% → 28.5% |
| GIA benchmark | 46.5% → 51.2% |
| Context reduction | 200KB raw data → 1KB results (typical) |

Most beneficial for: large dataset aggregation, multi-step dependent workflows (3+ tools), filtering/transforming results before Claude processes them, parallel operations across many items.

Less beneficial for: simple single-tool invocations, tasks where Claude should reason about all intermediate results, quick lookups with small responses.

---

## 5. Comparison to Our Codegen

### Shared Motivation

Both PTC and our codegen solve the same fundamental problem: serial LLM tool calls are slow, expensive, and error-prone for batch/iterative work. Both solutions have the LLM write code that loops over data instead of reasoning about each item individually.

### Key Differences

| Dimension | Anthropic PTC | Our Codegen |
|-----------|--------------|-------------|
| **What runs** | Python script in Anthropic's hosted sandbox | TypeScript app as separate local process |
| **Tool access** | Calls tools via API pause/resume protocol | Connects to MCP servers directly as a client |
| **Lifecycle** | Ephemeral — generated and discarded each invocation | Persistent — saved app, re-runnable indefinitely |
| **When code is written** | Every time, inline in the conversation | Once at generation time, reused across runs |
| **Parameterisation** | Implicit — Claude writes new code each time with different values | Explicit — typed input schema and profile config (planned) |
| **Validation** | None — code runs as-is | Vitest validation with up to 3 fix rounds |
| **Environment** | Anthropic-hosted sandbox (no ZDR) | User's machine, full data residency |
| **Language** | Python | TypeScript |
| **Parallel execution** | `asyncio.gather` in sandbox | `Promise.all` in generated code |
| **Template/infrastructure** | None — Claude writes everything from scratch | Typed MCP wrappers, config loading, file I/O utilities |

### What PTC Does Better

- **Zero setup cost** — No template, no generation step. Claude just writes the code inline.
- **Integrated with the API** — The pause/resume protocol is built into the Messages API. No separate MCP server needed.
- **`allowed_callers` pattern** — Clean opt-in mechanism for tool access control.
- **"Only final output enters context"** — Achieved within the API itself, not via process isolation.

### What Our Codegen Does Better

- **Persistence and reuse** — Generated apps are saved and re-runnable. PTC generates throwaway code on every invocation.
- **Parameterisation** — Typed input schemas and profile configuration (planned). PTC has no parameter model — it re-generates from scratch each time.
- **Scheduling** — Can be registered as broker cron jobs for recurring execution. PTC is conversation-bound.
- **Data residency** — Runs entirely on the user's machine. PTC runs on Anthropic's servers with no ZDR support.
- **Validation** — Generated code is tested with vitest before use. PTC runs untested code.
- **Template infrastructure** — 40+ typed MCP tool wrappers, config loading, file I/O. PTC starts from scratch each time.
- **MCP integration** — Generated apps connect to MCP servers directly, accessing the full tool ecosystem without API round-trips.

### Conceptual Relationship

PTC is an **optimisation of the tool-calling loop within a single conversation**. Our codegen is a **compilation step that produces a reusable artefact**. They solve the same N-round-trip problem at different levels:

- PTC: "Don't make N round-trips to the model — write a script that makes N tool calls in one execution"
- Codegen: "Don't use the model at all for the N items — generate code once, run it as many times as needed"

PTC reduces the cost of a single conversation. Codegen amortises the cost across unlimited future runs.

---

## 6. Implications for Our Architecture

### Could We Use PTC Instead of Codegen?

For one-off tasks, PTC would be simpler — no template, no generation step, no saved artefact. But it doesn't serve our reusability goals (parameterisation, scheduling, incremental runs). PTC generates throwaway code; we need persistent, parameterised apps.

### Could We Use PTC *Inside* Codegen?

Possibly. The codegen mini-agentic loop currently uses standard tool calling (one `read_file` tool with round-trips). If the codegen LLM could use PTC to read multiple referenced files in parallel and process them before generating code, it could reduce codegen latency. However, PTC requires Anthropic's code execution container, which adds a dependency on a hosted service and loses ZDR eligibility.

### Design Ideas Borrowed from PTC

1. **`allowed_callers` pattern** — When we generate MCP servers (Step 2 of parameterisation plan), we could use a similar opt-in mechanism to control which tools the generated server can call.

2. **"Only final output enters context"** — We already do this via process isolation (`run_task` captures stdout). PTC validates that this principle is correct and valuable.

3. **Parallel tool calls via `asyncio.gather` / `Promise.all`** — Our generated TypeScript code could use `Promise.all` more aggressively for independent tool calls (e.g. fetching multiple emails in parallel). The codegen system prompt could encourage this pattern.

---

## 7. Summary

PTC and our codegen are convergent solutions to the same problem, arrived at from different directions. PTC optimises within the API; we compile to a reusable artefact. For our use case (recurring batch tasks, scheduling, data residency, parameterisation), codegen remains the right approach. PTC validates our core thesis — that LLMs should write code for batch work rather than executing it turn by turn — and offers design patterns we can adopt.
