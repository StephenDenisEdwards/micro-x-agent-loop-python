# Plan: JobServe MCP Server

**Status: Planned** (2026-05-08)

## Context

The `jobserve_apply` codegen attempt (see ISSUE-006 + PLAN-shared-mcp-http-transport)
established that the infrastructure for codegen-driven Playwright tasks works
end-to-end — agent boots playwright via SSE, codegen subprocess attaches via
`MICRO_X_PLAYWRIGHT_MCP_URL`, profile-lock contention is gone. But generating
**static apply code from a prompt** has been a long, frustrating dead end:

- The codegen LLM writes element-finding heuristics blind, never having seen
  the JobServe DOM. It guesses at structure ("there's probably a button labelled
  Apply"). When reality differs (Apply is a `link`, CV button is 14 lines from
  its label, working-status is a `combobox`), the static code can't adapt.
- We've spent a day patching one heuristic at a time. Each fix surfaces the
  next mismatch. There is no architectural improvement to the codegen prompt
  that would prevent the next class of bug.

The pattern that actually works in this project for every other external service
is hand-written TypeScript inside an MCP server, exposing a semantic surface to
the agent and hiding the mechanics inside.

| MCP server | What the LLM sees | What's hidden inside |
|---|---|---|
| `gmail` | `gmail_search`, `gmail_read`, `gmail_send` | OAuth, Google API |
| `linkedin` | `linkedin_jobs`, `linkedin_job_detail` | Scraping or LinkedIn API |
| `web` | `web_fetch`, `web_search` | HTTP, HTML parsing |
| `github` | `list_repos`, `create_pr` | REST API |
| `playwright` | `browser_*` low-level | CDP |

A `jobserve` MCP slots in cleanly. Hand-written Playwright code, locator-based
(robust to small DOM changes), maintained in one place. The agent (and any
codegen task) gets `jobserve_apply_to_job(...)` and never reasons about
`<span>` vs `<textbox>`.

## Goal

A `jobserve` MCP server that:

- Lives at `mcp_servers/ts/packages/jobserve/` alongside the other first-party
  MCP servers.
- Exposes high-level semantic tools to the agent.
- Implements the apply flow with hand-written Playwright code, not LLM
  heuristics. Recorded once with `npx playwright codegen`, polished by hand.
- Replaces the failed `tools/jobserve_apply/` codegen task entirely.

## Why this is the right architecture (briefly)

**LLM is good at**: ranking jobs against a CV, drafting tailored cover letters,
extracting structured data from unstructured pages. Already used well in
`jobserve_rss_aggregator`.

**LLM is bad at**: reliably composing low-level browser actions into a static
script. We've proven this repeatedly today.

This plan moves the mechanical apply work from "LLM-generated brittle code" to
"hand-written code maintained in one place," matching how the rest of the
codebase treats every other site.

## Proposed tool surface

```
jobserve_apply_to_job(
  job_url: string,                   // the .jsap URL from the aggregator
  cover_letter: string,              // tailored letter (from aggregator)
  email?: string,                    // fallback if not pre-filled by JobServe
  uk_working_status?: string,        // one of: uk_citizen | indefinite_leave
                                     // | eu_citizen | work_permit | needs_sponsorship
  cv_path?: string,                  // absolute path to PDF
) -> {
  status: "applied" | "skipped" | "failed",
  reason?: string,                   // why skipped/failed
  confirmation_text?: string,        // captured text from success page
}

jobserve_check_login() -> {
  logged_in: boolean,
  account_name?: string,             // visible if logged in
  hint?: string,                     // human-readable next step
}
```

Out of scope (at least for v1):

