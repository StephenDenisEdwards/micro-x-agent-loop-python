# Trigger Broker — Manual Test Plan

Step-by-step walkthrough of every broker feature. Run these from the project root directory.

> **Prerequisites**
> - Python 3.11+ with the agent installed (`pip install -e .`)
> - A working `config.json` with at least one LLM provider
> - `.env` with valid API keys
> - `croniter` installed (`pip install croniter`)

> **Cleanup between test runs**
> To start fresh, delete the broker database:
> ```bash
> rm -f .micro_x/broker.db
> ```

---

## 1. One-Shot Autonomous Mode (`--run`)

The foundation — the broker dispatches jobs as `--run` subprocesses, so this must work first.

### Test 1.1: Basic one-shot run

```bash
python -m micro_x_agent_loop --run "What is 2 + 2? Reply with just the number."
```

**Expected:** Agent runs the prompt without interactive input, prints the answer, and exits. No `you>` prompt appears. Exit code 0.

### Test 1.2: One-shot with session continuity

```bash
# First run — creates context
python -m micro_x_agent_loop --run "Remember that my favourite colour is blue." --session test-broker-session

# Second run — should recall context
python -m micro_x_agent_loop --run "What is my favourite colour?" --session test-broker-session
```

**Expected:** Second run recalls "blue" from the first run's session.

### Test 1.3: One-shot with config override

```bash
python -m micro_x_agent_loop --run "Say hello" --config config-standard.json
```

**Expected:** Uses the specified config file instead of the default.

---

## 2. Job Management (`--job`)

### Test 2.1: Add a simple job

```bash
python -m micro_x_agent_loop --job add "test-job" "*/5 * * * *" "What time is it? Reply briefly."
```

**Expected output (similar to):**
```
Created job: test-job (id=a1b2c3d4)
  Cron: */5 * * * * (UTC)
  Prompt: What time is it? Reply briefly.
```

Note the job ID prefix (first 8 chars) — you'll use it in later tests.

### Test 2.2: Add a job with timezone

```bash
python -m micro_x_agent_loop --job add "morning-job" "0 9 * * *" "Good morning summary" --tz "Australia/Sydney"
```

**Expected:** Output shows `(Australia/Sydney)` next to the cron expression.

### Test 2.3: Add a job with all options

```bash
python -m micro_x_agent_loop --job add "full-options" "0 */6 * * *" "Check system status" \
  --tz "Europe/London" \
  --hitl --hitl-timeout 120 \
  --max-retries 3 --retry-delay 30 \
  --response-channel http --response-target "https://example.com/callback"
```

**Expected:** Output confirms all settings:
```
Created job: full-options (id=...)
  Cron: 0 */6 * * * (Europe/London)
  Prompt: Check system status
  Response: http -> https://example.com/callback
  HITL: enabled (timeout=120s)
  Retries: max=3, delay=30s (exponential backoff)
```

### Test 2.4: List jobs

```bash
python -m micro_x_agent_loop --job list
```

**Expected:** Shows all jobs created in 2.1–2.3, each with:
- ID prefix, enabled/disabled status, name
- Cron expression and timezone
- Prompt preview (truncated at 60 chars)
- HITL and retry info where configured
- Response channel where configured

### Test 2.5: Disable a job

```bash
python -m micro_x_agent_loop --job disable <id-prefix-from-2.1>
```

**Expected:** `Disabled job: test-job (a1b2c3d4)`

Verify with `--job list` — the job should show `[disabled]`.

### Test 2.6: Enable a job

```bash
python -m micro_x_agent_loop --job enable <id-prefix-from-2.1>
```

**Expected:** `Enabled job: test-job (a1b2c3d4)`

Verify with `--job list` — the job should show `[enabled]`.

### Test 2.7: Run a job manually (run-now)

```bash
python -m micro_x_agent_loop --job run-now <id-prefix-from-2.1>
```

**Expected:**
- Prints `Running job: test-job...`
- Agent runs the prompt in the foreground (you see output inline)
- Prints `Run completed successfully.` with the output
- No broker daemon needed — this runs the subprocess directly

