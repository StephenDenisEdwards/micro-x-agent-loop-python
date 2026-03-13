# Plan: Multi-Provider Support (Gemini + DeepSeek)

**Status:** Completed
**Date:** 2026-03-13

**Goal:** Add Google Gemini and DeepSeek as first-class LLM providers alongside the existing Anthropic and OpenAI providers, enabling users to switch models via config without code changes.

---

## 1. Why

- **Cost:** DeepSeek models are significantly cheaper than Anthropic/OpenAI at comparable capability tiers.
- **Capability diversity:** Gemini 2.0/2.5 Flash offers fast, cheap inference; Gemini Pro offers strong reasoning.
- **Resilience:** Provider diversification reduces dependency on a single vendor.
- **Sub-agent cost reduction:** Gemini Flash / DeepSeek Chat are excellent candidates for cheap sub-agent models.

---

## 2. Current Provider Architecture

The provider layer is minimal and well-factored:

| File | Role |
|------|------|
| `provider.py` | Factory: `create_provider(name) → StreamProvider` |
| `providers/anthropic_provider.py` | Anthropic streaming + prompt caching + tool calls |
| `providers/openai_provider.py` | OpenAI streaming + tool calls (OpenAI SDK) |
| `app_config.py` | `resolve_runtime_env(provider_name)` — maps provider name → API key env var |

`LLMProvider` protocol (from `provider.py`):
```python
class LLMProvider(Protocol):
    async def stream_chat(
        self, model, max_tokens, temperature, system_prompt,
        messages: list[dict], tools: list[dict], *, line_prefix=""
    ) -> tuple[dict, list[dict], str, UsageResult]: ...

    async def create_message(
        self, model, max_tokens, temperature, messages: list[dict]
    ) -> tuple[str, UsageResult]: ...

    def convert_tools(self, tools: list[Tool]) -> list[dict]: ...
```

`stream_chat` returns `(message_dict, tool_use_blocks, stop_reason, usage)` in Anthropic-style internal format.
`tools` passed to `stream_chat` are already pre-converted (via `convert_tools`) before `TurnEngine` is constructed.

**Note:** The `LLMProvider` protocol declares `*, line_prefix: str = ""` but this is stale — `TurnEngine` actually calls `stream_chat(..., channel=self._channel)`. All provider implementations (including new ones) must accept `*, channel: AgentChannel | None = None` as the keyword argument. Follow existing provider implementations, not the protocol signature.

---

## 3. DeepSeek Provider

### API Compatibility

DeepSeek exposes an **OpenAI-compatible REST API** at `https://api.deepseek.com`. The `openai` Python SDK works against it by setting `base_url`. This means `DeepSeekProvider` can be a thin subclass of `OpenAIProvider`.

### Implementation

**`providers/deepseek_provider.py`** — new file:
```python
from micro_x_agent_loop.providers.openai_provider import OpenAIProvider

class DeepSeekProvider(OpenAIProvider):
    def __init__(self, api_key: str) -> None:
        super().__init__(api_key=api_key, base_url="https://api.deepseek.com", provider_name="deepseek")
```

**`providers/openai_provider.py`** — minor change:
- Add optional `base_url: str | None = None` and `provider_name: str = "openai"` params to `__init__`
- Pass `base_url` to `openai.AsyncOpenAI(base_url=base_url, ...)`
- Use `provider_name` in `UsageResult` instead of hardcoded `"openai"`

### Models

| Model ID | Notes |
|----------|-------|
| `deepseek-chat` | V3; strong general model, cheap |
| `deepseek-reasoner` | R1; reasoning model (returns `reasoning_content` — hidden from conversation) |

### Caching

DeepSeek has automatic prefix caching but uses different usage field names than OpenAI:
- OpenAI: `usage.prompt_tokens_details.cached_tokens`
- DeepSeek: `usage.prompt_cache_hit_tokens` (top-level field, not nested)

The inherited OpenAI usage extraction will silently report 0 cache hits for DeepSeek. `DeepSeekProvider` must override the usage extraction to also check `getattr(usage, "prompt_cache_hit_tokens", 0)` as a fallback when `prompt_tokens_details` is absent or zero.

### Reasoning Content (deepseek-reasoner)

`deepseek-reasoner` returns `reasoning_content` in streaming deltas. The `openai` SDK does not declare this as a typed field, but it surfaces transparently via Pydantic's `extra="allow"` — `delta.reasoning_content` works at runtime (stored in `__pydantic_extra__`). Use `getattr(delta, "reasoning_content", None)` for safety.

