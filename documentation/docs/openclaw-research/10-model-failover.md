# Model Failover

OpenClaw handles model/auth failures in two stages: auth profile rotation within a provider, then model fallback to the next provider.

## Auth profiles

Credentials live in `~/.openclaw/agents/<agentId>/agent/auth-profiles.json`. Two types:
- `api_key` — `{ provider, key }`
- `oauth` — `{ provider, access, refresh, expires, email? }`

### Rotation order

When a provider has multiple profiles:
1. Explicit config: `auth.order[provider]`
2. Configured profiles: `auth.profiles` filtered by provider
3. Stored profiles from `auth-profiles.json`

Default round-robin: OAuth before API keys, oldest `lastUsed` first within each type. Cooldown/disabled profiles moved to the end.

### Session stickiness

Auth profile is **pinned per session** to keep provider caches warm. Not rotated on every request. Pin resets on:
- Session reset (`/new` / `/reset`)
- Compaction completes
- Profile enters cooldown/disabled

### Cooldowns

On auth/rate-limit errors, exponential backoff: 1m -> 5m -> 25m -> 1h (cap).

State tracked in `auth-profiles.json`:
```json
{ "usageStats": { "provider:profile": { "cooldownUntil": ..., "errorCount": 2 } } }
```

### Billing disables

Insufficient credits/balance triggers longer backoff: starts at 5h, doubles per failure, caps at 24h. Resets after 24h without failure.

## Model fallback

If all profiles for a provider fail, OpenClaw moves to the next model in `agents.defaults.model.fallbacks`. Applies to auth failures, rate limits, and timeouts that exhausted profile rotation.

## Model selection order

1. **Primary** model (`agents.defaults.model.primary`)
2. **Fallbacks** in `agents.defaults.model.fallbacks` (in order)
3. Provider auth failover happens inside a provider before advancing

## Built-in providers

OpenAI, Anthropic, OpenAI Code (Codex), OpenCode Zen, Google Gemini, Google Vertex, Z.AI (GLM), Vercel AI Gateway, OpenRouter, xAI, Groq, Cerebras, Mistral, GitHub Copilot, Hugging Face.

Custom providers via `models.providers` for OpenAI/Anthropic-compatible proxies (Moonshot, Ollama, vLLM, LM Studio, LiteLLM, etc.).

## Key references

- Model failover: [`docs/concepts/model-failover.md`](/root/openclaw/docs/concepts/model-failover.md)
- Models CLI: [`docs/concepts/models.md`](/root/openclaw/docs/concepts/models.md)
- Model providers: [`docs/concepts/model-providers.md`](/root/openclaw/docs/concepts/model-providers.md)
- OAuth: [`docs/concepts/oauth.md`](/root/openclaw/docs/concepts/oauth.md)
