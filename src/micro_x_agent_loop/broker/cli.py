"""CLI commands for broker and job management."""

from __future__ import annotations

from micro_x_agent_loop.broker.runner import run_agent
from micro_x_agent_loop.broker.service import BrokerService
from micro_x_agent_loop.broker.store import BrokerStore

_DEFAULT_DB_PATH = ".micro_x/broker.db"


def _get_store(db_path: str = _DEFAULT_DB_PATH) -> BrokerStore:
    return BrokerStore(db_path)


async def handle_broker_command(args: list[str], config: dict | None = None) -> None:
    """Handle --broker <subcommand> CLI arguments."""
    if not args:
        _print_broker_help()
        return

    sub = args[0]
    broker_config = config or {}
    db_path = broker_config.get("BrokerDatabase", _DEFAULT_DB_PATH)
    poll_interval = int(broker_config.get("BrokerPollIntervalSeconds", 5))
    max_concurrent = int(broker_config.get("BrokerMaxConcurrentRuns", 2))
    webhook_enabled = bool(broker_config.get("BrokerWebhookEnabled", False))
    webhook_host = str(broker_config.get("BrokerHost", "127.0.0.1"))
    webhook_port = int(broker_config.get("BrokerPort", 8321))
    channels_config = broker_config.get("BrokerChannels", {})
    recovery_policy = str(broker_config.get("BrokerRecoveryPolicy", "skip"))
    api_secret = broker_config.get("BrokerApiSecret") or None

    if sub == "start":
        service = BrokerService(
            db_path=db_path,
            poll_interval=poll_interval,
            max_concurrent_runs=max_concurrent,
            webhook_enabled=webhook_enabled,
            webhook_host=webhook_host,
            webhook_port=webhook_port,
            channels_config=channels_config,
            recovery_policy=recovery_policy,
            api_secret=api_secret,
        )
        try:
            await service.start()
        except RuntimeError as ex:
            print(f"Error: {ex}")
            return

    elif sub == "stop":
        if BrokerService.stop_broker():
            print("Broker stopped.")
        else:
            print("Broker is not running.")

    elif sub == "status":
        pid = BrokerService.read_pid()
        if pid:
            print(f"Broker is running (PID {pid})")
            store = _get_store(db_path)
            jobs = store.list_jobs()
            enabled = sum(1 for j in jobs if j["enabled"])
            print(f"Jobs: {len(jobs)} total, {enabled} enabled")
            store.close()
        else:
            print("Broker is not running.")

    else:
        print(f"Unknown broker command: {sub}")
        _print_broker_help()


async def handle_job_command(args: list[str], config: dict | None = None) -> None:
    """Handle --job <subcommand> CLI arguments."""
    if not args:
        _print_job_help()
        return

    sub = args[0]
    rest = args[1:]
    broker_config = config or {}
    db_path = broker_config.get("BrokerDatabase", _DEFAULT_DB_PATH)
    store = _get_store(db_path)

    try:
        if sub == "add":
            _job_add(store, rest)
        elif sub == "list":
            _job_list(store)
        elif sub == "remove":
            _job_remove(store, rest)
        elif sub == "enable":
            _job_enable(store, rest, enabled=True)
        elif sub == "disable":
            _job_enable(store, rest, enabled=False)
        elif sub == "run-now":
            await _job_run_now(store, rest)
        elif sub == "runs":
            _job_runs(store, rest)
        else:
            print(f"Unknown job command: {sub}")
            _print_job_help()
    finally:
        store.close()


