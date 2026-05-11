# ADR-023: Truncation Signaling for File-Handling MCP Tools

## Status

Accepted — 2026-05-11

## Context

Four filesystem MCP tools (`read_file`, `grep`, `glob`, `bash`) can produce output larger than the caller asked for. Each has a cap:

| Tool | Default cap | Hard max |
|------|-------------|----------|
| `read_file` | 2,000 lines | 10,000 lines |
| `grep` | 250 matches | 5,000 matches |
| `glob` | 250 paths | 5,000 paths |
| `bash` | 10 MB stdout+stderr | (same) |

When the cap is hit, the model gets *some* output and the rest is dropped. Whether the model notices that a drop occurred — and whether it knows how to recover — depends entirely on the truncation signal in the tool response.

Prior behaviour had three problems:

1. **Soft signals at the wrong position.** `read_file` / `grep` / `glob` appended terse markers like `[truncated to 250 of 1834 — narrow the pattern]` at the end of the content. Model attention favours recent tokens (good), but the markers omitted the missing fraction in bytes/percent and didn't supply a literal recovery call (bad).
2. **A bash signalling bug.** `execFile`'s `maxBuffer` overflow shares `error.killed = true` with timeout-kills, so the bash tool mis-reported buffer overflow as `timed_out: true`. There was no `output_truncated` field and no in-band marker. A runaway command produced a misleading "your command timed out" — wrong cause, wrong recovery advice.
3. **No design rule.** Each tool's marker had grown independently. New tools (or upstream maintainers) had no template to follow.

The failure mode this creates is the worst kind for an agent: a confident, well-formatted, wrong answer drawn from partial data. The model has no way to know what it missed.

Upstream Anthropic has been working the same problem — [claude-code issue #22699](https://github.com/anthropics/claude-code/issues/22699) proposes a tiered model (silent below 500 lines, advisory between 500 and 2,000, hard refusal above 2,000) with pre-flight size checks. We adopt the signalling half of that proposal; pre-flight refusal is deferred (see Consequences).

## Decision

All file-handling MCP tools that can truncate output emit an in-band truncation marker following a single template. The marker has four properties:

1. **States that truncation happened**, in natural language the model will actually read. The word "truncated" plus a number appear in the response text — not only in `structuredContent` metadata, which intermediate layers may strip and which models weight less heavily than visible text.
2. **Quantifies what's missing.** Show what was returned vs. the total, in both count and (where meaningful) bytes, plus a percentage. The model needs the missing fraction to decide whether partial is enough.
3. **Supplies a literal recovery call.** The marker contains a copy-pasteable next call, not a description. `read_file(path="/x/y.log", offset=2001, limit=2000)` beats "use offset/limit to continue."
4. **Distinguishes cause** when retry strategy depends on it. Line cap vs. byte cap vs. process-killed-for-output vs. timeout drive different recoveries.

### Template

```
[Output truncated: <what was shown> of <what existed> (<percentage>, optionally <bytes shown of bytes total>).
 To <recovery verb>: <literal next tool call> — or <alternative narrowing advice>]
```

### Per-tool application

**`read_file`** (`mcp_servers/ts/packages/filesystem/src/tools/read-file.ts`)

```
[Output truncated: showed lines 1-2000 of 8431 (24%, 156KB of 642KB).
 To read more: read_file(path="/abs/path/y.log", offset=2001, limit=2000)]
```

**`grep`** (`mcp_servers/ts/packages/filesystem/src/tools/grep.ts`)

```
[Output truncated: showed first 250 of 1834 matches (14%).
 To see more: grep(pattern="...", path="...", head_limit=1834) — or narrow with glob/type/pattern]
```

**`glob`** (`mcp_servers/ts/packages/filesystem/src/tools/glob.ts`)

```
[Output truncated: showed first 250 of 7843 paths (3%).
 To see more: glob(pattern="...", path="...", head_limit=5000) — or narrow the pattern]
```

**`bash`** (`mcp_servers/ts/packages/filesystem/src/tools/bash.ts`)

```
[Output truncated: command emitted >10.0MB to stdout+stderr; output cut at the 10.0MB boundary and the process was killed.
 To capture more: redirect to a file (e.g., `command > /tmp/out.log 2>&1`) and use read_file with offset/limit,
 or narrow via head/tail/grep in the command itself]
```

`bash` also gains a dedicated `output_truncated: boolean` field on `structuredContent`, distinct from `timed_out`. The runCommand callback checks `error.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER_EXCEEDED"` *before* the generic `error.killed` branch, since maxBuffer overflows also set `killed`.

### Design rules

- **Marker position**: end of the content, not the beginning. Models attend more strongly to recent tokens; the marker must be the last thing the model sees before deciding what to do next.
- **`isError`**: truncation alone is not an error for the read-style tools (`read_file`, `grep`, `glob`) — the operation succeeded and returned valid (if partial) output. `bash` truncation *is* `isError: true` because the underlying process was killed before completing.
- **Empty results vs. truncated-to-zero**: distinct strings (`(no matches)` vs. a truncation marker). Conflating these is a documented source of silent wrong answers; the implementation paths are deliberately separate.
- **Continuation arithmetic is the tool's job, not the model's**: `read_file` computes `nextOffset = endLine + 1` and emits the literal call. The model never does pagination math.
- **No mid-record / mid-line truncation**: the existing tools are line-oriented and slice at line boundaries. If a future mode (head+tail, structured output) needs middle omission, the marker template extends to `[... N items omitted (positions X-Y) ...]` per the same in-band principle.

## Consequences

### Positive

- Truncation becomes visible. Soft-signal fidelity rises from "model may notice" to "model has the recovery call sitting in its context, ready to execute."
- Cross-tool consistency. New file-handling tools (or refactors of existing ones) have a single template to follow.
- `bash` overflow stops masquerading as a timeout. Misleading retry advice (`re-run with longer timeout`) is replaced with correct advice (`redirect output, then read_file`).
- Continuation calls eliminate API-recall failures, where the model knew it should continue but guessed the parameter name wrong.

### Negative

- Marker text adds 100–250 bytes to truncated responses. Negligible against the content size that triggered truncation in the first place.
- `output_truncated` is a new field on `bash`'s `structuredContent`. Existing callers parsing only `stdout`/`stderr`/`exit_code`/`timed_out` are unaffected; callers explicitly schema-validating against the old shape would need to accept the additional field.

### Open / deferred

- **Pre-flight refusal of unbounded reads on very large files** (claude-code issue #22699's >2,000-line tier) is not implemented here. The signalling improvements make silent partial answers much harder, but a determined model can still ignore the marker and answer from partial content. For higher reliability, a future ADR can add: (a) `stat` size check before reading, (b) refusal-with-guidance (not `isError`) when the caller did not pass explicit `limit` and the file exceeds a threshold, (c) intentional bypass when `offset` or `limit` is present.
- **Stateful continuation tokens** (truly model-can't-fake-having-read-this semantics) would require a stateful tool layer and are not in scope.
- **Other tools that could grow output caps** (e.g. future log-tailing, directory-listing-with-content tools) should adopt the template before shipping.

## References

- [claude-code issue #22699 — Size-aware file reading](https://github.com/anthropics/claude-code/issues/22699) — Anthropic's pre-flight + tiered-refusal proposal; we adopt the signalling principles, defer the refusal tier.
- ADR-014 — Structured tool results: this ADR layers human-readable markers on top of structured `truncated` / `output_truncated` fields. Both are present; the in-band text is the primary signal for the model.
