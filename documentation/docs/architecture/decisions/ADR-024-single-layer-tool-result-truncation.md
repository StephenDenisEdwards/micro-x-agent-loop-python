# ADR-024: Single-Layer Tool-Result Truncation Policy

## Status

Accepted — 2026-05-14

## Context

Tool results flow through four layers between the upstream call and the conversation that the model sees:

```
upstream service                                                  conversation
       │                                                                ▲
       ▼                                                                │
   MCP server  ──►  task wrapper (tools.ts)  ──►  TurnEngine  ──►  model context
   (web-fetch.ts,   (per codegen task,             (agent, applies
    read-file.ts,    hand-written, was             ToolResultOverrides)
    …)              copied from a template)
```

Each layer historically had its own char-cap default:

| Layer | Where | Old default |
|------|-------|------------|
| `web_fetch` MCP server | `mcp_servers/ts/packages/web/src/tools/web-fetch.ts` — `DEFAULT_MAX_CHARS` | 50,000 |
| Codegen template wrapper | `codegen-templates/template-ts/src/tools.ts` — `webFetch(..., maxChars = 50000)` | 50,000 |
| Per-task wrapper | `tools/<task>/src/tools.ts` — same line, copied at task generation | 50,000 |
| `ToolResultOverrides` | `config-base.json` — `web__web_fetch.MaxChars` | configurable (e.g. 200,000) |

None of those layers knew about the others. The user-visible signal was the bottom-most one — `ToolResultOverrides` — but the actual truncation usually fired in the top-most one, with the bottom layers seeing a pre-shrunk payload. Two concrete symptoms drove this ADR:

1. **Lifted caps did not lift caps.** A `ToolResultOverrides[web__web_fetch] = { MaxChars: 200000 }` setting did nothing useful: the MCP server had already cut at 50,000 before the agent's override ever saw the data. The agent's `[OUTPUT TRUNCATED: Showing 200,000 of N characters]` diagnostic could not fire either, because no result it ever processed exceeded 200,000.
2. **Per-task wrappers re-introduced the cap silently.** Setting the server-side default to "no cap" did not help any existing codegen task, because each per-task `tools.ts` had its own `maxChars = 50000` default at the wrapper layer. A user can correctly remove the server-side default, the wrapper layer, *and* configure the agent override — and still find their task hitting 50,000 because a different task's `tools.ts` retained the wrapper-level default.

The failure mode is the worst kind of layered system: each individual cap is small and seems sensible in isolation, but together they make the user-visible policy knob ineffective and the actual policy invisible to anyone debugging.

This complements [ADR-023](./ADR-023-file-handling-truncation-signaling.md), which addressed *what we tell the model when truncation happens*. ADR-024 addresses *where the truncation policy itself lives*.

## Decision

Tool-result char-truncation and summarisation policy lives in exactly one place: the agent's `ToolResultOverrides`, applied by `turn_engine._truncate_tool_result` and `turn_engine._summarize_tool_result`. No layer between the upstream call and the agent may apply a char-cap default.

Concretely:

### Rule 1 — MCP servers don't char-truncate by default

An MCP server tool that returns text MUST NOT have a hardcoded default character cap. It MAY accept an *opt-in* parameter (e.g. `maxChars` on `web_fetch`) the caller can pass when they specifically want a smaller payload for a probe or rate-limited path. When the parameter is omitted, the server returns the full extracted content.

