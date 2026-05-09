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
- On `bash`, be guided away from operations the dedicated tools cover (`cat`, `grep`, `find`, `sed`), with an optional opt-in allowlist + path-escape scan for accident prevention. (This is a single-user developer tool — there is no separate "production" deployment mode.)

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
`mcp_servers/ts/packages/filesystem/src/tools/edit-file.ts`, registered in `index.ts`. Aligns with [ADR-015](../architecture/decisions/ADR-015-all-tools-as-typescript-mcp-servers.md) — TypeScript MCP server, no Python tool code.

#### Tool surface

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

#### Semantics

Mirror Claude Code's `Edit` where sensible. Specified explicitly because the defaults bite on Windows.

**Resolution and existence**
- Resolve `path` via the existing `PathPolicy` — no new containment code.
- File-not-found → error `"file not found: <path>"`. Do **not** auto-create. (The description tells the LLM to use `write_file` for new files.)

**Encoding**
- Read as UTF-8 by default.
- Preserve UTF-8 BOM on write if present in the original.
- Detect binary content by scanning the first 8 KB for null bytes; if found → error `"refusing to edit binary file"`.
- Refuse files larger than a configurable limit (default 5 MB) → error `"file too large for edit_file — use write_file or split the edit"`.

**Line endings (Windows-critical, not optional)**
- Detect the file's existing EOL convention (CRLF vs LF) by sampling.
- Normalize both `old_string` and `new_string` to the file's EOL **before** matching, and write back with the same EOL.
- Without this, a model producing LF strings cannot edit CRLF files — most of this codebase. This is the single biggest reason a naive port of Claude Code's `Edit` would be unusable here.

**Matching and replacement**
- After EOL normalization, count occurrences of `old_string`.
- 0 → error `"old_string not found"`.
- 1 → replace, return `replacements: 1`.
- ≥2 with `replace_all=false` → error `"old_string is not unique (N matches) — add surrounding context or set replace_all=true"` (include the count).
- ≥2 with `replace_all=true` → replace all, return `replacements: N`.
- `old_string == new_string` → error `"old_string and new_string are identical — refusing no-op"`. Prevents the model from spinning on a malformed call.

**Writing**
- Write atomically: write to `<path>.<random>.tmp` in the same directory, fsync, then rename over the original. Same-directory rename is atomic on NTFS and POSIX; cross-directory is not.
- Preserve file mode and timestamps where the platform allows.

