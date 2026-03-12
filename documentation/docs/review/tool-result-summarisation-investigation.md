# Tool Result Summarisation — Deep Investigation

**Date:** 2026-03-12
**Scope:** Current implementation, failure modes, and what becomes possible with structured tool results

---

## 1. Where We Are

### The existing pipeline

Every tool result passes through three sequential stages in `turn_engine.py`:

```
Tool executes
    ↓
ToolResultFormatter.format()     ← config-driven: json / table / text / key_value
    ↓
_summarize_tool_result()         ← LLM call (disabled by default)
    ↓
_truncate_tool_result()          ← hard char cap (always on)
    ↓
Injected into conversation history
```

### The data structure

`tool.py` — `ToolResult` carries both representations from the start:

```python
@dataclass
class ToolResult:
    text: str                          # human-readable prose fallback
    structured: dict[str, Any] | None  # machine-parseable JSON
    is_error: bool = False
```

`mcp_tool_proxy.py` (lines 56–80) already extracts `structuredContent` from MCP responses and stores it in `ToolResult.structured`. All TypeScript MCP servers in this project return both `content` (text) and `structuredContent` (JSON).

### What the formatter does with structured data

`tool_result_formatter.py` selects a rendering strategy per tool:

| Strategy | What it produces | When used |
|---|---|---|
| `json` | Pretty-printed full JSON | `github__get_pr`, most structured tools |
| `table` | Markdown table (array of objects) | `web__web_search`, `linkedin__linkedin_jobs` |
| `text` | Single field extracted | `filesystem__read_file` (extracts `content`), `filesystem__bash` (extracts `stdout`) |
| `key_value` | `key: value` lines | `filesystem__write_file` |

The formatter already does lossless field-level extraction for the **presentation** layer. It does not reduce context window size — it changes shape, not volume.

---

## 2. Why the Original Summarisation Failed

ADR-013 documents a production failure: a job search workflow with summarisation enabled missed job listings and their URLs compared to the same workflow with it disabled. Haiku was discarding listings it deemed less relevant — but all were required.

### The fundamental problem

The LLM summarisation prompt (`turn_engine.py` lines 405–409) was:

```
"Summarize this tool output concisely, preserving all decision-relevant
data (names, numbers, IDs, paths, errors).
Tool: {tool_name}\n\n{result}"
```

The problem is the phrase "decision-relevant." That decision belongs to the main agent, which has the user's goal in context. The summarisation model sees only the tool output — it has no idea which of twenty job listings the user will care about, so it picks the ones it judges most relevant. That judgement is wrong.

**This is not a prompt engineering problem.** No instruction to "preserve everything important" can work when the model doing the preserving doesn't know what important means in the task context.

This applies to any LLM-based summarisation of unstructured results — web pages, email bodies, search results, file contents. The information loss is unpredictable and task-dependent.

---

## 3. What Changes with Structured Results

Structured tool results are a different problem domain. The key distinction:

| | Unstructured text | Structured JSON |
|---|---|---|
| Schema | Unknown | Known at tool definition time |
| Fields | Implicit in prose | Explicit, named, typed |
| Extraction | LLM must guess | Deterministic projection |
| Loss | Unpredictable | Controlled (you choose which fields to drop) |
| Summarisation need | Lossy compression | Lossless projection |

With `ToolResult.structured` populated, we have a fundamentally different set of options.

### Option A — Field projection (lossless within selected fields)

Instead of asking an LLM to "summarise" a GitHub PR response, project to only the fields the agent task needs:

```json
{
  "number": 42,
  "title": "Fix auth bug",
  "state": "open",
  "url": "https://github.com/...",
  "additions": 23,
  "deletions": 5
}
```

rather than the full 20-field response. Every retained field is exact — no information loss within the projection. The only question is which fields to project, and that can be defined statically per tool in config.

This is already half-built. `ToolResultFormatter` with `strategy: "text"` does single-field extraction. The gap is multi-field projection and row-limiting for arrays.

### Option B — Row limiting for array results (lossless per row)

For array tools (search results, job listings, emails), the volume is `n_rows × row_size`. The formatter already supports `max_rows` in the `table` strategy, but only for presentation — it doesn't affect the text that gets stored in conversation history when structured is `None`.

