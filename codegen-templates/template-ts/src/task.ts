/**
 * Task implementation — REPLACE THIS FILE.
 *
 * Single-tool shape (default — used by most task apps). Must export:
 *   SERVERS: string[]         — MCP server names to connect
 *   TOOL_NAME: string         — snake_case tool name
 *   TOOL_DESCRIPTION: string  — one-line description for tool discovery
 *   TOOL_INPUT_SCHEMA: {}     — Zod raw shape for tool input params
 *   handleTool(input, clients, profile, config): Promise<Record<string, unknown>>
 *
 * Multi-tool shape (when a task naturally groups related tools — e.g. a
 * processor that exposes both a "process" and a "draft_reply" tool). Replace
 * the above with:
 *   import { defineTools } from "../../_runtime/src/tool-def.js";
 *   export const SERVERS: string[] = [...];
 *   export const SERVER_NAME = "my_app";  // optional; defaults to dir name
 *   export const TOOLS = defineTools([
 *     { name: "tool_a", description: "...", inputSchema: { ... },
 *       handler: async (input, clients, profile, config) => { ... } },
 *     { name: "tool_b", description: "...", inputSchema: { ... },
 *       handler: async (input, clients, profile, config) => { ... } },
 *   ]);
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
