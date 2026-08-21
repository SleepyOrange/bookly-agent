// @ts-check
const { defineConfig, devices } = require('@playwright/test');
const path = require('path');

const PORT = 8300;
const REPO_ROOT = path.resolve(__dirname, '..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python3');

module.exports = defineConfig({
  testDir: './specs',
  fullyParallel: false, // shared stub server / sessions dict -- keep it simple and serial
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: `"${PYTHON}" "${path.join(REPO_ROOT, 'tests', 'frontend_stub_server.py')}" ${PORT}`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 15000,
  },
});
