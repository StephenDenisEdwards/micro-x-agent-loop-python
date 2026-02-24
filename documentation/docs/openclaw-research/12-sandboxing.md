# Sandboxing

OpenClaw can run tools inside Docker containers to limit blast radius. Optional, controlled by config. The Gateway stays on the host; only tool execution is sandboxed.

## What gets sandboxed

- Tool execution: `exec`, `read`, `write`, `edit`, `apply_patch`, `process`
- Optional sandboxed browser

**Not sandboxed:**
- The Gateway process itself
- Elevated exec (explicitly runs on host, bypasses sandbox)

## Modes (`sandbox.mode`)

- `"off"` — no sandboxing
- `"non-main"` — sandbox only non-main sessions (groups, channels, cron, hooks)
- `"all"` — every session runs in a sandbox

## Scope (`sandbox.scope`)

- `"session"` (default) — one container per session
- `"agent"` — one container per agent
- `"shared"` — one container for all sandboxed sessions

## Workspace access (`sandbox.workspaceAccess`)

- `"none"` (default) — isolated workspace under `~/.openclaw/sandboxes`
- `"ro"` — agent workspace mounted read-only at `/agent`
- `"rw"` — agent workspace mounted read-write at `/workspace`

## Images and setup

Default image: `openclaw-sandbox:bookworm-slim` (built via `scripts/sandbox-setup.sh`).

Containers run with **no network** by default (override with `sandbox.docker.network`).

`setupCommand` runs once after container creation (inside container via `sh -lc`). Pitfalls:
- No egress by default, so package installs fail unless you enable network
- `readOnlyRoot: true` prevents writes
- Must be root for package installs

## Custom bind mounts

`sandbox.docker.binds` mounts host directories into the container (`host:container:mode`). Dangerous bind sources blocked (docker.sock, /etc, /proc, /sys, /dev).

## Multi-agent overrides

Each agent can override sandbox + tools independently via `agents.list[].sandbox` and `agents.list[].tools`.

## Sandbox browser

- Auto-starts when browser tool needs it
- Separate image: `openclaw-sandbox-browser`
- `sandbox.browser.allowHostControl` lets sandboxed sessions target host browser

## Key references

- Sandboxing: [`docs/gateway/sandboxing.md`](/root/openclaw/docs/gateway/sandboxing.md)
- Sandbox vs Tool Policy vs Elevated: [`docs/gateway/sandbox-vs-tool-policy-vs-elevated.md`](/root/openclaw/docs/gateway/sandbox-vs-tool-policy-vs-elevated.md)
- Multi-agent sandbox & tools: [`docs/tools/multi-agent-sandbox-tools.md`](/root/openclaw/docs/tools/multi-agent-sandbox-tools.md)
