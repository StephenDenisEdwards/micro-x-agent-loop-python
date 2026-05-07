# Codegen tool types — keeping wrappers in sync with MCP schemas

The codegen MCP server feeds the contents of `tools/template-ts/src/tools.ts` (plus `tool-types.ts`) into its LLM's system prompt as the catalogue of upstream MCP wrappers the generated task code can call. If a wrapper's TypeScript signature drifts from the upstream MCP server's actual `inputSchema`, the LLM generates code with invalid argument shapes — invalid enum values, missing fields, wrong types — and the generated tool fails or silently misbehaves at runtime.

To prevent that, `tool-types.ts` is **auto-generated** from each upstream MCP server's live `tools/list` response. Hand-written wrappers in `tools.ts` consume those types so a wrapper can't accidentally widen `dateSincePosted: "past month" | "past week" | "24hr"` back to `string`.

## Workflow

```bash
# 1. Build the upstream MCP server you've changed
cd mcp_servers/ts/packages/linkedin && npm run build

# 2. Regenerate the types in template-ts
cd tools/template-ts && npm run regen-tool-types

# 3. Fix any TypeScript errors in tools.ts the new types surface
npm run typecheck

# 4. Commit both src/tool-types.ts and any tools.ts changes together
```

`npm run build` in `tools/template-ts` runs `check-tool-types` followed by `typecheck`. CI / pre-merge will fail if `tool-types.ts` has drifted from the upstream MCP schemas — the message tells the developer to run `regen-tool-types`.

## Adding a new upstream MCP server

1. Wrap its tools in `tools/template-ts/src/tools.ts` (hand-written — composites, defaults, result-parsing).
2. Add the server entry to `tools/template-ts/scripts/tool-types.config.json`:
   ```json
   {
     "name": "<server-name>",
     "entry": "../../mcp_servers/ts/packages/<pkg>/dist/index.js",
     "env": { "...": "dummy values for any auth env vars the server gates registration on" },
     "tools": ["tool_one", "tool_two"]
   }
   ```
3. Build the upstream package (`dist/index.js` must exist).
4. Run `npm run regen-tool-types`.
5. Update wrappers in `tools.ts` to use `<Tool>Args` / `<Tool>Result` from `./tool-types.js`.
6. `npm run typecheck`.

## Why an env block in the config?

Some MCP servers register a subset of their tools conditionally on env vars (e.g. LinkedIn only registers `linkedin_draft_post` / `linkedin_draft_article` / `linkedin_publish_draft` when `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` are set). The generator needs to see *all* tools, not just unauthenticated ones, so the config lets you supply dummy values for the gating env vars. **The dummy values never make it into a real auth flow** — the script only calls `tools/list`, which returns schemas, then exits.

## Audit status

| Server | Wrappers in `tools.ts` use generated types? | Drift-checked? | Enum bugs caught |
|---|---|---|---|
| google (gmail/calendar/contacts) | ✅ | ✅ | (no upstream enums) |
| linkedin | ✅ | ✅ | `dateSincePosted`, `jobType`, `experienceLevel`, `sortBy`, `remoteFilter` (latter was missing entirely from wrapper) |
| web | ✅ | ✅ | (no upstream enums) |
| filesystem | ✅ | ✅ | (no upstream enums; uses generated `BashResult` / `ReadFileResult`) |
| github | ✅ | ✅ | `state`, `type`, `sort` were typed as `string` in wrappers |
| anthropic-admin | ✅ | ✅ | `action`, `bucketWidth` were typed as `string` |
| interview-assist | ✅ | ✅ | `optimize`, `source` were typed as `string` |

All upstream MCP servers wrapped in `tools.ts` are now migrated and protected by the build-time drift check. Adding a new MCP server (or new tool to an existing server) requires updating `scripts/tool-types.config.json` and re-running `npm run regen-tool-types` — the build will block PRs that forget.

> **Note:** the filesystem section in `tools.ts` does not currently wrap the new `grep` and `glob` tools. They were added to the filesystem MCP server but task code that needs search functionality should add wrappers for them — the generated types are not yet in the config.
