/**
 * Task implementation — REPLACE THIS FILE.
 *
 * Must export:
 *   SERVERS: string[]  — MCP server names to connect
 *   runTask(clients, config): Promise<void>  — the task logic
 */

import type { Clients } from "./tools.js";

export const SERVERS: string[] = [];

export async function runTask(
  _clients: Clients,
  _config: Record<string, unknown>,
): Promise<void> {
  console.log("No task implemented. Edit src/task.ts.");
}
