import { ConvexError, v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { requireWorkspace, requireWorkspaceId, asConvexWorkspaceId,
  requireInternalApiKey,} from "./lib/auth";

export const listForCurrent = query({
  args: {},
  handler: async (ctx) => {
    const { workspaceId } = await requireWorkspace(ctx);
    return await ctx.db
      .query("workspaces")
      .withIndex("by_workspace_id", (q) => q.eq("legacyId", workspaceId))
      .unique();
  },
});

export const upsertForCurrent = mutation({
  args: {
    name: v.optional(v.string()),
    plan: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    const existing = await ctx.db
      .query("workspaces")
      .withIndex("by_workspace_id", (q) => q.eq("legacyId", workspaceId))
      .unique();
    if (existing) {
      await ctx.db.patch(existing._id, {
        ...(args.name !== undefined ? { name: args.name } : {}),
        ...(args.plan !== undefined ? { plan: args.plan } : {}),
      });
      return existing._id;
    }
    return await ctx.db.insert("workspaces", {
      legacyId: workspaceId,
      ...(args.name !== undefined ? { name: args.name } : {}),
      ...(args.plan !== undefined ? { plan: args.plan } : {}),
      ownerId: undefined,
      dubbingMinutes: 0,
    });
  },
});

export const getMinutes = query({
  args: { workspaceId: v.optional(v.string()) },
  handler: async (ctx, args) => {
    if (args.workspaceId) {
      await requireWorkspaceId(ctx, args.workspaceId);
    } else {
      await requireWorkspace(ctx);
    }
    const ws = args.workspaceId ?? (await requireWorkspace(ctx)).workspaceId;
    const doc = await ctx.db
      .query("workspaces")
      .withIndex("by_workspace_id", (q) => q.eq("legacyId", ws))
      .unique();
    return doc?.dubbingMinutes ?? 0;
  },
});

export const addMinutes = mutation({
  args: { delta: v.number() },
  handler: async (ctx, args) => {
    if (args.delta === 0) {
      throw new ConvexError("ZERO_DELTA_NOT_ALLOWED");
    }
    const { workspaceId } = await requireWorkspace(ctx);
    const doc = await ctx.db
      .query("workspaces")
      .withIndex("by_workspace_id", (q) => q.eq("legacyId", workspaceId))
      .unique();
    if (!doc) {
      throw new ConvexError("WORKSPACE_NOT_FOUND");
    }
    const next = (doc.dubbingMinutes ?? 0) + args.delta;
    if (next < 0) {
      throw new ConvexError("INSUFFICIENT_MINUTES");
    }
    await ctx.db.patch(doc._id, { dubbingMinutes: next });
    return next;
  },
});

export const deductMinutes = mutation({
  args: { amount: v.number() },
  handler: async (ctx, args) => {
    if (args.amount <= 0) {
      throw new ConvexError("AMOUNT_MUST_BE_POSITIVE");
    }
    const { workspaceId } = await requireWorkspace(ctx);
    const doc = await ctx.db
      .query("workspaces")
      .withIndex("by_workspace_id", (q) => q.eq("legacyId", workspaceId))
      .unique();
    if (!doc) {
      throw new ConvexError("WORKSPACE_NOT_FOUND");
    }
    const next = Math.max(0, (doc.dubbingMinutes ?? 0) - args.amount);
    await ctx.db.patch(doc._id, { dubbingMinutes: next });
    return next;
  },
});

export const workspaceRef = asConvexWorkspaceId;

export const findByOwnerInternal = query({
  args: { ownerUserId: v.string(),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const doc = await ctx.db
      .query("workspaces")
      .withIndex("by_owner", (q) => q.eq("ownerUserId", args.ownerUserId))
      .first();
    if (!doc) return null;
    return { _id: doc._id, legacyId: doc.legacyId, name: doc.name };
  },
});

export const createForOwnerInternal = mutation({
  args: {
    ownerUserId: v.string(),
    orgId: v.string(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const existing = await ctx.db
      .query("workspaces")
      .withIndex("by_owner", (q) => q.eq("ownerUserId", args.ownerUserId))
      .first();
    if (existing) {
      return { _id: existing._id, legacyId: existing.legacyId, name: existing.name };
    }
    const legacyId = args.orgId;
    const wsId = await ctx.db.insert("workspaces", {
      legacyId,
      name: "Default Workspace",
      ownerUserId: args.ownerUserId,
      dubbingMinutes: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
    return { _id: wsId, legacyId, name: "Default Workspace" };
  },
});

// ----------------------------------------------------------------------------
// Internal variants for Python FastAPI adapter (no auth check).
// ----------------------------------------------------------------------------

import { Id } from "./_generated/dataModel";

async function resolveWorkspaceId(
  ctx: { db: { query: any; get: any; normalizeId: any } },
  workspaceIdOrLegacy: string,
): Promise<Id<"workspaces">> {
  const normalized = ctx.db.normalizeId("workspaces", workspaceIdOrLegacy);
  if (normalized) return normalized;
  const ws = await ctx.db
    .query("workspaces")
    .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", workspaceIdOrLegacy))
    .first();
  if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND");
  return ws._id;
}

export const getMinutesInternal = query({
  args: { legacyId: v.string(),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    // Pird PIRD-017: caller passes legacyId; we look up the workspace
    // server-side. Caller cannot choose which workspace's minutes to read.
    const ws = await ctx.db
      .query("workspaces")
      .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", args.legacyId))
      .first();
    if (!ws) return 0;
    return ws.dubbingMinutes ?? 0;
  },
});

export const addMinutesInternal = mutation({
  args: { legacyId: v.string(), delta: v.number(),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    if (args.delta === 0) throw new ConvexError("ZERO_DELTA_NOT_ALLOWED");
    if (args.delta < 0) throw new ConvexError("DELTA_MUST_BE_NON_NEGATIVE");
    // Pird PIRD-017: workspace is looked up by legacyId; no caller-supplied
    // workspaceId.
    const ws = await ctx.db
      .query("workspaces")
      .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", args.legacyId))
      .first();
    if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND");
    const next = (ws.dubbingMinutes ?? 0) + args.delta;
    if (next < 0) throw new ConvexError("INSUFFICIENT_MINUTES");
    await ctx.db.patch(ws._id, { dubbingMinutes: next });
    return next;
  },
});

export const deductMinutesInternal = mutation({
  args: { legacyId: v.string(), amount: v.number(),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    if (args.amount <= 0) throw new ConvexError("AMOUNT_MUST_BE_POSITIVE");
    
    const ws = await ctx.db
      .query("workspaces")
      .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", args.legacyId))
      .first();
    if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND");
    
    // Active Kill-Switch & Fraud Lockdown Enforcement
    if (ws.isLocked || ws.status === "LOCKED_REFUND") {
      throw new ConvexError("WORKSPACE_ACCOUNT_LOCKED_REFUND_FRAUD");
    }
    
    // Cumulative Velocity Limit Enforcement: Calculate usage over the last 48 hours
    const createdAtMs = ws.createdAt ? new Date(ws.createdAt).getTime() : Date.now();
    const ageHours = (Date.now() - createdAtMs) / (1000 * 3600);
    const totalPurchased = ws.totalPurchasedMinutes ?? 0;
    
    if (ageHours < 48 && totalPurchased === 0) {
      const fortyEightHoursAgoIso = new Date(Date.now() - 48 * 3600 * 1000).toISOString();
      // Database-level range filtering on compound index [workspaceId, createdAt]
      const recentJobs = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_workspace_and_created", (q: any) =>
          q.eq("workspaceId", ws._id).gte("createdAt", fortyEightHoursAgoIso)
        )
        .collect();

      let totalConsumedLast48h = 0;
      for (const j of recentJobs) {
        if (j.total_duration_sec) {
          totalConsumedLast48h += j.total_duration_sec / 60;
        }
      }

      if (totalConsumedLast48h + args.amount > 30) {
        throw new ConvexError("VELOCITY_LIMIT_EXCEEDED");
      }
    }
    
    const current = ws.dubbingMinutes ?? 0;
    if (current < args.amount) throw new ConvexError("INSUFFICIENT_MINUTES");
    const next = current - args.amount;
    await ctx.db.patch(ws._id, { dubbingMinutes: next });
    return next;
  },
});

export const handleRefundKillSwitchInternal = mutation({
  args: {
    legacyId: v.string(),
    amountDeducted: v.number(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const ws = await ctx.db
      .query("workspaces")
      .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", args.legacyId))
      .first();
    if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND");
    
    const current = ws.dubbingMinutes ?? 0;
    const next = current - args.amountDeducted;
    
    // Active Kill-Switch: if refund pushes balance negative or zeroes account, lock immediately
    const shouldLock = next <= 0;
    await ctx.db.patch(ws._id, {
      dubbingMinutes: next,
      isLocked: shouldLock,
      status: shouldLock ? "LOCKED_REFUND" : ws.status,
      updatedAt: new Date().toISOString(),
    });
    
    // Cancel any active running jobs for this workspace
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
        
      for (const job of activeJobs) {
        await ctx.db.patch(job._id, {
          status: "failed",
          error: "WORKSPACE_LOCKED_REFUND_KILL_SWITCH",
          updatedAt: new Date().toISOString(),
        });
      }
    }
    
    return { newBalance: next, locked: shouldLock };
  },
});
export const getAllForDebug = query({ handler: async (ctx) => { return await ctx.db.query("workspaces").collect(); } });
