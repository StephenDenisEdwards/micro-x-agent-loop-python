# OpenClaw Project Overview

## Executive Summary
OpenClaw is a TypeScript-based, multi-channel personal AI assistant platform centered on a local Gateway control plane. The project ships a CLI (`openclaw`), gateway runtime, channel integrations, plugin/extension architecture, mobile and desktop companion apps, and tooling for onboarding, configuration, diagnostics, and operations.

At a high level:
- CLI + Gateway are the operational core.
- Channel/message surfaces are pluggable and account-aware.
- Routing/session model supports multi-agent isolation by channel/account/peer.
- Plugins extend channels, tools, providers, gateway methods, hooks, and CLI.
- The repository also contains first-party app clients (macOS/iOS/Android), docs, and release/testing automation.

## Repository Structure
Top-level areas and their roles:
- `src/`: Main TypeScript codebase (CLI, gateway, channels, routing, media, plugins, memory, providers).
- `extensions/`: Workspace extension/plugin packages (channel plugins and other capabilities).
- `apps/`: Native apps (`android`, `ios`, `macos`) and shared app code.
- `docs/`: Mintlify documentation across user-facing and reference topics.
- `ui/`: Web UI assets/tooling for the control surface.
- `scripts/`: Build/test/release/dev automation scripts.
- `packages/`: Additional workspace packages.

Workspace configuration (`pnpm-workspace.yaml`) includes root package, `ui`, `packages/*`, and `extensions/*`.

## Core Runtime Architecture
### 1) CLI entry and command system
Primary entrypoint:
- `src/index.ts`

Behavior:
- Loads env/runtime guards, logging capture, and builds the Commander program.
- Exports reusable helpers (config/session/infra utilities).
- Installs global error handling and parses CLI args asynchronously.

CLI composition:
- `src/cli/program/build-program.ts` creates program + context.
- `src/cli/program/command-registry.ts` registers core commands lazily.
- `src/cli/program/register.subclis.ts` registers sub-CLIs lazily/eagerly.

Design characteristic:
- Lazy command registration minimizes startup overhead and avoids loading heavy modules unless required.

### 2) Gateway server
Gateway entrypoints:
- `src/gateway/server.ts`
- `src/gateway/server.impl.ts`

Responsibilities in `server.impl.ts` include:
- Config read/validation and legacy migration.
- Plugin auto-enable logic and plugin loading.
- Runtime config resolution (bind/auth/tailscale/control UI/OpenAI-compatible HTTP endpoints).
- Channel manager startup and lifecycle integration.
- Health, heartbeat, cron, reload handlers, node subscriptions, and WS handling.
- Optional sidecars (control UI assets, canvas host, discovery/tailscale features).

This makes the gateway the central control plane for events, sessions, channel runtime state, and agent interactions.

### 3) Protocol and RPC boundary
Gateway protocol surface:
- `src/gateway/protocol/index.ts`

Characteristics:
- Ajv-backed schema validation for request/response/event frames.
- Extensive typed methods for sessions, chat, agents, nodes, devices, models, skills, wizard, cron, approvals, etc.
- Versioned protocol framing (`PROTOCOL_VERSION` and schema exports).

### 4) Channel plugin runtime and lifecycle
Channel plugin registry:
- `src/channels/plugins/index.ts`

Lifecycle orchestration:
- `src/gateway/server-channels.ts`

Behavior:
- Enumerates channel plugins from active plugin registry.
- Starts/stops per-account channel runtimes.
- Tracks runtime status snapshots and errors.
- Applies config-aware enable/configured checks for each account.

Important architectural point:
- Channels are not hardcoded in one manager; they are plugin-registered and normalized via channel registry/order metadata.

## Gateway Runtime Model (Practical)
- The Gateway is a long-running process (control plane server), and the CLI often acts as a client to it for runtime operations.
- Not every CLI command requires a running Gateway (some are local/config/utility commands), but assistant runtime features depend on Gateway availability.
- Recommended production-style setup is running the Gateway as a background service/daemon so channels, sessions, and automations stay available.
- The Gateway does not have to run on the same machine as the CLI user; remote mode is supported.
- Cron and scheduled automations are executed by the Gateway process. If the Gateway is not running at schedule time, those tasks will not run on time.
## Plugins and Extensions
Plugin loader/runtime:
- `src/plugins/loader.ts`
- `src/plugins/runtime.ts`

