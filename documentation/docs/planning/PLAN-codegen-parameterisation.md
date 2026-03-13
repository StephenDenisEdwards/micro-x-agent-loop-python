# Plan: Codegen — Parameterised MCP Server Generation

**Status: Completed** (2026-03-11)

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

### Implementation Notes

**Files modified:**
- `src/micro_x_agent_loop/system_prompt.py` — Added `_CODEGEN_DIRECTIVE` with Non-negotiable rules, Process steps, and Guidelines. Always included in the system prompt (harmless if codegen not configured).

**Directive iterations:**
1. Initial version: guidelines-level instruction to only parameterise from the prompt. Agent ignored it and invented 6 profile fields (time_format, include_declined, highlight_keywords, etc.).
2. Added explicit negative examples to guidelines. Agent reduced to 4 invented fields.
3. Promoted to Non-negotiable section at top of directive with concrete examples of what NOT to do. Agent reduced to 1 pragmatic field (calendar_id — needed by the API).

**Key learning:** LLMs treat guidelines as suggestions. Binary rules in a "Non-negotiable" section with negative examples are much more effective than positive guidance buried in a list.

### Test Results (2026-03-11)

| # | Test | Result | Notes |
|---|------|--------|-------|
| 3 | Calendar daily briefing | Pass | Clean after directive iteration. 2 run params, empty profile (1 pragmatic API field). |
| 4 | GitHub repo health | Pass | `repo` correctly as run param. Thresholds in profile (debatable but reasonable). |
| 5 | Research with scoring | Pass | Good pattern recognition. Keywords/weights in profile, topic as run param. |
| 6 | LinkedIn job search | Pass | Correct profile/param split for user-specific data. |
| 7 | Simple one-off | Pass | Skipped negotiation, generated directly. |
| 8 | Explicit skip | Pass | Respected "don't ask me about parameters", generated directly. |
| 9 | Contacts cleanup | Pass | Empty profile with clear reasoning ("pure analysis task"). |
| 10 | Cost tracking | Pass | Empty profile, pragmatic run params (date range, bucket width). |
| 12 | Ambiguous (email monitor) | Partial | Chose to propose (reasonable). Invented `summary_format` (not in prompt). Core fields correct. |

**Remaining observations:**
- The agent occasionally adds 1 pragmatic field not explicitly in the prompt (e.g. `calendar_id`, `max_results`) when the underlying API requires it. This is acceptable — surfacing a necessary implementation detail as configurable is reasonable.
- Profile/run-param boundary is sometimes debatable (e.g. thresholds in test 4). The negotiation handles this — the user can move items.
- Compiled mode detection and parameterisation negotiation both trigger on the same prompts. They work together but should eventually be unified.
- Tests 1, 2, 11 not yet run. Core validation is sufficient — all three categories (complex, simple, skip) are covered.

## Step 2: Codegen Template and Prompt for MCP Server Generation — Complete

**Goal:** Extend the codegen server and TypeScript template to generate MCP servers with typed input schemas and `profile.json` support. Generated servers are registered in a manifest file and discovered via tool search — not added to `config.json`.

### Changes

- **`tools/template-ts/`** — New or modified infrastructure files:
  - `src/index.ts` — Rewrite as MCP server entry point instead of script runner. Starts a FastMCP server that exposes generated tools. Uses stdio transport (no daemon — started on demand, exits when done).
  - `src/task.ts` — New contract: export tool definitions (name, description, input schema, handler) instead of a single `runTask` function.
  - `profile.json` — Template file, populated with user-specific values at generation time.
  - Existing infrastructure (`mcp-client.ts`, `tools.ts`, `llm.ts`, `utils.ts`, `test-base.ts`) — Unchanged. The generated server is both MCP server (exposing tools) and MCP client (calling other MCP servers).

- **`tools/manifest.json`** — New file. Registry of all generated MCP servers. Updated by `generate_code` on creation. Structure:
  ```json
  {
    "job_search": {
      "description": "Search job boards, score and rank matches against profile",
      "input_schema": {
        "days": { "type": "number", "default": 1, "description": "How far back to search" },
        "outputDir": { "type": "string", "default": ".", "description": "Where to write the report" }
      },
      "created": "2026-03-11",
      "server": {
        "transport": "stdio",
        "command": "npx",
        "args": ["tsx", "src/index.ts", "--config", "../../config.json"],
        "cwd": "tools/job_search/"
      }
    }
  }
  ```
  The manifest serves double duty: task catalogue (discovery, metadata) and MCP server config (transport, command, cwd). Separate from `config.json` so generated servers don't pollute the core agent config.

