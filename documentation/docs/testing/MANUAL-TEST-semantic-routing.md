# Manual Test Plan — Semantic Model Routing

**Related plan:** [PLAN-semantic-model-routing.md](../planning/PLAN-semantic-model-routing.md)
**Code under test:** `src/micro_x_agent_loop/semantic_classifier.py`, `src/micro_x_agent_loop/provider_pool.py`, `src/micro_x_agent_loop/routing_feedback.py`, `src/micro_x_agent_loop/turn_engine.py` (dispatch), `src/micro_x_agent_loop/agent.py` (wiring)

---

## Prerequisites

- Anthropic API key configured in `.env`
- `config-base.json` accessible
- Log level `DEBUG` to observe routing decisions
- For cross-provider tests: Ollama running locally with a model pulled (e.g., `ollama pull llama3.2:3b`)

---

## Test 1 — Semantic routing disabled (default)

**Goal:** Verify that with `SemanticRoutingEnabled=false` (default), the system behaves identically to before — no semantic classification, no provider pool.

**Steps:**

1. Ensure `SemanticRoutingEnabled` is `false` or absent from config
2. Start the agent: `python -m micro_x_agent_loop`
3. Submit several prompts of different types (greeting, question, code request)
4. Check `/cost` for model breakdown

**Expected:**
- All API calls use the main model (Sonnet)
- No "Semantic routing" messages in logs
- `/cost` shows only one model in the breakdown
- `/routing` command says "Routing stats require SemanticRoutingEnabled=true"

---

## Test 2 — Trivial messages route to cheap model

**Goal:** Verify that greetings and acknowledgements route to the cheap model.

**Steps:**

1. Configure:
   ```json
   {
     "SemanticRoutingEnabled": true,
     "SemanticRoutingStrategy": "rules+keywords",
     "RoutingPolicies": {
       "trivial": { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
       "conversational": { "provider": "anthropic", "model": "claude-haiku-4-5-20251001" },
       "code_generation": { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" },
       "analysis": { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" }
     }
   }
   ```
2. Start the agent with `LogLevel: "DEBUG"`
3. Submit: "hello"
4. Observe the logs

**Expected:**
- Logs show: `Semantic routing: task_type=trivial stage=rules confidence=0.95`
- API call uses Haiku
- `/cost` shows Haiku in the model breakdown

---

## Test 3 — Code generation routes to main model

**Goal:** Verify that code-related prompts use the main model.

**Steps:**

1. Same config as Test 2 (semantic routing enabled)
2. Submit: "write a function that calculates the fibonacci sequence in Python"
3. Observe the logs

**Expected:**
- Logs show: `Semantic routing: task_type=code_generation stage=rules`
- API call uses Sonnet (main model)
- Response contains working code

---

## Test 4 — Tool-result continuation routes to cheap model

**Goal:** Verify that after tool execution, continuation calls use the cheap model.

**Steps:**

1. Same config as Test 2
2. Submit a prompt that triggers a tool call (e.g., "read the file config.json")
3. Observe the logs for the continuation call

**Expected:**
- First LLM call (iteration 0) classifies the task normally (e.g., `code_review` or `conversational`)
- Continuation call after tool result (iteration 1+) routes as `tool_continuation`
- Logs show: `task_type=tool_continuation stage=rules`

---

## Test 5 — Complexity guard overrides cheap routing

**Goal:** Verify that complexity keywords force the main model regardless of other signals.

**Steps:**

1. Same config as Test 2
2. Submit: "analyze this architecture and evaluate the trade-offs"
3. Observe the logs

**Expected:**
- Logs show: `task_type=analysis stage=rules reason=complexity keyword detected`
- API call uses Sonnet
- The complexity guard fires before any cheap-routing rule

---

## Test 6 — Keyword-vector classification (Stage 2)

**Goal:** Verify that messages not matching Stage 1 rules fall through to Stage 2 keyword similarity.

**Steps:**

1. Same config as Test 2
2. Submit a message that doesn't match any obvious rule pattern, e.g.: "tell me about the overview and key highlights of this project"
3. Observe the logs

**Expected:**
- Logs show: `stage=keywords` (not `rules`)
- The task type is determined by keyword similarity (likely `summarization` for this example)
- Confidence is typically 0.4–0.85

---

## Test 7 — Cross-provider routing (Anthropic + Ollama)

**Goal:** Verify that the provider pool dispatches to different providers for different task types.

**Steps:**

1. Ensure Ollama is running: `ollama serve` (or Docker equivalent)
2. Pull a model: `ollama pull llama3.2:3b`
3. Configure:
   ```json
   {
     "SemanticRoutingEnabled": true,
     "RoutingPolicies": {
       "trivial": { "provider": "ollama", "model": "llama3.2:3b" },
       "conversational": { "provider": "ollama", "model": "llama3.2:3b" },
       "code_generation": { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" },
       "analysis": { "provider": "anthropic", "model": "claude-sonnet-4-5-20250929" }
     }
   }
   ```
