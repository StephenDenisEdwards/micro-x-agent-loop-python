/**
 * Task implementation — REPLACE THIS FILE.
 *
 * Must export:
 *   SERVERS: string[]         — MCP server names to connect
 *   TOOL_NAME: string         — snake_case tool name
 *   TOOL_DESCRIPTION: string  — one-line description for tool discovery
 *   TOOL_INPUT_SCHEMA: {}     — Zod raw shape for tool input params
 *   handleTool(input, clients, profile, config): Promise<Record<string, unknown>>
 */

import type { Clients } from "./tools.js";

export const SERVERS: string[] = [];
export const TOOL_NAME = "example_tool";
export const TOOL_DESCRIPTION = "No tool implemented. Edit src/task.ts.";
export const TOOL_INPUT_SCHEMA = {};

export async function handleTool(
  _input: Record<string, unknown>,
  _clients: Clients,
  _profile: Record<string, unknown>,
  _config: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return { message: "No task implemented. Edit src/task.ts." };
}
