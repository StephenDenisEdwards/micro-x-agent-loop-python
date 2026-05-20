# DESIGN — `describe_structure` Tool

**Status:** Proposed
**Date:** 2026-05-20
**Author:** Stephen D Edwards (with Claude)
**Tool home:** native in-process filesystem tools (alongside F1–F6), per [ADR-025](../architecture/decisions/ADR-025-native-filesystem-tools.md) and the `project_native_core_tools` decision — **not** an MCP server, **not** a per-task codegen target.

## One-line

A generic, body-incapable, format-detecting native tool that returns the *shape* of a file — root/format, the dominant repeating unit and its count, a clipped one-element sample, top-level tags/keys — without the file body ever entering the LLM's context.

---

## 1. Motivation

### 1.1 The triggering failure

The prompt "**count the number of jobs in `jobserve-sample.rss`**" (a 291,488-byte RSS 2.0 feed delivered as a *single line*, 50 `<item>` elements) is the load-bearing example. It looks trivial — a child can do it. The agent cannot do it reliably. The eval suite (`tests/evals/test_count_jobs.py`) reproduces the failure deterministically *as a class of behaviour*; the specific runs differ each time, but the failure modes recur:

- **Wrong-pattern guess.** Agent emits `grep '&lt;item&gt;'` (HTML-escaped) — zero matches. (Tracked as a separate suspected escaping bug, orthogonal to this design.)
- **No fallback procedure.** On a zero count, the agent does not re-ground its world-model. It invents new patterns (`### \d+\.`, `\d+\. \*\*` — Markdown-heading guesses for an RSS file) and thrashes.
- **Catastrophic perception.** When the agent does decide to "look," its only options are blind `grep` (requires already knowing what to count) or `read_file` (dumps 291KB — caught by `ToolResultSummarizationEnabled` and turned into a $0.34 / 41 s summarization call, masking the violation as a "pass" until Criterion 2 was hardened).
- **Confident hallucination.** Observed answer in a failing run: *"I can see from the file that it says **'30 total' jobs**…"* — fabricated number, then thrash.
- **Non-determinism.** Same prompt, same config, same model: 1 FAIL / 2 PASS over 3 runs. A single green is not a verdict.

This is a textbook instance of the [ISSUE-007](../issues/ISSUE-007-prose-contract-drift-across-policy-layers.md) thesis: behaviour emerges from many layers that no one mechanism reconciles. The fix is not better prompts — it is *removing the latitude* that lets the agent guess.

### 1.2 The 8-year-old framing

The child given the same task does:

1. **Glances** at a piece of the file (not the whole thing).
2. **Notices** repeating chunks; each chunk is a "job."
3. **Counts** the chunks (or a per-chunk marker).
4. **Sanity-checks** the count against what they saw.

The child is not smarter. They have **bounded perception** ("I can see *a bit* without seeing it all"), **grounding** ("a zero count means my model is wrong — look, don't re-guess"), and **verification** ("does 50 fit what I saw?"). The agent has none of these:

- All-or-nothing perception (blind grep vs whole-file dump). No "glance."
- No grounding loop: a zero result triggers another guess, not an observation.
- No plausibility check: any number that fits the template ships, including "30."

`describe_structure` directly supplies the missing **bounded perception** primitive. Pairing it with a method directive supplies the **grounding** procedure. (Verification — cross-method consistency — is a future lever, out of scope here.)

### 1.3 Hypothesis verified by the eval suite

Holding fixture, config (`config-anthropic-eval-0001.json`), and model (Sonnet 4.5) constant, varying only the prompt:

| Eval | Prompt | Observed |
|---|---|---|
| `test_count_job_items.py` | "count the number of **job items**" (leaks `<item>`) | PASS, 1 grep, ~$0.02 |
| `test_count_jobs.py` | "count the number of **jobs**" (honest, no leak) | FAIL: `&lt;item&gt;`, read 291KB, hallucinated "30", thrashed to cap, ~$0.40 |
| `test_count_jobs_structure_given.py` | honest + "**this is RSS 2.0, jobs are `<item>`**" | PASS, 1 grep, ~$0.02 |

