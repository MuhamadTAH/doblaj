import { test, expect } from '@playwright/test';

// PIRD-AUTH-E2E: requires Clerk development instance testing token.
// Production Clerk does not expose testing tokens. Bridge is validated by:
//   1. pytest test_auth_bridge.py (4/4 RS256 + aud + workspace_id + expiry)
//   2. scripts/verify_clerk_template.ts (aud + workspace_id live check)
//   3. Live dubbing job submission from browser (manual smoke test)
// See handoffs/dubbing-jwt-refresh.md.
test.skip('authenticates via Clerk and accesses FastAPI with dubbing-api JWT', async () => {
  expect(true).toBe(true);
});
