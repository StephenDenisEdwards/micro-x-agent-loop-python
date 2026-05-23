# Plan: Multi-Tool Codegen Task Apps

**Status: Completed**

## Problem

The TypeScript codegen template (`codegen-templates/template-ts/`) is hardcoded to expose exactly one MCP tool per task app. The sealed `src/index.ts` imports the singletons `TOOL_NAME`, `TOOL_DESCRIPTION`, `TOOL_INPUT_SCHEMA`, `handleTool` from `task.ts` and registers one `server.tool(...)`.

Some task apps naturally group related tools — e.g. an email processor that wants both `process_alerts` and `draft_reply`, sharing the Gmail MCP connection and the same profile. Today the only options are:

1. **Split into sibling task apps.** Two directories, two subprocesses, two `connectUpstream` calls. Wasteful when the tools share state or upstream connections.
2. **Multiplex inside `handleTool`** via an `action` discriminator. One MCP tool from the outside, branching internally. Worse LLM discoverability — the agent sees one tool with a busier schema.

Both options compromise. The MCP protocol itself supports many tools per server; the template just doesn't expose that capability.

## Proposed Solution

Extend the template so a `task.ts` can export a `TOOLS: ToolDef[]` array instead of (or in addition to) the legacy single-tool quadruple. The sealed `src/index.ts` introspects what `task.ts` exports and adapts: legacy shape gets synthesized into a one-element `TOOLS` array, native multi-tool shape is used directly.

Existing task apps need **zero edits**.

## Locked-in Design Decisions

| # | Decision | Choice | Notes |
|---|---|---|---|
| 1 | Back-compat strategy | Support both shapes via adapter | Existing apps unchanged; ~15-line adapter in `index.ts` |
| 2 | MCP server name | Optional `SERVER_NAME` export, dir-basename fallback | Legacy apps stay byte-equivalent (dir name = tool name today) |
| 3 | Per-tool upstream `servers` | Single top-level `SERVERS` only | Symmetry with legacy shape; per-tool `servers?` rejected as over-engineering |
| 4 | `--run` with no `--tool` | Require `--tool <name>` for multi-tool; default to the only tool for single-tool | Preserves existing `npx tsx --run` invocations from `mcp_servers/python/codegen/main.py` |
| 5 | Name collision in `TOOLS` | Throw at import time | Empty/duplicate names always indicate a bug |
| 6 | Placeholder `task.ts` | Keep legacy single-tool shape, add docstring linking the `TOOLS` option | Common case stays simple |
| 7 | `tools/manifest.json` schema | Soft shim — always write `tools: [...]`, keep singular `tool_name`/`description`/`input_schema` populated when only one tool | Single-tool readers keep working; multi-tool readers branch on array length |

## Proposed Contract

### New shared type — `tools/_runtime/src/tool-def.ts` (new file)

```ts
import type { z } from "zod";
import type { Clients } from "...";  // import note in actual file

export interface ToolDef<I extends z.ZodRawShape = z.ZodRawShape> {
  name: string;                  // snake_case MCP tool name
  description: string;
  inputSchema: I;                // Zod raw shape, same format as legacy TOOL_INPUT_SCHEMA
  handler: (
    input: z.infer<z.ZodObject<I>>,
    clients: Clients,
    profile: Record<string, unknown>,
    config: Record<string, unknown>,
  ) => Promise<Record<string, unknown>>;
}

export function defineTools<T extends ToolDef[]>(tools: T): T {
  return tools;  // identity helper for tuple-preserving type inference
}
```