def _job_add(store: BrokerStore, args: list[str]) -> None:
    """Add a new scheduled job."""
    if len(args) < 3:
        print(
            "Usage: --job add <name> <cron_expr> <prompt> "
            "[--tz TZ] [--config path] [--session id] "
            "[--response-channel channel] [--response-target target] "
            "[--hitl] [--hitl-timeout secs] [--max-retries N] [--retry-delay secs]"
        )
        return

    name = args[0]
    cron_expr = args[1]
    prompt = args[2]

    # Parse optional flags
    tz = "UTC"
    config_profile = None
    session_id = None
    response_channel = "log"
    response_target = None
    hitl_enabled = False
    hitl_timeout = 300
    max_retries = 0
    retry_delay = 60
    i = 3
    while i < len(args):
        if args[i] == "--tz" and i + 1 < len(args):
            tz = args[i + 1]
            i += 2
        elif args[i] == "--config" and i + 1 < len(args):
            config_profile = args[i + 1]
            i += 2
        elif args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--response-channel" and i + 1 < len(args):
            response_channel = args[i + 1]
            i += 2
        elif args[i] == "--response-target" and i + 1 < len(args):
            response_target = args[i + 1]
            i += 2
        elif args[i] == "--hitl":
            hitl_enabled = True
            i += 1
        elif args[i] == "--hitl-timeout" and i + 1 < len(args):
            hitl_timeout = int(args[i + 1])
            i += 2
        elif args[i] == "--max-retries" and i + 1 < len(args):
            max_retries = int(args[i + 1])
            i += 2
        elif args[i] == "--retry-delay" and i + 1 < len(args):
            retry_delay = int(args[i + 1])
            i += 2
        else:
            i += 1

    try:
        from croniter import croniter  # type: ignore[import-untyped]
        if not croniter.is_valid(cron_expr):
            print(f"Invalid cron expression: {cron_expr}")
            return
    except ImportError:
        pass

    job = store.create_job(
        name=name,
        cron_expr=cron_expr,
        prompt_template=prompt,
        timezone=tz,
        config_profile=config_profile,
        session_id=session_id,
        hitl_enabled=hitl_enabled,
        hitl_timeout_seconds=hitl_timeout,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay,
    )

    # Set response routing if specified
    if response_channel != "log" or response_target:
        store.update_job(
            job["id"],
            response_channel=response_channel,
            **({"response_target": response_target} if response_target else {}),
        )

    print(f"Created job: {job['name']} (id={job['id'][:8]})")
    print(f"  Cron: {cron_expr} ({tz})")
    print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    if response_channel != "log":
        print(f"  Response: {response_channel} -> {response_target or '(sender)'}")
    if hitl_enabled:
        print(f"  HITL: enabled (timeout={hitl_timeout}s)")
    if max_retries > 0:
        print(f"  Retries: max={max_retries}, delay={retry_delay}s (exponential backoff)")


def _job_list(store: BrokerStore) -> None:
    """List all jobs."""
    jobs = store.list_jobs()
    if not jobs:
        print("No jobs configured.")
        return

    for job in jobs:
        status = "enabled" if job["enabled"] else "disabled"
        print(f"  {job['id'][:8]}  [{status}]  {job['name']}")
        print(f"           Cron: {job['cron_expr']} ({job.get('timezone', 'UTC')})")
        prompt_preview = job["prompt_template"][:60]
        print(f"           Prompt: {prompt_preview}{'...' if len(job['prompt_template']) > 60 else ''}")
        resp_ch = job.get("response_channel", "log")
        if resp_ch != "log":
            print(f"           Response: {resp_ch} -> {job.get('response_target', '(sender)')}")
        if job.get("hitl_enabled"):
            print(f"           HITL: timeout={job.get('hitl_timeout_seconds', 300)}s")
        if job.get("max_retries", 0) > 0:
            print(f"           Retries: max={job['max_retries']}, delay={job.get('retry_delay_seconds', 60)}s")
        if job.get("next_run_at"):
            print(f"           Next: {job['next_run_at']}")
        if job.get("last_run_at"):
            print(f"           Last: {job['last_run_at']}")
        print()


def _job_remove(store: BrokerStore, args: list[str]) -> None:
    """Remove a job by ID prefix."""
    if not args:
        print("Usage: --job remove <job_id_prefix>")
        return

    prefix = args[0]
    jobs = store.list_jobs()
    matches = [j for j in jobs if j["id"].startswith(prefix)]

    if not matches:
        print(f"No job found matching: {prefix}")
    elif len(matches) > 1:
        print(f"Ambiguous prefix '{prefix}' matches {len(matches)} jobs:")
        for j in matches:
            print(f"  {j['id'][:8]}  {j['name']}")
    else:
        job = matches[0]
        store.delete_job(job["id"])
        print(f"Removed job: {job['name']} ({job['id'][:8]})")


