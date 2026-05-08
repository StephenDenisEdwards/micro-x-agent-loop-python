# Codegen tool types — keeping wrappers in sync with MCP schemas

The codegen MCP server feeds the contents of `tools/template-ts/src/tools.ts` (plus `tool-types.ts`) into its LLM's system prompt as the catalogue of upstream MCP wrappers the generated task code can call. If a wrapper's TypeScript signature drifts from the upstream MCP server's actual `inputSchema`, the LLM generates code with invalid argument shapes — invalid enum values, missing fields, wrong types — and the generated tool fails or silently misbehaves at runtime.

To prevent that, `tool-types.ts` is **auto-generated** from each upstream MCP server's live `tools/list` response. Hand-written wrappers in `tools.ts` consume those types so a wrapper can't accidentally widen `dateSincePosted: "past month" | "past week" | "24hr"` back to `string`.

## Workflow (existing first-party server)

```bash
# 1. Build the upstream MCP server you've changed
cd mcp_servers/ts/packages/linkedin && npm run build

# 2. Regenerate the types in template-ts
cd tools/template-ts && npm run regen-tool-types

# 3. Fix any TypeScript errors in tools.ts the new types surface
npm run typecheck

# 4. Commit both src/tool-types.ts and any tools.ts changes together
```

For npx-fetched servers (e.g. `@playwright/mcp`), step 1 is skipped —
the regen script invokes `npx` directly per the config entry. See
"Adding a new upstream MCP server" below for both config shapes.

`npm run build` in `tools/template-ts` runs `check-tool-types` followed by `typecheck`. CI / pre-merge will fail if `tool-types.ts` has drifted from the upstream MCP schemas — the message tells the developer to run `regen-tool-types`.

## Adding a new upstream MCP server

The config supports two shapes of server entry depending on where the
package lives.

### Shape A — first-party server (built locally)

For servers in `mcp_servers/ts/packages/<pkg>/`:

```json
{
  "name": "<server-name>",
  "entry": "../../mcp_servers/ts/packages/<pkg>/dist/index.js",
  "env": { "...": "dummy values for any auth env vars the server gates registration on" },
  "tools": ["tool_one", "tool_two"]
}
```

The script will spawn `node <entry>` and talk to it over stdio.

### Shape B — third-party / npx-fetched server

For servers fetched at runtime (e.g. `@playwright/mcp`):

```json
{
  "name": "<server-name>",
  "command": "npx.cmd",
  "args": [
    "-y", "@some-org/some-mcp@latest",
    "--flag-1", "value-1"
  ],
  "tools": ["tool_one", "tool_two"]
}
```

The script will spawn `<command> <args...>` and talk to it over stdio.
On Windows, `.cmd` / `.bat` commands automatically use `shell: true`.
Use only flags that put the server in **stdio** mode (no `--port`); the
introspection step uses stdio regardless of how the agent later runs the
server.

### Worked example — `@playwright/mcp`

Both shapes coexist in `tool-types.config.json`. Playwright shows the
npx pattern end-to-end:

```json
{
  "name": "playwright",
  "command": "npx.cmd",
  "args": [
    "-y", "@playwright/mcp@latest",
    "--browser", "msedge",
    "--isolated",
    "--headless"
  ],
  "tools": [
    "browser_navigate", "browser_snapshot",
    "browser_click", "browser_type", "browser_select_option",
    "browser_file_upload", "browser_press_key", "browser_evaluate",
    "browser_close", "browser_wait_for"
  ]
}
```

`--isolated --headless` keep the browser ephemeral and invisible during
the introspection-only spawn — the regen script never actually drives a
page. (At runtime the agent uses different flags; see ISSUE-006 and
PLAN-shared-mcp-http-transport.)

### Steps regardless of shape

1. Add the entry above to `tools/template-ts/scripts/tool-types.config.json`.
2. Build the upstream package if first-party (`npm run build` in its
   directory). Skip if npx-fetched.
3. Run `npm run regen-tool-types` in `tools/template-ts/`. The script
   spawns the server, calls `tools/list`, and writes typed `XxxArgs` /
   `XxxResult` definitions into `src/tool-types.ts`.
