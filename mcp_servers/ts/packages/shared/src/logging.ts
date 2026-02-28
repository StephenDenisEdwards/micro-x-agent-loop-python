import pino from "pino";

/**
 * Structured JSON logger that writes to stderr (never stdout).
 * In stdio MCP servers, stdout is the JSON-RPC transport channel —
 * any non-protocol output there corrupts communication.
 */
export function createLogger(serverName: string): pino.Logger {
  return pino(
    {
      name: serverName,
      level: process.env.LOG_LEVEL ?? "info",
      timestamp: pino.stdTimeFunctions.isoTime,
      formatters: {
        level(label) {
          return { level: label };
        },
      },
    },
    pino.destination({ dest: 2, sync: false }), // fd 2 = stderr
  );
}

export type Logger = pino.Logger;
