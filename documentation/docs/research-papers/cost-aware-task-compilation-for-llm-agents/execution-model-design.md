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

## 4. Open Questions

### 4.1 MCP Access from Generated Code

How does generated code call MCP servers?

Options:
- **Generated code imports an MCP client library** that the sandbox provides. The library handles connection, authentication, and schema validation.
- **The sandbox exposes MCP servers as local HTTP endpoints** that generated code calls with standard HTTP libraries.
- **The runtime wraps MCP servers in a Python SDK** auto-generated from server schemas, providing typed function calls.

This is an infrastructure question with significant implications for developer experience and reliability.

### 4.2 Sandboxing and Trust

Generated code that calls real external services (reading email, posting to APIs) needs careful sandboxing:

- What permissions does the sandbox have?
- Can generated code only call registered MCP servers, or can it make arbitrary network calls?
- Should the agent present the generated code to the user for approval before execution?
- Should there be a dry-run mode that validates the code without executing external calls?

### 4.3 Error Recovery

What happens when generated code fails mid-execution?

- Does the agent retry with a patched version of the code?
- Does it fall back to prompt mode for the failing portion?
- How does it report partial results?

### 4.4 Code Quality and Review

Should the LLM review its own generated code before execution?

- A second LLM pass checking for obvious bugs, missing error handling, or incorrect MCP usage could catch many issues.
- This adds latency and token cost, but may be worth it for reliability.
- Alternatively, static analysis or schema validation of MCP calls could catch type mismatches without an LLM pass.

### 4.5 When to Compile vs When to Prompt

The cost-aware switching decision itself needs design:

- Is it a hard threshold (item count > N, estimated tokens > T)?
- Does the LLM decide ("this task looks like it should be compiled")?
- Is it user-configurable ("always compile job search tasks")?
- Can the user force one mode or the other?

### 4.6 Caching and Reuse of Generated Programs

If the agent generates a program for "daily job search report" today, can it reuse or adapt that program tomorrow?

- This moves toward the pre-built runtime model — but with the runtime generated by the agent itself over time.
- A library of previously generated and validated programs could become a performance optimisation.
- Risk: cached programs may not adapt to changed MCP server schemas or user requirements.

---

## 5. Relationship to the White Paper Example

The engineering white paper (section 6) presents the job search report as a concrete example using the pre-built runtime model. This was chosen for clarity of exposition — it cleanly illustrates the separation of semantic reasoning from deterministic execution without introducing the additional complexity of code generation.

The hybrid MCP model described here is the intended general-purpose mechanism. The white paper example remains valid as an illustration of *what* compiled mode achieves (cost reduction, deterministic guarantees, reproducibility). This document explores *how* it achieves it in a general-purpose agent.

As this design matures, the white paper may be updated with a second example showing the MCP-based execution model, or a reference to this document may be added.

---

## 6. Summary of Current Thinking

The compiled task execution model for a general-purpose personal agent should:

1. **Use LLM-generated code** — not pre-built runtimes — to maintain generality.
2. **Program against registered MCP servers** — providing typed, known interfaces that constrain the generated code and reduce bug surface area.
3. **Leverage the existing MCP server registry** — so that the agent's capabilities are defined once and available in both prompt mode and compiled mode.
4. **Execute in a sandbox** — with controlled access to MCP servers and appropriate permission boundaries.
5. **Remain inspectable** — generated code can be reviewed before execution.

The MCP server registry becomes the bridge between the agent's conversational tool-use capabilities and its programmatic execution capabilities. Same servers, different orchestration.

---

*This document will be updated as the design evolves.*