The *only* difference between FAIL and PASS was telling the agent the structure. That isolates the gap as **schema-ascertainment**, not tool-use and not model capability. `describe_structure` is the agent-discoverable replacement for the human-supplied hint.

---

## 2. Prior art

The pattern is **documented best practice**, not novel:

- **Anthropic — ["Code execution with MCP"](https://www.anthropic.com/engineering/code-execution-with-mcp)**: agents should explore structure / filter data before it reaches the model. Their worked example: 150k → 2k tokens (98.7% reduction). This design is an instance of that principle applied to file inspection.
- **`universal-json-agent-mcp`** (open source, `uv tool install universal-json-agent-mcp`): JSON-only structure tooling. Exposes `get_structure` (skeleton: keys/types/nesting, **no values**), `distinct_paths`, `load_json` (metadata only). We borrow the **body-free output contract** and (for JSON) can stand on this engine.
- **Codebase-Memory** (tree-sitter knowledge graphs over 66 languages via MCP): code-only structural exploration. Available as a per-language engine we can delegate to.
- **XML editors** (e.g. XMLSpy): GUI table views of repeating elements — not agent tools.

**The gap.** No off-the-shelf tool provides a **generic, format-detecting, body-incapable** structure probe for *any* file (RSS/XML/JSON/CSV/log/unknown) with a single call returning the dominant repeating unit and its count. That is what this design fills.

**Why this gap exists, despite the pattern being recognised** (worth recording so the design stays honest):

1. Large context windows + tool-result summarization paper over the failure for most inputs.
2. The failure is **invisible without measurement** — the same instrumentation we built this session (BufferedChannel trajectories, hardened Criterion 2, cost from `SessionAccumulator`) is what makes the failure legible. Most teams don't build it.
3. Unglamorous infra — no demo appeal.
4. Generic-across-formats is genuinely harder than per-format.
5. Prevailing MCP design philosophy ("small composable tools, let the model figure it out") optimizes for flexibility, which is the very latitude that produces our failure. This design **deliberately diverges** from that philosophy — see §3.

---

## 3. Design principles

1. **Body-incapable by construction.** The tool must be *structurally unable* to return the file body. Output is bounded by the schema (counts, names, a clipped sample), enforced in code, not by a soft limit. If a tool *can* dump 291KB, the LLM will eventually make it. This is the whole-session lesson: reliability comes from removing the rope.

2. **Single call, not a composable kit — deliberate divergence from prior art.** `universal-json-agent-mcp`'s philosophy is "small tools composed by the AI." That optimizes for *flexibility*. We optimize for *reliability*: every decision we hand the agent is a place it can thrash. One call → one structured answer → minimal judgment surface. We accept reduced flexibility as the price of consistent behaviour.

3. **Format-detecting, not per-format.** The agent does not pre-classify the file. The tool sniffs format (root XML tag, JSON top-level type, CSV header heuristics, byte-order marks, extension as a weak hint) and returns the appropriate shape. **Unknown** is a first-class return path — it still gives the agent useful orienting facts rather than failing.

4. **Stand on proven engines under the hood.** Do not hand-roll parsers. Use `xml.etree.ElementTree.iterparse` (streaming SAX-style) for XML, `ijson` or a streaming visitor for JSON/JSONL, the stdlib `csv.Sniffer` for CSV, optional `tree-sitter` for code in Phase 2. The tool's value is the *unifying body-incapable interface*, not novel parsing.

5. **Streams from disk; never loads the body into Python memory in one shot, and never into model context at all.** The whole point.

6. **Deterministic.** Same file, same output, every time. No LLM in the loop. No sampling-based heuristics that vary run-to-run.

7. **Cheap.** Single pass for the common formats. The agent must feel no temptation to skip it.

---

## 4. Interface

### 4.1 Name & location

- **Tool name (LLM-facing):** `filesystem__describe_structure`
- **Source location:** `src/micro_x_agent_loop/native_tools/filesystem/structure_tool.py` (alongside `read_tools.py`, `bash_tool.py`, etc.)
- **Schema registered via:** the native filesystem tool registration path the F1–F6 series established.

### 4.2 Input

```python
class DescribeStructureInput:
    path: str            # required; subject to PathPolicy (allowed dirs) like all native fs tools
    max_sample_bytes: int = 512   # hard upper bound on the clipped one-element sample
```

No `format` override input — the tool detects. No `include_body` flag — the tool *cannot* return the body. No `output_mode` switches — one call returns one shape.

### 4.3 Output

A single structured payload, byte-bounded (≤ ~2 KB total by construction):

```jsonc
{
  "path": "C:/.../jobserve-sample.rss",
  "size_bytes": 291488,
  "is_single_line": true,                // line_count == 0 newlines → critical perception flag
  "format": "xml.rss-2.0",               // or "xml.atom", "json", "jsonl", "csv", "tsv", "log", "unknown"
  "encoding": "utf-8",                   // detected; defaults documented
  "confidence": "high",                  // "high" | "medium" | "low" | "unknown"

  // Format-specific shape, ONE of:
  "xml": {
    "root": "rss",
    "namespaces": ["http://www.w3.org/2005/Atom"],
    "repeating_element": "item",         // dominant repeated child under root/channel
    "repeating_element_path": "rss/channel/item",
    "count": 50,
    "child_tags": ["title", "link", "description", "pubDate", "guid"],
    "sample_element_clipped": "<item><title>...</title>...</item>"   // ≤ max_sample_bytes
  },
  // or:
  "json": {
    "root_type": "array" | "object",
    "repeating_path": "$.items[*]",      // largest top-level array, or null
    "count": 50,
    "element_shape": {"id": "string", "title": "string", "date": "string"},  // type skeleton, no values
    "top_level_keys": ["items", "metadata"],
    "sample_element_clipped": "{\"id\":\"...\",...}"
  },
  // or:
  "csv": {
    "delimiter": ",",
    "has_header": true,
    "header": ["title", "url", "date"],
    "row_count": 50,
    "sample_row_clipped": "Senior Backend Engineer,https://...,2026-05-20"
  },
  // or (the unknown-but-useful fallback):
  "unknown": {
    "line_count": 0,
    "first_bytes_clipped": "<?xml version=\"1.0\"?><rss...",   // ≤ max_sample_bytes
    "last_bytes_clipped": "...</rss>",                          // ≤ max_sample_bytes
    "tag_or_keyword_histogram": [["<item>", 50], ["<title>", 51], ["<link>", 51]]
  },

  "notes": [
    "Single-line file; line-based tools (grep -c, head -n N) will not work as expected."
  ]
}
```

Hard contract: every output field is either a name, a count, a type, or a *clipped* sample bounded by `max_sample_bytes`. The full body is unreachable.

### 4.4 Worked example — the load-bearing case

`describe_structure("…/jobserve-sample.rss")` returns:

```json
{
  "size_bytes": 291488, "is_single_line": true, "format": "xml.rss-2.0",
  "xml": {
    "root": "rss", "repeating_element": "item",
    "repeating_element_path": "rss/channel/item", "count": 50,
    "child_tags": ["title", "link", "pubDate", "guid", "description"],
    "sample_element_clipped": "<item><title>…</title>…</item>"
  },
  "notes": ["Single-line file; line-based tools will not work as expected."]
}
```

The agent's task collapses to "the answer is `xml.count`." No guessing, no pattern construction, no body in context, deterministic, single call. The Scenario 3 prompt's effect (`PASS, 1 grep, $0.02`) reproduced *without* the human supplying the hint.

---

## 5. "Repeating unit" detection per format

The most subtle piece. Specification per format:

- **XML / RSS / Atom.** Stream with `iterparse`. Tally counts of *direct children of the document root or of a single dominant child* (RSS: `<channel>`; Atom: `<feed>` itself). The repeating element is the most-frequent child tag whose count is ≥ 2× the next most frequent — the "dominant" repetition. If no clear winner, return `repeating_element: null` and the full child-tag histogram; do not guess.
- **JSON.** Stream with `ijson`. The repeating unit is the **longest top-level array** (or, if root is an array, the array itself). `element_shape` is the type-skeleton union of the first ≤ 20 elements. No values.
- **JSONL / NDJSON.** Each line is one element. `count` is the line count. `element_shape` from the first record.
- **CSV / TSV.** `csv.Sniffer` for delimiter + header. Repeating unit = data row. `count` = row count (streamed).
- **Plain log / line-oriented.** `count` = line count. `repeating_element: null` unless a strong prefix pattern (timestamp regex) dominates ≥ 80% of lines.
- **Unknown.** Return the `unknown` block (line count + first/last bytes + tag-or-keyword histogram of top regex matches like `<\w+>`, `^"\w+":`). The agent at least learns size, shape class, and orienting samples.

Detection order: BOM / first non-whitespace byte → extension → content sniff. Confidence is reported.

---

## 6. Body-incapable contract (the enforcement)

This is the design's load-bearing safety property. Enforced as follows:

- Output serialized through a schema validator that **rejects** any string field larger than `max_sample_bytes` (default 512, ceiling 2048). The tool implementation truncates with an explicit ellipsis suffix; downstream cannot enlarge it.
- No code path in `structure_tool.py` reads the entire file into a single in-memory string. Streaming primitives only (`iterparse`, `ijson`, `csv.reader` over a file handle, `enumerate(open(path))`).
- The tool's `ToolResultOverrides` config is **`MaxChars: 2048`** with summarization **off** (already-bounded; summarization is wasted cost and would obscure the structured payload). See [ADR-024](../architecture/decisions/ADR-024-single-layer-tool-result-truncation.md).
- Unit tests assert: (a) a 1 GB synthetic file produces a payload ≤ 2 KB and runs in < 1 s; (b) every string field's byte length ≤ `max_sample_bytes`; (c) no path produces a `result_chars` ≥ 4 KB on the eval fixture.

---

## 7. Tool is necessary but not sufficient — the directive pairing

This session's clearest negative finding: **the agent did not reach for structure inspection even when every tool was available.** It guessed and thrashed. A tool that exists but is not invoked is no fix.

So `describe_structure` ships with a paired **generic** directive in the system prompt (`system_prompt.py`), distinct from per-task guidance:

> *When asked to count, enumerate, or measure entities in a file you do not understand — and especially when a file is large or you have not previously inspected it — first call `filesystem__describe_structure(path)` to learn its format and repeating unit. Use the result to choose the counting/extraction tool. Never guess a regex or element name. Never `read_file` a file you have not first described.*

The directive is generic (teaches *method*, not the RSS answer). It is not "programming the task"; it is teaching the agent the child's procedure: look → identify → count.

`config-0002` = `config-0001` + this directive + the tool available. That is the deliberate test of the hypothesis under controlled conditions.

---

## 8. Verification plan

The same apparatus this session built is how this design is judged. No new instrumentation needed.

1. **Build** `filesystem__describe_structure` per §4–6.
2. **Add** the §7 directive to `system_prompt.py`.
3. **Create** `config-anthropic-eval-0002.json` — pure inheritance baseline + (later) any directive flags. Same model pin (Sonnet 4.5).
4. **Run** `test_count_jobs.py` (the **honest, non-leaking** prompt — no structure given) against `config-0002` ≥ 5 times.
5. **Read** for each run, in the `[eval record]`:
   - Was `filesystem__describe_structure` called *first*, unprompted? (the real metric)
   - Did `read_file` of the fixture happen at all? (must be **no**)
   - Did `&lt;item&gt;` appear? (must be **no**)
   - Was the answer correct (50) without thrash, without hitting the cap?
6. **Success criteria:**
   - Pass rate on the honest prompt ≥ 4/5 (vs the current ~2/3 baseline).
   - Trajectory: `describe_structure` → `grep` (or equivalent) → answer. Two tool calls, no `read_file`, no whole-file summarization, no `&lt;item&gt;`, no cap-hit.
   - Cost ~$0.02 range (matches Scenario 3 ceiling), not $0.40 (Scenario 2 thrash range).

The verdict is *trajectory + rate*, not a single green. Criterion 2 hardened against summarization (committed `dc95719`) keeps the verdict honest.

---

## 9. Non-goals

- **Not a parser/extractor.** Returns shape, not data. To pull values, the agent uses the existing counting/reading tools *informed by* the structure result.
- **Not RAG.** No embeddings, no retrieval ranking. Structure-by-streaming only.
- **Not a query language.** No XPath/JSONPath input. (That can layer on later as a separate, also-bounded tool.)
- **Not a fix for the `&lt;item&gt;` escaping bug.** That is a separate, orthogonal defect (suspected to be either a model artifact or a tool-input escaping layer). `describe_structure` *routes around* the symptom by removing the need to construct discovery patterns by hand; the underlying bug should still be traced independently.
- **Not a replacement for `read_file`.** `read_file` remains for reading content the agent has *deliberately decided* to read after probing structure.

---

## 10. Open questions & risks

1. **Will the agent actually reach for it?** The directive should compel it, but agents have ignored directives before in this session. Verification §8 tests precisely this. If the trajectory shows the tool unused, the lever is the directive (or sub-agent routing), not the tool design.
2. **"Repeating unit" ambiguity.** Some files have no single dominant repeating element (mixed feeds, multi-section configs). Spec mitigates by returning `repeating_element: null` + the full histogram rather than guessing; the directive is to *use the result*, not invent one.
3. **Format-detection failure on adversarial / malformed inputs.** Stream parsers fail gracefully — return what was ascertained before failure, plus an `error` note. Never throw on a malformed file.
4. **Maintenance surface.** Each format engine is a dependency or stdlib piece. Phase 1 keeps it stdlib-only (`xml.etree`, `json` streaming via incremental decoder, `csv`); Phase 2 introduces `ijson` / `tree-sitter` only if Phase 1 proves the value.
5. **Interaction with `tool_search` / cache-creation cost.** Adding any tool grows the schema (~30k cache-creation tokens already). For `config-0002` we accept this cost; if it hurts, downgrade the directive to "load on demand" via `tool_search`.
6. **One-tool-vs-kit revisited.** If empirical use shows the agent wants to drill (e.g. "describe, then show me one full sample, then count") the kit philosophy may need to win for advanced cases. The single-call form remains the default reliability surface; a sibling `inspect_sample(path, element)` could be added later — bounded the same way.

---

## 11. Phasing

**Phase 1 (verify the hypothesis):**
- Formats: XML/RSS/Atom, JSON, JSONL, CSV/TSV, unknown-fallback.
- stdlib parsers only.
- Body-incapable contract enforced.
- Directive added to `system_prompt.py` (generic, not task-specific).
- `config-anthropic-eval-0002.json` committed.
- Honest-prompt eval (`test_count_jobs.py`) run 5× against `-0002`. Decision gate on §8 success criteria.

**Phase 2 (only if Phase 1 confirms the hypothesis):**
- YAML, TOML, line-oriented logs with regex inference.
- Optional `tree-sitter` engine for source code (delegate to existing tree-sitter installs).
- Sibling bounded `inspect_sample(path, element_id)` for one-element drill-down.

**Phase 3 (speculative):**
- Memorise the *method* (not the answer) across sessions: after `n` solved trajectories with `describe_structure → counter`, the system-prompt directive becomes optional/derivable. This is the "child learns" endgame and is out of scope here; recorded for the roadmap.

---

## 12. Relationship to the Map-Evaluate pattern

[`DESIGN-map-evaluate-pattern`](DESIGN-map-evaluate-pattern.md) (proposal, draft) addresses an adjacent reliability/cost failure mode: when an outer agent must process **N items against criteria**, raw item content accumulates in the outer conversation and quality degrades. The two designs are **complementary, not overlapping**:

| Axis of "too big" | Design |
|---|---|
| **One** input too dense/large for the agent to investigate | `describe_structure` |
| **N** items would all have to enter outer context to evaluate | `evaluate_items` (Map-Evaluate) |

They share architectural DNA — both move raw-content consumption *inside* a tool and return only compact structured output, keeping the outer LLM context lean — and they compose naturally in real workflows:

```
Source (file/feed/page)
   ↓ describe_structure(path)
{format: rss-2.0, repeating: item, count: 50, …}
   ↓ agent extracts the N items via a targeted call
[item_1, item_2, …, item_N]
   ↓ evaluate_items(rubric, items)
ranked compact scores
   ↓ agent writes report
```

In this composition the outer context never holds a file body *or* any raw item content. Without `describe_structure`, Map-Evaluate still relies on the agent already knowing what the items are and how many — which is exactly the schema-ascertainment gap this design fills. With both: bounded perception → bounded evaluation → bounded outer context.

**Honest non-equivalence.** Neither tool requires the other. Many `describe_structure` uses don't involve N-item scoring (just count, just identify format, just confirm a log's repeating prefix). Many Map-Evaluate uses don't involve unintelligible inputs (the agent already has a structured list). They're complementary *in workflows where both apply*, and each is independently useful otherwise.

