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
| `--tz <timezone>` | IANA timezone for cron evaluation (e.g. `Europe/London`). Defaults to local timezone |
| `--config <path>` | Config file override for this job's agent runs |
| `--session <id>` | Resume a specific session for each run (maintains conversation continuity) |

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
  "BrokerPollIntervalSeconds": 5,
  "BrokerMaxConcurrentRuns": 2,
  "BrokerDatabase": ".micro_x/broker.db"
}
```

| Setting | Default | Purpose |
|---------|---------|---------|
| `BrokerEnabled` | `true` | Master switch for broker functionality |
| `BrokerPollIntervalSeconds` | `5` | How often the scheduler checks for due jobs |
| `BrokerMaxConcurrentRuns` | `2` | Maximum simultaneous agent subprocesses |
| `BrokerDatabase` | `.micro_x/broker.db` | Path to the broker SQLite database |

## Database

The broker uses a separate SQLite database (not the agent's `memory.db`). Default location: `.micro_x/broker.db`

Two tables:
- **`broker_jobs`** — job definitions, schedules, and configuration
- **`broker_runs`** — execution history and results

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
