import { ConvexError, v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { Id } from "./_generated/dataModel";
import { requireWorkspace,
  requireInternalApiKey,} from "./lib/auth";

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

export const listForWorkspace = query({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    return await ctx.db
      .query("dubbingJobs")
      .withIndex("by_workspace_id", (q) => q.eq("workspaceId", workspaceId))
      .order("desc")
      .take(args.limit ?? 50);
  },
});

export const get = query({
  args: { jobId: v.id("dubbingJobs") },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    const doc = await ctx.db.get(args.jobId);
    if (!doc || doc.workspaceId !== workspaceId) {
      throw new ConvexError("NOT_FOUND");
    }
    return doc;
  },
});

export const create = mutation({
  args: {
    sourceUrl: v.string(),
    targetLang: v.string(),
    sourceLang: v.optional(v.string()),
    ttsProvider: v.optional(v.string()),
    sourceVideoR2Key: v.string(),
  },
  handler: async (ctx, args) => {
    const { workspaceId, userId } = await requireWorkspace(ctx);
    const now = new Date().toISOString();
    return await ctx.db.insert("dubbingJobs", {
      legacyId: crypto.randomUUID(),
      workspaceId,
      userId,
      sourceUrl: args.sourceUrl,
      targetLang: args.targetLang,
      sourceLang: args.sourceLang,
      ttsProvider: args.ttsProvider,
      sourceVideoR2Key: args.sourceVideoR2Key,
      status: "pending",
      progress: 0,
      createdAt: now,
      updatedAt: now,
    });
  },
});

export const updateStatus = mutation({
  args: {
    jobId: v.id("dubbingJobs"),
    status: v.string(),
    progress: v.optional(v.number()),
    resultUrl: v.optional(v.string()),
    resultVideoR2Key: v.optional(v.string()),
    error: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    const doc = await ctx.db.get(args.jobId);
    if (!doc || doc.workspaceId !== workspaceId) {
      throw new ConvexError("NOT_FOUND");
    }
    const patch: Record<string, unknown> = {
      status: args.status,
      updatedAt: new Date().toISOString(),
    };
    if (args.progress !== undefined) patch.progress = args.progress;
    if (args.resultUrl !== undefined) patch.resultUrl = args.resultUrl;
    if (args.resultVideoR2Key !== undefined)
      patch.resultVideoR2Key = args.resultVideoR2Key;
    if (args.error !== undefined) patch.error = args.error;
    await ctx.db.patch(args.jobId, patch);
    return args.jobId;
  },
});

export const setProgress = mutation({
  args: {
    jobId: v.id("dubbingJobs"),
    progress: v.number(),
  },
  handler: async (ctx, args) => {
    if (args.progress < 0 || args.progress > 100) {
      throw new ConvexError("PROGRESS_OUT_OF_RANGE");
    }
    const { workspaceId } = await requireWorkspace(ctx);
    const doc = await ctx.db.get(args.jobId);
    if (!doc || doc.workspaceId !== workspaceId) {
      throw new ConvexError("NOT_FOUND");
    }
    await ctx.db.patch(args.jobId, {
      progress: args.progress,
      updatedAt: new Date().toISOString(),
    });
    return args.jobId;
  },
});

// ----------------------------------------------------------------------------
// Internal (service-to-service) variants for the Python FastAPI adapter.
// No auth check. workspaceId / jobId accept either Convex native IDs or
// legacy UUID strings (resolved via by_legacy_id index).
// ----------------------------------------------------------------------------

export const createInternal = mutation({
  args: {
    workspaceId: v.string(),
    ownerUserId: v.optional(v.string()),
    legacyId: v.optional(v.string()),
    sourceVideoR2Key: v.optional(v.string()),
    sourceLang: v.optional(v.string()),
    targetLang: v.optional(v.string()),
    ttsProvider: v.optional(v.string()),
    consentVersion: v.optional(v.string()),
    userIpAddress: v.optional(v.string()),
    consentTimestamp: v.optional(v.string()),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    // PIRD-017: this is a NEW doc — there's no parent to derive from.
    // Caller is the Python adapter, which always passes the
    // server-resolved workspaceId from the JWT-verified browser path.
    // Existing resolveWorkspaceId still accepts either legacy or native id.
    const workspaceId = await resolveWorkspaceId(ctx, args.workspaceId);
    const now = new Date().toISOString();
    const legacyId = args.legacyId ?? crypto.randomUUID();
    const _id = await ctx.db.insert("dubbingJobs", {
      legacyId,
      workspaceId,
      ownerUserId: args.ownerUserId,
      sourceVideoR2Key: args.sourceVideoR2Key ?? "",
      sourceLang: args.sourceLang ?? "ku",
      targetLang: args.targetLang ?? "ar-IQ",
      ttsProvider: args.ttsProvider ?? "minimax",
      consentVersion: args.consentVersion,
      userIpAddress: args.userIpAddress,
      consentTimestamp: args.consentTimestamp,
      status: "pending",
      progress: 0,
      chunksCount: 0,
      rollingCps: 0,
      createdAt: now,
      updatedAt: now,
    });
    return await ctx.db.get(_id);
  },
});

