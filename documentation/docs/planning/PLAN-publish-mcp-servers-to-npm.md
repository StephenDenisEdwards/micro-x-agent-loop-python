# Plan: Publish MCP Servers to npm

**Status:** In Progress — Phase 1 code-complete (pending npm publish)
**Date:** 2026-04-29
**Owner:** —
**Reference:** [Publishing the Google MCP Server (worked example)](../guides/publishing-google-mcp.md)

## Context

Today our TypeScript MCP servers in `mcp_servers/ts/packages/` are a private monorepo. To use any of them in another project (or share them with other agents / Claude Desktop / Claude Code users), the consumer has to clone this repo, run `npm install && npm run build`, and hand-write absolute `node /path/to/dist/index.js` lines into their MCP client config. That's the wrong friction level for a reusable component.

Industry-standard distribution for TypeScript MCP servers is `npx -y @scope/mcp-name` resolved from the public npm registry. That single line works in Claude Desktop's `claude_desktop_config.json`, Claude Code's `.mcp.json`, and our own `config.json`'s `McpServers` section. Once published, our servers become drop-in components for anyone running an MCP-aware client.

The blocker today is mechanical — the workspace `*` dependency on `@micro-x/mcp-shared` is unpublishable, no package has the metadata npm requires, and we have no release pipeline. None of this is conceptually hard; it just needs a focused pass and a working canary before we put credential-bearing servers (Google, GitHub, X) through it.

The full deployment recipe for a single server is documented in [`guides/publishing-google-mcp.md`](../guides/publishing-google-mcp.md). This plan covers the staged rollout across all eleven servers, the supporting infrastructure (CI, versioning convention, smoke tests), and the acceptance criteria.

## Goals

- Every `@micro-x/mcp-*` package installable via `npx -y @micro-x/mcp-<name>` from a clean machine.
- Each package self-documenting on npmjs.com (README, required env vars, install snippets for the three main clients).
- Releases triggered by git tags, with provenance attestations.
- Token/credential cache paths under user control via env vars — never written to package-internal directories.
- All existing servers in `mcp_servers/ts/packages/` shipped (eleven total, including `shared`).

## Non-goals

- DXT bundles for Claude Desktop one-click install — listed as optional in the worked example, deferred until npm flow is solid.
- Auto-generation of MCP client configs (separate concern, fits under [End-User Deployment](PLAN-end-user-deployment.md)).
- Publishing the Python agent loop itself to PyPI — different distribution channel, different audience.
- Versioning lockstep across servers — each package versions independently.

## Approach

Six phases. Phase 1 establishes the canary (`mcp-echo` — no auth, no native deps). Phase 2 establishes the credential pattern (`mcp-google` — the worked example, drives all the hard requirements). Phases 3–5 mechanically replicate to the remaining servers, grouped by complexity. Phase 6 automates and documents.

Each server publish must satisfy the full checklist from `guides/publishing-google-mcp.md` (package metadata, README, LICENSE, configurable credential path, `--help` flag, dry-run inspection, smoke test in all three clients).

## Phase 1 — Canary: publish `@micro-x/mcp-shared` and `@micro-x/mcp-echo`

`echo` is the simplest server we have — no auth, no env vars, one tool. It validates the entire publish pipeline before we put anything credential-bearing through it.

**Deliverables:**

1. ~~Register the `@micro-x` scope on npmjs.com under the project owner's account; enable 2FA on the account. Decide org membership policy (single owner vs. team).~~ **Pending** — manual step.
2. ~~Pick a license (MIT recommended unless we have a reason otherwise). Add `LICENSE` file at `mcp_servers/ts/` root and copy into each package directory we publish.~~ **Done 2026-04-29.** MIT license at `mcp_servers/ts/LICENSE`, copied into `shared/` and `echo/`.
3. ~~Apply the `package.json` template from the worked example to `packages/shared/`:~~ **Done 2026-04-29.** `version: "1.0.0"`, `publishConfig.access: "public"`, `files`, `engines`, `repository`/`homepage`/`bugs`/`keywords`, `prepublishOnly` script.
4. ~~Apply the same template to `packages/echo/` and change `"@micro-x/mcp-shared": "*"` → `"@micro-x/mcp-shared": "^1.0.0"`.~~ **Done 2026-04-29.** Also added `chmod` step to build script for POSIX bin shim.
5. ~~Write `packages/shared/README.md` and `packages/echo/README.md`.~~ **Done 2026-04-29.** Shared: internal utilities disclaimer + exports table. Echo: install snippets for Claude Desktop/Code/loop, tool docs, `--help` flag docs.
6. ~~Run `npm pack --dry-run` against both. Inspect tarballs — confirm no `src/`, no `tsconfig*`, no source maps unless we want them.~~ **Done 2026-04-29.** Both clean: `dist/`, `README.md`, `LICENSE`, `package.json` only. Shared 12.7 kB, Echo 3.2 kB.
7. `npm login`, `npm publish -w packages/shared`, then `npm publish -w packages/echo`. **Pending** — manual step after scope registration.
8. From a clean directory: `npx -y @micro-x/mcp-echo --help` succeeds and the server speaks MCP over stdio. **Pending** — after publish.
9. Add the canary install line to the project README. **Pending** — after publish.

