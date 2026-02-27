# Execution Model Design
## How Compiled Task Mode Actually Works

**Status:** Active exploration
**Document type:** Living design document — captures iterative brainstorming, tradeoffs, and open questions

---

## 1. The Design Question

The engineering white paper establishes *that* agents should switch to compiled task mode for large, structured, or compliance-sensitive workloads. This document explores *how* — what the execution mechanism actually looks like at runtime.

The core constraint: the mechanism must be **general-purpose**. This is a personal agent, not a domain-specific pipeline. The agent cannot require pre-built runtimes for every task type it might encounter.

---

## 2. Three Execution Models

### 2.1 Pre-Built Runtime

The LLM produces a structured task specification (JSON). A pre-existing, tested runtime interprets the specification and executes the pipeline.

**How it works:**
- The LLM outputs a task spec: data sources, extraction schema, scoring rubric, output template.
- A runtime engine — built and tested in advance — reads the spec and executes deterministic processing.
- The LLM is called back only for narrative generation from compact results.

**Strengths:**
- Execution logic is tested and stable.
- No risk of generated code bugs.
- Highly predictable behaviour.

**Weaknesses:**
- Not general-purpose. Every new task type requires a new runtime or runtime extension.
- The task spec becomes a DSL — and DSLs accumulate complexity or become limiting.
- Scales poorly to the variety of tasks a personal agent encounters.

**Verdict:** Suitable for known, recurring workloads (e.g., a daily job search report that runs the same way every time). Not viable as the general-purpose mechanism.

### 2.2 LLM-Generated Code (Fully Dynamic)

The LLM writes a complete program from scratch and executes it in a sandbox.

**How it works:**
- The LLM receives the task and writes a Python script (or equivalent) that does everything: fetches data, parses it, scores, validates, renders output.
- The script is executed in a sandboxed environment.
- The LLM may review or iterate on the code before execution.

**Strengths:**
- Fully general-purpose. Any task the LLM can reason about, it can write code for.
- No pre-built infrastructure required beyond the sandbox.
- Flexible — adapts to novel task shapes without engineering effort.

**Weaknesses:**
- Generated code is untested code. Bugs are likely, especially in edge cases.
- The LLM invents interfaces — network calls, file paths, API shapes — that may not match reality.
- Reliability problem is traded, not solved: from constraint drift in prompt mode to bugs in generated code.
- Harder to audit or trust for sensitive operations.

**Verdict:** Maximum flexibility, but the reliability gap is a real concern. The model is good at writing code, but "good" is not "guaranteed correct."

### 2.3 Hybrid: LLM-Generated Code Against Registered MCP Servers

The LLM writes a program, but programs against a known set of capabilities exposed by registered MCP servers — the same servers the agent already uses for tool calls in prompt mode.

**How it works:**
- The agent has registered MCP servers (Gmail, LinkedIn, file system, calendar, etc.) with typed schemas.
- In prompt mode, the agent calls these as tools through the agent loop.
- In compiled mode, the LLM writes a program that calls the **same MCP servers** programmatically — not through the agent loop's tool-call mechanism, but as API calls from generated code.
- The MCP server registry serves as both the agent's tool palette (prompt mode) and the SDK available to generated programs (compiled mode).
- The generated code orchestrates the full pipeline: fetch data via MCP, transform/score/validate in code, render output, write files via MCP.

**Strengths:**
- General-purpose. Whatever MCP servers are registered define what the agent can do in either mode. No pre-built runtimes per task type.
- No new infrastructure. The MCP servers already exist. They are exposed through a different interface (code imports vs tool calls), but the capabilities are identical.
- The LLM programs against known contracts. MCP server schemas provide typed interfaces — the model is not inventing APIs, it is calling documented ones. This dramatically narrows the surface area for bugs.
- Well-suited to LLM strengths. Writing code that calls well-documented APIs with typed schemas is exactly where models are most reliable.
- Inspectable before execution. The generated code can be reviewed — by the user, by the LLM itself, or by a validation pass — before it runs.
- Consistent capability model. The agent's capabilities are defined once (MCP server registration) and available in both execution modes. Adding a new MCP server expands both prompt mode and compiled mode simultaneously.

