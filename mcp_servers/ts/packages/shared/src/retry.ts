/**
 * Resilient HTTP fetch with retry, timeout, and Retry-After header support.
 *
 * Uses p-retry for exponential backoff. Provides:
 * - `isTransientStatusCode(code)` — identifies retryable HTTP status codes
 * - `isTransientError(error)` — identifies retryable errors (UpstreamError with transient status, network errors, timeouts)
 * - `resilientFetch(url, init, options)` — fetch with timeout + automatic retry on transient failures
 */

import pRetry, { AbortError } from "p-retry";
import { UpstreamError } from "./errors.js";

export interface ResilientFetchOptions {
  /** Request timeout in ms (default 30000). */
  timeoutMs?: number;
  /** Max retry attempts, not counting the initial attempt (default 3). */
  retries?: number;
  /** Minimum delay between retries in ms (default 1000). */
  minTimeout?: number;
  /** Maximum delay between retries in ms (default 30000). */
  maxTimeout?: number;
}

const TRANSIENT_STATUS_CODES = new Set([429, 500, 502, 503, 504]);

/**
 * Returns true for HTTP status codes that represent transient failures.
 */
export function isTransientStatusCode(code: number): boolean {
  return TRANSIENT_STATUS_CODES.has(code);
}

/**
 * Returns true for errors that represent transient failures worth retrying.
 */
export function isTransientError(error: unknown): boolean {
  if (error instanceof UpstreamError) {
    return error.statusCode != null && isTransientStatusCode(error.statusCode);
  }
  if (error instanceof TypeError) return true; // network errors (fetch spec)
  if (error instanceof Error && error.name === "AbortError") return true; // timeouts
  return false;
}

/**
 * Parse a Retry-After header value into milliseconds.
 * Supports both delta-seconds and HTTP-date formats.
 * Returns undefined if the header is missing or unparseable.
 */
function parseRetryAfter(header: string | null): number | undefined {
  if (!header) return undefined;
  const seconds = Number(header);
  if (!Number.isNaN(seconds) && seconds >= 0) {
    return seconds * 1000;
  }
  const date = Date.parse(header);
  if (!Number.isNaN(date)) {
    const ms = date - Date.now();
    return ms > 0 ? ms : 0;
  }
  return undefined;
}

/**
 * Parse GitHub-style x-ratelimit-reset (unix epoch seconds) into ms delay.
 */
function parseRateLimitReset(header: string | null): number | undefined {
  if (!header) return undefined;
  const epoch = Number(header);
  if (Number.isNaN(epoch)) return undefined;
  const ms = epoch * 1000 - Date.now();
  return ms > 0 ? ms : 0;
}

/**
 * Fetch with automatic timeout and retry on transient failures.
 *
 * On 429 responses, respects Retry-After and x-ratelimit-reset headers
 * by setting `retryAfterMs` on the thrown UpstreamError, which is used
 * via p-retry's `onFailedAttempt` to wait the appropriate time.
 */
export async function resilientFetch(
  url: string | URL,
  init?: RequestInit,
  options?: ResilientFetchOptions,
): Promise<Response> {
  const timeoutMs = options?.timeoutMs ?? 30_000;
  const retries = options?.retries ?? 3;
  const minTimeout = options?.minTimeout ?? 1_000;
  const maxTimeout = options?.maxTimeout ?? 30_000;

  return pRetry(
    async () => {
      const controller = new AbortController();
      const existingSignal = init?.signal;

      // Link external signal if provided
      if (existingSignal?.aborted) {
        throw new AbortError("Request aborted");
      }
      existingSignal?.addEventListener("abort", () => controller.abort(), { once: true });

      const timer = setTimeout(() => controller.abort(), timeoutMs);

      let response: Response;
      try {
        response = await fetch(url, { ...init, signal: controller.signal });
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") {
          // If the external signal caused it, don't retry
          if (existingSignal?.aborted) {
            throw new AbortError("Request aborted");
          }
          throw new UpstreamError(`Request timed out after ${timeoutMs / 1000}s`);
        }
        throw err; // TypeError (network) — p-retry retries by default
      } finally {
        clearTimeout(timer);
      }

      if (isTransientStatusCode(response.status)) {
        // Extract retry delay from response headers
        const retryAfterMs =
          parseRetryAfter(response.headers.get("retry-after")) ??
          parseRateLimitReset(response.headers.get("x-ratelimit-reset"));

        const err = new UpstreamError(
          `HTTP ${response.status} from ${typeof url === "string" ? url : url.toString()}`,
          response.status,
          retryAfterMs,
        );
        throw err;
      }

      return response;
    },
    {
      retries,
      minTimeout,
      maxTimeout,
      randomize: true,
      shouldRetry: ({ error }) => isTransientError(error),
      onFailedAttempt: async ({ error, attemptNumber, retriesLeft }) => {
        // If the server told us how long to wait, honor it
        if (error instanceof UpstreamError && error.retryAfterMs != null) {
          const capped = Math.min(error.retryAfterMs, maxTimeout);
          if (capped > 0) {
            await new Promise((resolve) => setTimeout(resolve, capped));
          }
        }
        // Logging is left to callers; p-retry handles backoff timing
        void attemptNumber;
        void retriesLeft;
      },
    },
  );
}
