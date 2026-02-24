# Multi-Agent Routing

OpenClaw can host multiple fully isolated agents in a single Gateway process, each with its own workspace, auth, sessions, and persona.

## What is "one agent"?

An agent is a fully scoped brain with its own:
- **Workspace** (files, AGENTS.md/SOUL.md/USER.md, memory, persona rules)
- **State directory** (`agentDir`) for auth profiles, model registry, per-agent config
- **Session store** under `~/.openclaw/agents/<agentId>/sessions`
- **Auth profiles** per-agent in `~/.openclaw/agents/<agentId>/agent/auth-profiles.json`
- **Skills** via workspace `skills/` folder (shared skills from `~/.openclaw/skills`)

## Routing rules (bindings)

Bindings are deterministic, most-specific wins:

1. `peer` match (exact DM/group/channel ID)
2. `parentPeer` match (thread inheritance)
3. `guildId + roles` (Discord role routing)
4. `guildId` (Discord)
5. `teamId` (Slack)
6. `accountId` match for a channel
7. Channel-level match (`accountId: "*"`)
8. Default agent (first in list or `default: true`)

If a binding sets multiple match fields, all must match (AND semantics).

## Use cases

### Multiple people on one server
Each person gets an isolated agent with separate workspace, auth, and sessions. One WhatsApp number can route different DMs to different agents via peer bindings.

### Different models per channel
Route WhatsApp to a fast Sonnet agent and Telegram to an Opus deep-work agent:
```json5
{
  agents: { list: [
    { id: "chat", model: "anthropic/claude-sonnet-4-5" },
    { id: "opus", model: "anthropic/claude-opus-4-6" }
  ]},
  bindings: [
    { agentId: "chat", match: { channel: "whatsapp" } },
    { agentId: "opus", match: { channel: "telegram" } }
  ]
}
```

### Per-agent sandbox and tools
Each agent can have its own sandbox mode and tool restrictions:
```json5
{
  agents: { list: [
    { id: "personal", sandbox: { mode: "off" } },
    { id: "family", sandbox: { mode: "all", scope: "agent" },
      tools: { allow: ["read"], deny: ["exec", "write", "edit"] } }
  ]}
}
```

### Agent-to-agent messaging
Off by default; must be explicitly enabled and allowlisted:
```json5
{ tools: { agentToAgent: { enabled: false, allow: ["home", "work"] } } }
```

## Key references

- Multi-agent routing: [`docs/concepts/multi-agent.md`](/root/openclaw/docs/concepts/multi-agent.md)
- Channel routing: [`docs/channels/channel-routing.md`](/root/openclaw/docs/channels/channel-routing.md)
- Multi-agent sandbox & tools: [`docs/tools/multi-agent-sandbox-tools.md`](/root/openclaw/docs/tools/multi-agent-sandbox-tools.md)
