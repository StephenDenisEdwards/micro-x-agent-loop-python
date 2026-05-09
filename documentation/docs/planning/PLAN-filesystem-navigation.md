# Plan: Filesystem Navigation Capability

**Status: Planned** (2026-05-09)

## Context

We want the agent to be **very good** at navigating the filesystem — finding files, searching contents, reading targeted sections, and making surgical edits — at the level of fluency that Claude Code achieves. Today the agent has a working but uneven FS surface: `grep` and `glob` are well-designed and have a path-containment policy; `read_file`, `write_file`, `append_file`, and `bash` are minimal and lack guidance, line numbers, structured edits, or containment.

Investigation (2026-05-09 session) audited the current FS toolset against Claude Code's design and identified specific, prioritised gaps. This plan turns those findings into actionable work.

The critical observation: **most of the gap is in prompts and tool descriptions, not capability.** The single biggest *capability* gap is the absence of an `edit_file` tool. Everything else is either a description rewrite or a contained additive change.

## Goal

After this plan lands, an LLM driving this agent should:

- Reach for `grep`/`glob`/`read_file`/`edit_file` instinctively rather than `bash` for FS work, because the system prompt and tool descriptions tell it to.
- Be able to make surgical in-place edits via exact-string replacement, instead of round-tripping through `write_file` for every change.
- Quote `file:line` coordinates from `read_file` output and feed them back into edits.
- Issue independent FS lookups in parallel by default.
- Delegate broad codebase exploration to the existing `explore` sub-agent so search noise stays out of the main context.
- On `bash`, be guided away from operations the dedicated tools cover (`cat`, `grep`, `find`, `sed`), and be optionally constrained by an allowlist + path-escape scan in production deployments.

## Current state (audit summary)

Source: `mcp_servers/ts/packages/filesystem/src/`.

| Tool | Status | Gap |
|---|---|---|
| `grep` (ripgrep) | Good. Three output modes; respects `.gitignore`; path-policy gated; opinionated description ("USE THIS — not read_file") | Verify all three output modes are wired and described |
| `glob` (fast-glob) | Good. mtime-sorted; path-policy gated | Description is one line — no anti-pattern guidance |
| `read_file` | Minimal. Reads text + `.docx`. **No line numbers, no offset/limit, no path policy** (`read-file.ts:7-77`) | Major capability gap — model can't quote `file:line`, can't read large files cheaply |
| `write_file` | Full overwrite only. No path policy | Forces full-file rewrites even for one-line changes |
| `append_file` | Append only. No path policy | OK for logs; not a substitute for edits |
| `bash` | Full shell. 30 s timeout. **No path policy, no allowlist, no CWD pinning** (`bash.ts:9-77`). One-line description | Tracked under [ISSUE-005](../issues/ISSUE-005-bash-tool-bypasses-path-policy.md) |
| **`edit_file`** | **Missing** | Highest-leverage capability gap |
| System-prompt FS guidance | Only a `tool_search` directive; FS tool selection lives inside individual descriptions | No global "use Read not cat / Grep not bash grep / Edit not sed" rule |
| Parallelism guidance | Mentioned only for `spawn_subagent` (`_TASK_DECOMPOSITION_DIRECTIVE`) | No directive telling the model to batch independent FS calls |
| Explore sub-agent | Exists (`spawn_subagent` with `agent_type=explore`) | Underused — system prompt does not actively push delegation |

## What Claude Code does differently

See **Reference material** below for source links. Key patterns worth borrowing:

- **`Edit` tool** with exact-string replacement. Fails loudly if `old_string` is non-unique unless `replace_all=true`. Requires a prior `Read` of the file.
- **`Read` returns `cat -n`-numbered output** with `offset` / `limit` parameters. Native handling of images, PDFs (with page ranges), and Jupyter notebooks.
- **System-prompt anti-patterns** (verbatim from Claude Code): *"Avoid using this tool to run `cat`, `head`, `tail`, `sed`, `awk`, or `echo` commands… use the appropriate dedicated tool."*
- **`Bash` working-directory pinning** + per-project **allowlist** via `.claude/settings.json` (e.g. `Bash(npm test:*)`).
- **`Explore` sub-agent**: read-only, Haiku-fast, runs in its own context so search results never bloat the main conversation. Three thoroughness levels: quick / medium / very thorough.
- **Automatic parallel batching** of independent tool calls — the harness executes them concurrently and the prompt nudges the model to issue them in one response.
- **Verbose, opinionated tool descriptions** — every tool's description doubles as a mini-guide on when to use it and what to use instead.

## Phases

Phases are ordered by leverage-per-effort. Phases 1–2 are independent and can land in parallel; phases 3+ build on 1–2.

### Phase 1 — Prompt and tool-description rewrite (no code logic)

Cheap, high-impact, all in `system_prompt.py` and the TypeScript tool registrations.

