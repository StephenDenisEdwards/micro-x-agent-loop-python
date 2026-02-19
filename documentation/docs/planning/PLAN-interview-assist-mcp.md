# Plan: Interview Assist MCP Integration

**Status: Completed (Phase 1 + STT extension)** (Updated 2026-02-19)

Implementation snapshot:

- Phase 1 analysis/evaluation MCP tools: Completed
- STT MCP tools (`ia_transcribe_once`, `stt_*`): Completed
- Phase 2 recommendations: Planned

## Goal

Expose `interview-assist-2` analysis and evaluation workflows as MCP tools so agent users can run interview diagnostics through natural-language requests.

## Scope

Phase 1 focuses on wrapping existing stable non-interactive CLI modes from:

- `Interview-assist-transcription-detection-console`

No behavior changes are required in `interview-assist-2` for this first version.

## Tool Surface (Phase 1)

- `ia_healthcheck`
- `ia_list_recordings`
- `ia_analyze_session`
- `ia_evaluate_session`
- `ia_compare_strategies`
- `ia_tune_threshold`
- `ia_regression_test`
- `ia_create_baseline`

## Architecture

1. MCP server implemented in Python (`mcp_servers/interview_assist_server.py`) using FastMCP.
2. Each MCP tool shells out to `dotnet run --no-build --project ... -- <args>`.
3. Results are returned as structured JSON-like payloads:
   - command output tails for diagnostics
   - file paths for generated artifacts
   - parsed evaluation summaries where available
4. Repo path is configurable per call, with fallback order:
   - tool argument `repo_path`
   - `INTERVIEW_ASSIST_REPO` environment variable
   - default local path (`C:\Users\steph\source\repos\interview-assist-2`)

## Risks and Mitigations

- Build/output noise corrupting stdio:
  - Use `--no-build` and require project to be built beforehand.
- Long-running evaluations:
  - Per-tool timeout parameters with sensible defaults.
- CLI output format drift:
  - Prefer output-file JSON parsing over console parsing where possible.

## Validation

1. Start MCP server locally.
2. Run `ia_healthcheck`.
3. Run `ia_list_recordings`.
4. Run `ia_analyze_session` on known JSONL.
5. Run `ia_evaluate_session` and verify metrics summary.

## Phase 2 (Recommended)

Propose changes in `interview-assist-2` for stronger machine contracts:

- Add a `--json` mode for non-interactive commands with stable schemas.
- Extract command handlers into reusable services for easier hosting.
- Optionally add native .NET MCP server in `interview-assist-2` to remove Python wrapper.
