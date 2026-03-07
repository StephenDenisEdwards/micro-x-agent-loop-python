# Trigger Broker Operations

Guide for setting up, configuring, and managing the trigger broker for scheduled agent runs.

## Prerequisites

- Python 3.11+ with the agent installed (`pip install -e .` or `uv pip install -e .`)
- A working `config.json` (or variant) with at least one LLM provider configured
- `.env` file with API keys

## Quick Start

### 1. Add a cron job

```bash
python -m micro_x_agent_loop --job add "daily-summary" "0 9 * * *" "Summarise my unread emails and calendar for today" --tz "Australia/Sydney"
```

This creates a job named `daily-summary` that runs at 9:00 AM Sydney time every day.

### 2. Start the broker

```bash
python -m micro_x_agent_loop --broker start
```

The broker runs in the foreground and dispatches jobs on schedule. It writes a PID file to prevent multiple instances.

### 3. Check status

```bash
python -m micro_x_agent_loop --broker status
```

Shows whether the broker is running, how many jobs are configured, and recent run counts.

### 4. Stop the broker

```bash
python -m micro_x_agent_loop --broker stop
```

Sends a signal to the running broker. In-flight runs are allowed to complete before exit.

## Job Management

### Adding jobs

```bash
python -m micro_x_agent_loop --job add <name> <cron_expr> <prompt> [options]
```

| Option | Purpose |
|--------|---------|
| `--tz <timezone>` | IANA timezone for cron evaluation (e.g. `Europe/London`). Defaults to UTC |
| `--config <path>` | Config file override for this job's agent runs |
| `--session <id>` | Resume a specific session for each run (maintains conversation continuity) |
| `--response-channel <ch>` | Channel for response routing (`http`, `log`, etc.) |
| `--response-target <target>` | Channel-specific target (callback URL, phone number) |
| `--hitl` | Enable async human-in-the-loop (agent can ask questions) |
| `--hitl-timeout <secs>` | How long to wait for a human answer (default: 300) |
| `--max-retries <N>` | Max retry attempts on failure (default: 0) |
| `--retry-delay <secs>` | Base delay between retries in seconds (default: 60, exponential backoff) |

Cron expressions use standard 5-field format: `minute hour day-of-month month day-of-week`

Examples:
- `"0 9 * * *"` — daily at 9:00 AM
- `"*/30 * * * *"` — every 30 minutes
- `"0 9 * * 1-5"` — weekdays at 9:00 AM
- `"0 0 1 * *"` — first of each month at midnight

### Listing jobs

```bash
python -m micro_x_agent_loop --job list
```

Shows all jobs with their cron expressions, enabled status, and next/last run times.

### Removing jobs

```bash
python -m micro_x_agent_loop --job remove <id-prefix>
```

Accepts a prefix of the job ID (enough characters to be unambiguous).

### Enabling/disabling jobs

```bash
python -m micro_x_agent_loop --job enable <id-prefix>
python -m micro_x_agent_loop --job disable <id-prefix>
```

Disabled jobs remain in the database but are skipped during scheduling.

### Manual trigger

```bash
python -m micro_x_agent_loop --job run-now <id-prefix>
```

Runs the job immediately in the foreground (without the broker). Output is printed inline. Useful for testing job prompts.

### Viewing run history

```bash
python -m micro_x_agent_loop --job runs [id-prefix]
```

Shows recent runs with status indicators:

| Icon | Status |
|------|--------|
| `+` | Completed successfully |
| `!` | Failed |
| `>` | Running |
| `-` | Skipped (overlap policy) |
| `?` | Unknown |

If `id-prefix` is provided, shows runs for that job only. Otherwise shows all runs.

## HTTP Webhook Triggers

When `BrokerWebhookEnabled` is set to `true`, the broker runs a FastAPI server that accepts external triggers.

### Triggering a run via HTTP

```bash
curl -X POST http://127.0.0.1:8321/api/trigger/http \
  -H "Authorization: Bearer YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise today'\''s news", "callback_url": "https://example.com/webhook"}'
```

### Checking run status

```bash
curl http://127.0.0.1:8321/api/runs/<run_id>
```

### Health check

```bash
curl http://127.0.0.1:8321/api/health
```

Returns job count, active runs, and available channels.

## Human-in-the-Loop (HITL)

Jobs can be configured to allow the agent to ask questions asynchronously via the originating channel.

### Enabling HITL

```bash
python -m micro_x_agent_loop --job add "research-task" "0 10 * * *" "Research X and write a report" \
  --hitl --hitl-timeout 600 --response-channel http --response-target https://example.com/webhook
```

When the agent calls `ask_user`, the question is:
1. Posted to the broker's HTTP API
2. Routed to the response channel (e.g., WhatsApp, HTTP callback)
3. The agent polls for an answer (every 3 seconds)
4. If no answer within the timeout, the agent receives a "no response" message and decides how to proceed

