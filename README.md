# micro-x-agent-loop-python

A minimal AI agent loop built with Python and the Anthropic Claude API. The agent runs in a REPL, takes natural-language prompts, and autonomously calls tools to get things done. Responses stream in real time as Claude generates them.

This is the Python port of [micro-x-agent-loop-dotnet](https://github.com/StephenDenisEdwards/micro-x-agent-loop-dotnet). Both projects share the same architecture, tools, and configuration format.

## Features

- **Streaming responses** — text appears word-by-word as Claude generates it
- **Parallel tool execution** — multiple tool calls in a single turn run concurrently via `asyncio.gather`
- **Automatic retry** — tenacity-based exponential backoff on API rate limits
- **Conversation compaction** — LLM-based summarization keeps long conversations within context limits
- **MCP tool servers** — extend the agent with external tools via the Model Context Protocol (stdio and HTTP transports)
- **Configurable logging** — structured logging via loguru to console and/or file
- **Conditional tools** — Gmail, Calendar, Anthropic usage, and web search tools only load when their credentials are present
- **Cross-platform** — works on Windows, macOS, and Linux

## Quick Start

### Prerequisites

- [Python 3.11+](https://python.org/)
- [uv](https://docs.astral.sh/uv/) (package manager) — see [Why uv?](#why-uv) below
- A model provider API key:
  - [Anthropic API key](https://console.anthropic.com/) when `Provider=anthropic` (default), or
  - OpenAI API key when `Provider=openai`
- (Optional) Google OAuth credentials for Gmail and Calendar tools — see [Gmail Setup](#gmail-setup)
- (Optional) [Brave Search API key](https://brave.com/search/api/) for the `web_search` tool
- (Optional) Anthropic Admin API key (`sk-ant-admin...`) for the `anthropic_usage` tool
- (Optional) GitHub personal access token (`GITHUB_TOKEN`) for `github_*` tools
- (Optional) Deepgram API key (`DEEPGRAM_API_KEY`) for Interview Assist transcription/STT tools
- (Optional) [.NET 10 SDK](https://dotnet.microsoft.com/download) for the system-info MCP server (in the shared [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repo)
- (Optional) [Go 1.21+](https://go.dev/dl/) and a C compiler (GCC) for the WhatsApp MCP server
- (Optional) local clone of `interview-assist-2` for Interview Assist MCP tools (analysis/evaluation workflows)

### Install uv

[uv](https://docs.astral.sh/uv/) is a fast Python package and project manager built by [Astral](https://astral.sh/) (the Ruff team). It's written in Rust and replaces `pip`, `pip-tools`, `virtualenv`, and `pyenv` in a single tool — with 10-100x faster dependency resolution and installs.

**Windows (PowerShell) — recommended:**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
This automatically adds `uv` to your PATH. Restart your terminal after installing.

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Or via pip:**
```bash
pip install uv
```

> **Windows PATH issue with `pip install uv`:** When pip installs with `--user` (the default when site-packages is not writeable), the `uv.exe` binary lands in a user Scripts directory that is **not** on your PATH. You'll see:
>
> ```
> 'uv' is not recognized as an internal or external command
> ```
>
> **Fix — choose one:**
>
> 1. **Add the Scripts directory to your PATH** (run in PowerShell, then restart your terminal):
>    ```powershell
>    $scriptsDir = & python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))"
>    [Environment]::SetEnvironmentVariable("Path", "$([Environment]::GetEnvironmentVariable('Path', 'User'));$scriptsDir", "User")
>    ```
>
> 2. **Use the official installer instead** (handles PATH automatically):
>    ```powershell
>    pip uninstall uv -y
>    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
>    ```
>
> 3. **Run uv as a Python module** (no PATH change needed):
>    ```bash
>    python -m uv sync
>    python -m uv run python -m micro_x_agent_loop
>    ```

**Verify the installation:**

```bash
uv --version
```

### 1. Clone and configure

```bash
git clone https://github.com/StephenDenisEdwards/micro-x-agent-loop-python.git
cd micro-x-agent-loop-python
```

Copy the example environment file and fill in your keys:

```bash
cp .env.example .env
```

Then edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
ANTHROPIC_ADMIN_API_KEY=sk-ant-admin...
BRAVE_API_KEY=BSA...
GITHUB_TOKEN=ghp_...
DEEPGRAM_API_KEY=dg_...
```

Required key depends on `Provider` in `config.json`:

- `Provider: "anthropic"` (default) -> `ANTHROPIC_API_KEY` required
- `Provider: "openai"` -> `OPENAI_API_KEY` required

All other keys are optional and only enable specific tool sets.

| Key | Required | Used for |
|-----|----------|----------|
| `ANTHROPIC_API_KEY` | Yes when `Provider=anthropic` | Main LLM provider |
| `OPENAI_API_KEY` | Yes when `Provider=openai` | Main LLM provider |
| `GOOGLE_CLIENT_ID` | No | Gmail, Calendar, Contacts tools (with secret) |
| `GOOGLE_CLIENT_SECRET` | No | Gmail, Calendar, Contacts tools (with client id) |
| `ANTHROPIC_ADMIN_API_KEY` | No | `anthropic_usage` tool |
| `BRAVE_API_KEY` | No | `web_search` tool |
| `GITHUB_TOKEN` | No | GitHub tools (`github_*`) |
| `DEEPGRAM_API_KEY` | No | Interview Assist STT transcription tools (`ia_transcribe_once`, `stt_*`) |

For the Interview Assist MCP server path, set `INTERVIEW_ASSIST_REPO` in the MCP server `env` block in `config.json` (not in `.env`).
### 2. Run

**Windows:**
```cmd
run.bat
```

**macOS / Linux:**
```bash
./run.sh
```

That's it — one command. The script handles everything automatically:

1. **First run:** Creates a Python virtual environment (`.venv/`), installs all dependencies via pip, then starts the agent. This takes 30-60 seconds.
2. **Subsequent runs:** Detects that the venv and packages are already installed, skips straight to starting the agent (instant).
3. **Recovery:** If the venv exists but packages are missing (e.g. after a failed install), it detects this and reinstalls automatically.

You never need to activate a virtual environment, run `pip install`, or know anything about Python packaging.

<details>
<summary>Alternative: using uv</summary>

```bash
uv sync
uv run python -m micro_x_agent_loop
```

</details>

<details>
<summary>Alternative: manual venv + pip</summary>

```bash
python -m venv .venv

# Activate — pick one:
.venv\Scripts\activate        # Windows (cmd)
.venv\Scripts\Activate.ps1    # Windows (PowerShell)
source .venv/bin/activate     # macOS / Linux

pip install .
python -m micro_x_agent_loop
```

</details>

#### You'll see:

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
Compaction: summarize (threshold: 80,000 tokens, tail: 6 messages)
Logging: console (stderr, DEBUG), file (agent.log, DEBUG)

you>
```

Type a natural-language prompt and press Enter. The agent will stream its response and call tools as needed. Type `exit` or `quit` to stop.

Tools that appear depend on which credentials are configured in `.env` and which MCP servers are available.

### 3. MCP server setup (optional)

The system-info MCP server lives in the shared [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repository. To enable it:

1. Install the [.NET 10 SDK](https://dotnet.microsoft.com/download) (or later)
2. Clone and build the server:
   ```bash
   git clone https://github.com/StephenDenisEdwards/mcp-servers.git
   dotnet build mcp-servers/system-info/src
   ```
3. Update the `McpServers` entry in `config.json` to point to the server:
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

### 4. WhatsApp MCP server setup (optional)

The agent can send and receive WhatsApp messages via the [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) external MCP server. This is a two-component system: a **Go bridge** that connects to WhatsApp Web, and a **Python MCP server** that the agent communicates with.

**Prerequisites:** [Go 1.21+](https://go.dev/dl/), a C compiler (GCC), and [uv](https://docs.astral.sh/uv/).

> **Windows users:** The Go bridge depends on CGO (go-sqlite3), which requires GCC in your PATH. Windows does not ship with GCC. Install via MSYS2 (`pacman -S mingw-w64-ucrt-x86_64-gcc`) or [WinLibs](https://winlibs.com/), then build using **PowerShell** (not Git Bash). See the [full WhatsApp setup guide](documentation/docs/design/tools/whatsapp-mcp/README.md) for details.

1. Clone and build the Go bridge:
   ```bash
   git clone https://github.com/lharries/whatsapp-mcp.git
   cd whatsapp-mcp/whatsapp-bridge
   CGO_ENABLED=1 go build -o whatsapp-bridge .
   ```

2. **Start the bridge in a separate terminal** (keep it open) and scan the **QR code** with your phone (WhatsApp > Settings > Linked Devices > Link a Device):
   ```bash
   ./whatsapp-bridge
   ```
   **Wait for sync** — after scanning the QR code, wait 30-60 seconds until you see `History sync complete` in the bridge terminal.

3. Add to `config.json` (Windows — use `python -m uv` since `uv` may not be on PATH):
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
   On macOS/Linux, use `"command": "uv"` with `"args": ["--directory", "/path/to/...", "run", "main.py"]` instead.

4. Start the agent (with the bridge still running) — WhatsApp tools will appear in the MCP servers section. Test with: `List my 5 most recent WhatsApp chats`

The Go bridge must be running and authenticated before the agent starts. If the bridge shows `Client outdated (405)`, update the whatsmeow library and rebuild — see the [full WhatsApp setup guide](documentation/docs/design/tools/whatsapp-mcp/README.md#updating-the-bridge).

### 5. Interview Assist MCP server setup (optional)

This repo includes a local MCP wrapper for `interview-assist-2` analysis/evaluation workflows and STT tools for voice mode.

1. Build the Interview Assist console once:

   ```powershell
   dotnet build C:\Users\steph\source\repos\interview-assist-2\Interview-assist-transcription-detection-console\Interview-assist-transcription-detection-console.csproj
   dotnet build C:\Users\steph\source\repos\interview-assist-2\Interview-assist-stt-cli\Interview-assist-stt-cli.csproj
   ```

2. Add server config:

   ```json
   {
     "McpServers": {
       "interview-assist": {
         "transport": "stdio",
         "command": "python",
         "args": ["C:\\Users\\steph\\source\\repos\\micro-x-agent-loop-python\\mcp_servers\\interview_assist_server.py"],
         "env": {
           "INTERVIEW_ASSIST_REPO": "C:\\Users\\steph\\source\\repos\\interview-assist-2"
         }
       }
     }
   }
   ```

See [Interview Assist MCP docs](documentation/docs/design/tools/interview-assist-mcp/README.md) for tool list and details.

For voice transcription tools, set `DEEPGRAM_API_KEY` in `.env`.

### Configuration

App settings live in `config.json` in the project root:

```json
{
  "Model": "claude-sonnet-4-5-20250929",
  "MaxTokens": 8192,
  "Temperature": 1.0,
  "MaxToolResultChars": 40000,
  "MaxConversationMessages": 50,
  "CompactionStrategy": "summarize",
  "CompactionThresholdTokens": 80000,
  "ProtectedTailMessages": 6,
  "WorkingDirectory": "C:\\Users\\you\\documents",
  "LogLevel": "DEBUG",
  "LogConsumers": [
    { "type": "console" },
    { "type": "file", "path": "agent.log" }
  ],
  "McpServers": {
    "system-info": {
      "transport": "stdio",
      "command": "dotnet",
      "args": ["run", "--no-build", "--project", "C:\\path\\to\\mcp-servers\\system-info\\src"]
    }
  }
}
```

| Setting | Description | Default |
|---------|-------------|---------|
| `Model` | Claude model ID | `claude-sonnet-4-5-20250929` |
| `MaxTokens` | Max tokens per response | `8192` |
| `Temperature` | Sampling temperature (0.0 = deterministic, 1.0 = creative) | `1.0` |
| `MaxToolResultChars` | Max characters per tool result before truncation | `40000` |
| `MaxConversationMessages` | Max messages in history before trimming oldest | `50` |
| `CompactionStrategy` | `"none"` or `"summarize"` — LLM-based conversation compaction | `"none"` |
| `CompactionThresholdTokens` | Estimated token count that triggers compaction | `80000` |
| `ProtectedTailMessages` | Recent messages protected from compaction | `6` |
| `WorkingDirectory` | Default directory for file and shell tools | Current working directory |
| `LogLevel` | Logging level (DEBUG, INFO, WARNING, ERROR) | `"DEBUG"` |
| `LogConsumers` | Array of log outputs (`console` and/or `file`) | `[]` |
| `McpServers` | MCP server configurations (see [MCP docs](documentation/docs/operations/config.md#mcpservers)) | `{}` |

All settings are optional — sensible defaults are used when missing. See [Configuration Reference](documentation/docs/operations/config.md) for full details.

Secrets (API keys) stay in `.env` and are loaded by python-dotenv.

## Gmail Setup

Gmail and Calendar tools require Google OAuth2 credentials. If you don't need them, skip this section entirely — all other tools work without it.

### 1. Create OAuth credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select an existing one)
3. Enable the **Gmail API** and **Google Calendar API** under APIs & Services > Library
4. Go to APIs & Services > Credentials > Create Credentials > OAuth client ID
5. Application type: **Desktop app**
6. Copy the **Client ID** and **Client Secret** into your `.env` file

### 2. First-run authorization

The first time you use a Gmail tool (e.g. `gmail_search`), a browser window will open asking you to sign in to your Google account and grant permission. After you authorize:

- An access token is cached locally in `.gmail-tokens/token.json`
- Subsequent runs reuse the cached token (no browser prompt)
- The token auto-refreshes when expired

Calendar tools trigger a separate OAuth flow on first use, with tokens cached in `.calendar-tokens/`.

## Tools

### Always available

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands (cmd.exe on Windows, bash on Unix). 30s timeout. |
| `read_file` | Read text files and `.docx` documents. Relative paths resolve against `WorkingDirectory`. |
| `write_file` | Write content to a file, creating parent directories as needed. |
| `append_file` | Append content to an existing file, creating it if it doesn't exist. |
| `linkedin_jobs` | Search LinkedIn job postings with filters (keyword, location, date, type, remote, experience, limit). |
| `linkedin_job_detail` | Fetch full job description from a LinkedIn job URL. |
| `web_fetch` | Fetch and extract content from a URL (HTML converted to text, JSON pretty-printed). |

### Conditional (require credentials)

| Tool | Required credential | Description |
|------|-------------------|-------------|
| `gmail_search` | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Search Gmail using Gmail search syntax |
| `gmail_read` | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Read full email content by message ID |
| `gmail_send` | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Send a plain-text email |
| `calendar_list_events` | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | List events by date range or search query |
| `calendar_create_event` | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Create events with title, time, attendees |
| `calendar_get_event` | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Get full event details by ID |
| `anthropic_usage` | `ANTHROPIC_ADMIN_API_KEY` | Query usage, cost, and Claude Code productivity reports |
| `web_search` | `BRAVE_API_KEY` | Search the web via Brave Search API |

### MCP tools (dynamic)

MCP tools are discovered from external servers configured in `config.json`. The system-info server (from the shared [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repo) provides:

| Tool | Description |
|------|-------------|
| `system-info__system_info` | OS, CPU, memory, uptime, .NET runtime |
| `system-info__disk_info` | Per-drive disk usage (fixed drives) |
| `system-info__network_info` | Network interfaces with IP addresses |

The external [WhatsApp MCP server](documentation/docs/design/tools/whatsapp-mcp/README.md) provides:

| Tool | Description |
|------|-------------|
| `whatsapp__search_contacts` | Search contacts by name or phone number |
| `whatsapp__list_messages` | Search/filter messages with pagination and context |
| `whatsapp__list_chats` | List chats with search and sorting |
| `whatsapp__get_chat` | Chat metadata by JID |
| `whatsapp__get_direct_chat_by_contact` | Find direct chat by phone number |
| `whatsapp__get_contact_chats` | All chats involving a contact |
| `whatsapp__get_last_interaction` | Most recent message with a contact |
| `whatsapp__get_message_context` | Messages surrounding a specific message |
| `whatsapp__send_message` | Send text to a phone number or group JID |
| `whatsapp__send_file` | Send a file (image, video, document) |
| `whatsapp__send_audio_message` | Send audio as a voice message (requires ffmpeg) |
| `whatsapp__download_media` | Download media from a message |

The local [Interview Assist MCP server](documentation/docs/design/tools/interview-assist-mcp/README.md) provides:

| Tool | Description |
|------|-------------|
| `interview-assist__ia_healthcheck` | Validate Interview Assist repo/project setup |
| `interview-assist__ia_list_recordings` | List recent Interview Assist recording files |
| `interview-assist__ia_analyze_session` | Generate markdown report from session JSONL |
| `interview-assist__ia_evaluate_session` | Evaluate precision/recall/F1 for a session |
| `interview-assist__ia_compare_strategies` | Compare heuristic/LLM/parallel detection strategies |
| `interview-assist__ia_tune_threshold` | Tune detection confidence threshold |
| `interview-assist__ia_regression_test` | Run regression check against baseline |
| `interview-assist__ia_create_baseline` | Create baseline JSON from session data |
| `interview-assist__ia_transcribe_once` | One-shot microphone/loopback transcription |
| `interview-assist__stt_list_devices` | List STT sources plus detected capture/render endpoint devices |
| `interview-assist__stt_start_session` | Start continuous STT session |
| `interview-assist__stt_get_updates` | Poll incremental STT events |
| `interview-assist__stt_get_session` | Read STT session status/counters |
| `interview-assist__stt_stop_session` | Stop STT session |

MCP tools are prefixed as `{server_name}__{tool_name}`. Any MCP-compatible server can be added via config — no code changes needed. See [Tool System Design](documentation/docs/design/DESIGN-tool-system.md#mcp-tools-dynamic) for details.

## Example Prompts

### File operations

```
Read the file documents/Stephen Edwards CV December 2025.docx and summarise it
```

```
Create a file called notes.txt with a summary of today's tasks
```

### Shell commands

```
List all Python files in this project
```

```
What's the current git status?
```

### LinkedIn job search

```
Search LinkedIn for remote senior .NET developer jobs posted in the last week
```

```
Get the full job description for the first result
```

### Web

```
Fetch the content from https://example.com and summarise it
```

```
Search the web for "Python asyncio best practices" and summarise the top results
```

### Gmail

```
Search my Gmail for unread emails from the last 3 days
```

```
Send an email to alice@example.com with subject "Meeting Notes" and body "Here are the notes from today's meeting..."
```

### Calendar

```
What meetings do I have today?
```

```
Create a meeting called "Team Standup" tomorrow at 10am for 30 minutes
```

### WhatsApp

```
Search my WhatsApp contacts for John
```

```
List my recent WhatsApp chats
```

```
Send a WhatsApp message to 1234567890 saying "I'll be there in 10 minutes"
```

### System information

```
What are my system specs?
```

### Multi-step tasks

```
Read my CV from documents/Stephen Edwards CV December 2025.docx, then search LinkedIn for .NET jobs in London posted this week, and write a cover letter for the best match
```

```
Search my Gmail for emails from recruiters in the last week and summarise them
```

### Voice mode

```text
/voice start microphone
```

```text
/voice start microphone --mic-device-name "Headset (Jabra Evolve2 65)"
```

```text
/voice start microphone --mic-device-id {0.0.1.00000000}.{...}
```

```text
/voice start microphone --chunk-seconds 2 --endpointing-ms 500 --utterance-end-ms 1500
```

```text
/voice status
```

```text
/voice events 50
```

```text
/voice stop
```

Voice mode details:

- The agent only executes spoken turns from `utterance_final` STT events.
- Finalization timing is controlled primarily by Deepgram settings passed through MCP (`endpointing_ms`, `utterance_end_ms`).
- `chunk_seconds` remains in the command surface for compatibility with earlier session implementations.
- If microphone capture is wrong/empty, use `interview-assist__stt_list_devices` and pass `--mic-device-name` or `--mic-device-id` on `/voice start`.

### Voice Tuning Quick Reference

Balanced (recommended):

```text
/voice start microphone --mic-device-name "Headset (Jabra Evolve2 65)" --endpointing-ms 500 --utterance-end-ms 1500
```

Fast response (may split more):

```text
/voice start microphone --mic-device-name "Headset (Jabra Evolve2 65)" --endpointing-ms 300 --utterance-end-ms 1000
```

Conservative finalization (less cutoff):

```text
/voice start microphone --mic-device-name "Headset (Jabra Evolve2 65)" --endpointing-ms 700 --utterance-end-ms 2200
```

## Dependencies

| Package | Purpose | C# Equivalent |
|---------|---------|---------------|
| [anthropic](https://pypi.org/project/anthropic/) | Claude API (official SDK) | Anthropic.SDK |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | Load `.env` files | DotNetEnv |
| [tenacity](https://pypi.org/project/tenacity/) | Retry with exponential backoff | Polly |
| [python-docx](https://pypi.org/project/python-docx/) | Read `.docx` files | DocumentFormat.OpenXml |
| [beautifulsoup4](https://pypi.org/project/beautifulsoup4/) + [lxml](https://pypi.org/project/lxml/) | HTML parsing and conversion | HtmlAgilityPack |
| [httpx](https://pypi.org/project/httpx/) | Async HTTP client | HttpClient |
| [google-api-python-client](https://pypi.org/project/google-api-python-client/) | Gmail and Calendar API | Google.Apis.Gmail.v1 |
| [google-auth-oauthlib](https://pypi.org/project/google-auth-oauthlib/) | Google OAuth2 flow | Google.Apis.Auth |
| [loguru](https://pypi.org/project/loguru/) | Structured logging | Serilog |
| [mcp](https://pypi.org/project/mcp/) | Model Context Protocol client | ModelContextProtocol |

## Quality Gates

This repo enforces code quality via CI and local hooks:

- `ruff check src tests` (lint)
- `ruff format --check src tests` (format)
- `mypy` on critical architecture modules:
  - `src/micro_x_agent_loop/agent.py`
  - `src/micro_x_agent_loop/turn_engine.py`
  - `src/micro_x_agent_loop/voice_runtime.py`
  - `src/micro_x_agent_loop/mcp/`
  - `src/micro_x_agent_loop/providers/`
- `python -m unittest discover -s tests`

Local setup:

```bash
pip install ".[dev]"
pre-commit install
```

## Why uv?

This project uses **uv** instead of pip for package management.

| Feature | uv | pip |
|---------|-----|-----|
| Install speed | 10-100x faster (Rust) | Baseline |
| Virtual env management | Automatic (`uv sync` creates `.venv/`) | Manual (`python -m venv`) |
| Run in venv | `uv run <cmd>` — no activate needed | `source .venv/bin/activate` first |
| Lockfile | `uv.lock` for reproducible installs | Requires `pip-compile` |
| Python version management | Built-in (`uv python install 3.12`) | Needs pyenv |
| Config format | Standard `pyproject.toml` | `requirements.txt` or `pyproject.toml` |

**Key commands for this project:**

| Command | What it does |
|---------|-------------|
| `uv sync` | Install all dependencies from `pyproject.toml` into `.venv/` |
| `uv run python -m micro_x_agent_loop` | Run the app inside the managed venv |
| `uv add <package>` | Add a new dependency to `pyproject.toml` and install it |
| `uv remove <package>` | Remove a dependency |

## Troubleshooting

### `'uv' is not recognized` on Windows

See the [Install uv](#install-uv) section above. The quickest fix is to run `uv` as a Python module instead:

```bash
python -m uv sync
python -m uv run python -m micro_x_agent_loop
```

### `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` environment variable is required

Create a `.env` file in the project root containing the key for your configured provider:

```
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...
```

Or copy the example: `cp .env.example .env` and fill in your key.

### Gmail/Calendar tools not showing up

These tools only register when both `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set in `.env`. If you don't need them, this is expected — the other tools work without it.

### Gmail OAuth browser doesn't open

If the OAuth browser window fails to open on a headless machine, you'll need to run the first authorization on a machine with a browser. The resulting `.gmail-tokens/token.json` can then be copied to the headless machine.

### MCP server fails with "Failed to parse JSONRPC message"

The MCP server is writing non-JSONRPC data to stdout (e.g., build output or logging). For .NET servers, build separately (`dotnet build path/to/mcp-servers/system-info/src`) and use `--no-build` in the config. See [Troubleshooting](documentation/docs/operations/troubleshooting.md) for details.

### WhatsApp: `gcc not found` when building the bridge

The Go bridge uses CGO (go-sqlite3) and needs GCC. On Windows, install via MSYS2 or WinLibs, and build using PowerShell (not Git Bash). See [WhatsApp setup guide](documentation/docs/design/tools/whatsapp-mcp/README.md#windows-specific-the-cgo-problem).

### WhatsApp: `Client outdated (405)` when starting the bridge

WhatsApp has rejected the bridge's client version. Update the Go library and rebuild:
```bash
cd whatsapp-mcp/whatsapp-bridge
go get go.mau.fi/whatsmeow@latest && go mod tidy
CGO_ENABLED=1 go build -o whatsapp-bridge .
rm -rf store/           # delete old session
./whatsapp-bridge       # scan QR code again
```
See [Updating the Bridge](documentation/docs/design/tools/whatsapp-mcp/README.md#updating-the-bridge) for Windows instructions and troubleshooting build errors.

### WhatsApp: tools return empty results

All WhatsApp tools succeed but return no data. This means the SQLite database (`whatsapp-bridge/store/messages.db`) does not exist yet. Start the Go bridge, scan the QR code, and wait for the history sync to complete (30-60 seconds) before using the agent.

### WhatsApp: `Connection refused` when sending messages

The Go bridge must be running at `localhost:8080` before using WhatsApp tools. Start it with `./whatsapp-bridge` (or `.\whatsapp-bridge.exe` on Windows). The bridge must stay running in its own terminal.

### `Rate limited. Retrying in Xs...`

The agent automatically retries with exponential backoff (10s, 20s, 40s, 80s, 160s) when the Anthropic API returns a rate limit error. Wait for retries to complete — no action needed.

### Tool output truncated warning

If a tool returns more than 40,000 characters, the output is truncated. You can increase the limit in `config.json`:

```json
{
  "MaxToolResultChars": 80000
}
```

### Conversation history trimmed warning

When the conversation exceeds 50 messages, the oldest messages are removed. Enable compaction for smarter context management:

```json
{
  "CompactionStrategy": "summarize",
  "MaxConversationMessages": 100
}
```

## Architecture

```
src/micro_x_agent_loop/
  __main__.py              -- Entry point: loads config, builds tools, initializes MCP, starts REPL
  agent.py                 -- Agent loop: streaming, parallel tool dispatch, history management
  agent_config.py          -- Configuration dataclass
  llm_client.py            -- Anthropic API streaming + tenacity retry
  compaction.py            -- Conversation compaction strategies (none, summarize)
  logging_config.py        -- Loguru logging setup from config
  system_prompt.py         -- System prompt text
  tool.py                  -- Tool Protocol (structural typing interface)
  tool_registry.py         -- Assembles tools with dependencies (conditional registration)
  mcp/
    mcp_manager.py         -- MCP server connection lifecycle
    mcp_tool_proxy.py      -- Adapter: MCP tool -> Tool Protocol
  tools/
    bash_tool.py
    read_file_tool.py
    write_file_tool.py
    append_file_tool.py
    html_utilities.py      -- Shared HTML-to-text conversion
    web/
      web_fetch_tool.py    -- Fetch and extract web content
      web_search_tool.py   -- Web search via Brave Search API
      search_provider.py   -- Search provider abstraction
      brave_search_provider.py
    linkedin/
      linkedin_jobs_tool.py
      linkedin_job_detail_tool.py
    gmail/
      gmail_auth.py        -- OAuth2 flow + token caching
      gmail_parser.py      -- MIME parsing + body extraction
      gmail_search_tool.py
      gmail_read_tool.py
      gmail_send_tool.py
    calendar/
      calendar_auth.py     -- OAuth2 flow (separate tokens)
      calendar_list_events_tool.py
      calendar_create_event_tool.py
      calendar_get_event_tool.py
    anthropic/
      anthropic_usage_tool.py  -- Usage/cost/Claude Code reports

```

The system-info MCP server lives in the separate [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repository, shared with the .NET agent.

### How the agent loop works

1. You type a prompt at the `you>` prompt
2. The prompt is sent to Claude via the Anthropic streaming API
3. Claude's response streams word-by-word to your terminal
4. If Claude decides to use tools, the tool calls are executed **in parallel** via `asyncio.gather`
5. Tool results are sent back to Claude, which continues generating a response
6. Steps 3-5 repeat until Claude responds with text only (no tool calls)
7. The conversation history is maintained across prompts in the same session
8. When the conversation grows large, compaction summarizes older messages to stay within context limits

## Documentation

Full documentation is available in the [documentation/docs/](documentation/docs/index.md) directory:

- [Software Architecture Document](documentation/docs/architecture/SAD.md) — system overview, components, data flow
- [Tool System Design](documentation/docs/design/DESIGN-tool-system.md) — tool interface, registry, MCP integration
- [Compaction Design](documentation/docs/design/DESIGN-compaction.md) — conversation compaction algorithm
- [WhatsApp MCP Setup](documentation/docs/design/tools/whatsapp-mcp/README.md) — WhatsApp integration guide, prerequisites, pain points
- [Configuration Reference](documentation/docs/operations/config.md) — all settings with types and defaults
- [Architecture Decision Records](documentation/docs/architecture/decisions/README.md) — index of all ADRs

## See Also

- [micro-x-agent-loop-dotnet](https://github.com/StephenDenisEdwards/micro-x-agent-loop-dotnet) — the original C#/.NET 8 implementation with full architecture documentation, ADRs, and design docs

## License

MIT

