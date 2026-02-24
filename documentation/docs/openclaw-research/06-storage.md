# Storage

Everything lives under `~/.openclaw` by default (overridable via `OPENCLAW_STATE_DIR`).

## Directory layout

```
~/.openclaw/
├── openclaw.json                          # System config (JSON5)
├── credentials/
│   ├── oauth.json                         # OAuth provider tokens
│   ├── whatsapp/<accountId>/
│   │   ├── creds.json                     # Baileys session
│   │   └── creds.json.bak                 # Backup
│   └── <channel>-pairing.json             # Pending pairing requests
├── agents/<agentId>/
│   ├── sessions/
│   │   ├── sessions.json                  # Session store index (key -> metadata)
│   │   └── <sessionId>.jsonl              # Full transcript per session
│   ├── agent/
│   │   ├── models.json                    # Custom model catalog
│   │   └── auth-profiles.json             # Per-agent OAuth profiles
│   └── qmd/                               # QMD search sidecar state (if enabled)
├── workspace/                             # Agent workspace (default path)
│   ├── AGENTS.md                          # Operating instructions
│   ├── SOUL.md                            # Persona/tone
│   ├── USER.md                            # User profile
│   ├── IDENTITY.md                        # Agent name/emoji
│   ├── TOOLS.md                           # Tool conventions
│   ├── HEARTBEAT.md                       # Heartbeat checklist
│   ├── BOOT.md                            # Gateway startup script
│   ├── BOOTSTRAP.md                       # One-time first-run ritual
│   ├── MEMORY.md                          # Curated long-term memory
│   ├── memory/YYYY-MM-DD.md              # Daily memory logs
│   ├── skills/                            # Workspace-specific skills
│   ├── hooks/                             # Workspace-specific hooks
│   └── canvas/                            # Canvas UI files
├── skills/                                # Managed/shared skills
├── hooks/                                 # Managed hooks
│   └── transforms/                        # Webhook transform modules
├── memory/<agentId>.sqlite                # Vector search index
├── logs/
│   └── commands.log                       # Command audit log (JSONL)
├── sandboxes/                             # Isolated sandbox workspaces
├── dns/                                   # DNS-SD zone files
└── settings/                              # UI preferences
```

## What stores what

| Data | Location | Format | Agent-writable |
|------|----------|--------|----------------|
| Configuration | `~/.openclaw/openclaw.json` | JSON5 | Via `/config` if enabled |
| Session index | `agents/<id>/sessions/sessions.json` | JSON | No (gateway owns) |
| Session transcripts | `agents/<id>/sessions/*.jsonl` | JSONL | No (append-only) |
| Workspace memory | `workspace/memory/*.md` | Markdown | Yes |
| Workspace instructions | `workspace/*.md` | Markdown | Manual or agent write |
| OAuth/credentials | `credentials/` | JSON | No |
| WhatsApp auth | `credentials/whatsapp/` | JSON | No (Baileys manages) |
| Auth profiles | `agents/<id>/agent/auth-profiles.json` | JSON | No (onboarding) |
| Managed skills | `skills/` | Various | No (installer) |
| Vector index | `memory/<agentId>.sqlite` | SQLite | No (auto-maintained) |
| Canvas files | `workspace/canvas/` | HTML/CSS/JS | Yes |

## Design principles

- **Gateway is source of truth** — UIs query the gateway, never read files directly
- **Transcripts are append-only** — JSONL only appended to (compaction summaries inserted inline)
- **Session pruning is in-memory only** — trimming tool results doesn't touch disk
- **Memory is plain Markdown** — the vector index is derived; Markdown files are the source of truth
- **Credentials are isolated** — separate from workspace, never committed

## Environment variables

```
OPENCLAW_STATE_DIR=~/.openclaw          # All mutable data
OPENCLAW_CONFIG_PATH=~/.openclaw/openclaw.json
OPENCLAW_HOME=~
OPENCLAW_AGENT_DIR=~/.openclaw/agents/main/agent
OPENCLAW_OAUTH_DIR=~/.openclaw/credentials
OPENCLAW_PROFILE=dev                    # Creates ~/.openclaw-dev, workspace-dev
```

## Multi-instance

```bash
OPENCLAW_STATE_DIR=~/.openclaw-work openclaw gateway --port 19001
# or
openclaw gateway --profile work   # uses ~/.openclaw-work
```

## Backup

Recommended: put the workspace in a private git repo. Never commit credentials, session transcripts, or API keys.

## Key references

- Agent workspace: [`docs/concepts/agent-workspace.md`](/root/openclaw/docs/concepts/agent-workspace.md)
- Agent runtime: [`docs/concepts/agent.md`](/root/openclaw/docs/concepts/agent.md)
- Session management: [`docs/concepts/session.md`](/root/openclaw/docs/concepts/session.md)
- Gateway configuration: [`docs/gateway/configuration.md`](/root/openclaw/docs/gateway/configuration.md)
- Config paths source: [`src/config/paths.ts`](/root/openclaw/src/config/paths.ts)
- Session paths source: [`src/config/sessions/paths.ts`](/root/openclaw/src/config/sessions/paths.ts)