- **`mcp_servers/python/codegen/main.py`**:
  - `build_system_prompt()` — Updated to instruct the LLM to generate an MCP server tool definition with the agreed input schema, read `profile.json` at runtime, and return structured output.
  - `generate_code()` — Write `profile.json` alongside generated code, populated with values from the prompt. Update `tools/manifest.json` with the new server entry.
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
- `tools/manifest.json` is created/updated with the new server entry
- Vitest validation still works (tests cover pure logic, not MCP server registration)

### Risks

- Template complexity increases significantly — `index.ts` becomes an MCP server instead of a simple script runner
- Dual-role lifecycle (server + client) may introduce startup/shutdown issues
- The codegen LLM must understand MCP server registration patterns — more complex generation task

### Resolved Questions

- **One tool per server.** Each generated app exposes a single MCP tool. Simpler to generate, test, and reason about. Multiple related tasks = multiple servers.
- **`run_task` becomes a fallback.** The primary path is MCP tool invocation via the agent. `run_task` remains for standalone execution (`--run` flag) — e.g. cron jobs, manual runs.
- **Stdio transport, no daemon.** Generated servers use stdio — started on demand by `mcp_manager`, exit when the connection closes. No stay-alive process management needed.

### Implementation Notes

**Files modified:**
- `tools/template-ts/package.json` — Added `zod@^3.25.0` dependency
- `tools/template-ts/src/index.ts` — Complete rewrite. Dual-mode: MCP server (default, stdio) or standalone (`--run`). Lazy upstream MCP client connection on first tool call. Loads `profile.json` from task directory.
- `tools/template-ts/src/task.ts` — New contract: exports `SERVERS`, `TOOL_NAME`, `TOOL_DESCRIPTION`, `TOOL_INPUT_SCHEMA` (Zod raw shape), `handleTool(input, clients, profile, config)`
- `tools/template-ts/profile.json` — Empty template file (`{}`)
- `mcp_servers/python/codegen/main.py`:
  - `build_system_prompt()` — New runtime contract describing MCP server exports, `TOOL_INPUT_SCHEMA` format with Zod, `profile.json` contract
  - `parse_files()` — Now accepts `.json` files
  - `generate_code()` — Writes `profile.json` to task root, updates `tools/manifest.json`
  - `_update_manifest()` — New helper: parses `TOOL_NAME`/`TOOL_DESCRIPTION` from generated task.ts
  - `run_task()` — Passes `--run` flag for standalone execution

**Key design decisions:**
- The LLM generates `TOOL_INPUT_SCHEMA` as a flat Zod raw shape (not `z.object()`). `index.ts` handles `McpServer.tool()` registration — the LLM never touches the MCP server API directly.
- `handleTool` returns `Record<string, unknown>` — `index.ts` wraps it into MCP `content` format.
- Upstream MCP clients connect lazily on first tool call, not at server startup. This avoids startup-ordering issues and unnecessary connections.
- In MCP server mode, all logging goes to stderr (stdout is the MCP transport).
- `profile.json` is NOT in `INFRASTRUCTURE_FILES` — the LLM generates it with values from the user's prompt.

## Step 3: Discovery and Integration via Tool Search — Complete

**Goal:** Wire up the full flow: agent negotiation → `generate_code` with manifest entry → tool search discovers generated tools → agent connects and calls them on demand.

### Approach: Manifest + Tool Search

Generated MCP servers are **not** added to `config.json`. Instead:

1. `generate_code` writes the server entry to `tools/manifest.json`
2. The tool search mechanism is extended to include manifest entries in its search index
3. When the agent needs a generated tool, it uses tool search (as it does for any other tool)
4. Tool search returns the manifest entry with connection details
5. `mcp_manager` connects to the server on demand via stdio
6. The tool becomes available for the remainder of the session

