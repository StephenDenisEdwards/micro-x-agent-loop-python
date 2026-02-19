# Interview Assist MCP Server

This MCP server exposes `interview-assist-2` evaluation workflows and STT transcription workflows as tools for the Python agent.

## Location

- Server script: `mcp_servers/interview_assist_server.py`
- Target repo (default): `C:\Users\steph\source\repos\interview-assist-2`

## Prerequisites

- .NET SDK installed (`dotnet --version`)
- `interview-assist-2` cloned locally
- `Interview-assist-transcription-detection-console` buildable
- `DEEPGRAM_API_KEY` set when using transcription tools (`ia_transcribe_once`, `stt_*`)
- Python environment with `mcp` installed (already in this repo's dependencies)

Build once before first use:

```powershell
dotnet build C:\Users\steph\source\repos\interview-assist-2\Interview-assist-transcription-detection-console\Interview-assist-transcription-detection-console.csproj
dotnet build C:\Users\steph\source\repos\interview-assist-2\Interview-assist-stt-cli\Interview-assist-stt-cli.csproj
```

## MCP Configuration

Add this server to `config.json`:

```json
{
  "McpServers": {
    "interview-assist": {
      "transport": "stdio",
      "command": "python",
      "args": [
        "C:\\Users\\steph\\source\\repos\\micro-x-agent-loop-python\\mcp_servers\\interview_assist_server.py"
      ],
      "env": {
        "INTERVIEW_ASSIST_REPO": "C:\\Users\\steph\\source\\repos\\interview-assist-2"
      }
    }
  }
}
```

## Tools

- `ia_healthcheck`: verifies dotnet + repo/project paths
- `ia_list_recordings`: lists recent JSONL sessions in `recordings/`
- `ia_analyze_session`: generates markdown report from session JSONL
- `ia_evaluate_session`: computes precision/recall/F1 and returns summary
- `ia_compare_strategies`: compares heuristic/LLM/parallel detection modes
- `ia_tune_threshold`: tunes detection threshold
- `ia_regression_test`: checks current run against baseline
- `ia_create_baseline`: creates baseline JSON from session data
- `ia_transcribe_once`: captures live microphone/loopback audio for N seconds and returns Deepgram transcription JSON
- `stt_list_devices`: lists logical STT sources (`microphone`, `loopback`)
- `stt_start_session`: starts continuous STT polling session
- `stt_get_updates`: fetches incremental STT events since sequence id
- `stt_get_session`: reads session status/counters/latest transcript
- `stt_stop_session`: stops session

## Notes

- Commands run with `dotnet run --no-build` to avoid stdout build noise breaking MCP stdio transport.
- `ia_evaluate_session` and `ia_compare_strategies` use JSON output files where possible and return parsed data.
- For large outputs, tools return output tails to keep responses manageable.
- Transcription tools read `DEEPGRAM_API_KEY` from the MCP server process environment.
- `stt_*` session tools are Phase 1 scaffolding: they poll repeated short captures (default 4s chunks) and emit incremental events.

## Continuous Voice Workflow

High-level flow used by the agent voice runtime:

1. `stt_start_session` with `source="microphone"` (or `loopback`)
2. Poll `stt_get_updates(session_id, since_seq)` in a loop
3. For each `utterance_final` event, enqueue text as a normal agent user turn
4. `stt_stop_session` when voice mode ends
