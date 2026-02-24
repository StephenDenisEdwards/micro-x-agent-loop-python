# OpenClaw Architecture Research

Research notes from an exploration of the [OpenClaw](https://github.com/openclaw/openclaw) codebase — a personal AI assistant you run on your own devices.

These documents cover the major subsystems of OpenClaw as reference material for designing and comparing agent loop architectures.

## Documents

| Document | Summary |
|----------|---------|
| [01-overview.md](01-overview.md) | Project overview and technology stack |
| [02-automation.md](02-automation.md) | Heartbeat, cron, hooks, webhooks, and Lobster workflows |
| [03-lobster-workflows.md](03-lobster-workflows.md) | Deterministic workflow runtime with approval gates |
| [04-agent-loop.md](04-agent-loop.md) | Agent loop lifecycle, streams, queueing, and hook points |
| [05-sessions-and-memory.md](05-sessions-and-memory.md) | Session management, memory files, and vector search |
| [06-storage.md](06-storage.md) | File system layout, persistence, and state management |
| [07-plugin-system.md](07-plugin-system.md) | Plugin architecture, registration API, slots, and distribution |
| [08-channel-system.md](08-channel-system.md) | Messaging channel architecture, routing, queueing, and adapters |

## Source Codebase

All references point to paths within the OpenClaw monorepo at `/root/openclaw`.

- **Runtime**: Node >= 22, TypeScript (ESM, strict mode)
- **Docs site**: [docs.openclaw.ai](https://docs.openclaw.ai)
- **Repo**: [github.com/openclaw/openclaw](https://github.com/openclaw/openclaw)