1. **Add an FS-navigation directive** to `system_prompt.py` alongside `_TOOL_SEARCH_DIRECTIVE` and `_TASK_DECOMPOSITION_DIRECTIVE`. Suggested skeleton:
   - Prefer `read_file` over `bash cat` / `head` / `tail`.
   - Prefer `grep` over `bash grep` / `rg`.
   - Prefer `glob` over `bash find` / `ls -R`.
   - Prefer `edit_file` over `bash sed` / `awk` (once Phase 2 lands).
   - Use `bash` only when no dedicated tool fits.
2. **Add a parallel-execution directive**: *"If multiple FS lookups have no data dependency, issue them in a single assistant response so the harness can run them concurrently."* This is honest — `turn_engine.py:459` already does `asyncio.gather`.
3. **Add an explore-sub-agent directive**: *"For broad codebase exploration that needs more than ~3 grep/glob queries, spawn the `explore` sub-agent so search output stays in its context, not yours."*
4. **Rewrite `bash` tool description** to include the anti-patterns above and warn about cross-platform pitfalls. Today's description is one line.
5. **Rewrite `read_file` and `glob` descriptions** to match the opinionated style of `grep`'s description (which already says *"USE THIS — not read_file…"*).
6. **Verify `grep`'s three output modes** (content / files\_with\_matches / count) are exposed and clearly documented in the description so the model picks the cheapest mode.

**Deliverable:** one PR. Pure text changes. No behaviour change to tools.

### Phase 2 — Add `edit_file` MCP tool

The single biggest capability gap. New file at
`mcp_servers/ts/packages/filesystem/src/tools/edit-file.ts`, registered in `index.ts`.

Tool surface:
```
edit_file(
  path: string,
  old_string: string,
  new_string: string,
  replace_all?: boolean = false,
) -> {
  path: string,
  replacements: number,
}
```

