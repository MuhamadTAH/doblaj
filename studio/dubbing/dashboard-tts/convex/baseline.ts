import { mutation, internalMutation, query } from "./_generated/server";
import { internal } from "./_generated/api";
import { semanticRatioAggregate } from "./aggregates";

export const updateBaseline = internalMutation({
  args: {},
  handler: async (ctx) => {
    // 1. Get the aggregate sum and count
    const sumResult = await semanticRatioAggregate.sum(ctx);
    const countResult = await semanticRatioAggregate.count(ctx);
    
    if (countResult > 0) {
      const average = sumResult / countResult;
      
      // 2. Write it to system_config
      const existingConfig = await ctx.db
        .query("system_config")
        .withIndex("by_key", (q) => q.eq("key", "kurdish_wps_baseline"))
        .first();
        
      if (existingConfig) {
        await ctx.db.patch(existingConfig._id, {
          value: average,
          sample_size: countResult,
          updated_at: Date.now()
        });
      } else {
        await ctx.db.insert("system_config", {
          key: "kurdish_wps_baseline",
          value: average,
          sample_size: countResult,
          updated_at: Date.now()
        });
      }
    }
  },
});

export const getBaseline = query({
  args: {},
  handler: async (ctx) => {
    const config = await ctx.db
      .query("system_config")
      .withIndex("by_key", (q) => q.eq("key", "kurdish_wps_baseline"))
      .first();
      
    // Default to 1.90 if not yet calculated or not enough data
    return config ? config.value : 1.90;
  }
});
