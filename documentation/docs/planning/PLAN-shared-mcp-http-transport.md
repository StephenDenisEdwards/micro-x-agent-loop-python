# Plan: Shared MCP servers via HTTP transport

**Status: Phases 0–1 Complete — Phases 2–4 Pending** (2026-05-08)

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

**Status: Completed (2026-05-08). Both questions answered ✅. Plan is unblocked.**

**0a. Does `@playwright/mcp` actually serve over HTTP?** ✅ Yes.

`@playwright/mcp@latest --help` advertises:

```
--port <port>    port to listen on for SSE transport.
```

Started with `npx -y @playwright/mcp@latest --browser msedge --port 8082 --isolated --headless` and probed with curl:

```
$ curl -i http://localhost:8082/sse
HTTP/1.1 200 OK
Content-Type: text/event-stream
...
event: endpoint
data: /sse?sessionId=ee3f3148-80fe-4d24-ad82-6f92171a2f09
```

Standard MCP SSE pattern: client connects to `/sse`, server returns a session-specific endpoint, MCP RPC then runs over that. Pins client-side libraries:

- Python (Phase 1): `mcp.client.sse.sse_client(url)`
- TypeScript (Phase 2): `SSEClientTransport` from `@modelcontextprotocol/sdk/client/sse.js`

**0b. Does it isolate concurrent clients?** ✅ Yes (default behaviour).

`--help` describes a `--shared-browser-context` flag: *"reuse the same browser context between all connected HTTP clients."* Default (without the flag) is per-client isolation.

Empirically confirmed with a small SSE-client script (`spike-isolation.mjs`, deleted after the test): two clients connected to the same server, A navigated to `https://example.com`, B navigated to `https://example.org`, then each ran `browser_snapshot`. Result:

```
Client A sees: https://example.com/
Client B sees: https://example.org/
✅ ISOLATED — each client has its own context
```

So no explicit `browser_new_context` plumbing is needed in client code, and `--shared-browser-context` should NOT be added to the config — default isolation is what we want.

**Useful flags discovered during the spike:**

- `--port <N>` — already known; SSE transport.
- `--host <host>` — defaults to `localhost`. Bind to `0.0.0.0` only if you need cross-machine.
- `--isolated` — keep profile in memory, don't write to disk. Useful for tests, NOT for production where we want the persistent profile.
- `--shared-browser-context` — opposite of what we want. Don't enable.
- `--headless` — useful for CI or background runs. Production agent run still wants headed for the persistent-profile flow.

**Output:** Phase 0 took ~10 minutes once the package was warmed up. Both blockers cleared.

## Phase 1 — Python side: `mcp_manager.py` learns HTTP

**Status: Complete (2026-05-08).**

**Files modified:**
- `src/micro_x_agent_loop/mcp/mcp_manager.py` — transport switching, subprocess spawn, port polling.
- `tests/test_mcp_manager.py` — 19 new unit tests (16 ExtractPort/BuildUrl/WaitForPort/StartTransportSwitch).

**Changes landed:**

- New `transport` field in server config; values `"stdio"` (default), `"sse"`, or `"http"`. Existing stdio configs unchanged.
- New module-level helpers:
  - `_extract_port(config)` — reads `port` field or scans `args` for `--port <N>`.
  - `_build_url(config, path)` — uses explicit `url` field or composes `http://<host>:<port><path>`.
  - `_wait_for_port(host, port, timeout)` — polls TCP with 200 ms backoff and 30 s default timeout.
- `_ServerConnection` gained `_proc: asyncio.subprocess.Process | None` to track spawned children.
- New `_spawn_subprocess` helper called by both HTTP-flavoured transports; preserves env-merge logic and `MICRO_X_AGENT_CONFIG_JSON` forwarding.
- `_run_sse` (new): spawn → wait for port → connect via `mcp.client.sse.sse_client` against `/sse` endpoint.
- `_run_http` (rewritten): spawn → wait for port → connect via `streamable_http_client`. Preserves "attach to a pre-running URL" by skipping spawn when no `command` is configured.
- `start()` dispatches to `_run_stdio` / `_run_sse` / `_run_http` based on the `transport` field; unknown transports raise `ValueError`.
- `stop()` now also terminates the spawned subprocess (with `kill` fallback after `_SHUTDOWN_TIMEOUT`) so HTTP/SSE-spawned servers don't leak.

**Verification:**
- 35/35 unit tests pass in `test_mcp_manager.py`.
- `mypy src/micro_x_agent_loop/mcp/mcp_manager.py` — clean.
- 55/55 pass across `test_mcp_manager.py + test_mcp_tool_proxy.py + test_bootstrap.py` — no regressions to consumers.
- End-to-end "boot the agent with playwright on HTTP and watch it work" is deferred to Phase 4 (config flip), since changing `config-base.json` for that test belongs naturally there.

**Effort actual:** ~1.5 hours.

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

1. ~~Which HTTP transport does `@playwright/mcp` actually serve — SSE, streamable-HTTP, or both?~~ **Answered by Phase 0: SSE only.** Endpoint is `/sse`, MCP SSE pattern. Pins both Python (`sse_client`) and TS (`SSEClientTransport`) library choices.
2. Port-allocation policy — start with hardcoded values per server in config; if conflicts become a real problem, add a discovery mechanism (read stdout for a "Listening on …" line, or scan a port range).
3. Should `mcp-client.ts` (TypeScript) support both SSE and streamable-HTTP transports, or just SSE? **SSE only for now** — that's what `@playwright/mcp` speaks. Add streamable-HTTP later only if a future server requires it.

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
