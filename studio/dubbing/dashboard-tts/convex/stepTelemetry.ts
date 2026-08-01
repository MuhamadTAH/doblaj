import { mutation } from "./_generated/server";
import { requireInternalApiKey } from "./lib/auth";
import { v, ConvexError } from "convex/values";
import { Id } from "./_generated/dataModel";

async function resolveJobId(
  ctx: { db: { query: any; get: any; normalizeId: any } },
  jobIdOrLegacy: string,
): Promise<Id<"dubbingJobs">> {
  const normalized = ctx.db.normalizeId("dubbingJobs", jobIdOrLegacy);
  if (normalized) return normalized;
  const job = await ctx.db
    .query("dubbingJobs")
    .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", jobIdOrLegacy))
    .first();
  if (!job) throw new ConvexError("JOB_NOT_FOUND");
  return job._id;
}

export const insertInternal = mutation({
  args: {
    jobId: v.string(), // accepting legacy string or native ID
    chunkIndex: v.optional(v.number()),
    stepName: v.string(),
    durationMs: v.number(),
    statusCode: v.number(),
    computeProvider: v.string(),
    usageUnits: v.optional(v.number()),
    costUsd: v.number(),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);

    const realJobId = await resolveJobId(ctx, args.jobId);
    // Pird PIRD-017: derive workspaceId from the job doc itself.
    const jobDoc = await ctx.db.get(realJobId);
    const realWorkspaceId = jobDoc?.workspaceId;

    let resolvedChunkId: any = undefined;
    if (args.chunkIndex !== undefined && args.chunkIndex >= 0 && realWorkspaceId) {
      const chunk = await ctx.db
        .query("dubbingChunks")
        .withIndex("by_workspace_job", (q) => q.eq("workspaceId", realWorkspaceId).eq("jobId", realJobId))
        .filter((q) => q.eq(q.field("chunkIndex"), args.chunkIndex))
        .first();

      if (!chunk) {
        console.warn(`[TELEMETRY] Chunk not found for jobId ${args.jobId} and chunkIndex ${args.chunkIndex}`);
      } else {
        resolvedChunkId = chunk._id;
      }
    }

    return await ctx.db.insert("step_telemetry", {
      chunk_id: resolvedChunkId,
      step_name: args.stepName,
      duration_ms: args.durationMs,
      status_code: args.statusCode,
      compute_provider: args.computeProvider,
      usage_units: args.usageUnits,
      cost_usd: args.costUsd,
    });
  },
});

