# Getting Started

## Prerequisites

- [Python 3.11](https://www.python.org/downloads/) or later
- An [Anthropic API key](https://console.anthropic.com/)
- (Optional) Google OAuth credentials for Gmail and Calendar tools
- (Optional) [.NET 10 SDK](https://dotnet.microsoft.com/download) for the bundled system-info MCP server
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

The Google credentials are optional — if omitted, the Gmail and Calendar tools will not be registered. The Anthropic Admin API key is optional — if omitted, the `anthropic_usage` tool will not be registered. All other tools work normally.

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
Tools:
  - bash
  - read_file
  - write_file
  - append_file
  - linkedin_jobs
  - linkedin_job_detail
  - web_fetch
  - gmail_search
  - gmail_read
  - gmail_send
  - calendar_list_events
  - calendar_create_event
  - calendar_get_event
  - anthropic_usage
  - web_search
MCP servers:
  - system-info: system_info, disk_info, network_info
  - whatsapp: search_contacts, list_messages, list_chats, get_chat, ...
Working directory: C:\path\to\your\documents

you>
```

If Google credentials or the Anthropic Admin API key are not configured, their respective tools will not appear in the tool list. If the .NET SDK is not installed or the system-info MCP server has not been built, the MCP servers section will not appear (a warning is logged but the agent starts normally). The same applies to the WhatsApp MCP server — if it is not configured or the bridge is not set up, the agent starts without WhatsApp tools.

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

The repository includes a bundled .NET MCP server that exposes system information tools (`system_info`, `disk_info`, `network_info`). To enable it:

1. Install the [.NET 10 SDK](https://dotnet.microsoft.com/download) (or later)
2. Build the server:

```bash
dotnet build mcp-servers/system-info
```

3. The `McpServers` entry in `config.json` is already configured. On next startup, the agent will show `system-info__system_info`, `system-info__disk_info`, and `system-info__network_info` in the tool list.

Rebuild after any code changes to the MCP server — the config uses `--no-build` to avoid build output interfering with the stdio transport.

### WhatsApp MCP Server Setup (Optional)

The agent can connect to WhatsApp via the [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) external MCP server. This is a two-component system: a Go bridge that connects to WhatsApp Web, and a Python MCP server that the agent talks to.

**Prerequisites:** [Go 1.21+](https://go.dev/dl/), a C compiler (GCC), and [uv](https://docs.astral.sh/uv/).

> **Windows users:** The Go bridge depends on CGO (go-sqlite3), which requires GCC in your PATH. This is the biggest pain point on Windows. See the [WhatsApp MCP docs](../design/tools/whatsapp-mcp/README.md#windows-specific-the-cgo-problem) for detailed instructions on installing GCC via WinLibs and working around long-path issues in Git Bash.

1. Clone and build the bridge:

```bash
git clone https://github.com/lharries/whatsapp-mcp.git
cd whatsapp-mcp/whatsapp-bridge
CGO_ENABLED=1 go build -o whatsapp-bridge .   # Linux/macOS
```

On Windows, use PowerShell — see the [full build instructions](../design/tools/whatsapp-mcp/README.md#2-build-the-go-bridge).

2. Start the bridge and scan the QR code with your phone (WhatsApp > Settings > Linked Devices > Link a Device):

```bash
./whatsapp-bridge
```

3. Add the MCP server to `config.json`:

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

4. Start the agent. The WhatsApp tools (`search_contacts`, `list_messages`, `send_message`, etc.) will appear in the MCP servers section.

The Go bridge must be running before you start the agent. See [WhatsApp MCP](../design/tools/whatsapp-mcp/README.md) for the full setup guide, all 12 tools, known limitations, and troubleshooting.

## Project Structure

```
micro-x-agent-loop-python/
├── .env                           # Secrets (not in git)
├── .env.example                   # Template for .env
├── config.json                    # App configuration
├── pyproject.toml                 # Python package metadata and dependencies
├── run.bat                        # Windows startup script
├── run.sh                         # macOS/Linux startup script
├── README.md                      # Project overview
├── documentation/docs/            # Full documentation
├── mcp-servers/                   # MCP tool servers
│   └── system-info/               # .NET MCP server for system information
└── src/
    └── micro_x_agent_loop/
        ├── __init__.py
        ├── __main__.py            # Entry point and REPL
        ├── agent.py               # Agent loop orchestrator
        ├── agent_config.py        # Configuration dataclass
        ├── llm_client.py          # Anthropic API + streaming + tenacity
        ├── system_prompt.py       # System prompt text
        ├── tool.py                # Tool Protocol (interface)
        ├── mcp/
        │   ├── __init__.py
        │   ├── mcp_tool_proxy.py  # Adapter: MCP tool -> Tool Protocol
        │   └── mcp_manager.py     # MCP server connection lifecycle
        └── tools/
            ├── tool_registry.py   # Tool assembly and registration
            ├── bash_tool.py       # Shell command execution
            ├── read_file_tool.py  # File reading (.txt, .docx)
            ├── write_file_tool.py # File writing
            ├── html_utilities.py  # Shared HTML-to-text
            ├── anthropic/
            │   └── anthropic_usage_tool.py  # Usage/cost/Claude Code reports
            ├── linkedin/
            │   ├── linkedin_jobs_tool.py    # Job search
            │   └── linkedin_job_detail_tool.py # Job detail fetch
            ├── gmail/
            │   ├── gmail_auth.py      # OAuth2 flow
            │   ├── gmail_parser.py    # MIME parsing
            │   ├── gmail_search_tool.py # Email search
            │   ├── gmail_read_tool.py   # Email reading
            │   └── gmail_send_tool.py   # Email sending
            └── calendar/
                ├── calendar_auth.py             # OAuth2 flow (separate tokens)
                ├── calendar_list_events_tool.py  # Event listing
                ├── calendar_create_event_tool.py # Event creation
                └── calendar_get_event_tool.py    # Event detail
```
