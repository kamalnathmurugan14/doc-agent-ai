import { defineConfig } from "@playwright/test";

// Starts a throw-away backend (hashing embedder, temp docs) and the Vite dev server.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://localhost:5173",
    launchOptions: { executablePath: process.env.CHROMIUM_PATH || undefined },
  },
  webServer: [
    {
      command: "python scripts/e2e_server.py",
      cwd: "../backend",
      url: "http://localhost:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    { command: "npm run dev", url: "http://localhost:5173", reuseExistingServer: !process.env.CI },
  ],
});
