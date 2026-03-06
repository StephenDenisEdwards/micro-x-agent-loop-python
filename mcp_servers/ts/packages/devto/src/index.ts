#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x/mcp-shared";
import { registerCreateArticle } from "./tools/create-article.js";
import { registerPublishArticle } from "./tools/publish-article.js";
import { registerUpdateArticle } from "./tools/update-article.js";
import { registerListMyArticles } from "./tools/list-my-articles.js";
import { registerGetArticle } from "./tools/get-article.js";
import { registerGetArticleComments } from "./tools/get-article-comments.js";

const logger = createLogger("mcp-devto");

const apiKey = process.env.DEV_TO_API_KEY ?? "";

const server = createServer({
  name: "devto",
  version: "0.1.0",
  logger,
});

if (apiKey) {
  registerCreateArticle(server, logger, apiKey);
  registerPublishArticle(server, logger, apiKey);
  registerUpdateArticle(server, logger, apiKey);
  registerListMyArticles(server, logger, apiKey);
  registerGetArticle(server, logger, apiKey);
  registerGetArticleComments(server, logger, apiKey);
} else {
  logger.info("DEV_TO_API_KEY not set — all tools disabled");
}

startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start devto server");
  process.exit(1);
});
