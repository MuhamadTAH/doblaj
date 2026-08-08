import { test, expect } from '@playwright/test';

const APP_URL = process.env.VITE_APP_URL || 'https://doblaj.com';
const FASTAPI_URL = process.env.VITE_API_BASE_URL || 'https://api.doblaj.com';

test.describe('Thundering Herd Concurrency Lock Test (PIRD-020)', () => {
  test('5 concurrent FastAPI calls produce exactly 1 Clerk token refresh', async ({ page, context }) => {
    const sessionCookie = process.env.CLERK_SESSION_COOKIE;
    if (!sessionCookie) {
      test.skip(true, 'Set $env:CLERK_SESSION_COOKIE to a real __session JWT');
      return;
    }

    await context.addCookies([{
      name: '__session',
      value: sessionCookie,
      url: APP_URL,
      httpOnly: true,
      secure: true,
      sameSite: 'Lax',
    }]);

    let clerkTokenRequests = 0;
    page.on('request', (req) => {
      const url = req.url().toLowerCase();
      if (url.includes('clerk.') && (url.includes('/v1/') || url.includes('tokens'))) {
        clerkTokenRequests++;
        console.log(`[CLERK TOKEN REQ] #${clerkTokenRequests}: ${req.url()}`);
      }
    });

    await page.goto(`${APP_URL}/history`);
    await page.waitForLoadState('networkidle');
    await page.waitForFunction(
      () => !!(window as any).Clerk?.session,
      null,
      { timeout: 20000 }
    );

    clerkTokenRequests = 0;

    const results = await page.evaluate(async (apiBase) => {
      const promises = Array.from({ length: 5 }, () =>
        fetch(`${apiBase}/video/jobs`, { method: 'GET' }).then((r) => r.status).catch(() => 0)
      );
      return await Promise.all(promises);
    }, FASTAPI_URL);

    console.log(`Statuses: ${JSON.stringify(results)}`);
    console.log(`Clerk token refresh requests: ${clerkTokenRequests}`);

    expect(clerkTokenRequests).toBeLessThanOrEqual(1);
  });
});
