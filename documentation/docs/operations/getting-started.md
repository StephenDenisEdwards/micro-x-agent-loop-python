# Getting Started

## Prerequisites

- [Python 3.11](https://www.python.org/downloads/) or later
- An LLM provider API key: [Anthropic](https://console.anthropic.com/), [OpenAI](https://platform.openai.com/), [DeepSeek](https://platform.deepseek.com/), or [Gemini](https://aistudio.google.com/) — or use [Ollama](local-llm-ollama.md) for free local inference (no API key needed)
- [Node.js 18+](https://nodejs.org/) — required for TypeScript MCP tool servers
- (Optional) Google OAuth credentials for Gmail and Calendar tools
- (Optional) [.NET 10 SDK](https://dotnet.microsoft.com/download) for the system-info MCP server (in the shared [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repo)
- (Optional) [Go 1.21+](https://go.dev/dl/) and a C compiler (GCC) for the WhatsApp MCP server

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/StephenDenisEdwards/micro-x-agent-loop-python.git
cd micro-x-agent-loop-python
```

### 2. Create the `.env` file

Create `.env` in the project root with your API keys:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
ANTHROPIC_ADMIN_API_KEY=sk-ant-admin...
```

The Google credentials are optional — they are passed to the `google` MCP server via its `env` block in `config.json`. If the server is not configured, Google tools will not be available. The Anthropic Admin API key is optional — it is passed to the `anthropic-admin` MCP server. All other tools work normally.

### 3. Configure settings

Edit `config.json` to set your preferences:

```json
{
  "Model": "claude-sonnet-4-5-20250929",
  "MaxTokens": 8192,
  "WorkingDirectory": "C:\\path\\to\\your\\documents"
}
```

See [Configuration Reference](config.md) for all available settings.

### 4. Run

**Easiest method — use the startup script:**

Windows:
```bash
run.bat
```

macOS/Linux:
```bash
chmod +x run.sh
./run.sh
```

The startup script automatically:
1. Creates a virtual environment (`.venv/`) if it doesn't exist
2. Installs the package and all dependencies if not already installed
3. Launches the agent REPL

You should see:

```
micro-x-agent-loop (type 'exit' to quit)
MCP servers:
  - filesystem: bash, read_file, write_file, append_file, save_memory
  - web: web_fetch, web_search
  - linkedin: linkedin_jobs, linkedin_job_detail
  - github: list_prs, get_pr, create_pr, list_issues, create_issue, get_file, search_code, list_repos
  - google: gmail_search, gmail_read, gmail_send, calendar_list_events, ...
  - anthropic-admin: anthropic_usage
  - interview-assist: ia_healthcheck, ia_list_recordings, ...
  - system-info: system_info, disk_info, network_info
  - whatsapp: search_contacts, list_messages, list_chats, get_chat, ...
Working directory: C:\path\to\your\documents

you>
```

All tools are provided by MCP servers. If a server fails to connect (e.g. missing credentials, unbuilt project), a warning is logged but the agent starts normally with the remaining servers.

**Alternative — pip install:**

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate    # macOS/Linux
pip install .
python -m micro_x_agent_loop
```

**Alternative — uv:**

```bash
uv sync
uv run python -m micro_x_agent_loop
```

**API server mode** (for web, desktop, or mobile clients):

```bash
python -m micro_x_agent_loop --server start
```

This starts a FastAPI server on `http://127.0.0.1:8321` with REST and WebSocket endpoints. See the [API Server Operations](api-server.md) guide for details.

## First Use

Try a simple prompt to verify everything works:

```
you> What files are in the current directory?
```

The agent will use the `bash` tool to run `dir` or `ls` and report the results.

### Gmail First Use

The first time you use a Gmail tool, a browser window will open for Google OAuth sign-in. After authorizing, tokens are cached in `.gmail-tokens/` for future sessions.

```
you> Search my Gmail for unread emails from the last 3 days
```

### Calendar First Use

The first time you use a Calendar tool, a separate browser window will open for Google OAuth sign-in (Calendar uses its own scope). After authorizing, tokens are cached in `.calendar-tokens/` for future sessions.

```
you> What meetings do I have today?
```

### MCP Server Setup (Optional)

The system-info MCP server lives in the shared [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repository (used by both the Python and .NET agents). To enable it:

1. Install the [.NET 10 SDK](https://dotnet.microsoft.com/download) (or later)
2. Clone and build the server:

```bash
git clone https://github.com/StephenDenisEdwards/mcp-servers.git
dotnet build mcp-servers/system-info/src
```

3. Update the `McpServers` entry in `config.json` to point to the server with an absolute path:

```json
{
  "McpServers": {
    "system-info": {
      "transport": "stdio",
      "command": "dotnet",
      "args": ["run", "--no-build", "--project", "C:\\path\\to\\mcp-servers\\system-info\\src"]
    }
  }
}
```

4. On next startup, the agent will show `system-info__system_info`, `system-info__disk_info`, and `system-info__network_info` in the tool list.

Rebuild after any code changes to the MCP server — the config uses `--no-build` to avoid build output interfering with the stdio transport.

### WhatsApp MCP Server Setup (Optional)

The agent can send and receive WhatsApp messages via the [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) external MCP server. This is a two-component system: a **Go bridge** that connects to WhatsApp Web, and a **Python MCP server** that the agent communicates with.

**Prerequisites:** [Go 1.21+](https://go.dev/dl/), a C compiler (GCC), and [uv](https://docs.astral.sh/uv/).

> **Windows users:** The Go bridge depends on CGO (go-sqlite3), which requires GCC in your PATH. Windows does not ship with GCC. Install via MSYS2 (`pacman -S mingw-w64-ucrt-x86_64-gcc`) or [WinLibs](https://winlibs.com/), then build using **PowerShell** (not Git Bash). See the [full WhatsApp setup guide](../design/tools/whatsapp-mcp/README.md#windows-specific-the-cgo-problem) for details.

**Step 1 — Clone and build the Go bridge:**

```bash
git clone https://github.com/lharries/whatsapp-mcp.git
cd whatsapp-mcp/whatsapp-bridge
CGO_ENABLED=1 go build -o whatsapp-bridge .   # Linux/macOS
```

On Windows (PowerShell):
```powershell
$env:PATH = "C:\msys64\ucrt64\bin;" + $env:PATH   # adjust to your GCC location
$env:CGO_ENABLED = "1"
go build -o whatsapp-bridge.exe .
```

**Step 2 — Start the bridge and authenticate (in a separate terminal — keep it open):**

```bash
./whatsapp-bridge          # Linux/macOS
.\whatsapp-bridge.exe      # Windows
```

On first run, the bridge displays a **QR code**. Scan it with your phone:
- Open WhatsApp > **Settings** > **Linked Devices** > **Link a Device**
- Point your phone camera at the QR code

**Step 3 — Wait for sync.** After scanning, wait 30-60 seconds until you see `History sync complete. Stored N messages.` in the bridge terminal. This creates the `store/messages.db` database that the tools read from.

**Step 4 — Add the MCP server to `config.json`:**

Windows:
```json
{
  "McpServers": {
    "whatsapp": {
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "uv", "--directory", "C:\\path\\to\\whatsapp-mcp\\whatsapp-mcp-server", "run", "main.py"]
    }
  }
}
```

macOS / Linux:
```json
{
  "McpServers": {
    "whatsapp": {
      "transport": "stdio",
      "command": "uv",
      "args": ["--directory", "/path/to/whatsapp-mcp/whatsapp-mcp-server", "run", "main.py"]
    }
  }
}
```

> **Windows note:** Use `"command": "python"` with `"-m", "uv"` instead of `"command": "uv"` — the `uv` binary may not be on the system PATH when spawned by the agent.

**Step 5 — Start the agent** (with the bridge still running in its own terminal). WhatsApp tools will appear in the MCP servers section. Test with: `List my 5 most recent WhatsApp chats`

See [WhatsApp MCP](../design/tools/whatsapp-mcp/README.md) for the full setup guide, all 12 tools, known limitations, and troubleshooting.

## Project Structure

```
micro-x-agent-loop-python/
├── .env                           # Secrets (not in git)
├── .env.example                   # Template for .env
├── config.json                    # App configuration (pointer to active config file)
├── pyproject.toml                 # Python package metadata and dependencies
├── run.bat                        # Windows startup script
├── run.sh                         # macOS/Linux startup script
├── README.md                      # Project overview
├── documentation/docs/            # Full documentation
├── mcp_servers/ts/                # TypeScript MCP servers (npm workspaces monorepo)
│   ├── package.json               # Workspaces root
│   ├── tsconfig.base.json
│   └── packages/
│       ├── shared/                # @micro-x-ai/mcp-shared (validation, logging, errors)
│       ├── filesystem/            # bash, read_file, write_file, append_file, save_memory
│       ├── web/                   # web_fetch, web_search
│       ├── linkedin/              # linkedin_jobs, linkedin_job_detail
│       ├── github/                # 8 GitHub tools
│       ├── google/                # 12 Google tools (Gmail, Calendar, Contacts)
│       ├── anthropic-admin/       # anthropic_usage
│       └── interview-assist/      # 14 interview-assist + STT tools
└── src/
    └── micro_x_agent_loop/
        ├── __init__.py
        ├── __main__.py            # Entry point and REPL
        ├── agent.py               # Agent loop orchestrator
        ├── agent_config.py        # Configuration dataclass
        ├── api_payload_store.py   # In-memory ring buffer for API request/response payloads
        ├── app_config.py          # Config parsing (AppConfig, RuntimeEnv)
        ├── bootstrap.py           # Runtime factory (wires MCP, memory, provider)
        ├── tool.py                # Tool Protocol + ToolResult dataclass
        ├── tool_result_formatter.py # Structured → text formatting (json, table, text, key_value)
        ├── llm_client.py          # Shared utilities (Spinner, retry callback)
        ├── logging_config.py      # Log consumer registry (console, file, metrics, api_payload)
        ├── system_prompt.py       # System prompt template + resolve_system_prompt()
        ├── turn_engine.py         # LLM turn loop with parallel tool dispatch
        ├── commands/
        │   └── router.py          # Slash command dispatch (/help, /tool, /debug, etc.)
        ├── mcp/
        │   ├── __init__.py
        │   ├── mcp_tool_proxy.py  # Adapter: MCP tool → Tool Protocol + ToolResult
        │   └── mcp_manager.py     # MCP server connection lifecycle (parallel startup)
        └── memory/
            ├── store.py           # SQLite connection and schema
            ├── session_manager.py # Session CRUD, message persistence
            ├── checkpoints.py     # File snapshotting and rewind
            └── ...
```
