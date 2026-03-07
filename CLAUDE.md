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
                                   Provider        Tool dispatch
                                 (Anthropic/       (MCP servers)
                                   OpenAI)

Trigger Broker (always-on daemon):
  broker/service.py → scheduler.py ──→ dispatcher.py → runner.py (subprocess: --run)
                    → webhook_server.py ↗        ↓
                                        response_router.py → channels.py (adapters)
                    broker/store.py (SQLite: broker_jobs, broker_runs, broker_questions)
```

### Key Files

| File | Purpose |
|------|---------|
| `__main__.py` | Entry point, REPL, CLI args (`--run`, `--broker`, `--job`), startup |
| `agent.py` | Orchestrator: message history, mode analysis, memory, metrics |
| `turn_engine.py` | Single turn: LLM call → tool execution → response |
| `mode_selector.py` | Stage 1 pattern matching + Stage 2 LLM classification |
| `provider.py` | Factory for LLM providers |
| `providers/anthropic_provider.py` | Anthropic streaming + prompt caching |
| `providers/openai_provider.py` | OpenAI streaming |
| `app_config.py` | Config loading, base inheritance, env var expansion |
| `agent_config.py` | Runtime config dataclass (48 fields) |
| `bootstrap.py` | Wires up memory, MCP servers, event sinks |
| `compaction.py` | Conversation compaction strategies (none/summarize) |
| `tool.py` | Tool protocol (name, description, execute, is_mutating) |
| `ask_user.py` | Human-in-the-loop questioning via questionary |
| `tool_search.py` | On-demand tool discovery for large tool sets |
| `system_prompt.py` | LLM system prompt and directives (`_ASK_USER_DIRECTIVE`, etc.) |
| `metrics.py` | Metric builders, `SessionAccumulator`, cost tracking |
| `memory/` | SQLite session persistence, checkpoints, events, pruning |
| `mcp/` | MCP server lifecycle, tool proxying |
| `commands/` | Slash command routing (/session, /voice, /cost, etc.) |
| `services/` | Session controller, checkpoint service |
| `broker/` | Trigger broker: cron scheduler, webhook server, HITL, retries, channel adapters, CLI |

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
- Profiles: `config-standard.json`, `config-standard-no-summarization.json`, `config-baseline.json`

### Memory System

- Opt-in via `MemoryEnabled=true`
- SQLite at `.micro_x/memory.db`
- 6 tables: sessions, messages, tool_calls, checkpoints, checkpoint_files, events
- Broker DB at `.micro_x/broker.db` — 3 tables: broker_jobs, broker_runs, broker_questions
- Checkpoint rewind restores files to pre-mutation state
- Pruning: time-based, per-session message cap, global session cap

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
