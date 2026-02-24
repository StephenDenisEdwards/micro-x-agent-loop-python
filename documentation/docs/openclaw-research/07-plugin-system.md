# Plugin System

Plugins are TypeScript modules that run in-process with the gateway. Loaded at runtime via `jiti` and treated as trusted code.

## What a plugin can register

| Method | Purpose |
|--------|---------|
| `registerTool()` | Agent tools (JSON-schema functions the model calls) |
| `registerHook()` | Internal event-driven automation |
| `registerCommand()` | Auto-reply commands (bypass LLM) |
| `registerChannel()` | Messaging channels |
| `registerProvider()` | Model provider auth flows |
| `registerGatewayMethod()` | WebSocket RPC methods |
| `registerCli()` | CLI commands |
| `registerService()` | Background services |
| `registerHttpHandler()` / `registerHttpRoute()` | HTTP endpoints |
| `on()` | Typed lifecycle hooks |

## Plugin structure

```
extensions/my-plugin/
├── openclaw.plugin.json      # Manifest (required)
├── index.ts                  # Entry point
├── package.json              # Optional
├── src/                      # Implementation
└── skills/                   # Optional bundled skills
```

### Manifest (`openclaw.plugin.json`)

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "description": "...",
  "kind": "memory",
  "channels": ["mychannel"],
  "providers": ["myauth"],
  "skills": ["./skills/my-skill"],
  "configSchema": { "type": "object", "properties": {} }
}
```

### Entry point

```typescript
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

export default function register(api: OpenClawPluginApi) {
  api.registerTool({ name: "my_tool", ... });
  api.on("before_agent_start", async (event) => { ... });
}
```

## Discovery and loading order

Plugins discovered from four locations (first match wins on ID conflict):

1. **Config paths** — `plugins.load.paths`
2. **Workspace extensions** — `<workspace>/.openclaw/extensions/`
3. **Global extensions** — `~/.openclaw/extensions/`
4. **Bundled extensions** — shipped with OpenClaw

Loading pipeline: discover -> read manifests -> validate config schemas -> resolve enable state -> load modules via `jiti` -> call `register()` -> collect registrations.

## Configuration

```json5
{
  plugins: {
    enabled: true,
    allow: ["voice-call"],
    deny: ["untrusted"],
    load: { paths: ["./my-plugin"] },
    slots: { memory: "memory-core" },
    entries: {
      "voice-call": {
        enabled: true,
        config: { provider: "twilio" }
      }
    }
  }
}
```

## Plugin slots (exclusive categories)

Only one plugin of a given `kind` can be active. Currently:
- **`memory`** — default `memory-core`, alternative `memory-lancedb`, or `"none"` to disable

## Tools

Two categories:
- **Required** — always available when plugin is enabled
- **Optional** — needs `tools.alsoAllow: ["my_tool"]`

Tools can be static objects or factories receiving context (config, workspaceDir, agentId, sessionKey, channel). Return `null` to conditionally skip (e.g. in sandbox).

## Plugin hooks

**Agent**: `before_agent_start`, `llm_input`, `llm_output`, `agent_end`, `before_compaction`, `after_compaction`, `before_reset`

**Message**: `message_received`, `message_sending` (can modify/cancel), `message_sent`

**Tool**: `before_tool_call` (can block), `after_tool_call`, `tool_result_persist` (synchronous)

**Session**: `session_start`, `session_end`

**Gateway**: `gateway_start`, `gateway_stop`

Void hooks run in parallel. Modifying hooks run sequentially with merged results.

## Commands (auto-reply, no LLM)

```typescript
api.registerCommand({
  name: "mystatus",
  handler: async (ctx) => ({ text: "Status: OK" })
});
```

Plugin commands run before built-in commands, which run before the AI agent. Cannot override reserved names.

## Channel plugins

Register a full messaging channel with adapters for config resolution, capabilities, outbound delivery, onboarding, health diagnostics, threading, streaming, mentions.

## Provider plugins

Register model provider auth flows (OAuth, API key, device code, custom). Return credential profiles for model API calls.

## Plugin runtime (`api.runtime`)

Core helpers: config load/write, system events, media operations, TTS, memory tools, channel helpers, logging, state directory.

## Distribution

Published as npm packages:
```json
{
  "name": "@openclaw/my-pack",
  "openclaw": { "extensions": ["./src/safety.ts", "./src/tools.ts"] }
}
```

Install via `openclaw plugins install <spec>`. Dependencies installed with `--ignore-scripts`.

## Key references

- Plugin documentation: [`docs/tools/plugin.md`](/root/openclaw/docs/tools/plugin.md)
- Plugin manifest spec: [`docs/plugins/manifest.md`](/root/openclaw/docs/plugins/manifest.md)
- Agent tools authoring: [`docs/plugins/agent-tools.md`](/root/openclaw/docs/plugins/agent-tools.md)
- Plugin types: [`src/plugins/types.ts`](/root/openclaw/src/plugins/types.ts)
- Plugin loader: [`src/plugins/loader.ts`](/root/openclaw/src/plugins/loader.ts)
- Plugin discovery: [`src/plugins/discovery.ts`](/root/openclaw/src/plugins/discovery.ts)
- Plugin registry: [`src/plugins/registry.ts`](/root/openclaw/src/plugins/registry.ts)
- Plugin hooks runner: [`src/plugins/hooks.ts`](/root/openclaw/src/plugins/hooks.ts)
- Plugin SDK exports: [`src/plugin-sdk/index.ts`](/root/openclaw/src/plugin-sdk/index.ts)
