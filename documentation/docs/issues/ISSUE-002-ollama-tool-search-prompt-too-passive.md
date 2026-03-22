# ISSUE-002: Small Models Select Wrong Tool Due to Noisy tool_search Results

## Status

**Resolved** — 2026-03-22. Three fixes applied and validated end-to-end. See [Resolution](#resolution) for details.

## Summary

When `qwen2.5:7b` (Ollama) is used with `tool_search_only: true` and `pin_continuation: true`, the model calls `tool_search` but receives too many irrelevant results (24 matches for "list files"). This causes two cascading failures: initially the model asked for permission instead of acting (fixed by prompt change), then it called the wrong tool (`filesystem__read_file` instead of `filesystem__bash`) with hallucinated parameters.

The root cause is that `tool_search` uses keyword matching which returns noisy results, while a capable model like Haiku can pick the correct tool from 100 options because it understands semantic intent.

## Investigation Timeline

### Phase 1: Model asks for permission instead of acting

With the prompt "list my files":

1. **Iteration 0:** Ollama calls `tool_search("list files")` — correct tool call ✓
2. **Iteration 1 (pinned):** Ollama receives 22 loaded tool schemas, responds with:

   > "the most direct tool for listing files in your current directory is `filesystem__bash`. Let's use this tool to execute a command that lists the files. Would you like me to proceed?"

   The model **identified the correct tool** but generated text instead of making a tool call.

**Key finding:** The model CAN select the right tool from 22 options. The failure was behavioural (asking permission), not capability.

### Phase 2: Prompt fix — model now acts but picks wrong tool

Added directive to system prompt (both compact and full):
- "Always call tools directly — never ask the user for permission before using a tool."
- "Do not describe what you plan to do — just do it."

After the fix, the model stopped asking permission and made a tool call. However:

1. **Iteration 1 (pinned):** Ollama called `filesystem__read_file` with `file_path: "C:\path\to\your\file.txt"` — wrong tool, hallucinated path
2. **Iteration 2 (pinned):** After the error, reverted to text response asking the user

**Key finding:** With 22 tool schemas loaded, the model picks the wrong tool and hallucinates parameters. The tool it needs (`filesystem__bash`) is buried among 21 irrelevant tools.

### Phase 3: Comparison with working config (unpinned → Haiku)

With `pin_continuation: false` on `factual_lookup` and `tool_continuation` routed to Haiku:

1. **Iteration 0:** Ollama calls `tool_search` ✓
2. **Iteration 1:** Haiku (via `tool_continuation`) receives full 100 tools → calls `filesystem__bash("dir /B")` ✓
3. **Iteration 2:** Haiku processes the result ✓

**Key finding:** Haiku picks the correct tool from 100 options with zero help. Tool search returns 24 noisy matches. The gap between Haiku's tool selection and tool_search's keyword matching is the core problem.

## Root Cause Analysis

### Why tool_search returns noisy results

`tool_search` uses keyword matching: each query term scores 3 points for a name match and 1 point for a description match. The query "list files" matches:

- "list" → `list_repos`, `list_issues`, `list_chats`, `list_events`, `list_messages`, `list_discussions`, `list_prs`, `list_contacts`, `list_recordings`, `list_devices` (10+ matches)
- "file" → `read_file`, `write_file`, `append_file`, `save_memory` (4+ matches)
- Combined: 24 matches, `TOOL_SEARCH_MAX_LOAD` loads 20 of them

The keyword algorithm has no concept of user intent. "list my files" means local filesystem, but keyword matching scores `github__list_repos` the same as `filesystem__bash`.

### Why Haiku succeeds where tool_search fails

Haiku understands semantic intent — it knows "list my files" means the local filesystem, not GitHub repos or WhatsApp chats. It picks `filesystem__bash` from 100 tools because it reasons about meaning, not keywords.

### The fundamental mismatch

The architecture assumes tool_search narrows the tool set to relevant tools, then the small model picks from the narrowed set. But tool_search's keyword matching is so much worse than LLM tool selection that it actually makes the problem harder — it loads 20 mostly-irrelevant tools that confuse the small model.

## What Is NOT the Problem

Through systematic testing we confirmed:

- **Model CAN make tool calls** — it successfully called `tool_search` on iteration 0
- **Model CAN process tool_search results** — it understood the list of 24 matching tools
- **Model CAN select the right tool from 22 options** — it correctly identified `filesystem__bash` (Phase 1, before prompt fix)
- **Model CAN handle the compact system prompt** — 2214 chars, well within context limits
- **The prompt was too passive** — fixed by adding directive language (Phase 2)
- **22 tool schemas alone is not the blocker** — the model can reason about them, but struggles to reliably emit the correct tool_use block with correct parameters

## Proposed Fix: Semantic Tool Search via Embeddings

Replace keyword-based tool_search with vector similarity search using embeddings.

### Architecture

1. **At agent startup:** embed all tool names + descriptions using a local embedding model via Ollama (e.g. `nomic-embed-text`, ~274MB)
2. **On `tool_search(query)`:** embed the query, compute cosine similarity against all tool embeddings, return top-k (3–5) most similar tools
3. **No per-search API cost** — embeddings are computed locally via the existing Ollama container

### Why embeddings

- "list my files" would embed semantically close to `filesystem__bash` ("execute a shell command and return its output") rather than `github__list_repos`
- For ~100 tools, no vector database is needed — a numpy array with cosine similarity is sufficient (< 1ms per search)
- Ollama is already a dependency for local model routing — reusing it for embeddings adds no new infrastructure
- One-time embedding cost at startup (~1–2 seconds for 100 tools), then instant similarity search

### Expected outcome

With top-5 semantic matches, "list my files" would return:
- `filesystem__bash` (execute shell commands)
- `filesystem__read_file` (read a file)
- `filesystem__write_file` (write a file)
- `filesystem__append_file` (append to a file)
- `filesystem__save_memory` (save to memory)

The 7B model would have 5 highly relevant filesystem tools instead of 22 noisy matches spanning 8 different MCP servers. This should be well within its capability to select correctly.

### Fallback

If Ollama embedding is unavailable (e.g. embedding model not pulled), fall back to the existing keyword search. The feature should be opt-in via config, similar to `ToolSearchEnabled`.

## Resolution

Three fixes were applied and validated end-to-end with `qwen2.5:7b` via Ollama:

### Fix 1: Directive system prompt (both compact and full)

Added to the base system prompt (affects all models):

> "Always call tools directly — never ask the user for permission before using a tool. Do not describe what you plan to do — just do it."

**Result:** The model stopped asking "Would you like me to proceed?" and started emitting tool_use blocks directly. However, with 22 noisy tool schemas from keyword search, it picked the wrong tool (`filesystem__read_file` instead of `filesystem__bash`) and hallucinated parameters.

**File:** `src/micro_x_agent_loop/system_prompt.py`

### Fix 2: Semantic tool search via Ollama embeddings

Replaced keyword-based `tool_search` scoring with cosine similarity on dense embeddings from Ollama's `nomic-embed-text` model. Tool names are split from `filesystem__bash` to `filesystem bash` for readable embedding text. Search hints are added for tools whose descriptions don't cover common use cases (e.g. `filesystem__bash` now includes "list files, directory listing, dir, ls").

**Result:** "list files" returns 5 relevant tools (including `filesystem__bash` at #2) instead of 24 noisy keyword matches. The model reliably picks `filesystem__bash` from the 5 options.

**Config:**
- `ToolSearchStrategy: "auto"` — try semantic, fallback to keyword
- `ToolSearchMaxLoad: 5` — only load top 5 matches
- `EmbeddingModel: "nomic-embed-text"` — Ollama embedding model
- `OllamaBaseUrl: "http://localhost:11434"` — configurable Ollama endpoint

**Files:** `src/micro_x_agent_loop/embedding.py` (new), `src/micro_x_agent_loop/tool_search.py` (refactored to async + embedding integration)

### Fix 3: Search hints for under-described tools

Some MCP tool descriptions don't mention their common use cases. `filesystem__bash` is described as "Execute a shell command" — the words "file", "list", "directory" never appear. The embedding model correctly embeds this as "shell command execution", which is semantically distant from "list my files".

Added `_TOOL_SEARCH_HINTS` dictionary in `embedding.py` that appends common use cases to the embedding text:

```python
_TOOL_SEARCH_HINTS = {
    "filesystem__bash": "list files, directory listing, dir, ls, run command, ...",
    "google__gmail_search": "list emails, read emails, inbox, email search, ...",
    "google__calendar_list_events": "list calendar, schedule, meetings, ...",
    "google__contacts_list": "list contacts, phone numbers, address book",
}
```

**Result:** `filesystem__bash` jumped from not-in-top-10 to #2 for "list files". `google__gmail_search` jumped from #5 to #1 for "list my emails". `google__calendar_list_events` scores 0.77 for "list my calendar events".

### Validated end-to-end result

With `config-testing-semantic-routing-local-1.json` (pinned, Ollama for factual_lookup):

Prompt: "list my files"
1. **Iteration 0:** Ollama calls `tool_search("list files")` — semantic search returns 5 tools ✓
2. **Iteration 1 (pinned):** Ollama picks `filesystem__bash` from 7 tool schemas, calls `dir /s /b` ✓
3. **Iteration 2 (pinned):** Ollama receives 11KB dir output — returns empty (context overflow for 7B model)

The tool discovery and execution chain works fully locally at zero API cost. The remaining limitation is that the 7B model cannot process large tool results (11KB+). This is an inherent context window constraint, not a search or routing problem. For this case, the unpinned config (local-2) with Haiku handling iteration 2 is the recommended pattern.

## Remaining Limitation

Large tool results (>5KB) overwhelm the 7B model's effective context on iteration 2+. The model returns empty content instead of summarising the result. This is not fixable via search or prompt improvements — it's a model capability constraint.

**Workarounds:**
- Use the unpinned config (local-2): Ollama discovers tools, Haiku executes and summarises. Cost: ~$0.001/turn.
- Use `pin_continuation: true` only for tasks where tool results are small (file reads, short API responses).
- Future: add a per-policy `max_tool_result_chars` override to truncate results for small models before feeding them back.

## Related

- [DESIGN: Semantic Model Routing](../design/DESIGN-semantic-model-routing.md) — per-policy `tool_search_only`, `system_prompt`, `pin_continuation`, semantic tool search
- [ADR-020: Semantic Model Routing](../architecture/decisions/ADR-020-semantic-model-routing.md)
- `src/micro_x_agent_loop/embedding.py` — Ollama embedding client, vector index, search hints
- `src/micro_x_agent_loop/tool_search.py` — async `ToolSearchManager` with semantic/keyword dual path
- `src/micro_x_agent_loop/system_prompt.py` — directive prompt fix
- [DESIGN: Cache-Preserving Tool Routing](../design/DESIGN-cache-preserving-tool-routing.md) — tool search context
