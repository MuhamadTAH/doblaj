import { convexTest } from "convex-test";
import { describe, it, expect } from "vitest";
import schema from "./schema";
import { api } from "./_generated/api";

const modules = import.meta.glob("./**/*.*s");
const INTERNAL_API_KEY = "doblaj_dev_secret_key_change_in_prod";

describe("Defensive Sweeper Convex Range Scanning, Expiry, & DLQ Suite", () => {
  it("uses compound index [status, createdAt] to fetch only charges older than 15m up to bounded limit", async () => {
    const t = convexTest(schema, modules);

    const workspaceId = await t.run(async (ctx) => {
      return await ctx.db.insert("workspaces", {
        name: "Sweeper Index Workspace",
        legacyId: "ws_sweeper_index_001",
        dubbingMinutes: 0,
        plan: "pro",
      });
    });

    const nowMs = Date.now();

    // 1. Insert 3 fresh pending charges (created 2 minutes ago)
    for (let i = 1; i <= 3; i++) {
      await t.run(async (ctx) => {
        await ctx.db.insert("expectedCharges", {
          referenceId: `ref_fresh_${i}`,
          workspaceId,
          amount: 30000,
          currency: "IQD",
          minutesGranted: 15,
          tier: "pro",
          status: "pending",
          createdAt: new Date(nowMs - 2 * 60 * 1000).toISOString(),
        });
      });
    }

    // 2. Insert 5 eligible pending charges (created 25 minutes ago)
    for (let i = 1; i <= 5; i++) {
      await t.run(async (ctx) => {
        await ctx.db.insert("expectedCharges", {
          referenceId: `ref_eligible_${i}`,
          workspaceId,
          amount: 30000,
          currency: "IQD",
          minutesGranted: 15,
          tier: "pro",
          status: "pending",
          createdAt: new Date(nowMs - 25 * 60 * 1000).toISOString(),
        });
      });
    }

    // 3. Query pending charges for sweep older than 15 minutes with limit 50
    const sweepCandidates = await t.query(api.sweeper.getPendingChargesForSweep, {
      olderThanMinutes: 15,
      limit: 50,
      __internalApiKey: INTERNAL_API_KEY,
    });

    // Must return strictly the 5 eligible charges, completely skipping the 3 fresh ones
    expect(sweepCandidates.length).toBe(5);
    for (const c of sweepCandidates) {
      expect(c.referenceId).toContain("ref_eligible");
    }

    // 4. Test bounded limit (e.g. limit: 2)
    const boundedCandidates = await t.query(api.sweeper.getPendingChargesForSweep, {
      olderThanMinutes: 15,
      limit: 2,
      __internalApiKey: INTERNAL_API_KEY,
    });
    expect(boundedCandidates.length).toBe(2);
  });

  it("refuses to expire charges when circuit breaker is unhealthy (Systemic Circuit Awareness)", async () => {
    const t = convexTest(schema, modules);

    const workspaceId = await t.run(async (ctx) => {
      return await ctx.db.insert("workspaces", {
        name: "Circuit Unhealthy Workspace",
        legacyId: "ws_unhealthy_001",
        dubbingMinutes: 0,
        plan: "pro",
      });
    });

    const nowMs = Date.now();
    // 50-hour-old charge
    await t.run(async (ctx) => {
      await ctx.db.insert("expectedCharges", {
        referenceId: "ref_outage_charge_001",
        workspaceId,
        amount: 30000,
        currency: "IQD",
        minutesGranted: 15,
        tier: "pro",
        status: "pending",
        createdAt: new Date(nowMs - 50 * 60 * 60 * 1000).toISOString(),
      });
    });

    // Run expire with isCircuitHealthy: false (e.g. Wayl 503 outage all weekend)
    const frozenRes = await t.mutation(api.sweeper.expireStalePendingCharges, {
      maxAgeHours: 48,
      limit: 100,
      isCircuitHealthy: false,
      __internalApiKey: INTERNAL_API_KEY,
    });

    expect(frozenRes.status).toBe("frozen_circuit_unhealthy");
    expect(frozenRes.expiredCount).toBe(0);

    // Charge MUST remain in "pending" status (never mutated while blind)
    const charge = await t.run(async (ctx) => {
      return await ctx.db
        .query("expectedCharges")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", "ref_outage_charge_001"))
        .unique();
    });
    expect(charge?.status).toBe("pending");
  });

  it("routes expired charges to manualReviewQueue (DLQ) and auto-resolves on late webhook arrival", async () => {
    const t = convexTest(schema, modules);

    const workspaceId = await t.run(async (ctx) => {
      return await ctx.db.insert("workspaces", {
        name: "DLQ Recovery Workspace",
        legacyId: "ws_dlq_recovery_001",
        dubbingMinutes: 0,
        plan: "pro",
      });
    });

    const nowMs = Date.now();
    const refId = "ref_dlq_late_arrival_001";

    // 1. Insert 50-hour-old pending charge
    await t.run(async (ctx) => {
      await ctx.db.insert("expectedCharges", {
        referenceId: refId,
        workspaceId,
        amount: 30000,
        currency: "IQD",
        minutesGranted: 15,
        tier: "pro",
        status: "pending",
        createdAt: new Date(nowMs - 50 * 60 * 60 * 1000).toISOString(),
      });
    });

    // 2. Health is OK, expire job runs
    const expiryRes = await t.mutation(api.sweeper.expireStalePendingCharges, {
      maxAgeHours: 48,
      limit: 100,
      isCircuitHealthy: true,
      __internalApiKey: INTERNAL_API_KEY,
    });

    expect(expiryRes.expiredCount).toBe(1);
    expect(expiryRes.queuedForReviewCount).toBe(1);

    // 3. Verify record routed to manualReviewQueue (DLQ)
    const dlqItems = await t.run(async (ctx) => {
      return await ctx.db
        .query("manualReviewQueue")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", refId))
        .collect();
    });
    expect(dlqItems.length).toBe(1);
    expect(dlqItems[0].status).toBe("pending_review");
    expect(dlqItems[0].reason).toBe("stale_pending_48h_unverified");

    // 4. Late-arrival webhook arrives on Monday morning
    const webhookRes = await t.mutation(api.payments.recordAndProcessWaylEvent, {
      referenceId: refId,
      amount: 30000,
      currency: "IQD",
      rawPayload: JSON.stringify({ referenceId: refId, status: "Complete", amount: 30000 }),
      __internalApiKey: INTERNAL_API_KEY,
    });

    expect(webhookRes.status).toBe("processed");

    // 5. Verify customer received their 15 minutes
    const ws = await t.run(async (ctx) => {
      return await ctx.db.get(workspaceId);
    });
    expect(ws?.dubbingMinutes).toBe(15);

    // 6. Verify DLQ item was automatically resolved
    const resolvedDlq = await t.run(async (ctx) => {
      return await ctx.db
        .query("manualReviewQueue")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", refId))
        .unique();
    });
    expect(resolvedDlq?.status).toBe("resolved");
    expect(resolvedDlq?.lastKnownWaylStatus).toBe("Complete");
  });
});