**Also done:** Added `--help` / `-h` flag to `echo/src/index.ts` (prints usage, tools, exits 0).

**Acceptance:** A fresh user with only Node 18+ installed can run `npx -y @micro-x/mcp-echo` and use the `echo` tool from Claude Desktop, Claude Code, and our own loop.

**Rollback:** If publish fails or the published artifact is broken, `npm deprecate @micro-x/mcp-echo@<version> "broken — use later release"`. Never `npm unpublish` after 72 hours (npm policy); deprecate and ship a patch instead.

## Phase 2 — Worked example: publish `@micro-x/mcp-google`

Establishes the pattern for credential-bearing servers. Everything in the worked example doc lands here.

**Deliverables:**

1. Apply the `package.json` template from the worked example to `packages/google/`.
2. Write `packages/google/README.md` covering: install snippets for the three clients, required env vars (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_TOKEN_CACHE_PATH`), inline OAuth Cloud Console setup walkthrough (or link to existing `guides/google-mcp-setup.md`), tool table, security/credentials notes.
3. Make the OAuth token cache path configurable via `GOOGLE_TOKEN_CACHE_PATH`. Default to `${XDG_DATA_HOME:-$HOME/.local/share}/mcp-google/tokens.json` on POSIX and `%APPDATA%/mcp-google/tokens.json` on Windows. Document the default in the README and the worked example.
4. Add `--help` / `-h` flag to `src/index.ts` that prints required env vars and exits 0 — required so `npx @micro-x/mcp-google --help` produces useful output instead of triggering an OAuth flow.
5. `npm pack --dry-run` and inspect.
6. `npm publish -w packages/google`.
7. Smoke-test `npx -y @micro-x/mcp-google --help` from a clean directory with no env vars set — should print env requirements and exit 0.
8. Wire the published package into Claude Desktop, Claude Code, and our own loop using `npx`. Verify `gmail_search` (read-only, lowest blast radius) works in all three before declaring done.

**Acceptance:** A user with their own Google Cloud OAuth credentials can install via `npx -y @micro-x/mcp-google` and complete an end-to-end OAuth flow without modifying any code.

## Phase 3 — Replicate to remaining no-auth and simple-auth servers

Mechanical application of the Phase 2 pattern. Group by similarity to keep review tight.

**Servers:** `mcp-web`, `mcp-filesystem` (no auth or simple env-var auth).

**Per-server deliverables (each):**

1. Apply `package.json` template.
2. Write `packages/<name>/README.md`.
3. Make any local file paths or caches configurable via env var.
4. Add `--help` flag.
5. `npm pack --dry-run` and inspect.
6. Publish.
7. Smoke-test in one client (Claude Code is fastest for verification — `.mcp.json` reload is cheap).

**Acceptance:** Both servers installable via `npx -y` and operational in at least one MCP client.

## Phase 4 — Replicate to OAuth and API-key servers

Higher-risk because credentials are involved. Each one repeats the Phase 2 credential-handling discipline.

**Servers:** `mcp-github`, `mcp-x-twitter`, `mcp-linkedin`, `mcp-devto`, `mcp-reddit` (currently blocked — skip until the upstream Reddit blocker clears), `mcp-anthropic-admin`.

**Per-server deliverables:** same as Phase 3, plus:

- Confirm any local credential cache (OAuth tokens, refresh tokens) is configurable via a server-specific env var (`GITHUB_TOKEN_CACHE_PATH`, `X_TOKEN_CACHE_PATH`, etc.) with a documented platform-appropriate default.
- README must include a "Credentials" section with explicit security notes (where tokens are written, what scopes are required, how to revoke).
- Smoke-test the lowest-blast-radius read-only tool first; do not test mutating tools (post, send, delete) against production accounts during the publish-verification step.

**Acceptance:** Each server installable via `npx -y` with credentials supplied via env vars; read-only tools verified against a test account.

## Phase 5 — Specialty server: `mcp-interview-assist`

This server has STT/recording dependencies that may carry native modules or platform-specific behaviour. Audit before applying the standard template — bundling decisions (Option A vs. Option B in the worked example) may differ for this one.

**Deliverables:**

1. Inventory native dependencies and platform-specific code paths.
2. Decide bundling strategy (likely keep `tsc` + real `@micro-x/mcp-shared` dep, but verify native modules survive `npm install` on Windows / macOS / Linux).
3. Apply the `package.json` template with any required adjustments (`os` field, `cpu` field, `optionalDependencies` for platform-specific modules).
4. Write `packages/interview-assist/README.md` with explicit platform support matrix.
5. Publish and smoke-test on at least two of {Windows, macOS, Linux}.

**Acceptance:** Installable on the documented platforms; native module load succeeds; STT path verifies.

## Phase 6 — Automate and document

Once all servers are published manually at least once, automate the release pipeline so future versions don't drift.

**Deliverables:**

1. Add `.github/workflows/publish-mcp.yml`:
   - Trigger on tags matching `mcp-<name>-v*` (one tag pattern; the workflow extracts `<name>` and publishes the matching workspace).
   - Set up Node 20, run `npm ci` at `mcp_servers/ts/`, run `npm run build`.
   - Publish with `npm publish -w packages/<name> --provenance --access public` using an `NPM_TOKEN` repo secret.
   - On failure, post a comment on the triggering commit.
2. Document the release process in `documentation/docs/operations/publishing-mcp-releases.md`:
   - Tag convention (`mcp-google-v0.2.0`, etc.).
   - Versioning policy: independent semver per package; bump `@micro-x/mcp-shared` minor → all dependent servers must bump patch within one week.
   - Pre-release checklist: `npm pack --dry-run`, smoke test in clients, README diff review.
   - Deprecation policy: `npm deprecate` rather than unpublish; ship a patch.
3. Add a `mcp_servers/ts/CHANGELOG.md` (one section per package) and require updates as part of any PR that bumps a version.
4. Update `documentation/docs/architecture/SAD.md` to note that MCP servers are distributed via npm and are not part of the Python package boundary.
5. Update [`PLAN-end-user-deployment.md`](PLAN-end-user-deployment.md) to reference the published packages — onboarding can now use `npx` references in default configs instead of local paths.

**Acceptance:** Pushing a `mcp-echo-v1.0.1` tag results in a new published version on npm with provenance, no manual steps required.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| `@micro-x` scope is taken on npm | Check availability before Phase 1. If taken, pick an alternative scope (`@micro-x-agent`, `@microxa`) and apply consistently. Document the chosen scope in the operations doc. |
| Published `@micro-x/mcp-shared` breaks consumers via accidental breaking change | Treat `shared` as a public API. Any change to its exported surface bumps the major version; servers re-pin and re-publish in lockstep. Smoke-test all dependent servers before publishing a `shared` major. |
| OAuth token cache path change strands existing users on next upgrade | The first publish is `0.1.0` (no users yet). Future cache-path changes ship a one-shot migration shim that reads the old path and writes the new path. |
| `npm publish` from a developer machine ships local-only changes | Phase 6 moves all publishes to GitHub Actions. Until then, every manual publish must be from a clean checkout of the tagged commit. |
| Native modules in `mcp-interview-assist` fail to install on a platform | Phase 5 audit catches this. Worst case: ship that server with `os` restrictions and a documented limitation rather than blocking the others. |
| Tarball accidentally includes `.env` or other secrets | `files` allowlist prevents this by default — only `dist`, `README.md`, `LICENSE` ship. The `npm pack --dry-run` step in every phase is the verification. CI workflow can also run `npm pack --dry-run` and fail if any blocked filename appears. |

## Open Questions

1. **Org account vs. personal account on npm.** Pre-Phase-1 decision. Org is cleaner long-term but adds setup overhead. Default: org if more than one person will publish; personal otherwise.
2. **Public registry vs. GitHub Packages.** Public npm is more discoverable and is the default for `npx`. GitHub Packages requires `.npmrc` configuration on every consumer. Default: public npm unless we have a specific reason for private distribution.
3. **License choice.** MIT is the conventional default. Apache-2.0 if we want explicit patent grants. Decide before Phase 1.
4. **Bundling strategy** (Option A vs. Option B in the worked example). The plan assumes Option A (publish `shared`). Confirm or flip this before Phase 1.
5. **Versioning baseline.** Start `shared` at `1.0.0` (signalling stable public API) or `0.1.0` (signalling "expect breaks")? Default: `1.0.0` for `shared` since we'll be hesitant to break it; `0.1.0` for individual servers.

## Acceptance Criteria (Plan-level)

- [ ] All eleven `@micro-x/mcp-*` packages published to npm with provenance attestations.
- [ ] Each package has a per-package README on npmjs.com with install snippets for Claude Desktop, Claude Code, and the loop.
- [ ] Each credential-bearing server has a configurable token cache path documented in its README.
- [ ] A clean machine with only Node 18+ installed can use any server via `npx -y @micro-x/mcp-<name>`.
- [ ] GitHub Actions publishes new versions on tag push without any manual steps.
- [ ] Operations doc documents the release process; CHANGELOG exists and is current.
