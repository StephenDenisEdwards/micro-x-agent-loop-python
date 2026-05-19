"""Eval harness — constructs the real Agent exactly as ``--run`` does
(``cli.dispatch.run_oneshot``), with the model pinned, a ``BufferedChannel``
injected, and clean shutdown. Assertion helpers read the channel's rich
``tool_records`` / ``text`` / ``turn_usages``.

Eval test files stay trivial:

    from tests.evals.harness import run_eval, assert_tool_used

    def test_x():
        r = run_eval("prompt", model="claude-haiku-4-5-20251001")
        assert_tool_used(r, "filesystem__bash")
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from micro_x_agent_loop.agent_channel import BufferedChannel
from micro_x_agent_loop.app_config import (
    load_json_config,
    parse_app_config,
    resolve_runtime_env,
)
from micro_x_agent_loop.bootstrap import bootstrap_runtime
from micro_x_agent_loop.cli.repl import shutdown_runtime

DEFAULT_CONFIG = "config-base.json"


@dataclass
class EvalResult:
    """What an eval can assert against. ``channel`` is the live
    ``BufferedChannel``; the helpers below wrap common assertions."""

    channel: BufferedChannel

    @property
    def text(self) -> str:
        return self.channel.text

    def started_tools(self) -> list[str]:
        """Tool names in the order they began executing."""
        return [r["tool_name"] for r in self.channel.tool_records]

    def records_for(self, tool_name: str) -> list[dict[str, Any]]:
        return [r for r in self.channel.tool_records if r["tool_name"] == tool_name]

    def total_cost_usd(self) -> float:
        return sum(float(u.get("estimated_cost_usd", 0.0)) for u in self.channel.turn_usages)


def _allow_fixture_dir(raw_config: dict[str, Any], extra_allowed_dirs: list[str]) -> None:
    """Append eval fixture dirs to the top-level ``Filesystem.AllowedDirs``
    block. Post-ADR-025 the filesystem tools are native and read their allowed
    roots from this block — *not* from an MCP server env var (F6 removed the
    filesystem MCP server entirely). ``parse_app_config`` lifts ``Filesystem``
    into ``app.filesystem_config`` and ``filesystem_roots_from_config`` splits
    ``AllowedDirs`` on ``os.pathsep`` to build the native ``PathPolicy``.

    Eval fixtures live in-repo outside the configured working dir, so the eval
    sandbox must opt them in. This is legitimate test-environment setup — we
    test tool *selection*, not the path-guard — and it flows through the same
    config the production agent uses, so the two stay consistent.
    """
    if not extra_allowed_dirs:
        return
    fs = raw_config["Filesystem"] = dict(raw_config.get("Filesystem", {}))
    existing = fs.get("AllowedDirs", "")
    parts = (
        [p for p in existing.split(os.pathsep) if p]
        if isinstance(existing, str) and existing
        else []
    )
    for d in extra_allowed_dirs:
        if d not in parts:
            parts.append(d)
    fs["AllowedDirs"] = os.pathsep.join(parts)


@contextlib.asynccontextmanager
async def eval_session(
    *,
    model: str,
    config_path: str = DEFAULT_CONFIG,
    extra_allowed_dirs: list[str] | None = None,
) -> AsyncIterator[tuple[Any, BufferedChannel]]:
    """Async context manager: yields ``(agent, channel)`` for one or more
    ``await agent.run(prompt)`` calls (multi-turn evals reuse the session),
    then tears the runtime down. Mirrors ``run_oneshot`` construction.

    The model is **pinned** by overwriting ``Model`` in the resolved config
    (no ``#Model`` indirection) so evals never drift when the project default
    model moves. ``extra_allowed_dirs`` opts eval fixture directories into the
    filesystem MCP allowed-roots policy.
    """
    raw_config, _ = load_json_config(config_path)
    raw_config = dict(raw_config)
    raw_config["Model"] = model  # pin — see docstring
    _allow_fixture_dir(raw_config, extra_allowed_dirs or [])

    app = parse_app_config(raw_config)
    env = resolve_runtime_env(app.provider_name)
    if not env.provider_api_key:
        raise RuntimeError(
            f"{env.provider_env_var} not set — eval needs live provider credentials"
        )

    channel = BufferedChannel()
    runtime = await bootstrap_runtime(
        app,
        env,
        autonomous=True,
        resolved_config=raw_config,
        channel_override=channel,
    )
    try:
        await runtime.agent.initialize_session()
        yield runtime.agent, channel
    finally:
        await shutdown_runtime(runtime)


async def _run_eval_async(
    prompts: list[str],
    *,
    model: str,
    config_path: str,
    extra_allowed_dirs: list[str] | None,
) -> EvalResult:
    async with eval_session(
        model=model, config_path=config_path, extra_allowed_dirs=extra_allowed_dirs
    ) as (agent, channel):
        for prompt in prompts:
            await agent.run(prompt)
    return EvalResult(channel=channel)


def run_eval(
    prompt: str | list[str],
    *,
    model: str,
    config_path: str = DEFAULT_CONFIG,
    extra_allowed_dirs: list[str] | None = None,
) -> EvalResult:
    """Sync entry point for eval test functions. Pass a list of prompts for
    a multi-turn eval (same session, sequential turns)."""
    prompts = [prompt] if isinstance(prompt, str) else list(prompt)
    return asyncio.run(
        _run_eval_async(
            prompts,
            model=model,
            config_path=config_path,
            extra_allowed_dirs=extra_allowed_dirs,
        )
    )


# --------------------------------------------------------------------------
# Assertion helpers. Tolerances per PLAN: regex (not exact) on args, allow
# bonus tool calls, cost ±30% headroom is the caller's to set.
# --------------------------------------------------------------------------


def assert_tool_used(
    result: EvalResult, tool_name: str, *, args_regex: str | None = None
) -> None:
    recs = result.records_for(tool_name)
    assert recs, (
        f"expected tool {tool_name!r} to be used; "
        f"tools used: {result.started_tools()}"
    )
    if args_regex is not None:
        pat = re.compile(args_regex)
        blobs = [str(r.get("tool_input")) for r in recs]
        assert any(pat.search(b) for b in blobs), (
            f"tool {tool_name!r} used but no call matched /{args_regex}/; "
            f"inputs seen: {blobs}"
        )


def assert_tool_not_used(result: EvalResult, tool_name: str) -> None:
    used = result.started_tools()
    assert tool_name not in used, (
        f"tool {tool_name!r} should NOT have been used; tools used: {used}"
    )


def assert_answer_matches(result: EvalResult, pattern: str) -> None:
    assert re.search(pattern, result.text), (
        f"answer did not match /{pattern}/; answer was:\n{result.text!r}"
    )


def assert_cost_under(result: EvalResult, usd: float) -> None:
    actual = result.total_cost_usd()
    assert actual < usd, f"cost ${actual:.4f} exceeded ceiling ${usd:.4f}"


def assert_tool_sequence(
    result: EvalResult, expected: list[str], *, allow_extra: bool = True
) -> None:
    """Assert ``expected`` appears as a subsequence (allow_extra=True) or an
    exact prefix-equal sequence (allow_extra=False) of started tools."""
    actual = result.started_tools()
    if allow_extra:
        it = iter(actual)
        missing = [name for name in expected if name not in it]
        assert not missing, (
            f"expected subsequence {expected} not found in {actual} "
            f"(missing/ordering: {missing})"
        )
    else:
        assert actual == expected, f"expected exactly {expected}, got {actual}"
