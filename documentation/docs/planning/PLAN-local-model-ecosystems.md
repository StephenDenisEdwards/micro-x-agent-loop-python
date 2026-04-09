# Plan: Local Model Ecosystem Support

**Status:** Planned
**Date:** 2026-04-09

**Goal:** Enable the agent to connect to any OpenAI-compatible local model server (vLLM, LM Studio, LocalAI, llama.cpp, Jan, TGI, etc.) via a single generic provider, rather than requiring a dedicated subclass per ecosystem.

---

## 1. Why

Ollama is currently the only supported local model runtime. The broader ecosystem includes many OpenAI-compatible inference servers, each differing only in default port:

| Server | Default endpoint | API key required | Notes |
|--------|-----------------|------------------|-------|
| **Ollama** | `localhost:11434/v1` | No | Already supported |
| **vLLM** | `localhost:8000/v1` | No | High-throughput, PagedAttention |
| **LM Studio** | `localhost:1234/v1` | No | Desktop GUI, GGUF models |
| **LocalAI** | `localhost:8080/v1` | No | Multi-backend (llama.cpp, transformers) |
| **llama.cpp server** | `localhost:8080/v1` | No | Minimal C++ runtime |
| **Jan** | `localhost:1337/v1` | No | Desktop app, local-first |
| **TGI** | `localhost:8080/v1` | No | HF production serving |
| **MLX** (mlx_lm.server) | `localhost:8080/v1` | No | Apple Silicon optimised |
| **ExLlamaV2** (tabbyAPI) | `localhost:5000/v1` | No | Fast GPTQ/EXL2 inference |

All expose the OpenAI chat completions API. Creating a dedicated provider subclass for each would be boilerplate — they all inherit `OpenAIProvider` with nothing but a different port.

### Design Decision: Generic Provider vs N Subclasses

**Option A — Named subclasses** (one per server): Easy to discover, but 15+ lines of boilerplate per server with no behavioural difference.

**Option B — Generic `openai-compatible` provider** with configurable base URL: One implementation covers all current and future servers. Users specify `"Provider": "openai-compatible"` + `"ProviderBaseUrl": "http://localhost:8000/v1"` in config.

**Decision: Option B**, with named shortcuts as sugar (Phase 2). Rationale:
- The only difference between these servers is the default port
- A generic provider handles any future OpenAI-compatible server with zero code changes
- Named shortcuts (Phase 2) provide convenience without requiring separate classes

---

## 2. Current Architecture

The existing provider layer already supports this pattern:

| Component | Current state |
|-----------|--------------|
| `OpenAIProvider` | Accepts `base_url` and `provider_name` in `__init__` |
| `OllamaProvider` | Thin subclass: sets `base_url` to `localhost:11434/v1`, dummy API key, `tool_choice=auto` |
| `DeepSeekProvider` | Thin subclass: sets `base_url` to `api.deepseek.com` |
| `ProviderFactory` | Resolves API key + passes `ollama_base_url` — but only for Ollama |
| `agent_config.py` | Has `ollama_base_url: str` — no generic base URL field |
| `config-base.json` | Has `OllamaBaseUrl` — no generic equivalent |

The `OpenAIProvider` is already parameterised — the generic provider is essentially just wiring config to it.

---

## 3. Implementation

### Phase 1 — Generic `openai-compatible` provider (core)

**Goal:** Users can connect to any OpenAI-compatible server via config alone.

**Config (`config-base.json`):**
```json
{
  "ProviderBaseUrl": "",
  "ProviderApiKeyOptional": false
}
```

