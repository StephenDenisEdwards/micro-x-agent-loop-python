#!/usr/bin/env node
// Regenerate src/tool-types.ts from upstream MCP server schemas.
//
// Usage:
//   node scripts/regen-tool-types.mjs              # rewrite src/tool-types.ts
//   node scripts/regen-tool-types.mjs --check      # write to a temp file and diff; exit non-zero if changed
//
// Add servers/tools to scripts/tool-types.config.json. Each listed server's
// dist/index.js must be built (run `npm run build` in that package first).

import { spawn } from "node:child_process";
import { readFile, writeFile, mkdtemp } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = path.resolve(HERE, "..");
const CONFIG_PATH = path.join(HERE, "tool-types.config.json");

const args = new Set(process.argv.slice(2));
const CHECK_MODE = args.has("--check");

const config = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
const outputFile = path.resolve(PKG_ROOT, config.outputFile);

const MARKER = "// ============================================================";
const HEADER = `${MARKER}
// AUTO-GENERATED — do not edit by hand.
// Regenerate with:  npm run regen-tool-types  (in tools/template-ts/)
// Source of truth: upstream MCP server inputSchema / outputSchema.
${MARKER}
`;

async function main() {
  const sections = [];
  for (const server of config.servers) {
    const spawnSpec = resolveSpawnSpec(server);
    const tools = await listTools(spawnSpec, server.env ?? {});
    const wanted = new Set(server.tools);
    const found = new Map(tools.map((t) => [t.name, t]));
    for (const name of wanted) {
      if (!found.has(name)) {
        throw new Error(`Server "${server.name}" does not expose tool "${name}". Available: ${[...found.keys()].join(", ")}`);
      }
    }
    sections.push(renderServerSection(server, tools.filter((t) => wanted.has(t.name))));
  }

  const generated = HEADER + "\n" + sections.join("\n\n") + "\n";

  if (CHECK_MODE) {
    const dir = await mkdtemp(path.join(tmpdir(), "tool-types-check-"));
    const tmpPath = path.join(dir, "tool-types.ts");
    await writeFile(tmpPath, generated, "utf8");
    let current = "";
    try { current = await readFile(outputFile, "utf8"); } catch {}
    if (current !== generated) {
      process.stderr.write(
        `[regen-tool-types --check] DRIFT detected.\n` +
        `  ${outputFile} is out of sync with upstream MCP schemas.\n` +
        `  Run: npm run regen-tool-types\n`,
      );
      process.exit(1);
    }
    process.stdout.write("[regen-tool-types --check] OK — no drift.\n");
    return;
  }

  await writeFile(outputFile, generated, "utf8");
  process.stdout.write(`Wrote ${path.relative(process.cwd(), outputFile)} (${generated.length} bytes)\n`);
}

/**
 * Resolve a config entry to the spawn command + args.
 *
 * Two shapes are supported:
 *   - Local first-party server: { "entry": "../../mcp_servers/.../dist/index.js" }
 *     → spawn `node <entry>`, requires the package to be built.
 *   - Third-party / npx-fetched server: { "command": "npx.cmd", "args": [...] }
 *     → spawn that command directly. Use shell:true on Windows for .cmd files.
 */
function resolveSpawnSpec(server) {
  if (server.command) {
    return {
      cmd: server.command,
      args: server.args ?? [],
      shell: server.command.endsWith(".cmd") || server.command.endsWith(".bat"),
      label: `${server.command} ${(server.args ?? []).join(" ")}`,
    };
  }
  if (!server.entry) {
    throw new Error(`Server "${server.name}" must specify either "entry" or "command".`);
  }
  const entryAbs = path.resolve(PKG_ROOT, server.entry);
  if (!existsSync(entryAbs)) {
    throw new Error(
      `Server entry not found: ${entryAbs}\n` +
      `Build the upstream MCP server first.`,
    );
  }
  return { cmd: "node", args: [entryAbs], shell: false, label: entryAbs };
}

async function listTools(spawnSpec, extraEnv) {
  const { cmd, args: spawnArgs, shell, label } = spawnSpec;
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, spawnArgs, {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, ...extraEnv },
      shell,
    });
    let stderrBuf = "";
    child.stderr.on("data", (d) => { stderrBuf += d.toString(); });
    let buf = "";
    let done = false;
    const timer = setTimeout(() => {
      if (done) return;
      child.kill();
      reject(new Error(`Timed out waiting for tools/list from ${label}\nstderr:\n${stderrBuf}`));
    }, 30_000);
    child.on("error", (err) => { if (!done) { done = true; clearTimeout(timer); reject(err); } });
    child.stdout.on("data", (d) => {
      buf += d.toString();
      const lines = buf.split("\n"); buf = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        let msg; try { msg = JSON.parse(line); } catch { continue; }
        if (msg.id === 1) {
          child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }) + "\n");
        } else if (msg.id === 2) {
          done = true;
          clearTimeout(timer);
          child.kill();
          resolve(msg.result?.tools ?? []);
          return;
        }
      }
    });
    child.stdin.write(JSON.stringify({
      jsonrpc: "2.0", id: 1, method: "initialize",
      params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "regen-tool-types", version: "0" } },
    }) + "\n");
  });
}

