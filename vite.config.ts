import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  root: "frontend",
  build: {
    outDir: "../src/weekly_cs_report/static/spa",
    emptyOutDir: true,
    sourcemap: false,
    assetsInlineLimit: 0,
  },
  test: {
    environment: "jsdom",
    // Full-screen jsdom renders run ~4.5 s under coverage on CI runners.
    testTimeout: 15_000,
    globals: true,
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      // The entry point only mounts the tree; it is exercised by Playwright,
      // not by jsdom, so counting it here would measure the wrong thing.
      // The A/B section ships behind AB_TEST_ENABLED = false and is never
      // rendered; count it again when the flag is turned on.
      exclude: [
        "src/main.tsx",
        "src/components/AbTestSection.tsx",
        "src/lib/ab-test-*.ts",
      ],
      thresholds: {
        branches: 80,
        functions: 80,
        lines: 80,
        statements: 80,
      },
    },
  },
});
