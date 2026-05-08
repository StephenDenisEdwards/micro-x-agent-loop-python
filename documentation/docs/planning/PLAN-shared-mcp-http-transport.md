# Plan: Shared MCP servers via HTTP transport

**Status: Planned** (2026-05-08)

## Context

Resolves [ISSUE-006: Playwright profile contention](../issues/ISSUE-006-playwright-profile-contention.md). Implements **Option D** of that issue: convert selected MCP servers (Playwright in particular) from stdio to HTTP transport so the agent and any codegen subprocess can both attach to the same single server instance, instead of each spawning their own.

Read ISSUE-006 first for the full design rationale and trade-offs vs Options A–C. This document is the implementation plan only.

## Goal

After this plan lands:

- `@playwright/mcp` is started once per agent boot and listens on a configurable local HTTP port. The agent and any codegen task subprocess connect to it as MCP clients via HTTP.
- One Edge process holds the persistent profile lock; concurrent MCP clients on the same browser are safe (each gets its own `BrowserContext`).
- The `tools/jobserve_apply/` reproduction case from ISSUE-006 runs to completion without profile-lock timeout.
- Servers without contention problems (gmail, linkedin, web, github, …) keep their existing stdio bootstrap unchanged. The change is opt-in per server via a `transport: "http"` field in `config-base.json`.

Lifecycle stays local: agent spawns the HTTP server as a subprocess at boot, kills it on shutdown. HTTP only changes the wire protocol, not who owns the process. (See ISSUE-006 §"Transport vs lifecycle.")

## Phase 0 — Verification spike (BLOCKS the rest of the work)

Two empirical questions must be answered before any code lands. If either fails, the plan needs revision.

**0a. Does `@playwright/mcp` actually serve over HTTP?**

```powershell
npx -y @playwright/mcp@latest --browser msedge --port 8081
```

From a separate shell, hit it: `curl http://localhost:8081/sse` (or whatever endpoint it advertises — check `--help`). Expectation: an SSE-style streaming response or an MCP handshake reply. If `--port` isn't a real flag, look for the equivalent in the package's documentation. If there's no HTTP transport at all, Option D is dead and we either fork the package, switch to a different Playwright-MCP wrapper, or fall back to ISSUE-006 Option C.

**0b. Does it isolate concurrent clients?**

Spin up one server. Connect twice from two trivial Node scripts using `@modelcontextprotocol/sdk`'s SSE client. From client A: `browser_new_context` then `browser_navigate(URL_A)`. From client B: same with `URL_B`. Verify each client sees its own page, no clobbering.

If `@playwright/mcp` shares one active page across all clients, every client must explicitly carry a context handle on every call — feasible but adds friction throughout the codebase. Decide outcome here before proceeding.

**Output of phase 0:** documented yes/no on both questions, the actual SSE/HTTP URL format, and whether per-client `BrowserContext` works as expected. ~30–60 minutes.

## Phase 1 — Python side: `mcp_manager.py` learns HTTP

**Files:** `src/micro_x_agent_loop/mcp/mcp_manager.py`

Changes:

- Read a new optional `transport: "stdio" | "http"` field per server in `_server_configs`. Default `"stdio"` for backwards compatibility.
- For `transport: "http"` servers in `_ServerConnection.start`:
  1. Spawn the subprocess with the configured `command`/`args` (where `args` includes `--port <N>`). Same lifecycle as today — agent owns the process, kills it on shutdown.
  2. Poll `http://localhost:<port>` until ready (200ms intervals, 30s timeout). On timeout, log and raise.
  3. Connect via the Python `mcp` library's HTTP/SSE client transport (likely `mcp.client.sse.sse_client` or `streamablehttp_client` — the spike confirms which).
- The existing `_run_stdio` becomes one of two transport strategies, picked by config.

**Tests:** existing stdio path keeps working unchanged. Add one test that mocks an HTTP MCP endpoint (use `aiohttp` test server or similar) and verifies `mcp_manager` connects and discovers tools.

**Done when:** changing only `playwright`'s entry in `config-base.json` to `transport: "http"` (with `--port 8081` in args) boots the agent successfully and the agent can drive a browser via Playwright over HTTP. All other servers remain stdio and unaffected.

**Effort:** ~half a day.

## Phase 2 — TypeScript side: `_runtime/src/mcp-client.ts` learns HTTP

**Files:**

- `tools/_runtime/src/mcp-client.ts` — the `McpClient` wrapper used by every codegen task.
- `tools/template-ts/src/index.ts:connectUpstream` — only if it needs to know about the env var directly; ideally not.

Changes to `McpClient.connect()`:

