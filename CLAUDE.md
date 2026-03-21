# CLAUDE.md — Project Context for AI Assistants

## Project

**micro-x-agent-loop-python** — A general-purpose, cost-aware AI agent with multi-provider LLM support, MCP tool orchestration, and session persistence.

## Language & Layout

- **Python 3.11+**, src layout: `src/micro_x_agent_loop/`
- **TypeScript** MCP servers: `mcp_servers/ts/` (separate repos, not Python)
- Package manager: `pip` or `uv`
- Config: `config.json` (supports `Base` inheritance, `ConfigFile` indirection, `${ENV}` expansion)
- Secrets: `.env` file (never commit)

## Key Commands

```bash
# Run the agent (interactive REPL)
./run.sh                          # macOS/Linux
run.bat                           # Windows
python -m micro_x_agent_loop      # Direct

# One-shot autonomous execution
python -m micro_x_agent_loop --run "prompt text" [--session <id>] [--config path]

# Trigger broker (scheduled/cron jobs)
python -m micro_x_agent_loop --broker start    # Start daemon
python -m micro_x_agent_loop --broker stop     # Stop daemon
python -m micro_x_agent_loop --broker status   # Show status
python -m micro_x_agent_loop --job add <name> <cron_expr> <prompt> [--tz TZ] [--hitl] [--max-retries N]
python -m micro_x_agent_loop --job list
python -m micro_x_agent_loop --job run-now <id>
python -m micro_x_agent_loop --job runs [id]

# API server (HTTP/WebSocket for web, desktop, mobile clients)
python -m micro_x_agent_loop --server start              # Start server
python -m micro_x_agent_loop --server start --broker     # Start server with broker
python -m micro_x_agent_loop --server http://host:port   # Connect CLI to server

# Tests
python -m pytest tests/ -v

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

## Architecture Overview

```
__main__.py → app_config → bootstrap_runtime → Agent → REPL loop
                                                  ↓
                                            TurnEngine
                                          ↙         ↘
                                   Provider        Tool dispatch     SubAgentRunner
                                 (Anthropic/       (MCP servers)     (spawn_subagent
                                   OpenAI)                            pseudo-tool)

Trigger Broker (always-on daemon):
  broker/service.py → scheduler.py ──→ dispatcher.py → runner.py (subprocess: --run)
                    → webhook_server.py ↗        ↓
                                        response_router.py → channels.py (adapters)
                    broker/store.py (SQLite: broker_jobs, broker_runs, broker_questions)

API Server (--server start):
  server/app.py (FastAPI + lifespan) → AgentManager → Agent per session
       ├── REST: /api/chat, /api/sessions, /api/health
       └── WS:   /api/ws/{session_id} → WebSocketChannel → Agent
```

### Key Files

| File | Purpose |
|------|---------|
| `__main__.py` | Entry point, REPL, CLI args (`--run`, `--broker`, `--job`, `--server`), startup |
| `agent.py` | Orchestrator: message history, mode analysis, memory, metrics |
| `turn_engine.py` | Single turn: LLM call → tool execution → response |
| `mode_selector.py` | Stage 1 pattern matching + Stage 2 LLM classification |
| `provider.py` | Factory for LLM providers |
| `providers/anthropic_provider.py` | Anthropic streaming + prompt caching |
| `providers/openai_provider.py` | OpenAI streaming |
| `providers/ollama_provider.py` | Ollama local LLM (OpenAI-compatible) |
| `app_config.py` | Config loading, base inheritance, env var expansion |
| `agent_config.py` | Runtime config dataclass (48 fields) |
| `bootstrap.py` | Wires up memory, MCP servers, event sinks |
| `compaction.py` | Conversation compaction strategies (none/summarize) |
| `agent_channel.py` | AgentChannel protocol + implementations (Terminal, Buffered, Broker channels) |
| `tool.py` | Tool protocol (name, description, execute, is_mutating) |
| `tool_search.py` | On-demand tool discovery for large tool sets |
| `sub_agent.py` | SubAgentRunner, agent types (explore/summarize/general), spawn_subagent pseudo-tool |
| `system_prompt.py` | LLM system prompt and directives (`_ASK_USER_DIRECTIVE`, `_SUBAGENT_DIRECTIVE`, etc.) |
| `metrics.py` | Metric builders, `SessionAccumulator`, cost tracking |
| `memory/` | SQLite session persistence, checkpoints, events, pruning |
| `mcp/` | MCP server lifecycle, tool proxying |
| `commands/` | Slash command routing (/session, /voice, /cost, etc.) |
| `services/` | Session controller, checkpoint service |
| `broker/` | Trigger broker: cron scheduler, webhook server, HITL, retries, channel adapters, CLI |
| `server/app.py` | FastAPI API server with REST + WebSocket endpoints |
| `server/agent_manager.py` | Per-session Agent lifecycle (create, cache, evict) |
| `server/ws_channel.py` | WebSocketChannel: AgentChannel for real-time streaming |
| `server/broker_routes.py` | Broker endpoints (jobs, runs, HITL, webhooks) as APIRouter |
| `server/client.py` | WebSocket CLI client for `--server http://...` mode |

