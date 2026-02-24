# Browser Tool

OpenClaw can run a dedicated, isolated Chrome/Brave/Edge/Chromium profile that the agent controls via CDP (Chrome DevTools Protocol).

## Architecture

- A **control service** inside the Gateway accepts HTTP requests (loopback only)
- Connects to Chromium browsers via **CDP**
- For advanced actions, uses **Playwright** on top of CDP
- Agent gets one tool: `browser`

## Profiles

- **`openclaw`** — managed, isolated browser (no extension required)
- **`chrome`** — extension relay to your system browser (requires OpenClaw extension attached to a tab)
- Custom profiles for remote CDP endpoints

## Capabilities

- **Tab control**: list, open, focus, close
- **Navigation**: navigate, wait for URL/load/selector/JS predicate
- **Snapshots**: AI snapshot (numeric refs) or role snapshot (accessibility tree with `e12`-style refs)
- **Screenshots**: full page or element, with optional ref label overlays
- **Actions**: click, type, drag, select, hover, scroll into view, press keys
- **Forms**: fill multiple fields, upload files, handle dialogs
- **Downloads**: trigger and wait for downloads
- **State**: cookies, localStorage, sessionStorage (get/set/clear)
- **Environment**: offline mode, custom headers, HTTP auth, geolocation, media queries, timezone, locale, device emulation
- **Debugging**: console logs, network requests, response bodies, error collection, trace recording, PDFs

## Snapshot and ref system

Two snapshot styles:
- **AI snapshot** (default): numeric refs (`12`) resolved via Playwright's `aria-ref`
- **Role snapshot** (`--interactive`): role refs (`e12`) resolved via `getByRole()` — includes nth disambiguation

Refs are **not stable across navigations**. Re-snapshot and use fresh refs after page changes.

## Sandboxed sessions

- Default: `target="sandbox"` (sandbox browser container)
- `target="host"` requires `sandbox.browser.allowHostControl: true`
- `target="node"` routes to a paired node with browser capability

## Remote CDP

- Set `browser.profiles.<name>.cdpUrl` for remote browsers
- Supports auth via query tokens or HTTP Basic
- Browserless.io supported for hosted remote CDP

## Security

- Browser control is loopback-only; access via Gateway auth or node pairing
- `browser.evaluateEnabled` gates arbitrary JS execution (disable for safety)
- Remote CDP endpoints should be tunneled and protected
- Managed browser profile is separate from personal profile

## Key references

- Browser: [`docs/tools/browser.md`](/root/openclaw/docs/tools/browser.md)
- Chrome extension: [`docs/tools/chrome-extension.md`](/root/openclaw/docs/tools/chrome-extension.md)
- Browser login: [`docs/tools/browser-login.md`](/root/openclaw/docs/tools/browser-login.md)
- Linux troubleshooting: [`docs/tools/browser-linux-troubleshooting.md`](/root/openclaw/docs/tools/browser-linux-troubleshooting.md)
