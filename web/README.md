# micro-x-agent-loop-python — Web Frontend

A web frontend for the micro-x agent, built with **React 19** and **TypeScript**. Mirrors the Textual TUI in `src/micro_x_agent_loop/tui/`: chat log, tool panel, session sidebar, status bar, log panel, command palette, ask_user modal, and the keyboard shortcuts from `AgentTUI.BINDINGS`.

The frontend connects to the existing FastAPI server in `src/micro_x_agent_loop/server/app.py`:

| Surface | URL |
|---|---|
| Health | `GET /api/health` |
| Sessions | `GET/POST /api/sessions`, `DELETE /api/sessions/{id}` |
| Messages | `GET /api/sessions/{id}/messages` |
| Streaming chat | `WS /api/ws/{session_id}` |

The WebSocket protocol mirrors `WebSocketChannel` in `src/micro_x_agent_loop/server/ws_channel.py`.

## Quick start

```bash
# 1. Start the agent API server (from the repo root)
python -m micro_x_agent_loop --server start --broker

# 2. In another shell, run the dev server (proxies /api → 127.0.0.1:8321)
cd web
npm install
npm run dev          # http://127.0.0.1:5173
```

## Scripts

| Script | Purpose |
|---|---|
| `npm run dev` | Vite dev server (port 5173, /api proxy) |
| `npm run build` | Production build (`tsc -b && vite build`) |
| `npm run preview` | Preview the production build |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint over `src/` and `e2e/` |
| `npm test` | Vitest unit tests |
| `npm run test:coverage` | Vitest with coverage |
| `npm run test:e2e` | Playwright UI tests (uses the in-page mock WS harness) |

## Layout

```
src/
  api/             RestClient, AgentWebSocketClient, URL helpers
  components/      ChatLog, ToolPanel, SessionSidebar, StatusBar,
                   PromptInput, AskUserModal, CommandPalette, …
  hooks/           useAgentSession, useTheme
  state/           agentReducer (frame → view-model state machine)
  styles/          global.css (themes via data-theme on <html>)
  test/            mock-ws.ts, e2e-mock-bootstrap.ts, setup.ts
  types/           protocol.ts (WS frame shapes)
e2e/               Playwright specs
```

## Testing strategy

- **Unit tests (Vitest + Testing Library):** every component and module. The reducer is tested exhaustively for each frame type; the WebSocket client is tested with a `MockWebSocket` double that lets the test drive ``open`` / ``message`` / ``close`` / ``error`` events.
- **E2E tests (Playwright):** load the real built frontend with `VITE_E2E_MOCK_WS=1`. This installs a JavaScript-level `WebSocket` stub and `fetch` stub. Each spec drives the page via `window.__E2E__.emitFrame(...)` and reads the page's outgoing frames via `window.__E2E__.sentFrames()`. No Python backend required.

## Mapping TUI → web

| TUI (Textual) | Web (React) |
|---|---|
| `tui/app.py` `AgentTUI` | `src/App.tsx` |
| `widgets/chat_log.py` | `components/ChatLog.tsx` |
| `widgets/tool_panel.py` | `components/ToolPanel.tsx` |
| `widgets/session_sidebar.py` | `components/SessionSidebar.tsx` |
| `widgets/status_bar.py` | `components/StatusBar.tsx` |
| `widgets/log_panel.py` | `components/LogPanel.tsx` |
| `screens/ask_user_modal.py` | `components/AskUserModal.tsx` |
| `SlashCommandProvider` (palette) | `components/CommandPalette.tsx` |
| `BINDINGS` (Ctrl+S/T/L/P/D) | App keydown handler |
| Themes (`_THEMES`) | `hooks/useTheme.ts` + `styles/global.css` |
