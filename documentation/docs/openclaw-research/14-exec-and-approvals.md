# Exec Tool and Approvals

## Exec tool

Runs shell commands in the workspace. Supports foreground and background execution.

### Parameters

- `command` (required)
- `host` (`sandbox | gateway | node`) — where to execute (default: sandbox)
- `security` (`deny | allowlist | full`) — enforcement mode for gateway/node
- `ask` (`off | on-miss | always`) — approval prompts
- `elevated` (bool) — request elevated mode (gateway host)
- `timeout` (seconds, default 1800)
- `yieldMs` (default 10000) — auto-background after delay
- `background` (bool) — background immediately
- `pty` (bool) — run in pseudo-terminal
- `env` — key/value overrides
- `workdir` — defaults to cwd

### Important notes

- Sandboxing is **off by default**. When off, `host=sandbox` runs directly on the gateway host with no container and no approvals.
- `host=gateway` and `host=node` reject `env.PATH` and loader overrides (`LD_*`/`DYLD_*`) to prevent binary hijacking.
- Background sessions are scoped per agent.

### Process management

Background exec uses the `process` tool:
- `process poll <sessionId>` — check output
- `process send-keys <sessionId> ["Enter"]` — send keystrokes
- `process paste <sessionId> "text"` — bracketed paste
- `process submit <sessionId>` — send CR

## Exec approvals

The companion app / node host guardrail for letting a sandboxed agent run commands on a real host. Commands are allowed only when policy + allowlist + (optional) user approval all agree.

### Policy knobs

**Security** (`exec.security`):
- `deny` — block all host exec
- `allowlist` — allow only allowlisted commands
- `full` — allow everything

**Ask** (`exec.ask`):
- `off` — never prompt
- `on-miss` — prompt only when allowlist doesn't match
- `always` — prompt on every command

**Ask fallback** (when no UI is reachable):
- `deny` — block
- `allowlist` — allow if allowlist matches
- `full` — allow

### Allowlist

Per-agent glob patterns matching resolved binary paths:
```json
{
  "agents": {
    "main": {
      "security": "allowlist",
      "ask": "on-miss",
      "allowlist": [
        { "pattern": "~/Projects/**/bin/rg" },
        { "pattern": "/opt/homebrew/bin/*" }
      ]
    }
  }
}
```

Shell chaining (`&&`, `||`, `;`) allowed when every segment satisfies the allowlist. Command substitution (`$()`) rejected.

### Safe bins

Stdin-only binaries that can run without explicit allowlist entries. Force argv to literal text (no globbing, no `$VARS`). Default: `jq`, `grep`, `cut`, `sort`, `uniq`, `head`, `tail`, `tr`, `wc`.

### Approval flow

1. Exec tool returns `status: "approval-pending"` with an approval ID
2. Gateway broadcasts `exec.approval.requested` to operator clients
3. Operator resolves via Control UI, macOS app, or `/approve` in chat
4. Actions: **Allow once**, **Always allow** (add to allowlist), **Deny**
5. On completion: system events `Exec finished` / `Exec denied`

### Chat-forwarded approvals

```json5
{
  approvals: { exec: {
    enabled: true,
    mode: "session",
    targets: [{ channel: "slack", to: "U12345678" }]
  }}
}
```

Reply: `/approve <id> allow-once` / `allow-always` / `deny`

### apply_patch (experimental)

Subtool of `exec` for structured multi-file edits. OpenAI models only. Workspace-contained by default.

## Key references

- Exec tool: [`docs/tools/exec.md`](/root/openclaw/docs/tools/exec.md)
- Exec approvals: [`docs/tools/exec-approvals.md`](/root/openclaw/docs/tools/exec-approvals.md)
- Elevated mode: [`docs/tools/elevated.md`](/root/openclaw/docs/tools/elevated.md)
- Sandbox vs Tool Policy vs Elevated: [`docs/gateway/sandbox-vs-tool-policy-vs-elevated.md`](/root/openclaw/docs/gateway/sandbox-vs-tool-policy-vs-elevated.md)
