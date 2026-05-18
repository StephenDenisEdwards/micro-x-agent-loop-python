# ADR-025: Native in-process tools for core primitives; MCP for external + isolatable subsystems

## Status

Accepted — 2026-05-18. **Amends [ADR-015](./ADR-015-all-tools-as-typescript-mcp-servers.md)** (whose blanket "all tools are TypeScript MCP servers" rule no longer holds — see Decision).

## Context

ADR-015 established that *every* tool is a TypeScript MCP server in a separate process. In practice this proved to be the wrong default for the agent's **core primitives** (filesystem IO, bash, grep, glob, system info):

- A multi-day debugging session was dominated by MCP-transport failure modes on these hot, frequently-called tools: stdio/SSE read-timeouts, pydantic notification-validation spam, `cmd.exe`-vs-bash divergence on Windows, subprocess lifecycle/rate-limit entanglement. None of that is intrinsic to the tool's job — it's transport tax.
- Per-call subprocess round-trips add latency to the hottest tools.
- An out-of-process tool can only be tested through an MCP harness; in-process Python tools are testable with plain pytest.
- Mainstream agents (Claude Code's `Read`/`Write`/`Edit`/`Grep`/`Glob`/`Bash`, etc.) implement core primitives as **native in-process built-ins**. ADR-015's "everything is an MCP server" is the outlier, not the norm. MCP was designed for talking to systems you don't own — not for your own core capability.

A naïve correction ("first-party → native, third-party → MCP") was considered and rejected as the wrong axis: `codegen` is first-party but is a heavyweight subsystem (it runs its *own* nested Anthropic agentic loop, spawns `npm`/`tsx` builds, mutates `manifest.json`, has its own venv and `MICRO_X_*_MCP_URL` plumbing). Pulling it in-process would entangle a second long-running LLM loop with the agent and remove the crash/hang isolation a subprocess gives it — for ~zero benefit, since codegen is rarely called and inherently multi-minute, so transport overhead is noise.

## Decision

Tool hosting is chosen by **what the tool is**, on a single axis: *lightweight primitive* vs *heavyweight isolatable subsystem* — **not** first-party vs third-party.

**Native (in-process Python `Tool`-protocol objects):** lightweight, fast, stateless, frequently-called core primitives.
- `system-info` — done (commit `fee58a5`).
- `filesystem` — next (read/write/edit/append/delete/grep/glob/bash/save-memory). The hot path; highest native payoff.

**MCP (out-of-process server):** both of —
- External / third-party integrations (gmail, github, linkedin, web, playwright, …) — unchanged.
- First-party but **heavyweight, slow, crash-prone, isolatable subsystems**. `codegen` stays MCP: its own nested LLM loop + subprocess builds + own venv; subprocess isolation is a *feature* (a codegen blow-up cannot take the agent down), and its native speed payoff is ~zero.

Native tools implement the existing `Tool` Protocol (`src/micro_x_agent_loop/tool.py`) — same interface MCP tools are proxied into, so the agent, routing, tool-search, and truncation layers treat them identically. They are registered in `src/micro_x_agent_loop/native_tools/` via `build_native_tools()`, appended to the tool list in `bootstrap.py`, and **logged at startup alongside MCP servers** (`Native tools: N tool(s) registered (...)` next to `MCP server 'X': N tool(s) discovered`).

Fully-qualified tool names are preserved across the migration (`system-info__system_info`, `filesystem__bash`, …) so nothing referencing them — directives, routing policies, tool-search, evals — breaks.

## Consequences

### Positive
- Eliminates the MCP-transport failure class for the hottest tools (no stdio/SSE, no subprocess lifecycle, no notification-validation spam).
- Lower latency on the hot path; one less subprocess/venv/external repo per migrated primitive (system-info dropped a whole .NET dependency).
- Core tools become unit-testable with plain pytest — directly strengthens the behavioural-eval work (ISSUE-007 / PLAN-behavioural-eval-suite).
- A clear, defensible hosting rule that won't need re-litigating per tool.

### Negative
- A native tool runs in the agent process: a bug there is an agent bug, not a contained subprocess failure. Mitigated by keeping only *simple, well-tested* primitives native and leaving genuinely risky subsystems (codegen) isolated.
- The filesystem port is a **full Python reimplementation** of ~1.6k LOC of TypeScript (9 tools + `PathPolicy`), and there is **no existing TS test suite** to port — behaviour must be pinned by *new* characterization tests. This is the main execution risk; addressed in PLAN-behavioural-eval-suite + dedicated filesystem tests, and the port is sequenced last and reviewed before starting.
- Config sourcing changes: `filesystem_roots_from_mcp_config` (commit `e5c6e9e`) currently reads allowed/readonly roots from the *filesystem MCP server's env block*. Once filesystem is native there is no such block; roots must be sourced from agent config instead. Tracked as part of the filesystem port.

### Neutral / on the record
- This ADR amends but does not delete ADR-015: TypeScript MCP servers remain correct for external integrations and isolatable subsystems. ADR-015's error was the word "all".
- Recording the reversal explicitly (rather than letting the rule drift) is the [ISSUE-007](../../issues/ISSUE-007-prose-contract-drift-across-policy-layers.md) discipline applied to ourselves.

## Alternatives considered

- **Keep ADR-015 as-is (everything MCP).** Rejected: the transport tax on hot primitives is real and recurring; mainstream practice disagrees.
- **Everything native (including codegen).** Rejected: removes crash/hang isolation from a heavyweight nested-agent subsystem for no speed benefit; highest risk, lowest payoff.
- **Axis = first-party vs third-party.** Rejected: misclassifies codegen (first-party yet must stay isolated). The correct axis is primitive vs isolatable-subsystem.

## References

- [ADR-015](./ADR-015-all-tools-as-typescript-mcp-servers.md) — amended by this ADR.
- [ADR-023](./ADR-023-file-handling-truncation-signaling.md), [ADR-024](./ADR-024-single-layer-tool-result-truncation.md) — filesystem truncation/signalling behaviour the native port must preserve faithfully.
- [ISSUE-007](../../issues/ISSUE-007-prose-contract-drift-across-policy-layers.md) — record reversals; don't let policy drift silently.
- `src/micro_x_agent_loop/native_tools/` — the native-tool pattern (system-info is the reference implementation).
- `src/micro_x_agent_loop/bootstrap.py` — native registration + startup listing.
