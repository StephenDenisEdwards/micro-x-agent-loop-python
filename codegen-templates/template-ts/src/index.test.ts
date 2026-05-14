import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { loadJsonConfig } from "./index.js";

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
