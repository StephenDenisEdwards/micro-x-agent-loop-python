# ISSUE-003: Ollama Tool Calling

## Working Example: Session `3d36e2ed-001d-41d6-b334-31391c4afbb3`

A successful end-to-end Ollama tool-calling session observed on 2026-03-23.

### Session Summary

| Field | Value |
|-------|-------|
| **Duration** | ~1 min 35s (13:12:16 → 13:13:51) |
| **Configured Model** | claude-sonnet-4-5-20250929 |
| **Actual Model Used** | qwen2.5:7b (Ollama, all 3 calls) |
| **Cost** | $0.00 (local model) |

### Config

Config file: `config-testing-semantic-routing-local-4.json`

```json
{
  "Base": "config-base.json",
  "PerTurnRoutingEnabled": false,
  "RoutingFeedbackEnabled": false,
  "SemanticRoutingEnabled": true,
  "SemanticRoutingStrategy": "rules+keywords",
  "RoutingPolicies": {
    "trivial":           { "provider": "ollama", "model": "qwen2.5:7b", "tool_search_only": true, "system_prompt": "compact", "pin_continuation": true },
    "conversational":    { "provider": "ollama", "model": "qwen2.5:7b", "tool_search_only": true, "system_prompt": "compact", "pin_continuation": true },
    "factual_lookup":    { "provider": "ollama", "model": "qwen2.5:7b", "tool_search_only": true, "system_prompt": "compact", "pin_continuation": true },
    "summarization":     { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
    "code_generation":   { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929", "pin_continuation": true },
    "code_review":       { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929", "pin_continuation": true },
    "analysis":          { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929", "pin_continuation": true },
    "tool_continuation": { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" },
    "creative":          { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" }
  },
  "CompactionThresholdTokens": 2000,
  "LogLevel": "DEBUG"
}
```

Key config details:
- **Semantic routing** enabled with `rules+keywords` strategy (no LLM classifier call)
- **Three task types routed to Ollama**: trivial, conversational, factual_lookup — all with `tool_search_only`, `compact` system prompt, and `pin_continuation`
- **Remaining task types** stay on Anthropic (Haiku for summarization, Sonnet for everything else)

### Conversation Flow

1. **User**: `"list my files"`
2. **Assistant**: Called `tool_search` with query `"list files"` — semantic classifier routed as `factual_lookup` to Ollama/qwen2.5:7b
3. **Tool result**: Returned 5 matching tools (github\_\_get\_file, filesystem\_\_bash, interview-assist list, github\_\_list\_repos, filesystem\_\_...)
4. **Assistant**: Called `filesystem__bash` with command `dir` — routing **pinned** to ollama/qwen2.5:7b (`pin_continuation` from iteration 0)
5. **Tool result**: Directory listing of `C:\Users\steph\source\repos\resources\documents`
6. **Assistant**: Returned formatted file listing to user

### API Call Metrics (3 calls)

| # | Call Type | Duration | TTFT | Stop Reason | Msgs | Tools |
|---|-----------|----------|------|-------------|------|-------|
| 1 | `semantic:factual_lookup` | 6.98s | 0ms | tool_use | 1 | 2 |
| 2 | `pinned:ollama/qwen2.5:7b` | 7.71s | 0ms | tool_use | 3 | 7 |
| 3 | `pinned:ollama/qwen2.5:7b` | 71.68s | 4.0s | end_turn | 5 | 7 |

### Observations

1. **Semantic routing worked** — the classifier correctly identified `"list my files"` as a `factual_lookup` task and routed to the cheap local model instead of Claude Sonnet.

2. **Pin continuation engaged** — after the initial routing decision, subsequent calls within the same turn stayed pinned to `ollama/qwen2.5:7b`, as expected.

3. **Call #3 was very slow (71.7s)** — the final response generation where the model formatted the directory listing. The 4s TTFT and 71.7s total duration suggest qwen2.5:7b struggled with the large tool result (~1400 tokens). This is likely due to Ollama processing the full context locally.

4. **Token counts are all zero** — Ollama's OpenAI-compatible API is not reporting token usage. Cost tracking and token metrics are blind for Ollama-routed calls. May need to parse `usage` from Ollama's response differently or estimate tokens.

5. **Tool search as first step** — the agent used `tool_search` before picking `filesystem__bash`, showing the on-demand tool discovery flow is working. The tool set expanded from 2 schemas (just `tool_search` + `ask_user`) to 7 after discovery.

## Working Example: Session `f24fa307-c711-49ae-99dd-8f87e520ad1c`

A two-turn Ollama session observed on 2026-03-23. Turn 1 succeeds (repeatability check vs session `3d36e2ed`). Turn 2 exposes a routing quality issue.

### Session Summary

| Field | Value |
|-------|-------|
| **Duration** | ~8 min 15s (13:26:12 → 13:34:27) |
| **Configured Model** | claude-sonnet-4-5-20250929 |
| **Actual Model Used** | qwen2.5:7b (Ollama, 4 calls) + claude-haiku-4-5 (1 classification call) |
| **Total Cost** | $0.0005 (Haiku classification only) |

### Config

Same config as session `3d36e2ed` above: `config-testing-semantic-routing-local-4.json`

### Turn 1: "list my files" (success)

#### Conversation Flow

1. **User**: `"list my files"`
2. **Assistant**: Called `tool_search` with query `"list files"` — semantic classifier routed as `factual_lookup` to Ollama/qwen2.5:7b
3. **Tool result**: Returned 5 matching tools (github\_\_get\_file, filesystem\_\_bash, interview-assist list, github\_\_list\_repos, filesystem\_\_write\_file)
4. **Assistant**: Called `filesystem__bash` with command `dir` — routing **pinned** to ollama/qwen2.5:7b (`pin_continuation` from iteration 0)
5. **Tool result**: Directory listing of `C:\Users\steph\source\repos\resources\documents`
6. **Assistant**: Returned formatted file listing to user

#### API Call Metrics