### Test 2.8: View run history

```bash
python -m micro_x_agent_loop --job runs
```

**Expected:** Shows at least one run (from test 2.7):
```
  [+] a1b2c3d4  completed   2026-03-07T...  manual
      Result: <first line of output>
```

Filter by job:
```bash
python -m micro_x_agent_loop --job runs <id-prefix-from-2.1>
```

**Expected:** Shows only runs for that specific job.

### Test 2.9: Remove a job

```bash
python -m micro_x_agent_loop --job remove <id-prefix-from-2.2>
```

**Expected:** `Removed job: morning-job (...)`. Verify with `--job list` — only 2 jobs remain.

### Test 2.10: Invalid cron expression

```bash
python -m micro_x_agent_loop --job add "bad-cron" "not-a-cron" "test"
```

**Expected:** `Invalid cron expression: not-a-cron`

### Test 2.11: Ambiguous ID prefix

If you have two jobs whose IDs start with the same character:
```bash
python -m micro_x_agent_loop --job remove a
```

**Expected:** Shows `Ambiguous prefix 'a' matches N jobs:` and lists the matches.

### Test 2.12: Missing arguments

```bash
python -m micro_x_agent_loop --job add
python -m micro_x_agent_loop --job remove
python -m micro_x_agent_loop --job run-now
```

**Expected:** Each prints a usage message with the correct syntax.

---

## 3. Broker Daemon (`--broker`)

### Test 3.1: Broker status (not running)

```bash
python -m micro_x_agent_loop --broker status
```

**Expected:** `Broker is not running.`

### Test 3.2: Broker stop (not running)

```bash
python -m micro_x_agent_loop --broker stop
```

**Expected:** `Broker is not running.`

### Test 3.3: Start the broker

First, ensure you have at least one enabled job with a near-future schedule:

```bash
python -m micro_x_agent_loop --job add "every-minute" "* * * * *" "Say the current UTC time in one sentence."
```

Now start the broker (runs in foreground — use a separate terminal for other commands):

```bash
python -m micro_x_agent_loop --broker start
```

**Expected:**
- Logs: `Broker service starting (db=.micro_x/broker.db, pid=XXXXX)`
- Within ~60 seconds, you should see a run dispatched:
  - `Dispatching cron run for job every-minute...` (or similar log)
  - Agent subprocess output in the logs
  - `Run XXXXXXXX completed successfully`

Leave the broker running for tests 3.4–3.7.

### Test 3.4: Broker status (running)

In a **second terminal**:

```bash
python -m micro_x_agent_loop --broker status
```

**Expected:**
```
Broker is running (PID XXXXX)
Jobs: N total, M enabled
```

### Test 3.5: Observe scheduled execution

Watch the broker terminal. The `every-minute` job should fire once per minute. After 2–3 minutes, verify the run history:

```bash
python -m micro_x_agent_loop --job runs <every-minute-id>
```

**Expected:** Multiple `[+] completed` runs, each ~1 minute apart.

### Test 3.6: Overlap protection (skip_if_running)

Add a slow job to test overlap prevention:

```bash
python -m micro_x_agent_loop --job add "slow-job" "* * * * *" "Count slowly from 1 to 50, one number per line."
```

**Expected:** The broker should dispatch this job, but skip subsequent triggers while the first run is still active. Look for `Skipping job slow-job: already running` in the logs.

### Test 3.7: Concurrent run limit

The default `BrokerMaxConcurrentRuns` is 2. With `every-minute` and `slow-job` both running every minute, the broker should cap at 2 simultaneous runs. Watch the logs for capacity messages.

### Test 3.8: Stop the broker

In the second terminal:

```bash
python -m micro_x_agent_loop --broker stop
```

**Expected:**
- Second terminal prints `Broker stopped.`
- First terminal shows graceful shutdown:
  - `Waiting for N in-flight run(s)...` (if any are active)
  - `Broker service stopped`

### Test 3.9: Stale PID file recovery