- `ProviderBaseUrl` — base URL for the generic provider (must include `/v1` if the server requires it)
- `ProviderApiKeyOptional` — when `true`, uses a dummy API key if none is set (local servers don't need one)

**Usage example (`config-local-vllm.json`):**
```json
{
  "Base": "config-base.json",
  "Provider": "openai-compatible",
  "Model": "meta-llama/Llama-3.1-8B-Instruct",
  "ProviderBaseUrl": "http://localhost:8000/v1",
  "ProviderApiKeyOptional": true,
  "SubAgentProvider": "openai-compatible",
  "SubAgentModel": "meta-llama/Llama-3.1-8B-Instruct"
}
```

**Files modified:**

| File | Change |
|------|--------|
| `agent_config.py` | Add `provider_base_url: str = ""` and `provider_api_key_optional: bool = False` fields |
| `provider.py` | Add `"openai-compatible"` branch to `create_provider()` factory; accept `provider_base_url` param in factory |
| `provider.py` (`ProviderFactory`) | Thread `provider_base_url` through `ProviderFactory.__init__` and `create()` |
| `config-base.json` | Add `ProviderBaseUrl` and `ProviderApiKeyOptional` keys |
| `bootstrap.py` | Pass `provider_base_url` from config to `ProviderFactory` |

**New provider class — none.** The generic provider is just `OpenAIProvider` instantiated with the user's base URL:

```python
# In create_provider():
if name == "openai-compatible":
    effective_key = api_key or ("openai-compatible" if api_key_optional else api_key)
    return OpenAIProvider(effective_key, base_url=provider_base_url, provider_name="openai-compatible")
```

**`tool_choice` behaviour:** Unlike Ollama's override (`tool_choice=auto`), the generic provider uses OpenAI defaults. If a specific server needs `tool_choice=auto`, users can set `"ToolChoiceOverride": "auto"` (see Phase 3).

### Phase 2 — Named shortcuts (convenience)

**Goal:** Common servers get short aliases so users don't need to remember ports.

Add a `_LOCAL_SHORTCUTS` dict to `provider.py`:

```python
_LOCAL_SHORTCUTS: dict[str, str] = {
    "vllm":       "http://localhost:8000/v1",
    "lmstudio":   "http://localhost:1234/v1",
    "localai":    "http://localhost:8080/v1",
    "llamacpp":   "http://localhost:8080/v1",
    "jan":        "http://localhost:1337/v1",
    "tgi":        "http://localhost:8080/v1",
    "mlx":        "http://localhost:8080/v1",
    "tabbyapi":   "http://localhost:5000/v1",
}
```

In `create_provider()`, before the existing `if/elif` chain:

```python
if name in _LOCAL_SHORTCUTS:
    effective_url = provider_base_url or _LOCAL_SHORTCUTS[name]
    return OpenAIProvider(
        api_key or name,
        base_url=effective_url,
        provider_name=name,
    )
```

`ProviderBaseUrl` overrides the default port if specified (user has a non-standard setup).

**Config example (`config-local-lmstudio.json`):**
```json
{
  "Base": "config-base.json",
  "Provider": "lmstudio",
  "Model": "lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF",
  "ProviderApiKeyOptional": true
}
```

**Pricing:** All local models are free. Add a wildcard convention or per-model zero entries:

```json
"lmstudio/*":  { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"vllm/*":      { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 },
"localai/*":   { "input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0 }
```

### Phase 3 — Provider-specific overrides (optional)

**Goal:** Handle behavioural differences between servers without subclassing.

Some local servers benefit from tweaks:

| Override | Purpose | Servers that need it |
|----------|---------|---------------------|
| `tool_choice=auto` | Nudge small models to use tools | Ollama, vLLM with small models |
| `stream_options` removal | Some servers reject `include_usage` | Older llama.cpp builds |
| Custom stop tokens | Server-specific stop sequences | Some fine-tuned models |

**Approach:** Add optional `ProviderOverrides` config dict:

```json
{
  "ProviderOverrides": {
    "tool_choice": "auto",
    "stream_options": false
  }
}
```

These are applied in `_build_stream_kwargs()`. This replaces the need for Ollama-style subclass overrides for simple cases.

**This phase is optional** — only implement if users report compatibility issues with specific servers.

---

## 4. Ollama Relationship

Ollama keeps its dedicated provider because it has specific behaviour:
- Appends `/v1` to the base URL (users configure `OllamaBaseUrl` without the `/v1` suffix)
- Forces `tool_choice=auto` for all requests with tools
- These are Ollama-specific conventions, not shared by other servers

The named shortcut `"ollama"` continues to route to `OllamaProvider`, not the generic path.

---

## 5. RoutingPolicies Integration

Local providers work with the existing `RoutingPolicies` system:

```json
{
  "RoutingPolicies": {
    "trivial":         { "provider": "lmstudio", "model": "gemma-2b" },
    "code_generation": { "provider": "openai-compatible", "model": "codellama-34b" },
    "analysis":        { "provider": "anthropic", "model": "claude-sonnet-4-20250514" }
  }
}
```

This enables hybrid routing: cheap local models for simple tasks, cloud models for complex ones.

---

## 6. Files Summary

### Created

| File | Phase | Purpose |
|------|-------|---------|
| `config-local-vllm.json` | 1 | Example config profile for vLLM |
| `config-local-lmstudio.json` | 2 | Example config profile for LM Studio |
| `tests/providers/test_openai_compatible_provider.py` | 1 | Tests for generic provider creation |

### Modified

| File | Phase | Change |
|------|-------|--------|
| `agent_config.py` | 1 | Add `provider_base_url`, `provider_api_key_optional` fields |
| `provider.py` | 1 | Add `openai-compatible` to factory, thread `provider_base_url` |
| `config-base.json` | 1 | Add `ProviderBaseUrl`, `ProviderApiKeyOptional` keys |
| `bootstrap.py` | 1 | Pass new config fields to `ProviderFactory` |
| `provider.py` | 2 | Add `_LOCAL_SHORTCUTS` dict and resolution logic |
| `config-base.json` | 2 | Add zero-cost pricing entries for local providers |

---

## 7. Testing

| Test | Phase | What it covers |
|------|-------|----------------|
| `create_provider("openai-compatible")` with `provider_base_url` | 1 | Factory returns `OpenAIProvider` with correct `base_url` |
| Dummy API key when `api_key_optional=True` | 1 | No crash when key is empty |
| Error when `provider_base_url` is empty for `openai-compatible` | 1 | Validates config |
| Named shortcuts resolve to correct URLs | 2 | `_LOCAL_SHORTCUTS` mapping |
| `ProviderBaseUrl` overrides default shortcut port | 2 | Custom port support |
| Existing Ollama/DeepSeek/Gemini providers unaffected | 1 | Regression |

---

## 8. Implementation Sequence

```
Phase 1   Generic openai-compatible provider        (core — smallest useful change)
Phase 2   Named shortcuts for common servers         (convenience — depends on Phase 1)
Phase 3   ProviderOverrides config                   (optional — only if needed)
```

Phase 1 is the minimum viable change. Phases 2 and 3 are additive.
