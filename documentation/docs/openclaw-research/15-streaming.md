# Streaming and Chunking

OpenClaw has two streaming layers — neither is true token-delta streaming to channels.

## Block streaming (channel messages)

Sends completed text blocks as normal channel messages while the model generates.

```
Model output -> text_delta events -> chunker -> channel send (block replies)
```

### Controls

- `blockStreamingDefault`: `"on"` / `"off"` (default off)
- `blockStreamingBreak`: `"text_end"` (emit as you go) or `"message_end"` (flush at end)
- `blockStreamingChunk`: `{ minChars, maxChars, breakPreference }`
- `blockStreamingCoalesce`: `{ minChars, maxChars, idleMs }` — merge blocks before sending
- Channel overrides: `*.blockStreaming`, `*.textChunkLimit`, `*.chunkMode`

### Chunking algorithm

- **Low bound**: don't emit until buffer >= `minChars`
- **High bound**: prefer splits before `maxChars`
- **Break preference**: paragraph -> newline -> sentence -> whitespace -> hard break
- **Code fences**: never split inside; if forced, close + reopen to keep Markdown valid
- `maxChars` clamped to channel `textChunkLimit`

### Channel text limits

| Channel | Limit |
|---------|-------|
| Telegram | 4000 |
| WhatsApp | 4000 |
| Slack | 4000 |
| Signal | 4000 |
| Discord | 2000 |
| IRC | 350 |

### Coalescing

Reduces "single-line spam" by merging consecutive chunks:
- Waits for idle gaps (`idleMs`) before flushing
- `maxChars` cap forces flush
- `minChars` prevents tiny fragments
- Default `minChars` bumped to 1500 for Signal/Slack/Discord

### Human-like pacing

Optional randomized pause between block replies (after the first):
- `humanDelay` modes: `off` (default), `natural` (800-2500ms), `custom` (minMs/maxMs)

## Telegram preview streaming

The only channel with live partial-stream updates:
- Uses `sendMessage` + `editMessageText` to update a preview message in real time
- `streamMode`: `"partial"` (latest text), `"block"` (chunked blocks), `"off"`
- Preview streaming is separate from block streaming
- Text-only finals applied by editing the preview message in place

## Key references

- Streaming: [`docs/concepts/streaming.md`](/root/openclaw/docs/concepts/streaming.md)
- Messages: [`docs/concepts/messages.md`](/root/openclaw/docs/concepts/messages.md)
