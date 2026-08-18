import { mutation, query } from "./_generated/server";
import { v } from "convex/values";
import { ConvexError } from "convex/values";

function assertInternalApiKey(args: { __internalApiKey?: string }) {
  const secret = process.env.INTERNAL_API_KEY || "doblaj_dev_secret_key_change_in_prod";
  if (args.__internalApiKey !== secret) {
    throw new ConvexError("UNAUTHORIZED_INTERNAL_CALL");
  }
}

async function resolveWorkspaceId(ctx: any, idOrLegacy: string) {
  try {
    const direct = await ctx.db.get(idOrLegacy as any);
    if (direct) return direct._id;
  } catch {}
  const byLegacy = await ctx.db
    .query("workspaces")
    .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", idOrLegacy))
    .unique();
  if (byLegacy) return byLegacy._id;
  throw new ConvexError(`WORKSPACE_NOT_FOUND: ${idOrLegacy}`);
}

/**
 * 1. Record an expected charge before generating a Wayl checkout link.
 */
export const recordExpectedCharge = mutation({
  args: {
    referenceId: v.string(),
    workspaceId: v.string(),
    amount: v.number(),
    currency: v.string(),
    minutesGranted: v.number(),
    tier: v.string(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    assertInternalApiKey(args);
    const workspaceId = await resolveWorkspaceId(ctx, args.workspaceId);

    const existing = await ctx.db
      .query("expectedCharges")
      .withIndex("by_reference_id", (q) => q.eq("referenceId", args.referenceId))
      .unique();

    if (existing) {
      await ctx.db.patch(existing._id, {
        amount: args.amount,
        currency: args.currency,
        minutesGranted: args.minutesGranted,
        tier: args.tier,
        status: "pending",
      });
      return existing._id;
    }

    return await ctx.db.insert("expectedCharges", {
      referenceId: args.referenceId,
      workspaceId,
      amount: args.amount,
      currency: args.currency,
      minutesGranted: args.minutesGranted,
      tier: args.tier,
      status: "pending",
      createdAt: new Date().toISOString(),
    });
  },
});

/**
 * 2. Atomic Webhook Processing with Read-First Zero-Cost Idempotency.
 */
export const recordAndProcessWaylEvent = mutation({
  args: {
    referenceId: v.string(),
    amount: v.number(),
    currency: v.string(),
    rawPayload: v.string(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    assertInternalApiKey(args);

    // 1. READ FIRST (Zero-Cost Exit for Replays / OCC Retries)
    // Never write before verifying whether this transaction is already complete.
    const existing = await ctx.db
      .query("transactions")
      .withIndex("by_reference_id", (q) => q.eq("referenceId", args.referenceId))
      .unique();

    if (existing) {
      return { status: "already_processed", transactionId: existing._id };
    }

    // 2. NOW establish durability anchor for genuinely new events
    await ctx.db.insert("webhookEvents", {
      referenceId: args.referenceId,
      rawPayload: args.rawPayload,
      receivedAt: Date.now(),
    });

    // 3. Cross-validate against expectedCharges
    const expected = await ctx.db
      .query("expectedCharges")
      .withIndex("by_reference_id", (q) => q.eq("referenceId", args.referenceId))
      .unique();

    if (!expected || expected.amount !== args.amount || expected.currency !== args.currency) {
      // Log anomaly in securityAlerts and return flagged (do NOT throw so event log is preserved)
      await ctx.db.insert("securityAlerts", {
        type: "amount_mismatch",
        referenceId: args.referenceId,
        details: {
          expected: expected ? { amount: expected.amount, currency: expected.currency } : null,
          received: { amount: args.amount, currency: args.currency },
        },
        createdAt: Date.now(),
      });
      return { status: "flagged", reason: "amount_mismatch" };
    }

    // 4. Fulfill Transaction
    const approxUsd = expected.currency === "USD" ? args.amount / 100.0 : args.amount / 1500.0;
    const txId = await ctx.db.insert("transactions", {
      legacyId: args.referenceId,
      referenceId: args.referenceId,
      subyTransactionId: args.referenceId,
      workspaceId: expected.workspaceId,
      tier: expected.tier,
      amount: args.amount,
      currency: args.currency,
      amountUsd: approxUsd,
      minutesAdded: expected.minutesGranted,
      status: "complete",
      createdAt: new Date().toISOString(),
    });

    // 5. Update Workspace Balance & Append to Ledger
    const ws = await ctx.db.get(expected.workspaceId);
    if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND");
    const currentMin = ws.dubbingMinutes ?? 0;
    const nextMinutes = currentMin + expected.minutesGranted;

    await ctx.db.patch(expected.workspaceId, {
      dubbingMinutes: nextMinutes,
      updatedAt: new Date().toISOString(),
    });

    await ctx.db.insert("ledger", {
      workspaceId: expected.workspaceId,
      referenceId: args.referenceId,
      delta: expected.minutesGranted,
      type: "purchase",
      resultingBalance: nextMinutes,
      actor: "webhook",
      createdAt: Date.now(),
    });

    await ctx.db.patch(expected._id, {
      status: "complete",
    });

    // 6. Auto-resolve any DLQ item in manualReviewQueue if present
    const dlqItem = await ctx.db
      .query("manualReviewQueue")
      .withIndex("by_reference_id", (q) => q.eq("referenceId", args.referenceId))
      .unique();

    if (dlqItem) {
      await ctx.db.patch(dlqItem._id, {
        status: "resolved",
        resolvedAt: Date.now(),
        lastKnownWaylStatus: "Complete",
      });
    }

    return { status: "processed", transactionId: txId, newBalance: nextMinutes };
  },
});

/**
 * 3. Process Refund or Chargeback with Account Quarantine
 */
export const processRefundAtomic = mutation({
  args: {
    referenceId: v.string(),
    reason: v.string(),
    isChargeback: v.optional(v.boolean()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    assertInternalApiKey(args);
    const refundKey = args.referenceId.startsWith("REFUND-")
      ? args.referenceId
      : `REFUND-${args.referenceId}`;

    // Read first check
    const existingRefund = await ctx.db
      .query("transactions")
      .withIndex("by_reference_id", (q) => q.eq("referenceId", refundKey))
      .unique();

    if (existingRefund) {
      return { status: "already_processed", transactionId: existingRefund._id };
    }

    // Find original transaction
    const orig = await ctx.db
      .query("transactions")
      .withIndex("by_reference_id", (q) => q.eq("referenceId", args.referenceId))
      .unique();

    let workspaceId: any;
    let minutesToDeduct = 1;
    let amountToRefund = 0;

    if (orig) {
      workspaceId = orig.workspaceId;
      minutesToDeduct = orig.minutesAdded || 1;
      amountToRefund = orig.amount || 0;
    } else {
      const expected = await ctx.db
        .query("expectedCharges")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", args.referenceId))
        .unique();
      if (expected) {
        workspaceId = expected.workspaceId;
        minutesToDeduct = expected.minutesGranted || 1;
        amountToRefund = expected.amount || 0;
      }
    }

    if (!workspaceId) {
      throw new ConvexError(`CANNOT_LOCATE_TRANSACTION_FOR_REFUND: ${args.referenceId}`);
    }

    const txId = await ctx.db.insert("transactions", {
      legacyId: refundKey,
      referenceId: refundKey,
      subyTransactionId: refundKey,
      workspaceId,
      tier: "refund",
      amount: -Math.abs(amountToRefund),
      minutesAdded: -Math.abs(minutesToDeduct),
      status: "refunded",
      createdAt: new Date().toISOString(),
    });

    const ws = await ctx.db.get(workspaceId);
    if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND");
    const currentMin = ws.dubbingMinutes ?? 0;
    const nextMinutes = Math.max(0, currentMin - minutesToDeduct);

    const patchPayload: any = {
      dubbingMinutes: nextMinutes,
      updatedAt: new Date().toISOString(),
    };

    // If Chargeback / Stolen card signal: Quarantine workspace immediately
    if (args.isChargeback) {
      patchPayload.status = "under_review";
      patchPayload.isLocked = true;

      await ctx.db.insert("securityAlerts", {
        type: "chargeback_quarantine",
        referenceId: args.referenceId,
        details: {
          reason: args.reason,
          workspaceId: String(workspaceId),
          deductedMinutes: minutesToDeduct,
        },
        createdAt: Date.now(),
      });
    }

    await ctx.db.patch(workspaceId, patchPayload);

    await ctx.db.insert("ledger", {
      workspaceId,
      referenceId: refundKey,
      delta: -Math.abs(minutesToDeduct),
      type: args.isChargeback ? "chargeback" : "refund",
      resultingBalance: nextMinutes,
      actor: "admin",
      createdAt: Date.now(),
    });

    return { status: "success", transactionId: txId, newBalance: nextMinutes };
  },
});

/**
 * 4. Self-Verifying Balance Auditor (Calculates Sum of Ledger vs Workspace Cached Balance)
 */
export const auditLedgerBalances = query({
  args: {
    workspaceId: v.optional(v.string()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    assertInternalApiKey(args);

    let targets = [];
    if (args.workspaceId) {
      const wsId = await resolveWorkspaceId(ctx, args.workspaceId);
      const ws = await ctx.db.get(wsId);
      if (ws) targets.push(ws);
    } else {
      targets = await ctx.db.query("workspaces").take(100);
    }

    const auditResults = [];
    for (const ws of targets) {
      const ledgerEntries = await ctx.db
        .query("ledger")
        .withIndex("by_workspace_id", (q) => q.eq("workspaceId", ws._id))
        .collect();

      const calculatedMinutes = ledgerEntries.reduce((sum, entry) => sum + (entry.delta || 0), 0);
      const cachedMinutes = ws.dubbingMinutes ?? 0;
      const drift = cachedMinutes - calculatedMinutes;

      auditResults.push({
        workspaceId: ws._id,
        legacyId: ws.legacyId,
        cachedMinutes,
        calculatedMinutes,
        drift,
        isBalanced: drift === 0,
        entriesCount: ledgerEntries.length,
      });
    }

    return auditResults;
  },
});
