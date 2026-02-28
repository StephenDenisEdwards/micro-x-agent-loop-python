/**
 * Categorized error types for MCP tool execution.
 *
 * - ValidationError: bad input from the LLM (schema mismatch, missing fields)
 * - UpstreamError:   an external API or service failed
 * - PermissionError: access denied (credentials, sandbox, path traversal)
 */

export class ValidationError extends Error {
  public readonly code = "VALIDATION_ERROR" as const;

  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

export class UpstreamError extends Error {
  public readonly code = "UPSTREAM_ERROR" as const;
  public readonly statusCode?: number;

  constructor(message: string, statusCode?: number) {
    super(message);
    this.name = "UpstreamError";
    this.statusCode = statusCode;
  }
}

export class PermissionError extends Error {
  public readonly code = "PERMISSION_ERROR" as const;

  constructor(message: string) {
    super(message);
    this.name = "PermissionError";
  }
}

export type McpToolError = ValidationError | UpstreamError | PermissionError;
