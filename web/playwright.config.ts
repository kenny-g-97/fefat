import { defineConfig, devices } from "@playwright/test"
import { E2E_PASSWORD } from "./e2e/support/password.ts"

// Ports beside `just dev`'s 8765 and 5173, so that both can run at once.
const SERVER_PORT = 8766
const DEV_SERVER_PORT = 5174
const desktop = {
  ...devices["Desktop Chrome"],
  viewport: { width: 1280, height: 800 },
}

/** The UI harness of step 4.3 (`just e2e`): every spec against the built app that `fefat up`
 * serves on a seeded temporary home, and the login once more through the Vite dev server's
 * proxy, at desktop size alone (D-54). */
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  retries: 0,
  forbidOnly: true,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { screenshot: "only-on-failure", trace: "retain-on-failure" },
  projects: [
    {
      name: "desktop",
      use: { ...desktop, baseURL: `http://127.0.0.1:${SERVER_PORT}` },
    },
    {
      name: "dev-proxy",
      testMatch: "login.spec.ts",
      use: { ...desktop, baseURL: `http://localhost:${DEV_SERVER_PORT}` },
    },
  ],
  webServer: [
    {
      command: "uv run python scripts/e2e_server.py",
      cwd: "..",
      url: `http://127.0.0.1:${SERVER_PORT}/v1/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
      env: {
        FEFAT_E2E_PORT: String(SERVER_PORT),
        FEFAT_E2E_PASSWORD: E2E_PASSWORD,
        PYTHONUTF8: "1",
      },
    },
    {
      command: `pnpm exec vite --port ${DEV_SERVER_PORT} --strictPort`,
      url: `http://localhost:${DEV_SERVER_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { FEFAT_SERVER_PORT: String(SERVER_PORT) },
    },
  ],
})
