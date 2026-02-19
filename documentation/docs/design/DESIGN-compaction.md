# Design: Conversation Compaction

## Status

**Implemented** — via strategy pattern in `compaction.py`.

## Problem

The agent loop currently manages context with two blunt mechanisms:

1. **Per-result truncation** — `_truncate_tool_result()` clips individual tool outputs at `max_tool_result_chars` (40,000 chars). This happens at ingestion time and is irreversible.
2. **History trimming** — `_trim_conversation_history()` does a hard `del self._messages[:remove_count]` when `len(self._messages) > max_conversation_messages` (50). No summarization, no context preservation — old messages simply vanish.

This is problematic for multi-step tasks where earlier instructions, scoring criteria, and intermediate results are critical context. For example, when the user says "Execute the job search prompt from search-prompt.txt", the search criteria read from the file are essential for scoring decisions later. If those messages are trimmed, Claude loses the ability to apply the correct rubric.

There is also no token awareness. The 50-message limit is a count-based proxy that doesn't account for message size — 50 messages containing short text exchanges use far fewer tokens than 50 messages containing large tool results.

## Reference: OpenClaw

The [openclaw](https://github.com/nicobailey/openclaw) project (TypeScript) implements a sophisticated multi-layer compaction system:

- **Token estimation** — `estimateTokens()` on each message, accumulated totals
- **Adaptive chunking** — `splitMessagesByTokenShare()` divides messages into equal-token chunks; `chunkMessagesByMaxTokens()` splits by max tokens per chunk
- **Multi-stage summarization** — `summarizeInStages()`: split messages into N parts, summarize each, then merge summaries with "Merge these partial summaries into a single cohesive summary. Preserve decisions, TODOs, open questions, and any constraints."
- **Fallback strategy** — full summarization → partial (excluding oversized messages) → annotation-only ("Context contained N messages. Summary unavailable.")
- **Context window guard** — model context window awareness (200K default), hard minimum 16K, warning at 32K
- **Compaction reserve** — 20K tokens kept reserved for the compaction API call itself
- **Context pruning** — separate from compaction; truncates oversized tool results keeping head+tail, replaces with placeholder when ratio still too high
- **Overflow detection** — monitors for context overflow errors, auto-triggers compaction (up to 3 attempts), falls back to tool result truncation

Key constants: `BASE_CHUNK_RATIO=0.4`, `MIN_CHUNK_RATIO=0.15`, `SAFETY_MARGIN=1.2`

Source files: `src/agents/compaction.ts`, `src/agents/pi-embedded-runner/compact.ts`, `src/agents/context-window-guard.ts`

## Approach

**Single-pass LLM summarization** triggered by a token-estimate threshold. When estimated context exceeds a configurable limit, the "middle" of the conversation (between the first user message and the most recent N messages) is summarized by Claude into a concise narrative and injected back as a context summary. The old messages are replaced, freeing context budget while preserving key facts.

This adapts openclaw's core idea while keeping the implementation proportional to this micro agent's scope.

## Architecture

### New File: `compaction.py`

Uses a **strategy pattern** (matching the `Tool` Protocol pattern in `tool.py`). A `CompactionStrategy` Protocol defines `async def maybe_compact(messages) -> messages`. Two implementations:

- **`NoneCompactionStrategy`** — no-op, returns messages unchanged (backward-compatible default)
- **`SummarizeCompactionStrategy`** — single-pass LLM summarization of the conversation middle

The `AgentConfig` dataclass holds a `compaction_strategy: CompactionStrategy` field (the strategy object itself, not individual config fields for threshold/tail). Configuration details like `threshold_tokens` and `protected_tail_messages` are constructor parameters on `SummarizeCompactionStrategy`.

### Modified Files

| File | Change |
|------|--------|
| `agent_config.py` | Add `compaction_strategy: CompactionStrategy` field (default: `NoneCompactionStrategy`) |
| `agent.py` | Add `_maybe_compact()` which delegates to the strategy then runs `_trim_conversation_history()` as backstop; replace both `_trim_conversation_history()` calls in `run()` |
| `__main__.py` | Parse `CompactionStrategy`, `CompactionThresholdTokens`, `ProtectedTailMessages` from config; construct the appropriate strategy object |

### No Changes To

`llm_client.py`, `tool.py`, `system_prompt.py`, any tool implementations. Compaction is entirely within the orchestration layer.

## Algorithm

### Token Estimation

Walk all content blocks in each message dict:

| Content Type | Character Source |
|-------------|-----------------|
| String content | `len(content)` |
| `text` block | `len(block["text"])` |
| `tool_use` block | `len(block["name"]) + len(json.dumps(block["input"]))` |
| `tool_result` block | `len(block["content"])` (when content is a string) |

Divide total characters by 4 to get estimated tokens. This is the standard heuristic for English text with the Claude tokenizer.

### Trigger Decision

`Agent._maybe_compact()` is called at the same two points where `_trim_conversation_history()` previously ran (after adding a user message and after adding tool results). It delegates to the configured strategy, then runs `_trim_conversation_history()` as a hard backstop.

For `SummarizeCompactionStrategy.maybe_compact()`:

```
estimated tokens > threshold_tokens (80K)?
  No  → return unchanged
  Yes → compaction zone (messages[1] to messages[-tail]) has ≥ 1 message?
    No  → return unchanged (everything is protected)
    Yes → adjust boundary for tool pairs, summarize, rebuild
    On failure → log warning, return unchanged (backstop trim handles it)
```

### Message Protection

Three categories of messages are protected from compaction:

1. **`messages[0]`** (first user message) — always preserved. This establishes the task context. In the job search scenario, this is "Execute the job search prompt from search-prompt.txt".
2. **Last N messages** (`protected_tail_messages`, default 6) — always preserved. These are the most recent exchanges where active work is happening.
3. **Tool-use/result pairs** — the compaction boundary is adjusted so a `tool_use` block in an assistant message is never separated from its corresponding `tool_result` in the next user message.

Everything between index 1 and `len(messages) - protected_tail_messages` is the **compaction zone**.

### Boundary Adjustment

`_adjust_boundary()` checks the last message in the compaction zone. If it's an assistant message containing `tool_use` blocks, the boundary is pulled back so the corresponding `tool_result` message (which follows it in the protected tail) stays paired:

```python
while end > start + 1:
    boundary_msg = messages[end - 1]
    if boundary_msg is an assistant message with tool_use blocks:
        end -= 1  # Pull boundary back to keep the pair together
    else:
        break
```

### Summarization

1. **Convert** compactable messages to text with **tool result previews** — first 500 chars + last 200 chars of each tool result, not the full content. This dramatically reduces the input to the summarization call.

2. **Cap** summarization input at 100,000 characters. If exceeded, truncate from the middle with a marker.

3. **Call the configured LLM provider** (non-streaming via `provider.create_message()`, temperature=0, max_tokens=4096) with a focused summarization prompt:

```
Summarize the following conversation history between a user and an AI assistant.
Preserve these details precisely:
- The original user request and any specific criteria or instructions
- All decisions made and their reasoning
- Key data points, URLs, file paths, and identifiers that may be needed later
- Any scores, rankings, or evaluations produced
- Current task status and next steps

Do NOT include raw tool output data (job descriptions, email bodies, etc.) —
just note what was retrieved and key findings.

Format as a concise narrative summary.
```

The summarization call uses the same `model` and provider as the main agent. Retry logic is handled inside the provider's `create_message()` method.

4. **Return** the summary text.

### Message Reconstruction

After compaction, the message list is rebuilt:

```
[0] user: original request + "\n\n[CONTEXT SUMMARY]\n{summary}\n[END CONTEXT SUMMARY]"
[1] assistant: "Understood. Continuing with the current task."  (if needed for role alternation)
[2..N] Protected tail messages (unchanged)
```

The first user message and summary are merged into a single user message to avoid consecutive same-role messages. An assistant acknowledgment is inserted only if needed to maintain the strict role alternation required by the Anthropic API (i.e., if the first protected tail message is also a user-role message).

### Fallback

- If the summarization API call fails (network error, rate limit exhausted after retries), catch the exception, log to stderr, and fall back to `_trim_conversation_history()`.
- The existing `max_conversation_messages` trimming still runs as a hard backstop after compaction.

## Configuration

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `CompactionThresholdTokens` | int | 80,000 | Estimated token count that triggers compaction |
| `ProtectedTailMessages` | int | 6 | Recent messages to never compact (~3 exchange pairs) |
| `CompactionStrategy` | string | `"none"` | Strategy name: `"none"` or `"summarize"` |

Config JSON keys follow the existing PascalCase convention used in `config.json`. The strategy is constructed in `__main__.py` from these config values and passed as a single `compaction_strategy` object on `AgentConfig`. Omitting `CompactionStrategy` or setting `"none"` gives the old (no compaction) behavior.

**Rationale for defaults:**

- **80,000 tokens** — Claude Sonnet/Haiku have a 200K context window. 80K leaves room for the system prompt (~500 tokens), tool definitions (~2K tokens), the response (~8K tokens), and a comfortable margin. This is the "start worrying" threshold.
- **6 protected tail messages** — Protects the most recent 3 exchange pairs (user + assistant). In the job search scenario, this keeps the current scoring/writing activity in context.

## Job Search Scenario Walkthrough

For "Execute the job search prompt from search-prompt.txt":

### Single Search Round (~25-30K tokens)

Generates ~8-10 messages. The tool results from `linkedin_job_detail` and `gmail_read` are the biggest consumers (~10K chars each). Total is well under the 80K threshold. **No compaction triggers.**

### After 2-3 Rounds (~85K tokens)

The user refines criteria and searches again. Tokens hit ~85K. Compaction triggers.

**Compaction zone**: Messages 1-18 (the first two search rounds).
**Protected zone**: Messages 19-24 (current scoring/writing activity) + Message 0 (original request).

**What the summary captures:**
> "The user requested a job search based on criteria in search-prompt.txt: .NET developer, senior level, remote, £500-700/day. First search found 10 LinkedIn results and 7 JobServe emails. Detailed analysis of 5 positions: [Company A - Senior .NET Dev - scored 7/10, URL: ...], [Company B - ...]. Gmail alerts yielded 3 additional positions. Scoring rubric: technical stack match (30%), remote policy (20%), salary (25%), growth (25%). Report file created: todays-jobs-2026-02-17.md."

**What is discarded** (but was preserved in the summary):
- Full job descriptions (10K chars each) — summarized as company/title/score/URL
- Full email bodies — summarized as key findings
- Intermediate "I'll search now..." assistant messages

**Result**: Context drops from ~85K to ~10K tokens. All key facts preserved. Claude can continue scoring, writing, or searching with full awareness of what was already done.

### Critical Preservation

| Content | Where After Compaction |
|---------|----------------------|
| Search criteria / scoring rubric | In `messages[0]` (always protected as first user message) |
| Job scores and rankings | In the summary narrative |
| URLs and identifiers | In the summary narrative |
| Current task status | In protected tail messages |
| Full job descriptions | Discarded (can be re-fetched via tools if needed) |

## What This Omits vs OpenClaw

| OpenClaw Feature | Why Omitted |
|-----------------|-------------|
| Multi-stage chunked summarization | Single-pass is sufficient for our message volumes |
| Adaptive chunk sizing with token share | Unnecessary complexity for a micro agent |
| Context window guard with hard minimum | Simple threshold is enough |
| Compaction reserve calculation | Our summarization input is already small (previews, not full text) |
| Security stripping of toolResult.details | Our tool results are plain text, no separate `details` field |
| Overflow detection with retry loop | tenacity retry + trimming fallback covers this |
| Separate context pruning phase | Existing `_truncate_tool_result` handles per-result truncation |
| Plugin hooks (before/after compaction) | No plugin system in this project |

## Transparency

All compaction activity goes to stderr (matching the existing pattern):

```
  Compaction: estimated ~85,200 tokens, threshold 80,000 — compacting 18 messages
  Compaction: summarized 18 messages into ~800 tokens, freed ~72,000 estimated tokens
```

On failure:
```
  Warning: Compaction failed: {error}. Falling back to history trimming.
```

## Source Files

| File | Role |
|------|------|
| `compaction.py` | `CompactionStrategy` Protocol, `NoneCompactionStrategy`, `SummarizeCompactionStrategy`, helpers |
| `agent_config.py` | `compaction_strategy` field on `AgentConfig` |
| `agent.py` | `_maybe_compact()` method, integration into `run()` loop |
| `__main__.py` | Config parsing and strategy construction |