**Weaknesses:**
- Generated code is still untested, though the typed MCP schemas reduce risk significantly.
- MCP servers must be callable from generated code, not just from the agent loop. This may require an SDK or client library accessible from the sandbox.
- Error handling in generated code may be naive — network failures, rate limits, malformed responses.
- Sandboxing must be robust enough to run generated code that makes real external calls (Gmail, LinkedIn).

**Verdict:** The most promising direction. Combines general-purpose flexibility with meaningful guardrails from the MCP server contracts.

---

## 3. Why the Hybrid MCP Model is Compelling

The key insight is that the MCP server registry already represents a curated, typed catalogue of the agent's capabilities. In prompt mode, the agent loop mediates access to these capabilities. In compiled mode, the generated code accesses them directly.

This creates a clean architectural symmetry:

```
Prompt Mode:
  User prompt → LLM → tool call → MCP server → result → LLM → response

Compiled Mode:
  User prompt → LLM → generates program → program calls MCP servers →
  deterministic processing → compact results → LLM → narrative
```

Same capabilities. Same data sources. Same typed contracts. Different orchestration model.

The MCP schemas act as the "standard library" for generated programs. The LLM does not need to invent how to search Gmail or fetch a LinkedIn job posting — those interfaces are declared. It writes the orchestration, transformation, scoring, and rendering logic around them.

---

## 4. The Critical Constraint: Data Must Not Touch Context

During design exploration, a simpler approach was considered: the agent loop fetches data via normal MCP tool calls (prompt mode), saves it to intermediate files, and then generated code processes those files. This would avoid the complexity of MCP access from generated code entirely.

This approach is fatally flawed. When the agent loop calls MCP tools to fetch 30 emails and 20 job listings, those results — 50,000+ tokens of raw data — land in the conversation history. The data passes through the LLM's context even though the LLM doesn't need to reason over it. This defeats the entire purpose of compiled task mode, which exists precisely to keep bulk data out of context.

**The generated code must handle fetching itself.** Data must flow from source to file to processing to output without ever passing through the LLM's context window. This means the generated code needs direct access to MCP servers.

---

## 5. The MCP Client Library

The question of how generated code accesses MCP servers resolves cleanly once you recognise that MCP servers are just processes. The generated code can spawn MCP server instances directly, connect as a client, make calls, and get results. No special infrastructure required — just a library that wraps the mechanics.

### 5.1 The Library Interface

```python
from agent_mcp import connect

async with connect("gmail") as gmail:
    emails = await gmail.call("search", query="from:jobserve newer_than:1d")

async with connect("linkedin") as linkedin:
    jobs = await linkedin.call("search", query="(.NET OR Azure) contract UK")

# From here, pure Python — no MCP, no LLM
for job in jobs:
    job["score"] = compute_weighted_score(job, rubric)

qualified = [j for j in jobs if j["score"] >= 5]
ranked = sorted(qualified, key=lambda j: j["score"], reverse=True)

render_report(ranked, template="todays-jobs-report")
```

### 5.2 What the Library Handles

The `agent_mcp` library (working name) provides the bridge between generated code and the agent's registered MCP servers:

- **Registry lookup.** Resolves server names ("gmail", "linkedin") to their configuration from the agent's MCP server registry.
- **Process management.** Spawns the MCP server process, manages its lifecycle, shuts it down cleanly when the context manager exits.
- **Client connection.** Connects to the spawned server using the MCP protocol.
- **Credential passthrough.** Passes through authentication credentials (OAuth tokens, API keys) that the MCP servers already have access to in prompt mode.
- **Schema exposure.** Makes the server's tool schemas available to the generated code, enabling the LLM to write calls that match the expected parameters.

### 5.3 Why This Works

The library is small and focused — it is not a framework, it is connection plumbing. The complexity it absorbs is mechanical (process spawning, protocol connection, credential management), not semantic. The LLM does not need to understand the library internals. It needs to know:

- Server names (same names it already uses in prompt mode)
- Tool names and parameters (same schemas it already sees in prompt mode)
- The `connect` / `call` pattern

This is a trivial API surface. The LLM already knows how to call these servers — it does it every time it uses a tool in prompt mode. The library just provides the same access from inside generated code.

### 5.4 Architectural Symmetry

The MCP server registry now serves as a unified capability layer across both execution modes:

```
Prompt Mode:
  User prompt → LLM → tool call → agent loop → MCP server → result → LLM → response

Compiled Mode:
  User prompt → LLM → generates program →
    program imports agent_mcp →
    program spawns MCP servers directly →
    program does deterministic processing →
    program writes output →
  LLM reads compact results → narrative
```

