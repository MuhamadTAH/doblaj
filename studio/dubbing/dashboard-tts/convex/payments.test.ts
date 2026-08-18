import { convexTest } from "convex-test";
import { describe, it, expect, beforeEach } from "vitest";
import schema from "./schema";
import { api } from "./_generated/api";

const modules = import.meta.glob("./**/*.*s");
const INTERNAL_API_KEY = "doblaj_dev_secret_key_change_in_prod";

describe("Convex OCC Payment Security & Concurrency Test Suite", () => {
  // =========================================================================
  // Scenario 2: The Concurrency Bloodbath (OCC Stress Test)
  // =========================================================================
  it("Test 2.1: The 100-Clone Attack fires 100 simultaneous calls directly at payments:recordAndProcessWaylEvent", async () => {
    const t = convexTest(schema, modules);

    // 1. Setup real workspace record
    const workspaceId = await t.run(async (ctx) => {
      return await ctx.db.insert("workspaces", {
        legacyId: "ws_stress_occ_001",
        name: "OCC Stress Workspace",
        dubbingMinutes: 0,
        plan: "pro",
        status: "ACTIVE",
      });
    });

    const refId = "ref_100_clone_live_convex";
    const amount = 30000;
    const currency = "IQD";
    const minutesGranted = 15;

    // 2. Record expected charge before webhook arrives
    await t.mutation(api.payments.recordExpectedCharge, {
      referenceId: refId,
      workspaceId: "ws_stress_occ_001",
      amount,
      currency,
      minutesGranted,
      tier: "pro",
      __internalApiKey: INTERNAL_API_KEY,
    });

    const rawPayload = JSON.stringify({
      referenceId: refId,
      status: "Complete",
      amount,
      currency,
    });

    // 3. Fire 100 simultaneous concurrent mutations at the exact same millisecond using Promise.all
    const promises = Array.from({ length: 100 }, () =>
      t.mutation(api.payments.recordAndProcessWaylEvent, {
        referenceId: refId,
        amount,
        currency,
        rawPayload,
        __internalApiKey: INTERNAL_API_KEY,
      })
    );

    const results = await Promise.all(promises);

    // 4. Assertion 4: All 100 calls returned cleanly without throwing 500s or crashing
    const processed = results.filter((r) => r.status === "processed");
    const alreadyProcessed = results.filter((r) => r.status === "already_processed");

    expect(processed.length).toBe(1);
    expect(alreadyProcessed.length).toBe(99);

    // 5. Assertion 1: Exactly 1 row in transactions table
    const txRecords = await t.run(async (ctx) => {
      return await ctx.db
        .query("transactions")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", refId))
        .collect();
    });
    expect(txRecords.length).toBe(1);
    expect(txRecords[0].status).toBe("complete");
    expect(txRecords[0].minutesAdded).toBe(15);

    // 6. Assertion 2: Exactly 1 row in webhookEvents table (Read-First Zero-Cost Idempotency)
    const webhookEvents = await t.run(async (ctx) => {
      return await ctx.db
        .query("webhookEvents")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", refId))
        .collect();
    });
    expect(webhookEvents.length).toBe(1);

    // 7. Assertion 3: Exactly 1 row in ledger table for this referenceId
    const ledgerRows = await t.run(async (ctx) => {
      return await ctx.db
        .query("ledger")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", refId))
        .collect();
    });
    expect(ledgerRows.length).toBe(1);
    expect(ledgerRows[0].delta).toBe(15);
    expect(ledgerRows[0].resultingBalance).toBe(15);
    expect(ledgerRows[0].type).toBe("purchase");

    // 8. Assert workspace balance credited exactly ONCE
    const ws = await t.run(async (ctx) => {
      return await ctx.db.get(workspaceId);
    });
    expect(ws?.dubbingMinutes).toBe(15);
  });

  // =========================================================================
  // Scenario 4: The Sweeper vs. Webhook Collision
  // =========================================================================
  it("Test 4.1: The Dead-Heat Race fires Sweeper and Webhook concurrently for the exact same transaction", async () => {
    const t = convexTest(schema, modules);

    const workspaceId = await t.run(async (ctx) => {
      return await ctx.db.insert("workspaces", {
        legacyId: "ws_sweeper_race_001",
        name: "Sweeper Race Workspace",
        dubbingMinutes: 10,
        plan: "pro",
        status: "ACTIVE",
      });
    });

    const refId = "ref_dead_heat_convex_001";
    const amount = 15000;
    const currency = "IQD";
    const minutesGranted = 5;

    await t.mutation(api.payments.recordExpectedCharge, {
      referenceId: refId,
      workspaceId: "ws_sweeper_race_001",
      amount,
      currency,
      minutesGranted,
      tier: "starter",
      __internalApiKey: INTERNAL_API_KEY,
    });

    const payload = JSON.stringify({
      referenceId: refId,
      status: "Complete",
      amount,
      currency,
    });

    // Fire Sweeper task and Webhook handler task simultaneously
    const webhookTask = t.mutation(api.payments.recordAndProcessWaylEvent, {
      referenceId: refId,
      amount,
      currency,
      rawPayload: payload,
      __internalApiKey: INTERNAL_API_KEY,
    });

    const sweeperTask = t.mutation(api.payments.recordAndProcessWaylEvent, {
      referenceId: refId,
      amount,
      currency,
      rawPayload: payload,
      __internalApiKey: INTERNAL_API_KEY,
    });

    const [whRes, swRes] = await Promise.all([webhookTask, sweeperTask]);

    const statuses = [whRes.status, swRes.status];
    expect(statuses).toContain("processed");
    expect(statuses).toContain("already_processed");

    // Verify balance increased by +5 exactly ONCE (from 10 to 15)
    const ws = await t.run(async (ctx) => {
      return await ctx.db.get(workspaceId);
    });
    expect(ws?.dubbingMinutes).toBe(15);

    const ledgerRows = await t.run(async (ctx) => {
      return await ctx.db
        .query("ledger")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", refId))
        .collect();
    });
    expect(ledgerRows.length).toBe(1);
  });

  // =========================================================================
  // Scenario 3: Financial Integrity & Ledger Drift
  // =========================================================================
  it("Test 3.1: Anomaly detection on amount mismatch logs to securityAlerts and returns flagged", async () => {
    const t = convexTest(schema, modules);

    const workspaceId = await t.run(async (ctx) => {
      return await ctx.db.insert("workspaces", {
        name: "Salami Workspace",
        legacyId: "ws_salami_001",
        dubbingMinutes: 0,
        plan: "pro",
      });
    });

    const refId = "ref_salami_mismatch_001";
    // Expected is 30,000 IQD
    await t.mutation(api.payments.recordExpectedCharge, {
      referenceId: refId,
      workspaceId: "ws_salami_001",
      amount: 30000,
      currency: "IQD",
      minutesGranted: 15,
      tier: "pro",
      __internalApiKey: INTERNAL_API_KEY,
    });

    // Attacker modifies webhook payload to send 25,000 IQD
    const result = await t.mutation(api.payments.recordAndProcessWaylEvent, {
      referenceId: refId,
      amount: 25000,
      currency: "IQD",
      rawPayload: JSON.stringify({ referenceId: refId, amount: 25000 }),
      __internalApiKey: INTERNAL_API_KEY,
    });

    expect(result.status).toBe("flagged");
    expect(result.reason).toBe("amount_mismatch");

    // Verify 0 minutes credited
    const ws = await t.run(async (ctx) => {
      return await ctx.db.get(workspaceId);
    });
    expect(ws?.dubbingMinutes).toBe(0);

    // Verify alert logged
    const alerts = await t.run(async (ctx) => {
      return await ctx.db
        .query("securityAlerts")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", refId))
        .collect();
    });
    expect(alerts.length).toBe(1);
    expect(alerts[0].type).toBe("amount_mismatch");
  });

  it("Test 3.2: Chargeback quarantine locks workspace and logs chargeback to ledger", async () => {
    const t = convexTest(schema, modules);

    const workspaceId = await t.run(async (ctx) => {
      return await ctx.db.insert("workspaces", {
        name: "Chargeback Workspace",
        legacyId: "ws_chargeback_001",
        dubbingMinutes: 30,
        plan: "pro",
        status: "ACTIVE",
        isLocked: false,
      });
    });

    const refId = "ref_chargeback_victim_001";
    await t.mutation(api.payments.recordExpectedCharge, {
      referenceId: refId,
      workspaceId: "ws_chargeback_001",
      amount: 30000,
      currency: "IQD",
      minutesGranted: 15,
      tier: "pro",
      __internalApiKey: INTERNAL_API_KEY,
    });

    // Process initial purchase
    await t.mutation(api.payments.recordAndProcessWaylEvent, {
      referenceId: refId,
      amount: 30000,
      currency: "IQD",
      rawPayload: JSON.stringify({ referenceId: refId, amount: 30000 }),
      __internalApiKey: INTERNAL_API_KEY,
    });

    // Now execute chargeback refund
    const refundResult = await t.mutation(api.payments.processRefundAtomic, {
      referenceId: refId,
      reason: "Bank dispute / stolen card chargeback",
      isChargeback: true,
      __internalApiKey: INTERNAL_API_KEY,
    });

    expect(refundResult.status).toBe("success");

    // Verify workspace status is under_review and locked
    const ws = await t.run(async (ctx) => {
      return await ctx.db.get(workspaceId);
    });
    expect(ws?.status).toBe("under_review");
    expect(ws?.isLocked).toBe(true);

    // Verify ledger has both purchase and chargeback entries
    const ledger = await t.run(async (ctx) => {
      return await ctx.db
        .query("ledger")
        .withIndex("by_workspace_id", (q) => q.eq("workspaceId", workspaceId))
        .collect();
    });
    expect(ledger.length).toBe(2);
    const chargebackRow = ledger.find((l) => l.type === "chargeback");
    expect(chargebackRow).toBeDefined();
    expect(chargebackRow?.delta).toBe(-15);
  });
});
