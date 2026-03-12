# Plan: CLI Status Bar (Per-Turn Cost Visibility)

## Status

**Planned** — Addresses Strategy 4 gaps in [cost-reduction-review.md](../review/cost-reduction-review.md).

## Problem

Per-turn cost metrics are fully tracked (`SessionAccumulator` in `metrics.py`) but only visible via the `/cost` slash command. Users have no passive awareness of spend as they interact. The review identifies two gaps:

1. **Per-turn cost not surfaced in the REPL** — users must actively check.
2. **No session budget enforcement** — no warnings or hard stops.

This plan addresses gap (1) by adding a persistent status bar to the CLI that displays a live cost summary after every turn.

## Design

### Approach: prompt_toolkit `bottom_toolbar`

`PromptSession` accepts a `bottom_toolbar` parameter — a callable that returns formatted text rendered below the input prompt. This is purpose-built for persistent status displays and requires no new dependencies.

### Visual Layout

```
assistant> Here are the results you asked for...

┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
 $0.043 │ T3 │ 2,450 in │ 1,200 out │ cache 82% │ sonnet-4
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
you> _
```

### Toolbar Content

A single compact line showing the most important metrics from `SessionAccumulator`:

| Field | Source | Example |
|-------|--------|---------|
| Total cost | `total_cost_usd` | `$0.043` |
| Turn count | `total_turns` | `T3` |
| Input tokens | `total_input_tokens` | `2,450 in` |
| Output tokens | `total_output_tokens` | `1,200 out` |
| Cache hit rate | `total_cache_read_tokens / (total_input_tokens + total_cache_read_tokens)` | `cache 82%` |
| Model | `model` (short name) | `sonnet-4` |

