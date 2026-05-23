import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";

import { loadJsonConfig } from "./config.js";
import { normalizeTools } from "./tool-loader.js";

const tempDirs: string[] = [];

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("loadJsonConfig", () => {
  it("resolves ConfigFile, Base inheritance, and env vars", () => {
    // The inherited-config env var takes precedence in loadJsonConfig, which
    // would short-circuit this file-based test when the suite is run from a
    // process that has it set (e.g. codegen's validation subprocess).
    delete process.env.MICRO_X_AGENT_CONFIG_JSON;

    const root = mkdtempSync(join(tmpdir(), "task-app-config-"));
    tempDirs.push(root);

    const configJsonPath = join(root, "config.json");
    const variantPath = join(root, "variant.json");
    const basePath = join(root, "base.json");

    writeFileSync(configJsonPath, JSON.stringify({ ConfigFile: "variant.json" }, null, 2));
    writeFileSync(
      basePath,
      JSON.stringify(
        {
          McpServers: {
            google: {
              command: "npx",
              args: ["tsx", "google.ts"],
            },
          },
          WorkingDirectory: "${TEST_WORKDIR}",
        },
        null,
        2,
      ),
    );
    writeFileSync(
      variantPath,
      JSON.stringify(
        {
          Base: "base.json",
          McpServers: {
            google: {
              env: {
                GOOGLE_CLIENT_ID: "${TEST_CLIENT_ID}",
              },
            },
          },
        },
        null,
        2,
      ),
    );

    process.env.TEST_WORKDIR = "C:/work";
    process.env.TEST_CLIENT_ID = "client-123";

    const [config, source] = loadJsonConfig(configJsonPath);

    expect(source).toBe("variant.json");
    expect(config).toEqual({
      McpServers: {
        google: {
          command: "npx",
          args: ["tsx", "google.ts"],
          env: {
            GOOGLE_CLIENT_ID: "client-123",
          },
        },
      },
      WorkingDirectory: "C:/work",
    });
  });
});

describe("normalizeTools", () => {
  const noopHandler = async () => ({});

  it("returns TOOLS as-is when set", () => {
    const tools = [
      { name: "tool_a", description: "a", inputSchema: {}, handler: noopHandler },
      { name: "tool_b", description: "b", inputSchema: {}, handler: noopHandler },
    ];
    const result = normalizeTools(
      { SERVERS: ["google"], TOOLS: tools, SERVER_NAME: "my_app" },
      "/tmp/some_dir",
    );
    expect(result.tools).toBe(tools);
    expect(result.servers).toEqual(["google"]);
    expect(result.serverName).toBe("my_app");
  });

  it("synthesizes a single-tool array from legacy exports", () => {
    const result = normalizeTools(
      {
        SERVERS: ["web"],
        TOOL_NAME: "legacy_tool",
        TOOL_DESCRIPTION: "desc",
        TOOL_INPUT_SCHEMA: { x: z.string() },
        handleTool: noopHandler,
      },
      "/tmp/some_dir",
    );
    expect(result.tools).toHaveLength(1);
    expect(result.tools[0].name).toBe("legacy_tool");
    expect(result.tools[0].description).toBe("desc");
    expect(result.serverName).toBe("legacy_tool");
  });

  it("falls back to directory basename when SERVER_NAME absent and multi-tool", () => {
    const tools = [
      { name: "tool_a", description: "a", inputSchema: {}, handler: noopHandler },
      { name: "tool_b", description: "b", inputSchema: {}, handler: noopHandler },
    ];
    const result = normalizeTools({ TOOLS: tools }, "/path/to/my_task_dir");
    expect(result.serverName).toBe("my_task_dir");
  });

  it("throws on duplicate tool names", () => {
    const tools = [
      { name: "dup", description: "a", inputSchema: {}, handler: noopHandler },
      { name: "dup", description: "b", inputSchema: {}, handler: noopHandler },
    ];
    expect(() => normalizeTools({ TOOLS: tools }, "/tmp/dir")).toThrow(/duplicate tool name: dup/);
  });

  it("throws when neither shape is present", () => {
    expect(() => normalizeTools({}, "/tmp/dir")).toThrow(
      /must export either TOOLS .* or the legacy single-tool quadruple/,
    );
  });

  it("throws on a TOOLS entry with missing name", () => {
    const tools = [
      { name: "", description: "a", inputSchema: {}, handler: noopHandler },
    ];
    expect(() => normalizeTools({ TOOLS: tools }, "/tmp/dir")).toThrow(
      /missing or non-string name/,
    );
  });
});
