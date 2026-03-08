# Planning: End-User Deployment & Installation

**Status:** Draft
**Date:** 2026-03-04
**Updated:** 2026-03-08
**Goal:** Enable a non-expert user to install, configure, and run micro-x-agent on their machine with minimal friction.

---

## 1. Current State Assessment

### What works today

The project has two entry scripts (`run.sh` for Unix, `run.bat` for Windows) that:
1. Create a Python virtual environment if missing
2. `pip install .` the Python package
3. Launch the REPL

`run.bat` also starts/stops the WhatsApp bridge process if present.

The project supports four execution modes:
- **REPL** — interactive terminal (`run.bat` / `run.sh`)
- **One-shot** — autonomous execution (`--run "prompt"`)
- **API Server** — HTTP/WebSocket for web, desktop, mobile clients (`--server start`)
- **Trigger Broker** — cron scheduler, webhooks, HITL (`--broker start` or `--server start --broker`)

There is a `config-base.json` with `${VAR}` environment variable placeholders and a `Base` inheritance system for config variants. Config profiles exist: `config-baseline.json`, `config-standard-sonnet.json`, `config-standard-cheap.json`, `config-standard-openai.json`, etc.

Everything has sensible defaults — an empty `{}` config.json works (no MCP servers, but the agent runs).

### What a user must currently do manually

| Step | Difficulty | Notes |
|------|-----------|-------|
| Install Python 3.11+ | Medium | Must be correct version, on PATH |
| Install Node.js 18+ | Medium | Required for all TypeScript MCP servers |
| Clone the repo | Easy | `git clone` |
| Create `.env` with API keys | Easy | Copy `.env.example`, fill in keys (14 possible keys) |
| Set environment variables for `config-base.json` paths | Hard | `MICRO_X_HOME`, `MICRO_X_WORKING_DIR`, `MICRO_X_LOG_DIR` — user must understand the config system |
| Run `npm install && npm run build` in `mcp_servers/ts/` | Medium | Must know about TypeScript build step |
| Choose or create a `config.json` | Hard | Must understand all options, MCP server paths, tool formatting, etc. |
| (Optional) Set up Google OAuth credentials | Hard | Requires Google Cloud Console project, OAuth consent screen, client ID/secret |
| (Optional) Install .NET SDK, clone mcp-servers repo, build | Hard | For system-info server |
| (Optional) Install Go + GCC, clone whatsapp-mcp, build bridge, scan QR | Very Hard | For WhatsApp tools |
| (Optional) Install `uv` | Easy | For codegen MCP server |
| (Optional) Install `mcp-discord` npm package globally | Medium | For Discord tools |
| Run `run.sh` or `run.bat` | Easy | |

**Key pain points:**
- No single command to go from zero to working
- TypeScript MCP servers require a separate build step that is never automated
- Config files use absolute paths that differ per machine and OS
- `config-base.json` uses Windows backslash paths — doesn't work on macOS/Linux
- No validation of prerequisites (Python version, Node.js presence, etc.)
- No guided setup for API keys
- Optional tools (WhatsApp, system-info, Discord) have deep dependency chains
- No way to discover what's misconfigured until startup errors appear
- Server/broker modes have additional env vars (`SERVER_HOST`, `SERVER_PORT`, `SERVER_API_SECRET`) that are undocumented for end users

---

## 2. Problem Decomposition

The deployment problem splits into five distinct layers:

### Layer 1: Prerequisites (runtime installation)
- Python 3.11+
- Node.js 18+
- (Optional) uv, .NET SDK, Go, GCC, ffmpeg

### Layer 2: Project setup (source code + dependencies)
- Clone the repo
- Python: `pip install .` (or `uv sync`)
- Node.js: `npm install && npm run build` in `mcp_servers/ts/`

### Layer 3: Secrets (API keys)
- At minimum, one LLM provider key (Anthropic or OpenAI)
- Optional keys: Brave Search, GitHub, Google (OAuth), Deepgram, Anthropic Admin, LinkedIn (OAuth), Discord, X/Twitter (OAuth), Dev.to

