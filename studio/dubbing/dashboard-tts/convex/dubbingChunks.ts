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
    expectedWorkspaceId: v.optional(v.string()),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const chunkId = await resolveChunkId(ctx, args.chunkId);
    const existing = await ctx.db.get(chunkId);
    if (!existing) throw new ConvexError("CHUNK_NOT_FOUND");
    // PIRD-017 follow-up, Part03: refuse the write when the caller
    // declared a workspace that does not own the chunk. Chunks derive
    // their workspaceId from the parent job, so we compare the chunk's
    // workspaceId directly against the expected id (no resolveWorkspaceId
    // call needed — the chunk's workspaceId is already a resolved
    // Convex Id<"workspaces">).
    if (args.expectedWorkspaceId) {
      // Resolve the expected id once for canonical comparison.
      const normalized = ctx.db.normalizeId("workspaces", args.expectedWorkspaceId);
      const expectedCanonical = normalized ?? args.expectedWorkspaceId;
      if (existing.workspaceId !== expectedCanonical) {
        throw new ConvexError("WORKSPACE_MISMATCH");
      }
    }
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

export const claimNextBatchInternal = mutation({
  args: {
    jobId: v.string(),
    batchSize: v.optional(v.number()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    let realJobId: any = args.jobId;
    if (args.jobId.length !== 32) {
      const j = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", args.jobId))
        .first();
      if (j) realJobId = j._id;
    }

    const batchLimit = args.batchSize ?? 5;
    const now = Date.now();
    const staleLockThreshold = now - 5 * 60 * 1000; // 5 minutes

    const allChunks = await ctx.db
      .query("dubbingChunks")
      .filter((q: any) =>
        q.or(q.eq(q.field("jobId"), realJobId), q.eq(q.field("jobId"), args.jobId))
      )
      .collect();

    // Sort by chunkIndex asc
    allChunks.sort((a, b) => a.chunkIndex - b.chunkIndex);

    const eligible = allChunks.filter((c: any) => {
      const s = (c.status || "").toUpperCase();
      if (s === "PENDING_ASR" || s === "PENDING_TRANSLATION" || s === "PENDING") {
        return true;
      }
      // Re-claim stale locked chunks
      if ((s === "TRANSLATING" || s === "PROCESSING") && (!c.lockedAt || c.lockedAt < staleLockThreshold)) {
        return true;
      }
      return false;
    });

    const claimed = eligible.slice(0, batchLimit);
    const results = [];

    for (const chunk of claimed) {
      await ctx.db.patch(chunk._id, {
        status: "TRANSLATING",
        lockedAt: now,
        updatedAt: new Date().toISOString(),
      });
      const updated = await ctx.db.get(chunk._id);
      results.push(updated);
    }

    return results;
  },
});

export const completeTranslationInternal = mutation({
  args: {
    jobId: v.string(),
    chunkIndex: v.number(),
    sourceText: v.optional(v.string()),
    kurdishText: v.optional(v.string()),
    isEmptyOrSilence: v.boolean(),
    error: v.optional(v.string()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    let realJobId: any = args.jobId;
    if (args.jobId.length !== 32) {
      const j = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", args.jobId))
        .first();
      if (j) realJobId = j._id;
    }

    const chunk = await ctx.db
      .query("dubbingChunks")
      .filter((q: any) =>
        q.and(
          q.or(q.eq(q.field("jobId"), realJobId), q.eq(q.field("jobId"), args.jobId)),
          q.eq(q.field("chunkIndex"), args.chunkIndex)
        )
      )
      .first();

    if (!chunk) throw new ConvexError("CHUNK_NOT_FOUND");

    const nowIso = new Date().toISOString();
    const patch: Record<string, any> = {
      updatedAt: nowIso,
    };

    if (args.error) {
      patch.status = "FAILED";
      patch.error = args.error;
    } else if (args.isEmptyOrSilence) {
      patch.status = "SKIPPED";
      patch.kurdishRaw = "[بێدەنگی]";
      patch.kurdishText = "[بێدەنگی]";
      patch.sourceText = args.sourceText || "[بێدەنگی]";
      patch.transcriptSrc = args.sourceText || "[بێدەنگی]";
    } else {
      patch.status = "PENDING_TTS";
      patch.kurdishRaw = args.kurdishText || "";
      patch.kurdishText = args.kurdishText || "";
      patch.sourceText = args.sourceText || "";
      patch.transcriptSrc = args.sourceText || "";
    }

    await ctx.db.patch(chunk._id, patch);

    // Parent Job Evaluation
    const allJobChunks = await ctx.db
      .query("dubbingChunks")
      .filter((q: any) =>
        q.or(q.eq(q.field("jobId"), realJobId), q.eq(q.field("jobId"), args.jobId))
      )
      .collect();

    const nonFinished = allJobChunks.filter((c: any) => {
      const s = (c.status || "").toUpperCase();
      return !["PENDING_TTS", "SKIPPED", "COMPLETED", "TRANSCRIPTION_COMPLETE", "FAILED"].includes(s);
    });

    if (allJobChunks.length > 0 && nonFinished.length === 0) {
      await ctx.db.patch(realJobId, {
        status: "TRANSLATION_COMPLETE",
        progress: 50,
        updatedAt: nowIso,
      });
    }

    return await ctx.db.get(chunk._id);
  },
});

export const updateChunkByIndexInternal = mutation({
  args: {
    jobId: v.string(),
    chunkIndex: v.number(),
    status: v.string(),
    patch: v.optional(v.any()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    let realJobId: any = args.jobId;
    if (args.jobId.length !== 32) {
      const j = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", args.jobId))
        .first();
      if (j) realJobId = j._id;
    }
    const chunk = await ctx.db
      .query("dubbingChunks")
      .filter((q: any) =>
        q.and(
          q.or(q.eq(q.field("jobId"), realJobId), q.eq(q.field("jobId"), args.jobId)),
          q.eq(q.field("chunkIndex"), args.chunkIndex)
        )
      )
      .first();
    if (!chunk) throw new ConvexError("CHUNK_NOT_FOUND");
    const safePatch: Record<string, unknown> = {
      status: args.status,
      updatedAt: new Date().toISOString(),
    };
    if (args.patch) {
      for (const [k, v] of Object.entries(args.patch)) {
        safePatch[k] = v;
      }
    }
    await ctx.db.patch(chunk._id, safePatch);
    return await ctx.db.get(chunk._id);
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
        kurdish_raw_audio_url: v.optional(v.string()),
        kurdish_word_count: v.optional(v.number()),
        kurdish_wps: v.optional(v.number()),
        baseline_wps_used: v.optional(v.number()),
        speed_multiplier: v.optional(v.number()),
        target_ratio_applied: v.optional(v.number()),
        was_clamped: v.optional(v.boolean()),
        final_arabic_word_count: v.optional(v.number()),
        semantic_ratio: v.optional(v.number()),
        kurdish_syllable_count: v.optional(v.number()),
        final_arabic_syllable_count: v.optional(v.number()),
        ffmpeg_warp_factor: v.optional(v.number()),
        vad_duration_sec: v.optional(v.number()),
        speechDuration: v.optional(v.number()),
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
            assembledAudioR2Key, speaker, pipelineDetails, error,
            kurdish_raw_audio_url, kurdish_word_count, kurdish_wps,
            baseline_wps_used, speed_multiplier, target_ratio_applied, was_clamped,
            final_arabic_word_count, semantic_ratio, kurdish_syllable_count,
            final_arabic_syllable_count, ffmpeg_warp_factor, vad_duration_sec,
            speechDuration } =
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
    if (kurdish_raw_audio_url !== undefined) docData.kurdish_raw_audio_url = kurdish_raw_audio_url;
    if (kurdish_word_count !== undefined) docData.kurdish_word_count = kurdish_word_count;
    if (kurdish_wps !== undefined) docData.kurdish_wps = kurdish_wps;
    if (baseline_wps_used !== undefined) docData.baseline_wps_used = baseline_wps_used;
    if (speed_multiplier !== undefined) docData.speed_multiplier = speed_multiplier;
    if (target_ratio_applied !== undefined) docData.target_ratio_applied = target_ratio_applied;
    if (was_clamped !== undefined) docData.was_clamped = was_clamped;
    if (final_arabic_word_count !== undefined) docData.final_arabic_word_count = final_arabic_word_count;
    if (semantic_ratio !== undefined) docData.semantic_ratio = semantic_ratio;
    if (kurdish_syllable_count !== undefined) docData.kurdish_syllable_count = kurdish_syllable_count;
    if (final_arabic_syllable_count !== undefined) docData.final_arabic_syllable_count = final_arabic_syllable_count;
    if (ffmpeg_warp_factor !== undefined) docData.ffmpeg_warp_factor = ffmpeg_warp_factor;
    if (vad_duration_sec !== undefined) docData.vad_duration_sec = vad_duration_sec;
    if (speechDuration !== undefined) docData.speechDuration = speechDuration;
    
    return await ctx.db.insert("dubbingChunks", docData);
  },
});

export const batchInsertChunksInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    jobId: v.string(),
    bgAudioR2Key: v.optional(v.string()),
    isolatedVocalsR2Key: v.optional(v.string()),
    chunks: v.array(
      v.object({
        legacyId: v.string(),
        chunkIndex: v.number(),
        startTime: v.number(),
        endTime: v.number(),
        speechDuration: v.number(),
        vad_duration_sec: v.optional(v.number()),
        kurdish_raw_audio_url: v.optional(v.string()),
        ttsAudioR2Key: v.optional(v.string()),
        status: v.string(),
      })
    ),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
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

    // Delete any existing old chunks for this job (idempotent overwrite on retry)
    const existingChunks = await ctx.db
      .query("dubbingChunks")
      .withIndex("by_workspace_job", (q) =>
        q.eq("workspaceId", realWorkspaceId).eq("jobId", realJobId)
      )
      .collect();
    for (const ec of existingChunks) {
      await ctx.db.delete(ec._id);
    }

    const insertedIds = [];
    const now = new Date().toISOString();

    for (const c of args.chunks) {
      const id = await ctx.db.insert("dubbingChunks", {
        legacyId: c.legacyId,
        workspaceId: realWorkspaceId,
        jobId: realJobId,
        chunkIndex: c.chunkIndex,
        startTime: c.startTime,
        endTime: c.endTime,
        speechDuration: c.speechDuration,
        vad_duration_sec: c.vad_duration_sec ?? c.speechDuration,
        kurdish_raw_audio_url: c.kurdish_raw_audio_url,
        ttsAudioR2Key: c.ttsAudioR2Key,
        status: c.status,
        createdAt: now,
        updatedAt: now,
      });
      insertedIds.push(id);
    }

    const jobPatch: Record<string, any> = {
      status: "SEPARATION_COMPLETE",
      progress: 25,
      chunksCount: args.chunks.length,
      updatedAt: now,
    };
    if (args.bgAudioR2Key) jobPatch.bgAudioR2Key = args.bgAudioR2Key;
    if (args.isolatedVocalsR2Key) jobPatch.isolatedVocalsR2Key = args.isolatedVocalsR2Key;

    await ctx.db.patch(realJobId, jobPatch);

    return { success: true, count: insertedIds.length, chunkIds: insertedIds };
  },
});
