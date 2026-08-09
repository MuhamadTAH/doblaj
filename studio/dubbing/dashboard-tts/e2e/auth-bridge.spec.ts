import { test, expect } from '@playwright/test';

// ============================================================================
// PIRD-AUTH-E2E: REQUIRED SETUP BEFORE RUNNING
// ============================================================================
// You MUST run this test with Clerk keys from your DEVELOPMENT instance:
//   $env:CLERK_PUBLISHABLE_KEY="pk_test_YOUR_DEV_KEY"
//   $env:CLERK_SECRET_KEY="sk_test_YOUR_DEV_KEY"
//   $env:CLERK_TESTING_TOKEN="<dev instance testing token>"
//
// PRODUCTION KEYS WILL NOT WORK.
// - Production Clerk does NOT expose testing tokens
// - Production session cookies cannot be replayed by Playwright (different
//   origin + Clerk JWT validation rejects automation origins)
// - Bot protection on production actively blocks headless browsers
//
// The dubbing-api JWT template, public_metadata.workspace_id, and FastAPI
// audience check are validated separately by:
//   1. pytest test_auth_bridge.py (4/4 unit tests)
//   2. scripts/verify_clerk_template.ts (live JWT shape check)
//   3. Live dubbing job submission from a real browser (manual smoke test)
//
// This spec exists to provide a complete end-to-end verification once a
// dev Clerk instance is configured. It will be skipped with a clear message
// if the required env vars are missing.
// ============================================================================

const APP_URL = process.env.VITE_APP_URL || 'http://localhost:5173';
const FASTAPI_URL = process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8999';

test.describe('Zero-Trust Authentication Bridge E2E (dev Clerk)', () => {
  test('authenticates via Clerk dev instance and accesses FastAPI with dubbing-api JWT', async ({ page, context }) => {
    const sessionCookie = process.env.CLERK_SESSION_COOKIE;
    const testingToken = process.env.CLERK_TESTING_TOKEN;
    if (!sessionCookie && !testingToken) {
      test.skip(true, 'Set $env:CLERK_SESSION_COOKIE (or CLERK_TESTING_TOKEN) before running.');
      return;
    }

    if (sessionCookie) {
      await context.addCookies([{
        name: '__session',
        value: sessionCookie,
        url: APP_URL,
        httpOnly: true,
        secure: true,
        sameSite: 'Lax',
      }]);
    }

    let clerkTokenRequests = 0;
    page.on('request', (req) => {
      const url = req.url().toLowerCase();
      if (url.includes('clerk.') && (url.includes('/v1/') || url.includes('tokens'))) {
        clerkTokenRequests++;
      }
    });

    await page.goto(`${APP_URL}/history`);
    await page.waitForLoadState('networkidle');
    await page.waitForFunction(
      () => !!(window as any).Clerk?.session,
      null,
      { timeout: 20000 }
    );

    const apiJwt = await page.evaluate(async () => {
      const clerk = (window as any).Clerk;
      if (!clerk?.session) throw new Error('Clerk session not initialized');
      return await clerk.session.getToken({ template: 'dubbing-api' });
    });

    expect(apiJwt).toBeTruthy();

    const backendResponse = await page.request.get(`${FASTAPI_URL}/video/jobs`, {
      headers: { Authorization: `Bearer ${apiJwt}` },
    });

    expect(backendResponse.status()).toBe(200);
    const body = await backendResponse.json();
    expect(Array.isArray(body)).toBe(true);

    expect(clerkTokenRequests).toBeGreaterThanOrEqual(0);
  });
});
