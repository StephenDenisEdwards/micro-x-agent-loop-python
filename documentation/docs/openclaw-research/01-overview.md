# OpenClaw Overview

## What it is

OpenClaw is a personal AI assistant you run on your own devices. It answers on the channels you already use (WhatsApp, Telegram, Slack, Discord, Google Chat, Signal, iMessage, Microsoft Teams, WebChat) plus extension channels (BlueBubbles, Matrix, Zalo, IRC, Nostr, and more). It can speak and listen on macOS/iOS/Android and render a live Canvas.

The Gateway is the control plane — a single long-lived daemon that owns all messaging surfaces and exposes a typed WebSocket API.

## Technology stack

- **Language**: TypeScript (ESM, strict mode)
- **Runtime**: Node >= 22
- **Schema**: TypeBox for protocol definitions (TypeScript types -> JSON Schema -> Swift models)
- **Package manager**: pnpm (bun optional for running TS directly)
- **Monorepo**: ~40+ packages/extensions
- **Testing**: Vitest
- **Linting**: oxlint, markdownlint

## Documentation

The project has extensive user/operator-facing documentation (100+ markdown files):

- `docs/concepts/` — architecture, agent loop, sessions, models, TypeBox, compaction
- `docs/cli/` — every CLI command
- `docs/channels/` — setup guides per messaging channel
- `docs/automation/` — cron, webhooks, polling, Gmail pub/sub
- `docs/install/` — installation and updating
- `docs/gateway/` — protocol, security
- `docs/tools/` — tool documentation
- `docs/experiments/` — proposals and plans
- i18n — Japanese and Chinese translations

No formal ADRs (architecture decision records) or internal engineering design docs exist.

## Key references

- Project README: `/root/openclaw/README.md`
- Gateway architecture: [`docs/concepts/architecture.md`](/root/openclaw/docs/concepts/architecture.md)
- Platform docs: [`docs/platforms/index.md`](/root/openclaw/docs/platforms/index.md)
- TypeBox schemas: [`docs/concepts/typebox.md`](/root/openclaw/docs/concepts/typebox.md)