// Pird PIRD-017: every *Internal function below derives workspaceId
// server-side from the doc itself. Caller-supplied workspaceId is rejected
// at the schema level (no such arg). This prevents a single-shared
// INTERNAL_API_KEY from being used to write cross-tenant.

// Return all legacyIds currently in the dubbingJobs table so the backfill
// script can skip rows that are already migrated.
export const listAllLegacyIdsInternal = query({
  args: { __internalApiKey: v.string() },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const docs = await ctx.db.query("dubbingJobs").collect();
    return docs.map((d) => d.legacyId);
  },
});

export const getInternal = query({
  args: { 
    jobId: v.string(),
    expectedWorkspaceId: v.optional(v.string()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const jobId = await resolveJobId(ctx, args.jobId);
    const doc = await ctx.db.get(jobId);
    if (!doc) throw new ConvexError("NOT_FOUND");
    
    if (args.expectedWorkspaceId) {
      const expectedId = await resolveWorkspaceId(ctx, args.expectedWorkspaceId);
      if (doc.workspaceId !== expectedId) {
        throw new ConvexError("WORKSPACE_MISMATCH");
      }
    }
    
    return doc;
  },
});

export const listForWorkspaceInternal = query({
  args: { workspaceId: v.string(), limit: v.optional(v.number()),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const workspaceId = await resolveWorkspaceId(ctx, args.workspaceId);
    return await ctx.db
      .query("dubbingJobs")
      .withIndex("by_workspace_id", (q) => q.eq("workspaceId", workspaceId))
      .order("desc")
      .take(args.limit ?? 50);
  },
});

export const listByStatusInternal = query({
  args: { status: v.string(), limit: v.optional(v.number()), __internalApiKey: v.string() },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    return await ctx.db
      .query("dubbingJobs")
      .withIndex("by_status", (q) => q.eq("status", args.status))
      .order("desc")
      .take(args.limit ?? 50);
  },
});

export const updateStatusInternal = mutation({
  args: {
    jobId: v.string(),
    status: v.string(),
    progress: v.optional(v.number()),
    chunksCount: v.optional(v.number()),
    resultVideoR2Key: v.optional(v.string()),
    error: v.optional(v.string()),
    expectedWorkspaceId: v.optional(v.string()),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const jobId = await resolveJobId(ctx, args.jobId);
    const doc = await ctx.db.get(jobId);
    if (!doc) throw new ConvexError("NOT_FOUND");
    // PIRD-017 follow-up, Part03: refuse the write when the caller
    // declared a workspace that does not own the doc.
    if (args.expectedWorkspaceId) {
      const expectedId = await resolveWorkspaceId(ctx, args.expectedWorkspaceId);
      if (doc.workspaceId !== expectedId) {
        throw new ConvexError("WORKSPACE_MISMATCH");
      }
    }
    const patch: Record<string, unknown> = {
      status: args.status,
      updatedAt: new Date().toISOString(),
    };
    if (args.progress !== undefined) patch.progress = args.progress;
    if (args.chunksCount !== undefined) patch.chunksCount = args.chunksCount;
    if (args.resultVideoR2Key !== undefined)
      patch.resultVideoR2Key = args.resultVideoR2Key;
    if (args.error !== undefined) patch.error = args.error;
    await ctx.db.patch(jobId, patch);
    return await ctx.db.get(jobId);
  },
});

