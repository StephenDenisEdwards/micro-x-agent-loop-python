# Prompt Versioning Code Review

**Reviewed:** 2026-06-05
**Reviewer:** Analysis of `system_prompt.py`, `memory/store.py`, `session_replay.py` against patterns in other agents and prompt-management tools
**Scope:** Mechanisms for identifying, reproducing, and comparing system-prompt versions across runs
**Status key:** `✅ Done` · `⚠️ Partial` · `🔲 Planned` · `❌ Gap`

---

## Review Context

This review audits how micro-x-agent-loop-python identifies and stores the system prompt used for each LLM call, compares against patterns in other agents (Claude Code, LangChain Hub, PromptLayer, Langfuse, vendor consoles), and records what is implemented, what is missing, and what would be worth adding.

Triggering question: *Is there any mechanism for prompt versioning? Is this something other agents implement? Is it worth considering?*

Short answer: micro-x already has **content-addressed** versioning (sha256 over the rendered prompt). It does not have **semantic** versioning (no `v1`/`v2` label, no eval gating). The content-addressed layer reproduces any past run; what's missing is a way to *talk about* prompt eras and *compare* them ergonomically.

Primary reference plans: none — this is a fresh review.
Related ADRs: none yet.

---

## What Exists Today

### Content-addressed storage

`memory/store.py:82` defines the schema:

```sql
CREATE TABLE IF NOT EXISTS system_prompts (
    sha256 TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    chars INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_requests (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    iteration INTEGER NOT NULL,
    system_prompt_sha256 TEXT NOT NULL,   -- FK to system_prompts
    tools_sha256 TEXT NOT NULL,
    messages_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

`memory/session_manager.py:231` (`persist_system_prompt`) is `INSERT OR IGNORE` keyed by the sha — every distinct prompt is stored once regardless of how many sessions reuse it. Tool schemas are deduped the same way (`tool_schemas`).

Four useful properties drop out:

- **Exact reproducibility** — any past `llm_requests` row can be replayed against the exact prompt text used at the time.
- **Deduplication** — a 12 KB prompt used across 5 000 turns costs 12 KB, not 60 MB.
- **Implicit version identity** — two runs with the same prompt have the same sha; any change (whitespace, flag flip, env var) produces a new sha.
- **Audit trail** — `created_at` on the prompt row records first-seen time.

### Dynamic prompt construction

`system_prompt.py:501` (`get_system_prompt`) builds the prompt from ~12 flags:

```python
def get_system_prompt(
    *,
    user_memory: str = "",
    user_memory_enabled: bool = False,
    concise_output_enabled: bool = False,
    tool_search_active: bool = False,
    task_decomposition_enabled: bool = False,
    working_directory: str | None = None,
    extra_allowed_dirs: list[str] | None = None,
    readonly_dirs: list[str] | None = None,
    autonomous: bool = False,
    hitl_enabled: bool = False,
    compact: bool = False,
    extras: list[str] | None = None,
) -> str:
```

The "version space" is therefore the Cartesian product of:

- The git SHA of `system_prompt.py` at run time (controls the directive bodies),
- The flag combination chosen by config / routing policy,
- The user-memory contents at that moment,
- The working directory + allowed-dirs list,
- Any `extras` lines from the routing policy (e.g. gemma3:4b suppression hints).

`config-base.json` exposes the only "named" knob: `RoutingPolicies.*.system_prompt: "compact"` selects the small-model variant via the `compact=True` flag.

### Replay already reconstructs prompt text from the sha

`session_replay.py:147` (`_Verbatim`) and `session_replay.py:177` (`render`) reconstruct the verbatim prompt for any historical request given its sha:

```python
self._prompt_text = {r["sha256"]: r["text"]
                     for r in store.execute("SELECT sha256, text FROM system_prompts")}