def _job_enable(store: BrokerStore, args: list[str], *, enabled: bool) -> None:
    """Enable or disable a job by ID prefix."""
    if not args:
        action = "enable" if enabled else "disable"
        print(f"Usage: --job {action} <job_id_prefix>")
        return

    prefix = args[0]
    jobs = store.list_jobs()
    matches = [j for j in jobs if j["id"].startswith(prefix)]

    if not matches:
        print(f"No job found matching: {prefix}")
    elif len(matches) > 1:
        print(f"Ambiguous prefix '{prefix}' matches {len(matches)} jobs")
    else:
        job = matches[0]
        store.update_job(job["id"], enabled=1 if enabled else 0)
        action = "Enabled" if enabled else "Disabled"
        print(f"{action} job: {job['name']} ({job['id'][:8]})")


async def _job_run_now(store: BrokerStore, args: list[str]) -> None:
    """Manually trigger a job run immediately."""
    if not args:
        print("Usage: --job run-now <job_id_prefix>")
        return

    prefix = args[0]
    jobs = store.list_jobs()
    matches = [j for j in jobs if j["id"].startswith(prefix)]

    if not matches:
        print(f"No job found matching: {prefix}")
        return
    if len(matches) > 1:
        print(f"Ambiguous prefix '{prefix}' matches {len(matches)} jobs")
        return

    job = matches[0]
    print(f"Running job: {job['name']}...")

    run_id = store.create_run(
        job_id=job["id"],
        trigger_source="manual",
        prompt=job["prompt_template"],
        session_id=job.get("session_id"),
    )

    result = await run_agent(
        prompt=job["prompt_template"],
        config=job.get("config_profile"),
        session_id=job.get("session_id"),
        timeout_seconds=job.get("timeout_seconds"),
    )

    if result.ok:
        store.complete_run(run_id, result_summary=result.summary)
        print("Run completed successfully.")
        if result.stdout.strip():
            print(f"\n--- Output ---\n{result.stdout.strip()}\n--- End ---")
    else:
        error = result.stderr or f"Exit code {result.exit_code}"
        store.fail_run(run_id, error_text=error)
        print(f"Run failed: {error}")


def _job_runs(store: BrokerStore, args: list[str]) -> None:
    """Show run history for a job (or all jobs)."""
    job_id = None
    if args:
        prefix = args[0]
        jobs = store.list_jobs()
        matches = [j for j in jobs if j["id"].startswith(prefix)]
        if len(matches) == 1:
            job_id = matches[0]["id"]
        elif len(matches) > 1:
            print(f"Ambiguous prefix '{prefix}'")
            return

    runs = store.list_runs(job_id=job_id)
    if not runs:
        print("No runs found.")
        return

    for run in runs:
        status_icon = {
            "completed": "+",
            "failed": "!",
            "running": ">",
            "skipped": "-",
            "queued": ".",
        }.get(run["status"], "?")
        started = run.get("started_at", "?")[:19]
        resp = ""
        if run.get("response_sent"):
            resp = f" [sent:{run.get('response_channel', '')}]"
        elif run.get("response_error"):
            resp = " [resp-err]"
        print(f"  [{status_icon}] {run['id'][:8]}  {run['status']:10}  {started}  {run['trigger_source']}{resp}")
        if run.get("error_text"):
            print(f"      Error: {run['error_text'][:100]}")
        if run.get("result_summary"):
            summary_line = run["result_summary"].split("\n")[0][:80]
            print(f"      Result: {summary_line}")


def _print_broker_help() -> None:
    print("Broker commands:")
    print("  --broker start    Start the broker daemon")
    print("  --broker stop     Stop the running broker")
    print("  --broker status   Show broker status")


def _print_job_help() -> None:
    print("Job commands:")
    print("  --job add <name> <cron> <prompt> [--tz TZ] [--config path] [--session id]")
    print("                                   [--response-channel ch] [--response-target target]")
    print("                                   [--hitl] [--hitl-timeout secs]")
    print("                                   [--max-retries N] [--retry-delay secs]")
    print("  --job list        List all jobs")
    print("  --job remove <id> Remove a job")
    print("  --job enable <id> Enable a job")
    print("  --job disable <id> Disable a job")
    print("  --job run-now <id> Run a job immediately")
    print("  --job runs [id]   Show run history")
