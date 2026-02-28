#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x/mcp-shared";
import { getClient } from "./github-client.js";
import { registerListPRs } from "./tools/list-prs.js";
import { registerGetPR } from "./tools/get-pr.js";
import { registerCreatePR } from "./tools/create-pr.js";
import { registerListIssues } from "./tools/list-issues.js";
import { registerCreateIssue } from "./tools/create-issue.js";
import { registerGetFile } from "./tools/get-file.js";
import { registerSearchCode } from "./tools/search-code.js";
import { registerListRepos } from "./tools/list-repos.js";

const logger = createLogger("mcp-github");

const githubToken = process.env.GITHUB_TOKEN || "";

if (!githubToken) {
  logger.fatal("GITHUB_TOKEN environment variable is required");
  process.exit(1);
}

const octokit = getClient(githubToken);

const server = createServer({
  name: "github",
  version: "0.1.0",
  logger,
});

registerListPRs(server, logger, octokit);
registerGetPR(server, logger, octokit);
registerCreatePR(server, logger, octokit);
registerListIssues(server, logger, octokit);
registerCreateIssue(server, logger, octokit);
registerGetFile(server, logger, octokit);
registerSearchCode(server, logger, octokit);
registerListRepos(server, logger, octokit);

startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start github server");
  process.exit(1);
});
