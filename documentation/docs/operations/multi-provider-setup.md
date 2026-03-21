# Multi-Provider Setup Guide

How to switch between Anthropic, OpenAI, DeepSeek, Gemini, and Ollama as the LLM provider.

## Overview

The agent supports pluggable LLM providers via an abstraction layer (ADR-010). Anthropic (Claude), OpenAI (GPT), DeepSeek, Gemini, and Ollama (local) are supported. You can switch providers by changing two fields in `config.json`.

## Configuration

### Using Anthropic (Default)

```json
{
  "Provider": "anthropic",
  "Model": "claude-sonnet-4-5-20250929"
}
```

Required in `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### Using OpenAI

```json
{
  "Provider": "openai",
  "Model": "gpt-4o"
}
```

Required in `.env`:
```
OPENAI_API_KEY=sk-...
```

### Using DeepSeek

```json
{
  "Provider": "deepseek",
  "Model": "deepseek-chat"
}
```

Required in `.env`:
```
DEEPSEEK_API_KEY=sk-...
```

### Using Gemini

```json
{
  "Provider": "gemini",
  "Model": "gemini-2.0-flash"
}
```

Required in `.env`:
```
GEMINI_API_KEY=...
```

### Using Ollama (Local)

```json
{
  "Provider": "ollama",
  "Model": "phi3:mini",
  "ApiKey": "unused"
}
```

No API key required — Ollama runs locally via Docker. See [Local LLM with Ollama](local-llm-ollama.md) for full setup instructions.

Pre-built config profiles are available:

- **Local only** (fully offline): `config-standard-ollama-phi3.json`, `config-standard-ollama-llama3.json`, `config-standard-ollama-mistral.json`, `config-standard-ollama-gemma2.json`
- **Hybrid** (local main + cloud secondary features): `config-standard-ollama-phi3-hybrid.json`, `config-standard-ollama-llama3-hybrid.json`, `config-standard-ollama-mistral-hybrid.json`, `config-standard-ollama-gemma2-hybrid.json`

## Available Models

### Anthropic Models

| Model ID | Notes |
|----------|-------|
| `claude-opus-4-6` | Most capable, highest cost |
| `claude-sonnet-4-6` | Best balance of capability and cost |
| `claude-sonnet-4-5-20250929` | Previous generation Sonnet |
| `claude-haiku-4-5-20251001` | Fastest, lowest cost |

### OpenAI Models

| Model ID | Notes |
|----------|-------|
| `gpt-4o` | Most capable GPT-4 variant |
| `gpt-4o-mini` | Faster, lower cost |
| `gpt-4-turbo` | Previous generation |

### DeepSeek Models

| Model ID | Notes |
|----------|-------|
| `deepseek-chat` | General purpose chat |
| `deepseek-reasoner` | Reasoning model |

### Gemini Models

| Model ID | Notes |
|----------|-------|
| `gemini-2.0-flash` | Fast, low cost |
| `gemini-2.5-pro-preview-03-25` | Most capable Gemini |

### Ollama Models (Local)

| Model ID | Size | Notes |
|----------|------|-------|
| `phi3:mini` | ~2.3GB | General purpose, strong for size |
| `llama3.2:3b` | ~2GB | Meta's small model |
| `mistral:7b` | ~4GB | Good quality, tight fit on 4GB VRAM |
| `gemma2:2b` | ~1.6GB | Google's small model |

All Ollama models run locally at $0 cost. Only one model can be loaded at a time with 4GB VRAM.

## Provider Differences

| Feature | Anthropic | OpenAI | DeepSeek | Gemini | Ollama |
|---------|-----------|--------|----------|--------|--------|
| Streaming | SSE with content blocks | SSE with deltas | SSE with deltas | SSE with deltas | SSE with deltas |
| Prompt caching | Supported (ADR-012) | Not supported | Not supported | Not supported | Not supported |
| Tool calling | Native tool_use blocks | Function calling | Function calling | Function calling | Function calling |
| Max tokens | Model-dependent | Model-dependent | Model-dependent | Model-dependent | Model-dependent |
| Cost tracking | Full pricing table | Full pricing table | Full pricing table | Full pricing table | $0 (local) |
| API key required | Yes | Yes | Yes | Yes | No |

### Prompt Caching

Prompt caching (`PromptCachingEnabled=true`) only works with Anthropic. When using OpenAI, this setting is ignored. Prompt caching can significantly reduce costs for repeated system prompts and tool definitions — see [Prompt Caching Cost Analysis](prompt-caching-cost-analysis.md).

### Cost Metrics

The `/cost` command works with both providers and shows accurate per-call and session-total costs. Pricing tables are maintained in `providers/common.py`.

## Switching Providers

1. Update `Provider` and `Model` in `config.json`
2. Ensure the corresponding API key is in `.env`
3. Restart the agent

No other configuration changes are needed. All tools, memory, and session features work identically with both providers.

## Using Different Models for Different Tasks

Some features support a separate model for cost optimization:

| Config Key | Purpose | Default |
|------------|---------|---------|
| `CompactionModel` | Model for conversation compaction | Same as main model |
| `Stage2Model` | Model for mode classification | Same as main model |
| `ToolResultSummarizationModel` | Model for summarizing large tool results | Same as main model |

Example — use a cheaper model for compaction:
```json
{
  "Provider": "anthropic",
  "Model": "claude-sonnet-4-5-20250929",
  "CompactionModel": "claude-haiku-4-5-20251001"
}
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `API key not found` | Check that the correct env var is set (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, or `GEMINI_API_KEY`). Ollama does not require an API key |
| `Model not found` | Verify the model ID is exact (including date suffix for Anthropic models) |
| Cost report shows $0 | The model may not be in the pricing table — check `providers/common.py` |
| Prompt caching not working | Only supported with Anthropic provider |

## Related

- [ADR-010: Multi-Provider LLM Support](../architecture/decisions/ADR-010-multi-provider-llm-support.md)
- [Configuration Reference](config.md)
- [Prompt Caching Cost Analysis](prompt-caching-cost-analysis.md)
- [Local LLM with Ollama](local-llm-ollama.md)
