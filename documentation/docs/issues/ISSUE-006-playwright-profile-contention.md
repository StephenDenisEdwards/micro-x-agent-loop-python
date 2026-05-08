# ISSUE-006: Playwright profile contention between agent and codegen tasks

## Date

2026-05-08

## Status

**Open** — design decision needed before any codegen task that drives a browser ships.

## Summary

The agent runs `@playwright/mcp` as a long-lived MCP server with a persistent
user-data-dir (`config-base.json:290-298`, currently
`C:\Users\steph\.playwright-mcp`). When a codegen task lists `playwright` in
its `SERVERS:` array, `tools/<task>/src/index.ts` spawns its **own**
`@playwright/mcp` subprocess pointed at the same `--user-data-dir`. Edge holds
an exclusive lock on the profile directory, so the codegen subprocess hangs
on profile acquisition until `run_task` times out.

Symptom seen in the wild: `tools/jobserve_apply/` generated cleanly, tests
passed, but `run_task` produced `Task failed (exit code 1)` after a Playwright
"navigation timeout" because the second `@playwright/mcp` instance never
managed to attach to the locked profile.

## Background: what `--user-data-dir` actually does

`--user-data-dir` is a Chromium flag (inherited by Edge, since Edge is
Chromium-based). It tells the browser: "store all per-user state in this
directory instead of the default profile location." So the directory **is**
the browsing identity.

**Contents of a user-data-dir:**

- Cookies (SQLite DB at `Default/Cookies`)
- LocalStorage / IndexedDB
- Saved passwords (encrypted at `Default/Login Data`)
- History, bookmarks, autofill
- HTTP / image / code cache
- Installed extensions
- Per-site permissions (camera, mic, notifications)
- Preferences (zoom levels, default downloads dir, etc.)

Move the directory to another machine, you're "still logged in" everywhere on
that machine. That's why pointing Playwright at a persistent
user-data-dir is the canonical way to keep an automation logged in across
runs (`chromium.launchPersistentContext(<dir>)` under the hood).

**Why the lock exists.** When Chromium launches with a given user-data-dir,
it writes three files in that directory:

- `SingletonLock` — a file lock claiming "this profile is mine."
- `SingletonCookie` — a randomly generated token used during handshake.
- `SingletonSocket` — a Unix domain socket / Windows named pipe.

A second Chromium process trying to open the same directory sees the lock,
contacts the existing process via the socket, and asks the running browser
to open a new window. **Two separate browser processes cannot own the same
user-data-dir simultaneously** — by design, because the cookie store,
history database, and cache are SQLite / leveldb files that aren't safe
under concurrent writers.

**Two layers of eager-vs-lazy** govern when the lock is actually held:

1. **Agent → MCP server: eager.** When the agent boots, `bootstrap.py`
   calls `McpManager.connect_all()` (`mcp_manager.py:192-211`), which
   iterates every server in `config-base.json`'s `McpServers` block and
   spawns each as a subprocess — including `@playwright/mcp` — regardless
   of whether you ever invoke a Playwright tool that session. (Generated
   codegen tasks listed in `tools/manifest.json` are different: those use
   `connect_on_demand` and only spawn on first call.)

2. **MCP server → browser: lazy.** `@playwright/mcp` itself does **not**
   launch Edge at startup. The browser is only launched on the first
   `browser_navigate` / `browser_click` / etc. call from the agent. Until
   that first call, no Edge process exists and the profile dir is not
   locked.

**Net effect:** at agent boot, the `@playwright/mcp` subprocess is running
but the profile is NOT locked. A second `@playwright/mcp` (e.g. spawned
by a codegen task subprocess) could in principle start without immediate
contention. The collision materialises only at the moment one of them
makes its first browser call against the shared `--user-data-dir`.

