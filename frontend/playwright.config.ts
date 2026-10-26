import { defineConfig, devices } from "@playwright/test";

// Runs against an already running stack (docker compose up, or API + `npm run dev`)
// seeded with backend/scripts/seed_demo.py.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
