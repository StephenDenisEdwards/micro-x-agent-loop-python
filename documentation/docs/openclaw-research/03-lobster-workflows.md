# Lobster Workflow Runtime

Lobster is an external CLI binary that OpenClaw shells out to as a subprocess. It provides deterministic, multi-step tool pipelines with approval checkpoints.

## Core flow

1. **Agent calls the `lobster` tool** with a pipeline (inline or `.lobster` file):
   ```json
   { "action": "run", "pipeline": "email.triage --limit 20" }
   ```

2. **OpenClaw spawns `lobster run --mode tool <pipeline>`** as a child process with `LOBSTER_MODE=tool`. Captures stdout, enforces timeout (default 20s) and output cap (default 512KB).

3. **Lobster returns a JSON envelope** with one of three statuses:
   - `ok` — pipeline completed, results included
   - `needs_approval` — paused at a side-effect gate; includes `resumeToken` and human-readable prompt
   - `cancelled` — pipeline was cancelled

4. **If approval is needed**, the agent shows the prompt to the user, then resumes:
   ```json
   { "action": "resume", "token": "abc123...", "approve": true }
   ```
   Spawns `lobster resume --token abc123... --approve yes`.

## JSON envelope schema

```typescript
type LobsterEnvelope =
  | {
      ok: true;
      status: "ok" | "needs_approval" | "cancelled";
      output: unknown[];
      requiresApproval: null | {
        type: "approval_request";
        prompt: string;
        items: unknown[];
        resumeToken?: string;
      };
    }
  | {
      ok: false;
      error: { type?: string; message: string };
    };
```

## Why not just let the agent loop?

- **Deterministic** — pipelines are data (not free-form LLM reasoning); reproducible and auditable
- **Resumable** — paused workflows store state locally via a compact resume token; no replay needed
- **Approval gates** — first-class support for pausing before side effects
- **Token-efficient** — multi-step pipeline runs as one tool call instead of many agent turns

## Enabling

Optional plugin tool, disabled by default:
```json
{ "tools": { "alsoAllow": ["lobster"] } }
```

Requires the `lobster` CLI binary on PATH. Disabled in sandboxed contexts.

## Security

- `lobsterPath` must be absolute; basename must be exactly `lobster`
- `cwd` sandboxed to gateway working directory (no `..` escape)
- No stdin; only stdout/stderr captured
- SIGKILL on timeout; truncate + kill on output overflow
- Tolerates noisy stdout (logs before JSON) by extracting the last JSON suffix

## Integration with OpenClaw tools

Lobster pipelines can call back into OpenClaw via HTTP:
```
openclaw.invoke --tool llm-task --action json --args-json '{...}'
```
Hits the gateway's `POST /tools/invoke` endpoint for structured LLM calls within a pipeline.

## Tool parameters

```typescript
{
  action: "run" | "resume",
  pipeline: string,          // Pipeline string or .lobster file path
  argsJson: string,          // Optional JSON arguments
  token: string,             // Resume token (for "resume" action)
  approve: boolean,          // Approve/deny (for "resume" action)
  lobsterPath: string,       // Optional absolute path to lobster binary
  cwd: string,               // Optional working directory
  timeoutMs: number,         // Default 20000
  maxStdoutBytes: number     // Default 512000
}
```

## Key references

- Documentation: [`docs/tools/lobster.md`](/root/openclaw/docs/tools/lobster.md)
- Tool implementation: [`extensions/lobster/src/lobster-tool.ts`](/root/openclaw/extensions/lobster/src/lobster-tool.ts)
- Tests: [`extensions/lobster/src/lobster-tool.test.ts`](/root/openclaw/extensions/lobster/src/lobster-tool.test.ts)
- Plugin registration: [`extensions/lobster/index.ts`](/root/openclaw/extensions/lobster/index.ts)
- Plugin manifest: [`extensions/lobster/openclaw.plugin.json`](/root/openclaw/extensions/lobster/openclaw.plugin.json)
