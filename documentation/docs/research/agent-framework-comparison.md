# Agent Framework Comparison: Dynamic Tool/Task Generation

**Date:** 2026-03-03
**Context:** Evaluating whether generated task apps should be MCP servers, and how other frameworks handle similar problems.

## Our Approach (micro-x codegen)

- LLM generates complete Python task apps from a prompt (collector, scorer, processor, tests)
- Generated app is a script (`python -m tools.job_search`) that connects to MCP servers as a client
- Codegen MCP server wraps invocation via `run_task()`
- **Unique:** We generate the business logic itself, not just orchestration
- **Problem:** LLM is non-deterministic — same prompt produces different code each run, sometimes broken (wrong query strings, different parsing logic, etc.)

## OpenClaw

- **200k+ GitHub stars**, open-source personal AI agent
- **Skills system:** A skill is a folder with `SKILL.md` (YAML frontmatter + markdown instructions). Skills load into agent context when active. Not generated code — prompt templates with tool access. Agent follows instructions each time rather than producing a reusable app.
- **Lazy tool loading:** Only one meta-tool in base context: `search_available_tools(query)`. Agent calls it when needed, handler returns the exact schema, tool becomes available next turn. Tools billed only when loaded — up to 90% API cost reduction.
- **ClawHub:** Public skill registry with vector search (embeddings, not keywords). All skills are open/public.
- **MCP integration:** Native MCP support. Tools defined as TypeScript functions with schemas. MCP tools are reusable across any MCP-compatible agent.
- **Key difference from us:** Skills are instructions the agent follows at runtime. We generate standalone code. They sidestep the reliability problem by not generating code at all.

Sources:
- https://bibek-poudel.medium.com/how-openclaw-works-understanding-ai-agents-through-a-real-architecture-5d59cc7a4764
- https://www.digitalocean.com/resources/articles/what-are-openclaw-skills
- https://github.com/openclaw/clawhub
- https://github.com/openclaw-token-optimizer/openclaw-token-optimizer

## Microsoft AutoGen / Agent Framework

- AutoGen v0.4 (Jan 2025): Complete redesign for multi-agent orchestration with code generation
- Microsoft Agent Framework (Oct 2025): Merges AutoGen's multi-agent orchestration with Semantic Kernel's production foundations
- Tools are pre-defined with function-calling interfaces, not dynamically generated
- Focus is on orchestrating existing tools, not generating new business logic

## OpenAI Agents SDK

- Lightweight Python framework (March 2025), 11k+ GitHub stars
- Multi-agent workflows with tracing and guardrails
- Provider-agnostic (100+ LLMs)
- Tools defined upfront with schemas — no dynamic generation

## Google Agent Development Kit (ADK)

- Modular framework (April 2025), integrates with Gemini/Vertex AI
- Hierarchical agent compositions
- Tools are code you write — no generation

## LangGraph / LangChain

- Stateful multi-agent apps modelled as directed cyclic graphs
- Complex branching, looping, decision logic
- Tools are pre-written code with function-calling interfaces

## Key Observations

1. **Nobody generates task apps from prompts.** Every framework assumes humans write the tools. Our codegen approach is novel but hits the fundamental LLM reliability problem.

2. **The reliability problem is unsolved.** All frameworks sidestep it by having humans write deterministic tool code. The LLM orchestrates (decides which tools to call), but the tools themselves are fixed.

3. **OpenClaw's lazy loading is the closest parallel** to our tool discovery feature (commit `5b2135f`). Both solve the "too many tools in context" problem.

4. **MCP is becoming the standard interface.** OpenClaw, Claude Code, and our system all use MCP for tool integration. Making generated apps MCP servers would align with this trend.

5. **The real gap:** A framework that can reliably generate business logic from natural language and produce consistent, testable output. Current LLM technology isn't reliable enough for this — prompts are ignored, code varies between runs, edge cases are missed randomly.

## Open Question: Should Generated Apps Be MCP Servers?

**Pros:**
- Parameterised input schemas (no more hardcoded query strings)
- Structured results back to caller
- Composable — agent can chain tools
- Aligns with MCP ecosystem trend

**Cons:**
- Dual role complexity (server to agent, client to google/linkedin)
- Lifecycle management (one-shot task vs long-lived server)
- Codegen already acts as proxy via `run_task()`

**Middle ground:** Keep script model, but generate with CLI args or JSON config for parameterisation. Codegen's `run_task` passes parameters through.