A single byte-level safety cap on the raw upstream response is permitted to prevent OOM (e.g. `web_fetch`'s `MAX_RESPONSE_BYTES = 2_000_000`). This cap MUST be:

- Bytes-based, not characters-based.
- Sized so that it triggers only on pathological responses (>1MB).
- Errored, not silently truncated: if a response would exceed it, the call fails with an `UpstreamError` rather than returning a partial payload.

### Rule 2 — Codegen templates don't char-truncate by default

Wrappers in `codegen-templates/template-ts/src/tools.ts` and `tools/_runtime/src/*` MUST NOT supply a default value for any truncation-controlling parameter. The wrapper signature is `maxChars?: T`, not `maxChars: T = N`, and the parameter is forwarded to the MCP call only when explicitly provided:

```ts
// Right:
export async function webFetch(
  clients: Clients, url: WebFetchArgs["url"], maxChars?: WebFetchArgs["maxChars"],
): Promise<WebFetchResult | null> {
  const args: WebFetchArgs = { url, ...(maxChars !== undefined ? { maxChars } : {}) };
  ...
}

// Wrong (re-introduces the cap at the wrapper layer):
export async function webFetch(
  clients: Clients, url: WebFetchArgs["url"], maxChars: WebFetchArgs["maxChars"] = 50000,
): Promise<WebFetchResult | null> {
  const args: WebFetchArgs = { url, maxChars };
  ...
}
```

### Rule 3 — Per-task `tools.ts` follows the template

Codegen tasks own their `tools.ts` (it is hand-written, not auto-regenerated). The same rule applies: no defaults on truncation-controlling parameters. When the template changes, existing tasks are swept to bring them into alignment.

### Rule 4 — The agent is the policy point

`ToolResultOverrides` in `config-base.json` is the single configurable source of truth for per-tool truncation and summarisation. The override fields and their precedence are unchanged from ADR-013 / the existing implementation:

- `Summarize: bool` — gates `_summarize_tool_result`.
- `MaxChars: int` — gates `_truncate_tool_result`. `0` means "no truncation"; positive values cap the result at that many characters with a `[OUTPUT TRUNCATED: Showing N of M characters from <tool>]` notice.
- `Threshold: int` — minimum length before summarisation kicks in.

Wildcard keys (`playwright__*`) and exact-match precedence (per the wildcard-keys commit) are unchanged.

### Rule 5 — Tool descriptions don't mislead

Tool descriptions advertising a default cap that no longer exists are misleading. The `web_fetch` description was updated to: *"Optional cap on returned content characters. If omitted, the full extracted content is returned (subject only to the 2 MB raw-response byte cap). The agent applies its own `ToolResultOverrides` policy on top of whatever this tool returns."*

## Consequences

### Positive

- **Configuration actually configures.** `ToolResultOverrides[X].MaxChars = 200000` now produces results up to 200,000 chars, not 50,000. `MaxChars: 0` means no cap, end to end.
- **One place to look.** When a tool result was truncated and the model needs to know why, the only suspect is `ToolResultOverrides`. The `[OUTPUT TRUNCATED]` notice (ADR-023 territory) accurately names the only layer that acted.
- **Cheaper diagnosis.** A run that previously cost $0.64 with 4 tool errors because the LLM was working around invisible caps now costs $0.02 with 1 tool call. The agent reaches the right answer the first time because the data layer is honest about what it returned.
- **Template alignment.** Future codegen tasks inherit the right default automatically. No reviewer needs to spot `maxChars = 50000` in a hand-edited `tools.ts`.
- **Clearer boundary.** MCP servers are plumbing; agent layer is policy. The boundary is documented and enforceable.

### Negative

- **A misconfigured override can flood context.** Setting `MaxChars: 100_000_000` on a tool whose upstream can return hundreds of MB will produce conversation entries large enough to evict useful history at compaction time. The 2 MB byte cap on `web_fetch` and equivalent per-server safety nets remain as a final backstop, but the agent operator carries more responsibility for sane override values.
- **Slightly larger default payloads.** Tools that previously truncated at 50k now return their full extracted content by default — typically 5–10× larger, occasionally up to the 2 MB byte cap. The `ToolResultOverrides` defaults in `config-base.json` are the right place to set a project-wide "safe" cap; this ADR mandates *where* truncation lives, not *what value* is sensible.
- **Existing per-task `tools.ts` files were swept by hand.** Future codegen-generated tasks pick up the template change automatically, but the rule applies retroactively to anything hand-written. There's no enforcement mechanism beyond review.

### Open / deferred

- **A lint rule for the no-default invariant.** ✅ Implemented as a grep step in the `lint` job of `.github/workflows/python-tests.yml`. The check fails CI if `DEFAULT_MAX_CHARS`, `maxChars ??`, or `maxChars ||` appears in `*.ts` / `*.js` / `*.py` under `mcp_servers/`, `codegen-templates/`, `tools/`, or `src/`, excluding `src/micro_x_agent_loop/turn_engine.py` (the one allowed location).
- **Per-server byte caps**, where they exist, are not yet uniformly documented or configurable. Each MCP server currently picks its own number (`web_fetch`: 2 MB). Standardising this is out of scope.
- **Truncation telemetry**. The agent already emits `was_summarized` in tool-execution metrics. A symmetric `was_truncated` flag would make it easier to spot when `ToolResultOverrides` is actually firing in production. Not required here.

## References

- [ADR-013](./ADR-013-tool-result-summarization-reliability.md) — `ToolResultOverrides` shape and the per-tool summarisation policy this ADR builds on.
- [ADR-023](./ADR-023-file-handling-truncation-signaling.md) — In-band truncation markers. Companion piece: ADR-023 says *how to tell the model what was truncated*; ADR-024 says *where the only allowed truncation lives*.
- Commit `7d98970` — `feat(tool-results): wildcard ToolResultOverrides keys; exempt Playwright`. The wildcard-key mechanism this ADR relies on.
- Commit history (this ADR's session) — removal of `DEFAULT_MAX_CHARS = 50_000` from `web-fetch.ts`; sweep of `webFetch` wrapper across `codegen-templates/template-ts/src/tools.ts` and `tools/jobserve-processor*/src/tools.ts`.