- Before deciding on transport, look up `MICRO_X_${name.toUpperCase().replaceAll('-','_')}_MCP_URL` in `process.env`.
- If set: instantiate `SSEClientTransport` from `@modelcontextprotocol/sdk/client/sse.js` (or `StreamableHTTPClientTransport` if the spike showed that's what `@playwright/mcp` speaks) using `new URL(url)`. Skip the `command`/`args` spawn entirely.
- If not set: fall back to the current `StdioClientTransport` spawn. Existing behaviour preserved.

The `McpClient.connect()` external signature stays `(command, args, env)` — the transport switch happens internally. `connectUpstream` doesn't need to know.

**Tests:** add a test that exports `MICRO_X_PLAYWRIGHT_MCP_URL=...` and verifies the client picks SSE transport instead of stdio. The migrated tasks' existing test suites (`jobserve_rss_aggregator`, etc.) should keep passing unchanged.

**Done when:** running a task standalone (`npx tsx src/index.ts --run`) still works as before, and running it with `MICRO_X_PLAYWRIGHT_MCP_URL` set in the env attaches it to that URL instead of spawning a new server.

**Effort:** ~half a day.

## Phase 3 — Codegen wiring: `run_task` injects URLs

**File:** `mcp_servers/python/codegen/main.py`

Changes to `run_task`:

- Read `MICRO_X_AGENT_CONFIG_JSON` from env (already forwarded by the agent — see `manifest.py:128`).
- For each server in the config with `transport: "http"`, compute its URL: `http://localhost:<port>` from the `--port` value in `args`. (For now we infer; later we can support an explicit `url` field if needed.)
- Build an `env` dict starting from `os.environ.copy()`, with one `MICRO_X_<NAME>_MCP_URL` entry per HTTP-transport server.
- Pass `env=env` to the existing `subprocess.run(...)` call.

That's it — the codegen subprocess inherits the URLs and Phase 2's `McpClient` handles the rest.

**Tests:** an integration test that exercises `run_task` with a stub HTTP MCP server and asserts the env var arrived in the subprocess. Or do this manually for the first iteration.

**Done when:** a codegen task with `SERVERS: ["playwright"]` runs end-to-end against the agent's already-running Playwright HTTP server, with no second `@playwright/mcp` spawn happening.

**Effort:** ~1–2 hours.

## Phase 4 — Convert Playwright in `config-base.json`

The smallest change but goes last because Phases 1–3 must already work.

```jsonc
"playwright": {
  "transport": "http",
  "command": "npx.cmd",
  "args": [
    "-y", "@playwright/mcp@latest",
    "--browser", "msedge",
    "--user-data-dir", "C:\\Users\\steph\\.playwright-mcp",
    "--port", "8081"
  ]
}
```

Other servers stay stdio. This conversion is opt-in per server.

**Done when:** a codegen task runs Playwright operations successfully. The `tools/jobserve_apply/` reproduction case from ISSUE-006 now works; profile-lock conflict gone. Any standalone task that doesn't go through the agent (e.g. an `npx tsx … --run` invocation outside the agent) still spawns its own Playwright server because no env var hint is present.

**Effort:** 5 minutes.

## Risk register

| Risk | Mitigation |
|---|---|
| `@playwright/mcp` doesn't support `--port` flag | Phase 0a catches this. Fallback: fork the package, adopt an alternate wrapper, or accept ISSUE-006 Option C. |
| `@playwright/mcp` shares one active page across clients | Phase 0b catches this. Fallback: every client carries an explicit `BrowserContext` handle on every call. |
| Hardcoded port 8081 collides with something on the user's machine | Make it configurable per-server in `config-base.json`. Document. Don't auto-allocate ephemeral ports yet. |
| Boot-time race: agent connects before HTTP server is ready | Polling-with-backoff in `mcp_manager.py` handles this. 30s timeout, raise on overrun. |
| Agent crashes ungracefully → orphaned `@playwright/mcp` holds the profile lock | `McpManager.close()` already kills children on shutdown. Verify it's robust to Ctrl+C and process-tree termination. May need a SIGTERM handler. |
| Existing stdio servers regress because of the refactor | Default `transport: "stdio"` in the new config field; existing config entries continue to work unchanged. Cover with a regression test. |
| `MICRO_X_<NAME>_MCP_URL` naming collides with an env var the user already has | Document the convention. The `MICRO_X_` prefix should be unique enough to be safe. |

## Open questions to resolve during implementation

1. Which HTTP transport does `@playwright/mcp` actually serve — SSE, streamable-HTTP, or both? Phase 0 answers this and pins the client-side library calls.
2. Port-allocation policy — start with hardcoded values per server in config; if conflicts become a real problem, add a discovery mechanism (read stdout for a "Listening on …" line, or scan a port range).
3. Should `mcp-client.ts` (TypeScript) support both SSE and streamable-HTTP transports, or just match whichever Phase 1 picks for Python? Probably match-and-extend-later — keep code paths minimal.

## Acceptance criteria for the change as a whole

- `tools/jobserve_apply/` (ISSUE-006 reproduction) runs to completion without profile-lock timeout.
- Running the same task standalone outside the agent still works as before — env var absent → stdio spawn.
- Other codegen tasks (`jobserve_rss_aggregator`, `jobserve_email_scraper`, `linkedin_job_scraper`) continue to work unchanged — they don't list `playwright` in `SERVERS`.
- `/cost` and the `__USAGE__:` cost-tracking sentinel still work (orthogonal, but worth verifying).
- `mcp_manager.py` regression-tests pass for the existing stdio path.
- ISSUE-006 status moves to **Resolved** with a `## Resolution` section pointing at the relevant commits.
- INDEX.md in `documentation/docs/planning/` is updated.

## Effort estimate

Roughly **1.5 days of focused work** end-to-end, gated on Phase 0's verification spike.

| Phase | Effort | Dependencies |
|---|---|---|
| 0 — Verification spike | 30–60 min | none |
| 1 — Python `mcp_manager.py` HTTP | half day | Phase 0 |
| 2 — TS `McpClient` HTTP | half day | Phase 0 |
| 3 — `run_task` env var injection | 1–2 hours | Phases 1, 2 |
| 4 — Flip `config-base.json` | 5 min | Phases 1, 2, 3 |

Phases 1 and 2 can run in parallel.

## Related

- [ISSUE-006: Playwright profile contention](../issues/ISSUE-006-playwright-profile-contention.md) — design rationale and Options A–D.
- `tools/jobserve_apply/` — concrete reproduction case; should pass after this plan ships.
- `src/micro_x_agent_loop/mcp/mcp_manager.py` — Phase 1 target.
- `tools/_runtime/src/mcp-client.ts` — Phase 2 target.
- `mcp_servers/python/codegen/main.py` — Phase 3 target.
- `config-base.json` — Phase 4 target.