With structured results consistently available, `max_rows` becomes a genuine token-reduction lever: return the top N results exactly, discard the rest. Each retained row is complete — no summarisation within a row. This is deterministic and auditable.

### Option C — Size-budgeted field truncation

For large text fields within structured results (e.g., a PR body, email body, page content), truncate the specific field at a configurable char limit rather than truncating the entire result at 40K chars.

```json
{
  "title": "...",
  "body": "First 2000 chars of the PR description... [TRUNCATED]",
  "url": "..."
}
```

The structured envelope (all other fields) is preserved exactly. Only the known-large prose field is truncated. Compare this to the current approach where the 40K hard truncation cuts off at an arbitrary point in the JSON/text, possibly mid-URL or mid-number.

### Option D — Deferred LLM extraction (structured schema → structured summary)

If an LLM call is genuinely needed (e.g., extracting key facts from a long structured document), structured input allows the prompt to be far more precise:

```
Extract the following fields from this GitHub PR review:
- verdict (approved/changes_requested/comment)
- blocking issues (list)
- non-blocking suggestions (list)

Input: { structured JSON here }
```

This is fundamentally different from unstructured summarisation because:
- The input schema is known — the LLM isn't guessing what fields exist
- The output schema is known — the LLM produces typed extraction, not prose
- The task is extraction, not compression — no information loss outside the specified fields
- Failure modes are predictable — missing field = empty, not garbled content

---

## 4. What Already Works Today

The infrastructure for structured-result size reduction already exists. It is not fully wired up for context-window cost reduction, but the pieces are present:

| Capability | Status | Location |
|---|---|---|
| `ToolResult.structured` field | ✅ Exists | `tool.py` |
| MCP `structuredContent` extraction | ✅ Done | `mcp_tool_proxy.py` lines 56–80 |
| Config-driven per-tool formatting | ✅ Done | `tool_result_formatter.py` |
| `max_rows` for table strategy | ✅ Done | `tool_result_formatter.py` (presentation only) |
| Single-field extraction (`text` strategy) | ✅ Done | `tool_result_formatter.py` |
| Multi-field projection | ❌ Not built | — |
| Field-level truncation for large prose fields | ❌ Not built | — |
| Structured-input LLM extraction | ❌ Not built | — |
| `output_schema` captured from MCP | ✅ Captured | `mcp_tool_proxy.py` (unused) |

The formatter currently runs before the LLM call and before the result enters history. That positioning is correct — it is the right place to reduce context size.

---

## 5. The Real Problem with the Current Formatter

The `ToolResultFormatter` converts structured data for **presentation** but does not optimise for **context window cost**. Specifically:

1. **`json` strategy** outputs the entire JSON object. A `github__get_pr` result with 20 fields, including a multi-paragraph PR body, enters the context as full JSON. If the task only needed `state` and `url`, 18 fields are noise.

2. **`table` strategy** applies `max_rows` only for display. If `ToolResult.structured` is the input and `max_rows: 20` is set, the table shows 20 rows — but this is downstream of the point where tokens are counted against the context window (the formatter output is what goes into history).

   Actually re-reading this: the formatter output IS what goes into history. So `max_rows` does reduce context size for table results — this is already working as a cost lever. It just isn't documented as one.

3. **`text` strategy** extracts a single field (e.g., `stdout` from bash results) — this already eliminates `stderr`, `exit_code`, and `timed_out` from the context. This is the closest thing to field projection that currently exists.

4. **There is no `fields` projection strategy.** A strategy that says "include only these named fields from the structured object" would be a direct, deterministic size reduction with no information loss for the projected fields.

---

## 6. What a Reliable Structured Summarisation Would Look Like

Given the above analysis, "summarisation" with structured results should be reframed as **structured reduction** — lossless within its scope, declarative, config-driven, no LLM required for the common case.

### Proposed additions to `ToolResultFormatter`

**Strategy: `fields` (multi-field projection)**

```json
"github__get_pr": {
  "format": "fields",
  "fields": ["number", "title", "state", "url", "additions", "deletions", "ci_status"]
}
```

Produces a key_value block with only the listed fields. Everything outside the list is dropped deterministically.

**Strategy: `table` with `max_chars_per_cell`**