function renderServerSection(server, tools) {
  const head = `// ${"-".repeat(70)}\n// ${server.name}\n// ${"-".repeat(70)}`;
  const blocks = tools.map((t) => renderTool(t)).join("\n\n");
  return `${head}\n\n${blocks}`;
}

function renderTool(tool) {
  const pascal = pascalCase(tool.name);
  const argsType = renderType(tool.inputSchema, `${pascal}Args`);
  const resultType = renderType(tool.outputSchema, `${pascal}Result`);
  const desc = (tool.description ?? "").replace(/\*\//g, "*\\/").trim();
  const docComment = desc ? `/** ${desc} */\n` : "";
  return `${docComment}export type ${pascal}Args = ${argsType.body};\n\nexport type ${pascal}Result = ${resultType.body};`;
}

function renderType(schema, name) {
  if (!schema) return { body: "Record<string, unknown>" };
  return { body: typeFor(schema) };
}

function typeFor(schema) {
  if (!schema || typeof schema !== "object") return "unknown";
  if (schema.const !== undefined) return JSON.stringify(schema.const);
  if (Array.isArray(schema.enum)) {
    return schema.enum.map((v) => JSON.stringify(v)).join(" | ") || "never";
  }
  if (Array.isArray(schema.anyOf)) return schema.anyOf.map(typeFor).join(" | ");
  if (Array.isArray(schema.oneOf)) return schema.oneOf.map(typeFor).join(" | ");

  const t = schema.type;
  if (t === "string") return "string";
  if (t === "number" || t === "integer") return "number";
  if (t === "boolean") return "boolean";
  if (t === "null") return "null";
  if (t === "array") return `Array<${typeFor(schema.items ?? {})}>`;
  if (t === "object" || schema.properties) return objectType(schema);
  if (Array.isArray(t)) return t.map((tt) => typeFor({ ...schema, type: tt })).join(" | ");
  return "unknown";
}

function objectType(schema) {
  const props = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const lines = Object.entries(props).map(([key, sub]) => {
    const optional = required.has(key) ? "" : "?";
    const doc = renderJsDoc(sub);
    const safeKey = /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key) ? key : JSON.stringify(key);
    return `  ${safeKey}${optional}: ${typeFor(sub)};${doc}`;
  });
  if (!lines.length) return schema.additionalProperties === false ? "Record<string, never>" : "Record<string, unknown>";
  return `{\n${lines.join("\n")}\n}`;
}

function renderJsDoc(sub) {
  if (!sub || typeof sub !== "object") return "";
  const desc = sub.description ? String(sub.description).trim() : "";
  const constraints = constraintsFor(sub);
  const merged = desc + constraints;
  if (!merged) return "";
  return ` /** ${merged.replace(/\*\//g, "*\\/")} */`;
}

// Surface JSON-Schema constraints that TypeScript can't express (integer,
// min/max, lengths, formats, defaults). The LLM consuming these types reads
// JSDoc, so embedding constraints here is what actually gets them enforced.
function constraintsFor(schema) {
  if (!schema || typeof schema !== "object") return "";
  const parts = [];

  if (schema.type === "integer") parts.push("integer");

  if (schema.minimum !== undefined && schema.maximum !== undefined) {
    parts.push(`${schema.minimum}–${schema.maximum}`);
  } else if (schema.minimum !== undefined) {
    parts.push(`≥ ${schema.minimum}`);
  } else if (schema.maximum !== undefined) {
    parts.push(`≤ ${schema.maximum}`);
  }
  if (schema.exclusiveMinimum !== undefined) parts.push(`> ${schema.exclusiveMinimum}`);
  if (schema.exclusiveMaximum !== undefined) parts.push(`< ${schema.exclusiveMaximum}`);
  if (schema.multipleOf !== undefined) parts.push(`multiple of ${schema.multipleOf}`);

  if (schema.type === "string") {
    if (schema.minLength !== undefined && schema.maxLength !== undefined) {
      parts.push(`${schema.minLength}–${schema.maxLength} chars`);
    } else if (schema.minLength !== undefined) {
      parts.push(`min ${schema.minLength} chars`);
    } else if (schema.maxLength !== undefined) {
      parts.push(`max ${schema.maxLength} chars`);
    }
    if (schema.format) parts.push(`format: ${schema.format}`);
    if (schema.pattern) parts.push(`pattern: ${schema.pattern}`);
  }

  if (schema.type === "array") {
    if (schema.minItems !== undefined && schema.maxItems !== undefined) {
      parts.push(`${schema.minItems}–${schema.maxItems} items`);
    } else if (schema.minItems !== undefined) {
      parts.push(`min ${schema.minItems} items`);
    } else if (schema.maxItems !== undefined) {
      parts.push(`max ${schema.maxItems} items`);
    }
    if (schema.uniqueItems) parts.push("unique items");
  }

  if (schema.default !== undefined) parts.push(`default: ${JSON.stringify(schema.default)}`);

  return parts.length ? ` (${parts.join(", ")})` : "";
}

function pascalCase(snake) {
  return snake
    .split(/[_-]+/)
    .filter(Boolean)
    .map((s) => s[0].toUpperCase() + s.slice(1))
    .join("");
}

main().catch((err) => {
  process.stderr.write(`[regen-tool-types] ${err.message}\n`);
  process.exit(1);
});
