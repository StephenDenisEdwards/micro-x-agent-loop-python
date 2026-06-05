# Changelog

All notable changes to micro-x-agent-loop-python are documented here, grouped by feature area.

## 2026-06-05 — v0.2.1

Cleanup release closing the 8 follow-up observations from the second-pass codebase-review audit performed against v0.2.0. Full details in [documentation/docs/review/codebase-review-2026-06-05-followups.md](documentation/docs/review/codebase-review-2026-06-05-followups.md).

### Refactored
- **Promoted 9 private symbols to the public testable surface** — `llm_client.on_retry`, `providers/gemini_provider.build_tool_use_id_map`, `providers/gemini_provider.is_retryable_gemini_error`, `system_prompt.SUBAGENT_DIRECTIVE`, `tool.sort_schema`, `tool_search.get_context_window`, `voice_ingress.parse_json_object` (module fn), `voice_runtime.parse_json_object` (method), `broker/runner.truncate_output`, `compaction.format_for_summarization`. All call sites updated. The leading-underscore variants are gone.
- **Eliminated all 3 `# type: ignore[assignment]` comments in `server/app.py`** — replaced with `TYPE_CHECKING` imports + explicit narrowed declarations (`sched: Scheduler | None = _state.get(...)`). Zero `# type: ignore` remain on `server/app.py`.
- **Typed the 10 `Any` fields on `AgentComponents`** with real Protocols via `TYPE_CHECKING` imports — `LLMProvider`, `AgentChannel`, `CompactionStrategy`, `LLMCompactor`, `ProviderPool`, `RoutingFeedbackStore`, `SemanticClassifierFn`, `RoutingFeedbackFn`. Zero `Any` on the dataclass.

### Features
- **`Agent.history` and `Agent.turn_number` public properties** — read-only accessors for the current conversation message list and completed-turn count. Integration tests now go through the public API instead of reaching into `agent._messages` / `agent._turn_number` at 7 sites.
- **`SpawnSubagentPseudoToolTests` end-to-end scenario** added to `tests/integration/test_agent_loop.py`. Wires `sub_agents_enabled` + a compact routing policy to trigger `SubAgentRunner` construction in `agent_builder`, patches `SubAgentRunner.run` with a canned `SubAgentResult`, asserts the result lands as a `tool_result` block and the loop continues. Closes the spawn_subagent coverage gap flagged in the re-audit.

