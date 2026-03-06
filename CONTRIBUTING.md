# Contributing to micro-x-agent-loop-python

## Prerequisites

- Python 3.11+
- Node.js 18+ (for MCP servers)
- An Anthropic or OpenAI API key

## Setup

```bash
git clone https://github.com/StephenDenisEdwards/micro-x-agent-loop-python.git
cd micro-x-agent-loop-python
cp .env.example .env   # Add your API keys
pip install -e ".[dev]"
```

## Quality Gates

All changes must pass these checks before committing:

```bash
# Lint (must pass with zero errors)
ruff check src/ tests/

# Type check
mypy src/

# Tests
python -m pytest tests/ -v
```

A `pre-commit` configuration is available. Install hooks with:

```bash
pre-commit install
```

## Code Style

- **Line length:** 120 characters
- **Linting:** Ruff with rules E, F, W, I, B, UP
- **Type hints:** Required on all public functions
- **Imports:** Use `from __future__ import annotations` in every module
- **Naming:** snake_case for functions/variables, PascalCase for classes
- **Docstrings:** Required for public classes and non-trivial functions

## Commit Messages

Use conventional prefix style:

| Prefix | Use For |
|--------|---------|
| `feat:` | New features or capabilities |
| `fix:` | Bug fixes |
| `docs:` | Documentation changes only |
| `refactor:` | Code restructuring without behaviour change |
| `chore:` | Build, tooling, dependency updates |
| `test:` | Adding or updating tests |

Examples:
```
feat: add LinkedIn publishing tools (draft-post, draft-article, publish-draft)
fix: isolate MCP cleanup signal in run.bat and add MCP server logging
docs: update SAD to v3.0 and add architecture diagrams to README
refactor: extract constants, CommandHandler, config inheritance
```

## Branching

- `master` is the main branch
- Create feature branches for non-trivial changes
- Keep commits focused — one logical change per commit

## Project Structure

```
src/micro_x_agent_loop/     # Python agent runtime
  agent.py                  # Main orchestrator
  turn_engine.py            # Single-turn LLM + tool execution
  mode_selector.py          # Prompt/compiled mode classification
  provider.py               # LLM provider factory
  providers/                # Anthropic + OpenAI implementations
  memory/                   # SQLite session persistence
  mcp/                      # MCP server lifecycle
  commands/                 # Slash command routing

mcp_servers/ts/             # TypeScript MCP server configs
documentation/docs/         # Full project documentation
tests/                      # Unit and integration tests
```

## Adding New Features

### Adding a New MCP Server

See [Adding an MCP Server](documentation/docs/guides/adding-an-mcp-server.md) for a step-by-step guide.

Key points:
- MCP servers are **TypeScript** projects in separate repos
- They are registered in `config.json` under `McpServers`
- The agent discovers tools automatically via the MCP protocol
- Do NOT create Python tool files — all tools go through MCP

### Adding a Slash Command

1. Add the handler method to `commands/command_handler.py`
2. Register it in `commands/router.py`
3. Add help text in the `/help` handler
4. Add tests in `tests/`

### Modifying the Agent Loop

See [Extending the Agent Loop](documentation/docs/guides/extending-the-agent-loop.md) for the event callback system.

Key points:
- `Agent` orchestrates via callbacks defined in `turn_events.py`
- `TurnEngine` handles the LLM call → tool execution cycle
- Add new callbacks to `TurnEvents` protocol, implement in `Agent`

## Architecture Decisions

Significant design choices are recorded as ADRs in `documentation/docs/architecture/decisions/`. Before proposing a change that affects architecture, check existing ADRs and create a new one if needed.

## Documentation

- Update relevant docs when changing behaviour
- Design docs live in `documentation/docs/design/`
- Per-tool docs live in `documentation/docs/design/tools/`
- Planning docs track feature work in `documentation/docs/planning/`
- Keep `CLAUDE.md` up to date when adding key files or changing conventions