Same servers. Same schemas. Same credentials. The only difference is who orchestrates the calls — the agent loop or the generated code.

Adding a new MCP server to the agent's registry automatically makes it available in both modes. The LLM sees it as a new tool in prompt mode and as a new `connect("server_name")` target in compiled mode.

---

## 6. Remaining Open Questions

### 6.1 Sandboxing and Trust

Generated code that calls real external services (reading email, posting to APIs) needs careful sandboxing:

- What permissions does the sandbox have?
- Can generated code only call registered MCP servers, or can it make arbitrary network calls?
- Should the agent present the generated code to the user for approval before execution?
- Should there be a dry-run mode that validates the code without executing external calls?

### 6.2 Error Recovery

What happens when generated code fails mid-execution?

- Does the agent retry with a patched version of the code?
- Does it fall back to prompt mode for the failing portion?
- How does it report partial results?

### 6.3 Code Quality and Review

Should the LLM review its own generated code before execution?

- A second LLM pass checking for obvious bugs, missing error handling, or incorrect MCP usage could catch many issues.
- This adds latency and token cost, but may be worth it for reliability.
- Alternatively, static analysis or schema validation of MCP calls could catch type mismatches without an LLM pass.

### 6.4 When to Compile vs When to Prompt

The cost-aware switching decision itself needs design:

- Is it a hard threshold (item count > N, estimated tokens > T)?
- Does the LLM decide ("this task looks like it should be compiled")?
- Is it user-configurable ("always compile job search tasks")?
- Can the user force one mode or the other?

### 6.5 Caching and Reuse of Generated Programs

If the agent generates a program for "daily job search report" today, can it reuse or adapt that program tomorrow?

- This moves toward the pre-built runtime model — but with the runtime generated by the agent itself over time.
- A library of previously generated and validated programs could become a performance optimisation.
- Risk: cached programs may not adapt to changed MCP server schemas or user requirements.

---

## 7. Relationship to the White Paper Example

The engineering white paper (section 6) presents the job search report as a concrete example using the pre-built runtime model. This was chosen for clarity of exposition — it cleanly illustrates the separation of semantic reasoning from deterministic execution without introducing the additional complexity of code generation.

The hybrid MCP model with the `agent_mcp` client library described here is the intended general-purpose mechanism. The white paper example remains valid as an illustration of *what* compiled mode achieves (cost reduction, deterministic guarantees, reproducibility). This document explores *how* it achieves it in a general-purpose agent.

As this design matures, the white paper may be updated with a second example showing the MCP-based execution model, or a reference to this document may be added.

---

## 8. Summary of Current Thinking

The compiled task execution model for a general-purpose personal agent should:

1. **Use LLM-generated code** — not pre-built runtimes — to maintain generality.
2. **Program against registered MCP servers** — providing typed, known interfaces that constrain the generated code and reduce bug surface area.
3. **Access MCP servers via a client library (`agent_mcp`)** — the library handles registry lookup, process spawning, client connection, and credential passthrough. The LLM writes against a minimal API surface (`connect`, `call`) using the same server names and tool schemas it already knows from prompt mode.
4. **Keep bulk data out of context entirely** — the generated code fetches, processes, and outputs data without it ever entering the LLM's conversation history. The LLM only sees compact results when called back for narrative generation.
5. **Execute in a sandbox** — with controlled access to MCP servers and appropriate permission boundaries.
6. **Remain inspectable** — generated code can be reviewed before execution.

The `agent_mcp` library is the key enabling component. It is not a framework — it is connection plumbing that bridges the agent's MCP server registry into generated code. The MCP server registry becomes the unified capability layer: same servers, same schemas, same credentials, accessible from both the agent loop (prompt mode) and generated programs (compiled mode).

---

## Design Evolution Log

| Date | Key Decision |
|---|---|
| Initial | Three execution models identified: pre-built runtime, fully dynamic, hybrid MCP |
| Initial | Hybrid MCP model selected as most promising direction |
| 2026-02-27 | "Agent loop fetches, code processes" approach rejected — data in context defeats the purpose |
| 2026-02-27 | MCP client library (`agent_mcp`) concept introduced — generated code spawns MCP servers directly |
| 2026-02-27 | MCP access from generated code resolved as a design question |

---

*This document will be updated as the design evolves.*