### Test quality
- **4 wall-clock sleeps removed or made deterministic.** Spinner idempotency tests (`test_llm_client.py:17`, `test_agent_channel.py:360`) no longer wall-clock-sleep. The mtime-ordering test (`test_native_filesystem_read_tools.py:172`) now uses explicit `os.utime()` calls (the original 20 ms sleep wouldn't have worked on 1 s mtime-resolution filesystems anyway). `test_ws_integration::test_ping_during_active_turn` simulated slow-turn shortened from 2.0 s → 0.5 s.

### Docs
- `tests/evals/filesystem-navigation/README.md` updated to the new `configs/evals/config-eval-haiku.json` path (stale from the v0.2.0 config reorganisation).

### Build state
Ruff clean · Mypy clean · **1,887 tests pass** / 14 skipped / 0 failing · **76% coverage** with the CI gate at 75%.

---

## 2026-06-05 — v0.2.0 — codebase review complete

The "post-review" milestone. Closes all 30 items from the 2026-06-05 codebase review (see [documentation/docs/review/codebase-review-2026-06-05.md](documentation/docs/review/codebase-review-2026-06-05.md)).

### Architecture
- **`agent.py` split: 1,219 → 872 LOC (-28%)** via three new modules: `history_repair.py` (pure history-repair utilities — `find_safe_trim_count`, `repair_orphan_head`, `repair_orphan_tool_uses`), `mode_orchestrator.py` (the PROMPT/COMPILED mode-analysis pipeline with DI), and `agent_listener.py` (`AgentEventListener` implementing the pure-observability subset of `TurnEvents`).
- **`commands/command_handler.py` split: 1,062 → 171 LOC (-84%)**. The class is now a pure delegating facade over 14 per-command modules (`help_command.py`, `session_command.py`, `tool_command.py`, `voice_command_handler.py`, etc.) plus a shared `CommandContext` dataclass.
- **`turn_engine.py`: `PseudoToolHandler` protocol extracted** with 4 concrete handlers (`ToolSearchHandler`, `AskUserHandler`, `TaskToolHandler`, `SubAgentHandler`). Dispatch is now a 20-line list walk instead of an 80-line 5-bucket `if/elif`. Adding a 5th pseudo tool is a one-line append.
- **`AgentChannel` Protocol drift fixed.** `begin_streaming` / `end_streaming` added to the Protocol with no-op implementations in `BufferedChannel`, `BrokerChannel`, `WebSocketChannel`. The `hasattr` guard in `agent.py` deleted.
- **Blocking `subprocess.run` wrapped in `asyncio.to_thread`** in `native_tools/filesystem/bash_tool.py` and `read_tools.py` — both called from async `execute` methods.
- **5 `Any`-typed dependencies in `TurnEngine` replaced** with real Protocols: `LLMProvider`, `LLMCompactor`, `SemanticClassifierFn` (Callable alias), `RoutingFeedbackFn` (Callable alias), `TaskEmbeddingIndex`.
- **`agent_config.py`: 4 unused sub-config dataclasses dropped** (`MemoryConfig`, `SubAgentConfig`, `CostReductionConfig`, `ToolResultConfig`). File shrank 268 → 176 LOC.

### Breaking change — config-file reorganisation
- **Profile / eval / testing configs moved out of repo root into `configs/{profiles,evals,testing}/`** — 36 → 3 `config-*.json` files at the repo root. Entry-point configs stay at root (`config.json`, `config-base.json`, `config-baseline.json`, `config-starter.json`).
- Each moved file's `Base: "config-base.json"` reference rewritten to `Base: "../../config-base.json"`. The one `ConfigFile`-indirected profile updated to the new path. `config-starter.json.bak` deleted.
- **Users with persisted `--config config-standard-X.json` invocations need to update to `--config configs/profiles/config-standard-X.json`** (or `configs/evals/`, `configs/testing/`). All test references, eval harness, README, CLAUDE.md, and 49 documentation references swept.

### Test quality
- **56 test files migrated** from `asyncio.run()` inside `unittest.TestCase` to `unittest.IsolatedAsyncioTestCase`. Only one `asyncio.run(` call remains in `tests/`, in the eval harness (legitimate).
- **44 new tests added (+52 net):** 6 end-to-end integration scenarios in new `tests/integration/test_agent_loop.py` (driving a real `Agent` with only the LLM provider faked; covers single-turn, multi-turn tool-call, multi-tool-per-response, `ask_user`, iteration cap, tool error propagation); 10 cli/dispatch routing tests; 16 services tests (`SessionController`, `CheckpointService`); 12 `agent_builder` branch tests.
- **Tests no longer write inside the repo.** `Path.cwd() / ".tmp-run"` replaced with `tempfile.TemporaryDirectory`.
- **Sleep-as-sync replaced with deterministic waits.** `WebSocketChannel` now tracks fire-and-forget `_send` futures in `_pending_sends` with a `_drain_pending_sends()` helper; `broker_store` tests use `timeout_seconds=-1` instead of wall-clock sleeps.
- **`MagicMock` sprawl in command tests replaced** with the existing `SessionManagerFake` / `CheckpointManagerFake` from `tests/fakes.py` + real `ToolResultFormatter` + real `CheckpointService`. The tautological `format_rewind_outcome_lines.return_value = ["  Rewound."]` → `assertIn("Rewound.")` pattern is gone.
- **`FakeStreamProvider.stream_chat` signature tightened** — no more `**kwargs` silently swallowing Provider Protocol drift.

### Hygiene
- **12 ruff violations, 2 mypy errors, 5 failing tests at start → 0 / 0 / 0.**
- **15 `# type: ignore[no-untyped-def]` annotations on FastAPI routes** in `server/app.py` and `server/broker_routes.py` replaced with real return types (`Response | dict[str, Any]`, `AsyncIterator[None]`, etc.).
- **6 source files gained `from __future__ import annotations`.**
- **3 private symbols promoted** to the public testable surface: `resolve_api_key_id`, `load_user_memory`, `parse_cli_args`.
- **Voice tests consolidated** at one level (`tests/voice/` subdirectory removed; all 4 voice test files at top level).
- **Coverage gate (≥75%) added to CI** alongside the ADR-024 grep gate.
- **Cleared the ADR-024 violation** in `mcp_servers/ts/packages/web/dist/` (the artifact was gitignored but stale on disk; rebuilt and added a CI grep gate to prevent re-introduction).

### Build state
Ruff clean · Mypy clean · **1,886 tests pass** / 14 skipped / 0 failing · **76% coverage** with the CI gate at 75% · Root `config-*.json` count **36 → 3**.

## 2026-05-09

### Fixed
- **`grep` description was too gentle about when to use `output_mode=content`.** Real-world repro: user asked "list all the Level-2 headings", model picked the default `files_with_matches` mode, got back just file paths, narrated *"the grep tool is giving me a summary instead of the raw lines"* and fell back to `read_file` — wasting a turn. Top-level description and `output_mode` parameter description both rewritten to lead with picking the mode (and to spell out: when the user wants matches/lines/headings/the actual text → `content`; `files_with_matches` ONLY when filenames alone answer the question). Default mode unchanged — matches Claude Code's convention; the failure was the model not picking `content` when it should have.

### Features
- **Filesystem-navigation eval set.** New `tests/evals/filesystem-navigation/` with eight read-only prompts (three narrow, three broad, two vague) and a Python runner that invokes the agent autonomously, parses `metrics.jsonl` for `tool_execution` events, and scores observed tool families against per-prompt expectations. Pass criterion: 80% of prompts pass; per-prompt retries (`--retries N`) absorb model non-determinism. Provides the verification harness for acceptance criteria #1 and #2 of [PLAN-filesystem-navigation](documentation/docs/planning/PLAN-filesystem-navigation.md). Closes Phase 5 — and with it, the entire Filesystem Navigation plan (Phase 6 image/PDF/notebook reading is explicitly deferred until a concrete use case appears).
- **`bash` containment (accident prevention).** Two opt-in env-var knobs apply *before* execution. **`FILESYSTEM_BASH_PATH_GUARD` (default ON, set `=false` to disable)** rejects commands that reference absolute paths or `..` traversal resolving outside `FILESYSTEM_WORKING_DIR` / `FILESYSTEM_ALLOWED_DIRS`. Tokenisation handles whitespace + `=` split with quote stripping; checks POSIX absolute (`/...`), Windows drive-letter (`C:\...`), UNC (`\\server\share`), and `..` traversal. **`FILESYSTEM_BASH_ALLOWED_COMMANDS` (opt-in)** restricts execution to commands whose first token is in the comma-separated list — three modes: unset (no filter), empty string (deny-all kill switch), list (first-token allowlist). Pipes / chains / subshells / command substitution are NOT decomposed and NOT checked — documented as a known gap. **Resolves [ISSUE-005](documentation/docs/issues/ISSUE-005-bash-tool-bypasses-path-policy.md) in its accident-prevention scope.** Adversarial portion remains out of scope (string-level filters are trivially bypassable; real isolation requires OS-level controls). Closes Phase 4 of [PLAN-filesystem-navigation](documentation/docs/planning/PLAN-filesystem-navigation.md).
- **`delete_file` MCP tool — single-file delete, checkpoint-tracked.** New first-party tool in the filesystem MCP server. Refuses directories (use `bash rm -r` / `rmdir` for those) and non-regular files. The file is snapshotted *before* unlink via the existing `_MUTATING_TOOL_NAMES` machinery, so `/rewind` restores deleted files with their original contents. Containment via `PathPolicy` + `realpath`. Removes the last common reason to reach for `bash` for everyday FS work — the system prompt and `bash` description both now point single-file deletes at `delete_file`. Closes Phase 2b of [PLAN-filesystem-navigation](documentation/docs/planning/PLAN-filesystem-navigation.md).
- **FS-navigation directive in the system prompt + opinionated tool descriptions.** New `_FS_NAVIGATION_DIRECTIVE` (in `system_prompt.py`) tells the model to reach for `read_file` / `grep` / `glob` / `edit_file` / `write_file` / `append_file` instead of `bash cat` / `grep` / `find` / `sed` / `echo >`. Calls out parallel execution (`asyncio.gather`), the 3-grep-query threshold for spawning an `explore` sub-agent, and the read_file → quote → edit_file editing workflow. Tool descriptions for `bash` (was one line), `glob` (was two lines), and `grep` (now documents the three output modes by name) rewritten in the same opinionated style as the existing `grep` description so the model picks the right tool from the description alone. Closes Phase 1 of [PLAN-filesystem-navigation](documentation/docs/planning/PLAN-filesystem-navigation.md).
- **`edit_file` MCP tool — surgical exact-string edits to existing files.** New first-party tool in the filesystem MCP server. Replaces `old_string` with `new_string`; uniqueness is enforced (set `replace_all=true` to apply to every match, or include more surrounding context). CRLF/LF line endings are detected from the file and `old_string` / `new_string` are normalised to match — critical for editing CRLF files with LF-default model output (Windows-primary codebase). UTF-8 BOM preserved. Binary files refused (null-byte sniff). Files larger than 5 MB refused (override via `FILESYSTEM_EDIT_MAX_BYTES`). Atomic write via same-directory temp + `rename`. Mutations are checkpointed by the agent's `_MUTATING_TOOL_NAMES` machinery so `/rewind` restores edits. Closes Phase 2 of [PLAN-filesystem-navigation](documentation/docs/planning/PLAN-filesystem-navigation.md).
- **`read_file` now returns `cat -n`-style line-numbered text with `offset` / `limit` parameters.** Default returns up to 2000 lines from line 1; pass `offset` / `limit` to read a specific window. Truncation marker (`[truncated at line N of M — use offset=N+1 to continue]`) tells the model when there's more. Empty files return `(file is empty)`; offsets past EOF return a clear hint. Binary files (null byte in the first 8 KB) are refused with an explicit error rather than dumping raw bytes. `.docx` extraction is unchanged but now line-numbered. Quoting `<path>:<line>` from the output is now natural — important groundwork for `edit_file`. **Backwards-incompatible** for any consumer that relied on the raw text format of the `text` content block; the agent and codegen subprocess do not, so no in-tree caller is affected.

### Behavioural changes (potentially breaking)
- **`write_file`, `append_file`, and `read_file` now enforce path containment.** All three tools route paths through `PathPolicy` (`resolveAllowed` with `realpath`). Absolute paths outside `FILESYSTEM_WORKING_DIR` and `FILESYSTEM_ALLOWED_DIRS` are now rejected with an error naming the env var; symlinks pointing out of the allowed roots are also rejected. Closes the asymmetry flagged in [ISSUE-005](documentation/docs/issues/ISSUE-005-bash-tool-bypasses-path-policy.md) §75 (search tools were gated; file tools were open). `bash` remains unconstrained — see ISSUE-005 for the threat-model statement. Workflows that read or wrote outside the workspace via these tools need to add the extra root to `FILESYSTEM_ALLOWED_DIRS`.

## 2026-03-04

### Features
- **Interactive mode selection** — When compiled-mode signals are detected in a user prompt, the agent now explains what it found and asks the user to choose between PROMPT and COMPILED mode before proceeding
- **LinkedIn publishing tools** — Added `draft-post`, `draft-article`, and `publish-draft` tools for LinkedIn content creation
- **`/tools mcp` command** — New command shows hierarchical tool listing grouped by MCP server
- **Ask-user pseudo-tool** — LLM can now pause and ask the user clarifying questions with arrow-key selection (ADR-017)
- **Startup logo** — ASCII art branding shown at agent startup

### Docs
- Split README into promotional README and practical QUICKSTART
- Updated SAD to v3.0 with architecture diagrams

## 2026-03-03

### Features
- **MCP retry/resilience** — MCP server connections and tool calls now retry on transient failures with exponential backoff (ADR-016)
- **GitHub structured content** — GitHub MCP tools return structured content with metadata
- **On-demand tool search** — Large tool sets are deferred and discovered by the LLM via `tool_search`
- **Codegen prompt discipline** — Tightened code generation prompts with infrastructure file deny rules

### Refactoring
- Extracted constants, CommandHandler, and config inheritance into separate modules
- Fixed `_to_bool` parsing and feature envy in agent configuration

## 2026-03-02

### Features
- **Codegen server** — Experimental MCP server for structured code generation tasks
- **`run_task` tool** — Execute codegen tasks with inline prompts
- **Ctrl+C interrupts** — Ctrl+C now interrupts the current agent turn instead of killing the process
- **Per-call cost breakdown** — `/cost` command shows per-API-call breakdown
- **Prompt caching in codegen** — Cache metrics propagated from nested LLM calls

### Fixes
- Fixed JobServe email parser and structuredContent text fallback
- Replaced hand-rolled HTML-to-text with `html-to-text` library
- Fixed pricing lookup for model names without date suffix
- Nested LLM costs from MCP tools now tracked in `/cost` metrics

### Docs
- Added cache-preserving tool routing design and plan
- Added research on KV cache mechanics and MCP tool routing

## 2026-03-01 and Earlier

### Features
- **Cost reduction architecture** (ADR-012) — Prompt caching, conversation compaction, tool result summarization, mode analysis, concise output mode
- **Mode analysis** — Two-stage prompt classification (pattern matching + LLM) to detect compiled-mode tasks
- **Multi-provider LLM support** (ADR-010) — Pluggable provider abstraction supporting Anthropic and OpenAI
- **Session persistence** (ADR-009) — SQLite-backed session memory with checkpoint rewind
- **Continuous voice mode** (ADR-011) — STT via MCP sessions with `/voice` orchestration
- **Web tools** — `web_fetch` for content extraction, `web_search` via Brave Search API
- **Google integration** — Gmail (search, read, send), Calendar (list, create, get events), Contacts
- **WhatsApp integration** — Contact search, chat history, message sending, media transfer
- **GitHub tools** — PRs, issues, code search, file access via MCP
- **Anthropic usage** — Admin API cost reporting via `anthropic_usage` tool
- **Conversation compaction** — Strategy pattern with summarize compaction to manage context length
- **Configurable logging** — Loguru-based logging with tool execution spinner
- **Structured metrics** — JSON Lines metrics emission for cost tracking and analysis

### Architecture
- MCP for all external tools (ADR-005)
- Separate repos for third-party MCP servers (ADR-006)
- Streaming responses via SSE (ADR-003)
- python-dotenv for secrets (ADR-001)
- tenacity for retry logic (ADR-002)
- Raw HTML for Gmail (ADR-004)
- Google Contacts as built-in tools (ADR-007)
- GitHub tools via raw httpx (ADR-008)

### Initial Release
- Python port of micro-x-agent-loop with interactive REPL
- Tool protocol with name, description, execute, is_mutating
- Bash, read_file, write_file, append_file built-in tools
- One-command startup via run.bat / run.sh