Reasoning tokens are tracked in `usage.completion_tokens_details.reasoning_tokens`. Total `completion_tokens` = reasoning + answer tokens combined.

The `DeepSeekProvider` should silently drop reasoning content (it is CoT internal monologue, not conversation). Cost metrics should track reasoning tokens separately using `completion_tokens_details.reasoning_tokens`.

---

## 4. Gemini Provider

### API

Google's `google-genai` SDK (`pip install google-genai`). Uses `genai.Client` with `GEMINI_API_KEY`. Does **not** use the OpenAI SDK — requires a separate implementation.

### Message Format Conversion

Gemini uses a different message format:
- Roles: `user` and `model` (not `assistant`)
- Content: `list[Part]` — `Part.text` for text, `Part.function_call` for tool calls, `Part.function_response` for tool results
- Tool calls have no stable ID in Gemini responses — must generate synthetic UUIDs

**Conversion logic needed:**
1. Internal `user` messages → Gemini `user` Content with text Part
2. Internal `assistant` messages with text → Gemini `model` Content with text Part
3. Internal `tool_use` blocks → Gemini `model` Content with `FunctionCall` Parts
4. Internal `tool_result` blocks → Gemini `user` Content with `FunctionResponse` Parts

**Synthetic ID strategy:** When a `FunctionCall` arrives in a Gemini response, assign `uuid4()` as its ID. Store this in a transient map. When building the next turn's `FunctionResponse`, look up by function name to reconstruct the ID for the internal format. (Gemini matches function responses by name, not ID.)

### Tool Schema Conversion

`CanonicalTool` → `genai.types.FunctionDeclaration`:
- `name`, `description` map directly
- `input_schema` (JSON Schema dict) → `parameters` field (Gemini SDK accepts dict directly in recent versions)

### Streaming

`client.aio.models.generate_content_stream(...)` yields `GenerateContentResponse` chunks:
- `chunk.text` → `TextDelta`
- `chunk.candidates[0].content.parts` → scan for `FunctionCall` parts → `ToolUseStart` / `ToolUseEnd`
- `chunk.usage_metadata` → `UsageResult` (on final chunk)

### Models

| Model ID | Notes |
|----------|-------|
| `gemini-2.0-flash` | Fast, cheap, good for sub-agents |
| `gemini-2.0-flash-thinking-exp` | Experimental reasoning |
| `gemini-2.5-pro-preview-03-25` | Strongest Gemini model |

### SDK Details (google-genai v1.67.0+)

**System prompt:** Pass as `GenerateContentConfig(system_instruction="...")` — accepts a plain string. This is `config=` on the generate call, not a constructor arg on the model.

**Tool schema:** `FunctionDeclaration(name=..., description=..., parameters=<dict>)` — Pydantic coerces the raw JSON Schema dict to a `Schema` object automatically. Alternatively use `parameters_json_schema=<dict>` (stored as-is, no coercion). Both work with standard JSON Schema format (`type`, `properties`, `required`).

**Tools config:** `GenerateContentConfig(tools=[types.Tool(function_declarations=[...])], automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))` — disable automatic function calling so we control the loop.

**Async streaming call:**
```python
async for chunk in await client.aio.models.generate_content_stream(
    model=model_id, contents=messages, config=config
):
    ...
```
Note: the coroutine must be `await`-ed, then the result is iterated.

**Function calls in chunks:** `chunk.function_calls` — list of `FunctionCall` objects with `.name` and `.args` (dict). May appear in intermediate chunks.

### Known Limitations

- Parallel tool calls: Gemini can return multiple `FunctionCall` parts in one response. Each gets its own synthetic ID.

---

## 5. Config Changes

### `config-base.json` — Pricing additions

Keys use the same schema as existing entries: `input`, `output`, `cache_read`, `cache_create` (per MTok USD). `cache_create` is `0.0` for all non-Anthropic providers — automatic caching has no write charge.

```json
"gemini/gemini-2.0-flash":             { "input": 0.10, "output": 0.40,  "cache_read": 0.025, "cache_create": 0.0 },
"gemini/gemini-2.5-pro-preview-03-25": { "input": 1.25, "output": 10.00, "cache_read": 0.31,  "cache_create": 0.0 },
"deepseek/deepseek-chat":              { "input": 0.27, "output": 1.10,  "cache_read": 0.07,  "cache_create": 0.0 },
"deepseek/deepseek-reasoner":          { "input": 0.55, "output": 2.19,  "cache_read": 0.14,  "cache_create": 0.0 }
```

