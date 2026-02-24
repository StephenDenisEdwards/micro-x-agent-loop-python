# Automation

OpenClaw has five automation mechanisms.

## 1. Heartbeat — periodic awareness

- Runs in the **main session** on a configurable interval (default 30 min)
- The agent reads a `HEARTBEAT.md` checklist each cycle (e.g. check inbox, review calendar)
- If nothing needs attention, replies `HEARTBEAT_OK` — no message delivered
- Supports `activeHours` to avoid running overnight
- Cheap: one agent turn batches multiple checks

```json5
{
  agents: {
    defaults: {
      heartbeat: {
        every: "30m",
        target: "last",
        activeHours: { start: "08:00", end: "22:00" }
      }
    }
  }
}
```

## 2. Cron — precise scheduling

- 5-field cron expressions with timezone support, or one-shot `--at` for future timestamps
- **Main session**: injects a system event handled at next heartbeat
- **Isolated session**: clean slate, own history, can use different model/thinking level
- Managed via `openclaw cron add/list/status/runs`

```bash
openclaw cron add \
  --name "Morning briefing" \
  --cron "0 7 * * *" \
  --tz "America/New_York" \
  --session isolated \
  --message "Generate today's briefing" \
  --model opus --announce
```

## 3. Hooks — event-driven internal automation

- TypeScript handlers that fire on gateway events
- Events: `command:new`, `command:reset`, `command:stop`, `agent:bootstrap`, `gateway:startup`
- Auto-discovered from three directories (workspace -> managed -> bundled)
- Each hook: directory with `HOOK.md` (metadata) + `handler.ts`
- 4 bundled hooks:
  - **session-memory**: saves context on `/new`
  - **bootstrap-extra-files**: injects workspace files at bootstrap
  - **command-logger**: audit log in JSONL
  - **boot-md**: runs `BOOT.md` on gateway start
- Installable as npm hook packs

## 4. Webhooks — external HTTP triggers

- Gateway exposes `POST /hooks/wake` (enqueue system event) and `POST /hooks/agent` (isolated agent run)
- Token-authenticated, rate-limited on auth failures
- Custom mapped endpoints via `hooks.mappings` with template/transform support
- Built-in Gmail preset: Gmail Pub/Sub -> `gog gmail watch serve` -> `/hooks/gmail` -> agent processes email
- Supports routing to specific agents via `agentId`, model overrides, and delivery to any channel

## 5. Lobster — deterministic workflow runtime

- Multi-step tool pipelines with approval gates and resumable runs
- Triggered by cron/heartbeat or called directly
- Returns JSON envelopes; pauses at `needs_approval` checkpoints
- See [03-lobster-workflows.md](03-lobster-workflows.md) for details

## Decision guide

| Use Case | Recommended | Why |
|----------|-------------|-----|
| Check inbox every 30 min | Heartbeat | Batches with other checks |
| Send daily report at 9am | Cron (isolated) | Exact timing needed |
| Monitor calendar | Heartbeat | Natural periodic fit |
| Weekly deep analysis | Cron (isolated) | Standalone, different model |
| Remind me in 20 min | Cron (`--at`) | One-shot with precise timing |
| Event-driven side effect | Hook | Fires on agent lifecycle events |
| External system trigger | Webhook | HTTP ingress from other services |

## Key references

- Hooks: [`docs/automation/hooks.md`](/root/openclaw/docs/automation/hooks.md)
- Cron vs Heartbeat: [`docs/automation/cron-vs-heartbeat.md`](/root/openclaw/docs/automation/cron-vs-heartbeat.md)
- Webhooks: [`docs/automation/webhook.md`](/root/openclaw/docs/automation/webhook.md)
- Gmail Pub/Sub: [`docs/automation/gmail-pubsub.md`](/root/openclaw/docs/automation/gmail-pubsub.md)
- Auth monitoring: [`docs/automation/auth-monitoring.md`](/root/openclaw/docs/automation/auth-monitoring.md)
- Troubleshooting: [`docs/automation/troubleshooting.md`](/root/openclaw/docs/automation/troubleshooting.md)
- Polls: [`docs/automation/poll.md`](/root/openclaw/docs/automation/poll.md)
