#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x-ai/mcp-shared";
import { registerWebFetch } from "./tools/web-fetch.js";
import { registerWebSearch } from "./tools/web-search.js";

const logger = createLogger("mcp-web");

const braveApiKey = process.env.BRAVE_API_KEY || "";

const server = createServer({
  name: "web",
  version: "0.1.0",
  logger,
});

// web_fetch is always available
registerWebFetch(server, logger);

// web_search requires BRAVE_API_KEY
if (braveApiKey) {
  registerWebSearch(server, logger, braveApiKey);
} else {
  logger.warn("BRAVE_API_KEY not set — web_search tool will not be registered");
}

startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start web server");
  process.exit(1);
});