This leverages the existing tool search infrastructure — no new discovery mechanism needed. Generated tools are treated the same as any other tool in the ecosystem, just with a different registration path.

### Changes

- **`src/micro_x_agent_loop/tool_search.py`** — Extend the search index to include entries from `tools/manifest.json`. Each manifest entry becomes a searchable tool with its description and input schema.

- **`src/micro_x_agent_loop/mcp/mcp_manager.py`** — Add ability to connect to a new MCP server mid-session given a manifest entry (transport, command, args, cwd). The connection follows the same lifecycle as startup-connected servers.

- **Agent → codegen handoff** — After negotiation, the agent composes a `generate_code` call that includes:
  - The original prompt/requirements
  - The agreed run parameter schema (names, types, defaults, descriptions)
  - The agreed profile structure and values
  - This may require a new parameter on `generate_code` (e.g. `contract: dict`) or a structured prompt format the codegen LLM understands.

- **Broker integration** — Generated MCP server tools can be referenced in broker job prompts. The broker reads `tools/manifest.json` to resolve server connection details, enabling scheduled execution without `config.json` changes.

### Acceptance Criteria

- Tool search returns generated tools from the manifest alongside regular tools
- Agent can discover a generated tool via tool search without knowing the exact name
- `mcp_manager` can connect to a manifest server mid-session
- User can go from prompt → negotiation → generation → tool search → tool call in a single session
- Agent can call the generated tool with run parameters
- Profile can be edited by the user between runs without regenerating
- Manifest entries persist across agent restarts

### Risks

- Schema fidelity: the agent must pass the negotiated contract to codegen without losing detail. If it paraphrases, the generated code won't match.
- Mid-session MCP server connection requires changes to `mcp_manager.py` — must handle startup errors gracefully without crashing the session.
- Manifest file could become stale if task directories are manually deleted. Need a validation step (check `cwd` exists) when loading.

### Implementation Notes

**New file:**
- `src/micro_x_agent_loop/manifest.py` — `ManifestTool` class (implements Tool protocol, connects on first `execute()` call) + `load_manifest()` loader

**Files modified:**
- `src/micro_x_agent_loop/mcp/mcp_manager.py`:
  - `connect_on_demand(server_name, config)` — Starts an MCP server mid-session, returns discovered tools, keeps connection for cleanup
  - `_run_stdio()` — Now passes `cwd` to `StdioServerParameters` (SDK supports it)
- `src/micro_x_agent_loop/bootstrap.py` — Loads `tools/manifest.json` after MCP server connection, creates `ManifestTool` instances, adds to tool list

**How it works:**
1. `bootstrap_runtime()` loads `tools/manifest.json` and creates `ManifestTool` placeholders
2. Placeholders implement the `Tool` protocol → indexed by `ToolSearchManager` automatically
3. Agent discovers tools via `tool_search` (keyword matching against name + description)
4. When the LLM calls a manifest tool, `ManifestTool.execute()` fires:
   a. Calls `mcp_manager.connect_on_demand()` → starts the generated MCP server via stdio
   b. Finds the matching `McpToolProxy` by name (`task_name__tool_name`)
   c. Delegates the call to the real proxy
   d. Caches the proxy for subsequent calls in the same session
5. Connection persists for the session, cleaned up by `mcp_manager.close()`

**Stale entry handling:** `load_manifest()` validates that each entry's `cwd` directory exists. Missing directories are skipped with a warning.

### Why Not `config.json`?

- `config.json` is the user's curated, permanent MCP server configuration. Generated servers are dynamic and potentially numerous.
- Adding to `config.json` creates permanent entries that require manual cleanup. The manifest is self-contained and can be regenerated from the `tools/` directory.
- `config.json` supports `Base` inheritance and `ConfigFile` indirection — complexity that generated servers don't need.
- The manifest approach keeps concerns separated: `config.json` = infrastructure, `manifest.json` = generated apps.

## Dependencies

- Step 1 has no code dependencies — can start immediately
- Step 2 depends on Step 1 validation (confirms the approach works)
- Step 3 depends on Step 2 (needs the MCP server template and manifest)
- Tool search extension (Step 3) is independent of the template changes (Step 2) and could be developed in parallel