| # | Call Type | Duration | TTFT | Stop Reason | Msgs | Tools | Cost |
|---|-----------|----------|------|-------------|------|-------|------|
| 1 | `semantic:factual_lookup` | 15.92s | 0ms | tool_use | 1 | 2 | $0.00 |
| 2 | `pinned:ollama/qwen2.5:7b` | 8.77s | 0ms | tool_use | 3 | 7 | $0.00 |
| 3 | `pinned:ollama/qwen2.5:7b` | 80.14s | 4.4s | end_turn | 5 | 7 | $0.00 |

#### Observations

1. **Reproducible** — identical prompt, identical routing decision (`factual_lookup` → Ollama), identical tool-calling sequence (`tool_search` → `filesystem__bash`). The routing is deterministic with `rules+keywords`.

2. **Call #1 was slower (15.9s vs 7.0s)** — the first API call took over twice as long as the equivalent call in session `3d36e2ed`. Likely Ollama model was cold-loaded (evicted from GPU memory between sessions).

3. **Call #3 still dominates (80.1s)** — the final response generation remains the bottleneck, slightly worse than the prior session (80.1s vs 71.7s). TTFT was comparable (4.4s vs 4.0s).

4. **Token counts still zero** — confirms the Ollama token reporting gap is systematic, not a one-off.

### Turn 2: "list last 10 emails" (failure)

#### Conversation Flow

1. **User**: `"list last 10 emails"`
2. **Rules+keywords classifier**: Could not classify — fell through to **Stage 2 LLM classification**
3. **Haiku classification call**: Classified as `trivial` (12.1s, $0.0005, 305 input / 40 output tokens)
4. **Assistant** (Ollama/qwen2.5:7b): Responded with a vague non-answer about needing `.eml` or `.txt` files and `dir` not filtering by email content. **Did not call any tools** — just gave up with `end_turn`.

#### API Call Metrics

| # | Call Type | Provider/Model | Duration | TTFT | Stop Reason | Msgs | Tools | Cost |
|---|-----------|----------------|----------|------|-------------|------|-------|------|
| 4 | `stage2_classification` | anthropic/haiku-4.5 | 12.12s | 0ms | — | 1 | 0 | $0.0005 |
| 5 | `semantic:trivial` | ollama/qwen2.5:7b | 23.83s | 10.6s | end_turn | 7 | 2 | $0.00 |

#### Observations

1. **Routing quality issue** — "list last 10 emails" was classified as `trivial` but it's actually a `factual_lookup` that needs tool access (e.g. Gmail MCP). The `trivial` policy gave qwen2.5:7b only 2 tool schemas (`tool_search` + `ask_user`), but the model didn't even attempt `tool_search` to discover email tools.

2. **Stage 2 fallback worked mechanically** — when rules+keywords couldn't classify, the system correctly fell back to Haiku for LLM classification. But Haiku's classification was wrong (`trivial` instead of `factual_lookup`).

3. **Pin continuation did NOT engage on turn 2** — correct behaviour, since `pin_continuation` only latches within a single turn, and this was a new turn.

4. **TTFT degraded (10.6s)** — much worse than turn 1's 4.4s, likely because of the larger message history (7 messages vs 5).

5. **qwen2.5:7b lacks initiative** — even with `tool_search` available, the model chose to respond with text rather than searching for email-related tools. This suggests small models may not reliably use tool_search without stronger prompting.

### Comparison: Turn 1 across Sessions

**Config**: Both sessions used the same config file (`config-testing-semantic-routing-local-4.json`), same configured model (`claude-sonnet-4-5-20250929`), same routing policies. Sessions are 14 minutes apart (13:12 vs 13:26) on the same day. The database does not store the config file path, but identical routing behaviour (same classification, same tool schema counts 2→7, same stop reasons) confirms the same configuration.

**Performance** (turn 1 only):

| Metric | Session `3d36e2ed` | Session `f24fa307` | Delta |
|--------|--------------------|--------------------|-------|
| Total duration | ~95s | ~125s | +30s |
| Call 1 (classify + tool_search) | 6.98s | 15.92s | +8.94s (cold start?) |
| Call 2 (tool use) | 7.71s | 8.77s | +1.06s |
| Call 3 (final response) | 71.68s | 80.14s | +8.46s |
| TTFT (call 3) | 4.0s | 4.4s | +0.4s |

**Conclusion**: No functional or config differences for turn 1 — only timing variance, most likely due to Ollama cold-start. Turn 2 reveals classification accuracy and small-model initiative as areas for improvement.

## Working Example: Session `77cc4235-42a7-41ae-8a6a-c77fd8463ed5`

Retry of the failed "list last 10 emails" prompt from session `f24fa307` turn 2, this time on a **fresh session** (`/session new`). Observed on 2026-03-23. **This time it succeeded.**

### Session Summary

| Field | Value |
|-------|-------|
| **Duration** | ~1 min 16s (13:37:57 → 13:39:13) |
| **Configured Model** | claude-sonnet-4-5-20250929 |
| **Actual Model Used** | qwen2.5:7b (Ollama, 3 calls) + claude-haiku-4-5 (1 classification call) |
| **Total Cost** | $0.0005 (Haiku classification only) |

### Config

Same config as previous sessions: `config-testing-semantic-routing-local-4.json`

### Conversation Flow

1. **User**: `"list last 10 emails"`
2. **Haiku stage 2 classification** (1.44s) — rules+keywords couldn't classify, fell through to Haiku. Classified as `trivial`.
3. **Assistant** (Ollama/qwen2.5:7b): Called `tool_search` with query `"email list"` — discovered 5 tools including `google__gmail_search`
4. **Assistant** (pinned): Called `google__gmail_search` with `query: "label:drafts", maxResults: 10`
5. **Tool result**: Returned 10 email drafts in table format
6. **Assistant**: Formatted and returned 10 email summaries to user

### API Call Metrics (4 calls)

