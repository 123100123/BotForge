#!/usr/bin/env node
// Checks the post-login redirect target (lib/session-expiry.ts: safeNextPath, postLoginPath,
// loginRedirectPath). The frontend has no test runner, so this runs on plain Node, which strips the
// TypeScript types itself (Node 22.18 or newer); a resolve hook maps the "@/..." imports to lib/.
// Usage (from frontend/):  npm run test:next-path   (or: node scripts/check-next-path.mjs)
import assert from "node:assert/strict";
import { register } from "node:module";

const root = new URL("../", import.meta.url).href;
const hooks = `
const ROOT = ${JSON.stringify(root)};
export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("@/")) return nextResolve(new URL(specifier.slice(2) + ".ts", ROOT).href, context);
  return nextResolve(specifier, context);
}`;
register(`data:text/javascript,${encodeURIComponent(hooks)}`);

const { safeNextPath, postLoginPath, loginRedirectPath } = await import("../lib/session-expiry.ts");

const ORIGIN = "https://app.example";
const BOT = "/bots/123e4567-e89b-12d3-a456-426614174000";
let checks = 0;

function accepts(raw, expected = raw) {
  assert.equal(safeNextPath(raw, ORIGIN), expected, `should accept ${JSON.stringify(raw)}`);
  checks++;
}

function refuses(raw) {
  assert.equal(safeNextPath(raw, ORIGIN), null, `should refuse ${JSON.stringify(raw)}`);
  checks++;
}

// ---- accepted: same-origin relative paths starting with a single "/"
accepts("/bots");
accepts("/");
accepts(`${BOT}?tab=data#runs`);
accepts(`${BOT}/x?q=%D8%A7%D9%84%D9%81`); // an encoded Persian query value
accepts("/bots/../bots/x", "/bots/x"); // dot segments come back normalized
accepts("/bots?next=//elsewhere.example"); // "//" inside the query is only text
accepts("/bots#//elsewhere.example");
accepts("/@evil.example"); // a path segment on this origin, not a host

// ---- refused: not a string or not a path
for (const raw of [null, undefined, "", "bots", "./bots", "?next=/bots", "#/bots"]) refuses(raw);

// ---- refused: absolute and protocol-relative URLs, script schemes
for (const raw of [
  "https://evil.example",
  "http://app.example/bots", // absolute even on this origin: only relative paths are accepted
  "//evil.example",
  "///evil.example",
  "//evil.example/bots",
  "javascript:alert(1)",
  "JavaScript:alert(1)",
  "/javascript:alert(1)",
  "vbscript:msgbox(1)",
  "data:text/html,x",
]) {
  refuses(raw);
}

// ---- refused: backslashes, control characters, spaces, non-ASCII
for (const raw of [
  "/\\evil.example",
  "\\\\evil.example",
  "/\\/evil.example",
  "/bots\\x",
  "/\t/evil.example",
  "/\n/evil.example",
  "/\r\n/evil.example",
  "/bots\u0000",
  "/bots\u007f",
  " /bots",
  "/bots ",
  "/ü",
  "/∕∕evil.example", // DIVISION SLASH
]) {
  refuses(raw);
}

// ---- refused: percent-encoded forms of the above (in any case, single or double encoded)
for (const raw of [
  "%2F%2Fevil.example",
  "/%2F/evil.example",
  "/%2f%2fevil.example",
  "/%5Cevil.example",
  "/%5cevil.example",
  "/%09/evil.example",
  "/%0a/evil.example",
  "/%00",
  "/%252F%252Fevil.example",
  "/%25252F%25252Fevil.example",
  "/%6A%61%76%61%73%63%72%69%70%74:alert(1)", // "javascript" encoded
  "/%E0%A4%A", // malformed
  "/%",
]) {
  refuses(raw);
}

// ---- refused: dot segments that the URL parser turns into "//host"
for (const raw of [
  "/..//evil.example",
  "/.//evil.example",
  "/%2e%2e//evil.example",
  "/%2E%2E//evil.example",
  "/x/../..//evil.example",
  "/.%2F%2Fevil.example", // decodes to "/.//evil.example"
  "/bots/..%2F..%2F%2Fevil.example",
]) {
  refuses(raw);
}

// ---- refused: auth pages (a loop) and over-long values
for (const raw of ["/login", "/signup", "/login?next=/bots", "/signup/", "/bots/../login"]) refuses(raw);
refuses("/" + "a".repeat(2048));
accepts("/" + "a".repeat(2047));

// ---- no origin (server rendering): nothing is accepted
assert.equal(safeNextPath("/bots", null), null);
checks++;

// ---- postLoginPath and loginRedirectPath
assert.equal(postLoginPath("?next=%2Fbots%2Fabc", ORIGIN), "/bots/abc");
assert.equal(postLoginPath("?next=https%3A%2F%2Fevil.example", ORIGIN), "/bots");
assert.equal(postLoginPath("?next=%2F%2Fevil.example", ORIGIN), "/bots");
assert.equal(postLoginPath("?next=%2F..%2F%2Fevil.example", ORIGIN), "/bots");
assert.equal(postLoginPath("?next=javascript%3Aalert(1)", ORIGIN), "/bots");
assert.equal(postLoginPath("", ORIGIN), "/bots");
const login = loginRedirectPath(`${BOT}?tab=data#runs`, ORIGIN);
assert.equal(login, `/login?next=${encodeURIComponent(`${BOT}?tab=data#runs`)}`);
assert.equal(postLoginPath(login.slice(login.indexOf("?")), ORIGIN), `${BOT}?tab=data#runs`); // round trip
assert.equal(loginRedirectPath("/login?next=%2Fbots", ORIGIN), "/login");
assert.equal(loginRedirectPath("//evil.example", ORIGIN), "/login");
assert.equal(loginRedirectPath("/bots", null), "/login");
checks += 12;

// ---- invariant over combinations of dangerous fragments: whatever is accepted stays on the origin
const parts = ["/", "\\", "%2F", "%2f", "%5C", "%2e", ".", "..", "%09", "@", ":", "evil.example", "%252F", "?", "#", "javascript:"];
let combinations = 0;
function walk(prefix, depth) {
  if (depth === 0) return;
  for (const part of parts) {
    const raw = prefix + part;
    combinations++;
    const result = safeNextPath(raw, ORIGIN);
    if (result !== null) {
      const url = new URL(result, ORIGIN);
      assert.equal(url.origin, ORIGIN, `left the origin: ${JSON.stringify(raw)} -> ${result}`);
      assert.ok(result.startsWith("/") && !result.startsWith("//"), `not a single-slash path: ${JSON.stringify(raw)}`);
      assert.ok(!/[\\\u0000-\u001f\u007f]/.test(result), `unsafe character: ${JSON.stringify(raw)}`);
      assert.ok(!url.pathname.startsWith("//"), `protocol-relative path: ${JSON.stringify(raw)}`);
      for (let decoded = result, i = 0; i < 3; i++) {
        decoded = decodeURIComponent(decoded);
        assert.ok(!decoded.startsWith("//") && !decoded.includes("\\"), `decodes off the origin: ${raw}`);
      }
    }
    walk(raw, depth - 1);
  }
}
walk("/", 4);
walk("", 3);

console.log(`check-next-path: ${checks} checks and ${combinations} combinations passed`);
