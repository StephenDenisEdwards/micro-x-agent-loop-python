import { realpath } from "node:fs/promises";
import path from "node:path";

const IS_WINDOWS = process.platform === "win32";

export interface PathPolicy {
  workingDir: string;
  extraAllowed: string[];
}

export function loadPathPolicy(workingDir: string, allowedDirsEnv: string | undefined): PathPolicy {
  const extras = (allowedDirsEnv ?? "")
    .split(path.delimiter)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => path.resolve(p));
  return { workingDir: path.resolve(workingDir), extraAllowed: extras };
}

export async function resolveAllowed(
  policy: PathPolicy,
  input: string | undefined,
  opts: { mustExist: boolean } = { mustExist: true },
): Promise<string> {
  const raw = input ?? policy.workingDir;
  const resolved = path.isAbsolute(raw) ? path.resolve(raw) : path.resolve(policy.workingDir, raw);

  const real = opts.mustExist
    ? await realpath(resolved)
    : await realpathExistingAncestor(resolved);

  const roots = [policy.workingDir, ...policy.extraAllowed];
  for (const root of roots) {
    const realRoot = await realpath(root).catch(() => root);
    if (isInside(real, realRoot)) return real;
  }

  const allowed = roots.map((r) => `  - ${r}`).join("\n");
  throw new Error(
    `Path "${raw}" is outside the allowed roots. Allowed:\n${allowed}\n` +
    `(set FILESYSTEM_ALLOWED_DIRS to add more, separated by "${path.delimiter}")`,
  );
}

function isInside(target: string, root: string): boolean {
  const t = IS_WINDOWS ? target.toLowerCase() : target;
  const r = IS_WINDOWS ? root.toLowerCase() : root;
  if (t === r) return true;
  const rWithSep = r.endsWith(path.sep) ? r : r + path.sep;
  return t.startsWith(rWithSep);
}

async function realpathExistingAncestor(p: string): Promise<string> {
  let current = p;
  const tail: string[] = [];
  while (true) {
    try {
      const real = await realpath(current);
      return tail.length ? path.join(real, ...tail.reverse()) : real;
    } catch {
      const parent = path.dirname(current);
      if (parent === current) return p;
      tail.push(path.basename(current));
      current = parent;
    }
  }
}
