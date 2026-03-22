# ADR-021: Same-Family Provider Fallback

## Status

Accepted — 2026-03-22

Extends [ADR-020](ADR-020-semantic-model-routing.md) (semantic model routing) and [ADR-010](ADR-010-multi-provider-llm-support.md) (multi-provider LLM support).

## Context

ADR-020 introduced the `ProviderPool` with health tracking and automatic fallback — when a provider fails, the pool retries the request on the configured fallback provider or the first available provider.

This fallback was format-agnostic: if Ollama (OpenAI-compatible wire format) failed, the pool would send the same messages, tools, and model name to the Anthropic provider. This caused 400 errors because:

1. **Message format incompatibility.** OpenAI format allows `content: null` on assistant messages with tool calls; Anthropic rejects null content (`"invalid message content type: <nil>"`).
2. **Tool schema incompatibility.** OpenAI and Anthropic use different tool definition structures.
3. **Model name mismatch.** The fallback passed the original model name (e.g., `qwen2.5:7b`) to a provider that doesn't serve that model.

Options considered:

1. **Re-convert messages, tools, and model on fallback.** This would require the pool to understand message transformation, tool conversion, and model mapping — responsibilities that belong to the turn engine. The pool would effectively re-run half the turn engine's dispatch logic, violating its single responsibility (dispatch + health tracking).

2. **Add a provider-to-default-model mapping and format adapters.** Lower coupling than option 1 but still adds format awareness to the pool. Format conversion is inherently provider-specific — the OpenAI provider already has `_to_openai_messages()` and `_to_openai_tools()` internally. Duplicating that knowledge in the pool creates two sources of truth.

3. **Tag providers with a format family and restrict fallback to same-family providers.** The pool stays simple (dispatch + health tracking). Cross-family resilience is the turn engine's responsibility — it already has the context to re-route, re-convert tools, and select an appropriate model.

## Decision

Adopt option 3: each provider declares a `family` property (`"anthropic"`, `"openai"`, or `"gemini"`) on the `LLMProvider` protocol. The `ProviderPool` tracks each provider's family at registration time and restricts all fallback paths (both `resolve_target` and the `stream_chat` exception handler) to same-family providers only.

Reasons:

- **Minimal change, maximum safety.** Adding a string property to each provider and a dict lookup in the pool eliminates the entire class of cross-family fallback bugs with ~30 lines of code.

- **Preserves pool's single responsibility.** The pool dispatches and tracks health. It does not transform messages or map models. Format-aware retry belongs in the turn engine where the format knowledge already lives.

- **Same-family fallback is useful.** If a user runs two OpenAI-compatible providers (e.g., OpenAI + DeepSeek, or two Ollama instances), same-family fallback works correctly because they share the same wire format.

- **Fail-fast for cross-family failures.** When no same-family provider is available, the pool raises immediately with a clear error message instead of sending incompatible data and getting a cryptic 400.

### Provider Families

| Family | Providers | Wire Format |
|--------|-----------|-------------|
| `"anthropic"` | AnthropicProvider | Anthropic Messages API |
| `"openai"` | OpenAIProvider, OllamaProvider, DeepSeekProvider | OpenAI Chat Completions API |
| `"gemini"` | GeminiProvider | Google Generative AI API |

OllamaProvider and DeepSeekProvider inherit `family` from OpenAIProvider — no override needed.

### Changes

1. **`LLMProvider` protocol** — new `family: str` property.
2. **Each provider class** — implements `family` returning `"anthropic"`, `"openai"`, or `"gemini"`.
3. **`ProviderPool.__init__`** — builds `_families: dict[str, str]` from registered providers via `getattr(provider, "family", name)` (safe for mocks that lack the property).
4. **`ProviderPool.resolve_target`** — fallback and "any available" loops filter by `target_family`.
5. **`ProviderPool.stream_chat`** — exception handler only attempts fallback when `_same_family(provider_name, fallback_provider)` is true.

## Consequences

**Easier:**

- Running mixed-provider configurations (Anthropic + Ollama) without risk of cross-format fallback errors
- Adding new providers — just declare the correct `family` and fallback works automatically within the family
- Diagnosing fallback failures — the error message now includes the family name and explains why no fallback was available

**Harder:**

- Cross-family resilience (e.g., "if Ollama is down, fall back to Anthropic with a different model") must be implemented in the turn engine, not the pool. This is a future enhancement, not a regression — the previous behaviour was broken (400 errors), not functional.

**Related:**

- [ADR-010](ADR-010-multi-provider-llm-support.md) — provider abstraction that this extends
- [ADR-020](ADR-020-semantic-model-routing.md) — introduced the provider pool that this fixes
