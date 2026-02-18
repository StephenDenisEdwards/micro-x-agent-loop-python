# Troubleshooting

## Common Issues

### "ANTHROPIC_API_KEY environment variable is required"

The `.env` file is missing or doesn't contain the key.

**Fix:** Create `.env` in the project root with:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Make sure the `.env` file is in the project root directory (where `run.bat` and `config.json` are).

### Rate limit error (HTTP 429)

```
Rate limited. Retrying in 10s (attempt 1/5)...
```

The Anthropic API has per-minute token limits. The agent retries automatically with exponential backoff.

**If it keeps failing:**
- Wait a minute and try again with a shorter prompt
- Lower `MaxTokens` in `config.json` to reduce response size
- Check your API tier at https://console.anthropic.com/
- Consider upgrading your API plan for higher rate limits

### Gmail tools not appearing

```
Tools: bash, read_file, write_file, linkedin_jobs, linkedin_job_detail
```

Gmail tools are only registered when both `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set in `.env`.

**Fix:** Add your Google OAuth credentials to `.env`:
```
GOOGLE_CLIENT_ID=your-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-secret
```

### Gmail OAuth browser window doesn't open

The OAuth flow needs to open a browser for Google sign-in. If you're running in a headless environment or the browser can't launch:

**Fix:** Run the application locally (not via SSH or in a container) for the first OAuth flow. After tokens are cached in `.gmail-tokens/`, the browser is no longer needed.

### "Could not extract job description from the page"

LinkedIn may have blocked the scraping request or changed their HTML structure.

**Possible causes:**
- LinkedIn rate limiting (too many requests in a short time)
- LinkedIn A/B testing different page layouts
- IP-based blocking

**Fix:** Wait a few minutes and try again. If persistent, the CSS selectors in `linkedin_job_detail_tool.py` may need updating.

### "No module named micro_x_agent_loop"

The package is not installed in the virtual environment.

**Fix:** If using `run.bat`/`run.sh`, delete the `.venv` directory and run the script again — it will recreate the environment and install dependencies:

```bash
# Windows
rmdir /s /q .venv
run.bat

# macOS/Linux
rm -rf .venv
./run.sh
```

If using pip manually:
```bash
.venv\Scripts\activate    # Windows
source .venv/bin/activate  # macOS/Linux
pip install .
```

### "OUTPUT TRUNCATED" message in tool results

```
Warning: read_file output truncated from 85,000 to 40,000 chars
```

A tool returned more text than the configured `MaxToolResultChars` limit.

**This is expected behavior.** The truncation prevents excessive token usage. If you need the full output:
- Increase `MaxToolResultChars` in `config.json`
- Ask the agent to read a specific section of the file
- Set `MaxToolResultChars` to `0` to disable truncation (use with caution)

### "Conversation history trimmed" message

```
Note: Conversation history trimmed — removed 2 oldest message(s) to stay within the 50 message limit
```

The conversation has exceeded `MaxConversationMessages`. Oldest messages were removed to stay within the limit.

**This is expected behavior.** It prevents rate limit errors from growing context. If you need longer conversations:
- Increase `MaxConversationMessages` in `config.json`
- Start a new session for unrelated tasks
- Set `MaxConversationMessages` to `0` to disable trimming (risk of rate limits)

### MCP server fails with "Failed to parse JSONRPC message"

```
Failed to parse JSONRPC message from server
pydantic_core._pydantic_core.ValidationError: 1 validation error for JSONRPCMessage
  Invalid JSON: expected value at line 1 column 1 ...