`Clients` is per-task (lives in each app's `src/tools.ts`). The runtime type lives in `_runtime` and is generic over the input shape.

### Multi-tool `task.ts` shape

```ts
import { z } from "zod";
import { defineTools, type ToolDef } from "../../_runtime/src/tool-def.js";
import type { Clients } from "./tools.js";

export const SERVERS = ["google"];
export const SERVER_NAME = "my_app";  // optional; defaults to directory basename

export const TOOLS = defineTools([
  {
    name: "process_alerts",
    description: "Process pending job alerts.",
    inputSchema: { dryRun: z.boolean().default(false).describe("Don't write files") },
    handler: async (input, clients, profile, config) => { ... },
  },
  {
    name: "draft_reply",
    description: "Draft a reply to a specific job.",
    inputSchema: { jobId: z.string().describe("Job ID from process_alerts") },
    handler: async (input, clients, profile, config) => { ... },
  },
]);
```

### Legacy single-tool `task.ts` shape (unchanged, still supported)

```ts
export const SERVERS = ["google"];
export const TOOL_NAME = "my_tool";
export const TOOL_DESCRIPTION = "...";
export const TOOL_INPUT_SCHEMA = { ... };
export async function handleTool(input, clients, profile, config) { ... }
```

### `--describe` output shape

Always emits the new shape; the singular fields are only present when there's one tool (soft back-compat shim):

```json
{
  "server_name": "my_app",
  "tools": [
    { "tool_name": "process_alerts", "description": "...", "input_schema": { ... } },
    { "tool_name": "draft_reply", "description": "...", "input_schema": { ... } }
  ],
  "tool_name": "my_tool",
  "description": "...",
  "input_schema": { ... }
}
```

The last three fields appear only when `tools.length === 1`. Unupdated readers (today's `_update_manifest`) work unchanged for single-tool apps.

### `tools/manifest.json` per-task entry

```json
{
  "my_task": {
    "tool_name": "my_task",
    "description": "...",
    "input_schema": { ... },
    "tools": [
      { "tool_name": "my_task", "description": "...", "input_schema": { ... } }
    ],
    "created": "2026-05-23",
    "server": { ... }
  }
}
```

`tools: [...]` is always present; the singular fields stay populated when `tools.length === 1`.

## Files Changed

| File | Change |
|---|---|
| `tools/_runtime/src/tool-def.ts` | **NEW** — `ToolDef` interface and `defineTools()` helper |
| `codegen-templates/template-ts/src/index.ts` | Adapter, loop registration, `--tool <name>` parsing, new describe shape |
| `codegen-templates/template-ts/src/task.ts` | Add docstring introducing `TOOLS`; export shape unchanged |
| `codegen-templates/template-ts/src/index.test.ts` | New unit tests for the normalization adapter |
| `mcp_servers/python/codegen/main.py` | `_update_manifest` writes `tools[]`; `list_tasks` enumerates per tool; `run_task` accepts optional `tool` arg; `build_system_prompt` teaches multi-tool option |
| `tools/jobserve_email_processor/src/index.ts` | Re-sync from template (DO NOT EDIT file) |
| `tools/jobserve_rss_processor/src/index.ts` | Re-sync from template (DO NOT EDIT file) |
| `documentation/docs/planning/INDEX.md` | Add entry for this plan |

**Not changed:** `scripts/regen-tool-types.mjs` — it generates types for upstream MCP servers, not the task's own tools. Confirmed by reading the script.

## Open Risks / Notes

1. **Tool-name namespacing across apps.** Multi-tool apps don't change how the agent loads tools — each registered MCP tool is still distinct from the agent's perspective. But the LLM codegen prompt should warn against generic names (`fetch`, `parse`) that would collide with upstream MCP tools.
2. **`McpServer.tool()` type inference under a loop.** Registering N tools via a loop means TypeScript can't infer per-tool param types at each call site. Using `defineTools()` with the tuple-preserving helper preserves it where possible; a `ToolDef<any>` cast in the registration loop is acceptable since Zod still validates at runtime.
3. **Manifest readers.** Three Python readers touch `tools/manifest.json` (two in `commands/command_handler.py`, one in `mcp_servers/python/codegen/main.py::list_tasks`). The soft shim means only `list_tasks` needs updating for multi-tool enumeration; the others continue to see the singular fields for single-tool apps.

## Status

- [x] Plan doc + INDEX.md
- [x] `tools/_runtime/src/tool-def.ts`
- [x] `codegen-templates/template-ts/src/index.ts` (extracted helpers into `config.ts` and `tool-loader.ts` so the template's own test suite runs for the first time — previously broken because `index.test.ts` triggered loading the runtime via `../../_runtime/` paths that only resolve in synced apps)
- [x] `codegen-templates/template-ts/src/task.ts` docstring
- [x] `codegen-templates/template-ts/src/index.test.ts` (7 passing — 1 pre-existing + 6 new for `normalizeTools`)
- [x] `mcp_servers/python/codegen/main.py` (manifest writer, `list_tasks` per-tool enumeration, `run_task --tool` passthrough, system prompt multi-tool section)
- [x] Re-sync existing apps' `index.ts` + new `config.ts` + `tool-loader.ts`
- [x] Final verification: both apps typecheck clean, all tests pass (13 + 24), `--describe` output preserves singular fields for single-tool apps

## Implementation Notes

- `ToolDef.inputSchema` is typed as `unknown` rather than `z.ZodRawShape` because zod 3.25's new `$ZodType` preview types don't unify with the MCP SDK's `ZodRawShape` signature. The template casts at the SDK boundary (`as z.ZodRawShape` in two places in `index.ts`). Runtime accepts both shapes; the cast is invisible to authors.
- `loadJsonConfig` was extracted from `index.ts` into `config.ts` as a side benefit — the existing template-level test for it was actually broken (transitively imported runtime paths), and lifting it out fixed that.
- All `*.ts` files in the template are now mirrored into `tools/<task_name>/src/` byte-identically: `index.ts`, `config.ts`, `tool-loader.ts`, `tool-types.ts` (and the per-task `tools.ts`, which is generated separately).
