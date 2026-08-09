import { test, expect } from '@playwright/test';

const APP_URL = process.env.VITE_APP_URL || 'https://doblaj.com';
const FASTAPI_URL = process.env.VITE_API_BASE_URL || 'https://api.doblaj.com';

// PIRD-020: single-flight Clerk token refresh.
// Strategy: inject real session cookie so Clerk.session is initialized, then
// intercept the FastAPI /video/jobs endpoint with route.fulfill(401). When
// apiClient.ts gets 401s on five concurrent calls, refreshTokenPromise must
// ensure exactly ONE call to Clerk's token endpoint, not five.
test.describe('Thundering Herd Concurrency Lock (PIRD-020)', () => {
  test('5 concurrent FastAPI 401s trigger exactly 1 Clerk token refresh', async ({ page, context }) => {
    const sessionCookie = process.env.CLERK_SESSION_COOKIE;
    if (!sessionCookie) {
      test.skip(true, 'Set $env:CLERK_SESSION_COOKIE to a real __session JWT before running.');
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

    // Boot the page so window.Clerk.session exists before we fire requests
    await page.goto(`${APP_URL}/history`);
    await page.waitForLoadState('networkidle');
    await page.waitForFunction(
      () => !!(window as any).Clerk?.session,
      null,
      { timeout: 20000 }
    );

    // Intercept ALL FastAPI requests and force 401 — this exercises the
    // apiClient.ts refresh-on-401 path.
    await page.route(`${FASTAPI_URL}/video/jobs`, (route) => {
      route.fulfill({ status: 401, body: JSON.stringify({ detail: 'mocked 401' }) });
    });

    clerkTokenRequests = 0;

    // Fire 5 concurrent calls. apiClient's interceptor sees 401, triggers
    // refreshTokenPromise once for the whole burst, retries with new token.
    const results = await page.evaluate(async (apiBase) => {
      const promises = Array.from({ length: 5 }, () =>
        fetch(`${apiBase}/video/jobs`, { method: 'GET' })
          .then((r) => r.status)
          .catch(() => 0)
      );
      return await Promise.all(promises);
    }, FASTAPI_URL);

    console.log(`Statuses: ${JSON.stringify(results)}`);
    console.log(`Clerk token refresh requests: ${clerkTokenRequests}`);

    for (const s of results) expect(s).toBe(401);
    expect(clerkTokenRequests).toBe(1);
  });
});
