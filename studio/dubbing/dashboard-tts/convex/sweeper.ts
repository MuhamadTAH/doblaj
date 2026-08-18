import { mutation, query } from "./_generated/server";
import { v } from "convex/values";
import { ConvexError } from "convex/values";

function assertInternalApiKey(args: { __internalApiKey?: string }) {
  const secret = process.env.INTERNAL_API_KEY || "doblaj_dev_secret_key_change_in_prod";
  if (args.__internalApiKey !== secret) {
    throw new ConvexError("UNAUTHORIZED_INTERNAL_CALL");
  }
}

/**
 * Find pending expected charges older than a given threshold (e.g. 15 minutes) for the sweeper to verify.
 * Uses compound index ["status", "createdAt"] for direct database-level range scanning.
 * Strict batching with .take(50) guarantees bounded memory and zero unbounded scans.
 */
export const getPendingChargesForSweep = query({
  args: {
    olderThanMinutes: v.optional(v.number()),
    limit: v.optional(v.number()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    assertInternalApiKey(args);
    const thresholdMinutes = args.olderThanMinutes ?? 15;
    const cutoffIso = new Date(Date.now() - thresholdMinutes * 60 * 1000).toISOString();
    const batchLimit = Math.min(args.limit ?? 50, 100);

    // Direct compound index range query: status == "pending" AND createdAt <= cutoffIso
    return await ctx.db
      .query("expectedCharges")
      .withIndex("by_status_and_created", (q) =>
        q.eq("status", "pending").lte("createdAt", cutoffIso)
      )
      .take(batchLimit);
  },
});

/**
 * Expire pending charges older than 48 hours and route to Dead Letter Queue (DLQ / manualReviewQueue).
 * Enforces Systemic Circuit Awareness: Refuses to expire any charges if the payment provider is unhealthy/circuit open.
 */
export const expireStalePendingCharges = mutation({
  args: {
    maxAgeHours: v.optional(v.number()),
    limit: v.optional(v.number()),
    isCircuitHealthy: v.optional(v.boolean()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    assertInternalApiKey(args);

    // SYSTEMIC CIRCUIT AWARENESS: Never mutate financial state while blind.
    if (args.isCircuitHealthy === false) {
      return {
        expiredCount: 0,
        queuedForReviewCount: 0,
        status: "frozen_circuit_unhealthy",
        reason: "Provider unreachable; pending charges preserved for safety.",
      };
    }

    const maxAgeMs = (args.maxAgeHours ?? 48) * 60 * 60 * 1000;
    const staleCutoffIso = new Date(Date.now() - maxAgeMs).toISOString();
    const batchLimit = Math.min(args.limit ?? 100, 200);

    const stale = await ctx.db
      .query("expectedCharges")
      .withIndex("by_status_and_created", (q) =>
        q.eq("status", "pending").lte("createdAt", staleCutoffIso)
      )
      .take(batchLimit);

    let queuedCount = 0;
    for (const p of stale) {
      // 1. Mark as expired
      await ctx.db.patch(p._id, { status: "expired" });

      // 2. Route to Dead Letter Queue (manualReviewQueue) for administrative escalation
      const existingQueue = await ctx.db
        .query("manualReviewQueue")
        .withIndex("by_reference_id", (q) => q.eq("referenceId", p.referenceId))
        .unique();

      if (!existingQueue) {
        await ctx.db.insert("manualReviewQueue", {
          referenceId: p.referenceId,
          workspaceId: p.workspaceId,
          amount: p.amount,
          currency: p.currency,
          minutesGranted: p.minutesGranted,
          tier: p.tier,
          reason: "stale_pending_48h_unverified",
          status: "pending_review",
          createdAt: Date.now(),
        });
        queuedCount++;
      }
    }

    return {
      expiredCount: stale.length,
      queuedForReviewCount: queuedCount,
      status: "completed",
    };
  },
});
