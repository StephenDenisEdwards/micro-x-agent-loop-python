# Plan: Codegen — Parameterised MCP Server Generation

**Status: Proposed** (2026-03-11)

## Context

Generated codegen apps are standalone scripts with all values hardcoded. Every variation requires a new `generate_code` call. This limits reusability — users can't adjust a search range or output directory without regenerating the entire app.

The goal is to generate MCP servers instead of scripts, with typed input schemas and profile-based configuration. The agent negotiates the parameter/profile split with the user before generating, so the contract is explicit and agreed rather than silently guessed by the LLM.

See: `documentation/docs/design/DESIGN-codegen-server.md` → "Future: Reusability" → "1. Parameterisation"

## Step 1: Agent-Guided Schema Negotiation (Validation)

**Goal:** Validate that the agent can reliably analyse a codegen prompt and propose a sensible parameter/profile split. Zero code changes to codegen — this is purely an agent system prompt directive.

### Changes

- **`src/micro_x_agent_loop/system_prompt.py`** — Add a codegen preparation directive to the system prompt. When the user asks to generate a reusable app, the agent should:
  1. Read the prompt (or prompt file)
  2. Analyse the variable data and classify into three categories:
     - **Run parameters** — values that change between executions (e.g. date range, output directory). These become the MCP tool input schema with types, defaults, and descriptions.
     - **Profile configuration** — values stable across runs but specific to the user or use case (e.g. candidate skills, scoring thresholds, preferred sources). These go into `profile.json`.
     - **Constants** — values that define what the app *does* (e.g. scoring logic, report format, link rewriting). Hardcoded in generated code.
  3. Present the proposal in a structured format (not free-form prose)
  4. Ask the user for confirmation or adjustments via `ask_user`
  5. Iterate until the user confirms
  6. Only then call `generate_code` with the agreed contract

### Acceptance Criteria

- Agent produces a structured proposal with run params (name, type, default, description), profile structure, and constants
- Proposal format is consistent across different prompts
- Agent correctly distinguishes run-time variability from user-level configuration
- Agent incorporates user feedback and re-presents the updated proposal
- Tested against at least 3 different prompts:
  - `job-search-prompt-v3.txt` (complex, multi-source, scoring)
  - A simple prompt (e.g. "summarise my last 20 emails")
  - A prompt with no obvious parameters (e.g. "list my calendar events for today")

### Risks

- The agent may produce inconsistent proposal formats without a strict template in the directive
- The agent may over-parameterise (everything becomes a parameter) or under-parameterise (everything hardcoded)
- The negotiation may add friction for users who just want a quick one-off generation — need a way to skip it

## Step 2: Codegen Template and Prompt for MCP Server Generation

**Goal:** Extend the codegen server and TypeScript template to generate MCP servers with typed input schemas and `profile.json` support.

### Changes

- **`tools/template-ts/`** — New or modified infrastructure files:
  - `src/index.ts` — Rewrite as MCP server entry point instead of script runner. Starts a FastMCP server that exposes generated tools.
  - `src/task.ts` — New contract: export tool definitions (name, description, input schema, handler) instead of a single `runTask` function.
  - `profile.json` — Template file, populated with user-specific values at generation time.
  - Existing infrastructure (`mcp-client.ts`, `tools.ts`, `llm.ts`, `utils.ts`, `test-base.ts`) — Unchanged. The generated server is both MCP server (exposing tools) and MCP client (calling other MCP servers).

- **`mcp_servers/python/codegen/main.py`**:
  - `build_system_prompt()` — Updated to instruct the LLM to generate an MCP server tool definition with the agreed input schema, read `profile.json` at runtime, and return structured output.
  - `generate_code()` — Write `profile.json` alongside generated code, populated with values from the prompt.
  - `parse_files()` — Accept `.json` files (for `profile.json`) in addition to `.ts`.

- **Codegen system prompt** — New sections:
  - MCP server tool registration pattern (schema, handler, structured return)
  - `profile.json` contract: read at startup, typed interface, values from original prompt
  - Guidance on what belongs in input schema vs profile vs constants

### Acceptance Criteria

- Generated app is a working MCP server that exposes at least one tool
- Tool has a typed input schema matching the agreed run parameters
- `profile.json` is generated with values extracted from the original prompt
- Profile values are read at runtime, not hardcoded
- Generated server connects to upstream MCP servers (gmail, linkedin, etc.) as a client
- Vitest validation still works (tests cover pure logic, not MCP server registration)

### Risks

- Template complexity increases significantly — `index.ts` becomes an MCP server instead of a simple script runner
- Dual-role lifecycle (server + client) may introduce startup/shutdown issues
- The codegen LLM must understand MCP server registration patterns — more complex generation task

### Open Questions

- Should the template support multiple tools per server, or one tool per generated app?
- Does `run_task` remain as a fallback for standalone execution, or is it replaced entirely?
- How does the generated server handle errors and partial results in structured output?

## Step 3: End-to-End Integration

**Goal:** Wire up the full flow: agent negotiation → `generate_code` with contract → generated MCP server → agent connects to it.

### Changes

- **Agent → codegen handoff** — After negotiation, the agent composes a `generate_code` call that includes:
  - The original prompt/requirements
  - The agreed run parameter schema (names, types, defaults, descriptions)
  - The agreed profile structure and values
  - This may require a new parameter on `generate_code` (e.g. `contract: dict`) or a structured prompt format the codegen LLM understands.

- **Dynamic MCP server connection** — After generation, the agent connects to the new MCP server mid-session without requiring a restart. Options:
  - Register in `config.json` and reconnect MCP servers
  - Dynamic server addition via `mcp_manager.py`
  - Manual: user restarts the agent (simplest, least friction for v1)

- **Broker integration** — Generated MCP server tools can be referenced in broker job prompts, enabling scheduled execution.

### Acceptance Criteria

- User can go from prompt → negotiation → generation → tool call in a single session
- Generated tool appears in the agent's tool list after connection
- Agent can call the generated tool with run parameters
- Profile can be edited by the user between runs without regenerating

### Risks

- Schema fidelity: the agent must pass the negotiated contract to codegen without losing detail. If it paraphrases, the generated code won't match.
- Dynamic server connection may require significant changes to `mcp_manager.py` and the agent lifecycle.
- Config registration creates permanent entries — need cleanup when tasks are deleted.

## Dependencies

- Step 1 has no code dependencies — can start immediately
- Step 2 depends on Step 1 validation (confirms the approach works)
- Step 3 depends on Step 2 (needs the MCP server template)
- Step 2 may benefit from the sub-agent architecture if available (see `PLAN-sub-agents.md`)
