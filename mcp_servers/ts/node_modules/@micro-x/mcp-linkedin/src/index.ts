#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x/mcp-shared";
import { registerLinkedInJobs } from "./tools/linkedin-jobs.js";
import { registerLinkedInJobDetail } from "./tools/linkedin-job-detail.js";

const logger = createLogger("mcp-linkedin");

const server = createServer({
  name: "linkedin",
  version: "0.1.0",
  logger,
});

registerLinkedInJobs(server, logger);
registerLinkedInJobDetail(server, logger);

startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start linkedin server");
  process.exit(1);
});
