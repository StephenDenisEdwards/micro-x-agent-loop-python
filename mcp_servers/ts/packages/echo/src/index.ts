#!/usr/bin/env node

import { z } from "zod";
import {
  createLogger,
  createServer,
  startStdioServer,
} from "@micro-x/mcp-shared";

// --help / -h flag
if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(`@micro-x/mcp-echo — Echo MCP server for connectivity testing

Usage:
  npx -y @micro-x/mcp-echo          Start the server (stdio transport)
  npx -y @micro-x/mcp-echo --help   Show this message

Tools:
  echo   Echo back the provided message with a timestamp

No environment variables required.
`);
  process.exit(0);
}

const logger = createLogger("mcp-echo");

const server = createServer({
  name: "echo",
  version: "0.1.0",
  logger,
});

// --- Echo tool ---

server.registerTool(
  "echo",
  {
    description: "Echo back the provided message. Useful for testing MCP connectivity.",
    inputSchema: {
      message: z.string().describe("The message to echo back"),
    },
    outputSchema: {
      echoed: z.string(),
      timestamp: z.string(),
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
    },
  },
  async (input) => {
    const startTime = Date.now();
    const requestId = crypto.randomUUID();

    logger.info({ tool: "echo", request_id: requestId }, "tool_call_start");

    const result = {
      echoed: input.message,
      timestamp: new Date().toISOString(),
    };

    const durationMs = Date.now() - startTime;
    logger.info(
      { tool: "echo", request_id: requestId, duration_ms: durationMs, outcome: "success" },
      "tool_call_end",
    );

    return {
      structuredContent: result,
      content: [{ type: "text" as const, text: result.echoed }],
    };
  },
);

// --- Start server ---

startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start echo server");
  process.exit(1);
});
