import { defineConfig, devices } from "@playwright/test";

/** Start the mock frontend separately; tests never start or mutate a real backend. */
export default defineConfig({
  testDir: "./tests/ui",
  outputDir: "./test-results/workflow",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  retries: 0,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    channel: "msedge",
    baseURL: process.env.UI_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
