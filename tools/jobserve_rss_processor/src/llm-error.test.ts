import { describe, it, expect } from "vitest";

import { buildLlmErrorReport } from "../../_runtime/src/llm.js";

// Verifies the runtime captures terminal LLM-call failures with enough detail
// to diagnose a 429 (status, retry hint, quota metric) — the gap that made an
// in-task rate-limit error invisible before.

describe("buildLlmErrorReport", () => {
  it("extracts status from a .status field (OpenAI/Anthropic SDK shape)", () => {
    const err = Object.assign(new Error("Too Many Requests"), { status: 429 });
    const r = buildLlmErrorReport("gemini/gemini-2.5-flash", err);
    expect(r.provider).toBe("gemini");
    expect(r.model).toBe("gemini-2.5-flash");
    expect(r.status_code).toBe(429);
  });

  it("extracts status from a .code field (google-genai shape)", () => {
    const err = Object.assign(new Error("RESOURCE_EXHAUSTED"), { code: 429 });
    expect(buildLlmErrorReport("gemini/gemini-2.5-flash", err).status_code).toBe(429);
  });

  it("parses retryDelay and quota metric from the message body", () => {
    const err = new Error(
      '429 RESOURCE_EXHAUSTED. quota_metric: ' +
        'generativelanguage.googleapis.com/generate_requests_per_model_per_minute ' +
        'retryDelay: 42s',
    );
    const r = buildLlmErrorReport("gemini/gemini-2.5-flash", err);
    expect(r.retry_delay_seconds).toBe(42);
    expect(r.quota_metric).toContain("per_minute");
  });

  it("bare model id defaults to anthropic and tolerates missing fields", () => {
    const r = buildLlmErrorReport("claude-sonnet-4-6", new Error("boom"));
    expect(r.provider).toBe("anthropic");
    expect(r.status_code).toBeNull();
    expect(r.retry_delay_seconds).toBeNull();
    expect(r.quota_metric).toBeNull();
    expect(r.error_type).toBe("Error");
    expect(r.message).toContain("boom");
  });
});
