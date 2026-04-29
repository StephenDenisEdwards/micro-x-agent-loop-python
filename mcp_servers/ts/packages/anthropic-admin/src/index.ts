#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x-ai/mcp-shared";
import { registerUsage } from "./tools/usage.js";

const logger = createLogger("mcp-anthropic-admin");

const adminApiKey = process.env.ANTHROPIC_ADMIN_API_KEY || "";

if (!adminApiKey) {
  logger.fatal("ANTHROPIC_ADMIN_API_KEY environment variable is required");
  process.exit(1);
}

const server = createServer({
  name: "anthropic-admin",
  version: "0.1.0",
  logger,
});

registerUsage(server, logger, adminApiKey);

startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start anthropic-admin server");
  process.exit(1);
});