Simulate a stale PID file:

```bash
echo 99999 > .micro_x/broker.pid
python -m micro_x_agent_loop --broker start
```

**Expected:** Broker detects the stale PID (`Removing stale PID file`), cleans it up, and starts normally. (Press Ctrl+C to stop.)

### Test 3.10: Double-start prevention

Start the broker in one terminal, then try to start it again:

```bash
# Terminal 1
python -m micro_x_agent_loop --broker start

# Terminal 2
python -m micro_x_agent_loop --broker start
```

**Expected:** Terminal 2 shows `Error: Broker is already running (PID file exists)`.

---

## 4. Webhook Server

Requires `BrokerWebhookEnabled: true` in your config. Add this to your `config.json`:

```json
{
  "BrokerWebhookEnabled": true,
  "BrokerPort": 8321,
  "BrokerChannels": {
    "http": { "enabled": true }
  }
}
```

Start the broker:
```bash
python -m micro_x_agent_loop --broker start
```

**Expected:** Logs include `Webhook server enabled on 127.0.0.1:8321`.

### Test 4.1: Health check

```bash
curl http://127.0.0.1:8321/api/health
```

**Expected:**
```json
{
  "status": "ok",
  "jobs_total": N,
  "jobs_enabled": M,
  "active_runs": 0,
  "channels": ["log", "http"]
}
```

### Test 4.2: List jobs via API

```bash
curl http://127.0.0.1:8321/api/jobs
```

**Expected:** JSON array of all jobs (same data as `--job list`).

### Test 4.3: Trigger a run via HTTP webhook

```bash
curl -X POST http://127.0.0.1:8321/api/trigger/http \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"What is the capital of France? Reply in one word.\"}"
```

**Expected:**
```json
{
  "status": "dispatched",
  "run_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

The broker logs should show the run being dispatched and completed.

### Test 4.4: Check run status via API

Using the `run_id` from test 4.3:

```bash
curl http://127.0.0.1:8321/api/runs/<run_id>
```

**Expected:** JSON with run details including `status`, `started_at`, `result_summary`, etc. If checked quickly, status may be `running`; after completion, `completed`.

### Test 4.5: Unknown channel

```bash
curl -X POST http://127.0.0.1:8321/api/trigger/unknown \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"test\"}"
```

**Expected:** 404 with `{"error": "Unknown channel: unknown"}`

### Test 4.6: Empty prompt

```bash
curl -X POST http://127.0.0.1:8321/api/trigger/http \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"\"}"
```

**Expected:** The webhook returns `{"status": "ignored"}` (empty prompt parsed as None by HttpAdapter).

### Test 4.7: Invalid JSON

```bash
curl -X POST http://127.0.0.1:8321/api/trigger/http \
  -H "Content-Type: application/json" \
  -d "not json"
```

**Expected:** 400 with `{"error": "Invalid JSON"}`

### Test 4.8: Run not found

```bash
curl http://127.0.0.1:8321/api/runs/nonexistent-id
```

**Expected:** 404 with `{"error": "Run not found"}`

### Test 4.9: Capacity limit via webhook

Set `BrokerMaxConcurrentRuns` to 1 in config, restart the broker, then fire two triggers rapidly:

```bash
curl -X POST http://127.0.0.1:8321/api/trigger/http \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"Count from 1 to 20 slowly.\"}"

# Immediately:
curl -X POST http://127.0.0.1:8321/api/trigger/http \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"Another task\"}"
```

**Expected:** First returns `dispatched`. Second returns 503 with `{"error": "At capacity, try again later"}`.

---

## 5. Bearer Token Auth

Add `BrokerApiSecret` to config:

```json
{
  "BrokerWebhookEnabled": true,
  "BrokerApiSecret": "my-test-secret"
}
```

Restart the broker.

### Test 5.1: Health check (no auth required)

```bash
curl http://127.0.0.1:8321/api/health
```

**Expected:** 200 OK — health endpoint is exempt from auth.

### Test 5.2: Authenticated request

```bash
curl http://127.0.0.1:8321/api/jobs \
  -H "Authorization: Bearer my-test-secret"