| # | Call Type | Provider/Model | Duration | TTFT | Stop Reason | Msgs | Tools | Cost |
|---|-----------|----------------|----------|------|-------------|------|-------|------|
| 1 | `stage2_classification` | anthropic/haiku-4.5 | 1.44s | 0ms | — | 1 | 0 | $0.0005 |
| 2 | `semantic:trivial` | ollama/qwen2.5:7b | 6.73s | 0ms | tool_use | 1 | 2 | $0.00 |
| 3 | `pinned:ollama/qwen2.5:7b` | ollama/qwen2.5:7b | 9.69s | 0ms | tool_use | 3 | 7 | $0.00 |
| 4 | `pinned:ollama/qwen2.5:7b` | ollama/qwen2.5:7b | 32.49s | 3.2s | end_turn | 5 | 7 | $0.00 |

### Observations

1. **Clean session fixed the tool-calling failure** — the same prompt that failed in session `f24fa307` turn 2 (where qwen2.5:7b gave up without calling any tools) succeeded here. The only structural difference is that this was a fresh session with no prior message history.

2. **Classification was identical** — Haiku classified as `trivial` in both cases. Both had only 2 tool schemas available (`tool_search` + `ask_user`). The routing path was the same — the difference was entirely in qwen2.5:7b's behaviour.

3. **Context pollution confirmed** — with 7 messages of prior context (session `f24fa307` turn 2), qwen2.5:7b failed to use `tool_search`. With 1 message (clean session), it succeeded. Small models are sensitive to context size and get confused/distracted by prior conversation history.

4. **Query was wrong** — the model searched `"label:drafts"` instead of inbox, returning drafts not the last 10 received emails. The user got results but not exactly what they asked for. This is a model quality issue with qwen2.5:7b's understanding of the prompt.

5. **Haiku was much faster** — classification took 1.44s vs 12.12s in session `f24fa307`. Likely Anthropic API was warm/cached.

6. **Final response was faster (32.5s vs 80s in prior sessions)** — the email result (~1175 tokens) was lighter than the `dir` listing (~1406 tokens), and the total context was smaller.

### Comparison: "list last 10 emails" — Failed vs Succeeded

| Aspect | `f24fa307` turn 2 (failed) | `77cc4235` (succeeded) |
|--------|---------------------------|------------------------|
| Message history at prompt time | 7 msgs (prior turn context) | 1 msg (clean session) |
| Stage 2 classification result | `trivial` | `trivial` (same) |
| Tool schemas available | 2 (tool_search + ask_user) | 2 (same) |
| Ollama behaviour | Gave up, no tool calls | Called `tool_search` → `gmail_search` |
| Haiku classification latency | 12.12s | 1.44s |
| TTFT (final Ollama call) | 10.6s | 3.2s |
| Outcome | Vague non-answer | 10 emails listed (wrong label) |

### Key Takeaway

The failure in session `f24fa307` turn 2 was **not a routing problem** — the classification and tool availability were identical. It was a **small-model context sensitivity problem**: qwen2.5:7b with a longer message history chose not to use its available tools. This suggests that for multi-turn sessions routed to small models, either (a) conversation history should be compacted more aggressively, or (b) the system prompt should more strongly direct the model to use `tool_search` when it cannot answer directly.

## Conclusions

### What works

1. **Semantic routing is functional** — rules+keywords correctly classifies simple prompts (`factual_lookup`) and routes to Ollama, saving 100% on API costs for those calls.
2. **Pin continuation works** — once routed to Ollama, subsequent calls within the same turn stay pinned. No mid-turn model switches.
3. **Tool search + discovery works** — qwen2.5:7b can use `tool_search` to discover tools and then call them correctly (at least on clean sessions).

### What's broken or needs improvement

1. **Context pollution kills small-model tool-calling** — qwen2.5:7b with 7 messages of history failed to use `tool_search`, but succeeded with 1 message. This is the biggest issue. Possible fixes:
   - More aggressive compaction for Ollama-routed turns
   - Stronger system prompt directive to always use `tool_search` when the model can't answer directly
   - Reset/trim history when routing to a small model

2. **Stage 2 classification accuracy** — Haiku classified "list last 10 emails" as `trivial` when it's actually `factual_lookup`. Both `trivial` and `factual_lookup` route to Ollama in this config so the model/tools are the same, but in a config where they differ this misclassification could matter.

3. **Ollama token reporting is blind** — all token counts are zero across every Ollama call. Cost tracking, context window management, and compaction thresholds can't work properly without token counts.

4. **Performance is slow** — final response generation takes 32–80s on qwen2.5:7b. TTFT degrades with context size (3.2s → 4.4s → 10.6s). For a "trivial" task this is worse UX than just paying for a fast Haiku call.

5. **Model quality gaps** — qwen2.5:7b searched `"label:drafts"` instead of inbox. It completed the task but answered the wrong question.

### Strategic question

Is routing trivial/conversational/factual_lookup to a local 7B model actually worth it? The cost savings are real ($0.00 vs ~$0.001 per Haiku call) but the trade-offs are significant: 10–80x slower, unreliable tool-calling in multi-turn, wrong query construction, and zero observability. Haiku would likely have completed all three sessions correctly in under 5 seconds each.

## Haiku Baseline: Session `76480d4e-85ce-4303-b84b-fdad2ee197df`

Same two prompts ("list my files" then "list last 10 emails") run in the **same session** (no `/session new`) using an all-Haiku config. This serves as the baseline comparison against the Ollama sessions above.

### Session Summary

| Field | Value |
|-------|-------|
| **Duration** | ~45s total (13:52:29 → 13:53:14) |
| **Model** | claude-haiku-4-5-20251001 (all calls) |
| **Total Cost** | $0.038 |
| **Total API Calls** | 7 |
| **Total Input Tokens** | 33,169 |
| **Total Output Tokens** | 975 |

### Config

Config file: `config-testing-haiku-baseline.json`