4. Add hand-written wrappers in `tools.ts` for each tool (see "Wrapper
   convention" below). The wrappers MUST consume the generated types
   for the codegen LLM to get type-safe interfaces.
5. `npm run typecheck` in `tools/template-ts/`. Must be clean.

## Wrapper convention — why hand-written wrappers matter

Generating types is only half the value. The codegen LLM doesn't have to
*use* the types — it can write `clients.foo.callTool("bar", { ... })`
with arbitrary fields and the call still typechecks because the
underlying signature is `Record<string, unknown>`. Wrappers in
`tools.ts` close that loophole by exposing typed entry points the LLM
is told to prefer.

Example wrapper following the established pattern (required positional,
optional bundled in `options?`):

```ts
import type { BrowserClickArgs } from "./tool-types.js";

export async function browserClick(
  clients: Clients,
  target: BrowserClickArgs["target"],            // required, typed
  options?: Omit<BrowserClickArgs, "target">,    // optional fields, typed
): Promise<unknown> {
  const args: BrowserClickArgs = { target, ...(options ?? {}) };
  return get(clients, "playwright").callTool("browser_click", args);
}
```

If the codegen LLM later writes `browserClick(clients, "e3", { wrong: 1 })`,
TypeScript catches it. If the LLM bypasses the wrapper, the typed args
in `tool-types.ts` still serve as documentation in the prompt context.

### Wrapper conventions, briefly

- camelCase the function name (`browserClick`, not `browser_click`).
- First parameter is always `clients: Clients`.
- Required fields → positional parameters, typed via `XxxArgs["field"]`
  so they stay synced with regen.
- Optional fields → `options?: Omit<XxxArgs, "required-1" | ...>`.
- Build the args object explicitly and call `get(clients, "<server>").callTool(...)`.
- Return `Promise<unknown>` for tools whose result is unstructured
  (most browser tools, file IO); return parsed/shaped types when the
  upstream returns predictable JSON (gmail, calendar, etc.).

## Common pitfalls

### Hallucinated parameter names — the `target` vs `ref` story

`@playwright/mcp`'s `browser_snapshot` returns text containing element
markers like `[ref=e3]`. The codegen LLM, when generating raw
`callTool` calls without a typed wrapper to enforce shape, is prone to
re-using `ref` as the *parameter* name when the actual schema requires
`target`. The result: every browser action silently fails with a
`messages: missing required parameter "target"` API error.

The fix is the loop the rest of this guide describes: introspected
types in `tool-types.ts` plus hand-written wrappers in `tools.ts`. The
guarantee comes from BOTH, not just types.

### Forgetting to update `tools.ts` after regen

`regen-tool-types` only touches `src/tool-types.ts`. If you add a
server to the config but no wrappers in `tools.ts`, the LLM has types
but no idiomatic interface, and `npm run typecheck` won't catch
anything because there are no consumers. The codegen system prompt
inlines both files; missing wrappers means the LLM falls back to raw
`callTool` and the loophole reopens.

### Server requires real auth even for `tools/list`

Some servers refuse to start without working credentials. Two options:

- Set dummy `env` values; if the server does its registration before
  hitting any auth-gated endpoint, this works.
- If not: maintain a mock `dist/index.js` that returns the same
  `tools/list` shape but skips real registration. Document in a comment.

## Why an env block in the config?

Some MCP servers register a subset of their tools conditionally on env vars (e.g. LinkedIn only registers `linkedin_draft_post` / `linkedin_draft_article` / `linkedin_publish_draft` when `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` are set). The generator needs to see *all* tools, not just unauthenticated ones, so the config lets you supply dummy values for the gating env vars. **The dummy values never make it into a real auth flow** — the script only calls `tools/list`, which returns schemas, then exits.

## Audit status

| Server | Spawn shape | Wrappers in `tools.ts` use generated types? | Drift-checked? | Enum / param bugs caught |
|---|---|---|---|---|
| google (gmail/calendar/contacts) | local `entry` | ✅ | ✅ | (no upstream enums) |
| linkedin | local `entry` | ✅ | ✅ | `dateSincePosted`, `jobType`, `experienceLevel`, `sortBy`, `remoteFilter` (latter was missing entirely from wrapper) |
| web | local `entry` | ✅ | ✅ | (no upstream enums) |
| filesystem | local `entry` | ✅ | ✅ | (no upstream enums; uses generated `BashResult` / `ReadFileResult`) |
| github | local `entry` | ✅ | ✅ | `state`, `type`, `sort` were typed as `string` in wrappers |
| anthropic-admin | local `entry` | ✅ | ✅ | `action`, `bucketWidth` were typed as `string` |
| interview-assist | local `entry` | ✅ | ✅ | `optimize`, `source` were typed as `string` |
| playwright | npx `command` | ✅ | ✅ | `target` (was misnamed `ref` in raw codegen output before wrappers landed); `values: Array<string>` (was singular `value: string`) |

All upstream MCP servers wrapped in `tools.ts` are now migrated and protected by the build-time drift check. Adding a new MCP server (or new tool to an existing server) requires updating `scripts/tool-types.config.json` and re-running `npm run regen-tool-types` — the build will block PRs that forget.