### Layer 4: Configuration (config.json)
- Machine-specific paths (working directory, log directory, MCP server paths)
- Feature selection (which MCP servers to enable, compaction, memory, etc.)
- Per-tool formatting rules
- Server/broker settings (host, port, API secret)

### Layer 5: Optional integrations (external tools)
- Google OAuth (requires browser-based consent flow)
- WhatsApp (requires Go bridge build + QR auth)
- System-info (requires .NET build)
- Discord (requires npm global install + bot token)
- Interview-assist (requires clone of external repo + Deepgram key)

---

## 3. Proposed Solutions

### 3.1 — Interactive Setup Wizard (`setup.py`)

A guided, interactive setup that handles Layers 2-4 automatically. This is the highest-impact single deliverable.

**What it does:**
1. **Checks prerequisites** — verifies Python version, Node.js presence, reports what's missing with install instructions per OS
2. **Installs Python dependencies** — creates venv, runs `pip install .`
3. **Builds TypeScript MCP servers** — runs `npm install && npm run build` in `mcp_servers/ts/`
4. **Collects API keys interactively** — prompts for each key with explanation of what it enables; writes `.env`
5. **Generates `config.json`** — auto-detects paths, asks which MCP servers to enable, writes a working config
6. **Validates the result** — attempts to start each enabled MCP server briefly to verify connectivity

**Config generation logic:**
- Auto-detect project root from the script's own location
- Ask user for their preferred working directory (default: `~/Documents`)
- Ask user for log directory (default: `<project_root>/logs`)
- Use forward slashes universally (works on all OSes in Node.js and Python)
- Only include MCP server entries for servers whose prerequisites are met
- Generate ToolFormatting entries for enabled servers only

**Implementation approach:**

```
python setup.py

=== micro-x-agent Setup ===

Checking prerequisites...
  [OK] Python 3.13.1
  [OK] Node.js v20.11.0
  [--] .NET SDK (not found — system-info tools will be unavailable)
  [--] Go (not found — WhatsApp tools will be unavailable)
  [OK] uv 0.5.4

Installing Python dependencies...
  [OK] Virtual environment created
  [OK] Dependencies installed

Building MCP servers...
  [OK] npm install completed
  [OK] npm run build completed

=== API Keys ===
Each key unlocks a set of tools. Press Enter to skip optional keys.

Anthropic API key (required for default provider):
  > sk-ant-...
  [OK] Key validated

Brave Search API key (enables web_search tool):
  > [Enter to skip]
  [SKIPPED] web_search will not be available

GitHub token (enables PR/issue/repo/discussions tools):
  > ghp_...
  [OK]

...

=== Configuration ===

Working directory (where file tools operate):
  > ~/Documents
  [OK] /home/user/Documents

Which configuration profile?
  [1] Standard (recommended) — memory, compaction, cost optimisation
  [2] Minimal — no memory, no compaction, lowest complexity
  [3] Custom — choose every setting

How will you use the agent?
  [1] Terminal REPL (default)
  [2] API Server (for web/mobile clients)
  [3] Both

Writing .env... done
Writing config.json... done

=== Verification ===
  [OK] filesystem MCP server responds
  [OK] web MCP server responds
  [OK] github MCP server responds
  [WARN] google MCP server — missing GOOGLE_CLIENT_ID (skipped)

Setup complete! Run the agent with:
  ./run.sh        (macOS/Linux)
  run.bat         (Windows)
```

**Estimated effort:** Medium (2-3 days).

### 3.2 — Cross-Platform Config with Forward-Slash Paths

Currently `config-base.json` uses Windows backslash paths. This breaks on macOS/Linux.

**Fix:** Normalize `config-base.json` to use forward slashes universally. Both Node.js and Python handle forward slashes on all OSes. No code changes required — just fix the JSON.

Additionally, replace absolute paths with `${MICRO_X_HOME}`-relative paths where possible, so the config works on any machine that sets one env var:

```json
{
  "args": ["${MICRO_X_HOME}/mcp_servers/ts/packages/filesystem/dist/index.js"]
}
```

