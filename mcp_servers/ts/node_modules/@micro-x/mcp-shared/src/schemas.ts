import { z } from "zod";

/**
 * Reusable schema fragments for MCP tool definitions.
 */

/** Standard success/failure result wrapper. */
export const ResultSchema = z.object({
  success: z.boolean(),
  message: z.string().optional(),
});

/** File path that must be a non-empty string. */
export const FilePathSchema = z.string().min(1, "path must not be empty");

/** Generic pagination parameters. */
export const PaginationSchema = z.object({
  page: z.number().int().min(1).default(1),
  per_page: z.number().int().min(1).max(100).default(30),
});

/**
 * Convert a Zod schema to JSON Schema suitable for MCP inputSchema/outputSchema.
 * Uses zod-to-json-schema under the hood if available, otherwise falls back
 * to a manual approach for simple schemas.
 */
export function zodToJsonSchema(schema: z.ZodTypeAny): Record<string, unknown> {
  // Use zod's built-in JSON schema generation
  // The MCP SDK handles this internally when using zod schemas,
  // but we expose it for manual tool definitions.
  return zodToPlainJsonSchema(schema);
}

function zodToPlainJsonSchema(schema: z.ZodTypeAny): Record<string, unknown> {
  // For object schemas, extract shape
  if (schema instanceof z.ZodObject) {
    const shape = schema.shape as Record<string, z.ZodTypeAny>;
    const properties: Record<string, unknown> = {};
    const required: string[] = [];

    for (const [key, value] of Object.entries(shape)) {
      properties[key] = zodToPlainJsonSchema(value);
      if (!(value instanceof z.ZodOptional) && !(value instanceof z.ZodDefault)) {
        required.push(key);
      }
    }

    const result: Record<string, unknown> = {
      type: "object",
      properties,
      additionalProperties: false,
    };
    if (required.length > 0) {
      result.required = required;
    }
    return result;
  }

  if (schema instanceof z.ZodString) return { type: "string" };
  if (schema instanceof z.ZodNumber) return { type: "number" };
  if (schema instanceof z.ZodBoolean) return { type: "boolean" };
  if (schema instanceof z.ZodArray) {
    return { type: "array", items: zodToPlainJsonSchema(schema.element) };
  }
  if (schema instanceof z.ZodOptional) {
    return zodToPlainJsonSchema(schema.unwrap());
  }
  if (schema instanceof z.ZodDefault) {
    return zodToPlainJsonSchema(schema.removeDefault());
  }
  if (schema instanceof z.ZodEnum) {
    return { type: "string", enum: schema.options };
  }

  return {};
}