export const updateCostInternal = mutation({
  args: {
    jobId: v.string(),
    totalProcessingLatencyMs: v.number(),
    totalCostUsd: v.number(),
    expectedWorkspaceId: v.optional(v.string()),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const jobId = await resolveJobId(ctx, args.jobId);
    const doc = await ctx.db.get(jobId);
    if (!doc) throw new ConvexError("NOT_FOUND");
    // PIRD-017 follow-up, Part03: see updateStatusInternal.
    if (args.expectedWorkspaceId) {
      const expectedId = await resolveWorkspaceId(ctx, args.expectedWorkspaceId);
      if (doc.workspaceId !== expectedId) {
        throw new ConvexError("WORKSPACE_MISMATCH");
      }
    }
    await ctx.db.patch(jobId, {
      total_processing_latency_ms: args.totalProcessingLatencyMs,
      total_cost_usd: args.totalCostUsd,
      updatedAt: new Date().toISOString(),
    });
    return await ctx.db.get(jobId);
  },
});

export const setProgressInternal = mutation({
  args: {
    jobId: v.string(),
    progress: v.number(),
    expectedWorkspaceId: v.optional(v.string()),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    if (args.progress < 0 || args.progress > 100) {
      throw new ConvexError("PROGRESS_OUT_OF_RANGE");
    }
    requireInternalApiKey(args.__internalApiKey);
    const jobId = await resolveJobId(ctx, args.jobId);
    const doc = await ctx.db.get(jobId);
    if (!doc) throw new ConvexError("NOT_FOUND");
    // PIRD-017 follow-up, Part03: see updateStatusInternal.
    if (args.expectedWorkspaceId) {
      const expectedId = await resolveWorkspaceId(ctx, args.expectedWorkspaceId);
      if (doc.workspaceId !== expectedId) {
        throw new ConvexError("WORKSPACE_MISMATCH");
      }
    }
    await ctx.db.patch(jobId, {
      progress: args.progress,
      updatedAt: new Date().toISOString(),
    });
    return await ctx.db.get(jobId);
  },
});

// Insert a historical job row from SQLite migration. Used by the
// backfill script when migrating old jobs into Convex.
export const backfillInsertInternal = mutation({
  args: {
    legacyId: v.string(),
    workspaceId: v.string(),
    ownerUserId: v.string(),
    status: v.string(),
    progress: v.optional(v.number()),
    sourceLang: v.optional(v.string()),
    targetLang: v.optional(v.string()),
    ttsProvider: v.optional(v.string()),
    sourceVideoR2Key: v.optional(v.string()),
    resultVideoR2Key: v.optional(v.string()),
    error: v.optional(v.string()),
    createdAt: v.string(),
    updatedAt: v.string(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const targetWorkspaceId = await resolveWorkspaceId(ctx, args.workspaceId);
    return await ctx.db.insert("dubbingJobs", {
      legacyId: args.legacyId,
      workspaceId: targetWorkspaceId,
      ownerUserId: args.ownerUserId,
      status: args.status,
      progress: args.progress ?? 0,
      chunksCount: 0,
      rollingCps: 0,
      sourceLang: args.sourceLang ?? "ku",
      targetLang: args.targetLang ?? "ar-IQ",
      ttsProvider: args.ttsProvider ?? "minimax",
      sourceVideoR2Key: args.sourceVideoR2Key ?? "",
      resultVideoR2Key: args.resultVideoR2Key ?? "",
      error: args.error ?? "",
      createdAt: args.createdAt,
      updatedAt: args.updatedAt,
    });
  },
});

// Pull orphan jobs (no ownerUserId OR empty workspaceId OR workspaceId
// points at a missing workspace) into a freshly-created workspace so
// first sign-in after workspace reprovision shows the user's history.
export const reassignOrphansToWorkspaceInternal = mutation({
  args: {
    ownerUserId: v.string(),
    workspaceId: v.string(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const targetWorkspaceId = await resolveWorkspaceId(ctx, args.workspaceId);
    const all = await ctx.db.query("dubbingJobs").collect();
    let moved = 0;
    for (const job of all) {
      const isOrphan =
        !job.ownerUserId ||
        !job.workspaceId ||
        job.ownerUserId === args.ownerUserId;
      if (!isOrphan) continue;
      await ctx.db.patch(job._id, {
        ownerUserId: args.ownerUserId,
        workspaceId: targetWorkspaceId,
        updatedAt: new Date().toISOString(),
      });
      moved++;
    }
    return moved;
  },
});

export const getAllForDebug = query({
  handler: async (ctx) => {
    return await ctx.db.query("dubbingJobs").collect();
  }
});