```

**Expected:** 200 OK with job list.

### Test 5.3: Missing auth

```bash
curl http://127.0.0.1:8321/api/jobs
```

**Expected:** 401 with `{"error": "Unauthorized"}`

### Test 5.4: Wrong token

```bash
curl http://127.0.0.1:8321/api/jobs \
  -H "Authorization: Bearer wrong-secret"
```

**Expected:** 401 with `{"error": "Unauthorized"}`

---

## 6. Human-in-the-Loop (HITL)

Requires the webhook server running. This tests the full HITL flow where an agent subprocess asks a question and an external client answers.

### Test 6.1: Create a HITL-enabled job and trigger it

```bash
python -m micro_x_agent_loop --job add "hitl-test" "0 0 1 1 *" \
  "Ask the user what format they want the report in, then say you would create it in that format." \
  --hitl --hitl-timeout 120
```

Trigger it manually (while broker with webhooks is running):

```bash
curl -X POST http://127.0.0.1:8321/api/trigger/http \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"Ask the user what format they want the report in, then say you would create it in that format.\"}"
```

Note the `run_id` from the response.

### Test 6.2: Check for pending questions

Poll for questions (the agent subprocess may take a few seconds to reach the ask_user call):

```bash
curl http://127.0.0.1:8321/api/runs/<run_id>/questions
```

**Expected:** When the agent asks a question:
```json
{
  "pending_question": {
    "id": "qid-xxx",
    "run_id": "...",
    "question_text": "What format would you like the report in?",
    "status": "pending",
    ...
  }
}
```

If the agent hasn't asked yet, `pending_question` will be `null`.

### Test 6.3: Answer a question

```bash
curl -X POST http://127.0.0.1:8321/api/runs/<run_id>/questions/<question_id>/answer \
  -H "Content-Type: application/json" \
  -d "{\"answer\": \"PDF format please\"}"
```

**Expected:** `{"status": "answered"}`

The agent subprocess should receive the answer and continue.

### Test 6.4: Question timeout

Create another HITL run but do NOT answer the question. Wait for the timeout:

```bash
python -m micro_x_agent_loop --job add "hitl-timeout-test" "0 0 1 1 *" \
  "Ask the user for their name, then greet them." \
  --hitl --hitl-timeout 15
```

Trigger it and let the question time out (15 seconds). The agent should receive a "no response" message and decide how to proceed autonomously.

### Test 6.5: Double-answer prevention

After answering a question (test 6.3), try answering again:

```bash
curl -X POST http://127.0.0.1:8321/api/runs/<run_id>/questions/<question_id>/answer \
  -H "Content-Type: application/json" \
  -d "{\"answer\": \"Another answer\"}"
```

**Expected:** 409 with `{"error": "Question is already answered"}`

---

## 7. Retry Policy

### Test 7.1: Job with retries (simulated failure)

Create a job that will fail (e.g., referencing a non-existent config):

```bash
python -m micro_x_agent_loop --job add "retry-test" "0 0 1 1 *" "test prompt" \
  --config "nonexistent-config.json" \
  --max-retries 3 --retry-delay 10
