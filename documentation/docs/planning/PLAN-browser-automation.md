# Plan: Add `browser` Tool (Phase 3)

**Status: Planned**

## Context

`web_fetch` (Phase 1) handles static pages and APIs. `web_search` (Phase 2) enables discovery. However, many modern sites require JavaScript rendering, and some tasks need form interaction (login flows, submissions, multi-step workflows). A browser automation tool fills this gap.

## Approach

Use Playwright for headless browser automation. Expose a single `browser` tool with an action-based interface rather than multiple fine-grained tools.

## Input Schema

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | One of: `navigate`, `click`, `type`, `screenshot`, `get_text`, `evaluate` |
| `url` | string | conditional | URL to navigate to (for `navigate` action) |
| `selector` | string | conditional | CSS selector (for `click`, `type`, `get_text`) |
| `text` | string | conditional | Text to type (for `type` action) |
| `script` | string | conditional | JavaScript to evaluate (for `evaluate` action) |

## Key Design Decisions

- **Single persistent browser session** per agent run — avoids startup cost on every call
- **Headless by default** — no GUI needed for agent use
- **Screenshot support** — return base64 image for visual debugging or page understanding
- **Text extraction** — reuse `html_to_text()` on rendered DOM for consistency with `web_fetch`
- **Timeout per action** — 30s default, same as `web_fetch`

## Implementation

- New file: `src/micro_x_agent_loop/tools/web/browser_tool.py`
- New dependency: `playwright` (requires `playwright install chromium` post-install)
- Register unconditionally in `tool_registry.py` (lazy browser launch on first use)

## Phase 4: Session Management (Future)

- Cookie persistence across agent runs
- Login flow support (credential storage)
- Browser profiles for different sites

## Not in Scope (Phase 3)

- Multi-tab management
- File upload/download
- Network interception
- Cookie/session persistence (deferred to Phase 4)

## Dependencies

- `playwright` — new dependency
- Chromium binary via `playwright install chromium`
