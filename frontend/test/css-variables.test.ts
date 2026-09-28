import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..", "src");

function cssFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      return cssFiles(path);
    }
    return entry.name.endsWith(".css") ? [path] : [];
  });
}

describe("CSS custom properties", () => {
  it("never reads a variable no stylesheet defines", () => {
    // An undefined var() makes the whole declaration invalid at computed-value
    // time, so the style silently disappears instead of failing the build.
    const sources = cssFiles(SRC).map((path) => ({
      path,
      text: readFileSync(path, "utf8"),
    }));
    const defined = new Set(
      sources.flatMap(({ text }) =>
        [...text.matchAll(/(--[\w-]+)\s*:/g)].map((match) => match[1]),
      ),
    );
    const undefinedUses = sources.flatMap(({ path, text }) =>
      [...text.matchAll(/var\(\s*(--[\w-]+)/g)]
        .map((match) => match[1])
        .filter((name) => !defined.has(name))
        .map((name) => `${path.slice(SRC.length + 1)}: ${name}`),
    );

    expect(undefinedUses).toEqual([]);
  });
});
