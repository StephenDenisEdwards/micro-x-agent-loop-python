#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x-ai/mcp-shared";
import { registerDraftTweet } from "./tools/draft-tweet.js";
import { registerDraftThread } from "./tools/draft-thread.js";
import { registerPublishDraft } from "./tools/publish-draft.js";
import { registerDeleteTweet } from "./tools/delete-tweet.js";
import { registerGetTweet } from "./tools/get-tweet.js";
import { registerGetMyTweets } from "./tools/get-my-tweets.js";
import { registerUploadMedia } from "./tools/x-upload-media.js";

const logger = createLogger("mcp-x-twitter");

const clientId = process.env.X_CLIENT_ID ?? "";
const clientSecret = process.env.X_CLIENT_SECRET ?? "";

const server = createServer({
  name: "x-twitter",
  version: "0.1.0",
  logger,
});

if (clientId && clientSecret) {
  // Draft tools (no API calls, just local validation)
  registerDraftTweet(server, logger);
  registerDraftThread(server, logger);

  // Publishing & management tools (require auth)
  registerPublishDraft(server, logger, clientId, clientSecret);
  registerDeleteTweet(server, logger, clientId, clientSecret);
  registerGetTweet(server, logger, clientId, clientSecret);
  registerGetMyTweets(server, logger, clientId, clientSecret);
  registerUploadMedia(server, logger, clientId, clientSecret);
} else {
  logger.info("X_CLIENT_ID or X_CLIENT_SECRET not set — all tools disabled. Set credentials in .env to enable.");
}

startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start x-twitter server");
  process.exit(1);
});