The setup wizard would set `MICRO_X_HOME` in `.env` and generate a config using these relative paths.

**Estimated effort:** Low (a few hours).

### 3.3 — Prerequisite Checker (`scripts/check-prereqs.py`)

A lightweight, standalone script that checks for all prerequisites and prints per-OS install instructions.

```
=== Prerequisite Check ===

Python 3.11+:       [OK] 3.13.1
Node.js 18+:        [MISSING]
  Install: https://nodejs.org/en/download
  macOS:   brew install node
  Ubuntu:  sudo apt install nodejs npm
  Windows: winget install OpenJS.NodeJS.LTS

uv (optional):      [OK] 0.5.4
.NET 10 (optional):  [MISSING]
Go 1.21+ (optional): [MISSING]
```

Non-invasive — doesn't install anything, just reports. Can be run before the full setup wizard.

**Estimated effort:** Low (half a day).

### 3.4 — Startup Validation

On `python -m micro_x_agent_loop`, check for common problems before bootstrapping:
- Node.js not installed (MCP servers will fail)
- MCP servers not built (`dist/` missing)
- Config references MCP server that doesn't exist
- API key env vars empty/missing

Print actionable errors instead of cryptic stack traces.

**Estimated effort:** Low (half a day).

### 3.5 — Auto-Build MCP Servers in Entry Scripts

If `mcp_servers/ts/packages/filesystem/dist/index.js` doesn't exist, automatically run `npm install && npm run build` in `mcp_servers/ts/`. Add this to both `run.sh` and `run.bat`.

Eliminates the most common "forgot to build" problem.

**Estimated effort:** Low (a few hours).

### 3.6 — Docker / Container Deployment

Provide a Dockerfile for users who want zero-install deployment. This is particularly useful for the **server mode**, where the agent runs headlessly.

**Architecture:**

```dockerfile
FROM python:3.13-slim

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs

# Copy project
COPY . /app
WORKDIR /app

# Install Python deps
RUN pip install .

# Build TypeScript MCP servers
RUN cd mcp_servers/ts && npm install && npm run build

# Default: API server mode
EXPOSE 8321
CMD ["python", "-m", "micro_x_agent_loop", "--server", "start"]
```

**Docker Compose for a clean experience:**

```yaml
services:
  agent:
    build: .
    ports:
      - "8321:8321"
    env_file: .env
    environment:
      - SERVER_HOST=0.0.0.0
      - SERVER_PORT=8321
    volumes:
      - ./config.json:/app/config.json
      - ~/Documents:/workspace
      - ./.micro_x:/app/.micro_x
```

**Considerations:**
- Server mode is the natural Docker deployment — no TTY needed
- REPL mode needs `-it` (interactive TTY)
- Google OAuth and WhatsApp QR flows don't work in containers
- Working directory must be a mounted volume

**Estimated effort:** Low-Medium (1-2 days).

### 3.7 — PyPI Packaging (`pip install micro-x-agent`)

Publish to PyPI so users can `pip install micro-x-agent` or `pipx install micro-x-agent`.

**Challenges:**
- TypeScript MCP servers are not Python packages — they'd need to be pre-built and included as package data, or `post_install` must run `npm install && npm run build`
- Python MCP server (codegen) also needs bundling
- Config generation still needed
- API key setup still needed

**Approach:**
1. Pre-build TypeScript MCP servers and include `dist/` as package data
2. Register a CLI entry point in `pyproject.toml`: `micro-x = micro_x_agent_loop.__main__:main`
3. Add subcommands: `micro-x setup`, `micro-x check`, `micro-x run`

```bash
pipx install micro-x-agent
micro-x setup     # interactive wizard
micro-x           # start the agent
micro-x --server start  # start the API server
```

**Estimated effort:** High (3-5 days). Requires restructuring the build to bundle pre-built JS, handling package data paths, and a proper CLI with subcommands.

### 3.8 — Platform-Specific Installers

For truly non-technical users.

