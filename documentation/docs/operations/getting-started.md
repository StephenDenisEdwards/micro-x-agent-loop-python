# Getting Started

## Prerequisites

- [Python 3.11](https://www.python.org/downloads/) or later
- An [Anthropic API key](https://console.anthropic.com/)
- (Optional) Google OAuth credentials for Gmail tools

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
```

The Google credentials are optional — if omitted, the Gmail tools will not be registered and all other tools work normally.

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
Tools: bash, read_file, write_file, linkedin_jobs, linkedin_job_detail, gmail_search, gmail_read, gmail_send
Working directory: C:\path\to\your\documents

you>
```

If Google credentials are not configured, the Gmail tools will not appear in the tool list.

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
└── src/
    └── micro_x_agent_loop/
        ├── __init__.py
        ├── __main__.py            # Entry point and REPL
        ├── agent.py               # Agent loop orchestrator
        ├── agent_config.py        # Configuration dataclass
        ├── llm_client.py          # Anthropic API + streaming + tenacity
        ├── system_prompt.py       # System prompt text
        ├── tool.py                # Tool Protocol (interface)
        └── tools/
            ├── tool_registry.py   # Tool assembly and registration
            ├── bash_tool.py       # Shell command execution
            ├── read_file_tool.py  # File reading (.txt, .docx)
            ├── write_file_tool.py # File writing
            ├── html_utilities.py  # Shared HTML-to-text
            ├── linkedin/
            │   ├── linkedin_jobs_tool.py    # Job search
            │   └── linkedin_job_detail_tool.py # Job detail fetch
            └── gmail/
                ├── gmail_auth.py      # OAuth2 flow
                ├── gmail_parser.py    # MIME parsing
                ├── gmail_search_tool.py # Email search
                ├── gmail_read_tool.py   # Email reading
                └── gmail_send_tool.py   # Email sending
```
