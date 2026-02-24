# Channel System

OpenClaw supports 20+ messaging channels through a unified plugin architecture. Each channel is a plugin implementing the `ChannelPlugin` interface.

## Supported channels

### Built-in / first-party
- **WhatsApp** — Baileys (web-based); QR pairing; most popular
- **Telegram** — Bot API via grammY; groups, forums, topics
- **Discord** — Bot API + Gateway; servers, channels, DMs, threads
- **Slack** — Bolt SDK; Socket Mode or HTTP Events API
- **Signal** — signal-cli integration; privacy-focused
- **iMessage (BlueBubbles)** — macOS server REST API (recommended)
- **iMessage (legacy)** — deprecated macOS via imsg CLI
- **Google Chat** — HTTP webhook
- **Microsoft Teams** — Bot Framework (plugin)
- **WebChat** — Gateway WebSocket UI

### Extension channels
- **IRC**, **Matrix**, **Mattermost**, **Feishu/Lark**, **LINE**, **Nextcloud Talk**, **Nostr**, **Tlon**, **Twitch**, **Zalo**, **Zalo Personal**

## ChannelPlugin interface

Every channel implements this contract:

```typescript
type ChannelPlugin<ResolvedAccount, Probe, Audit> = {
  id: ChannelId;
  meta: ChannelMeta;                        // Display name, order, docs path, aliases
  capabilities: ChannelCapabilities;        // Chat types, polls, reactions, media, threads
  defaults?: { queue?: { debounceMs? } };

  // Required adapters
  config: ChannelConfigAdapter;             // listAccountIds(), resolveAccount()
  outbound?: ChannelOutboundAdapter;        // sendText(), sendMedia(), deliveryMode

  // Optional adapters
  onboarding?: ChannelOnboardingAdapter;    // CLI wizard hooks
  setup?: ChannelSetupAdapter;              // Login/setup flows
  pairing?: ChannelPairingAdapter;          // DM pairing notifications
  security?: ChannelSecurityAdapter;        // DM policy, allowlists
  groups?: ChannelGroupAdapter;             // Group behavior
  mentions?: ChannelMentionAdapter;         // Mention stripping/handling
  status?: ChannelStatusAdapter;            // Health diagnostics
  gateway?: ChannelGatewayAdapter;          // Main channel logic (start/stop)
  auth?: ChannelAuthAdapter;                // Authentication
  commands?: ChannelCommandAdapter;         // Command handling
  streaming?: ChannelStreamingAdapter;      // Block streaming config
  threading?: ChannelThreadingAdapter;      // Thread/topic handling
  messaging?: ChannelMessagingAdapter;      // Message wrappers
  agentPrompt?: ChannelAgentPromptAdapter;  // Prompt customization per channel
  directory?: ChannelDirectoryAdapter;      // Contact/group directory
  resolver?: ChannelResolverAdapter;        // Target resolution
  actions?: ChannelMessageActionAdapter;    // Reactions, edits, deletes
  heartbeat?: ChannelHeartbeatAdapter;      // Periodic channel checks
  agentTools?: ChannelAgentToolFactory;     // Channel-owned agent tools
};
```

### Capabilities

Channels declare what they support:
```typescript
capabilities: {
  chatTypes: ["direct", "group", "channel", "thread"],
  polls: true,
  reactions: true,
  media: true,
  threads: true,
  nativeCommands: true,
  blockStreaming: true
}
```

### Text chunk limits (per channel)

| Channel | Limit |
|---------|-------|
| Telegram | 4000 chars |
| WhatsApp | 4000 chars |
| Slack | 4000 chars |
| Signal | 4000 chars |
| Discord | 2000 chars |
| IRC | 350 chars |

## Message flow

```
Inbound message
  -> Channel adapter receives
  -> Routing/bindings -> resolve agent + session key
  -> Dedupe cache (prevent duplicate delivery after reconnects)
  -> Debouncing (batch rapid text messages; media flushes immediately)
  -> Queue (if a run is active for this session)
  -> Agent run (streaming + tools)
  -> Reply shaping (NO_REPLY filtering, duplicate removal)
  -> Outbound (channel-specific chunking + formatting)
```

## Routing and session keys

Routing determines which agent processes a message. Resolution order:

1. Exact peer match (bindings with `peer.kind` + `peer.id`)
2. Parent peer match (thread inheritance)
3. Guild + roles match (Discord)
4. Guild match (Discord)
5. Team match (Slack)
6. Account match (`accountId`)
7. Channel match (any account on channel)
8. Default agent

### Session key shapes

- **DMs**: `agent:<agentId>:main` (or per-peer/per-channel-peer variants)
- **Groups**: `agent:<agentId>:<channel>:group:<id>`
- **Channels/rooms**: `agent:<agentId>:<channel>:channel:<id>`
- **Threads**: `agent:<agentId>:<channel>:channel:<id>:thread:<threadId>`
- **Telegram topics**: `agent:<agentId>:telegram:group:<id>:topic:<topicId>`