## Conventions

### Commit Messages

Use prefix style: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`

### Code Style

- **Ruff** for linting (rules: E, F, W, I, B, UP), 120-char line length
- **MyPy** for type checking
- Type hints on all public functions
- `from __future__ import annotations` in every module

### Testing

- Tests in `tests/` using `unittest` (run via `pytest`)
- Test fakes in `tests/fakes.py`: `FakeStreamProvider`, `FakeTool` for mocking the LLM and tools
- Name test files `test_<module>.py`

### Tools

- All tools are **TypeScript MCP servers** in separate repos — do NOT create Python tools
- The only Python "tools" are pseudo-tools: `ask_user`, `tool_search`
- Tool results are unstructured text (see ADR-014 / ISSUE-001)

### Mode Analysis

When a user submits a prompt:
1. **Stage 1** — pattern matching detects batch/scoring/stats/structured-output signals
2. **Stage 2** (if ambiguous) — LLM classifies as PROMPT or COMPILED
3. **User prompt** — if signals detected, user chooses the execution mode interactively
4. Currently diagnostic only — compiled mode execution path not yet implemented

### Config System

- `config.json` at project root, or `--config path` CLI arg
- Supports `Base` key for inheritance (variant overrides base)
- Supports `ConfigFile` key for indirection (pointer to actual config)
- `${ENV_VAR}` expanded recursively in all string values
- `#KeyName` self-references resolve to another key in the same config (e.g. `"SubAgentModel": "#Model"`)
- `Pricing` key: per-model token pricing (input/output/cache_read/cache_create per MTok USD) — no hardcoded defaults
- All configuration elements must be in `config-base.json` — no hardcoded fallback defaults in code
- Profiles: `config-standard.json`, `config-standard-no-summarization.json`, `config-baseline.json`

### Memory System

- Opt-in via `MemoryEnabled=true`
- SQLite at `.micro_x/memory.db`
- 6 tables: sessions, messages, tool_calls, checkpoints, checkpoint_files, events
- Broker DB at `.micro_x/broker.db` — 3 tables: broker_jobs, broker_runs, broker_questions
- Checkpoint rewind restores files to pre-mutation state
- Pruning: time-based, per-session message cap, global session cap

### Planning Index Hygiene

After completing any feature work or committing changes:
- Update the corresponding `PLAN-*.md` status field to match reality
- Ensure `INDEX.md` status, counts, and notes are consistent with plan files
- If a plan moves to Completed, add it to the "Completed priorities" collapsible section

## What NOT to Do

- Do not create new Python tool files — tools are TypeScript MCP servers
- Do not modify `.env` or commit secrets
- Do not add dependencies without checking `pyproject.toml` first
- Do not use `git add -A` — stage specific files only
- Do not skip pre-commit hooks (`--no-verify`)

## Documentation

Full docs in `documentation/docs/`:
- `architecture/` — SAD v3.0 + 18 ADRs
- `design/` — 10 core design docs + 20 per-tool docs
- `operations/` — setup, config, sessions, troubleshooting
- `guides/` — developer how-tos (adding MCP servers, extending the loop)
- `planning/` — feature plans with status tracking
- `research/` — framework studies, sandboxing, cost analysis
