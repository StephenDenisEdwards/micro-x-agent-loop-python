import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import type { Logger } from "./logging.js";

export interface ServerOptions {
  name: string;
  version: string;
  logger: Logger;
}

/**
 * Create an MCP server with stdio transport (default for local servers).
 *
 * Returns the McpServer instance for tool registration.
 * Call `start()` on the returned object to begin serving.
 */
export function createServer(options: ServerOptions): McpServer {
  const server = new McpServer(
    {
      name: options.name,
      version: options.version,
    },
    {
      capabilities: {
        tools: {},
      },
    },
  );

  return server;
}

/**
 * Connect the MCP server to stdio transport and start serving.
 * This is the standard entry point for local MCP servers.
 */
export async function startStdioServer(
  server: McpServer,
  logger: Logger,
): Promise<void> {
  const transport = new StdioServerTransport();

  logger.info("Starting MCP server on stdio transport");

  await server.connect(transport);

  // Handle graceful shutdown
  process.on("SIGINT", async () => {
    logger.info("Received SIGINT, shutting down");
    await server.close();
    process.exit(0);
  });

  process.on("SIGTERM", async () => {
    logger.info("Received SIGTERM, shutting down");
    await server.close();
    process.exit(0);
  });
}
