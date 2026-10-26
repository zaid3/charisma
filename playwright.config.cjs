const { defineConfig, devices } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests/browser', fullyParallel: false, workers: 1, retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:8787', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone SE'], defaultBrowserType: 'chromium' } }
  ],
  webServer: { command: 'python3 -m charisma serve --origin http://127.0.0.1:8787 --site-key browser-fixture-key --database /tmp/charisma-browser-fixture.sqlite3',
    env: { CHARISMA_ADMIN_TOKEN: 'browser-test-token-not-a-real-secret' },
    url: 'http://127.0.0.1:8787/health', reuseExistingServer: !process.env.CI }
});
