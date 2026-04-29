#!/usr/bin/env node

import { createLogger, createServer, startStdioServer } from "@micro-x-ai/mcp-shared";
import { registerBash } from "./tools/bash.js";
import { registerReadFile } from "./tools/read-file.js";
import { registerWriteFile } from "./tools/write-file.js";
import { registerAppendFile } from "./tools/append-file.js";
import { registerSaveMemory } from "./tools/save-memory.js";

const logger = createLogger("mcp-filesystem");

// Configuration from environment
const workingDir = process.env.FILESYSTEM_WORKING_DIR || process.cwd();
const memoryDir = process.env.USER_MEMORY_DIR || "";
const maxMemoryLines = parseInt(process.env.USER_MEMORY_MAX_LINES || "200", 10);

const server = createServer({
  name: "filesystem",
  version: "0.1.0",
  logger,
});

// Register all tools
registerBash(server, logger, workingDir);
registerReadFile(server, logger, workingDir);
registerWriteFile(server, logger, workingDir);
registerAppendFile(server, logger, workingDir);

if (memoryDir) {
  registerSaveMemory(server, logger, memoryDir, maxMemoryLines);
} else {
  logger.warn("USER_MEMORY_DIR not set — save_memory tool will not be registered");
}

// Start
startStdioServer(server, logger).catch((err: unknown) => {
  logger.fatal({ err }, "Failed to start filesystem server");
  process.exit(1);
});
