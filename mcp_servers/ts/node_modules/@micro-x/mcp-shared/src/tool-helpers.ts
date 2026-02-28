import type { z } from "zod";
import type { Logger } from "./logging.js";
import { ValidationError, UpstreamError, PermissionError } from "./errors.js";
import { validateInput } from "./validation.js";

/**
 * Standard tool handler wrapper that provides:
 * - Input validation via Zod schema
 * - Structured logging (request start, duration, outcome)
 * - Error categorization (validation vs upstream vs permission)
 * - structuredContent response format
 */
export function createToolHandler<TInput extends z.ZodTypeAny>(options: {
  name: string;
  inputSchema: TInput;
  logger: Logger;
  handler: (input: z.infer<TInput>) => Promise<ToolResponse>;
}): (input: Record<string, unknown>) => Promise<ToolHandlerResult> {
  const { name, inputSchema, logger, handler } = options;

  return async (rawInput: Record<string, unknown>): Promise<ToolHandlerResult> => {
    const startTime = Date.now();
    const requestId = crypto.randomUUID();

    logger.info({ tool: name, request_id: requestId }, "tool_call_start");

    try {
      const validatedInput = validateInput(inputSchema, rawInput);
      const response = await handler(validatedInput);
      const durationMs = Date.now() - startTime;

      logger.info(
        { tool: name, request_id: requestId, duration_ms: durationMs, outcome: "success" },
        "tool_call_end",
      );

      return {
        content: [{ type: "text", text: response.text }],
        structuredContent: response.structured,
        isError: false,
      };
    } catch (error) {
      const durationMs = Date.now() - startTime;
      const errorMessage = error instanceof Error ? error.message : String(error);
      const errorCode =
        error instanceof ValidationError
          ? "validation_error"
          : error instanceof UpstreamError
            ? "upstream_error"
            : error instanceof PermissionError
              ? "permission_error"
              : "internal_error";

      logger.error(
        {
          tool: name,
          request_id: requestId,
          duration_ms: durationMs,
          outcome: "error",
          error_code: errorCode,
          error_message: errorMessage,
        },
        "tool_call_end",
      );

      return {
        content: [{ type: "text", text: errorMessage }],
        isError: true,
      };
    }
  };
}

export interface ToolResponse {
  /** Human-readable text for the LLM context window. */
  text: string;
  /** Structured data for programmatic consumption (outputSchema). */
  structured?: Record<string, unknown>;
}

export interface ToolHandlerResult {
  content: Array<{ type: string; text: string }>;
  structuredContent?: Record<string, unknown>;
  isError: boolean;
}
