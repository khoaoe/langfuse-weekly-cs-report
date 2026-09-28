import { defineConfig, devices } from "@playwright/test";

const BASE_URL = "http://127.0.0.1:18765";

/**
 * Two runs cover the contract: light and dark at desktop width. The dashboard
 * is desktop only (1280–2560px); specs that need another width set it.
 * The server is the real FastAPI application with a fixed snapshot, so the
 * security headers, `/assets` route and SPA document under test are the ones
 * that ship.
 */
export default defineConfig({
  testDir: "./frontend/e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  webServer: {
    command: ".venv/bin/python scripts/e2e_server.py",
    url: `${BASE_URL}/healthz`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    {
      name: "desktop-light",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        colorScheme: "light",
      },
    },
    {
      name: "desktop-dark",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        colorScheme: "dark",
      },
    },
  ],
});