Failed to connect to MCP server 'system-info': Connection closed
```

The MCP server is writing non-JSONRPC data to stdout (e.g., build output, restore messages, or logging), which the MCP client tries to parse as JSONRPC and fails.

**Common causes:**

- Using `dotnet run` without `--no-build` — MSBuild/NuGet restore messages go to stdout
- A Node.js MCP server logging to `console.log` instead of `console.error`
- Any MCP server that writes to stdout before starting the JSONRPC transport

**Fix:** Ensure the MCP server writes **only** JSONRPC messages to stdout. For .NET servers:

1. Build separately: `dotnet build mcp-servers/system-info`
2. Use `--no-build` in the config args: `["run", "--no-build", "--project", "mcp-servers/system-info"]`
3. Use `Host.CreateEmptyApplicationBuilder(settings: null)` instead of `Host.CreateDefaultBuilder()` to avoid default console logging on stdout

For other runtimes, redirect all logging to stderr and ensure nothing writes to stdout except the JSONRPC transport.

### WhatsApp bridge build fails with "gcc not found"

```
cgo: C compiler "gcc" not found: exec: "gcc": executable file not found in %PATH%
```

The Go WhatsApp bridge uses [go-sqlite3](https://github.com/mattn/go-sqlite3), a CGO package that requires a C compiler (GCC) to build. Windows does not ship with GCC.

**Fix:** Install a GCC distribution and ensure it is in your PATH:

- **WinLibs (recommended):** `winget install BrechtSanders.WinLibs.POSIX.UCRT`
- **Chocolatey:** `choco install mingw`
- **MSYS2:** `winget install MSYS2.MSYS2`, then `pacman -S mingw-w64-ucrt-x86_64-gcc`

**Pain point:** WinLibs installed via winget goes to a deeply nested path under `AppData\Local\Microsoft\WinGet\Packages\`. Git Bash may not be able to access this path. Use **PowerShell** to build:

```powershell
$gccDir = (Get-ChildItem -Recurse "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "gcc.exe" | Select-Object -First 1).DirectoryName
$env:PATH = "$gccDir;$env:PATH"
$env:CGO_ENABLED = "1"
cd whatsapp-mcp\whatsapp-bridge
go build -o whatsapp-bridge.exe .
```

On macOS (`xcode-select --install`) and Linux (`apt install build-essential`), GCC is straightforward.

See [WhatsApp MCP docs](../design/tools/whatsapp-mcp/README.md#windows-specific-the-cgo-problem) for full details.

### WhatsApp bridge fails with "Client outdated (405)"

```
[Client ERROR] Client outdated (405) connect failure (client version: 2.3000.xxxx)
[Client/Socket ERROR] Error reading from websocket: websocket: close 1006 (abnormal closure): unexpected EOF
```

WhatsApp has rejected the bridge's client version. The `whatsmeow` Go library needs to be updated and the bridge rebuilt.

**Fix:**

```bash
cd whatsapp-mcp/whatsapp-bridge
go get go.mau.fi/whatsmeow@latest
go mod tidy
CGO_ENABLED=1 go build -o whatsapp-bridge .     # Linux/macOS
```

On Windows (PowerShell), ensure GCC is on PATH:
```powershell
$env:PATH = "C:\msys64\ucrt64\bin;" + $env:PATH   # adjust to your GCC location
$env:CGO_ENABLED = "1"
go get go.mau.fi/whatsmeow@latest
go mod tidy
go build -o whatsapp-bridge.exe .
```

If the build fails with errors like `not enough arguments in call to`, the new whatsmeow version introduced API changes. Common fix: add `context.Background()` as the first argument to affected function calls in `main.go`.

After rebuilding, delete the old session and re-authenticate:
```bash
rm -rf store/
./whatsapp-bridge       # scan QR code again
```

See the [WhatsApp MCP docs](../design/tools/whatsapp-mcp/README.md#updating-the-bridge) for details.

### WhatsApp tools return empty results / "(no output)"

All WhatsApp tools execute without error but return no data.

**Cause:** The SQLite database (`whatsapp-bridge/store/messages.db`) does not exist. This happens when the Go bridge has not been started, has not been authenticated (QR code not scanned), or the history sync has not completed yet.

**Fix:**
1. Start the Go bridge: `./whatsapp-bridge` (or `.\whatsapp-bridge.exe`)
2. Scan the QR code with your phone (WhatsApp > Settings > Linked Devices > Link a Device)
3. Wait 30-60 seconds for the history sync to complete — you will see `History sync complete. Stored N messages.` in the bridge terminal
4. Then start or restart the agent

### WhatsApp tools fail with "Connection refused"

```
httpx.ConnectError: [Errno 111] Connection refused
```

The WhatsApp Python MCP server cannot reach the Go bridge at `http://localhost:8080`.

**Fix:** Start the Go bridge before starting the agent:

```bash
cd whatsapp-mcp/whatsapp-bridge
./whatsapp-bridge          # Linux/macOS
whatsapp-bridge.exe        # Windows
```

The bridge must stay running for send operations to work. Reading cached messages from SQLite may work without the bridge if the database file exists from a previous session.

### WhatsApp QR code expired or doesn't render

On first run, the Go bridge displays a QR code that you scan with your phone. Issues:

- **QR code expired:** The code expires after ~60 seconds. Restart the bridge to get a new one.
- **QR code garbled:** The terminal needs Unicode support. Use Windows Terminal, iTerm2, or any modern terminal emulator. Older cmd.exe may not render the QR code correctly.
- **Already linked:** If you previously linked and the session is still valid, the bridge connects without showing a QR code.

### WhatsApp "no such table" SQLite error

```
sqlite3.OperationalError: no such table: messages
```

The SQLite database at `whatsapp-bridge/store/messages.db` has not been created yet.

**Fix:** Start the Go bridge and let it connect to WhatsApp. The database and tables are created on first successful connection.

### WhatsApp tools not appearing at agent startup

The MCP servers section does not show WhatsApp tools.

**Common causes:**

1. **Wrong path in config.json:** The `--directory` argument must point to the `whatsapp-mcp-server/` directory containing `main.py` and `pyproject.toml`.
2. **uv not installed:** The WhatsApp MCP server is run via `uv`. Install it from https://docs.astral.sh/uv/.
3. **Python dependency error:** Run `uv --directory /path/to/whatsapp-mcp-server sync` manually to see if dependencies install correctly.
4. **Port 8080 conflict:** If another application uses port 8080, the bridge cannot start. Check with `netstat -an | findstr 8080` (Windows) or `lsof -i :8080` (macOS/Linux).

### WhatsApp send_audio_message fails

```
FileNotFoundError: ffmpeg not found
```

The `send_audio_message` tool converts audio files to Opus .ogg format, which requires [ffmpeg](https://ffmpeg.org/) installed and in PATH.

**Fix:** Install ffmpeg, or use `send_file` instead (sends the raw audio file without conversion).

### run.bat creates venv but fails to start

If `run.bat` creates the virtual environment but fails with an error about missing packages:

**Fix:** The script should auto-install dependencies. If it doesn't, install manually:
```bash
.venv\Scripts\pip install .
```

Then run `run.bat` again.

## Diagnostic Tips

### Check your configuration

Run the app and check the tool list printed at startup. Missing tools indicate missing configuration.

### Check `.env` is being loaded

The `.env` file must be in the current working directory when the application runs. `run.bat` and `run.sh` execute from the project root, so place `.env` there.

If running manually, ensure you're in the project root:
```bash
cd micro-x-agent-loop-python
python -m micro_x_agent_loop
```

### Check API key validity

Test your API key independently:

```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: YOUR_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-5-20250929","max_tokens":10,"messages":[{"role":"user","content":"Hi"}]}'
```

### Check Python version

The project requires Python 3.11 or later:
```bash
python --version
```

If you have multiple Python versions, ensure `.venv` was created with the right one:
```bash
python3.11 -m venv .venv
```
