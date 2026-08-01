import { v } from "convex/values";
import { internalQuery, mutation, query } from "./_generated/server";
import { requireWorkspace,
  requireInternalApiKey,} from "./lib/auth";

export const list = query({
  args: { categoryId: v.optional(v.string()) },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    return await ctx.db
      .query("dubbingDictionaries")
      .withIndex("by_workspace_id", (q) => q.eq("workspaceId", workspaceId))
      .collect();
  },
});

/**
 * Internal: global lookup by categoryId. Bypasses auth so the Python
 * FastAPI worker (no Clerk session) can read the dictionary JSONB.
 */
export const getByCategoryInternal = query({
  args: { categoryId: v.string(),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const match = await ctx.db
      .query("dubbingDictionaries")
      .withIndex("by_category", (q) => q.eq("categoryId", args.categoryId))
      .first();
    return match ? (match.data ?? null) : null;
  },
});

/**
 * Internal: list all distinct categoryIds across all workspaces.
 */
export const listCategoriesInternal = query({
  args: {
    __internalApiKey: v.string(),},
  handler: async (ctx) => {
    const docs = await ctx.db.query("dubbingDictionaries").collect();
    const set = new Set<string>();
    for (const d of docs) {
      if (d.categoryId) set.add(d.categoryId as string);
    }
    return Array.from(set).sort();
  },
});

export const upsert = mutation({
  args: {
    legacyId: v.string(),
    src: v.optional(v.string()),
    tgt: v.optional(v.string()),
    context: v.optional(v.string()),
    priority: v.optional(v.number()),
    categoryId: v.optional(v.string()),
    data: v.optional(v.any()),
  },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    const existing = await ctx.db
      .query("dubbingDictionaries")
      .withIndex("by_legacy_id", (q) => q.eq("legacyId", args.legacyId))
      .unique();
    if (existing && existing.workspaceId !== workspaceId) {
      throw new Error("FORBIDDEN");
    }
    if (existing) {
      await ctx.db.patch(existing._id, {
        ...(args.src !== undefined ? { src: args.src } : {}),
        ...(args.tgt !== undefined ? { tgt: args.tgt } : {}),
        ...(args.context !== undefined ? { context: args.context } : {}),
        ...(args.priority !== undefined ? { priority: args.priority } : {}),
        ...(args.categoryId !== undefined ? { categoryId: args.categoryId } : {}),
        ...(args.data !== undefined ? { data: args.data } : {}),
      });
      return existing._id;
    }
    return await ctx.db.insert("dubbingDictionaries", {
      legacyId: args.legacyId,
      workspaceId,
      ...(args.src !== undefined ? { src: args.src } : {}),
      ...(args.tgt !== undefined ? { tgt: args.tgt } : {}),
      ...(args.context !== undefined ? { context: args.context } : {}),
      ...(args.priority !== undefined ? { priority: args.priority } : {}),
      ...(args.categoryId !== undefined ? { categoryId: args.categoryId } : {}),
      ...(args.data !== undefined ? { data: args.data } : {}),
    });
  },
});
