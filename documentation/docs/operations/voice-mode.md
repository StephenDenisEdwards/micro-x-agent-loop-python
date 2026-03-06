# Voice Mode Guide

How to use continuous voice input with the agent.

## Overview

Voice mode enables hands-free interaction via speech-to-text (STT). When active, the agent listens through your microphone, transcribes your speech, and processes it as a regular user message. Responses are displayed as text (no text-to-speech).

Voice mode uses an STT MCP server session (ADR-011) that runs alongside the agent.

## Starting Voice Mode

```
you> /voice start
```

The agent will:
1. Connect to the STT MCP server
2. Begin listening on your default microphone
3. Show a `[voice]` indicator when active

To stop:
```
you> /voice stop
```

You can also type messages normally while voice mode is active.

## Prerequisites

- A working microphone
- The Interview Assist MCP server configured (provides STT capabilities)
- Audio input permissions granted to your terminal

## Configuration

Voice-related settings in `config.json`:

| Setting | Default | Description |
|---------|---------|-------------|
| `McpServers.interview-assist` | — | MCP server providing STT tools |

## Tuning Parameters

The STT engine has parameters that affect how speech is segmented into utterances:

| Parameter | What It Does |
|-----------|-------------|
| `endpointing_ms` | Silence duration (ms) before an utterance is considered complete. Lower = faster response, higher = allows longer pauses mid-sentence. |
| `utterance_end_ms` | Maximum wait time (ms) after the last word before forcing utterance completion. |

### Recommended Starting Points

- **Fast conversation:** `endpointing_ms=500`, `utterance_end_ms=1000`
- **Thoughtful dictation:** `endpointing_ms=1500`, `utterance_end_ms=3000`
- **Default:** `endpointing_ms=1000`, `utterance_end_ms=2000`

## How It Works

1. The STT MCP server opens a persistent session (not a one-shot tool call)
2. Audio is streamed from the microphone to the STT engine
3. When an utterance is detected (based on silence thresholds), the transcribed text is fed into `Agent.run()` as a regular user message
4. The agent processes it normally (mode analysis, LLM call, tool execution)
5. The response is printed to the terminal
6. Listening resumes automatically

## Tips

- Speak clearly and pause briefly between commands
- Use `/voice stop` if background noise causes false triggers
- Voice mode works well with simple commands; for complex multi-step prompts, typing is more reliable
- The agent processes voice input identically to typed input — all tools, mode analysis, and memory features work the same

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `/voice start` fails | Check that the Interview Assist MCP server is configured and running |
| No transcription appears | Check microphone permissions and default audio input device |
| Utterances cut off too early | Increase `endpointing_ms` |
| Long pauses between words cause split utterances | Increase `utterance_end_ms` |
| Background noise triggers false utterances | Move to a quieter environment or increase silence thresholds |

## Related

- [ADR-011: Continuous Voice via STT MCP Sessions](../architecture/decisions/ADR-011-continuous-voice-stt-mcp-sessions.md)
- [PLAN: Continuous Voice Agent](../planning/PLAN-continuous-voice-agent.md)
- [Interview Assist MCP](../design/tools/interview-assist-mcp/README.md)
