import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  workspaces: defineTable({
    legacyId: v.string(),
    name: v.string(),
    ownerUserId: v.optional(v.string()),
    plan: v.optional(v.string()),
    dubbingMinutes: v.optional(v.number()),
    status: v.optional(v.string()), // ACTIVE, LOCKED_REFUND, RESTRICTED_VELOCITY
    isLocked: v.optional(v.boolean()),
    totalPurchasedMinutes: v.optional(v.number()),
    createdAt: v.optional(v.string()),
    updatedAt: v.optional(v.string()),
  }).index("by_legacy_id", ["legacyId"])
    .index("by_owner", ["ownerUserId"]),

  workspaceMembers: defineTable({
    legacyId: v.string(),
    workspaceId: v.id("workspaces"),
    userId: v.string(),
    role: v.string(),
    appPermissions: v.optional(v.any()),
    createdAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_workspace_id", ["workspaceId"]),

  users: defineTable({
    legacyId: v.string(),
    clerkId: v.optional(v.string()),
    email: v.optional(v.string()),
    firstName: v.optional(v.string()),
    lastName: v.optional(v.string()),
    imageUrl: v.optional(v.string()),
    updatedAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_clerk_id", ["clerkId"])
    .index("by_email", ["email"]),

  dubbingJobs: defineTable({
    legacyId: v.string(),
    workspaceId: v.id("workspaces"),
    ownerUserId: v.optional(v.string()), // Added for tracking who created the job
    
    // Adapted from 'videos' table in user spec
    user_id: v.optional(v.string()), // Kept matching their spec, usually same as ownerUserId
    total_duration_sec: v.optional(v.number()),
    
    status: v.string(), // Kept as string to prevent frontend strict literal breakage
    progress: v.number(),
    sourceVideoR2Key: v.optional(v.string()),
    resultVideoR2Key: v.optional(v.string()),
    sourceLang: v.string(),
    targetLang: v.string(),
    ttsProvider: v.string(),
    chunksCount: v.number(),
    rollingCps: v.number(),
    error: v.optional(v.string()),
    failedStep: v.optional(v.string()),
    createdAt: v.optional(v.string()),
    updatedAt: v.optional(v.string()),
    startedAt: v.optional(v.string()),
    completedAt: v.optional(v.string()),

    // --- Financial & Latency Tracking ---
    total_processing_latency_ms: v.optional(v.number()),
    total_cost_usd: v.optional(v.number()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_workspace_id", ["workspaceId"])
    .index("by_status", ["status"]),

  dubbingChunks: defineTable({
    legacyId: v.string(),
    workspaceId: v.id("workspaces"),
    jobId: v.id("dubbingJobs"), // Corresponds to video_id
    chunkIndex: v.number(),
    
    // Physics bounds
    startTime: v.number(), // start_time_ms
    endTime: v.number(), // end_time_ms
    vad_duration_sec: v.optional(v.number()),
    speechDuration: v.optional(v.number()),

    // Audio & NLP references
    kurdish_raw_audio_url: v.optional(v.string()),
    kurdishRaw: v.optional(v.string()), // kurdish_text
    kurdish_word_count: v.optional(v.number()),
    kurdish_wps: v.optional(v.number()),
    
    // Math Provenance Audit Fields
    baseline_wps_used: v.optional(v.number()),
    speed_multiplier: v.optional(v.number()),
    target_ratio_applied: v.optional(v.number()),
    was_clamped: v.optional(v.boolean()),

    // Arabic translations
    arabicText: v.optional(v.string()), // final_arabic_text
    final_arabic_word_count: v.optional(v.number()),
    semantic_ratio: v.optional(v.number()),
    
    // Diagnostic metrics
    kurdish_syllable_count: v.optional(v.number()),
    final_arabic_syllable_count: v.optional(v.number()),
    ffmpeg_warp_factor: v.optional(v.number()),

    // Legacy fields
    kurdishCorrected: v.optional(v.string()),
    arabicLocked: v.optional(v.string()),
    ttsAudioR2Key: v.optional(v.string()),
    assembledAudioR2Key: v.optional(v.string()),
    speaker: v.optional(v.string()),
    
    status: v.string(), // string for UI compatibility
    
    pipelineDetails: v.optional(v.any()),
    error: v.optional(v.string()),
    createdAt: v.optional(v.string()),
    updatedAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_workspace_id", ["workspaceId"])
    .index("by_workspace_job", ["workspaceId", "jobId"])
    .index("by_status", ["status"]),

  translation_attempts: defineTable({
    chunk_id: v.id("dubbingChunks"),
    video_id: v.id("dubbingJobs"),
    attempt_number: v.number(),
    target_min_words: v.number(),
    target_max_words: v.number(),

    prompt_template_version: v.string(),
    rendered_prompt: v.string(),

    generated_text: v.string(),
    generated_word_count: v.number(),
    status: v.union(
      v.literal("PASSED"),
      v.literal("FAILED_OVERFLOW"),
      v.literal("FAILED_UNDERFLOW")
    ),
  })
    .index("by_chunk", ["chunk_id"])
    .index("by_video", ["video_id"]),

  step_telemetry: defineTable({
    chunk_id: v.optional(v.id("dubbingChunks")),
    step_name: v.string(), // e.g., "VAD", "STT", "LLM", "TTS", "FFMPEG"
    duration_ms: v.number(), // The exact timing of this step
    status_code: v.number(),
    
    // --- NEW: Financial & Compute Tracking ---
    compute_provider: v.string(), // e.g., "gemini_api", "runpod_serverless", "fish_audio"
    usage_units: v.optional(v.number()), // Tokens, Characters, or GPU Seconds
    cost_usd: v.number(), // The calculated price of this single step execution
  }).index("by_chunk", ["chunk_id"]),

  user_edits: defineTable({
    chunk_id: v.id("dubbingChunks"),
    edit_type: v.union(v.literal("TEXT_CHANGE"), v.literal("TIMING_SHIFT")),
    original_state: v.string(),
    final_user_state: v.string(),
  }).index("by_chunk", ["chunk_id"]),

  system_config: defineTable({
    key: v.string(),
    value: v.number(),
    sample_size: v.number(),
    updated_at: v.number(),
  }).index("by_key", ["key"]),

  ingestion_errors: defineTable({
    source_step: v.string(),
    payload: v.string(),
    error_message: v.string(),
    retry_count: v.number(),
    resolved: v.boolean(),
  }).index("by_resolved", ["resolved"]),

  voiceReferences: defineTable({
    legacyId: v.string(),
    workspaceId: v.id("workspaces"),
    name: v.string(),
    r2Key: v.string(),
    durationSeconds: v.optional(v.number()),
    calibration: v.optional(v.any()),
    createdAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_workspace_id", ["workspaceId"]),

  // Pird: voice catalog with cached intro audio (Fish Audio public voices).
  // providerVoiceId = fish audio model id (32-char hex).
  // introStorageId is set by `ensureIntro` action after the first successful
  // render. introError is set when the action fails — never a 0-byte blob.
  // introTextHash guards re-renders: same text+voice → cache hit.
  ttsVoices: defineTable({
    legacyId: v.string(),
    workspaceId: v.id("workspaces"),
    name: v.string(),
    provider: v.string(),
    providerVoiceId: v.string(),
    language: v.optional(v.string()),
    gender: v.optional(v.string()),
    description: v.optional(v.string()),
    tags: v.optional(v.array(v.string())),
    active: v.boolean(),
    introStorageId: v.optional(v.id("_storage")),
    introBytes: v.optional(v.number()),
    introTextHash: v.optional(v.string()),
    introGeneratedAt: v.optional(v.number()),
    introError: v.optional(v.string()),
    createdAt: v.optional(v.string()),
    updatedAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_workspace_id", ["workspaceId"]),

  dubbingDictionaries: defineTable({
    legacyId: v.string(),
    workspaceId: v.id("workspaces"),
    categoryId: v.string(),
    data: v.any(),
    createdAt: v.optional(v.string()),
    updatedAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_workspace_id", ["workspaceId"])
    .index("by_category", ["categoryId"]),

  aiUsageLogs: defineTable({
    legacyId: v.string(),
    workspaceId: v.optional(v.id("workspaces")),
    service: v.string(),
    context: v.string(),
    provider: v.optional(v.string()),
    inputTokens: v.optional(v.number()),
    outputTokens: v.optional(v.number()),
    estimatedCostUsd: v.optional(v.number()),
    createdAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_workspace_id", ["workspaceId"]),

  apiKeys: defineTable({
    legacyId: v.string(),
    workspaceId: v.id("workspaces"),
    keyHash: v.string(),
    label: v.optional(v.string()),
    active: v.boolean(),
    lastUsedAt: v.optional(v.string()),
    createdAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_workspace_id", ["workspaceId"]),

  transactions: defineTable({
    legacyId: v.string(),
    subyTransactionId: v.optional(v.string()),
    workspaceId: v.id("workspaces"),
    tier: v.optional(v.string()),
    amountUsd: v.optional(v.number()),
    minutesAdded: v.optional(v.number()),
    createdAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_suby_transaction_id", ["subyTransactionId"])
    .index("by_workspace_id", ["workspaceId"]),

  // PIRD-013: GDPR consent ledger. Recorded on voice upload, voice clone,
  // and any other processing of biometric data. Records the policy
  // version the user consented to so a later policy change can prompt
  // re-consent rather than silently assume continued agreement.
  consent: defineTable({
    userId: v.string(),
    workspaceId: v.id("workspaces"),
    consentType: v.string(), // e.g. "voice_recording"
    consentTextVersion: v.string(), // e.g. "2026-07-26.1"
    ipAddress: v.optional(v.string()),
    userAgent: v.optional(v.string()),
    timestamp: v.string(),
  })
    .index("by_user", ["userId"])
    .index("by_workspace", ["workspaceId"])
    .index("by_user_type", ["userId", "consentType"]),

  webhookEvents: defineTable({
    eventId: v.string(),
    eventType: v.string(),
    payload: v.any(),
    status: v.string(), // PENDING, PROCESSED, FAILED
    createdAt: v.string(),
  }).index("by_event_id", ["eventId"]),
});
