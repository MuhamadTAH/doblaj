import { mutation } from "./_generated/server";
import { v } from "convex/values";
import { ConvexError } from "convex/values";
import { Id } from "./_generated/dataModel";
import { requireWorkspace,
  requireInternalApiKey,} from "./lib/auth";

export const record = mutation({
  args: {
    data: v.any(),
  },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    const now = new Date().toISOString();
    return await ctx.db.insert("aiUsageLogs", {
      legacyId: crypto.randomUUID(),
      workspaceId,
      data: { ...args.data, recordedAt: now },
    });
  },
});

// Internal: called by Python adapter. workspaceId may be legacy UUID.
// Schema: legacyId, workspaceId, service, context, provider, inputTokens,
// outputTokens, estimatedCostUsd, createdAt.

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

export const recordInternal = mutation({
  args: {
    workspaceId: v.string(),
    service: v.string(),
    context: v.string(),
    provider: v.optional(v.string()),
    model: v.optional(v.string()),
    inputTokens: v.optional(v.number()),
    outputTokens: v.optional(v.number()),
    estimatedCostUsd: v.optional(v.number()),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const workspaceId = await resolveWorkspaceId(ctx, args.workspaceId);
    const now = new Date().toISOString();
    return await ctx.db.insert("aiUsageLogs", {
      legacyId: crypto.randomUUID(),
      workspaceId,
      service: args.service,
      context: args.context,
      provider: args.provider,
      inputTokens: args.inputTokens,
      outputTokens: args.outputTokens,
      estimatedCostUsd: args.estimatedCostUsd,
      createdAt: now,
    });
  },
});
