# Planning: End-User Deployment & Installation

**Status:** Draft
**Date:** 2026-03-04
**Goal:** Enable a non-expert user to install, configure, and run micro-x-agent on their machine with minimal friction.

---

## 1. Current State Assessment

### What works today

The project has two entry scripts (`run.sh` for Unix, `run.bat` for Windows) that:
1. Create a Python virtual environment if missing
2. `pip install .` the Python package
3. Launch the REPL

There is also a `config-base.json` with `${VAR}` environment variable placeholders, allowing path-agnostic configuration.

### What a user must currently do manually

| Step | Difficulty | Notes |
|------|-----------|-------|
| Install Python 3.11+ | Medium | Must be correct version, on PATH |
| Install Node.js 18+ | Medium | Required for all TypeScript MCP servers |
| Clone the repo | Easy | `git clone` |
| Create `.env` with API keys | Easy | Copy `.env.example`, fill in keys |
| Set environment variables for `config-base.json` paths | Hard | `MICRO_X_HOME`, `MICRO_X_WORKING_DIR`, `MICRO_X_LOG_DIR` — user must understand the config system |
| Run `npm install && npm run build` in `mcp_servers/ts/` | Medium | Must know about TypeScript build step |
| Choose or create a `config.json` | Hard | Must understand all options, MCP server paths, tool formatting, etc. |
| (Optional) Set up Google OAuth credentials | Hard | Requires Google Cloud Console project, OAuth consent screen, client ID/secret |
| (Optional) Install .NET SDK, clone mcp-servers repo, build | Hard | For system-info server |
| (Optional) Install Go + GCC, clone whatsapp-mcp, build bridge, scan QR | Very Hard | For WhatsApp tools |
| (Optional) Install `uv` | Easy | For codegen MCP server |
| Run `run.sh` or `run.bat` | Easy | |

**Key pain points:**
- No single command to go from zero to working
- TypeScript MCP servers require a separate build step that is never automated
- Config files use absolute paths that differ per machine and OS
- `config-base.json` uses Windows backslash paths — doesn't work on macOS/Linux
- No validation of prerequisites (Python version, Node.js presence, etc.)
- No guided setup for API keys
- Optional tools (WhatsApp, system-info) have deep dependency chains (Go + GCC + CGO build)
- No way to discover what's misconfigured until startup errors appear

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
- Optional keys for Brave Search, GitHub, Google, Deepgram, Anthropic Admin

### Layer 4: Configuration (config.json)
- Machine-specific paths (working directory, log directory, MCP server paths)
- Feature selection (which MCP servers to enable, compaction, memory, etc.)
- Per-tool formatting rules

### Layer 5: Optional integrations (external tools)
- Google OAuth (requires browser-based consent flow)
- WhatsApp (requires Go bridge build + QR auth)
- System-info (requires .NET build)

---

## 3. Proposed Solutions

### 3.1 — Interactive Setup Script (`setup.py` / `setup.sh`)

A guided, interactive setup that handles Layers 2–4 automatically.

**What it does:**
1. **Checks prerequisites** — verifies Python version, Node.js presence, reports what's missing with install instructions per OS
2. **Installs Python dependencies** — creates venv, runs `pip install .`
3. **Builds TypeScript MCP servers** — runs `npm install && npm run build` in `mcp_servers/ts/`
4. **Collects API keys interactively** — prompts for each key with explanation of what it enables; writes `.env`
5. **Generates `config.json`** — auto-detects paths, asks which MCP servers to enable, writes a working config
6. **Validates the result** — attempts to start each enabled MCP server briefly to verify connectivity

**Config generation logic:**
- Auto-detect `MICRO_X_HOME` from the script's own location
- Ask user for their preferred working directory (default: `~/Documents`)
- Ask user for log directory (default: `MICRO_X_HOME/logs`)
- Use OS-appropriate path separators
- Only include MCP server entries for servers whose prerequisites are met (e.g., skip `system-info` if `dotnet` not found)

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

GitHub token (enables PR/issue/repo tools):
  > ghp_...
  [OK]

...

=== Configuration ===

Working directory (where file tools operate):
  > ~/Documents
  [OK] /home/user/Documents

Which features would you like?
  [x] Memory & sessions (recommended)
  [x] Conversation compaction (recommended)
  [ ] Concise output mode
  [ ] Tool result summarization

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

**Estimated effort:** Medium (2-3 days). The setup script is the highest-impact single deliverable.

### 3.2 — Cross-Platform Config with Auto-Detected Paths

Currently `config-base.json` uses `${VAR}` expansion but assumes Windows backslash paths. Replace this with a platform-aware config generator.

**Option A: Runtime path normalization**

Modify `_expand_env_vars()` in `app_config.py` to also normalize path separators for the current OS. Config files could use forward slashes universally, and the loader converts as needed.

```json
{
  "args": ["${MICRO_X_HOME}/mcp_servers/ts/packages/filesystem/dist/index.js"]
}
```

