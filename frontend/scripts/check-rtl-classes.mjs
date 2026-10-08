#!/usr/bin/env node
// Fails (exit 1) on physical-direction Tailwind classes in app/ and components/. The UI is right-to-left, so
// use logical utilities: ms-/me-/ps-/pe-, start-/end-, text-start/text-end, rounded-s/e, border-s/e.
// A line that is truly symmetric (for example `left-1/2 -translate-x-1/2` centering) is allowed when it
// carries the marker `rtl-ok` in a comment or string. Usage (from frontend/): npm run check:rtl
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const DIRS = ["app", "components"];
const EXT = /\.(tsx|ts|jsx|js|css)$/;

// Each pattern matches inside a class token: preceded by start, whitespace, quote, backtick or a variant colon.
const PREFIX = String.raw`(?<![\w-])(?:[\w\[\]=&>*:()-]+:)*-?`;
const PATTERNS = [
  [new RegExp(`${PREFIX}(?:ml|mr|pl|pr)-`), "ml-/mr-/pl-/pr- (use ms-/me-/ps-/pe-)"],
  [new RegExp(`${PREFIX}(?:left|right)-(?:\\d|\\[|px|full|auto|1/2)`), "left-/right- (use start-/end-)"],
  [new RegExp(`${PREFIX}text-(?:left|right)(?![\\w-])`), "text-left/text-right (use text-start/text-end)"],
  [new RegExp(`${PREFIX}rounded-(?:l|r|tl|tr|bl|br)(?:-|(?![\\w-]))`), "rounded-l/r/tl/tr/bl/br (use rounded-s/e/ss/se/es/ee)"],
  [new RegExp(`${PREFIX}border-(?:l|r)(?![\\w])`), "border-l/border-r (use border-s/border-e)"],
  [new RegExp(`${PREFIX}(?:float|clear)-(?:left|right)`), "float/clear left/right (use start/end)"],
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (name === "node_modules" || name === ".next") continue;
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (EXT.test(name)) yield p;
  }
}

let bad = 0;
for (const d of DIRS) {
  for (const file of walk(join(root, d))) {
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      if (line.includes("rtl-ok")) return;
      for (const [re, why] of PATTERNS) {
        const m = re.exec(line);
        if (m) {
          bad++;
          console.error(`${relative(root, file)}:${i + 1}: ${m[0]}  <- ${why}`);
        }
      }
    });
  }
}
if (bad) {
  console.error(`\n${bad} physical-direction class(es). Use logical utilities or mark a symmetric line with "rtl-ok".`);
  process.exit(1);
}
console.log("check:rtl ok: no physical-direction Tailwind classes.");