This is what makes Option C (standalone script) practical: "don't use
Playwright in the agent while the script is running" is a contract on the
**browser** being open, not on the agent process being alive. So you
can leave the agent up; you just can't ask it to drive a page during the
window the script needs the profile.

## Why this isn't a quick fix

The lock is at the *profile directory* level, owned by Edge itself. It can't
be relaxed via Playwright flags or MCP config. Two concurrent processes,
each launching Edge with the same `--user-data-dir`, will always collide. So
the choice isn't "make the lock go away" — it's "decide which process owns
the browser, and how anything else that needs a browser gets one."

The current implicit assumption — "the agent and any codegen task can both
talk to the persistent browser by each spawning their own MCP server" —
cannot work. `@playwright/mcp` is designed for a single-agent, single-browser
relationship.

## Options considered

### Option A — Codegen tasks must NOT use Playwright via MCP

Forbid `playwright` in any codegen task's `SERVERS:` list. The codegen system
prompt advertises which MCP servers are available; remove `playwright` from
that surface (or label it agent-only). Tasks that need a browser must
`import { chromium } from "playwright"` and manage their own browser context
inline.

**Pros:** removes the failure mode at the prompt layer; no surprise spawning
of duplicate MCP servers.
**Cons:** tasks lose the ergonomic typed-tool surface that MCP provides
(`browser_navigate`, `browser_click`, …) and have to write their own
Playwright code. Doesn't solve the profile-lock issue if the task's direct
SDK launch happens to use the same profile dir.

### Option B — Tasks use Playwright SDK directly with a separate profile

Same as A, plus convention: any codegen task that uses Playwright launches
its own `chromium.launchPersistentContext(<task-specific-profile-dir>)`. The
agent's profile is one directory; each task's profile is another. Logged-in
state has to be established per-profile, but processes can run concurrently
without locking each other out.

**Pros:** concurrent operation works; tasks own their own browser lifecycle.
**Cons:** N profiles = N login sessions. Awkward for sites where you'd want
one logged-in identity across uses.

### Option C — Standalone scripts outside the agent

For tasks that need a logged-in browser session, write them as standalone
TypeScript scripts that the user runs from a terminal (`npx tsx scripts/X.ts`)
— not as codegen tasks, not as MCP tools. The script imports Playwright SDK
directly and uses the agent's persistent profile dir, but only when the
agent isn't running (or hasn't activated its Playwright MCP yet, since
@playwright/mcp launches the browser lazily on first use).

**Pros:** zero contention with the agent; one canonical login profile reused
across runs; simplest possible architecture for the operator.
**Cons:** no integration with the agent's tool ecosystem; user has to
remember to close the agent's browser session (or skip browser commands)
before running the script.

### Option D — Single Playwright source of truth, multiple MCP clients

Keep exactly one `@playwright/mcp` running. Have both the agent and any
codegen task attach to it as MCP clients rather than spawning their own.
One MCP server → one Edge process → one profile-lock holder, ever. The
contention class disappears.

**Why it can't work today.** The agent's MCP servers run over stdio
(`mcp_manager.py:_run_stdio` opens a stdin/stdout pipe pair per spawned
server). Stdio is 1:1 — only the parent process holding the pipes can
talk to that server. A codegen task subprocess has no access to those
pipes, so its only option today is to bootstrap a fresh MCP server.

**Concrete change points to make it work:**

1. **Switch `@playwright/mcp` (and any other server you want to share)
   from stdio to HTTP/SSE transport.** The MCP spec supports both;
   `@playwright/mcp` exposes HTTP via a `--port <N>` flag. `config-base.json`
   gets a transport: `"http"` field for that server entry, plus a port.
2. **Teach `mcp_manager.py` to connect over HTTP** for servers configured
   that way. The Python `mcp` library has `streamablehttp_client` /
   SSE client helpers — small additional code path alongside the existing
   stdio one. The `_run_stdio` private becomes one of two transport
   strategies, picked by config.
