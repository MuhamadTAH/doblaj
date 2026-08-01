import { ConvexError, v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { Id } from "./_generated/dataModel";
import { requireWorkspace,
  requireInternalApiKey,} from "./lib/auth";

async function resolveChunkId(
  ctx: { db: { query: any; get: any; normalizeId: any } },
  chunkIdOrLegacy: string,
): Promise<Id<"dubbingChunks">> {
  const normalized = ctx.db.normalizeId("dubbingChunks", chunkIdOrLegacy);
  if (normalized) return normalized;
  const doc = await ctx.db
    .query("dubbingChunks")
    .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", chunkIdOrLegacy))
    .first();
  if (!doc) throw new ConvexError("CHUNK_NOT_FOUND");
  return doc._id;
}

export const listForJob = query({
  args: { jobId: v.id("dubbingJobs") },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    return await ctx.db
      .query("dubbingChunks")
      .withIndex("by_workspace_job", (q) =>
        q.eq("workspaceId", workspaceId).eq("jobId", args.jobId),
      )
      .collect();
  },
});

export const update = mutation({
  args: {
    chunkId: v.id("dubbingChunks"),
    transcriptSrc: v.optional(v.string()),
    transcriptTgt: v.optional(v.string()),
    audioPath: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const { workspaceId } = await requireWorkspace(ctx);
    const doc = await ctx.db.get(args.chunkId);
    if (!doc || doc.workspaceId !== workspaceId) {
      throw new ConvexError("NOT_FOUND");
    }
    const patch: Record<string, unknown> = {};
    if (args.transcriptSrc !== undefined) patch.transcriptSrc = args.transcriptSrc;
    if (args.transcriptTgt !== undefined) patch.transcriptTgt = args.transcriptTgt;
    if (args.audioPath !== undefined) patch.audioPath = args.audioPath;
    await ctx.db.patch(args.chunkId, patch);
    return args.chunkId;
  },
});

// Internal: accepts any subset of fields the pipeline writes. No auth.
// chunkId may be legacyId UUID or native Convex ID.

export const updateInternal = mutation({
  args: {
    chunkId: v.string(),
    patch: v.any(),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const chunkId = await resolveChunkId(ctx, args.chunkId);
    const existing = await ctx.db.get(chunkId);
    if (!existing) throw new ConvexError("CHUNK_NOT_FOUND");
    const safePatch: Record<string, unknown> = {};
    const allowed = new Set([
      "transcriptSrc", "transcriptTgt", "audioPath",
      "kurdishRaw", "kurdishCorrected", "arabicText", "arabicLocked",
      "ttsAudioR2Key", "assembledAudioR2Key", "speaker", "status",
      "pipelineDetails", "error", "updatedAt",
      "kurdish_raw_audio_url", "kurdish_word_count", "kurdish_wps",
      "baseline_wps_used", "speed_multiplier", "target_ratio_applied", "was_clamped",
      "final_arabic_word_count", "semantic_ratio",
      "kurdish_syllable_count", "final_arabic_syllable_count", "ffmpeg_warp_factor",
      "vad_duration_sec", "speechDuration"
    ]);
    for (const [k, v] of Object.entries(args.patch ?? {})) {
      if (allowed.has(k)) safePatch[k] = v;
    }
    safePatch.updatedAt = new Date().toISOString();
    await ctx.db.patch(chunkId, safePatch);
    return await ctx.db.get(chunkId);
  },
});

export const insertInternal = mutation({
  args: {
    legacyId: v.string(),
    jobId: v.string(),
    chunkIndex: v.number(),
    startTime: v.number(),
    endTime: v.number(),
    status: v.string(),
    // Pird (security review M4): replace `v.any()` with a strict object
    // schema. Previously an attacker could insert arbitrary fields like
    // `workspaceId` to override the typed one, or any column not in the
    // chunk schema. The allowlist mirrors `updateInternal`.
    patch: v.optional(
      v.object({
        transcriptSrc: v.optional(v.string()),
        transcriptTgt: v.optional(v.string()),
        audioPath: v.optional(v.string()),
        kurdishRaw: v.optional(v.string()),
        kurdishCorrected: v.optional(v.string()),
        arabicText: v.optional(v.string()),
        arabicLocked: v.optional(v.string()),
        ttsAudioR2Key: v.optional(v.string()),
        assembledAudioR2Key: v.optional(v.string()),
        speaker: v.optional(v.string()),
        pipelineDetails: v.optional(v.string()),
        error: v.optional(v.string()),
      }),
    ),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);

    // Pird PIRD-017: derive workspaceId from the parent job doc. Reject
    // any caller-supplied workspaceId at the schema level.
    let realJobId: any = args.jobId;
    if (args.jobId.length !== 32) {
      const j = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", args.jobId))
        .first();
      if (!j) throw new ConvexError("JOB_NOT_FOUND");
      realJobId = j._id;
    }
    const jobDoc: any = await ctx.db.get(realJobId);
    if (!jobDoc) throw new ConvexError("JOB_NOT_FOUND");
    const realWorkspaceId = jobDoc.workspaceId;

    // Pird: never let `patch` override identity columns. Strip anything
    // we already control above. This is defense in depth on top of the
    // typed object schema.
    const { transcriptSrc, transcriptTgt, audioPath, kurdishRaw,
            kurdishCorrected, arabicText, arabicLocked, ttsAudioR2Key,
            assembledAudioR2Key, speaker, pipelineDetails, error } =
            args.patch ?? {};
    const docData: any = {
      legacyId: args.legacyId,
      workspaceId: realWorkspaceId,
      jobId: realJobId,
      chunkIndex: args.chunkIndex,
      startTime: args.startTime,
      endTime: args.endTime,
      status: args.status,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    if (transcriptSrc !== undefined) docData.transcriptSrc = transcriptSrc;
    if (transcriptTgt !== undefined) docData.transcriptTgt = transcriptTgt;
    if (audioPath !== undefined) docData.audioPath = audioPath;
    if (kurdishRaw !== undefined) docData.kurdishRaw = kurdishRaw;
    if (kurdishCorrected !== undefined) docData.kurdishCorrected = kurdishCorrected;
    if (arabicText !== undefined) docData.arabicText = arabicText;
    if (arabicLocked !== undefined) docData.arabicLocked = arabicLocked;
    if (ttsAudioR2Key !== undefined) docData.ttsAudioR2Key = ttsAudioR2Key;
    if (assembledAudioR2Key !== undefined) docData.assembledAudioR2Key = assembledAudioR2Key;
    if (speaker !== undefined) docData.speaker = speaker;
    if (pipelineDetails !== undefined) docData.pipelineDetails = pipelineDetails;
    if (error !== undefined) docData.error = error;
    return await ctx.db.insert("dubbingChunks", docData);
  },
});
