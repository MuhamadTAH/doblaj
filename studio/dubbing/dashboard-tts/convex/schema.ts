import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  workspaces: defineTable({
    legacyId: v.string(),
    name: v.optional(v.string()),
    ownerUserId: v.optional(v.string()),
    ownerId: v.optional(v.string()),
    plan: v.optional(v.string()),
    dubbingMinutes: v.optional(v.number()),
    status: v.optional(v.string()), // ACTIVE, LOCKED_REFUND, RESTRICTED_VELOCITY
    isLocked: v.optional(v.boolean()),
    totalPurchasedMinutes: v.optional(v.number()),
    createdAt: v.optional(v.string()),
    updatedAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
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
    deletedAt: v.optional(v.string()),
    isBanned: v.optional(v.boolean()),
    isLocked: v.optional(v.boolean()),
    mfaEnabled: v.optional(v.boolean()),
    telegramChatId: v.optional(v.string()),
    updatedAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_clerk_id", ["clerkId"])
    .index("by_email", ["email"])
    .index("by_deleted_created", ["deletedAt", "updatedAt"]),

  dubbingJobs: defineTable({
    legacyId: v.string(),
    workspaceId: v.id("workspaces"),
    ownerUserId: v.optional(v.string()),
    user_id: v.optional(v.string()),
    total_duration_sec: v.optional(v.number()),
    
    status: v.string(), // QUEUED, PROCESSING, COMPLETED, FAILED, DEAD_LETTER, CANCELLED_PURGED
    progress: v.number(),
    sourceVideoR2Key: v.optional(v.string()),
    resultVideoR2Key: v.optional(v.string()),
    bgAudioR2Key: v.optional(v.string()),
    isolatedVocalsR2Key: v.optional(v.string()),
    sourceLang: v.string(),
    targetLang: v.string(),
    ttsProvider: v.string(),
    chunksCount: v.number(),
    rollingCps: v.number(),
    error: v.optional(v.string()),
    failedStep: v.optional(v.string()),
    consentVersion: v.optional(v.string()),
    userIpAddress: v.optional(v.string()),
    consentTimestamp: v.optional(v.string()),
    
    // --- Hardening & DLQ Fields ---
    retry_count: v.optional(v.number()),
    max_retries: v.optional(v.number()),
    api_cost: v.optional(v.number()),
    overrideParams: v.optional(v.any()),
    isPurged: v.optional(v.boolean()),
    deletedAt: v.optional(v.string()),

    createdAt: v.optional(v.string()),
    updatedAt: v.optional(v.string()),
    startedAt: v.optional(v.string()),
    completedAt: v.optional(v.string()),

    total_processing_latency_ms: v.optional(v.number()),
    total_cost_usd: v.optional(v.number()),
    mediaMetadata: v.optional(v.any()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_workspace_id", ["workspaceId"])
    .index("by_workspace_and_created", ["workspaceId", "createdAt"])
    .index("by_status", ["status"])
    .index("by_status_created", ["status", "createdAt"])
    .index("by_created", ["createdAt"]),

  dubbingChunks: defineTable({
    legacyId: v.string(),
    workspaceId: v.id("workspaces"),
    jobId: v.id("dubbingJobs"),
    chunkIndex: v.number(),
    
    startTime: v.number(),
    endTime: v.number(),
    vad_duration_sec: v.optional(v.number()),
    speechDuration: v.optional(v.number()),

    kurdish_raw_audio_url: v.optional(v.string()),
    kurdishRaw: v.optional(v.string()),
    kurdish_word_count: v.optional(v.number()),
    kurdish_wps: v.optional(v.number()),
    
    baseline_wps_used: v.optional(v.number()),
    speed_multiplier: v.optional(v.number()),
    target_ratio_applied: v.optional(v.number()),
    was_clamped: v.optional(v.boolean()),

    arabicText: v.optional(v.string()),
    final_arabic_word_count: v.optional(v.number()),
    semantic_ratio: v.optional(v.number()),
    
    kurdish_syllable_count: v.optional(v.number()),
    final_arabic_syllable_count: v.optional(v.number()),
    ffmpeg_warp_factor: v.optional(v.number()),

    kurdishCorrected: v.optional(v.string()),
    arabicLocked: v.optional(v.string()),
    ttsAudioR2Key: v.optional(v.string()),
    assembledAudioR2Key: v.optional(v.string()),
    speaker: v.optional(v.string()),
    
    status: v.string(),
    
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
    step_name: v.string(),
    duration_ms: v.number(),
    status_code: v.number(),
    compute_provider: v.string(),
    usage_units: v.optional(v.number()),
    cost_usd: v.number(),
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
    referenceId: v.optional(v.string()),
    subyTransactionId: v.optional(v.string()),
    workspaceId: v.id("workspaces"),
    tier: v.optional(v.string()),
    amountUsd: v.optional(v.number()),
    amount: v.optional(v.number()),
    currency: v.optional(v.string()),
    minutesAdded: v.optional(v.number()),
    status: v.optional(v.string()), // "complete", "refunded", "flagged"
    createdAt: v.optional(v.string()),
  })
    .index("by_legacy_id", ["legacyId"])
    .index("by_reference_id", ["referenceId"])
    .index("by_suby_transaction_id", ["subyTransactionId"])
    .index("by_workspace_id", ["workspaceId"]),

  expectedCharges: defineTable({
    referenceId: v.string(),
    workspaceId: v.id("workspaces"),
    amount: v.number(),
    currency: v.string(),
    minutesGranted: v.number(),
    tier: v.string(),
    status: v.string(),
    createdAt: v.string(),
  })
    .index("by_reference_id", ["referenceId"])
    .index("by_workspace_id", ["workspaceId"])
    .index("by_status", ["status"])
    .index("by_status_and_created", ["status", "createdAt"]),

  ledger: defineTable({
    workspaceId: v.id("workspaces"),
    referenceId: v.optional(v.string()),
    delta: v.number(),
    type: v.string(),
    resultingBalance: v.number(),
    actor: v.string(),
    createdAt: v.number(),
  })
    .index("by_workspace_id", ["workspaceId"])
    .index("by_reference_id", ["referenceId"]),

  securityAlerts: defineTable({
    type: v.string(),
    referenceId: v.optional(v.string()),
    details: v.any(),
    createdAt: v.number(),
  })
    .index("by_type", ["type"])
    .index("by_reference_id", ["referenceId"]),

  manualReviewQueue: defineTable({
    referenceId: v.string(),
    workspaceId: v.id("workspaces"),
    amount: v.number(),
    currency: v.string(),
    minutesGranted: v.number(),
    tier: v.string(),
    reason: v.string(),
    status: v.string(),
    lastKnownWaylStatus: v.optional(v.string()),
    createdAt: v.number(),
    resolvedAt: v.optional(v.number()),
  })
    .index("by_reference_id", ["referenceId"])
    .index("by_workspace_id", ["workspaceId"])
    .index("by_status", ["status"]),

  consent: defineTable({
    userId: v.string(),
    workspaceId: v.id("workspaces"),
    consentType: v.string(),
    consentTextVersion: v.string(),
    ipAddress: v.optional(v.string()),
    userAgent: v.optional(v.string()),
    timestamp: v.string(),
  })
    .index("by_user", ["userId"])
    .index("by_workspace", ["workspaceId"])
    .index("by_user_type", ["userId", "consentType"]),

  webhookEvents: defineTable({
    referenceId: v.optional(v.string()),
    eventId: v.optional(v.string()),
    eventType: v.optional(v.string()),
    payload: v.optional(v.any()),
    status: v.optional(v.string()),
    rawPayload: v.optional(v.string()),
    receivedAt: v.optional(v.number()),
    createdAt: v.optional(v.string()),
  })
    .index("by_reference_id", ["referenceId"])
    .index("by_event_id", ["eventId"]),

  // ==========================================
  // --- ADMIN PORTAL & ZERO-TRUST TABLES ---
  // ==========================================

  adminRoles: defineTable({
    legacyId: v.string(),
    name: v.string(), // "Super Admin", "Tier 1 Support", "Financial Controller", "Pipeline Operator"
    description: v.optional(v.string()),
    createdAt: v.string(),
  }).index("by_name", ["name"]),

  adminPermissions: defineTable({
    action: v.string(), // "users:impersonate", "billing:refund", "jobs:retry", "jobs:nuke", "admin:all"
    description: v.optional(v.string()),
    createdAt: v.string(),
  }).index("by_action", ["action"]),

  adminRolePermissions: defineTable({
    roleId: v.id("adminRoles"),
    permissionId: v.id("adminPermissions"),
  }).index("by_role", ["roleId"]),

  adminUserRoles: defineTable({
    userId: v.string(), // Clerk user id (e.g. "user_2...")
    roleId: v.id("adminRoles"),
    assignedBy: v.optional(v.string()),
    assignedAt: v.string(),
  }).index("by_user", ["userId"]),

  adminSessions: defineTable({
    sessionToken: v.string(),
    userId: v.string(),
    email: v.string(),
    isValid: v.boolean(),
    ipAddress: v.optional(v.string()),
    userAgent: v.optional(v.string()),
    expiresAt: v.number(),
    createdAt: v.string(),
  })
    .index("by_token", ["sessionToken"])
    .index("by_user", ["userId"]),

  adminAuditLogs: defineTable({
    actorId: v.string(),
    actorEmail: v.string(),
    action: v.string(),
    targetResource: v.string(), // "users", "dubbingJobs", "workspaces", "featureFlags", "transactions"
    targetId: v.optional(v.string()),
    changedFields: v.optional(v.any()), // e.g. { "dubbingMinutes": { "old": 15, "new": 100 } }
    metadata: v.optional(v.any()), // { ipAddress, userAgent, reason, impersonatorId }
    createdAt: v.string(),
  })
    .index("by_target_created", ["targetResource", "createdAt"])
    .index("by_actor_created", ["actorId", "createdAt"])
    .index("by_created", ["createdAt"]),

  auditOutbox: defineTable({
    eventId: v.string(),
    action: v.string(),
    actorId: v.string(),
    actorEmail: v.string(),
    targetResource: v.string(),
    targetId: v.optional(v.string()),
    changedFields: v.optional(v.any()),
    metadata: v.optional(v.any()),
    status: v.union(v.literal("PENDING"), v.literal("DELIVERED"), v.literal("FAILED")),
    retryCount: v.number(),
    lastAttemptAt: v.optional(v.number()),
    deliveredAt: v.optional(v.number()),
    createdAt: v.number(),
  })
    .index("by_status", ["status"])
    .index("by_status_created", ["status", "createdAt"]),

  adminPinSecurity: defineTable({
    userId: v.string(), // Clerk user ID (e.g. user_2...)
    email: v.string(),
    argon2Hash: v.string(), // Memory-hard Argon2id hash
    failedAttempts: v.number(), // Strike counter 0..5
    lockedUntil: v.optional(v.number()), // Timestamp ms if temporarily locked
    isPermanentlyLocked: v.boolean(), // True if >= 5 failed attempts
    lastVerifiedAt: v.optional(v.number()),
    createdAt: v.string(),
    updatedAt: v.string(),
  }).index("by_user", ["userId"]),

  actionApprovals: defineTable({
    legacyId: v.string(),
    requestedBy: v.string(), // Clerk User ID
    requestedByEmail: v.optional(v.string()),
    actionType: v.string(), // "REFUND", "NUKE_JOB", "USER_PURGE", "CRITICAL_FEATURE_FLAG_TOGGLE"
    payload: v.any(), // Locked immutable action payload
    thresholdUsd: v.optional(v.number()),
    status: v.union(v.literal("PENDING"), v.literal("APPROVED"), v.literal("REJECTED")),
    approvedBy: v.optional(v.string()),
    approvedByEmail: v.optional(v.string()),
    rejectedBy: v.optional(v.string()),
    reason: v.optional(v.string()),
    createdAt: v.string(),
    resolvedAt: v.optional(v.string()),
  })
    .index("by_status", ["status"])
    .index("by_status_created", ["status", "createdAt"]),

  featureFlags: defineTable({
    keyName: v.string(), // e.g. "RUNPOD_GPU_PROCESSING", "ACCEPT_NEW_JOBS", "ENABLE_FISH_AUDIO"
    description: v.optional(v.string()),
    tier: v.union(v.literal("TIER_1_OPERATIONAL"), v.literal("TIER_2_INFRASTRUCTURE")),
    isActive: v.boolean(),
    updatedBy: v.string(),
    updatedAt: v.string(),
  }).index("by_key", ["keyName"]),

  telegramSessions: defineTable({
    chatId: v.string(),
    workspaceId: v.optional(v.id("workspaces")),
    userId: v.optional(v.string()),
    isBotPaused: v.boolean(),
    botPausedUntil: v.optional(v.number()),
    lastMessage: v.optional(v.string()),
    updatedAt: v.string(),
  }).index("by_chat_id", ["chatId"]),

  telegramInteractions: defineTable({
    chatId: v.string(),
    sender: v.string(), // "USER" | "BOT" | "OPERATOR"
    message: v.string(),
    isHuman: v.boolean(),
    createdAt: v.string(),
  }).index("by_chat_id", ["chatId"]),

  migrationState: defineTable({
    name: v.string(), // e.g. "backfill_job_defaults_v1"
    lastProcessedCursor: v.optional(v.string()),
    processedCount: v.number(),
    totalRecords: v.optional(v.number()),
    batchSize: v.number(), // 500, 250, 50
    consecutiveBatchFailures: v.number(),
    status: v.union(
      v.literal("PENDING"),
      v.literal("RUNNING"),
      v.literal("PAUSED"),
      v.literal("FAILED_POISON_PILL"),
      v.literal("COMPLETED")
    ),
    errorLog: v.optional(
      v.array(
        v.object({
          recordId: v.string(),
          error: v.string(),
          timestamp: v.string(),
        })
      )
    ),
    startedAt: v.string(),
    updatedAt: v.string(),
    completedAt: v.optional(v.string()),
  }).index("by_name", ["name"]),
});
