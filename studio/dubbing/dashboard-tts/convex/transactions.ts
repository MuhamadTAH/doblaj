import { ConvexError, v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { Id } from "./_generated/dataModel";
import { requireWorkspace } from "./lib/auth";

async function resolveWorkspaceId(
  ctx: { db: { query: any; get: any } },
  workspaceIdOrLegacy: string,
): Promise<Id<"workspaces">> {
  if (workspaceIdOrLegacy.length === 32) {
    return workspaceIdOrLegacy as Id<"workspaces">;
  }
  const ws = await ctx.db
    .query("workspaces")
    .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", workspaceIdOrLegacy))
    .first();
  if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND");
  return ws._id;
}

export const exists = query({
  args: { legacyId: v.string() },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    const doc = await ctx.db
      .query("transactions")
      .withIndex("by_legacy_id", (q) => q.eq("legacyId", args.legacyId))
      .unique();
    return doc !== null && doc.workspaceId === workspaceId;
  },
});

export const record = mutation({
  args: {
    legacyId: v.string(),
    data: v.optional(v.any()),
  },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    const existing = await ctx.db
      .query("transactions")
      .withIndex("by_legacy_id", (q) => q.eq("legacyId", args.legacyId))
      .unique();
    if (existing) {
      if (existing.workspaceId !== workspaceId) {
        throw new ConvexError("FORBIDDEN");
      }
      return existing._id;
    }
    return await ctx.db.insert("transactions", {
      legacyId: args.legacyId,
      workspaceId,
      data: args.data,
    });
  },
});

export const existsInternal = query({
  args: { legacyId: v.string() },
  handler: async (ctx, args) => {
    const doc = await ctx.db
      .query("transactions")
      .withIndex("by_legacy_id", (q) => q.eq("legacyId", args.legacyId))
      .unique();
    return doc !== null;
  },
});

export const recordInternal = mutation({
  args: {
    legacyId: v.string(),
    workspaceId: v.string(),
    tier: v.optional(v.string()),
    amountUsd: v.optional(v.number()),
    minutesAdded: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    const workspaceId = await resolveWorkspaceId(ctx, args.workspaceId);
    const existing = await ctx.db
      .query("transactions")
      .withIndex("by_legacy_id", (q) => q.eq("legacyId", args.legacyId))
      .unique();
    if (existing) return existing._id;
    return await ctx.db.insert("transactions", {
      legacyId: args.legacyId,
      workspaceId,
      tier: args.tier,
      amountUsd: args.amountUsd,
      minutesAdded: args.minutesAdded,
      createdAt: new Date().toISOString(),
    });
  },
});

export const processPaymentSuccessInternal = mutation({
  args: {
    transactionId: v.string(),
    workspaceId: v.string(),
    tier: v.string(),
    amountUsd: v.number(),
    minutesAdded: v.number(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    const workspaceId = await resolveWorkspaceId(ctx, args.workspaceId);
    
    // Strict schema-level deduplication using dedicated by_suby_transaction_id index
    const existing = await ctx.db
      .query("transactions")
      .withIndex("by_suby_transaction_id", (q) => q.eq("subyTransactionId", args.transactionId))
      .first();
      
    if (existing) {
      return { status: "already_processed", transactionId: existing._id };
    }
    
    const txId = await ctx.db.insert("transactions", {
      legacyId: args.transactionId,
      subyTransactionId: args.transactionId,
      workspaceId,
      tier: args.tier,
      amountUsd: args.amountUsd,
      minutesAdded: args.minutesAdded,
      createdAt: new Date().toISOString(),
    });
    
    const ws = await ctx.db.get(workspaceId);
    if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND");
    const nextMinutes = (ws.dubbingMinutes ?? 0) + args.minutesAdded;
    await ctx.db.patch(workspaceId, {
      dubbingMinutes: nextMinutes,
      updatedAt: new Date().toISOString(),
    });
    
    return { status: "success", transactionId: txId, newBalance: nextMinutes };
  },
});

export const listInternal = query({
  args: { workspaceId: v.string() },
  handler: async (ctx, args) => {
    const workspaceId = await resolveWorkspaceId(ctx, args.workspaceId);
    return await ctx.db
      .query("transactions")
      .withIndex("by_workspace_id", (q) => q.eq("workspaceId", workspaceId))
      .collect();
  }
});
