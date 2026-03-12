# Plan: Externalise Pricing Data

## Status

**Completed** — Implemented 2026-03-12. Option A (config.json `Pricing` key).

## Problem

Model pricing is hardcoded in `src/micro_x_agent_loop/usage.py` as a `PRICING` dict. Every time a provider ships a new model or adjusts pricing, a code change + release is required. This creates unnecessary friction:

1. **New models return $0 cost** — `estimate_cost()` silently returns zero for unknown models, making cost tracking inaccurate until a developer adds the entry.
2. **Stale prices** — if a provider changes pricing (e.g. Anthropic's periodic price drops), the hardcoded values drift from reality with no indication.
3. **No user override** — users running fine-tuned models, custom deployments, or providers with negotiated pricing cannot correct the rates.
4. **Maintenance burden** — the PRICING dict has grown to 13 entries across 2 providers and will keep growing (Gemini, Mistral, local models, etc.).

## Goals

- Pricing data lives outside Python source code, loadable at startup.
- Existing hardcoded prices become defaults (zero-config still works).
- Users can override or extend pricing without code changes.
- Unknown-model cost reporting is visible (warning, not silent zero).

## Non-Goals

- Real-time pricing fetched from provider APIs (fragile, adds network dependency at startup).
- Per-request pricing negotiation or billing integration.

## Options

### Option A: JSON config file

A `pricing.json` file (or a `Pricing` section in the existing `config.json`) loaded at startup. The hardcoded dict becomes the fallback default; the file overrides/extends it.

```jsonc
// pricing.json or config.json → "Pricing" key
{
  "claude-opus-4-6-20260204": { "input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_create": 6.25 },
  "gpt-4o": { "input": 2.50, "output": 10.0, "cache_read": 1.25, "cache_create": 0.0 },
  "my-custom-model": { "input": 1.0, "output": 4.0, "cache_read": 0.0, "cache_create": 0.0 }
}
```

**Pros:**
- Trivial to implement — JSON load + dict merge.
- Fits the existing config pattern (`config.json` already supports `Base` inheritance, `${ENV}` expansion).
- Easy for users to edit.
- No new dependencies.

**Cons:**
- Still a static file — requires manual update when prices change.
- No schema validation beyond what we add.

### Option B: SQLite table

A `model_pricing` table in the existing `.micro_x/memory.db` (or a new `.micro_x/pricing.db`).

```sql
CREATE TABLE model_pricing (
    model TEXT PRIMARY KEY,
    input_per_mtok REAL NOT NULL,
    output_per_mtok REAL NOT NULL,
    cache_read_per_mtok REAL NOT NULL DEFAULT 0,
    cache_create_per_mtok REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Pros:**
- Queryable — could support historical pricing, effective dates, analytics.
- Natural fit if we later add automatic price fetching or a `/pricing` command.
- Already have SQLite infrastructure (`memory/store.py`).

**Cons:**
- Heavier than needed for ~20 static rows.
- Users can't easily hand-edit a DB — need CLI commands or a management UI.
- Adds migration complexity to the memory DB schema.

### Option C: Config file with bundled defaults

Hybrid: ship a `pricing-defaults.json` in the package (generated from the current hardcoded dict). At startup:
1. Load bundled defaults.
2. Overlay with user's `config.json → Pricing` overrides.
3. Merge into the runtime pricing dict.

This is Option A with the defaults extracted to a separate file so they can be updated independently of code.

**Pros:**
- Bundled file can be updated in a release without touching `usage.py`.
- User overrides are clean — only need to specify models they want to change.
- Defaults are still inspectable as a standalone file.

**Cons:**
- Two files to reason about (bundled defaults + user overrides).
- Marginal benefit over keeping defaults in code — both require a release to update.

## Recommendation

**Option A** — add a `Pricing` key to `config.json`, merge over hardcoded defaults.

Rationale:
- Simplest implementation (~30 lines of change).
- Consistent with the existing config system.
- Hardcoded defaults mean zero-config still works.
- Users with custom models or negotiated pricing get an immediate escape hatch.
- The SQLite option (B) is over-engineered for what is fundamentally a small static lookup table. It can be revisited if we add dynamic pricing features later.

## Design

### Loading

In `usage.py`, add a module-level function to accept pricing overrides:

```python
_pricing_overrides: dict[str, tuple[float, float, float, float]] = {}

def load_pricing_overrides(overrides: dict[str, dict]) -> None:
    """Merge user-supplied pricing into the lookup table.

    Called once at startup from bootstrap.py.
    Each entry: {"input": float, "output": float, "cache_read": float, "cache_create": float}
    """
    for model, prices in overrides.items():
        _pricing_overrides[model] = (
            prices["input"], prices["output"],
            prices.get("cache_read", 0.0), prices.get("cache_create", 0.0),
        )
```

### Lookup order

Update `_lookup_pricing()`:
1. Exact match in overrides.
2. Prefix match in overrides.
3. Exact match in hardcoded `PRICING`.
4. Prefix match in hardcoded `PRICING`.
5. Return `None` (unknown model).

### Config schema

In `config.json`:

```jsonc
{
  "Pricing": {
    "claude-opus-4-6-20260204": { "input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_create": 6.25 },
    "my-local-model": { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 }
  }
}
```

The `Pricing` key is optional. When absent, only hardcoded defaults apply.

### Warning on unknown models

Add a one-time warning per model in `estimate_cost()` when pricing lookup returns `None`:

```python
_warned_models: set[str] = set()

def estimate_cost(usage: UsageResult) -> float:
    prices = _lookup_pricing(usage.model)
    if prices is None:
        if usage.model and usage.model not in _warned_models:
            _warned_models.add(usage.model)
            logger.warning(f"No pricing data for model '{usage.model}' — cost will be reported as $0. "
                           f"Add it to config.json Pricing section.")
        return 0.0
    ...
```

### Bootstrap wiring

In `bootstrap.py` (or `app_config.py`), after loading config:

```python
pricing_overrides = config.get("Pricing", {})
if pricing_overrides:
    from micro_x_agent_loop.usage import load_pricing_overrides
    load_pricing_overrides(pricing_overrides)
```

## Files to Modify

| File | Change |
|------|--------|
| `src/micro_x_agent_loop/usage.py` | Add `_pricing_overrides`, `load_pricing_overrides()`, update `_lookup_pricing()`, add unknown-model warning |
| `src/micro_x_agent_loop/bootstrap.py` | Call `load_pricing_overrides()` with config data |
| `src/micro_x_agent_loop/app_config.py` | Pass through `Pricing` key (may already work if config is a plain dict) |
| `tests/test_usage.py` | Tests for override loading, lookup order, unknown-model warning |

## Estimated Effort

Small — ~30 lines of production code, ~50 lines of tests. Single PR.