3. **Pass the URL down to codegen subprocesses.** Easiest: in
   `codegen/main.py:run_task`, when spawning the child, inject env vars
   like `MICRO_X_PLAYWRIGHT_MCP_URL=http://localhost:8081` (and the same
   for any other shared server) into the `subprocess.run(..., env=...)`
   call.
4. **Teach `tools/template-ts/src/index.ts:connectUpstream` to prefer HTTP
   when the env var is set.** Pseudocode: for each server in `SERVERS`,
   look up `MICRO_X_<NAME>_MCP_URL`; if set, attach via HTTP client; if
   not, fall back to spawning the configured `command` over stdio. Tasks
   stay portable (still work standalone) but slot into the shared
   architecture when launched under the agent.

**What stays stdio:** servers without contention problems (gmail,
linkedin, web, github, …) can keep their existing stdio bootstrap. This
change only needs to apply where shared state matters. Playwright is
the obvious case; others may appear later (database connections,
long-running model servers, anything stateful).

**Concurrency caveat:** `@playwright/mcp` must tolerate two MCP clients
hitting it at once. Playwright SDK supports multiple `BrowserContext`
per browser, so each client should get its own context to avoid them
stepping on each other's pages. Worth verifying before committing —
if `@playwright/mcp` naively shares the active page across all clients,
the codegen task could clobber what the agent is doing mid-flow.

**Pros:** the persistent profile is always owned by exactly one Edge
process; tasks and agent share the same logged-in session; no per-task
profile sprawl; same pattern reusable for any future stateful MCP
server.
**Cons:** real work in three places (`mcp_manager.py`,
`codegen/main.py`, `template-ts/src/index.ts`); deployment now
involves picking and managing ports for the HTTP-transport servers;
context-isolation needs verifying server-side.

## Recommendation

**Option C for the immediate apply-loop use case** — write the JobServe
applier as a standalone TS script with Playwright SDK directly, not a codegen
task. This sidesteps the contention entirely.

**Option D as the longer-term architectural fix** if browser-driving codegen
tasks become a recurring pattern. It's the only option that gives a clean
"agent and tasks share one logged-in browser" experience.

**Option A as a short-term guard rail** regardless: update the codegen
system prompt and add a check in `copy_template` / `_update_manifest` that
warns or rejects when a generated task lists `playwright` in `SERVERS`,
until D is implemented. This stops the next person from rediscovering the
same trap.

## Acceptance criteria

When this issue is resolved:

- The codegen system prompt (`mcp_servers/python/codegen/main.py:build_system_prompt`)
  documents whether codegen tasks may use `playwright`, and if so, with what
  profile-management contract.
- Either `_update_manifest` or `copy_template` rejects (or loudly warns) on
  a task that lists `playwright` in `SERVERS` when the contract isn't met.
- `documentation/docs/operations/` has a short section on running browser-driving
  scripts vs the agent (when each owns the profile).
- `config-base.json` for `@playwright/mcp` is the single canonical source of the
  profile location; tasks that legitimately need their own profile use a clearly
  separate dir under `C:\Users\steph\.playwright-profiles\<task>\`.

## Related

- `config-base.json:290-298` — Playwright MCP server config with persistent
  `--user-data-dir`.
- `mcp_servers/python/codegen/main.py` — codegen system prompt advertises
  available MCP servers; this is where Option A's guard rail would live.
- `tools/template-ts/src/index.ts` — `connectUpstream()` spawns each MCP
  server in `SERVERS:` from scratch; this is where Option D's "attach to
  inherited" logic would go.
- `tools/jobserve_apply/` — concrete reproduction of the issue; the task
  generates and tests pass, but `run_task` hangs on the profile lock when the
  agent's Playwright is also running. May be left in place as evidence or
  removed once Option C ships a working alternative.
- See the *Background* section above for the full `--user-data-dir` /
  `SingletonLock` mechanism. Not Playwright's design — Chromium's.
