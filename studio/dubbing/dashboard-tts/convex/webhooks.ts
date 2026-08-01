import { ConvexError, v } from "convex/values";
import { mutation } from "./_generated/server";
import { requireInternalApiKey } from "./lib/auth";

export const recordAndProcessWebhookInternal = mutation({
  args: {
    eventId: v.string(),
    eventType: v.string(),
    payload: v.any(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);

    // 1. DUBABILITY: Record raw payload to webhookEvents table on disk BEFORE processing
    const existingEvent = await ctx.db
      .query("webhookEvents")
      .withIndex("by_event_id", (q) => q.eq("eventId", args.eventId))
      .first();

    if (existingEvent) {
      return { status: "already_recorded", eventId: existingEvent._id };
    }

    const eventRecordId = await ctx.db.insert("webhookEvents", {
      eventId: args.eventId,
      eventType: args.eventType,
      payload: args.payload,
      status: "PROCESSED",
      createdAt: new Date().toISOString(),
    });

    // 2. PROCESS WEBHOOK PAYLOAD
    const eventTypeUpper = args.eventType.toUpperCase();
    const eventData = args.payload.data || args.payload;

    if (eventTypeUpper === "PAYMENT_SUCCESS" || eventTypeUpper === "PAYMENT.SUCCESS") {
      const payment = eventData.payment || eventData;
      const context = eventData.context || {};
      const metadata = context.metadata || {};

      const workspaceIdStr = eventData.workspace_id || metadata.workspace_id || context.externalRef;
      const tierId = eventData.tier_id || metadata.tier_id || "pro";
      const transactionId = eventData.transaction_id || payment.id || args.eventId;

      if (!workspaceIdStr) throw new ConvexError("MISSING_WORKSPACE_ID");

      // Resolve workspace ID
      let ws = await ctx.db
        .query("workspaces")
        .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", workspaceIdStr))
        .first();

      if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND");

      // Dedup transaction using dedicated index
      const existingTx = await ctx.db
        .query("transactions")
        .withIndex("by_suby_transaction_id", (q) => q.eq("subyTransactionId", transactionId))
        .first();

      if (!existingTx) {
        let minutesAdded = 15;
        let amountUsd = 20;
        if (tierId === "starter") { minutesAdded = 5; amountUsd = 10; }
        else if (tierId === "creator") { minutesAdded = 120; amountUsd = 99; }

        await ctx.db.insert("transactions", {
          legacyId: transactionId,
          subyTransactionId: transactionId,
          workspaceId: ws._id,
          tier: tierId,
          amountUsd: amountUsd,
          minutesAdded: minutesAdded,
          createdAt: new Date().toISOString(),
        });

        const nextMinutes = (ws.dubbingMinutes ?? 0) + minutesAdded;
        const totalPurchased = (ws.totalPurchasedMinutes ?? 0) + minutesAdded;
        await ctx.db.patch(ws._id, {
          dubbingMinutes: nextMinutes,
          totalPurchasedMinutes: totalPurchased,
          updatedAt: new Date().toISOString(),
        });
      }
    } else if (eventTypeUpper === "PAYMENT_REFUNDED" || eventTypeUpper === "PAYMENT.REFUNDED") {
      const context = eventData.context || {};
      const metadata = context.metadata || {};
      const workspaceIdStr = eventData.workspace_id || metadata.workspace_id;
      const tierId = eventData.tier_id || metadata.tier_id || "pro";

      if (workspaceIdStr) {
        let ws = await ctx.db
          .query("workspaces")
          .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", workspaceIdStr))
          .first();

        if (ws) {
          let minutesToDeduct = 15;
          if (tierId === "starter") minutesToDeduct = 5;
          else if (tierId === "creator") minutesToDeduct = 120;

          const nextMinutes = (ws.dubbingMinutes ?? 0) - minutesToDeduct;
          const shouldLock = nextMinutes <= 0;

          await ctx.db.patch(ws._id, {
            dubbingMinutes: nextMinutes,
            isLocked: shouldLock,
            status: shouldLock ? "LOCKED_REFUND" : ws.status,
            updatedAt: new Date().toISOString(),
          });

          // Kill active running jobs
          if (shouldLock) {
            const activeJobs = await ctx.db
              .query("dubbingJobs")
              .withIndex("by_workspace_id", (q: any) => q.eq("workspaceId", ws._id))
              .filter((q: any) => q.or(
                q.eq(q.field("status"), "pending"),
                q.eq(q.field("status"), "processing"),
                q.eq(q.field("status"), "separating")
              ))
              .collect();

            for (const j of activeJobs) {
              await ctx.db.patch(j._id, {
                status: "failed",
                error: "WORKSPACE_LOCKED_REFUND_KILL_SWITCH",
                updatedAt: new Date().toISOString(),
              });
            }
          }
        }
      }
    }

    return { status: "persisted_and_processed", eventRecordId };
  },
});