### Caching policy per provider

`PromptCachingEnabled` is **Anthropic-only**. It controls explicit `cache_control: ephemeral` headers on system prompt and last tool schema. For all other providers, caching is automatic and server-side — this flag has no effect and is intentionally ignored by the factory when constructing non-Anthropic providers.

| Provider | Caching type | `cache_read_input_tokens` source | `cache_creation_input_tokens` |
|----------|-------------|----------------------------------|-------------------------------|
| Anthropic | Explicit opt-in (`cache_control` headers) | `usage.cache_read_input_tokens` | `usage.cache_creation_input_tokens` |
| OpenAI | Automatic prefix cache | `usage.prompt_tokens_details.cached_tokens` | 0 |
| DeepSeek | Automatic prefix cache | `usage.prompt_cache_hit_tokens` (top-level) | 0 |
| Gemini | Automatic implicit cache | `usage_metadata.cached_content_token_count` | 0 |

### New profile configs

**`config-standard-deepseek.json`:**
```json
{
  "Base": "config-base.json",
  "Provider": "deepseek",
  "Model": "deepseek-chat",
  "SubAgentProvider": "deepseek",
  "SubAgentModel": "deepseek-chat"
}
```

**`config-standard-gemini.json`:**
```json
{
  "Base": "config-base.json",
  "Provider": "gemini",
  "Model": "gemini-2.0-flash",
  "SubAgentProvider": "gemini",
  "SubAgentModel": "gemini-2.0-flash"
}
```

---

## 6. Code Changes Summary

| File | Change |
|------|--------|
| `providers/openai_provider.py` | Add `base_url`, `provider_name` params to `__init__` |
| `providers/deepseek_provider.py` | **New** — `DeepSeekProvider(OpenAIProvider)` |
| `providers/gemini_provider.py` | **New** — full Gemini implementation |
| `provider.py` | Add `deepseek` and `gemini` branches to factory |
| `app_config.py` | Add `deepseek` → `DEEPSEEK_API_KEY` and `gemini` → `GEMINI_API_KEY` to `resolve_runtime_env` — currently unknown providers silently fall through to `ANTHROPIC_API_KEY` |
| `config-base.json` | Add Gemini + DeepSeek pricing entries |
| `config-standard-deepseek.json` | **New** profile |
| `config-standard-gemini.json` | **New** profile |
| `pyproject.toml` | Add `google-genai>=1.0.0` dependency |

---

## 7. Tests

| File | Coverage |
|------|----------|
| `tests/providers/test_deepseek_provider.py` | `__init__` with correct `base_url`, `stream_chat` delegates to OpenAI provider |
| `tests/providers/test_gemini_provider.py` | Message conversion helpers, tool schema conversion, `stream_chat` with mocked SDK |
| `tests/test_app_config.py` | `resolve_runtime_env("gemini")` and `resolve_runtime_env("deepseek")` |
| `tests/test_provider.py` (extend) | `create_provider("deepseek")` and `create_provider("gemini")` return correct types |

---

## 8. Implementation Sequence

```
Phase 1a  Extend OpenAIProvider with base_url + provider_name params
Phase 1b  Implement DeepSeekProvider (thin subclass, depends on 1a)
Phase 2   Implement GeminiProvider (independent of 1)
Phase 3   Update create_provider factory (depends on 1b + 2)
Phase 4   Update resolve_runtime_env in app_config.py
Phase 5   Add google-genai to pyproject.toml
Phase 6   Add pricing entries to config-base.json
Phase 7   Create config profile files
Phase 8   Write tests
```

Phases 1 and 2 are independent and can be done in parallel. Phase 3 depends on both.

---

## 9. Resolved Pre-Implementation Questions

All open questions resolved via SDK source inspection and official docs:

| Question | Resolution |
|----------|-----------|
| Gemini `FunctionDeclaration(parameters=dict)` | ✅ Works — Pydantic coerces raw dict to `Schema`. Also `parameters_json_schema=dict` for no-coercion path. |
| Gemini `system_instruction` API surface | ✅ `GenerateContentConfig(system_instruction="...")` — plain string, passed as `config=` arg |
| DeepSeek `reasoning_content` in streaming | ✅ Accessible via `getattr(delta, "reasoning_content", None)` — stored in Pydantic `__pydantic_extra__` |
| DeepSeek reasoning token tracking | ✅ `usage.completion_tokens_details.reasoning_tokens` — separate field, can be tracked in cost metrics |