**Option B: Config template with OS-specific rendering**

The setup script generates the full config at install time with correct absolute paths for the user's OS. No env var expansion needed at runtime — paths are baked in.

**Recommendation:** Option A for the config-base template (forward slashes work on both OSes in Node.js and Python), combined with the setup script auto-generating the initial config.

### 3.3 — Prerequisite Installer Helpers

Rather than bundling installers, provide clear per-OS instructions and optionally a check-and-install script.

**`scripts/check-prereqs.sh` / `scripts/check-prereqs.py`:**

```
=== Prerequisite Check ===

Python 3.11+:     [OK] 3.13.1
Node.js 18+:      [MISSING]
  Install: https://nodejs.org/en/download
  macOS:   brew install node
  Ubuntu:  sudo apt install nodejs npm
  Windows: winget install OpenJS.NodeJS.LTS

uv (optional):    [OK] 0.5.4
.NET 10 (optional): [MISSING]
Go 1.21+ (optional): [MISSING]
```

This is lightweight, non-invasive, and doesn't try to auto-install system packages (which requires elevated permissions and varies by distro).

### 3.4 — Docker / Container Deployment

Provide a Dockerfile for users who want zero-install deployment.

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

# Entry point
CMD ["python", "-m", "micro_x_agent_loop"]
```

**Considerations:**
- The agent is a REPL — Docker needs `-it` (interactive TTY)
- `.env` passed via `--env-file .env` or Docker Compose
- `config.json` mounted as a volume or baked into the image
- Google OAuth flow requires a browser — doesn't work in containers without a workaround (token file volume mount from initial local auth)
- WhatsApp bridge requires QR code scanning — not feasible in containers
- Working directory (file tools) must be a mounted volume

**Docker Compose for a clean experience:**

```yaml
services:
  agent:
    build: .
    stdin_open: true
    tty: true
    env_file: .env
    volumes:
      - ./config.json:/app/config.json
      - ~/Documents:/workspace
      - ./.micro_x:/app/.micro_x
```

**Estimated effort:** Low-Medium (1-2 days). Good for tech-savvy users but doesn't eliminate all friction (OAuth, WhatsApp).

### 3.5 — Packaged Distribution (pip install / pipx)

Publish to PyPI so users can `pip install micro-x-agent` or `pipx install micro-x-agent`.

**Challenges:**
- TypeScript MCP servers are not Python packages — they'd need to be pre-built and included as package data, or the `post_install` step must run `npm install && npm run build`
- Config generation still needed
- API key setup still needed

**Approach:**
1. Pre-build TypeScript MCP servers and include the `dist/` output as package data
2. Register a CLI entry point: `micro-x = micro_x_agent_loop.__main__:main`
3. Include `setup` subcommand: `micro-x setup` runs the interactive wizard
4. Include `check` subcommand: `micro-x check` validates prerequisites and config

```bash
pipx install micro-x-agent
micro-x setup     # interactive wizard
micro-x           # start the agent
```

**Estimated effort:** High (3-5 days). Requires restructuring the build to bundle pre-built JS, handling package data paths, and a proper CLI with subcommands.

### 3.6 — Platform-Specific Installers

For truly non-technical users.

| Platform | Format | Tool |
|----------|--------|------|
| Windows | `.msi` or `.exe` installer | WiX, Inno Setup, or `pyinstaller` + NSIS |
| macOS | `.dmg` or Homebrew formula | `py2app` or `brew tap` |
| Linux | `.deb` / `.rpm` / Snap / Flatpak | `fpm`, `snapcraft` |

**What the installer would do:**
1. Bundle Python + Node.js runtimes (or declare them as dependencies)
2. Include pre-built MCP servers
3. Run the setup wizard on first launch
4. Create a desktop shortcut / Start Menu entry

**Estimated effort:** Very High (1-2 weeks per platform). Likely overkill for the current stage of the project. Revisit once the user base grows.

---

## 4. MCP Server Complexity Tiers

Not all MCP servers are equal in setup difficulty. The deployment strategy should tier them:

### Tier 1 — Zero-config (built-in, no extra credentials)
- **filesystem** — always available, core tool
- **linkedin** — scraping, no auth needed
- **codegen** — needs ANTHROPIC_API_KEY (already required for the agent itself)

### Tier 2 — API-key-only (one secret, no build step beyond the TS build)
- **web** — needs BRAVE_API_KEY for search; web_fetch works without
- **github** — needs GITHUB_TOKEN
- **anthropic-admin** — needs ANTHROPIC_ADMIN_API_KEY

### Tier 3 — OAuth flow required
- **google** — needs Google Cloud project + OAuth consent screen + client ID/secret + browser auth flow. Most complex credential setup.

### Tier 4 — External repo + separate runtime
- **system-info** — .NET SDK + clone separate mcp-servers repo + build
- **whatsapp** — Go + GCC + clone whatsapp-mcp repo + build bridge + QR code auth
- **interview-assist** — needs clone of interview-assist-2 repo + Deepgram API key

**Recommendation:** The setup wizard enables Tier 1 servers by default, asks about Tier 2 keys, provides guided setup for Tier 3, and mentions Tier 4 as "advanced" with links to docs.

---

## 5. Config Simplification

The current `config-base.json` is 135 lines and includes every possible option. A non-expert user doesn't need to understand compaction thresholds, tool result summarization, or protected tail messages.

### Proposed: Config profiles as named presets

```
Which configuration profile?
  [1] Standard (recommended) — memory, compaction, sensible defaults
  [2] Minimal — no memory, no compaction, lowest complexity
  [3] Cost-optimized — all cost reduction features enabled
  [4] Custom — choose every setting
