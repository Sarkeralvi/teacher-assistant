import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const baseURL = process.env.E2E_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:3000";
const installedChrome = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const chromiumExecutable =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ??
  (process.platform === "win32" && existsSync(installedChrome) ? installedChrome : undefined);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: {
    timeout: 15_000,
  },
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: process.env.E2E_VIDEO === "true" ? "retain-on-failure" : "off",
    launchOptions: chromiumExecutable ? { executablePath: chromiumExecutable } : undefined,
  },
});
