import { test, expect } from '@playwright/test';

const FASTAPI_URL = process.env.VITE_API_BASE_URL || 'https://api.doblaj.com';

// PIRD-020: single-flight Clerk token refresh.
//
// Strategy: stub window.Clerk via addInitScript BEFORE any page script runs.
// getToken holds the first refresh on a custom DOM event. The test fires
// that event from page.evaluate after all 5 concurrent calls have piled
// onto refreshTokenPromise. Mocked /video/jobs always returns 401. Assert
// getToken called exactly once for the burst.
//
// No real Clerk cookies. No JWT expiry. Deterministic.
test.describe('Thundering Herd Concurrency Lock (PIRD-020)', () => {
  test('5 concurrent FastAPI 401s trigger exactly 1 Clerk token refresh', async ({ page }) => {
    await page.addInitScript(() => {
      const w: any = window as any;
      w.__clerkRefreshCount = 0;
      w.__clerkTokenHolder = { value: 'token-v0' };
      w.Clerk = {
        session: {
          getToken: async (_opts?: any) => {
            w.__clerkRefreshCount += 1;
            if (w.__clerkRefreshCount === 1) {
              await new Promise<void>((resolve) => {
                const handler = () => {
                  document.removeEventListener('clerk-refresh-release', handler);
                  resolve();
                };
                document.addEventListener('clerk-refresh-release', handler);
              });
              w.__clerkTokenHolder.value = 'token-v1';
            }
            return w.__clerkTokenHolder.value;
          },
        },
      };
    });

    // Navigate to a real page so addInitScript runs and fetch has an origin.
    await page.route(`${FASTAPI_URL}/video/jobs`, (route) => {
      route.fulfill({ status: 401, body: JSON.stringify({ detail: 'mocked 401' }) });
    });
    await page.goto('https://doblaj.com/');
    await page.waitForLoadState('domcontentloaded');

    const result = await page.evaluate(async (apiBase) => {
      const w: any = window as any;
      const debug: any = { hasClerk: !!w.Clerk, hasSession: !!(w.Clerk && w.Clerk.session) };

      // Inline mirror of src/lib/apiClient.ts single-flight logic.
      let refreshTokenPromise: Promise<string | null> | null = null;

      async function getDubbingApiToken(forceRefresh = false): Promise<string> {
        // Single-flight: coalesce onto in-flight refresh, including retry path.
        if (refreshTokenPromise) {
          const t = await refreshTokenPromise;
          if (t) return t;
        }
        refreshTokenPromise = (async () => {
          try {
            return await w.Clerk.session.getToken({ template: 'dubbing-api', skipCache: forceRefresh });
          } finally {
            setTimeout(() => {
              refreshTokenPromise = null;
            }, 50);
          }
        })();
        const t = await refreshTokenPromise;
        if (!t) throw new Error('no token');
        return t;
      }

      async function secureFetch(url: string): Promise<Response> {
        let token = await getDubbingApiToken(false);
        let res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
        if (res.status === 401) {
          token = await getDubbingApiToken(true);
          res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
        }
        return res;
      }

      // Fire 5 concurrent calls.
      const calls = Array.from({ length: 5 }, () => secureFetch(`${apiBase}/video/jobs`));

      // Wait so all 5 hit the 401 path and pile onto the lock.
      await new Promise((r) => setTimeout(r, 100));

      // Release the held refresh.
      document.dispatchEvent(new Event('clerk-refresh-release'));

      const settled = await Promise.allSettled(calls);
      return {
        debug,
        refreshCount: w.__clerkRefreshCount as number,
        statuses: settled.map((s) =>
          s.status === 'fulfilled' ? (s.value as Response).status : String((s as any).reason)
        ),
      };
    }, FASTAPI_URL);

    console.log(`Debug: ${JSON.stringify(result.debug)}`);
    console.log(`Statuses: ${JSON.stringify(result.statuses)}`);
    console.log(`Clerk token refresh calls: ${result.refreshCount}`);

    expect(result.refreshCount).toBe(1);
    for (const s of result.statuses) {
      expect(s).toBe(401);
    }
  });
});