```

The setup wizard writes the full config.json based on the selected profile, with correct paths for the user's machine. Advanced users can still edit config.json directly.

### Proposed: Minimal viable config

The absolute minimum config.json for a working agent:

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

1. **`scripts/check-prereqs.py`** — Cross-platform prerequisite checker with install instructions
2. **Fix `config-base.json` path separators** — Use forward slashes universally (works on all OSes in Node.js/Python)
3. **Add MCP server build to `run.sh`/`run.bat`** — If `mcp_servers/ts/packages/filesystem/dist/index.js` doesn't exist, run `npm install && npm run build` automatically
4. **Write a `QUICKSTART.md`** — 10-step guide from zero to running agent, with OS-specific instructions

### Phase 2 — Interactive setup (2-3 days)

5. **`setup.py` interactive wizard** — Prerequisite check, API key collection, config generation, MCP build, verification
6. **Config profiles** — Standard, Minimal, Cost-optimized presets generated by the wizard
7. **Startup validation** — On `python -m micro_x_agent_loop`, check for common problems (Node.js missing, MCP servers not built, invalid config) and print actionable errors

### Phase 3 — Distribution (3-5 days)

8. **Dockerfile + docker-compose.yml** — For users comfortable with containers
9. **PyPI packaging** — Pre-built MCP servers as package data, `micro-x setup` CLI subcommand
10. **CLI entry point** — `micro-x` command with `setup`, `check`, `run` subcommands

### Phase 4 — Polish (ongoing)

11. **Google OAuth setup guide** — Step-by-step with screenshots for creating Google Cloud credentials
12. **Config editor** — `micro-x config` TUI for modifying settings without editing JSON
13. **Health check command** — `micro-x doctor` that diagnoses all integration issues
14. **Auto-update** — Check for new versions on startup, offer one-command upgrade

---

## 7. Open Questions

1. **Should we bundle Node.js?** Tools like `pkg` or `nexe` can compile Node.js apps into single binaries, eliminating the Node.js prerequisite. Trade-off: larger distribution size (~50MB), but one less thing to install.

2. **Should MCP servers be pre-built in the repo?** Committing `dist/` directories to git removes the build step for users. Trade-off: repo bloat, version drift between source and dist. Alternative: publish pre-built artifacts as GitHub release assets.

3. **Config file format:** JSON is unforgiving (no comments, strict syntax). Should we support TOML or YAML as alternatives? The config loader already does env var expansion — adding format support is low effort. TOML is especially user-friendly for simple key-value settings.

4. **Target audience:** Is this for developers who are comfortable with terminals, or truly non-technical users? The answer significantly affects whether we need platform installers (Phase 4+) or can stop at the interactive setup wizard (Phase 2).

5. **Versioning:** How do users know they need to update? How do they update without losing their config and .env? The setup wizard should be idempotent — re-running it preserves existing secrets and config.

---

## 8. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| TypeScript MCP server build fails (missing npm, network issues) | High — no tools available | Pre-flight check, clear error messages, fallback to "no tools" mode |
| User's Python is 3.10 or older | Medium — won't start | Prerequisite check with instructions; venv created with explicit python3.11 |
| Google OAuth setup is too complex | Low — optional feature | Step-by-step guide, or skip entirely; Tier 3 complexity |
| Config.json has wrong paths | High — MCP servers fail to start | Auto-generated config with validated paths; startup validation |
| Windows path issues (backslashes in JSON, spaces in paths) | Medium | Forward-slash normalization, quoted paths in MCP args |
| API key entered incorrectly | Medium — cryptic API errors | Validate key format and make a test API call during setup |
| Docker can't do OAuth/WhatsApp flows | Low — documented limitation | Clear docs, recommend local install for full feature set |

---

## 9. Success Criteria

A non-expert user should be able to go from "I just cloned this repo" to a working agent with filesystem + web tools in **under 10 minutes** with:
- No manual JSON editing
- No undocumented environment variables
- No separate build commands
- Clear error messages for anything that goes wrong

The setup experience should be **idempotent** — running it again doesn't break existing configuration, and offers to update/reconfigure.