```

`/replay --full` already surfaces the verbatim prompt — given the sha, the prompt is recoverable for the lifetime of the memory DB.

### Capability summary

| Capability | Today |
|---|---|
| Reproduce a past run's prompt | **Yes** (sha + `system_prompts` table) |
| Tell which prompt *era* a run belongs to | **No** — opaque hash, no human label |
| Diff two prompts | **No** — text is stored, but no tool surfaces the diff |
| Roll back to a previous prompt | **No** explicit mechanism (use git on `system_prompt.py`) |
| Attach eval scores to a prompt version | **No** |
| A/B compare prompts | **No** |
| Detect "this run used the *new* prompt vs. *old* prompt" without comparing shas | **No** |

---

## How Other Agents Handle This

### Single-binary agents (Claude Code, Cursor, Aider, Continue.dev)

Prompt versioning is **implicit**: the prompt ships with the release, so the prompt version = the binary version = a git SHA on the agent's own repo. There is no in-product concept of "prompt v3" — to see what prompt ran a week ago, check out the corresponding commit.

Natural fit for agents whose prompt lives in source. Downsides only show up when you want to A/B test or roll back the prompt independently of the binary.

### Prompt-management SaaS (LangChain Hub / LangSmith, PromptLayer, Helicone, Braintrust, Langfuse)

These treat the prompt as a **registry artifact** with explicit version IDs:

- **LangChain Hub** — `hub.pull("my-prompt", version="v3")`. Versions are git-like commits with a parent pointer, diff UI, and a movable `"production"` tag.
- **PromptLayer / Langfuse** — every invocation is logged with `prompt_template_id` + `version_number`. Eval runs are tied to a specific version so regressions are attributable.
- **Braintrust** — prompts live alongside eval datasets; "version" is the unit of comparison in the eval UI.

Model: prompt is a **database row**, not source code. You pay for that with infrastructure complexity (registry server, dev/prod sync, governance) and gain rollout/rollback independent of code deploys, plus an eval harness that knows which version is in flight.

### Vendor consoles (Anthropic Console, OpenAI Playground saved prompts)

Lightweight middle ground: prompts saved server-side with a version-history viewer, no programmatic rollout/rollback. Mostly useful for drafting, not production agents.

### Multi-agent frameworks (LangGraph, AutoGen, CrewAI, OpenAI Agents SDK)

Generally **no built-in prompt versioning**. The prompt is a Python string on an `Agent` object; versioning is delegated to whatever the user puts around it (git, or one of the SaaS tools above).

---

## Recommendations

Five candidate additions, ordered by cost-to-value.

### Recommendation 1 — Stamp `PROMPT_SCHEMA_VERSION` on every `llm_requests` row

| Attribute | Detail |
|-----------|--------|
| **Status** | 🔲 Planned (recommended) |
| **Principle** | Give every prompt era a human-readable label so it's filterable in SQL without comparing 64-character hashes. |
| **Review finding** | Today the only way to ask "did this run use the *new* prompt or the *old* one?" is to look up the sha and grep `git log`. A constant in `system_prompt.py`, bumped manually when the template changes meaningfully, fixes this. |
| **Proposed code locations** | Add `PROMPT_SCHEMA_VERSION = "2026-06-a"` constant in `src/micro_x_agent_loop/system_prompt.py`. Plumb through `Agent` → `persist_request`. Add `llm_requests.prompt_schema_version TEXT` column with migration. |
| **Bump cadence** | Bumped manually when a prompt-template change is significant enough that you'd want to localize a regression to "before vs. after this label". Judgement call, not on every commit. |
| **Estimated effort** | ~1 day. Constant + column + migration + plumbing through the persistence path. |
| **Value** | Filterable in SQL. Surfaces in observability (`session_replay.py` `_render_llm_call` could append it next to the sha). Cheapest and highest leverage. |
| **Residual gap** | The label is advisory and depends on humans bumping it. Doesn't capture flag-driven variants (e.g. `compact=True`) — that's still in the sha. |
| **Action taken** | — |

### Recommendation 2 — `/replay --diff <sha1> <sha2>` command

| Attribute | Detail |
|-----------|--------|
| **Status** | 🔲 Planned (recommended) |
| **Principle** | If we already store full prompt text for every distinct sha, expose a one-shot way to diff two of them. |
| **Review finding** | The diff is currently a manual operation: dump prompt A, dump prompt B, run `diff`. Adding it to `/replay` collapses a multi-step debugging task into one command. |
| **Proposed code locations** | New subcommand in `src/micro_x_agent_loop/commands/replay.py`. Backend: `SELECT text FROM system_prompts WHERE sha256 IN (?, ?)`, hand to `difflib.unified_diff`. |
| **Estimated effort** | ~½ day. ~30 lines. |
| **Value** | Self-service prompt diffing. Useful for "did something change in the prompt between yesterday's session and today's?" |
| **Residual gap** | Only diffs *rendered* prompts. Without Recommendation 3 you can't separate "template changed" from "user memory changed" — the diff will show both. |
| **Action taken** | — |

### Recommendation 3 — Separate template sha from substituted-data sha

| Attribute | Detail |
|-----------|--------|
| **Status** | ❌ Gap |
| **Principle** | The sha currently entangles "the prompt template" with "the data substituted into it" (user memory, working directory, allowed dirs). A single byte of user-memory drift mints a new prompt version. Splitting these lets us answer "did the *template* change?" independent of data drift. |
| **Review finding** | Useful only when prompt-author work starts producing regressions that can't be localized to template-vs-data. Not load-bearing for current agent behavior. |
| **Proposed code locations** | Refactor `get_system_prompt` to return `(template_sha, rendered_text)` and persist both on `llm_requests`. Add `system_prompt_templates` table parallel to `system_prompts`. |
| **Estimated effort** | ~2–3 days. Mostly migration + plumbing; small behavioral change. |
| **Value** | Cleaner attribution when investigating prompt-driven regressions. |
| **Residual gap** | None — but only worth building when a real debugging session demands it. |
| **Action taken** | — |

### Recommendation 4 — Full prompt registry (named prompts, semver, rollout/rollback)

| Attribute | Detail |
|-----------|--------|
| **Status** | ❌ Gap (recommend **defer**) |
| **Principle** | Treat prompts as registry artifacts independent of the code release cycle, so they can be rolled out and rolled back without a deploy. |
| **Review finding** | Conflicts with the current "prompts-as-source" architecture. With prompts as Python strings in `system_prompt.py`, git is already a registry — adding a parallel one duplicates state. Only worth building if prompts need to operate independently of code deploys, **and** there is an eval harness gating versions. |
| **Estimated effort** | Weeks. New tables, config plumbing, admin CLI or UI. |
| **Value** | Production-grade rollout/rollback if the use case exists; otherwise theater. |
| **Residual gap** | Without paired evals (Recommendation 5), version numbers don't gate anything. |
| **Action taken** | — (not recommended at current scale) |

### Recommendation 5 — Eval harness tied to prompt versions

| Attribute | Detail |
|-----------|--------|
| **Status** | ❌ Gap |
| **Principle** | A prompt version is decorative unless an eval suite scores it. With evals, "v2026-06-b dropped tool-search accuracy by 4 pp" becomes a real statement. |
| **Review finding** | The biggest investment of the five, and the one that makes versioning *useful* rather than the other way around. Worth its own review and plan — out of scope for this document, but flagged as the natural next step after Recommendations 1 and 2 land. |
| **Estimated effort** | Large. Benchmark suite, runner, score storage, regression gates. |
| **Value** | Turns versioning from labeling into gating. |
| **Action taken** | — |

---

## Summary

| # | Recommendation | Status | Effort | Priority |
|---|----------------|--------|--------|----------|
| 1 | `PROMPT_SCHEMA_VERSION` constant stamped on `llm_requests` | 🔲 Planned | ~1 day | **High** |
| 2 | `/replay --diff <sha1> <sha2>` command | 🔲 Planned | ~½ day | **High** |
| 3 | Separate template sha from substituted-data sha | ❌ Gap | ~2–3 days | Low (defer until needed) |
| 4 | Full prompt registry (semver, rollout/rollback) | ❌ Gap | Weeks | **Not recommended** at current scale |
| 5 | Eval harness tied to prompt versions | ❌ Gap | Large | Worth a separate review |

Bottom line: micro-x's content-addressed `system_prompts` table is already more than most agents have. Two small ergonomic additions (Recommendations 1 and 2) close ~80% of the gap to a "real" versioning system. Bigger investments (registry, evals) only pay off once eval-anchored prompt comparison becomes a real workflow — defer them until that need is concrete.

---

## Related

- `src/micro_x_agent_loop/system_prompt.py:501` — `get_system_prompt(...)` (prompt builder).
- `src/micro_x_agent_loop/system_prompt_builder.py` — directive concatenation helper.
- `src/micro_x_agent_loop/memory/store.py:82` — `system_prompts` / `llm_requests` schemas.
- `src/micro_x_agent_loop/memory/session_manager.py:231` — `persist_system_prompt`.
- `src/micro_x_agent_loop/session_replay.py:147` — `_Verbatim` (loads prompt text for replay).
- `config-base.json` → `RoutingPolicies.*.system_prompt` — the only "named variant" knob today (`"compact"` toggle).
- [ADR-013 — tool-result summarization reliability](../architecture/decisions/ADR-013-tool-result-summarization-reliability.md) — adjacent: stamps version-like identity on summarization behavior.