Capabilities from loader behavior:
- Discovers plugins from workspace and configured paths.
- Validates manifest/config schemas.
- Supports enable/disable policy and slot decisions.
- Registers plugin-provided channels, tools, hooks, providers, gateway methods, commands, HTTP handlers, and services.
- Uses Jiti for TS/JS plugin loading with `openclaw/plugin-sdk` aliasing.

Extensions directory contains many first-party extension packages (31 `package.json` files detected), including channels like Teams, Matrix, Zalo, Slack, Telegram, Signal, WhatsApp, and others.

## Routing, Sessions, and Multi-Agent Model
Route resolution:
- `src/routing/resolve-route.ts`
- `src/routing/session-key.ts`
- `src/sessions/session-key-utils.ts`

Key behaviors:
- Session key construction is channel/account/peer aware.
- Supports DM scoping modes (`main`, `per-peer`, `per-channel-peer`, `per-account-channel-peer`).
- Uses binding rules for channel/account/peer/guild/team/roles.
- Handles thread/parent session relationships and special session classes (cron/acp/subagent).

Result:
- OpenClaw can isolate context by channel/account/user while still allowing policy-driven consolidation where needed.

## Memory and Data Handling
QMD-backed memory manager:
- `src/memory/qmd-manager.ts`

Observed behavior:
- Per-agent memory/index isolation via state directories.
- Session export pipeline and collections management.
- Periodic/boot update runs.
- Query and indexing logic with scoped filtering support.

This indicates memory is designed for agent-local scoping with background synchronization and explicit collection control.

## Platform Apps and Surfaces
Apps in repo:
- `apps/macos`
- `apps/ios`
- `apps/android`
- `apps/shared`

Gateway/web/client surfaces include:
- Control UI served by gateway.
- Node/device pairing and remote control workflows.
- Mobile node integration and gateway orchestration.

## Build, Tooling, and Test Posture
### Build and packaging
- Runtime baseline: Node >=22.12.0 (`package.json` engines).
- Main build script composes TS build + plugin SDK typings + asset generation steps.
- Bundling config in `tsdown.config.ts` defines multiple entry outputs (`src/index.ts`, `src/entry.ts`, plugin SDK entries, hooks, etc.).

### Quality gates
- Linting/formatting: Oxlint + Oxfmt.
- Type checking: `pnpm tsgo` / TypeScript configs.
- Tests: Vitest unit/e2e/live plus extension/gateway-specific configs.
- Coverage thresholds in `vitest.config.ts` (70% lines/functions/statements, 55% branches) with intentional excludes for heavy integration surfaces.

### Testing strategy docs
- `docs/help/testing.md` describes layered test strategy:
  - Unit/integration
  - E2E gateway smoke
  - Live provider/model checks
  - Docker-backed scenarios

## Scale Signals (Current Snapshot)
From local repository scan:
- TypeScript files under `src`: 3032
- Test files named `*.test.ts` under `src`: 1005
- Extension `package.json` files under `extensions`: 31

These numbers indicate a large, actively tested codebase with significant extension/plugin breadth.

## Operational Focus Areas
The project emphasizes:
- Reliable onboarding and configuration workflows (`onboard`, `configure`, `doctor`).
- Safe operation across real messaging surfaces (pairing, allowlists, policy controls).
- Observability and maintenance (health/status/logs/system/doctor).
- Backward compatibility and migration support in config/runtime paths.

## Risks and Complexity Hotspots
From structure and module density, likely high-complexity zones are:
- Gateway lifecycle orchestration (`server.impl.ts` breadth).
- Cross-channel routing and policy interactions.
- Plugin compatibility/schema/runtime failures at load-time.
- Live-provider variability and auth/profile failover behavior.
- Multi-surface testing consistency (core + extensions + native apps).

## Overall Assessment
OpenClaw is a mature, large-scale monorepo for a local-first AI assistant platform with:
- Strong modularization (CLI/gateway/plugins/channels/apps/docs).
- Heavy emphasis on extensibility and multi-channel interoperability.
- Deep operational tooling (diagnostics, onboarding, security posture controls).
- Extensive automated testing footprint with dedicated live/e2e workflows.

It is best understood as an extensible assistant platform and control plane, not only a messaging bot.

