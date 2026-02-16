# micro-x-agent-loop-python

A minimal AI agent loop built with Python and the Anthropic Claude API. The agent runs in a REPL, takes natural-language prompts, and autonomously calls tools to get things done. Responses stream in real time as Claude generates them.

This is the Python port of [micro-x-agent-loop-dotnet](https://github.com/StephenDenisEdwards/micro-x-agent-loop-dotnet). Both projects share the same architecture, tools, and configuration format.

## Features

- **Streaming responses** — text appears word-by-word as Claude generates it
- **Parallel tool execution** — multiple tool calls in a single turn run concurrently via `asyncio.gather`
- **Automatic retry** — tenacity-based exponential backoff on API rate limits
- **Configurable limits** — max tool result size and conversation history length with clear warnings
- **Conditional tools** — Gmail tools only load when credentials are present
- **Cross-platform** — works on Windows, macOS, and Linux

## Quick Start

### Prerequisites

- [Python 3.11+](https://python.org/)
- [uv](https://docs.astral.sh/uv/) (package manager) — see [Why uv?](#why-uv) below
- An [Anthropic API key](https://console.anthropic.com/)
- (Optional) Google OAuth credentials for Gmail tools — see [Gmail Setup](#gmail-setup)

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
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
```

Only `ANTHROPIC_API_KEY` is required. Google credentials are optional — if omitted, Gmail tools are simply not registered and everything else works normally.

### 2. Install dependencies and run

#### Option A: Using uv (recommended)

```bash
uv sync
uv run python -m micro_x_agent_loop
```

#### Option B: Using pip (no extra tools needed)

```bash
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows (cmd)
.venv\Scripts\activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Install dependencies and run:

```bash
pip install .
python -m micro_x_agent_loop
```

#### You'll see:

```
micro-x-agent-loop (type 'exit' to quit)
Tools: bash, read_file, write_file, linkedin_jobs, linkedin_job_detail, gmail_search, gmail_read, gmail_send

you>
```

Type a natural-language prompt and press Enter. The agent will stream its response and call tools as needed. Type `exit` or `quit` to stop.

### Configuration

App settings live in `config.json` in the project root:

```json
{
  "Model": "claude-sonnet-4-5-20250929",
  "MaxTokens": 8192,
  "Temperature": 1.0,
  "MaxToolResultChars": 40000,
  "MaxConversationMessages": 50,
  "DocumentsDirectory": "C:\\path\\to\\your\\documents"
}
```

| Setting | Description | Default |
|---------|-------------|---------|
| `Model` | Claude model ID | `claude-sonnet-4-5-20250929` |
| `MaxTokens` | Max tokens per response | `8192` |
| `Temperature` | Sampling temperature (0.0 = deterministic, 1.0 = creative) | `1.0` |
| `MaxToolResultChars` | Max characters per tool result before truncation | `40000` |
| `MaxConversationMessages` | Max messages in history before trimming oldest | `50` |
| `DocumentsDirectory` | Fallback directory for `read_file` relative paths | _(none)_ |

All settings are optional — sensible defaults are used when missing.

Secrets (API keys) stay in `.env` and are loaded by python-dotenv.

## Gmail Setup

Gmail tools require Google OAuth2 credentials. If you don't need Gmail, skip this section entirely — all other tools work without it.

### 1. Create OAuth credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or select an existing one)
3. Enable the **Gmail API** under APIs & Services > Library
4. Go to APIs & Services > Credentials > Create Credentials > OAuth client ID
5. Application type: **Desktop app**
6. Copy the **Client ID** and **Client Secret** into your `.env` file

### 2. First-run authorization

The first time you use a Gmail tool (e.g. `gmail_search`), a browser window will open asking you to sign in to your Google account and grant permission. After you authorize:

- An access token is cached locally in `.gmail-tokens/token.json`
- Subsequent runs reuse the cached token (no browser prompt)
- The token auto-refreshes when expired

The agent requests two Gmail scopes:
- `gmail.readonly` — for searching and reading emails
- `gmail.send` — for sending emails

## Tools

### bash

Execute shell commands and return the output. Uses `cmd.exe` on Windows and `bash` on Unix. Commands time out after 30 seconds.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | yes | The bash command to execute |

### read_file

Read the contents of a file and return it as text. Supports plain text files and `.docx` documents (via python-docx).

For relative paths, the tool walks up from the current working directory to the repo root (`.git` directory) looking for a match. If not found, it falls back to the configured `DocumentsDirectory`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute or relative path to the file to read |

### write_file

Write content to a file, creating parent directories if they don't exist.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute or relative path to the file to write |
| `content` | string | yes | The content to write to the file |

### linkedin_jobs

Search for job postings on LinkedIn. Returns job title, company, location, date posted, salary (if listed), and URL.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `keyword` | string | yes | Job search keyword (e.g. `"software engineer"`) |
| `location` | string | no | Job location (e.g. `"New York"`, `"Remote"`) |
| `dateSincePosted` | string | no | Recency filter: `"past month"`, `"past week"`, or `"24hr"` |
| `jobType` | string | no | Employment type: `"full time"`, `"part time"`, `"contract"`, `"temporary"`, `"internship"` |
| `remoteFilter` | string | no | Work arrangement: `"on site"`, `"remote"`, or `"hybrid"` |
| `experienceLevel` | string | no | Level: `"internship"`, `"entry level"`, `"associate"`, `"senior"`, `"director"`, `"executive"` |
| `limit` | string | no | Max results to return (default `"10"`) |
| `sortBy` | string | no | Sort order: `"recent"` or `"relevant"` |

### linkedin_job_detail

Fetch the full job specification/description from a LinkedIn job URL. Use this after `linkedin_jobs` to get complete details for a specific posting.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | yes | The LinkedIn job URL (from a `linkedin_jobs` search result) |

### gmail_search

Search Gmail using [Gmail search syntax](https://support.google.com/mail/answer/7190?hl=en). Returns message ID, date, sender, subject, and snippet for each match. Only available when Google credentials are configured.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Gmail search query (e.g. `"is:unread"`, `"from:boss@co.com newer_than:7d"`) |
| `maxResults` | number | no | Max number of results (default 10) |

### gmail_read

Read the full content of a Gmail email by its message ID (from `gmail_search` results). Handles multipart MIME messages, preferring HTML content converted to readable plain text.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `messageId` | string | yes | The Gmail message ID (from `gmail_search` results) |

### gmail_send

Send a plain-text email from your Gmail account.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | string | yes | Recipient email address |
| `subject` | string | yes | Email subject line |
| `body` | string | yes | Email body (plain text) |

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
Run pytest and tell me if anything failed
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

```
Search LinkedIn for Python developer jobs in London, sorted by most recent
```

### Gmail

```
Search my Gmail for unread emails from the last 3 days
```

```
Read the email with subject "Interview Invitation" and summarise it
```

```
Send an email to alice@example.com with subject "Meeting Notes" and body "Here are the notes from today's meeting..."
```

### Multi-step tasks

```
Read my CV from documents/Stephen Edwards CV December 2025.docx, then search LinkedIn for .NET jobs in London posted this week, and write a cover letter for the best match
```

```
Search my Gmail for emails from recruiters in the last week and summarise them
```

```
Search LinkedIn for Python developer jobs in London, get the details for the top 3, and write a summary comparing them
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
| [google-api-python-client](https://pypi.org/project/google-api-python-client/) | Gmail API | Google.Apis.Gmail.v1 |
| [google-auth-oauthlib](https://pypi.org/project/google-auth-oauthlib/) | Google OAuth2 flow | Google.Apis.Auth |

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

### `ANTHROPIC_API_KEY environment variable is required`

Create a `.env` file in the project root containing your API key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Or copy the example: `cp .env.example .env` and fill in your key.

### Gmail tools not showing up

Gmail tools only register when both `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set in `.env`. If you don't need Gmail, this is expected — the other tools work without it.

### Gmail OAuth browser doesn't open

If the OAuth browser window fails to open on a headless machine, you'll need to run the first authorization on a machine with a browser. The resulting `.gmail-tokens/token.json` can then be copied to the headless machine.

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

When the conversation exceeds 50 messages, the oldest messages are removed. You can increase the limit in `config.json`:

```json
{
  "MaxConversationMessages": 100
}
```

## Architecture

```
__main__.py              -- Entry point: loads config, builds tools, starts REPL
agent.py                 -- Agent loop: streaming, parallel tool dispatch, history management
agent_config.py          -- Configuration dataclass
llm_client.py            -- Anthropic API streaming + tenacity retry
tool.py                  -- Tool Protocol (structural typing interface)
tool_registry.py         -- Assembles tools with dependencies (conditional Gmail)
tools/
  bash_tool.py
  read_file_tool.py
  write_file_tool.py
  html_utilities.py      -- Shared HTML-to-text conversion
  linkedin/
    linkedin_jobs_tool.py
    linkedin_job_detail_tool.py
  gmail/
    gmail_auth.py        -- OAuth2 flow + token caching
    gmail_parser.py      -- MIME parsing + body extraction
    gmail_search_tool.py
    gmail_read_tool.py
    gmail_send_tool.py
```

### How the agent loop works

1. You type a prompt at the `you>` prompt
2. The prompt is sent to Claude via the Anthropic streaming API
3. Claude's response streams word-by-word to your terminal
4. If Claude decides to use tools, the tool calls are executed **in parallel** via `asyncio.gather`
5. Tool results are sent back to Claude, which continues generating a response
6. Steps 3-5 repeat until Claude responds with text only (no tool calls)
7. The conversation history is maintained across prompts in the same session

## See Also

- [micro-x-agent-loop-dotnet](https://github.com/StephenDenisEdwards/micro-x-agent-loop-dotnet) — the original C#/.NET 8 implementation with full architecture documentation, ADRs, and design docs

## License

MIT