```json
{
  "Base": "config-base.json",
  "Model": "claude-haiku-4-5-20251001",
  "PerTurnRoutingEnabled": false,
  "RoutingFeedbackEnabled": false,
  "SemanticRoutingEnabled": true,
  "SemanticRoutingStrategy": "rules+keywords",
  "RoutingPolicies": {
    "trivial":           { "provider": "anthropic", "model": "claude-haiku-4-5-20251001", "tool_search_only": true, "pin_continuation": true },
    "conversational":    { "provider": "anthropic", "model": "claude-haiku-4-5-20251001", "tool_search_only": true, "pin_continuation": true },
    "factual_lookup":    { "provider": "anthropic", "model": "claude-haiku-4-5-20251001", "tool_search_only": true, "pin_continuation": true },
    "summarization":     { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
    "code_generation":   { "provider": "anthropic", "model": "claude-haiku-4-5-20251001", "pin_continuation": true },
    "code_review":       { "provider": "anthropic", "model": "claude-haiku-4-5-20251001", "pin_continuation": true },
    "analysis":          { "provider": "anthropic", "model": "claude-haiku-4-5-20251001", "pin_continuation": true },
    "tool_continuation": { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
    "creative":          { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" }
  },
  "CompactionThresholdTokens": 4000,
  "LogLevel": "DEBUG"
}
```

### Turn 1: "list my files" (success)

#### Conversation Flow

