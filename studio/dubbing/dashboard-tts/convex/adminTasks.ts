import { ConvexError, v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { Id } from "./_generated/dataModel";
import { requireWorkspace, requireInternalApiKey } from "./lib/auth";

export const deleteAllInternal = mutation({
  args: { __internalApiKey: v.string() },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const all = await ctx.db.query("dubbingJobs").collect();
    let count = 0;
    for (const job of all) {
      await ctx.db.delete(job._id);
      count++;
    }
    return count;
  }
});
