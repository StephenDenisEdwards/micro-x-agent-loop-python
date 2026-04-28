# Publishing the Google MCP Server (Worked Example)

This guide documents everything we'd need to do to ship `@micro-x/mcp-google` to npm so that any MCP-compatible client (Claude Desktop, Claude Code, our own loop, etc.) can install it with a single `npx -y @micro-x/mcp-google` line.

It uses the Google server as the worked example because it's the most complex case — OAuth credentials, multi-tool surface, and a transitive workspace dep on `@micro-x/mcp-shared`. Everything here generalises to the other servers in `mcp_servers/ts/packages/`.

---

## Current state

```
mcp_servers/ts/
├── package.json              # private monorepo root
└── packages/
    ├── shared/               # @micro-x/mcp-shared  (workspace dep)
    └── google/               # @micro-x/mcp-google  → depends on shared via "*"
```

Blockers for `npm publish` today:

1. `package.json` declares `"@micro-x/mcp-shared": "*"` — npm rejects unresolvable specifiers on publish, and even if accepted, consumers can't install a phantom workspace package.
2. The `@micro-x` scope is not registered on the public npm registry under our control.
3. No `README.md` inside `packages/google/` (npm publishes the package-level README, not the repo root one).
4. No `files` allowlist — without one, npm ships `src/`, `tsconfig.json`, `node_modules` cruft.
5. No `prepublishOnly` build step — `dist/` could go stale or be missing entirely.
6. No `LICENSE`, `repository`, `keywords`, `engines`, `homepage`, `bugs` metadata.
7. The `dist/index.js` shebang line is correct, but we never `chmod +x` it during build, so `bin` invocation may fail on POSIX after install.
8. Tokens are cached to a path the package picks unilaterally — needs to be configurable so consumers control where credentials live.

---

## Step 1 — Decide the dependency strategy for `@micro-x/mcp-shared`

Two viable options. Pick one and apply consistently across all servers.

### Option A — Publish `@micro-x/mcp-shared` as a real package (recommended)

- Pros: smaller per-server tarballs, single source of truth, normal semver upgrades for consumers.
- Cons: every breaking change in `shared` needs a coordinated release across all `@micro-x/mcp-*` packages.

Steps:

1. Bump `packages/shared/package.json` to a real release version (`1.0.0`).
2. Add `"publishConfig": { "access": "public" }` to `shared/package.json`.
3. In `packages/google/package.json`, change `"@micro-x/mcp-shared": "*"` → `"@micro-x/mcp-shared": "^1.0.0"`.
4. Publish `shared` first (Step 6 below), then `google`.

### Option B — Bundle `@micro-x/mcp-shared` into each server with `tsup`

- Pros: each server is a single self-contained file; faster `npx` cold start; no cross-package version coordination.
- Cons: duplicated `shared` code across packages; bigger tarballs; harder to patch a `shared` bug everywhere.

Steps:

