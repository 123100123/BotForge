#!/usr/bin/env node
// Compares the interfaces in lib/types.ts with the pydantic models in backend/app/schemas/business.py:
// field names, nullability (`X | None` <-> `X | null`), optionality of request (*In) fields that have a
// backend default, and Literal unions. Not wired into npm scripts. Usage (from frontend/):
//   node scripts/check-schema-parity.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const py = readFileSync(join(root, "..", "backend/app/schemas/business.py"), "utf8");
const ts = readFileSync(join(root, "lib/types.ts"), "utf8");

const quoted = (text) => [...text.matchAll(/"([^"]+)"/g)].map((x) => x[1]).sort();

// ---- backend
const pyAliases = {}; // Name = Literal["a", "b"]
for (const m of py.matchAll(/^(\w+) = Literal\[([^\]]+)\]/gm)) pyAliases[m[1]] = quoted(m[2]);

function literalOf(type) {
  const inline = type.match(/Literal\[([^\]]+)\]/);
  if (inline) return quoted(inline[1]);
  const bare = type.replace(/\s*\|\s*None/, "").trim();
  return pyAliases[bare] ?? null;
}

const pyModels = {};
for (const block of py.split(/^class /m).slice(1)) {
  const name = block.match(/^(\w+)\(/)[1];
  const fields = {};
  let depth = 0;
  for (const line of block.split("\n").slice(1)) {
    if (/^\S/.test(line)) break;
    const m = depth === 0 ? line.match(/^    (\w+): (.+)$/) : null;
    depth += (line.match(/[([{]/g) ?? []).length - (line.match(/[)\]}]/g) ?? []).length;
    if (!m || m[1].startsWith("_")) continue;
    // `= Field(ge=1)` is a bound, not a default; `= Field(default=...)`, `default_factory` and `= value` are.
    const hasDefault = /\s=\s(?!Field\()/.test(m[2]) || /Field\([^)]*default/.test(m[2]);
    const type = m[2].split(/\s=\s/)[0];
    fields[m[1]] = { nullable: /\|\s*None\b/.test(type), hasDefault, literal: literalOf(type) };
  }
  pyModels[name] = fields;
}

// ---- frontend
const tsAliases = {};
for (const m of ts.matchAll(/^export type (\w+) =\s*([^;]+);/gm)) tsAliases[m[1]] = quoted(m[2]);
const tsModels = {};
for (const m of ts.matchAll(/^export interface (\w+) \{([\s\S]*?)^\}/gm)) {
  const fields = {};
  for (const f of m[2].matchAll(/^ {2}(\w+)(\?)?: ([^;]+);/gm)) {
    const type = f[3].trim();
    const lit = quoted(type);
    fields[f[1]] = {
      optional: !!f[2],
      nullable: /\|\s*null\b/.test(type),
      literal: lit.length ? lit : (tsAliases[type.replace(/\s*\|\s*null/, "").trim()] ?? null),
    };
  }
  tsModels[m[1]] = fields;
}

// ---- compare
const problems = [];
let compared = 0;
for (const [model, pf] of Object.entries(pyModels)) {
  const tf = tsModels[model];
  if (!tf) {
    problems.push(`${model}: no TypeScript interface`);
    continue;
  }
  compared++;
  const isInput = model.endsWith("In");
  for (const f of Object.keys(pf)) if (!(f in tf)) problems.push(`${model}.${f}: missing in types.ts`);
  for (const f of Object.keys(tf)) if (!(f in pf)) problems.push(`${model}.${f}: not in backend model`);
  for (const [f, p] of Object.entries(pf)) {
    const t = tf[f];
    if (!t) continue;
    if (p.nullable !== t.nullable && !(isInput && t.optional && p.hasDefault)) {
      problems.push(`${model}.${f}: nullability backend=${p.nullable} frontend=${t.nullable}`);
    }
    if (isInput && p.hasDefault && !t.optional) problems.push(`${model}.${f}: backend default but frontend field is required`);
    if (!isInput && t.optional) problems.push(`${model}.${f}: optional in a response type (the backend always sends it)`);
    if (p.literal && JSON.stringify(p.literal) !== JSON.stringify(t.literal)) {
      problems.push(`${model}.${f}: literals backend=${p.literal} frontend=${t.literal}`);
    }
  }
}
console.log(`compared ${compared} models`);
if (problems.length) {
  console.log(problems.map((p) => `MISMATCH ${p}`).join("\n"));
  process.exit(1);
}
console.log("no mismatches");