Semantics (mirroring Claude Code's `Edit`):
- Resolve `path` via the existing `PathPolicy` — no new containment code.
- Read the current file contents.
- If `old_string` does not appear: error with `"old_string not found"`.
- If `old_string` appears more than once and `replace_all=false`: error with `"old_string is not unique — provide more surrounding context or set replace_all=true"`.
- Otherwise apply the replacement(s) and write back atomically (write to temp file, rename).
- Refuse to edit binary files (encoding sniff).

Description must be opinionated: *"Use this for surgical edits. Do not rewrite a file via `write_file` if you only need to change a few lines — that wastes tokens and risks corrupting unrelated content."*

**Deliverable:** new tool + tests + description update in Phase 1's directive once it lands.

### Phase 3 — Upgrade `read_file`

Currently `read_file` is `readFile(path, "utf-8")` and returns raw text. Upgrade to:

1. **Line-numbered output** in `cat -n` format (matches Claude Code's `Read` exactly so the model's output instincts transfer).
2. **`offset` and `limit` parameters** for large files. Default: read up to 2000 lines from line 1.
3. **Path policy gating** (closes part of ISSUE-005 for the read path).
4. Optional: warn / refuse on binary files. Explicit error rather than dumping raw bytes.

The line-numbered output is what makes `edit_file` ergonomic — the model can quote `file:line` from `read_file` output and feed coordinates back into edits.

**Deliverable:** updated `read-file.ts` + description rewrite. Backwards-incompatible for any consumer reading the raw text via `structuredContent.content`, but the agent only consumes the `text` content block.

### Phase 4 — Bash hardening (close ISSUE-005)

Already designed in [ISSUE-005](../issues/ISSUE-005-bash-tool-bypasses-path-policy.md). This plan adopts **Option A** from that issue:

1. **Optional command allowlist** via `FILESYSTEM_BASH_ALLOWED_COMMANDS=git,npm,pytest,...`.
2. **Optional absolute-path escape scan** via `FILESYSTEM_BASH_PATH_GUARD=true`.
3. **Working-directory pinning**: every command runs with `cwd = workingDir` regardless of any inherited shell state.
4. Apply path policy to `write_file`, `append_file`, `read_file` (latter via Phase 3).

ISSUE-005 acknowledges this is not airtight — a determined agent can defeat string-level filters. The point is defence-in-depth and accident prevention, plus a knob the user can tighten per environment.

**Deliverable:** opt-in flags, default behaviour unchanged. Resolves ISSUE-005.

### Phase 5 — Promote the `explore` sub-agent (post Phase 1)

Phase 1 adds the directive. This phase verifies it actually changes behaviour:

- Manual test: a prompt requiring 5+ greps across the codebase. Confirm the model spawns `explore` instead of running them inline.
- If the model still runs them inline, tune the directive's threshold and the `explore` agent's description.
- Optional: tweak `SubAgentRunner` defaults so `explore` runs on a cheaper model (it likely already does — verify against `agent_config.py`).

**Deliverable:** manual test doc + any tuning commits.

### Phase 6 — Optional: image / PDF / notebook reading

Lowest priority. Only worth doing if the agent has actual use cases (design docs, screenshots).

- Images: pass through to the LLM as multimodal content blocks (provider-dependent — Anthropic supports it; OpenAI supports it; Gemini supports it).
- PDFs: extract per-page text (pdf-parse or similar), with `pages` parameter like Claude Code's `Read`.
- Notebooks (`.ipynb`): parse cells, return code + markdown + outputs interleaved.

**Deliverable:** capability extension to `read_file`. Defer until a concrete use case appears.

## Risks

- **Description rewrites can regress behaviour silently.** The model is currently using terse-described tools fine. A more opinionated description that says *"don't use `bash` for FS work"* may cause false negatives on legitimate `bash` use (e.g. running tests). Mitigation: describe the **anti-pattern**, not a blanket prohibition.
- **`edit_file` uniqueness check can frustrate the model on near-identical lines.** Mitigation: error message must explicitly suggest more surrounding context. Same trade-off Claude Code makes; works in practice.
- **Path policy on `read_file` breaks scripts that read outside the workspace** (e.g. `~/.config`). Mitigation: `FILESYSTEM_ALLOWED_DIRS` already supports extra roots.
- **Bash allowlist is opt-in by design** — most users will not configure it, so ISSUE-005's underlying risk persists. Real containment requires OS-level isolation (containers, AppArmor) — out of scope.

## Acceptance criteria

For the plan as a whole:

1. The agent, given *"find every place X is called and rename to Y"*, uses `grep` (not `bash grep`), uses `edit_file` (not `write_file`), and issues independent reads in parallel — without that prompt being in-context.
2. The agent, given a vague codebase question, spawns the `explore` sub-agent rather than running 6 inline greps.
3. `bash` is only invoked when no dedicated tool fits (running tests, git commands, build tools).
4. ISSUE-005 is closed (or the plan explicitly downgrades it to "won't fix without OS-level isolation").
5. All Phase 1–4 work passes existing tests + adds tests for `edit_file` and the upgraded `read_file`.

## Effort estimate

Rough, assuming one engineer:

| Phase | Estimate |
|---|---|
| 1 — Prompt + descriptions | 0.5 day |
| 2 — `edit_file` tool | 1 day |
| 3 — `read_file` upgrade | 0.5 day |
| 4 — Bash hardening (ISSUE-005) | 1–1.5 days |
| 5 — Explore sub-agent verification + tuning | 0.5 day |
| 6 — Image/PDF/notebook (optional) | 1–2 days |

Phases 1–3 together — roughly **2 days** — deliver the bulk of the user-visible improvement.

## Reference material

### Claude Code documentation

- **Main docs**: <https://docs.claude.com/en/docs/claude-code/overview>
- Pages of particular interest (navigate from the main docs):
  - **Tools Reference** — tool descriptions, parameters, and behavioural notes for `Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash`
  - **Sub-agents** — design and usage of the `Explore` sub-agent (read-only, Haiku-fast, isolated context)
  - **Best Practices** — context management, parallel tool calls, when to delegate to a sub-agent
  - **Settings** — `.claude/settings.json` permission/allowlist syntax (relevant to Phase 4 bash hardening)
- **Repo / issues**: <https://github.com/anthropics/claude-code>

### Underlying tools that Claude Code's `Glob`/`Grep` wrap (and which our equivalents already use)

- **ripgrep** (`grep` backend): <https://github.com/BurntSushi/ripgrep>
- **fast-glob** (`glob` backend): <https://github.com/mrmlnc/fast-glob>

### Internal sources informing this plan

- Audit of `mcp_servers/ts/packages/filesystem/src/` — current FS-tool inventory and gaps
- Verbatim quotes of the model-facing `grep` tool description (`grep.ts:18-25`) and the bash tool description (`bash.ts:13`)
- `system_prompt.py` directives reviewed for FS-navigation guidance gaps
- Comparison table built during the 2026-05-09 design conversation

## Related

- [ISSUE-005: bash tool bypasses filesystem path policy](../issues/ISSUE-005-bash-tool-bypasses-path-policy.md) — Phase 4 closes this
- [DESIGN-tool-system.md](../design/DESIGN-tool-system.md) — `tool_search` and dynamic tool list
- [DESIGN-task-decomposition.md](../design/DESIGN-task-decomposition.md) — sub-agent infrastructure that Phase 5 leverages
- [DESIGN-agent-loop.md](../design/DESIGN-agent-loop.md) — where parallel tool execution lives (`asyncio.gather` in `turn_engine.py:459`)
- [DESIGN-agent-loop-react-and-langgraph.md](../design/DESIGN-agent-loop-react-and-langgraph.md) — places this plan in the broader ReAct/agent-loop context
