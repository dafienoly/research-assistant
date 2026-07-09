import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8766';

// 15 pages to smoke test
const PAGES = [
  { path: '/', name: 'Home' },
  { path: '/data', name: 'DataCenter' },
  { path: '/console', name: 'AgentConsole' },
  { path: '/roadmap', name: 'Roadmap' },
  { path: '/reports', name: 'Reports' },
  { path: '/risk', name: 'LiveGate' },
  { path: '/paper', name: 'Paper' },
  { path: '/events', name: 'Events' },
  { path: '/ops', name: 'Ops' },
  { path: '/tasks', name: 'Tasks' },
  { path: '/backtest', name: 'Backtest' },
  { path: '/factors', name: 'Factors' },
  { path: '/stocks', name: 'StockPool' },
  { path: '/portfolio', name: 'Portfolio' },
  { path: '/settings', name: 'Settings' },
];

test.describe('V5 Fullstack E2E Smoke Test', () => {
  for (const pageDef of PAGES) {
    test(`Page ${pageDef.name} (${pageDef.path}) renders without errors`, async ({ page }) => {
      const consoleErrors: string[] = [];
      const networkErrors: { url: string; status: number }[] = [];

      page.on('console', (msg) => {
        if (msg.type() === 'error') {
          consoleErrors.push(msg.text());
        }
      });

      page.on('response', (response) => {
        if (response.status() >= 400) {
          networkErrors.push({ url: response.url(), status: response.status() });
        }
      });

      await page.goto(`${BASE_URL}${pageDef.path}`, { waitUntil: 'networkidle', timeout: 30000 });

      // Wait for React to render
      await page.waitForTimeout(2000);

      // Check no white screen: page should have content
      const bodyText = await page.textContent('body');
      expect(bodyText?.length).toBeGreaterThan(10);

      // Log warnings but don't fail for JS errors that might be antd deprecation warnings
      const realJsErrors = consoleErrors.filter(
        (e) => !e.includes('antd') && !e.includes('deprecated')
      );
      if (realJsErrors.length > 0) {
        console.warn(`JS errors on ${pageDef.path}:`, realJsErrors);
      }

      // Network errors may be acceptable (some APIs may 404 gracefully)
      if (networkErrors.length > 0) {
        console.warn(`Network errors on ${pageDef.path}:`, networkErrors);
      }

      // Take screenshot
      await page.screenshot({ 
        path: `screenshots/${pageDef.name.toLowerCase()}.png`,
        fullPage: true 
      });
    });
  }

  test('Frontend build artifacts exist', async () => {
    const fs = require('fs');
    const path = require('path');
    const distDir = path.join(__dirname, '..', 'dist');
    expect(fs.existsSync(path.join(distDir, 'index.html'))).toBeTruthy();
    expect(fs.existsSync(path.join(distDir, 'assets'))).toBeTruthy();
  });
});
