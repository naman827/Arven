import { defineConfig, devices } from '@playwright/test'

// E2E runs the real frontend against the real backend app wired to scripted fake providers
// (backend/tests/e2e_server.py). No API keys or paid calls are used.
export default defineConfig({
  testDir: './tests/e2e',
  outputDir: './e2e-output',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:5174', trace: 'retain-on-failure', colorScheme: 'dark' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      command: process.platform === 'win32' ? '..\\backend\\.venv\\Scripts\\python.exe -m tests.e2e_server' : '../backend/.venv/bin/python -m tests.e2e_server',
      cwd: '../backend',
      url: 'http://127.0.0.1:8001/api/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm run dev:e2e',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