Cache hit rate is omitted when zero (e.g., OpenAI provider where cache tokens aren't reported separately).

### Lifecycle

| Phase | Status bar visible? | Notes |
|-------|-------------------|-------|
| Waiting for input | Yes | prompt_toolkit renders `bottom_toolbar` |
| LLM streaming | No | `rich.Live` takes over the terminal |
| Tool execution | No | Spinner displayed by `TerminalChannel` |
| Turn complete | Briefly no, then yes | Control returns to prompt_toolkit |

The toolbar is only visible while `prompt_toolkit` owns the terminal (i.e., during user input). This is acceptable because the metrics update between turns — users see the latest cost when deciding what to type next.

### Fallback (no prompt_toolkit)

When prompt_toolkit setup fails and the REPL falls back to `input()`, the status bar is not available. Instead, print a one-line cost summary after each turn completes (before the next `input()` call). This uses the same `format_toolbar()` data.

## Implementation

### Step 1 — Add `format_toolbar()` to `SessionAccumulator`

**File:** `src/micro_x_agent_loop/metrics.py`

Add a compact single-line formatter alongside the existing `format_summary()`:

```python
def format_toolbar(self) -> str:
    """One-line cost summary for the CLI status bar."""
    parts = [f"${self.total_cost_usd:.3f}"]
    parts.append(f"T{self.total_turns}")
    parts.append(f"{self.total_input_tokens:,} in")
    parts.append(f"{self.total_output_tokens:,} out")

    total_input = self.total_input_tokens + self.total_cache_read_tokens
    if total_input > 0 and self.total_cache_read_tokens > 0:
        hit_rate = self.total_cache_read_tokens / total_input * 100
        parts.append(f"cache {hit_rate:.0f}%")

    if self.model:
        short = _short_model_name(self.model)
        parts.append(short)

    return " │ ".join(parts)
```

Add a helper to shorten model names for display:

```python
def _short_model_name(model: str) -> str:
    """Shorten model ID for toolbar display."""
    # "claude-sonnet-4-20250514" → "sonnet-4"
    # "claude-haiku-4-5-20251001" → "haiku-4.5"
    # "gpt-4.1-mini" → "gpt-4.1-mini"
    for prefix in ("claude-", "anthropic/"):
        if model.startswith(prefix):
            model = model[len(prefix):]
    # Strip date suffix (-YYYYMMDD)
    if len(model) > 9 and model[-8:].isdigit() and model[-9] == "-":
        model = model[:-9]
    return model
```

### Step 2 — Wire toolbar into `PromptSession`

**File:** `src/micro_x_agent_loop/__main__.py`

Pass the accumulator's toolbar formatter as `bottom_toolbar` when creating the session:

```python
def _create_prompt_session(toolbar_fn=None):
    # ... existing code ...
    return PromptSession(
        message=HTML("<b>you&gt; </b>"),
        multiline=True,
        key_bindings=bindings,
        prompt_continuation=".... ",
        bottom_toolbar=toolbar_fn,
    )
```

The `toolbar_fn` callable is created in the REPL setup to capture the agent's accumulator:

```python
from prompt_toolkit.formatted_text import HTML

def _make_toolbar_fn(accumulator):
    def toolbar():
        text = accumulator.format_toolbar()
        return HTML(f"<b>{text}</b>")
    return toolbar
```

### Step 3 — Fallback cost line for basic input mode

**File:** `src/micro_x_agent_loop/__main__.py`

When `session is None` (prompt_toolkit unavailable), print the toolbar text after each turn:

```python
# After agent.run() completes, before next input() call:
if session is None:
    toolbar_text = accumulator.format_toolbar()
    if toolbar_text:
        print(f"  [{toolbar_text}]")
```

### Step 4 — Config toggle

**File:** `src/micro_x_agent_loop/agent_config.py`

Add a config field to enable/disable the status bar (enabled by default):

| Config key | Type | Default | Description |
|------------|------|---------|-------------|
| `StatusBarEnabled` | bool | `true` | Show cost/token status bar in CLI |

This allows users to disable it if it interferes with their terminal setup or if they prefer a clean prompt.

### Step 5 — Style the toolbar

Use prompt_toolkit's style system to give the toolbar a visually distinct appearance:

```python
from prompt_toolkit.styles import Style

toolbar_style = Style.from_dict({
    "bottom-toolbar": "bg:#333333 #aaaaaa",
})
```

Pass `style=toolbar_style` to `PromptSession`. The muted background distinguishes the toolbar from conversation content.

## Files Changed

| File | Change |
|------|--------|
| `src/micro_x_agent_loop/metrics.py` | Add `format_toolbar()`, `_short_model_name()` |
| `src/micro_x_agent_loop/__main__.py` | Wire `bottom_toolbar` into `PromptSession`, fallback print |
| `src/micro_x_agent_loop/agent_config.py` | Add `StatusBarEnabled` config field |
| `src/micro_x_agent_loop/app_config.py` | Parse `StatusBarEnabled` from config |
| `tests/test_metrics.py` | Tests for `format_toolbar()`, `_short_model_name()` |
| `tests/test_cost_reduction.py` | Config test for `StatusBarEnabled` |

## Testing

### Unit Tests

| Test | File | Validates |
|------|------|-----------|
| `test_format_toolbar_basic` | `tests/test_metrics.py` | Correct format with all fields populated |
| `test_format_toolbar_no_cache` | `tests/test_metrics.py` | Cache field omitted when zero |
| `test_format_toolbar_zero_turns` | `tests/test_metrics.py` | Clean output before any API calls |
| `test_short_model_name_anthropic` | `tests/test_metrics.py` | Strips `claude-` prefix and date suffix |
| `test_short_model_name_openai` | `tests/test_metrics.py` | Passes through OpenAI names unchanged |
| `test_status_bar_config_default` | `tests/test_cost_reduction.py` | Defaults to enabled |
| `test_status_bar_config_disabled` | `tests/test_cost_reduction.py` | Can be disabled |

### Manual Test Plan

To be created in `documentation/docs/testing/MANUAL-TEST-cli-status-bar.md` at implementation time.

| Scenario | Steps | Expected |
|----------|-------|----------|
| Toolbar visible during input | Start agent, send a prompt, observe after response | Toolbar line with cost/tokens appears below conversation, above `you>` |
| Toolbar updates each turn | Send 3 prompts, observe toolbar after each | Cost and token counts increment |
| Cache rate shown for Anthropic | Use default Anthropic config, send 2+ prompts | `cache XX%` appears after turn 2 |
| Cache rate hidden for OpenAI | Use OpenAI config | No `cache` field in toolbar |
| Disabled via config | Set `StatusBarEnabled: false` | No toolbar, plain `you>` prompt |
| Fallback mode | Force prompt_toolkit failure (rename package) | Cost line printed as `[...]` after each turn |

## Scope Boundaries

**In scope:**
- Passive cost display in the CLI status bar
- Config toggle

**Out of scope (separate work):**
- Session budget caps (`SessionBudgetUSD` with warn/stop) — separate plan
- Per-turn cost delta display (showing cost of just the last turn) — future enhancement
- Status bar in `--server` mode (WebSocket clients render their own UI)
- Status bar in `--run` autonomous mode (no interactive prompt)

## Dependencies

- None — uses existing `SessionAccumulator` data and existing `prompt_toolkit` dependency.

## Risks

| Risk | Mitigation |
|------|------------|
| Terminal compatibility — some terminals may not render `bottom_toolbar` correctly | Config toggle to disable; falls back gracefully |
| prompt_toolkit version differences | Already handled: REPL falls back to `input()` if setup fails |
| Toolbar flicker during rapid tool calls | Not an issue — toolbar only renders during prompt_toolkit input phase |
| Rich.Live conflict | No conflict — `bottom_toolbar` is only active when prompt_toolkit owns the terminal, not during `rich.Live` streaming |