## Queueing modes

When a run is active, inbound messages can be handled in different modes:

| Mode | Behavior |
|------|----------|
| `steer` | Inject into current run; cancels pending tool calls after next boundary |
| `followup` | Enqueue for next agent turn after current run ends |
| `collect` | Coalesce all queued messages into single followup (default) |
| `steer-backlog` | Steer now AND preserve for followup |
| `interrupt` | Abort active run, run newest message (legacy) |

Configuration:
```json5
{
  messages: {
    queue: {
      mode: "collect",
      debounceMs: 1000,
      cap: 20,
      drop: "summarize",
      byChannel: { discord: "collect" }
    }
  }
}
```

Per-session override: `/queue <mode>`

## Debouncing

Rapid messages from the same sender are batched:
- `messages.inbound.debounceMs` (global)
- `messages.inbound.byChannel.<channel>` (per-channel override)
- Text-only; media/attachments flush immediately

## Pairing

### DM pairing
Unknown senders receive an 8-character uppercase code, expires in 1 hour. Pending requests capped at 3 per channel. Stored in `~/.openclaw/credentials/<channel>-pairing.json`.

### Node pairing
iOS/Android devices connect to Gateway as "nodes" and require approval.

## Group message behavior

### Activation modes
- **`mention`** (default): requires @-mention (real mentions or regex patterns)
- **`always`**: wake on every message; agent uses `NO_REPLY` token for silence when not adding value

### Group context
Pending messages (not yet in session) injected as:
```
[Chat messages since your last reply - for context]
...group messages with [from: Sender Name] prefixes...
[Current message - respond to this]
<triggering message>
```

### Group policy
- `open`: any sender can trigger
- `allowlist`: only senders in `groupAllowFrom`
- `disabled`: groups ignored

## Broadcast groups (experimental, WhatsApp only)

Multiple agents process the same group message simultaneously:
```json5
{
  broadcast: {
    strategy: "parallel",
    "120363403215116621@g.us": ["alfred", "baerbel"]
  }
}
```

Each agent has separate session keys, isolated history, different workspace/sandbox, different tools, but shared group context buffer.

## Typing indicators

Modes control when typing starts:

| Mode | When |
|------|------|
| `never` | No indicator |
| `instant` | As soon as model loop begins |
| `thinking` | On first reasoning delta |
| `message` | On first non-silent text delta |

## Channel docking

`src/channels/dock.ts` provides lightweight metadata for shared code paths. Built-in channels have hardcoded docks; plugin channels create docks dynamically via `buildDockFromPlugin()`.

## Plugin registration pattern

```typescript
// extensions/discord/index.ts
const plugin = {
  id: "discord",
  name: "Discord",
  configSchema: emptyPluginConfigSchema(),
  register(api: OpenClawPluginApi) {
    setDiscordRuntime(api.runtime);
    api.registerChannel({ plugin: discordPlugin });
  },
};
export default plugin;
```

## Key references

- Channel overview: [`docs/channels/index.md`](/root/openclaw/docs/channels/index.md)
- Channel routing: [`docs/channels/channel-routing.md`](/root/openclaw/docs/channels/channel-routing.md)
- Messages: [`docs/concepts/messages.md`](/root/openclaw/docs/concepts/messages.md)
- Pairing: [`docs/channels/pairing.md`](/root/openclaw/docs/channels/pairing.md)
- Group messages: [`docs/channels/group-messages.md`](/root/openclaw/docs/channels/group-messages.md)
- Broadcast groups: [`docs/channels/broadcast-groups.md`](/root/openclaw/docs/channels/broadcast-groups.md)
- Queue: [`docs/concepts/queue.md`](/root/openclaw/docs/concepts/queue.md)
- Typing indicators: [`docs/concepts/typing-indicators.md`](/root/openclaw/docs/concepts/typing-indicators.md)
- ChannelPlugin type: [`src/channels/plugins/types.plugin.ts`](/root/openclaw/src/channels/plugins/types.plugin.ts)
- Channel dock: [`src/channels/dock.ts`](/root/openclaw/src/channels/dock.ts)
- Discord implementation: [`extensions/discord/src/channel.ts`](/root/openclaw/extensions/discord/src/channel.ts)
- Telegram implementation: [`extensions/telegram/src/channel.ts`](/root/openclaw/extensions/telegram/src/channel.ts)
- WhatsApp plugin: [`extensions/whatsapp/index.ts`](/root/openclaw/extensions/whatsapp/index.ts)
- Slack plugin: [`extensions/slack/index.ts`](/root/openclaw/extensions/slack/index.ts)
- Signal plugin: [`extensions/signal/index.ts`](/root/openclaw/extensions/signal/index.ts)
