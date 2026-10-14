import { defineConfig, devices } from '@playwright/test';
import { readFileSync } from 'node:fs';
if (process.env.HOMEHQ_LOCAL_ENV_FILE) {
  const metadata = JSON.parse(readFileSync(process.env.HOMEHQ_LOCAL_ENV_FILE, 'utf8'));
  process.env.HOMEHQ_TEST_URL = metadata.env.API_URL;
  process.env.HOMEHQ_TEST_KEY = metadata.env.PUBLISHABLE_KEY;
}
export default defineConfig({
  testDir: './tests/e2e', timeout: 45_000, expect: { timeout: 12_000 },
  fullyParallel: false, workers: 1,
  use: { baseURL: process.env.HOMEHQ_WEB_URL || 'http://127.0.0.1:5184', trace: 'retain-on-failure', ...devices['Desktop Chrome'] },
  reporter: 'list',
});