- `jobserve_search_jobs` — the RSS aggregator already does this; don't duplicate.
- `jobserve_get_job_detail` — same source.
- Bulk-apply orchestration — composition lives outside the MCP (in a small
  script, or as part of the aggregator's reporting).

## How it talks to Playwright

There are two viable implementation choices; Phase 0 picks one.

**Choice A — MCP-of-MCPs (clean composition):** the jobserve MCP server is itself
a client of the playwright MCP server (connects via SSE using
`MICRO_X_PLAYWRIGHT_MCP_URL`, same pattern as codegen tasks). High-level apply
operation composes low-level `browser_*` calls. No second browser instance, no
profile lock concerns.

**Choice B — Direct Playwright SDK:** `import { chromium } from 'playwright'`
inside the MCP server, manage its own browser context. Either with a separate
`--user-data-dir` (extra login burden) or by attaching to the agent's running
browser via CDP if `@playwright/mcp` exposes a CDP endpoint.

Choice A is the architecturally cleanest and reuses everything we built today.
Choice B is more direct but introduces a second browser-lifecycle concern.

## Phases

### Phase 0 — Scope and recording (~1 hr)

- Run `npx playwright codegen https://www.jobserve.com/gb/en/<some-jsap-url>` while logged in.
- Click through a complete apply flow once, manually. Save the generated TypeScript.
- Inspect what locators Playwright codegen chose; verify they're stable
  (`getByRole`, `getByLabel`, accessible-name based).
- Decide A or B for the Playwright integration.
- If A: confirm we can spawn an `@modelcontextprotocol/sdk` SSE client from
  inside an MCP server (same Node process listens on stdio for the agent AND
  speaks SSE outbound to playwright). Quick spike.

**Output:** decision A/B, a working TypeScript apply function from the recording.

### Phase 1 — Package scaffold (~2 hrs)

- New `mcp_servers/ts/packages/jobserve/` package, mirror `linkedin/`'s layout.
- `package.json`, `tsconfig.json`, `src/index.ts` skeleton.
- Build wired into the same npm workspace pattern.
- Empty `tools/list` returning the two tool stubs above.

### Phase 2 — Apply flow implementation (~1 day)

- Take Phase 0's recorded TypeScript as starting point.
- Convert to use the chosen Playwright access path (A or B).
- Add the parameter handling (`cover_letter`, `email` fallback, `uk_working_status`
  combobox selection by visible text, `cv_path` upload).
- Verify success by waiting for "Your application has been submitted" text on
  the next page (we have the actual confirmation string from user).
- Handle failure modes:
  - not logged in → return `{status: "skipped", reason: "not_logged_in"}`
  - CV file missing → `{status: "skipped", reason: "cv_path_invalid"}`
  - JobServe rejected the form → `{status: "failed", reason: "form_validation: <message>"}`
  - network/timeout → `{status: "failed", reason: "<details>"}`

### Phase 3 — MCP tool wrapper (~2 hrs)

- Wire `jobserve_apply_to_job` and `jobserve_check_login` into the FastMCP-style
  tool registration in `src/index.ts`.
- Schema validation via the shared input-schema helpers (see `linkedin/` for
  reference).

### Phase 4 — Integration with the rest of the project (~1 hr)

- Add `jobserve` entry to `config-base.json:McpServers`.
- Add to `tools/template-ts/scripts/tool-types.config.json` so types regenerate.
- Run `npm run regen-tool-types` in `tools/template-ts/`.
- Hand-write wrappers in `tools/template-ts/src/tools.ts` (`jobserveApplyToJob`,
  `jobserveCheckLogin`) following the established convention. See
  `documentation/docs/guides/codegen-tool-types.md`.

### Phase 5 — Retire the codegen apply task (~30 min)

- Delete `tools/jobserve_apply/` and the `manifest.json` entry it added.
- Drop `documentation/docs/jobsearch/prompts/jobserve-apply-codegen-prompt.md`
  or mark it superseded.
- The aggregator can either:
  - emit a separate "applies queue" file the user invokes the MCP against
    interactively, or
  - call `jobserveApplyToJob` directly from a small follow-up script the user
    runs after reviewing the aggregator's output.

## Open questions

1. **A vs B for Playwright integration** (resolved in Phase 0).
2. **Locator strategy in the recording.** Playwright codegen sometimes emits
   text-based locators that are fragile (`getByText('Apply')` matches multiple
   things). The Phase 2 polish step needs to prefer `getByRole('link', { name: 'Apply' })`
   style locators wherever possible.
3. **Login expiry mid-batch.** If a user is applying to 5 jobs and the session
   expires after job 3, what should happen? Options: stop the batch, ask the
   user via `ask_user`, mark remaining as skipped. v1: stop on first
   `not_logged_in`, return summary up to that point.
4. **Captcha / unusual-traffic detection.** JobServe might trigger anti-bot
   measures on rapid bulk-apply. Add rate limiting (default 5–10 seconds between
   jobs) to v1; add explicit captcha-detection skip in a follow-up if it bites.
5. **Concurrent shared-context risk.** If the user is using the browser
   manually while a `jobserve_apply_to_job` call is running, they collide
   (same as `--shared-browser-context` discussion in ISSUE-006). Document
   that the user shouldn't touch the browser during an apply call. Or add an
   explicit lock/queue inside the MCP server.

## Risk register

| Risk | Mitigation |
|---|---|
| JobServe redesigns the apply form | Hand-edit the recorded TypeScript; one place to fix; release a new version of the MCP. |
| Persistent profile cookies expire daily | Already handled by `jobserve_check_login()` — caller prompts user to re-login. |
| User runs the MCP without first logging in | Same — `check_login` first, return clear `not_logged_in` skip. |
| Playwright codegen produces fragile locators | Phase 2 polish: replace text-based with role-based locators. Spot-check by deliberately tweaking JobServe's DOM (DevTools) to make sure locators still resolve. |
| Captcha / 429 rate limiting | Default 5–10 s delay between applies. Detect-and-stop on captcha pages. |
| The MCP server breaks the agent's startup if @playwright/mcp isn't running (Choice A) | Fail soft — `jobserve_apply_to_job` returns `{status: "failed", reason: "playwright_unavailable"}` if SSE connect fails, rather than aborting agent boot. |

## Acceptance criteria

- `mcp_servers/ts/packages/jobserve/` package builds, exposes `jobserve_apply_to_job`
  and `jobserve_check_login` over stdio MCP.
- Registered in `config-base.json`, with the agent's connect_all spawning it
  successfully at boot.
- Registered in `tool-types.config.json`; `npm run regen-tool-types` writes
  the corresponding `JobserveApplyToJobArgs` etc.
- Wrappers in `template-ts/src/tools.ts` consuming those types.
- A real apply attempt against a live JobServe job (with the user logged in)
  completes successfully and returns `status: "applied"`. Verified by
  log + JobServe's confirmation email landing.
- All four documented failure modes return the right `status`/`reason`.
- `tools/jobserve_apply/` directory removed; manifest entry gone; codegen
  prompt file marked superseded or deleted.

## Effort estimate

| Phase | Effort |
|---|---|
| 0 — scope + recording | 1 hr |
| 1 — package scaffold | 2 hrs |
| 2 — apply flow implementation | ~1 day |
| 3 — MCP tool wrapper | 2 hrs |
| 4 — integration | 1 hr |
| 5 — retire codegen task | 30 min |
| **Total** | **~1.5–2 days** |

Phase 2 is the dominant cost — that's where the real engineering happens
(handling all four failure modes, robust locators, login-state checks). The
other phases are mostly mechanical scaffolding following established patterns.

## Related

- [ISSUE-006: Playwright profile contention](../issues/ISSUE-006-playwright-profile-contention.md) — the architectural work this builds on.
- [PLAN-shared-mcp-http-transport](PLAN-shared-mcp-http-transport.md) — Phase 4 SSE handoff is what Choice A (MCP-of-MCPs) would use.
- [Codegen tool types guide](../guides/codegen-tool-types.md) — Phase 4 follows this convention.
- `mcp_servers/ts/packages/linkedin/` — closest existing pattern to copy from.
- `tools/jobserve_rss_aggregator/` — already does the searching/scoring/cover-letter work; this MCP is the missing piece for the apply step.
- `tools/jobserve_apply/` — the failed codegen task that this plan replaces.
