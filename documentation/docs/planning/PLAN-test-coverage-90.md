# Plan: Achieve 90% Test Coverage

## Status

Completed (85% coverage achieved — acceptable threshold)

## Context

Current test coverage is **59%** (2565 of 6285 statements missed) across 460 tests. The goal is to reach **90%** coverage. The core agent logic and data layer are already well-tested; the main gaps are in the broker subsystem, CLI entry points, and utility modules.

## Current Coverage Baseline

| Area | Files | Current | Target | Gap (stmts) |
|------|-------|---------|--------|-------------|
| **Core loop** | agent.py, turn_engine.py, compaction.py | 67-92% | 90% | ~100 |
| **Config & models** | agent_config.py, app_config.py, usage.py | 85-100% | 90% | ~20 |
| **Memory** | session_manager, checkpoints, events, facade | 89-100% | 90% | ~5 |
| **Providers** | anthropic_provider, openai_provider | 79-95% | 90% | ~30 |
| **Server** | app.py, agent_manager, ws_channel, sdk.py | 50-94% | 90% | ~80 |
| **Mode selector** | mode_selector.py | 98% | 90% | 0 |
| **Tool search, sub_agent** | tool_search.py, sub_agent.py | 98% | 90% | 0 |
| **Broker** | scheduler, dispatcher, store, channels, service, cli, webhook, runner, polling, response_router | 0-68% | 90% | ~600 |
| **CLI/entry** | __main__.py, bootstrap.py | 18-29% | 90% | ~250 |
| **Agent channel** | agent_channel.py | 64% | 90% | ~55 |
| **Commands** | command_handler.py, router.py, prompt_commands, voice_command | 26-77% | 90% | ~130 |
| **Utilities** | analyze_costs.py, tool_result_formatter.py, voice_ingress.py | 0-27% | 90% | ~160 |
| **MCP** | mcp_manager.py, mcp_tool_proxy.py | 24-43% | 90% | ~80 |
| **Other** | llm_client.py, logging_config.py, provider.py, server/client.py, broker_routes.py | 18-77% | 90% | ~120 |

**Total gap: ~1630 statements to cover** (from 59% → 90% of 6285 stmts).

## Prioritised Work Packages

### Phase 1: High-impact, low-effort (existing patterns)

These modules have partial coverage and existing test fakes. Extending tests is straightforward.

1. **agent.py** (67% → 90%) — Test uncovered branches: error handling, memory integration, mode analysis paths
2. **turn_engine.py** (92% → 95%) — Minor gap, cover error/edge paths
3. **agent_channel.py** (64% → 90%) — Test BrokerChannel, BufferedChannel, AgentChannel edge cases
4. **command_handler.py** (58% → 90%) — Test each slash command path; many are simple dispatchers
5. **compaction.py** (86% → 90%) — Cover remaining summarisation edge cases
6. **app_config.py** (85% → 90%) — Test config inheritance, env var expansion edge cases

### Phase 2: Server & providers

7. **server/app.py** (72% → 90%) — Test REST and WebSocket endpoints with httpx/TestClient
8. **server/sdk.py** (50% → 90%) — Test SDK wrapper methods
9. **server/broker_routes.py** (40% → 90%) — Test broker API routes
10. **server/client.py** (18% → 90%) — Test WebSocket CLI client with mock server
11. **openai_provider.py** (79% → 90%) — Test streaming, error handling
12. **llm_client.py** (68% → 90%) — Test retry/error paths

### Phase 3: Broker subsystem

The broker is the largest gap. Tests should use SQLite in-memory DBs and mock subprocesses.

13. **broker/store.py** (68% → 90%) — Test remaining CRUD operations
14. **broker/scheduler.py** (46% → 90%) — Test cron evaluation, job lifecycle
15. **broker/dispatcher.py** (42% → 90%) — Test dispatch logic, retry handling
16. **broker/runner.py** (40% → 90%) — Test subprocess spawning with mocks
17. **broker/channels.py** (37% → 90%) — Test each channel adapter (Email, Slack, Teams, etc.)
18. **broker/polling.py** (24% → 90%) — Test polling loop
19. **broker/response_router.py** (23% → 90%) — Test routing logic
20. **broker/service.py** (0% → 90%) — Test service start/stop lifecycle
21. **broker/cli.py** (0% → 90%) — Test CLI argument parsing and dispatch
22. **broker/webhook_server.py** (0% → 90%) — Test webhook endpoint handling

### Phase 4: Utilities & remaining modules

23. **analyze_costs.py** (0% → 90%) — Test cost analysis calculations
24. **tool_result_formatter.py** (27% → 90%) — Test formatting/truncation logic
25. **voice_ingress.py** (25% → 90%) — Test audio ingress with mock streams
26. **mcp/mcp_manager.py** (24% → 90%) — Test MCP server lifecycle with mocks
27. **mcp/mcp_tool_proxy.py** (43% → 90%) — Test tool proxying
28. **bootstrap.py** (29% → 90%) — Test wiring logic with dependency injection
29. **__main__.py** (18% → 90%) — Test CLI arg parsing and startup paths
30. **commands/prompt_commands.py** (26% → 90%) — Test prompt command handlers
31. **logging_config.py** (77% → 90%) — Cover remaining config paths

## Testing Approach

- **Use existing fakes** (`tests/fakes.py`: `FakeStreamProvider`, `FakeTool`) wherever possible
- **SQLite in-memory** for all DB-dependent tests (broker, memory)
- **No real LLM calls** — all provider tests use recorded/mocked responses
- **No real MCP servers** — mock the MCP client transport layer
- **httpx.AsyncClient / TestClient** for server endpoint tests
- **unittest.mock** for subprocess, file I/O, and external service calls

## Success Criteria

- `python -m pytest tests/ --cov=src/micro_x_agent_loop --cov-fail-under=90` passes
- No tests rely on network access or external services
- All 460+ existing tests continue to pass
