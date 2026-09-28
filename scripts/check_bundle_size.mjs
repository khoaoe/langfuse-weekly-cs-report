// Fails when the JavaScript the SPA loads up front exceeds the gzip budget.
// Counts the entry script and its modulepreload links from the built
// index.html; lazily imported chunks are not part of the first load.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const BUDGET_BYTES = 250 * 1000;
const root = "src/weekly_cs_report/static/spa";
const html = readFileSync(join(root, "index.html"), "utf8");
const scripts = [
  ...html.matchAll(/<script[^>]*type="module"[^>]*src="\/([^"]+\.js)"/g),
  ...html.matchAll(/<link[^>]*rel="modulepreload"[^>]*href="\/([^"]+\.js)"/g),
].map((match) => match[1]);
if (scripts.length === 0) {
  throw new Error("No entry script found in the built index.html.");
}
let total = 0;
for (const script of scripts) {
  const size = gzipSync(readFileSync(join(root, script)), { level: 9 }).length;
  total += size;
  console.log(`${script}: ${(size / 1000).toFixed(1)} kB gzip`);
}
console.log(`initial JS: ${(total / 1000).toFixed(1)} kB gzip (budget ${BUDGET_BYTES / 1000} kB)`);
if (total > BUDGET_BYTES) {
  process.exitCode = 1;
}