**Mutation tracking and checkpoints**
- Set MCP annotation `destructiveHint: true` so `McpToolProxy` exposes `is_mutating=true`.
- Python-side `predict_touched_paths(input)` returns `[input["path"]]` (Strict strategy, like `write_file` / `append_file` — see [DESIGN-tool-system.md](../design/DESIGN-tool-system.md#mutation-metadata)).
- Without this wiring `/rewind` will not restore `edit_file` mutations — make it a hard part of "done".

#### Description (LLM-facing)

Opinionated, in the same style as `grep`'s description:

> *"Use this for surgical edits to existing files. Provide enough surrounding context in `old_string` to make the match unique — uniqueness is enforced. Do **not** use `write_file` to change a few lines (it wastes tokens and risks corrupting unrelated content). Do **not** use `bash sed` / `awk`. Use `write_file` only to create a new file or replace its entire contents."*

#### Tests

Unit:
- Single match → `replacements: 1`.
- Multiple matches with `replace_all=false` → uniqueness error includes the count.
- Multiple matches with `replace_all=true` → all replaced.
- `old_string` not found → not-found error.
- File not found → not-found error (no auto-create).
- Binary file (null byte in first 8 KB) → refusal.
- UTF-8 BOM file → BOM preserved.
- CRLF file with LF `old_string` → match succeeds, file remains CRLF.
- LF file with CRLF `old_string` → match succeeds, file remains LF.
- Atomic-write crash simulation (kill between temp-write and rename) → original intact.
- File over size limit → refusal.
- `old_string == new_string` → refusal.

Integration:
- Mutation captured by the checkpoint system; `/rewind` restores the pre-edit content.
- Tool is reachable through the same provider-conversion pipeline as MCP tools (see [DESIGN-tool-system.md § Provider Schema Conversion](../design/DESIGN-tool-system.md#provider-schema-conversion)) for at least Anthropic + one OpenAI-compatible provider.

#### Routing and cache interaction

`edit_file` is high-frequency for any code task. Implications:

- Add to the **always-loaded** tool set, not gated behind `tool_search`. Forcing a search-then-load round-trip on every edit would torch the cost story for cheap-model routes.
- Same applies to the upgraded `read_file` from Phase 3.
- Audit `RoutingPolicies` entries with `tool_search_only=true` (e.g. small-model routes) to confirm the FS basics remain in scope. See [DESIGN-cache-preserving-tool-routing.md](../design/DESIGN-cache-preserving-tool-routing.md).

#### Out of scope (with rationale)

- **`multi_edit`** (Claude Code's batched-edit-to-one-file variant). Deferred. The agent loop already executes same-turn tool calls in parallel via `asyncio.gather` (`turn_engine.py:459`), so the model can issue N independent `edit_file` calls in one turn and they run concurrently. That covers the bulk of `MultiEdit`'s value at zero new surface area. Reconsider if measurement shows the model serializing edits unnecessarily.
- **Regex / fuzzy matching.** Exact-string only. Regex tempts the model into brittle patterns; the uniqueness check + `read_file` line numbers from Phase 3 provide enough precision in practice.

#### Sequencing

Phase 2 is a **hard prerequisite** of the `edit_file` line in Phase 1's directive. Either ship Phase 2 first, or split Phase 1 into wave A (general FS directives) and wave B (`edit_file` directive) gated on Phase 2 merging. Otherwise the model will confidently call a tool that does not yet exist.

#### Deliverable

`edit-file.ts` + `index.ts` registration + Python-side `predict_touched_paths` wiring + unit and integration tests + `ToolFormatting` config entry + description rewrite. Phase 1's `edit_file` directive activates only after this lands.

### Phase 2b — Add `delete_file` MCP tool

Small companion to Phase 2. Removes the last common reason to reach for `bash` for everyday FS work, completing the "bash as last resort" framing.

```
delete_file(path: string) -> { path: string, deleted: boolean }
```

- Resolve via `PathPolicy`.
- File not found → error (do not silently succeed — catches typos).
- Refuse to delete directories. A separate `delete_dir` can come later if needed.
- `destructiveHint: true`. `predict_touched_paths` returns `[path]`. Checkpoint must capture the file **before** deletion so `/rewind` can restore it.

Description: *"Delete a single file. Refuses directories. Use `bash` only for recursive or bulk deletion."*

Tests: not-found, directory refusal, successful delete + `/rewind` round-trip.

**Deliverable:** new tool + tests + `ToolFormatting` entry. Independent of Phase 2 — can ship in either order.

### Phase 3 — Upgrade `read_file`

Currently `read_file` is `readFile(path, "utf-8")` and returns raw text. Upgrade to:

1. **Line-numbered output** in `cat -n` format (matches Claude Code's `Read` exactly so the model's output instincts transfer).
2. **`offset` and `limit` parameters** for large files. Default: read up to 2000 lines from line 1.
3. **Path policy gating** (closes part of ISSUE-005 for the read path).
4. Optional: warn / refuse on binary files. Explicit error rather than dumping raw bytes.

The line-numbered output is what makes `edit_file` ergonomic — the model can quote `file:line` from `read_file` output and feed coordinates back into edits.

**Cost note:** `cat -n`-style line numbers add ~5–7 tokens per line versus the raw read. Negligible for files in the typical 100–500 line range; for the 2000-line default cap that is roughly +10–14 K tokens compared to the raw bytes. The cap exists for that reason. The description must tell the model to pass `offset`/`limit` for large files instead of paging through the default.

**Deliverable:** updated `read-file.ts` + description rewrite. Backwards-incompatible for any consumer reading the raw text via `structuredContent.content`, but the agent only consumes the `text` content block. (Codegen subprocesses also call MCP tools — confirm none depend on the raw `read_file` output before merging.)

### Phase 3b — Migrate `write_file` / `append_file` onto `PathPolicy` — **Completed 2026-05-09**

Shipped as a standalone change ahead of the rest of the plan. `write_file` and `append_file` now route paths through `resolveAllowed(policy, path, { mustExist: false })`; absolute paths outside `FILESYSTEM_WORKING_DIR` / `FILESYSTEM_ALLOWED_DIRS` are rejected; symlinks pointing outside are caught by `realpath`. Documented in `documentation/docs/setup/mcp-servers.md`, `documentation/docs/design/tools/write-file/README.md`, and `CHANGELOG.md` (2026-05-09 entry).

Carved out of the original Phase 4. [ISSUE-005's Related section](../issues/ISSUE-005-bash-tool-bypasses-path-policy.md) flags the asymmetry: `grep` and `glob` enforce containment, but `write_file` and `append_file` do not — "backwards" given the write tools are higher-risk. Phase 3 migrates `read_file`; this phase finishes the job.

The change is the ~15-line-diff sketched in ISSUE-005:

```ts
// Today (write_file / append_file)
const resolvedPath = path.isAbsolute(input.path)
  ? input.path
  : path.resolve(workingDir, input.path);

// After
const resolvedPath = await resolveAllowed(policy, input.path, { mustExist: false });
```

Changes:
- Tool signatures: `(server, logger, workingDir: string)` → `(server, logger, policy: PathPolicy)`.
- `index.ts` passes `policy` instead of `workingDir`.
- `resolveAllowed` adds: `realpath` resolution (defeats symlink escape), containment check, clear error message naming `FILESYSTEM_ALLOWED_DIRS` on denial.

**Behaviour change to flag in release notes:** absolute paths outside `FILESYSTEM_WORKING_DIR` (and not in `FILESYSTEM_ALLOWED_DIRS`) start failing for `write_file` / `append_file`. Today they silently succeed.

**Sequencing:** independent of Phase 4. Recommended to ship **before** Phase 4 — once writes are gated, the bash escape hatch becomes the only way to write outside the workspace, which makes Phase 4's residual-risk story honest rather than misleading.

**Deliverable:** updated `write-file.ts`, `append-file.ts`, `index.ts`; tests for absolute-path rejection and `FILESYSTEM_ALLOWED_DIRS` opt-in round-trip; release-note entry.

### Phase 4 — Bash containment (close ISSUE-005)

Framed explicitly as **accident prevention**, not adversarial robustness. A determined agent can defeat string-level filters trivially — `sh -c "..."`, command substitution, env-var indirection, write-then-execute, base64-decoded pipelines, in-shell `cd`. Real isolation requires OS-level controls (containers, AppArmor, sandbox-exec, Windows Job Objects) and is **out of scope** for this plan.

The goals here are narrow and measurable:

- Catch the no-config user who does not know to set the env vars.
- Catch obvious typos and slips (`cat /etc/...` when a workspace path was intended; `cd ../..` when the model lost track).
- Make the residual adversarial risk explicit in the bash tool description so a reader is not misled.

#### Already in place — not new work

`bash.ts:91-92` already invokes `execFile` with `cwd: workingDir`. Earlier drafts of this plan listed "working-directory pinning" as new work; it is not. The pinning sets the *initial* cwd only — the model can still `cd` mid-command to operate elsewhere, so it does not by itself prevent workspace escape. Phase 4 leaves this as-is and addresses escape via the path guard below.

#### What this phase ships

1. **`FILESYSTEM_BASH_PATH_GUARD` — default ON, opt-out via `=false`.**
   - Tokenize the command, find anything that looks like a path on the host platform: POSIX `/...`; Windows drive-letter `[A-Z]:\\...` / `[A-Z]:/...`, and UNC `\\server\share`.
   - Also flag any token containing `..` whose resolved form would land outside the workspace. ISSUE-005's "absolute paths only" framing misses the most common accident — `cd ../..; rm -rf .` — so the scan must handle relative traversal too.
   - Resolve each candidate via `realpath` (same primitive the file tools use after Phase 3 + Phase 3b — defeats symlink escape).
   - Reject if the resolved path is outside `FILESYSTEM_WORKING_DIR` and not in `FILESYSTEM_ALLOWED_DIRS`.
   - **Default-on is what gives Phase 4 a real-world delta.** Without it, the no-config user gets no behavioural change at all and ISSUE-005 is "closed" only by adding a knob nobody turns.

2. **`FILESYSTEM_BASH_ALLOWED_COMMANDS` — opt-in, three states:**
   - **Unset** → no filter (current behaviour).
   - **Empty string (`""`)** → deny-all (hard kill switch).
   - **Comma-separated list** → matches **only the first token** of the command. Pipes (`| head`), chains (`&& rm`), subshells (`(rm ...)`), and command substitution (`$(...)`, backticks) are **not** decomposed and **not** checked. This is documented as a known gap, not a security claim — see "Deliberately not shipped" below.

3. **Tool description rewrite** — also covered by Phase 1, but listed here for ISSUE-005 acceptance closure. Description must explicitly state: bash is *not* OS-sandboxed; the two env vars and what they do; preference for `read_file` / `grep` / `glob` / `edit_file` for FS work.

4. **Documentation:** env vars added to `documentation/docs/operations/config.md` and the filesystem package README, per [ISSUE-005 §66-67](../issues/ISSUE-005-bash-tool-bypasses-path-policy.md).

#### Deliberately not shipped (with rationale)

- **Chain / pipe / subshell decomposition for the allowlist.** Correct decomposition needs a real shell parser, and `cmd.exe` and `/bin/sh` chain semantics differ. Even with a perfect parser the bypasses in ISSUE-005 §17-23 remain. Defer until evidence the gap matters in practice (e.g. a user reports an accident the allowlist should have caught).
- **Syntactic refusal of `cd` as a token.** Bypassable (`PATH=$PWD/.. ./cd`, function shadowing, env-var indirection). Cwd pinning already sets the initial cwd; the path guard catches the rendered destination of any escape attempt that produces a checkable path token.
- **Lowering the 30 s timeout or 10 MB stdout cap** (`bash.ts:7, 94`). Out of scope. Revisit in a separate accident-prevention pass if either becomes a real source of harm.
- **Option B from ISSUE-005** — replace `bash` with structured tools (`git_command`, `run_tests`, `mkdir`/`mv`/`rm`, `package_script`). Deferred per ISSUE-005's own recommendation. Re-evaluate if any of: running untrusted prompts, multi-tenant use, or deployment to a sandbox-incompatible environment.

#### Platform handling

- **POSIX (`/bin/sh`):** absolute paths `/...`; chain operators `;`, `&&`, `||`, `|`.
- **Windows (`cmd.exe`):** drive-letter paths `C:\...` / `C:/...`, UNC `\\server\share`; chain operators `&`, `&&`, `||`, `|`. PowerShell is **not** spawned by `bash.ts` (`bash.ts:88-89`); if a user replaces the shell, all bets are off.

The path-guard tokenizer must handle both platforms; test matrix must include both.

#### Deliverable

- `bash.ts` updated: default-on path guard (incl. `..` traversal + `realpath`), opt-in allowlist with the three-state semantics above.
- Per-platform unit tests covering: absolute-path rejection (POSIX `/...`, Windows `C:\`, UNC `\\server\share`), `..` relative traversal rejection, symlink-escape rejection via `realpath`, allowlist first-token match, **explicit gap test** demonstrating that pipes/chains/subshells are not decomposed (documents the limitation in code so future maintainers don't assume it's a bug).
- Tool description rewrite (coordinates with Phase 1).
- `documentation/docs/operations/config.md` + filesystem package `README.md` updates per ISSUE-005 §66-67.
- Release-note entry: *"The no-config default now rejects absolute paths and `..` traversal outside the workspace from `bash`. Set `FILESYSTEM_BASH_PATH_GUARD=false` to restore previous behaviour."*

#### ISSUE-005 closure statement

Phase 4 (with Phase 3b) delivers **Option A** with the path guard default-on, satisfying ISSUE-005 acceptance criteria §62-69. **Option B** is explicitly deferred with re-evaluation criteria above. **Option C** (OS sandboxing) remains out of scope. Residual adversarial risk is acknowledged in the bash tool description rather than papered over.

### Phase 5 — Promote the `explore` sub-agent + behavioural eval set (post Phase 1)

Phase 1 adds the directive; this phase verifies it actually changes behaviour and provides the eval set that the acceptance criteria reference.

**Eval set** — 5–10 prompts of varying scope, checked into `tests/evals/filesystem-navigation/`:
- 2–3 narrow prompts (single file edit, single grep) — should *not* spawn `explore`, should use the dedicated tool not `bash`.
- 2–3 broad prompts (rename across codebase, find all callers of X) — should use `grep` + parallel `read_file` + `edit_file`, not `bash grep` / `write_file`.
- 2–3 vague exploration prompts (*"how does X work?"*, *"what calls Y?"*) — should spawn `explore` rather than running 6 inline greps.

Each prompt records the expected tool-call shape (which tools, parallel vs serial, sub-agent spawned y/n). A pass is "model picks the right tool family"; exact arguments are not scored.

**Pass threshold:** 80% pass rate across the set, no single prompt failing across 3 consecutive runs (handles model non-determinism).

If the eval shows the model still inlines greps, tune the directive's threshold and the `explore` agent's description, then re-run.

Optional: tweak `SubAgentRunner` defaults so `explore` runs on a cheaper model (it likely already does — verify against `agent_config.py`).

**Deliverable:** eval set committed under `tests/evals/`, run script, results doc, any tuning commits.

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
- **Bash allowlist remains opt-in.** Most users will not configure it. The path guard ships **default-on** to give the no-config case real protection against absolute-path and `..`-traversal accidents. Real adversarial containment still requires OS-level isolation (containers, AppArmor, Windows Job Objects) — out of scope.
- **Default-on path guard may break workflows that depend on writing outside the workspace via `bash`.** Mitigation: documented opt-out via `FILESYSTEM_BASH_PATH_GUARD=false`; release-note entry; the `FILESYSTEM_ALLOWED_DIRS` knob already exists for users who need extra roots.
- **Phase 3b is a behavioural break for absolute-path writes.** Today `write_file` / `append_file` silently accept absolute paths anywhere on disk. After Phase 3b they require the path to be inside `FILESYSTEM_WORKING_DIR` or `FILESYSTEM_ALLOWED_DIRS`. Mitigation: release note + clear error message naming the env var.

## Acceptance criteria

For the plan as a whole:

1. The agent, given *"find every place X is called and rename to Y"* with **no FS-tool guidance in the user message**, uses `grep` (not `bash grep`), uses `edit_file` (not `write_file`), and issues independent reads in parallel. Verified against a 5–10 prompt eval set (see Phase 5), not a single hand-picked example.
2. The agent, given a vague codebase question, spawns the `explore` sub-agent rather than running 6 inline greps. Same eval-set-based verification.
3. `bash` is only invoked when no dedicated tool fits (running tests, git commands, build tools).
4. ISSUE-005 is closed by Phase 3b + Phase 4: write tools enforce `PathPolicy`; bash ships a default-on path guard covering absolute paths, `..` traversal, and symlink escape; Option B is documented as deferred with re-evaluation criteria. The plan does not claim to close the adversarial portion of ISSUE-005 — that requires OS-level isolation and is out of scope.
5. All Phase 1–4 work passes existing tests + adds tests for `edit_file`, `delete_file`, the upgraded `read_file`, the migrated `write_file`/`append_file`, and the bash path guard (test list specified per phase, not left as "add tests").
6. `edit_file` round-trips correctly on CRLF files (Windows-default in this repo) — verified by a dedicated test, not assumed.
7. The bash path guard is verified on **both** POSIX and Windows path syntax (`/...`, `C:\...`, `\\server\share`, `..` traversal, symlink resolution) — single-platform pass is not sufficient.

## Effort estimate

Rough, assuming one engineer:

| Phase | Estimate |
|---|---|
| 1 — Prompt + descriptions | 0.5 day |
| 2 — `edit_file` tool (incl. CRLF handling, atomic write, checkpoint wiring, full test list) | 1.5–2 days |
| 2b — `delete_file` tool | 0.5 day |
| 3 — `read_file` upgrade (incl. round-trip tests for offset/limit/line-numbered output) | 1 day |
| 3b — Migrate `write_file` / `append_file` onto `PathPolicy` | 0.5 day |
| 4 — Bash containment (ISSUE-005) — default-on path guard, opt-in allowlist, per-platform tests | 1.5–2 days |
| 5 — Explore sub-agent verification + tuning | 0.5 day |
| 6 — Image/PDF/notebook (optional) | 1–2 days |

Phases 1–3 + 3b together — roughly **3.5 days** — deliver the bulk of the user-visible improvement. Phase 4 adds another 1.5–2 days; that is what closes ISSUE-005 in its accident-prevention scope. Earlier estimates undercounted both `edit_file` test coverage (CRLF, atomic-write crash sim, BOM, binary refusal) and the per-platform test matrix the bash path guard requires.

## Reference material

### Claude Code documentation

- **Main docs**: <https://docs.claude.com/en/docs/claude-code/overview>
- Pages of particular interest (navigate from the main docs):
  - **Tools Reference** — tool descriptions, parameters, and behavioural notes for `Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash`
  - **Sub-agents** — design and usage of the `Explore` sub-agent (read-only, Haiku-fast, isolated context)
  - **Best Practices** — context management, parallel tool calls, when to delegate to a sub-agent
  - **Settings** — `.claude/settings.json` permission/allowlist syntax (relevant to Phase 4 bash containment)
- **Repo / issues**: <https://github.com/anthropics/claude-code>

### Underlying tools that Claude Code's `Glob`/`Grep` wrap (and which our equivalents already use)

- **ripgrep** (`grep` backend): <https://github.com/BurntSushi/ripgrep>
- **fast-glob** (`glob` backend): <https://github.com/mrmlnc/fast-glob>

### Internal sources informing this plan

The audit was a one-shot conversational review (2026-05-09) — the conversation itself is not durable, so the findings are captured in this plan as the persistent artifact. All citations below are reproducible from the current tree:

- Audit of `mcp_servers/ts/packages/filesystem/src/` — current FS-tool inventory and gaps. Findings reproduced in the **Current state (audit summary)** table above; `git log mcp_servers/ts/packages/filesystem/` gives the contemporary history.
- Verbatim quotes of the model-facing `grep` tool description (`grep.ts:18-25`) and the bash tool description (`bash.ts:13`) — re-readable directly from those line ranges.
- `system_prompt.py` directives reviewed for FS-navigation guidance gaps — the relevant directives are named in Phase 1.1.
- Comparison against Claude Code is captured in the **What Claude Code does differently** section above; that section *is* the comparison table, so the conversation is not load-bearing for the plan's claims.

## Related

- [ISSUE-005: bash tool bypasses filesystem path policy](../issues/ISSUE-005-bash-tool-bypasses-path-policy.md) — Phase 4 closes this
- [DESIGN-tool-system.md](../design/DESIGN-tool-system.md) — `tool_search` and dynamic tool list
- [DESIGN-task-decomposition.md](../design/DESIGN-task-decomposition.md) — sub-agent infrastructure that Phase 5 leverages
- [DESIGN-agent-loop.md](../design/DESIGN-agent-loop.md) — where parallel tool execution lives (`asyncio.gather` in `turn_engine.py:459`)
- [DESIGN-agent-loop-react-and-langgraph.md](../design/DESIGN-agent-loop-react-and-langgraph.md) — places this plan in the broader ReAct/agent-loop context