| Platform | Format | Tool |
|----------|--------|------|
| Windows | `.msi` or `.exe` installer | WiX, Inno Setup, or `pyinstaller` + NSIS |
| macOS | `.dmg` or Homebrew formula | `py2app` or `brew tap` |
| Linux | `.deb` / `.rpm` / Snap / Flatpak | `fpm`, `snapcraft` |

**Estimated effort:** Very High (1-2 weeks per platform). Overkill for the current stage.

---

## 4. MCP Server Complexity Tiers

### Tier 1 — Zero-config (built-in, no extra credentials)
- **filesystem** — always available, core tool
- **codegen** — needs `ANTHROPIC_API_KEY` (already required for the agent itself), plus `uv`

### Tier 2 — API-key-only (one secret, no build step beyond the TS build)
- **web** — needs `BRAVE_API_KEY` for search; `web_fetch` works without
- **github** — needs `GITHUB_TOKEN`
- **anthropic-admin** — needs `ANTHROPIC_ADMIN_API_KEY`
- **devto** — needs `DEV_TO_API_KEY`

### Tier 3 — OAuth flow or complex auth
- **google** — needs Google Cloud project + OAuth consent screen + client ID/secret + browser auth flow
- **linkedin** — needs `LINKEDIN_CLIENT_ID` + `LINKEDIN_CLIENT_SECRET` (OAuth)
- **x-twitter** — needs `X_CLIENT_ID` + `X_CLIENT_SECRET` (OAuth, PKCE)

### Tier 4 — External repo + separate runtime
- **system-info** — .NET SDK + clone separate mcp-servers repo + build
- **whatsapp** — Go + GCC + clone whatsapp-mcp repo + build bridge + QR code auth
- **interview-assist** — needs clone of interview-assist-2 repo + `DEEPGRAM_API_KEY`
- **discord** — npm global install (`npm i -g mcp-discord`) + `DISCORD_TOKEN` (bot setup required)

**Recommendation:** The setup wizard enables Tier 1 servers by default, asks about Tier 2 keys, provides guided setup for Tier 3, and mentions Tier 4 as "advanced" with links to docs.

---

## 5. Config Simplification

The current `config-base.json` is ~200 lines and includes every possible option and all MCP servers. A non-expert user doesn't need to understand compaction thresholds, tool result summarization, or tool formatting rules.

### Proposed: Config profiles as named presets

```
Which configuration profile?
  [1] Standard (recommended) — memory, compaction, prompt caching, sensible defaults
  [2] Minimal — no memory, no compaction, lowest complexity
  [3] Cost-optimized — all cost reduction features enabled
  [4] Custom — choose every setting
```

The setup wizard writes the full `config.json` based on the selected profile, with correct paths for the user's machine. Advanced users can still edit `config.json` directly.

### Proposed: Minimal viable config

The absolute minimum `config.json` for a working agent:

```json
{}
```

Everything has defaults. The only thing truly required is `ANTHROPIC_API_KEY` in `.env`. The agent starts with no MCP servers (no tools) but runs.

To get the filesystem tools (the most essential):

```json
{
  "McpServers": {
    "filesystem": {
      "command": "node",
      "args": ["mcp_servers/ts/packages/filesystem/dist/index.js"]
    }
  }
}
```

**Recommendation:** Document the "just works" minimal config prominently, and let the setup wizard add complexity as the user opts in.

---

## 6. Recommended Implementation Roadmap

### Phase 1 — Quick wins (1-2 days)

1. **Fix `config-base.json` path separators** — Use forward slashes universally (works on all OSes in Node.js/Python). Add `${MICRO_X_HOME}` relative paths.
2. **Auto-build MCP servers in `run.sh`/`run.bat`** — If `mcp_servers/ts/packages/filesystem/dist/index.js` doesn't exist, run `npm install && npm run build` automatically.
3. **`scripts/check-prereqs.py`** — Cross-platform prerequisite checker with install instructions.
4. **Startup validation** — On `python -m micro_x_agent_loop`, check for common problems (Node.js missing, MCP servers not built, invalid config) and print actionable errors.
5. **Write a `QUICKSTART.md`** — 10-step guide from zero to running agent, with OS-specific instructions.

