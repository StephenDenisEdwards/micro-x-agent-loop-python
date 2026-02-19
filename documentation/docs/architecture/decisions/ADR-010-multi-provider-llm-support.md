# ADR-010: Multi-Provider LLM Support (Provider Abstraction)

## Status

Accepted

## Context

The agent loop was hardwired to the Anthropic Claude API. Every LLM interaction — streaming chat, compaction summarization, tool schema formatting — was coupled to the `anthropic` SDK directly in `llm_client.py` and `compaction.py`.

This made it impossible to use alternative models (GPT-4o, o1, o3, etc.) without rewriting core agent logic.

Options considered:

1. **Keep Anthropic-only** — simplest, but locks out all non-Anthropic models
2. **LiteLLM / unified gateway** — third-party proxy that normalizes APIs; adds a large dependency and a layer of indirection that is hard to debug
3. **Provider abstraction with canonical internal format** — define a `LLMProvider` Protocol, keep Anthropic message format as the internal canonical representation, and translate at the API boundary in each provider

## Decision

Adopt a provider abstraction (option 3) with Anthropic message format as the internal canonical format.

Reasons:

- **Zero changes to core logic.** The agent loop, compaction, memory, sessions, tool execution, and all code that inspects message content remain untouched. Only the API boundary translates.
- **Config-driven selection.** A single `"Provider"` field in `config.json` selects the backend. API keys are routed automatically (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`).
- **Minimal new surface area.** The `LLMProvider` Protocol has three methods: `stream_chat`, `create_message`, and `convert_tools`. Each provider is a self-contained module.
- **Retry stays per-provider.** Each provider wraps its own SDK-specific transient errors (rate limit, connection, timeout) with tenacity, so retry logic matches the actual exceptions raised.

The implementation includes:

- `provider.py` — `LLMProvider` Protocol and `create_provider()` factory
- `providers/anthropic_provider.py` — extracted from `llm_client.py`, implements streaming, non-streaming, and tool conversion using the `anthropic` SDK
- `providers/openai_provider.py` — translates between internal Anthropic-format messages and OpenAI chat completion format in both directions (outbound message/tool conversion, inbound streaming accumulation and stop reason mapping)
- `llm_client.py` — slimmed to shared utilities (`Spinner`, `_on_retry`)
- `compaction.py` — calls `provider.create_message()` instead of the raw `anthropic` client

### Internal Format Choice

Anthropic message format was chosen as canonical because:

- The codebase already used it everywhere — changing would touch every file
- Tool use/tool result blocks are explicit structured objects (not overloaded on the `tool_calls` field like OpenAI)
- System prompt is a separate parameter, not a message — cleaner separation

The OpenAI provider handles all translation:

| Direction | Anthropic (internal) | OpenAI (API) |
|-----------|---------------------|--------------|
| System prompt | `system=` parameter | `{"role": "system"}` message |
| Tool use | `{"type": "tool_use", "id", "name", "input"}` block | `tool_calls[].function` on assistant message |
| Tool result | `{"type": "tool_result", "tool_use_id", "content"}` block | `{"role": "tool", "tool_call_id", "content"}` message |
| Stop reason | `end_turn`, `tool_use`, `max_tokens` | `stop` -> `end_turn`, `tool_calls` -> `tool_use`, `length` -> `max_tokens` |

## Consequences

**Easier:**

- Adding new LLM providers (Google Gemini, local models via OpenAI-compatible APIs, etc.) — implement the three-method Protocol
- A/B testing models from different providers on the same conversation
- Using cheaper/faster models for compaction while using a more capable model for the main loop
- Running against any OpenAI-compatible API (Azure OpenAI, local vLLM, etc.) by setting the API key and model

**Harder:**

- Provider-specific features (Anthropic extended thinking, OpenAI structured outputs, etc.) require per-provider extensions to the Protocol
- Debugging message format issues requires understanding both the internal format and the provider's wire format
- Token estimation in compaction remains a rough chars/4 heuristic that doesn't account for provider-specific tokenization differences
