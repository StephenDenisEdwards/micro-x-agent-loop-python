#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x/mcp-shared";
import { registerDraftPost } from "./tools/draft-post.js";
import { registerPublishDraft } from "./tools/publish-draft.js";
import { registerSubmitComment } from "./tools/submit-comment.js";
import { registerEdit } from "./tools/edit.js";
import { registerDelete } from "./tools/delete.js";
import { registerGetPost } from "./tools/get-post.js";
import { registerListSubreddit } from "./tools/list-subreddit.js";
import { registerGetMyPosts } from "./tools/get-my-posts.js";
import { registerGetFlairs } from "./tools/get-flairs.js";
import { registerGetSubredditRules } from "./tools/get-subreddit-rules.js";
import { registerGetMe } from "./tools/get-me.js";

const logger = createLogger("mcp-reddit");

const clientId = process.env.REDDIT_CLIENT_ID ?? "";
const clientSecret = process.env.REDDIT_CLIENT_SECRET ?? "";
const username = process.env.REDDIT_USERNAME ?? "";
const password = process.env.REDDIT_PASSWORD ?? "";
const userAgent = process.env.REDDIT_USER_AGENT ?? `windows:com.micro-x.reddit-mcp:v0.1.0 (by /u/${username})`;

const server = createServer({
  name: "reddit",
  version: "0.1.0",
  logger,
});

if (clientId && clientSecret && username && password) {
  // Draft tools (pre-flight validation, no submission)
  registerDraftPost(server, logger, clientId, clientSecret, username, password, userAgent);

  // Publishing
  registerPublishDraft(server, logger, clientId, clientSecret, username, password, userAgent);

  // Direct actions (no draft pattern)
  registerSubmitComment(server, logger, clientId, clientSecret, username, password, userAgent);
  registerEdit(server, logger, clientId, clientSecret, username, password, userAgent);
  registerDelete(server, logger, clientId, clientSecret, username, password, userAgent);

  // Read-only tools
  registerGetPost(server, logger, clientId, clientSecret, username, password, userAgent);
  registerListSubreddit(server, logger, clientId, clientSecret, username, password, userAgent);
  registerGetMyPosts(server, logger, clientId, clientSecret, username, password, userAgent);
  registerGetFlairs(server, logger, clientId, clientSecret, username, password, userAgent);
  registerGetSubredditRules(server, logger, clientId, clientSecret, username, password, userAgent);
  registerGetMe(server, logger, clientId, clientSecret, username, password, userAgent);
} else {
  logger.info("Reddit credentials not fully set — all tools disabled. Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, and REDDIT_PASSWORD in .env to enable.");
}

startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start reddit server");
  process.exit(1);
});