### Answering a question

External systems can answer via the API:

```bash
curl -X POST http://127.0.0.1:8321/api/runs/<run_id>/questions/<question_id>/answer \
  -H "Content-Type: application/json" \
  -d '{"answer": "Use option B"}'
```

### Requirements

- The webhook server must be enabled (`BrokerWebhookEnabled: true`)
- The job needs a response channel configured for question routing

## Retry Policy

Jobs can automatically retry on failure with exponential backoff.

```bash
python -m micro_x_agent_loop --job add "flaky-task" "0 */6 * * *" "Check API status" \
  --max-retries 3 --retry-delay 60
```

This retries up to 3 times with delays of 60s, 120s, 240s (exponential backoff). Retries are scheduled as queued runs and picked up by the scheduler.

## One-Shot Autonomous Mode

The broker dispatches jobs using the `--run` flag, which can also be used directly:

```bash
python -m micro_x_agent_loop --run "Your prompt here"
```

In this mode the agent:
- Executes the prompt without human interaction
- Has no `ask_user` tool (cannot ask questions)
- Skips mode analysis prompts and voice input
- Includes an autonomy directive in its system prompt
- Exits after completing the prompt

Optional flags:
- `--session <id>` — resume an existing session
- `--config <path>` — use a specific config file

## Configuration

Broker settings in `config.json`:

```json
{
  "BrokerEnabled": true,
  "BrokerWebhookEnabled": true,
  "BrokerHost": "127.0.0.1",
  "BrokerPort": 8321,
  "BrokerPollIntervalSeconds": 5,
  "BrokerMaxConcurrentRuns": 2,
  "BrokerRecoveryPolicy": "skip",
  "BrokerDatabase": ".micro_x/broker.db",
  "BrokerApiSecret": "${BROKER_API_SECRET}",
  "BrokerChannels": {
    "http": {
      "enabled": true,
      "auth_secret": "${BROKER_HTTP_SECRET}"
    }
  }
}
```

| Setting | Default | Purpose |
|---------|---------|---------|
| `BrokerEnabled` | `true` | Master switch for broker functionality |
| `BrokerWebhookEnabled` | `false` | Enable the FastAPI webhook server |
| `BrokerHost` | `127.0.0.1` | Webhook server bind address |
| `BrokerPort` | `8321` | Webhook server port |
| `BrokerPollIntervalSeconds` | `5` | How often the scheduler checks for due jobs |
| `BrokerMaxConcurrentRuns` | `2` | Maximum simultaneous agent subprocesses |
| `BrokerRecoveryPolicy` | `skip` | Missed-run recovery: `skip` or `run_once` |
| `BrokerDatabase` | `.micro_x/broker.db` | Path to the broker SQLite database |
| `BrokerApiSecret` | (none) | Bearer token for management endpoint auth |
| `BrokerChannels` | `{}` | Per-channel adapter configuration |

## Database

The broker uses a separate SQLite database (not the agent's `memory.db`). Default location: `.micro_x/broker.db`

Three tables:
- **`broker_jobs`** — job definitions, schedules, HITL/retry configuration
- **`broker_runs`** — execution history, response tracking, retry state
- **`broker_questions`** — HITL questions and answers (linked to runs)

The database is created automatically on first use.

## Troubleshooting

### Broker won't start: "already running"

A previous broker instance may not have shut down cleanly, leaving a stale PID file.

1. Check if the process is actually running: `ps -p <pid>` (Linux/macOS) or Task Manager (Windows)
2. If not running, the stale PID file will be cleaned up automatically on the next start attempt
3. If the PID file persists, delete `.micro_x/broker.pid` manually

### Job runs but produces no output

- Check run history: `--job runs <id>` — look for errors in the `error_text` field
- Test the prompt manually: `--job run-now <id>` to see output inline
- Verify the config file has the right MCP servers enabled for the task
- Check that API keys in `.env` are valid

### Job is skipped

The overlap policy `skip_if_running` prevents concurrent runs of the same job. If a previous run is still active (or was not properly cleaned up), subsequent triggers are skipped.

Check for stuck runs in the run history and investigate the underlying subprocess.

### Cron timing seems wrong

- Verify the timezone: `--job list` shows the configured timezone
- Cron expressions are evaluated in the job's timezone, then converted to UTC for the poll comparison
- The broker polls every `BrokerPollIntervalSeconds` — jobs may fire up to that many seconds late

## Related Documents

- [DESIGN-trigger-broker.md](../design/DESIGN-trigger-broker.md) — component design and data flow
- [ADR-018](../architecture/decisions/ADR-018-trigger-broker-subprocess-dispatch.md) — architectural decision record
- [PLAN-trigger-broker.md](../planning/PLAN-trigger-broker.md) — feature plan with phased rollout
