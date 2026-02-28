import type { z } from "zod";
import { ValidationError } from "./errors.js";

/**
 * Validate tool input against a Zod schema.
 * Throws ValidationError with a clear message on failure.
 */
export function validateInput<T extends z.ZodTypeAny>(
  schema: T,
  input: unknown,
): z.infer<T> {
  const result = schema.safeParse(input);
  if (!result.success) {
    const issues = result.error.issues
      .map((i) => `${i.path.join(".")}: ${i.message}`)
      .join("; ");
    throw new ValidationError(`Invalid input: ${issues}`);
  }
  return result.data;
}

/**
 * Validate tool output against a Zod schema before returning.
 * Logs a warning and returns as-is if validation fails (defensive — don't crash).
 */
export function validateOutput<T extends z.ZodTypeAny>(
  schema: T,
  output: unknown,
  logger?: { warn: (msg: string) => void },
): z.infer<T> {
  const result = schema.safeParse(output);
  if (!result.success) {
    const issues = result.error.issues
      .map((i) => `${i.path.join(".")}: ${i.message}`)
      .join("; ");
    logger?.warn(`Output validation failed (returning anyway): ${issues}`);
    return output as z.infer<T>;
  }
  return result.data;
}
