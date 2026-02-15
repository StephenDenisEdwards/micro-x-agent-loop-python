# micro-x-agent-loop-python

A minimal AI agent loop built with Python and the Anthropic Claude API. The agent runs in a REPL, takes natural-language prompts, and autonomously calls tools to get things done. Responses stream in real time as Claude generates them.

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
- [uv](https://docs.astral.sh/uv/) (package manager)
- An [Anthropic API key](https://console.anthropic.com/)
- (Optional) Google OAuth credentials for Gmail tools

### 1. Clone and configure

```bash
git clone https://github.com/StephenDenisEdwards/micro-x-agent-loop-python.git
cd micro-x-agent-loop-python
```

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
```

Google credentials are optional — if omitted, Gmail tools are simply not registered.

### 2. Install dependencies and run

```bash
uv sync
uv run python -m micro_x_agent_loop
```

You'll see:

```
micro-x-agent-loop (type 'exit' to quit)
Tools: bash, read_file, write_file, linkedin_jobs, linkedin_job_detail, gmail_search, gmail_read, gmail_send

you>
```

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

## Tools

### bash

Execute shell commands and return the output (cmd.exe on Windows, bash on Unix). 30-second timeout.

### read_file

Read the contents of a text file or `.docx` document. Relative paths are resolved by walking up to the repo root, then falling back to the configured `DocumentsDirectory`.

### write_file

Write content to a file, creating parent directories if needed.

### linkedin_jobs

Search LinkedIn job postings by keyword, location, date, job type, remote filter, experience level, and sort order.

### linkedin_job_detail

Fetch the full job description from a LinkedIn job URL (returned by `linkedin_jobs`).

### gmail_search

Search Gmail using Gmail search syntax. Returns message ID, date, sender, subject, and snippet for each match. Only available when Google credentials are configured.

### gmail_read

Read the full content of a Gmail message by its ID.

### gmail_send

Send a plain-text email from your Gmail account.

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

### LinkedIn job search

```
Search LinkedIn for remote senior .NET developer jobs posted in the last week
```

```
Get the full job description for the first result
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

## License

MIT
