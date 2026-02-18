# WhatsApp MCP Server

## Overview

The WhatsApp MCP server gives the agent the ability to search, read, and send WhatsApp messages. It is an **external MCP server** — not bundled in this repository — based on the [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) project.

Unlike the bundled system-info MCP server, WhatsApp requires a **two-component architecture**: a Go bridge that maintains a persistent connection to WhatsApp Web, and a Python MCP server that the agent communicates with via stdio.

## Architecture

```
┌──────────────┐    stdio/JSONRPC    ┌──────────────────┐   HTTP :8080    ┌─────────────────┐   WebSocket   ┌──────────────┐
│  Agent Loop  │ ◄────────────────► │  Python MCP      │ ─────────────► │   Go Bridge     │ ◄──────────► │  WhatsApp    │
│  (this repo) │                    │  Server           │               │   (whatsmeow)   │              │  Web         │
└──────────────┘                    │                   │               │                 │              └──────────────┘
                                    │  reads SQLite  ──►│               │  writes SQLite  │
                                    └──────────────────┘               └─────────────────┘
                                              │                                  │
                                              └───────── messages.db ◄───────────┘
```

### Components

| Component | Language | Role |
|-----------|----------|------|
| **Go bridge** (`whatsapp-bridge/`) | Go | Connects to WhatsApp Web via the [whatsmeow](https://github.com/tulir/whatsmeow) library. Stores messages in a SQLite database. Exposes an HTTP API on port 8080 for sending messages and fetching contacts. |
| **Python MCP server** (`whatsapp-mcp-server/`) | Python | FastMCP server that reads the SQLite database for message history and calls the bridge HTTP API for sending. Communicates with the agent via stdio JSONRPC. |

### Data Flow

- **Reading messages**: Python MCP server queries SQLite directly at `../whatsapp-bridge/store/messages.db` (relative to the MCP server directory)
- **Sending messages**: Python MCP server calls `http://localhost:8080/api/messages/send` on the Go bridge
- **Contact search**: Python MCP server calls `http://localhost:8080/api/contacts` on the Go bridge
- **Media download**: Python MCP server calls `http://localhost:8080/api/messages/download-media` on the Go bridge

## Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| [Go](https://go.dev/dl/) | 1.21+ | Build the WhatsApp bridge |
| [uv](https://docs.astral.sh/uv/) | any | Run the Python MCP server |
| GCC / C compiler | any | Required by go-sqlite3 (CGO dependency) |

### Windows-Specific: The CGO Problem

The Go bridge uses [go-sqlite3](https://github.com/mattn/go-sqlite3), which is a CGO package — it contains C code that must be compiled with a C compiler. This is the single biggest pain point on Windows, because Go's CGO toolchain requires GCC in `PATH`, and Windows does not ship with GCC.

**What you will see if GCC is missing:**

```
cgo: C compiler "gcc" not found: exec: "gcc": executable file not found in %PATH%
```

**Options for getting GCC on Windows:**

| Option | Pros | Cons |
|--------|------|------|
| [WinLibs MinGW-w64](https://winlibs.com/) | Standalone, no installer bloat | Installs to a very long path under `AppData\Local\Microsoft\WinGet\Packages\` when installed via winget; some shells cannot access it |
| [MSYS2](https://www.msys2.org/) | Full Unix-like environment | Heavy; winget install may place it in an unexpected location |
| [TDM-GCC](https://jmeubank.github.io/tdm-gcc/) | Simple installer, short path | Less actively maintained |
| [Chocolatey mingw](https://community.chocolatey.org/packages/mingw) | `choco install mingw` | Requires Chocolatey |

**Recommended approach:** Install WinLibs via winget, then use PowerShell (not bash/Git Bash) to build, because Git Bash may fail to resolve the long WinGet package path:

```powershell
winget install BrechtSanders.WinLibs.POSIX.UCRT
# Find where it installed
$gccDir = (Get-ChildItem -Recurse "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "gcc.exe" | Select-Object -First 1).DirectoryName
$env:PATH = "$gccDir;$env:PATH"
$env:CGO_ENABLED = "1"
```

**Pain point — long paths in Git Bash:** WinLibs installs to a deeply nested path like:
```
C:\Users\you\AppData\Local\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin
```
Git Bash / MSYS2 bash may not be able to `cd` into or execute binaries from this path. Use **PowerShell** or **cmd.exe** instead when building the Go bridge.

### macOS / Linux

On macOS, GCC is available via Xcode Command Line Tools (`xcode-select --install`). On Linux, install `gcc` or `build-essential` from your package manager. CGO works without issues on these platforms.

## Setup

### 1. Clone the WhatsApp MCP repository

```bash
git clone https://github.com/lharries/whatsapp-mcp.git
cd whatsapp-mcp
```

### 2. Build the Go bridge

**macOS / Linux:**
```bash
cd whatsapp-bridge
CGO_ENABLED=1 go build -o whatsapp-bridge .
```

**Windows (PowerShell) — see [CGO Problem](#windows-specific-the-cgo-problem) above:**
```powershell
cd whatsapp-bridge
$gccDir = (Get-ChildItem -Recurse "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "gcc.exe" | Select-Object -First 1).DirectoryName
$env:PATH = "$gccDir;$env:PATH"
$env:CGO_ENABLED = "1"
go build -o whatsapp-bridge.exe .
```

The build produces a ~36 MB binary (`whatsapp-bridge` or `whatsapp-bridge.exe`).

### 3. Run the bridge and authenticate

```bash
./whatsapp-bridge    # or whatsapp-bridge.exe on Windows
```

On first run, the bridge prints a **QR code** to the terminal. Scan it with your phone:

1. Open WhatsApp on your phone
2. Go to **Settings > Linked Devices > Link a Device**
3. Scan the QR code displayed in the terminal

After scanning, the bridge connects to WhatsApp Web and begins receiving messages. It stores them in `whatsapp-bridge/store/messages.db`.

**Pain points:**
- The QR code expires quickly (~60 seconds). If it expires, restart the bridge to get a new one.
- The terminal must support Unicode block characters for the QR code to render correctly. Windows Terminal works; older cmd.exe may not.
- The bridge must stay running. If you close it, the MCP server loses the ability to send messages (reading cached messages from SQLite still works).

### 4. Configure the MCP server in config.json

Add the WhatsApp MCP server to your agent's `config.json`:

```json
{
  "McpServers": {
    "whatsapp": {
      "transport": "stdio",
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\whatsapp-mcp\\whatsapp-mcp-server", "run", "main.py"]
    }
  }
}
```

Replace `C:\\path\\to\\whatsapp-mcp\\whatsapp-mcp-server` with the actual absolute path to the cloned `whatsapp-mcp-server` directory.

The `uv --directory` flag ensures `uv` resolves the `pyproject.toml` from the correct directory and installs dependencies (`httpx`, `mcp[cli]`, `requests`) automatically.

### 5. Start the agent

Start the agent with `run.bat` or `run.sh`. You should see the WhatsApp tools in the MCP servers section:

```
MCP servers:
  - system-info: system_info, disk_info, network_info
  - whatsapp: search_contacts, list_messages, list_chats, get_chat, ...
```

## Startup Order

The Go bridge and the Python MCP server are **independent processes** with different lifecycles:

```
1. Start the Go bridge          →  must be running first
2. Start the agent (run.bat)    →  spawns the Python MCP server via uv
```

The agent's `McpManager` spawns the Python MCP server as a child process (stdio transport). But the Python MCP server needs the Go bridge to be running at `localhost:8080` for send operations and the SQLite database to exist for read operations.

**If the bridge is not running:**
- Message reading may still work (if the SQLite file exists from a previous session)
- Sending messages, searching contacts, and downloading media will fail with connection errors

## Tools

The WhatsApp MCP server exposes 12 tools. All tool names are prefixed with `whatsapp__` in the agent.

### Message Tools

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `list_messages` | `whatsapp__list_messages` | Search and filter messages by date, sender, chat, content. Supports pagination and context (messages before/after matches). |
| `get_message_context` | `whatsapp__get_message_context` | Get surrounding messages for a specific message ID. Useful for understanding conversation flow. |
| `send_message` | `whatsapp__send_message` | Send a text message to a phone number or group JID. |
| `send_file` | `whatsapp__send_file` | Send a file (image, video, document) to a phone number or group JID. |
| `send_audio_message` | `whatsapp__send_audio_message` | Send an audio file as a WhatsApp voice message (auto-converts to Opus .ogg). Requires ffmpeg. |
| `download_media` | `whatsapp__download_media` | Download media from a message to a local file path. |

### Chat Tools

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `list_chats` | `whatsapp__list_chats` | List chats with optional search, pagination, and sorting. |
| `get_chat` | `whatsapp__get_chat` | Get chat metadata by JID. |
| `get_direct_chat_by_contact` | `whatsapp__get_direct_chat_by_contact` | Find the direct chat with a contact by phone number. |
| `get_contact_chats` | `whatsapp__get_contact_chats` | Get all chats involving a specific contact. |

### Contact Tools

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `search_contacts` | `whatsapp__search_contacts` | Search contacts by name or phone number. |
| `get_last_interaction` | `whatsapp__get_last_interaction` | Get the most recent message involving a contact. |

### Recipient Format

For tools that accept a `recipient` parameter:
- **Individual chat**: Phone number with country code, no `+` or symbols (e.g., `1234567890`)
- **Group chat**: Group JID (e.g., `120363001234567890@g.us`)

## Known Limitations

1. **Bridge must run separately** — The Go bridge is not managed by the MCP config. You must start it manually before using WhatsApp tools.

2. **SQLite path is relative** — The Python MCP server reads `../whatsapp-bridge/store/messages.db` relative to its own directory. This means the `whatsapp-mcp` repo must keep its default directory layout.

3. **Bridge port is hardcoded** — The Go bridge listens on port 8080 and the Python MCP server calls `http://localhost:8080/api`. If port 8080 is in use, you must modify the source code.

4. **Audio messages require ffmpeg** — The `send_audio_message` tool converts audio to Opus .ogg format, which requires ffmpeg installed and in PATH. Falls back to `send_file` if unavailable.

5. **No message history before bridge start** — The bridge only stores messages received while it is running. Historical messages from before the bridge was started are not available.

6. **Single WhatsApp account** — The bridge connects to one WhatsApp account. To switch accounts, delete the `whatsapp-bridge/store/` directory and re-scan a new QR code.

7. **Session expiry** — WhatsApp may disconnect the linked device after ~14 days of inactivity. Re-run the bridge and scan a new QR code when this happens.

## Troubleshooting

See [Troubleshooting](../../../operations/troubleshooting.md) for general MCP issues and WhatsApp-specific problems.

### Quick Checks

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `gcc not found` during build | No C compiler in PATH | See [CGO Problem](#windows-specific-the-cgo-problem) |
| QR code doesn't render | Terminal doesn't support Unicode | Use Windows Terminal or iTerm2 |
| `Connection refused` on send | Bridge not running | Start the bridge first |
| `no such table` from SQLite | Database not created yet | Start the bridge and let it connect |
| Tools not appearing at startup | Config path wrong | Check the `--directory` path in config.json |
| `send_audio_message` fails | ffmpeg not installed | Install ffmpeg or use `send_file` instead |