4. Start the agent
5. Submit: "hi" (should route to Ollama)
6. Submit: "write a sorting algorithm" (should route to Anthropic)
7. Run `/cost`

**Expected:**
- "hi" → routed to `ollama/llama3.2:3b` (cost: $0.00)
- Sorting algorithm → routed to `anthropic/claude-sonnet-4-5-20250929`
- `/cost` model breakdown shows both providers
- Logs show `provider=ollama` and `provider=anthropic` for respective calls

---

## Test 8 — Provider fallback on error

**Goal:** Verify that if a provider fails, the pool falls back to the default provider.

**Steps:**

1. Configure with an unreachable provider:
   ```json
   {
     "SemanticRoutingEnabled": true,
     "RoutingPolicies": {
       "trivial": { "provider": "ollama", "model": "llama3.2:3b" }
     },
     "RoutingFallbackProvider": "anthropic",
     "RoutingFallbackModel": "claude-sonnet-4-5-20250929"
   }
   ```
2. Ensure Ollama is **not** running
3. Start the agent
4. Submit: "hi"

**Expected:**
- Ollama call fails
- Logs show: `Provider marked unavailable` and fallback warning
- Call is retried against Anthropic
- Agent responds normally using Anthropic
- Subsequent Ollama-targeted calls are temporarily routed to Anthropic (cooldown period)

---

## Test 9 — Routing feedback recording

**Goal:** Verify that routing outcomes are recorded to SQLite when feedback is enabled.

**Steps:**

1. Configure:
   ```json
   {
     "SemanticRoutingEnabled": true,
     "RoutingFeedbackEnabled": true,
     "RoutingFeedbackDbPath": ".micro_x/routing.db"
   }
   ```
2. Start the agent
3. Submit 5+ prompts of different types
4. Run `/routing`
5. Run `/routing tasks`
6. Run `/routing providers`
7. Run `/routing stages`
8. Run `/routing recent`

**Expected:**
- `/routing` shows summary: total routed calls, total cost, active task types, stage percentages
- `/routing tasks` shows per-task-type stats (count, avg cost, avg latency, avg confidence)
- `/routing providers` shows per-provider stats
- `/routing stages` shows what percentage of calls were classified by rules vs keywords
- `/routing recent` shows the last 20 routing decisions with details
- SQLite DB exists at `.micro_x/routing.db` with `routing_outcomes` table

---

## Test 10 — Cost savings observable in /cost

**Goal:** Verify that semantic routing produces measurable cost savings compared to single-model usage.

**Steps:**

1. Same config as Test 2 (semantic routing enabled, Haiku for cheap tasks)
2. Submit a mix of prompts:
   - "hello" (trivial → Haiku)
   - "what is Python?" (factual_lookup → Haiku)
   - "write a function to parse JSON" (code_generation → Sonnet)
   - "ok thanks" (trivial → Haiku)
   - "summarize what we discussed" (summarization → Haiku)
3. Run `/cost`

**Expected:**
- Model breakdown shows both Sonnet and Haiku
- Haiku calls have significantly lower cost per call (~3x cheaper input, ~3x cheaper output)
- `call_type` shows `semantic:<task_type>` in per-call breakdown
- Most calls (4 out of 5 in this example) should route to Haiku
- Total session cost is lower than an equivalent session without routing

---

## Test 11 — Semantic routing coexists with per-turn routing

**Goal:** Verify that semantic routing supersedes per-turn routing when both are enabled.

**Steps:**

1. Configure both:
   ```json
   {
     "SemanticRoutingEnabled": true,
     "PerTurnRoutingEnabled": true,
     "PerTurnRoutingModel": "claude-haiku-4-5-20251001",
     "PerTurnRoutingProvider": "anthropic"
   }
   ```
2. Start the agent
3. Submit several prompts
4. Observe the logs

**Expected:**
- Logs show "Semantic routing" messages (not "Turn routing")
- Semantic routing takes precedence when both are enabled
- Per-turn routing is not used

---

## Test 12 — Strategy "rules" only

**Goal:** Verify that `SemanticRoutingStrategy: "rules"` disables the keyword stage.

**Steps:**

1. Configure:
   ```json
   {
     "SemanticRoutingEnabled": true,
     "SemanticRoutingStrategy": "rules"
   }
   ```
2. Submit a prompt that would normally fall through to Stage 2
3. Observe the logs

**Expected:**
- Logs show `stage=rules` for all classifications
- No `stage=keywords` classifications appear
- Unmatched prompts default to `conversational` with low confidence