```json
"google__gmail_read": {
  "format": "table",
  "max_rows": 10,
  "max_chars_per_cell": 500
}
```

Limits both row count and per-cell content size. URL and ID fields are short — they survive intact. Only long prose cells are truncated.

**Field-level truncation config**

```json
"github__get_pr": {
  "format": "fields",
  "fields": ["number", "title", "state", "url", "body"],
  "truncate_fields": { "body": 1000 }
}
```

`body` is truncated at 1000 chars. All other projected fields are exact.

### When an LLM call is still justified

An LLM extraction call makes sense only when:

1. The tool returns unstructured prose **and** there is no `structured` data (true unstructured tools, third-party MCP servers)
2. The task requires semantic understanding of a long text field (e.g., "summarise the PR review comments into blocking/non-blocking")
3. The reduction target is not achievable by projection alone

In these cases, the extraction prompt should:
- Be given the structured envelope (all typed fields) as context
- Specify the exact output schema expected (typed JSON, not prose summary)
- Use the cheapest model that can reliably extract the required fields
- Treat the output as a new `ToolResult.structured` (typed extraction, not a summary)

---

## 7. Current LLM Summarisation — What to Do With It

The existing `_summarize_tool_result` in `turn_engine.py` is disabled by default and marked unreliable. Given the analysis above:

- **For structured results:** Replace with field projection (Options A–C above). No LLM needed.
- **For unstructured results (third-party tools with no `structured`):** The existing LLM path is the only option, but it remains unreliable for information-dense content. It is acceptable only for tasks where partial information loss is tolerable (e.g., summarising a long log file where "the gist suffices").
- **Provider/model bug:** The current code (`agent.py` lines 190–194) has the same provider fallback issue as compaction — `ToolResultSummarizationProvider` should follow the same required-field pattern. This is deferred until the feature is re-enabled.

---

## 8. Recommended Approach

### Phase 1 — Extend the formatter (no LLM, no risk)

1. Add `fields` projection strategy to `ToolResultFormatter`
2. Add `truncate_fields` config option (per-field char limits within structured results)
3. Add `max_chars_per_cell` to `table` strategy
4. Update `config-base.json` with revised per-tool formatting configs using the new strategies
5. Document `max_rows` as a cost lever (it already is one, just not documented as such)

This is pure config + formatter logic. No LLM calls, no unreliability, no new architectural decisions. It directly reduces context window tokens for structured tool results.

### Phase 2 — Add ToolResultSummarizationProvider (consistent with other providers)

Apply the same required-field pattern used for `CompactionProvider`, `Stage2Provider`, `SubAgentProvider`:
- `ToolResultSummarizationProvider` must be set when `ToolResultSummarizationEnabled: true`
- `ToolResultSummarizationModel` must be set when `ToolResultSummarizationEnabled: true`
- Validation at `Agent.__init__`, no fallbacks

Only relevant for unstructured tool results where the LLM path is still needed.

### Phase 3 — Structured LLM extraction (optional, scoped)

For specific high-value tools where semantic extraction is genuinely useful:

- Define an extraction config per tool: input fields, output schema, model
- Call the LLM with both structured envelope and extraction schema as prompt
- Validate output against schema; fall back to full result on failure
- Track as a separate `tool_extraction` call type in metrics

This is distinct from the old summarisation: typed input → typed output, no prose involved.

---

## 9. Summary

| Approach | Reliability | LLM needed | Works with structured | Status |
|---|---|---|---|---|
| Current LLM summarisation (unstructured) | ❌ Unreliable | Yes (cheap model) | N/A | Disabled |
| Hard truncation | ⚠️ Lossy at arbitrary point | No | Partial | Active |
| `max_rows` table limiting | ✅ Lossless per row | No | Yes | Active (undocumented cost lever) |
| `text` single-field extraction | ✅ Lossless | No | Yes | Active |
| `fields` multi-field projection | ✅ Lossless within projection | No | Yes | **Not built** |
| Field-level truncation (`truncate_fields`) | ⚠️ Lossy only for specified fields | No | Yes | **Not built** |
| Structured LLM extraction (typed → typed) | ✅ Reliable (typed output) | Yes | Yes | **Not built** |
