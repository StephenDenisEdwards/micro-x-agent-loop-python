# Multi-Provider Setup Guide

How to switch between Anthropic and OpenAI as the LLM provider.

## Overview

The agent supports pluggable LLM providers via an abstraction layer (ADR-010). Both Anthropic (Claude) and OpenAI (GPT) are supported. You can switch providers by changing two fields in `config.json`.

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

## Provider Differences

| Feature | Anthropic | OpenAI |
|---------|-----------|--------|
| Streaming | SSE with content blocks | SSE with deltas |
| Prompt caching | Supported (ADR-012) | Not supported |
| Tool calling | Native tool_use blocks | Function calling |
| Max tokens | Model-dependent | Model-dependent |
| Cost tracking | Full pricing table | Full pricing table |

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
| `API key not found` | Check that the correct env var is set (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) |
| `Model not found` | Verify the model ID is exact (including date suffix for Anthropic models) |
| Cost report shows $0 | The model may not be in the pricing table — check `providers/common.py` |
| Prompt caching not working | Only supported with Anthropic provider |

## Related

- [ADR-010: Multi-Provider LLM Support](../architecture/decisions/ADR-010-multi-provider-llm-support.md)
- [Configuration Reference](config.md)
- [Prompt Caching Cost Analysis](prompt-caching-cost-analysis.md)