```

Trigger it:
```bash
python -m micro_x_agent_loop --job run-now <retry-test-id>
```

**Expected:**
- First run fails (config not found)
- Check `--job runs <id>` — should show the failed run

When triggered via the broker (not `run-now`), failed runs with retries configured will automatically schedule retry runs with exponential backoff (10s, 20s, 40s).

---

## 8. Missed-Run Recovery

Tests the broker's behaviour when it starts up and finds jobs whose `next_run_at` is in the past.

### Test 8.1: Skip policy (default)

```bash
# Add a job, then manually set its next_run_at to the past
python -m micro_x_agent_loop --job add "recovery-skip" "0 9 * * *" "test prompt"
```

Start the broker with `BrokerRecoveryPolicy: "skip"` (default). The broker should advance the schedule to the next future occurrence without running the missed job. Check the logs for recovery messages.

### Test 8.2: Run-once policy

Set `BrokerRecoveryPolicy: "run_once"` in config. Add a job and ensure its `next_run_at` is in the past. Start the broker.

**Expected:** The broker fires the missed job once, then advances the schedule.

---

## 9. Help and Error Handling

### Test 9.1: Broker help

```bash
python -m micro_x_agent_loop --broker
```

**Expected:** Lists available broker subcommands (start, stop, status).

### Test 9.2: Job help

```bash
python -m micro_x_agent_loop --job
```

**Expected:** Lists available job subcommands with usage syntax.

### Test 9.3: Unknown broker subcommand

```bash
python -m micro_x_agent_loop --broker restart
```

**Expected:** `Unknown broker command: restart` followed by help text.

### Test 9.4: Unknown job subcommand

```bash
python -m micro_x_agent_loop --job pause foo
```

**Expected:** `Unknown job command: pause` followed by help text.

---

## 10. Database Inspection (Optional)

For troubleshooting or verifying state, you can query the SQLite database directly:

```bash
sqlite3 .micro_x/broker.db
```

### Useful queries

```sql
-- All jobs
SELECT id, name, enabled, cron_expr, timezone, next_run_at FROM broker_jobs;

-- Recent runs
SELECT id, job_id, status, trigger_source, started_at, error_text FROM broker_runs ORDER BY started_at DESC LIMIT 10;

-- HITL questions
SELECT id, run_id, question_text, status, answer FROM broker_questions;

-- Job columns (inspect schema)
.schema broker_jobs
.schema broker_runs
.schema broker_questions
```

---

## Cleanup

After testing, remove all test jobs and the database:

```bash
rm -f .micro_x/broker.db .micro_x/broker.pid
```

Remove any config changes you made for testing (`BrokerWebhookEnabled`, `BrokerApiSecret`, etc.).

---

## Test Summary Checklist

| # | Feature | Status |
|---|---------|--------|
| 1.1 | Basic one-shot run | |
| 1.2 | One-shot with session | |
| 1.3 | One-shot with config override | |
| 2.1 | Add simple job | |
| 2.2 | Add job with timezone | |
| 2.3 | Add job with all options | |
| 2.4 | List jobs | |
| 2.5 | Disable job | |
| 2.6 | Enable job | |
| 2.7 | Run job manually | |
| 2.8 | View run history | |
| 2.9 | Remove job | |
| 2.10 | Invalid cron expression | |
| 2.11 | Ambiguous ID prefix | |
| 2.12 | Missing arguments | |
| 3.1 | Broker status (not running) | |
| 3.2 | Broker stop (not running) | |
| 3.3 | Start broker + cron execution | |
| 3.4 | Broker status (running) | |
| 3.5 | Observe scheduled execution | |
| 3.6 | Overlap protection | |
| 3.7 | Concurrent run limit | |
| 3.8 | Stop broker | |
| 3.9 | Stale PID file recovery | |
| 3.10 | Double-start prevention | |
| 4.1 | Health check | |
| 4.2 | List jobs via API | |
| 4.3 | Trigger run via HTTP | |
| 4.4 | Check run status via API | |
| 4.5 | Unknown channel | |
| 4.6 | Empty prompt | |
| 4.7 | Invalid JSON | |
| 4.8 | Run not found | |
| 4.9 | Capacity limit via webhook | |
| 5.1 | Health (no auth required) | |
| 5.2 | Authenticated request | |
| 5.3 | Missing auth | |
| 5.4 | Wrong token | |
| 6.1 | HITL job trigger | |
| 6.2 | Poll for pending questions | |
| 6.3 | Answer a question | |
| 6.4 | Question timeout | |
| 6.5 | Double-answer prevention | |
| 7.1 | Retry on failure | |
| 8.1 | Recovery: skip policy | |
| 8.2 | Recovery: run_once policy | |
| 9.1 | Broker help | |
| 9.2 | Job help | |
| 9.3 | Unknown broker subcommand | |
| 9.4 | Unknown job subcommand | |