### Phase 2 — Interactive setup wizard (2-3 days)

6. **`setup.py` interactive wizard** — Prerequisite check, API key collection, config generation, MCP build, verification.
7. **Config profiles** — Standard, Minimal, Cost-optimized presets generated by the wizard.
8. **Deployment mode selection** — Wizard asks: REPL, API Server, or both. Generates appropriate config/instructions.

### Phase 3 — Distribution (3-5 days)

9. **Dockerfile + docker-compose.yml** — For server-mode deployment. Default entry point is `--server start`.
10. **PyPI packaging** — Pre-built MCP servers as package data, `micro-x setup` CLI subcommand.
11. **CLI entry point** — Add `[project.scripts]` to `pyproject.toml`: `micro-x = "micro_x_agent_loop.__main__:main"`.

### Phase 4 — Polish (ongoing)

12. **Google OAuth setup guide** — Step-by-step with screenshots for creating Google Cloud credentials.
13. **Config editor** — `micro-x config` TUI for modifying settings without editing JSON.
14. **Health check command** — `micro-x doctor` that diagnoses all integration issues.
15. **Auto-update** — Check for new versions on startup, offer one-command upgrade.

---

## 7. Open Questions

1. **Should we bundle Node.js?** Tools like `pkg` or `nexe` can compile Node.js apps into single binaries, eliminating the Node.js prerequisite. Trade-off: larger distribution size (~50MB), but one less thing to install.

2. **Should MCP servers be pre-built in the repo?** Committing `dist/` directories to git removes the build step for users. Trade-off: repo bloat, version drift between source and dist. Alternative: publish pre-built artifacts as GitHub release assets.

3. **Config file format:** JSON is unforgiving (no comments, strict syntax). Should we support TOML or YAML as alternatives? TOML is especially user-friendly for simple key-value settings.

4. **Target audience:** Is this for developers who are comfortable with terminals, or truly non-technical users? The answer significantly affects whether we need platform installers (Phase 4+) or can stop at the interactive setup wizard (Phase 2).

5. **Server as primary deployment?** For non-expert users, `--server start` with a web UI may be simpler than a terminal REPL. Should the setup wizard default to server mode? This would require a companion web client (currently only a CLI WebSocket client exists).

6. **Versioning:** How do users know they need to update? How do they update without losing their config and `.env`? The setup wizard should be idempotent — re-running it preserves existing secrets and config.

---

## 8. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| TypeScript MCP server build fails (missing npm, network issues) | High — no tools available | Pre-flight check, clear error messages, auto-build in run scripts |
| User's Python is 3.10 or older | Medium — won't start | Prerequisite check with instructions; venv created with explicit python3.11 |
| Google OAuth setup is too complex | Low — optional feature | Step-by-step guide, or skip entirely; Tier 3 complexity |
| Config.json has wrong paths | High — MCP servers fail to start | Auto-generated config with validated paths; startup validation |
| Windows path issues (backslashes in JSON, spaces in paths) | Medium | Forward-slash normalization, quoted paths in MCP args |
| API key entered incorrectly | Medium — cryptic API errors | Validate key format and make a test API call during setup |
| Docker can't do OAuth/WhatsApp flows | Low — documented limitation | Clear docs, recommend local install for full feature set |
| Server mode needs a web client | Medium — useless without UI | Note: currently only CLI WebSocket client exists; a web UI would be needed for non-expert server deployment |
| ToolFormatting is complex and easy to misconfigure | Medium | Setup wizard generates correct formatting for enabled servers; defaults are sensible |

---

## 9. Success Criteria

A non-expert user should be able to go from "I just cloned this repo" to a working agent with filesystem + web tools in **under 10 minutes** with:
- No manual JSON editing
- No undocumented environment variables
- No separate build commands
- Clear error messages for anything that goes wrong

The setup experience should be **idempotent** — running it again doesn't break existing configuration, and offers to update/reconfigure.
