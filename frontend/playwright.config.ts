import { defineConfig } from '@playwright/test';

const TEST_PORT = 5188;

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  expect: {
    timeout: 5000,
  },
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://localhost:${TEST_PORT}`,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'desktop',
      use: {
        viewport: { width: 1280, height: 800 },
      },
    },
    {
      name: 'tablet',
      use: {
        viewport: { width: 768, height: 1024 },
      },
    },
    {
      name: 'mobile',
      use: {
        viewport: { width: 375, height: 667 },
      },
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${TEST_PORT} --strictPort`,
    port: TEST_PORT,
    reuseExistingServer: false,
    timeout: 120000,
  },
});
