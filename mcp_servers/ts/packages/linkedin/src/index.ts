#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x-ai/mcp-shared";
import { registerLinkedInJobs } from "./tools/linkedin-jobs.js";
import { registerLinkedInJobDetail } from "./tools/linkedin-job-detail.js";
import { registerDraftPost } from "./tools/draft-post.js";
import { registerDraftArticle } from "./tools/draft-article.js";
import { registerPublishDraft } from "./tools/publish-draft.js";

const logger = createLogger("mcp-linkedin");

const clientId = process.env.LINKEDIN_CLIENT_ID ?? "";
const clientSecret = process.env.LINKEDIN_CLIENT_SECRET ?? "";

const server = createServer({
  name: "linkedin",
  version: "0.2.0",
  logger,
});

// Job search tools (no auth needed)
registerLinkedInJobs(server, logger);
registerLinkedInJobDetail(server, logger);

// Publishing tools (need OAuth credentials)
if (clientId && clientSecret) {
  registerDraftPost(server, logger, clientId, clientSecret);
  registerDraftArticle(server, logger, clientId, clientSecret);
  registerPublishDraft(server, logger, clientId, clientSecret);
} else {
  logger.info("LINKEDIN_CLIENT_ID not set — publishing tools disabled");
}

startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start linkedin server");
  process.exit(1);
});