**Design philosophy divergence to flag.** Map-Evaluate is firmly on the *flexibility* side (rubric-driven, output_fields configurable, concurrency tunable). `describe_structure` is firmly on the *reliability* side (one call, no knobs, no LLM inside the tool). The project deliberately maintains **both schools** — they are the right answers to different problems, not competing ideologies. This doc explicitly diverges from prior art's "small composable tools" philosophy because the failure mode being addressed is *guess-and-thrash*, which more knobs would worsen. Map-Evaluate's flexibility is right *for its problem*; this design's rigidity is right *for ours*.

---

## 13. Related

- [ADR-025 — Native filesystem tools](../architecture/decisions/ADR-025-native-filesystem-tools.md) — defines where this tool lives and how it's loaded.
- [ADR-024 — Single-layer tool-result truncation](../architecture/decisions/ADR-024-single-layer-tool-result-truncation.md) — `ToolResultOverrides` is where the body-incapable cap (`MaxChars`) is configured.
- [ISSUE-007 — Prose-contract drift across policy layers](../issues/ISSUE-007-prose-contract-drift-across-policy-layers.md) — the failure mode this design is responding to (LLM emergent behaviour across uncorrelated layers).
- [PLAN-behavioural-eval-suite](../planning/PLAN-behavioural-eval-suite.md) — the apparatus that surfaced the gap and verifies the fix.
- `tests/evals/test_count_job_items.py`, `test_count_jobs.py`, `test_count_jobs_structure_given.py` — the three scenarios that isolate schema-ascertainment as the gap. Commits `2cc453b`, `09c02a4`, `dc95719`.
- Anthropic — ["Code execution with MCP"](https://www.anthropic.com/engineering/code-execution-with-mcp) — best-practice articulation of the underlying pattern.
- [`universal-json-agent-mcp`](https://github.com/GautamVhavle/universal-json-agent) — prior art for body-free structural exploration (JSON-only).
