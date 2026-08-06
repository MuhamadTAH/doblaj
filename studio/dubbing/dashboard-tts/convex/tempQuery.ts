import { mutation, query } from './_generated/server';
import { v } from "convex/values";
import { requireInternalApiKey } from "./lib/auth";

export const getLatest = query({
  handler: async (ctx) => {
    return await ctx.db.query('dubbingJobs').order('desc').take(5);
  },
});

export const forceUpdate = mutation({
  args: { legacyId: v.string(), __internalApiKey: v.optional(v.string()) },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const job = await ctx.db.query("dubbingJobs").withIndex("by_legacy_id", q => q.eq("legacyId", args.legacyId)).first();
    if (!job) return "not found";
    
    await ctx.db.patch(job._id, {
      status: "gpu_finished",
      progress: 50,
      resultVideoR2Key: `dubbing/user_3HPcoDQrbj3QUoOh4882TeqzIBr/${args.legacyId}/intermediate_${args.legacyId}.zip`,
    });
    return "updated";
  }
});