1. Add `tsup` as a dev dep in `packages/google/`.
2. Add a `tsup.config.ts` that bundles `src/index.ts` with `noExternal: ["@micro-x/mcp-shared"]` and externalises everything else (`googleapis`, `google-auth-library`, etc. stay as runtime deps so consumers don't pay for native rebuilds).
3. Replace `"build": "tsc"` with `"build": "tsup"`.
4. Drop `"@micro-x/mcp-shared"` from `dependencies` (it's now inlined). Keep it as a `devDependency` so the workspace link still works for development.

For our case **Option A is recommended** — the servers genuinely share code (logger, server factory, retry helpers) and we want one bug fix to flow to all of them.

---

## Step 2 — Update `packages/google/package.json`

Target shape:

```json
{
  "name": "@micro-x/mcp-google",
  "version": "0.1.0",
  "description": "Google MCP server — Gmail, Calendar, and Contacts tools over OAuth2",
  "keywords": ["mcp", "model-context-protocol", "google", "gmail", "calendar", "contacts", "claude"],
  "homepage": "https://github.com/<owner>/micro-x-agent-loop-python/tree/master/mcp_servers/ts/packages/google",
  "bugs": "https://github.com/<owner>/micro-x-agent-loop-python/issues",
  "repository": {
    "type": "git",
    "url": "git+https://github.com/<owner>/micro-x-agent-loop-python.git",
    "directory": "mcp_servers/ts/packages/google"
  },
  "license": "MIT",
  "author": "micro-x",
  "type": "module",
  "main": "dist/index.js",
  "bin": { "mcp-google": "dist/index.js" },
  "files": ["dist", "README.md", "LICENSE"],
  "engines": { "node": ">=18.17" },
  "scripts": {
    "build": "tsc && node -e \"require('fs').chmodSync('dist/index.js', 0o755)\"",
    "clean": "rm -rf dist",
    "start": "node dist/index.js",
    "prepublishOnly": "npm run clean && npm run build"
  },
  "publishConfig": { "access": "public" },
  "dependencies": {
    "@micro-x/mcp-shared": "^1.0.0",
    "google-auth-library": "^9.15.0",
    "googleapis": "^144.0.0",
    "html-to-text": "^9.0.5",
    "open": "^10.1.0",
    "zod": "^3.24.0"
  },
  "devDependencies": {
    "@types/html-to-text": "^9.0.4",
    "@types/node": "^22.0.0",
    "typescript": "^5.7.0"
  }
}
```

Key additions explained:

- `files`: allowlist what gets shipped. Without this, npm publishes everything not in `.npmignore` — `src/`, source maps, internal docs.
- `prepublishOnly`: guarantees the `dist/` we ship matches the source we tagged.
- `chmodSync` after `tsc`: cross-platform replacement for `chmod +x` so the `bin` shim is executable on POSIX after install.
- `publishConfig.access: "public"`: scoped packages default to private; this flag is required for free public publishes.
- `engines.node`: Node 18.17 is the minimum that ships modern fetch + ESM stably; matches our other servers.

---

## Step 3 — Add `packages/google/README.md`

This is what users see on npmjs.com. Required sections:

1. **One-liner**: "Google MCP server — Gmail, Calendar, Contacts."
2. **Install / run**: `npx -y @micro-x/mcp-google` and the equivalent Claude Desktop `claude_desktop_config.json` snippet.
3. **Required environment variables**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_TOKEN_CACHE_PATH` (see Step 4).
4. **OAuth setup walkthrough**: link to or inline the existing `google-mcp-setup.md` content (Cloud project creation, scopes, redirect URI).
5. **Tool list**: copy the table from `google-mcp-setup.md`.
6. **Security notes**: tokens are cached locally, never sent anywhere except Google's APIs.
7. **License**: MIT (or whichever we choose).

---

## Step 4 — Make credential storage configurable

Right now `mcp_servers/ts/packages/google/src/index.ts` reads `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` from env, but the OAuth token cache path is hard-coded inside `src/auth/`. For a published package, consumers must control where tokens land — they're long-lived secrets.

Required change: introduce a `GOOGLE_TOKEN_CACHE_PATH` env var (default to `${XDG_DATA_HOME:-$HOME/.local/share}/mcp-google/tokens.json` on POSIX and `%APPDATA%/mcp-google/tokens.json` on Windows). Document the default in the README.

Also add a `--help` / `-h` flag at the top of `index.ts` that prints required env vars and exits 0, so users running `npx @micro-x/mcp-google --help` get usable output instead of an OAuth flow.

---

## Step 5 — Add a `LICENSE` file

`packages/google/LICENSE` (and same in `packages/shared/`). Pick MIT unless we have a reason not to. npm warns at publish time if it's missing.

---

## Step 6 — First publish (manual dry run)

From `mcp_servers/ts/`:

```bash
# 1. Build everything in dependency order
npm run build

# 2. Sanity check what would actually go into the tarball
npm pack --dry-run -w packages/shared
npm pack --dry-run -w packages/google

# Look for:
#   - no src/, no tsconfig*, no .map files (unless we want them)
#   - dist/index.js present and listed
#   - README.md, LICENSE present

# 3. Log in (one-time per machine)
npm login

# 4. Publish shared first — google depends on it
npm publish -w packages/shared

# 5. Then google
npm publish -w packages/google

# 6. Smoke test from a scratch directory
cd /tmp && mkdir mcp-test && cd mcp-test
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... npx -y @micro-x/mcp-google --help
```

---

## Step 7 — Automate with GitHub Actions (recommended)

Manual `npm publish` is fine for the first release. For ongoing releases, add `.github/workflows/publish-mcp.yml` that:

1. Triggers on tags matching `mcp-google-v*` (and `mcp-shared-v*`, etc. — one tag pattern per package).
2. Sets up Node 20, runs `npm ci` at `mcp_servers/ts/`, runs `npm run build`.
3. Runs `npm publish -w packages/google --provenance --access public` using an `NPM_TOKEN` secret.
4. The `--provenance` flag attaches an attestation linking the published artifact to the workflow run that produced it — visible on npmjs.com as a verified badge. Free and worth turning on.

Tag convention: `mcp-google-v0.1.1` rather than a single repo-wide `v0.1.1`, so each server versions independently.

---

## Step 8 — Wire the published server into a client (verification)

This is the acceptance test for "it shipped correctly."

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%/Claude/claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "google": {
      "command": "npx",
      "args": ["-y", "@micro-x/mcp-google"],
      "env": {
        "GOOGLE_CLIENT_ID": "...",
        "GOOGLE_CLIENT_SECRET": "..."
      }
    }
  }
}
```

**Claude Code** (`.mcp.json` at the project root):

```json
{
  "mcpServers": {
    "google": {
      "command": "npx",
      "args": ["-y", "@micro-x/mcp-google"],
      "env": { "GOOGLE_CLIENT_ID": "...", "GOOGLE_CLIENT_SECRET": "..." }
    }
  }
}
```

**Our own loop** (`config.json`'s `McpServers` section): same shape — `command: "npx"`, `args: ["-y", "@micro-x/mcp-google"]`.

If all three clients can list `gmail_search` etc. and successfully complete an OAuth flow against a test Google account, the publish is good.

---

## Optional — Ship a DXT bundle for one-click Claude Desktop install

Anthropic's [Desktop Extension format](https://github.com/anthropics/dxt) wraps an MCP server + manifest into a single `.dxt` file that users install by double-clicking. Worth doing for the highest-traffic servers (Google, GitHub) but skip for the long tail.

Steps:

1. `npm install -g @anthropic-ai/dxt`.
2. `dxt init` inside `packages/google/` — generates `manifest.json`.
3. Fill in `display_name`, `icon`, `user_config` (declare `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` as user-prompted fields with `sensitive: true`).
4. `dxt pack` → produces `mcp-google.dxt`.
5. Attach `.dxt` files to GitHub Releases.

DXT and npm are not mutually exclusive — ship both.

---

## Generalising to the other servers

Once `mcp-google` is published, replicating to `mcp-github`, `mcp-x-twitter`, `mcp-reddit`, `mcp-linkedin`, `mcp-devto`, `mcp-anthropic-admin`, `mcp-filesystem`, `mcp-web`, `mcp-echo`, `mcp-interview-assist` is mechanical:

- Apply the Step 2 `package.json` template.
- Add a per-package README and LICENSE.
- Decide which env vars each needs and document them.
- Add a tag pattern + workflow line for each.

`mcp-echo` is the easiest second target — no auth, no native deps — and serves as a working canary for the publish pipeline before we put anything credential-bearing through it.

---

## Checklist

- [ ] Decide Option A (publish `shared`) vs. Option B (bundle).
- [ ] Update `packages/shared/package.json` with real version + `publishConfig`.
- [ ] Update `packages/google/package.json` per Step 2.
- [ ] Make token cache path configurable via env var.
- [ ] Add `--help` flag to `src/index.ts`.
- [ ] Write `packages/google/README.md`.
- [ ] Add `LICENSE` files.
- [ ] `npm pack --dry-run` and inspect tarball contents.
- [ ] `npm login` and publish `shared` then `google`.
- [ ] Smoke-test `npx -y @micro-x/mcp-google --help` from a clean directory.
- [ ] Wire into Claude Desktop, Claude Code, and our loop and verify all three.
- [ ] Add GitHub Actions workflow with `--provenance`.
- [ ] (Optional) Ship a `.dxt` bundle.