1. **User**: `"list my files"`
2. **Assistant**: "I'll list the files in your current directory." + called `tool_search` with query `"list files directory"`
3. **Tool result**: 5 matching tools (filesystem\_\_bash, github\_\_get\_file, filesystem\_\_write\_file, filesystem\_\_save\_memory, ...)
4. **Assistant**: "Now I'll list your files using a Windows directory command:" + called `filesystem__bash` with `dir /B`
5. **Tool result**: Clean file listing (bare names, no metadata — smarter than Ollama's `dir`)
6. **Assistant**: Returned **categorised** file listing (Documents & Reports, Code & Projects, etc.)

#### API Call Metrics

| # | Call Type | Duration | TTFT | Stop Reason | Input | Output | Cost |
|---|-----------|----------|------|-------------|-------|--------|------|
| 1 | `semantic:factual_lookup` | 1.27s | 890ms | tool_use | 2,978 | 66 | $0.0033 |
| 2 | `pinned:anthropic/haiku-4.5` | 1.30s | 718ms | tool_use | 3,964 | 68 | $0.0043 |
| 3 | `pinned:anthropic/haiku-4.5` | 2.77s | 766ms | end_turn | 4,554 | 292 | $0.0060 |

**Turn 1 total: 5.33s, $0.0136**

### Turn 2: "list last 10 emails" (success with recovery)

#### Conversation Flow

1. **User**: `"list last 10 emails"`
2. **Assistant**: Called `tool_search` with query `"email read messages"` — discovered gmail tools
3. **Assistant**: "I'll read your last 10 emails:" + called `email_summary__email_summary`
4. **Tool error**: `email_summary` MCP server failed to start (`WinError 193`)
5. **Assistant**: "The email tool encountered an error. Let me check if there's an existing email summary file:" + called `filesystem__read_file` with `todays_emails.md`
6. **Tool result**: Email summary markdown file from Feb 19, 2026
7. **Assistant**: Returned formatted list of last 10 emails with subjects, senders, and snippets

#### API Call Metrics

| # | Call Type | Duration | TTFT | Stop Reason | Input | Output | Cost |
|---|-----------|----------|------|-------------|-------|--------|------|
| 4 | `semantic:trivial` | 1.20s | 0ms | tool_use | 4,124 | 56 | $0.0044 |
| 5 | `pinned:anthropic/haiku-4.5` | 1.13s | 797ms | tool_use | 5,039 | 51 | $0.0053 |
| 6 | `pinned:anthropic/haiku-4.5` | 1.19s | 657ms | tool_use | 5,154 | 83 | $0.0056 |
| 7 | `pinned:anthropic/haiku-4.5` | 4.45s | 625ms | end_turn | 7,356 | 359 | $0.0092 |

**Turn 2 total: 7.97s, $0.0244**

### Observations

1. **Both turns succeeded in the same session** — unlike Ollama, Haiku handled the multi-turn case without issue. The 7-message history that caused qwen2.5:7b to give up was no problem for Haiku.

2. **Error recovery** — when `email_summary__email_summary` failed (MCP server crash), Haiku immediately pivoted to reading an existing email summary file. qwen2.5:7b in the same failure scenario would likely have given up.

3. **Classification was the same** — "list last 10 emails" was still classified as `trivial` (not `factual_lookup`). The misclassification didn't matter because Haiku used `tool_search` regardless.

4. **Smarter tool usage** — Haiku used `dir /B` (bare format) instead of `dir`, producing cleaner output. It also categorised the file listing into logical groups rather than just echoing the raw list.

5. **Token reporting works** — full visibility into input/output tokens for every call. Cost tracking is accurate.

6. **No stage 2 classification needed** — the rules+keywords classifier handled both prompts without falling through to an LLM classification call (unlike the Ollama sessions where "list last 10 emails" required a Haiku stage 2 call).

### Head-to-Head: Ollama vs Haiku

| Metric | Ollama (qwen2.5:7b) | Haiku (claude-haiku-4.5) | Factor |
|--------|---------------------|--------------------------|--------|
| **Turn 1 duration** | 95–125s | 5.3s | **18–24x faster** |
| **Turn 2 duration** | 24–36s (failed/partial) | 8.0s (succeeded) | **3–4x faster + correct** |
| **Turn 2 multi-turn** | Failed (context pollution) | Succeeded | — |
| **Error recovery** | N/A | Automatic fallback | — |
| **Turn 1 cost** | $0.00 | $0.014 | — |
| **Turn 2 cost** | $0.0005 (classification) | $0.024 | — |
| **Total cost** | $0.0005 | $0.038 | **76x more expensive** |
| **Token visibility** | Zero (all blind) | Full | — |
| **Output quality** | Raw list / wrong query | Categorised / error recovery | — |
| **TTFT (worst)** | 10.6s | 890ms | **12x faster** |

## Optimal Anthropic Config: Session `7e366d5c-b585-48e2-bc00-1b726e2a8508`

A 5-turn, multi-task session using `config-optimal-anthropic.json` — Haiku for simple tasks, Sonnet for complex ones. This session tests the cost/quality split across varied workloads.

### Session Summary

| Field | Value |
|-------|-------|
| **Duration** | ~10 min (15:02:52 → 15:12:39) |
| **Messages** | 30 (15 user, 15 assistant) |
| **API Calls** | 17 |
| **Total Input Tokens** | 329,112 |
| **Total Output Tokens** | 6,574 |
| **Cache Created** | 37,990 tokens |
| **Cache Read** | 94,975 tokens |
| **Total Cost** | **$0.879** |

### Config

Config file: `config-optimal-anthropic.json` — Haiku for trivial/conversational/factual\_lookup/summarization, Sonnet for code/analysis/creative/tool\_continuation. Semantic routing with `rules+keywords` strategy, routing feedback enabled.

### Turn-by-Turn Breakdown

| Turn | User Prompt | Classification | Model | API Calls | Duration | Cost |
|------|-------------|----------------|-------|-----------|----------|------|
| 1 | "list this weeks appointments" | `factual_lookup` | Haiku | 3 | 5.4s | $0.014 |
| 2 | "list all emails regarding payments..." | `trivial` (stage 2) | Haiku | 4 | 11.5s | $0.020 |
| 3 | "for all urgent action emails provide a summary..." | `creative` (stage 2) | Sonnet | 2 | 25.7s | $0.179 |
| 4 | "list my repositories" | `factual_lookup` | Haiku | 3 | 8.0s | $0.089 |
| 5 | "summarise each" | `summarization` → `tool_continuation` | Haiku → Sonnet | 4 | 83.7s | $0.577 |

### Per-Call Detail

| # | Turn | Call Type | Model | Input | Output | Cache Create | Cache Read | Duration | Cost |
|---|------|-----------|-------|-------|--------|-------------|------------|----------|------|
| 1 | 1 | `semantic:factual_lookup` | Haiku | 2,858 | 73 | 0 | 0 | 2.0s | $0.003 |
| 2 | 1 | `pinned:haiku` | Haiku | 4,173 | 154 | 0 | 0 | 1.8s | $0.005 |
| 3 | 1 | `pinned:haiku` | Haiku | 4,696 | 144 | 0 | 0 | 1.6s | $0.005 |
| 4 | 2 | `stage2_classification` | Haiku | 310 | 39 | 0 | 0 | 1.4s | $0.001 |
| 5 | 2 | `semantic:trivial` | Haiku | 3,823 | 70 | 0 | 0 | 3.9s | $0.004 |
| 6 | 2 | `pinned:haiku` | Haiku | 4,813 | 104 | 0 | 0 | 1.2s | $0.005 |
| 7 | 2 | `pinned:haiku` | Haiku | 8,493 | 380 | 0 | 0 | 5.2s | $0.010 |
| 8 | 3 | `stage2_classification` | Haiku | 314 | 30 | 0 | 0 | 1.4s | $0.000 |
| 9 | 3 | `semantic:creative` | **Sonnet** | 5,667 | 278 | **18,995** | 0 | 6.8s | **$0.092** |
| 10 | 3 | `tool_continuation` | **Sonnet** | 23,697 | 695 | 0 | **18,995** | 18.9s | $0.087 |
| 11 | 4 | `semantic:factual_lookup` | Haiku | 26,929 | 71 | 0 | 0 | 1.6s | $0.027 |
| 12 | 4 | `pinned:haiku` | Haiku | 28,285 | 64 | 0 | 0 | 1.4s | $0.029 |
| 13 | 4 | `pinned:haiku` | Haiku | 30,171 | 547 | 0 | 0 | 5.0s | $0.033 |
| 14 | 5 | `semantic:summarization` | Haiku | 27,100 | 740 | **18,995** | 0 | 4.4s | $0.055 |
| 15 | 5 | `tool_continuation` | **Sonnet** | 46,595 | 422 | 0 | **18,995** | 9.4s | $0.152 |
| 16 | 5 | `tool_continuation` | **Sonnet** | 51,844 | 2,453 | 0 | **18,995** | 62.2s | **$0.198** |
| 17 | 5 | `tool_continuation` | **Sonnet** | 54,344 | 250 | 0 | **18,995** | 7.7s | $0.172 |

### Cost by Model

| Model | Calls | Input Tokens | Output Tokens | Cache Created | Cache Read | Cost | % |
|-------|-------|-------------|---------------|---------------|------------|------|---|
| **Haiku 4.5** | 12 | 146,965 | 2,476 | 18,995 | 0 | $0.200 | **23%** |
| **Sonnet 4.5** | 5 | 182,147 | 4,098 | 18,995 | 94,975 | $0.702 | **77%** |
| **Total** | **17** | **329,112** | **6,574** | **37,990** | **94,975** | **$0.879** | |

### Observations

1. **Routing worked correctly** — simple lookups (appointments, repos, emails) went to Haiku. The summary and email-detail tasks escalated to Sonnet. The system correctly identified "summarise each" as needing Sonnet via `tool_continuation`.

2. **Prompt caching is working** — 18,995 tokens cached on turn 3, then read 4 times (turns 3, 5×3). That's 94,975 cache-read tokens at $0.30/MTok instead of $3.00/MTok input — saving roughly **$0.26** on this session alone.

3. **Turn 5 dominates cost ($0.577 / 66%)** — "summarise each" triggered 10 parallel `github__get_file` calls, then 5 more, generating ~19K tokens of tool results. Sonnet then processed 50K+ input tokens across 3 continuation calls. This is where the money goes.

4. **Haiku input tokens grow fast** — by turn 4, Haiku is processing 26–30K input tokens per call ($0.027–0.033 each). The conversation history accumulates. Compaction hasn't triggered yet (threshold is 80K).

5. **Turn 4 is expensive for what it does** — "list my repositories" is a simple `factual_lookup` but costs $0.089 because the conversation history is already ~28K tokens. Each Haiku call at that point costs more than the entire turn 1.

6. **Stage 2 classification cost is negligible** — $0.001 total for 2 classification calls. Worth it for routing accuracy.

### Cost-Saving Opportunities

1. **Earlier compaction** — by turn 4, Haiku is re-processing 28K tokens of history for a simple lookup. Compacting after turn 3 would cut turn 4–5 Haiku costs significantly.

2. **Prompt caching on Haiku calls** — cache creation happened on Sonnet calls but not Haiku. If Haiku calls also cached the system prompt/history, the repeated 28K input would be much cheaper ($0.10/MTok read vs $1.00/MTok input).

3. **Tool result summarization** — turn 5 pulled 15K+ tokens of GitHub file content. Summarizing tool results before feeding back would reduce Sonnet's input costs on continuation calls.

### Changes Made

#### 1. Config: `config-optimal-anthropic.json`

- **`CompactionThresholdTokens`**: 80,000 → **25,000** — triggers compaction much earlier, preventing Haiku from re-processing 28K+ tokens of stale history on simple lookups.
- **`ToolResultSummarizationEnabled`**: `false` → **`true`** — summarizes tool results over 4,000 tokens before feeding them back to the LLM, reducing input costs on continuation calls (e.g. the 15K+ GitHub content in turn 5).

#### 2. Code: Conversation history caching (`anthropic_provider.py`)

**Problem**: Haiku calls with `tool_search_only: true` get only 2 tool schemas. The cached prefix (system prompt + 2 tools) was under Anthropic's 2,048 token minimum for Haiku, so `cache_control` markers were silently ignored. Sonnet calls with 99 tool schemas easily exceeded the minimum, which is why only Sonnet got cache hits.

**Fix**: Added a third cache breakpoint on the **last message** in the conversation. Anthropic allows up to 4 breakpoints; we now use 3:

```
Before (2 breakpoints):
  [system prompt + cache_control] → [last tool + cache_control] → [messages...]

After (3 breakpoints):
  [system prompt + cache_control] → [last tool + cache_control] → [messages... + last msg cache_control]
```

On iteration 2+ within a turn, the entire prefix (system + tools + all prior messages) gets cached. Even with only 2 tool schemas, once the conversation grows past 2,048 tokens the cache kicks in. The last message content block is patched with `cache_control: {type: "ephemeral"}` — handles both `list[dict]` content (patches last block) and `str` content (wraps in a text block).

**Expected impact on session `7e366d5c`**: Turn 4's three Haiku calls re-processed 26–30K tokens each at $1.00/MTok. With message caching, iterations 2 and 3 would read ~26K from cache at $0.10/MTok — saving roughly **$0.05 per multi-iteration Haiku turn**.

**Validation**: mypy clean, 1355 tests passing.

## Replay Comparison: Before vs After Optimisation

The same 5 prompts were replayed in a new session (`d99b8057`) using the optimised config and caching code change, then compared against the original session (`7e366d5c`).

### Prompts (identical in both sessions)

1. `"list this weeks appointments"`
2. `"list all emails regarding payments, late payments, credit cards and so forth"`
3. `"for all the urgent action emails provide a brief summary and include any links or email links etc"`
4. `"list my repositories"`
5. `"summurise each"`

### Session `d99b8057` — Per-Call Detail

| # | Turn | Call Type | Model | Input | Output | Cache Create | Cache Read | Duration | Cost |
|---|------|-----------|-------|-------|--------|-------------|------------|----------|------|
| 1 | 1 | `semantic:factual_lookup` | Haiku | 2,979 | 80 | 0 | 0 | 1.6s | $0.0034 |
| 2 | 1 | `pinned:haiku` | Haiku | 5 | 158 | 4,296 | 0 | 1.6s | $0.0062 |
| 3 | 1 | `pinned:haiku` | Haiku | 5 | 147 | 527 | 4,296 | 1.4s | $0.0018 |
| 4 | 2 | `semantic:trivial` | Haiku | 3,958 | 67 | 0 | 0 | 1.5s | $0.0043 |
| 5 | 2 | `pinned:haiku` | Haiku | 5 | 109 | 5,640 | 0 | 1.3s | $0.0076 |
| 6 | 2 | `tool_summarization` | Sonnet | 3,677 | 514 | 0 | 0 | 9.0s | $0.0187 |
| 7 | 2 | `pinned:haiku` | Haiku | 4 | 389 | 631 | 5,640 | 3.2s | $0.0033 |
| 8 | 3 | `semantic:creative` | Sonnet | 3 | 279 | 4,808 | 16,992 | 4.5s | $0.0273 |
| 9 | 3 | `tool_summarization` | Sonnet | 1,444 | 216 | 0 | 0 | 5.0s | $0.0076 |
| 10 | 3 | `tool_summarization` | Sonnet | 8,949 | 329 | 0 | 0 | 10.0s | $0.0318 |
| 11 | 3 | `tool_summarization` | Sonnet | 3,786 | 279 | 0 | 0 | 11.2s | $0.0155 |
| 12 | 3 | `tool_continuation` | Sonnet | 7 | 840 | 4,801 | 21,800 | 13.9s | $0.0372 |
| 13 | 4 | `semantic:factual_lookup` | Haiku | 3 | 67 | 10,987 | 0 | 1.6s | $0.0141 |
| 14 | 4 | `pinned:haiku` | Haiku | 5 | 64 | 12,337 | 0 | 1.4s | $0.0157 |
| 15 | 4 | `tool_summarization` | Sonnet | 1,854 | 305 | 0 | 0 | 7.4s | $0.0101 |
| 16 | 4 | `pinned:haiku` | Haiku | 4 | 286 | 377 | 12,337 | 2.7s | $0.0031 |
| 17 | 5 | `semantic:summarization` | Haiku | 3 | 361 | 28,378 | 0 | 2.9s | $0.0373 |
| 18 | 5 | `tool_continuation` | Sonnet | 7 | 600 | 2,832 | 26,601 | 6.9s | $0.0276 |
| 19 | 5 | `tool_summarization` | Sonnet | 2,423 | 395 | 0 | 0 | 10.0s | $0.0132 |
| 20 | 5 | `tool_summarization` | Sonnet | 3,772 | 684 | 0 | 0 | 11.3s | $0.0216 |
| 21 | 5 | `tool_summarization` | Sonnet | 7,235 | 1,107 | 0 | 0 | 23.4s | $0.0383 |
| 22 | 5 | `tool_continuation` | Sonnet | 7 | 86 | 3,813 | 29,433 | 3.0s | $0.0244 |
| 23 | 5 | `tool_summarization` | Sonnet | 1,854 | 340 | 0 | 0 | 9.3s | $0.0107 |
| 24 | 5 | `tool_continuation` | Sonnet | 6 | 735 | 435 | 33,246 | 14.3s | $0.0226 |

### Cost by Model (After)

| Model | Calls | Input Tokens | Output Tokens | Cache Created | Cache Read | Cost | % |
|-------|-------|-------------|---------------|---------------|------------|------|---|
| **Haiku 4.5** | 10 | 6,971 | 1,728 | 63,173 | 22,273 | $0.097 | **24%** |
| **Sonnet 4.5** | 14 | 35,024 | 6,709 | 16,689 | 128,072 | $0.307 | **76%** |
| **Total** | **24** | **41,995** | **8,437** | **79,862** | **150,345** | **$0.404** | |

### Head-to-Head Comparison

| Metric | Before (`7e366d5c`) | After (`d99b8057`) | Delta |
|--------|--------------------|--------------------|-------|
| **Total Cost** | **$0.879** | **$0.404** | **-$0.475 (54% saving)** |
| API Calls | 17 | 24 | +7 (tool summarization) |
| Input Tokens | 329,112 | 41,995 | **-287,117 (87% reduction)** |
| Output Tokens | 6,574 | 8,437 | +1,863 (summarization output) |
| Cache Created | 37,990 | 79,862 | +41,872 (more caching) |
| Cache Read | 94,975 | 150,345 | +55,370 (more cache hits) |
| Haiku Cost | $0.200 | $0.097 | **-$0.103 (52% saving)** |
| Sonnet Cost | $0.702 | $0.307 | **-$0.395 (56% saving)** |
| Duration | ~134s | ~159s | +25s (summarization overhead) |

### What Drove the Savings

1. **Message caching on Haiku** — Haiku calls now show `cache_read` tokens (e.g. call #3: 4,296 read, call #7: 5,640 read, call #16: 12,337 read). Before, all Haiku cache columns were zero. The input tokens per Haiku call dropped from 26–30K to single digits on cached iterations.

2. **Tool result summarization** — 8 `tool_summarization` calls compressed large tool results before feeding them back. This is why input tokens dropped 87% (329K → 42K) even though output tokens increased slightly. The summarization calls themselves cost ~$0.17 total but saved far more by reducing downstream input costs.

3. **Compounding effect** — smaller tool results → smaller conversation history → smaller input on every subsequent call. The savings compound across turns.

### Trade-offs

- **+25s wall time** — the 8 summarization calls add latency (~9–23s each). For interactive use this is noticeable but acceptable given the cost savings.
- **+7 extra API calls** — more calls but much cheaper ones. Total output tokens increased by 1,863 (summarization outputs).
- **Information loss** — summarized tool results lose detail. The LLM sees a compressed version, not the raw data. For most use cases this is fine; for tasks requiring exact data (e.g. extracting specific fields from raw HTML), it could be a problem.

## Replay 2: Session `9846759b-6280-4bec-9cd1-abec0d8f5e41`

A second replay of the same 5 prompts with the optimised config, to test repeatability and account for LLM non-determinism.

### Session Summary

| Field | Value |
|-------|-------|
| **Duration** | ~4 min 42s (15:37:57 → 15:42:39) |
| **Model** | Haiku 4.5 + Sonnet 4.5 (semantic routing) |
| **Total Cost** | **$0.537** |
| **API Calls** | 32 |
| **Total Input Tokens** | 52,593 |
| **Total Output Tokens** | 11,906 |
| **Cache Created** | 81,531 tokens |
| **Cache Read** | 242,570 tokens |

### Per-Call Detail

| # | Turn | Call Type | Model | Input | Output | Cache Create | Cache Read | Duration | Cost |
|---|------|-----------|-------|-------|--------|-------------|------------|----------|------|
| 1 | 1 | `semantic:factual_lookup` | Haiku | 2,858 | 73 | 0 | 0 | 2.2s | $0.0032 |
| 2 | 1 | `pinned:haiku` | Haiku | 5 | 154 | 4,168 | 0 | 1.8s | $0.0060 |
| 3 | 1 | `pinned:haiku` | Haiku | 5 | 131 | 523 | 4,168 | 1.4s | $0.0017 |
| 4 | 2 | `stage2_classification` | Haiku | 310 | 39 | 0 | 0 | 1.4s | $0.0005 |
| 5 | 2 | `semantic:trivial` | Haiku | 3,810 | 70 | 0 | 0 | 1.2s | $0.0042 |
| 6 | 2 | `pinned:haiku` | Haiku | 5 | 106 | 4,795 | 0 | 1.5s | $0.0065 |
| 7 | 2 | `tool_summarization` | Sonnet | 3,198 | 443 | 0 | 0 | 8.3s | $0.0162 |
| 8 | 2 | `pinned:haiku` | Haiku | 5 | 353 | 557 | 4,795 | 3.0s | $0.0029 |
| 9 | 3 | `stage2_classification` | Haiku | 314 | 31 | 0 | 0 | 1.6s | $0.0005 |
| 10 | 3 | `semantic:creative` | Sonnet | 3 | 233 | 4,504 | 16,992 | 4.2s | $0.0255 |
| 11 | 3 | `tool_summarization` | Sonnet | 1,444 | 216 | 0 | 0 | 5.0s | $0.0076 |
| 12 | 3 | `tool_summarization` | Sonnet | 3,786 | 287 | 0 | 0 | 8.6s | $0.0157 |
| 13 | 3 | `tool_summarization` | Sonnet | 8,949 | 349 | 0 | 0 | 10.9s | $0.0321 |
| 14 | 3 | `tool_continuation` | Sonnet | 7 | 652 | 3,147 | 21,496 | 11.1s | $0.0281 |
| 15 | 4 | `semantic:factual_lookup` | Haiku | 3 | 71 | 8,841 | 0 | 1.5s | $0.0114 |
| 16 | 4 | `pinned:haiku` | Haiku | 5 | 64 | 10,195 | 0 | 1.1s | $0.0131 |
| 17 | 4 | `tool_summarization` | Sonnet | 1,854 | 348 | 0 | 0 | 8.1s | $0.0108 |
| 18 | 4 | `pinned:haiku` | Haiku | 4 | 271 | 420 | 10,195 | 2.2s | $0.0029 |
| 19 | 5 | `semantic:summarization` | Haiku | 3 | 596 | 26,264 | 0 | 3.6s | $0.0358 |
| 20 | 5 | `tool_summarization` | Sonnet | 1,982 | 609 | 0 | 0 | 11.2s | $0.0151 |
| 21 | 5 | `tool_summarization` | Sonnet | 2,423 | 470 | 0 | 0 | 12.6s | $0.0143 |
| 22 | 5 | `tool_summarization` | Sonnet | 7,235 | 1,161 | 0 | 0 | 25.9s | $0.0391 |
| 23 | 5 | `tool_continuation` | Sonnet | 7 | 401 | 11,129 | 18,995 | 6.0s | $0.0535 |
| 24 | 5 | `tool_summarization` | Sonnet | 2,187 | 468 | 0 | 0 | 9.5s | $0.0136 |
| 25 | 5 | `tool_summarization` | Sonnet | 3,772 | 659 | 0 | 0 | 10.9s | $0.0212 |
| 26 | 5 | `tool_continuation` | Sonnet | 7 | 367 | 1,746 | 30,124 | 5.8s | $0.0211 |
| 27 | 5 | `tool_continuation` | Sonnet | 7 | 361 | 1,065 | 31,870 | 4.6s | $0.0190 |
| 28 | 5 | `tool_continuation` | Sonnet | 7 | 240 | 1,457 | 32,935 | 11.3s | $0.0190 |
| 29 | 5 | `tool_summarization` | Sonnet | 6,531 | 771 | 0 | 0 | 16.5s | $0.0312 |
| 30 | 5 | `tool_continuation` | Sonnet | 7 | 96 | 2,216 | 34,392 | 3.7s | $0.0201 |
| 31 | 5 | `tool_summarization` | Sonnet | 1,854 | 399 | 0 | 0 | 10.6s | $0.0115 |
| 32 | 5 | `tool_continuation` | Sonnet | 6 | 1,417 | 504 | 36,608 | 37.5s | $0.0341 |

### Cost by Model

| Model | Calls | Input Tokens | Output Tokens | Cache Created | Cache Read | Cost | % |
|-------|-------|-------------|---------------|---------------|------------|------|---|
| **Haiku 4.5** | 12 | 7,327 | 1,959 | 55,763 | 19,158 | $0.089 | **17%** |
| **Sonnet 4.5** | 20 | 45,266 | 9,947 | 25,768 | 223,412 | $0.449 | **83%** |
| **Total** | **32** | **52,593** | **11,906** | **81,531** | **242,570** | **$0.537** | |

### Observations

1. **Turn 5 took more iterations** — Sonnet made 6 `tool_continuation` calls (vs 4 in replay 1) and 7 `tool_summarization` calls (vs 4). The model chose to fetch repos in smaller batches this time, adding more round-trips.

2. **Caching improved further** — 242K cache read tokens vs 150K in replay 1. Haiku cost dropped to $0.089 (from $0.097). The message caching fix compounds over more iterations.

3. **Non-determinism is the cost variance driver** — the $0.133 difference between replays ($0.404 vs $0.537) is entirely from Sonnet's turn 5 behaviour. Haiku costs were nearly identical ($0.097 vs $0.089).

### Three-Way Comparison

| Metric | Original (`7e366d5c`) | Replay 1 (`d99b8057`) | Replay 2 (`9846759b`) |
|--------|--------------------|--------------------|---------------------|
| **Total Cost** | **$0.879** | **$0.404** | **$0.537** |
| **Saving vs Original** | — | **54%** | **39%** |
| API Calls | 17 | 24 | 32 |
| Input Tokens | 329,112 | 41,995 | 52,593 |
| Output Tokens | 6,574 | 8,437 | 11,906 |
| Cache Created | 37,990 | 79,862 | 81,531 |
| Cache Read | 94,975 | 150,345 | 242,570 |
| Haiku Cost | $0.200 | $0.097 | $0.089 |
| Sonnet Cost | $0.702 | $0.307 | $0.449 |
| Duration | ~134s | ~159s | ~245s |

### Conclusions

- **Optimisations deliver consistent savings** — both replays are significantly cheaper than the original (39–54%), despite LLM non-determinism causing variance between runs.
- **Haiku costs are stable and low** — $0.089–$0.097 across replays, down from $0.200. The message caching fix and compaction threshold change are working reliably.
- **Sonnet cost variance is the wildcard** — $0.307–$0.449 depending on how many iterations the model takes on complex tasks. This is inherent to non-deterministic LLM behaviour and cannot be eliminated through configuration.
- **Expected cost range for this workload** — $0.40–$0.55 with the optimised config, vs $0.88 without. A **40–55% reduction**.
