import { mutation, internalMutation, query, internalQuery } from "./_generated/server";
import { ConvexError, v } from "convex/values";
import { paginationOptsValidator } from "convex/server";
import { requireInternalApiKey } from "./lib/auth";

/**
 * Pird Dubbing Platform — Zero-Trust Admin Mutations & Procedures
 */

export async function checkAdminIdentity(ctx: { auth: { getUserIdentity: () => Promise<any> }; db: any }) {
  const identity = await ctx.auth.getUserIdentity();
  if (!identity) {
    throw new ConvexError("UNAUTHENTICATED");
  }
  const user = await ctx.db
    .query("users")
    .withIndex("by_clerk_id", (q: any) => q.eq("clerkId", identity.subject))
    .unique();

  // Check if user has an active adminUserRoles record or clerkId in admin list
  const adminRole = await ctx.db
    .query("adminUserRoles")
    .withIndex("by_user", (q: any) => q.eq("userId", identity.subject))
    .first();

  const isRoleAdmin = identity.app_role === "admin" || identity.app_role === "org:admin";
  const allowed = (process.env.ADMIN_CLERK_IDS ?? "").split(",").map((s: string) => s.trim()).filter(Boolean);
  const isEnvAdmin = allowed.includes(identity.subject);

  if (!adminRole && !isRoleAdmin && !isEnvAdmin) {
    throw new ConvexError("FORBIDDEN: Admin privileges required");
  }

  return { identity, user, adminRole };
}

// -------------------------------------------------------------
// Transactional Delta Audit Logger Helper
// -------------------------------------------------------------
export async function logAuditWithOutbox(
  ctx: { db: any },
  args: {
    actorId: string;
    actorEmail: string;
    action: string;
    targetResource: string;
    targetId?: string;
    changedFields?: any;
    metadata?: any;
  }
) {
  const nowStr = new Date().toISOString();
  const nowNum = Date.now();
  const eventId = crypto.randomUUID();

  // 1. Write to Convex adminAuditLogs for fast UI rendering
  await ctx.db.insert("adminAuditLogs", {
    actorId: args.actorId,
    actorEmail: args.actorEmail,
    action: args.action,
    targetResource: args.targetResource,
    targetId: args.targetId,
    changedFields: args.changedFields,
    metadata: args.metadata,
    createdAt: nowStr,
  });

  // 2. Write to auditOutbox for asynchronous, guaranteed delivery to external WORM SIEM
  await ctx.db.insert("auditOutbox", {
    eventId,
    action: args.action,
    actorId: args.actorId,
    actorEmail: args.actorEmail,
    targetResource: args.targetResource,
    targetId: args.targetId,
    changedFields: args.changedFields,
    metadata: args.metadata,
    status: "PENDING",
    retryCount: 0,
    createdAt: nowNum,
  });
}

// -------------------------------------------------------------
// Job Operations & DLQ Mutations
// -------------------------------------------------------------
export const retryJobInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    jobId: v.id("dubbingJobs"),
    actorId: v.string(),
    actorEmail: v.string(),
    overrideParams: v.optional(v.any()),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const job = await ctx.db.get(args.jobId);
    if (!job) throw new ConvexError("JOB_NOT_FOUND");

    const oldStatus = job.status;
    await ctx.db.patch(args.jobId, {
      status: "QUEUED",
      retry_count: 0,
      overrideParams: args.overrideParams ?? job.overrideParams,
      error: undefined,
      failedStep: undefined,
      updatedAt: new Date().toISOString(),
    });

    await logAuditWithOutbox(ctx, {
      actorId: args.actorId,
      actorEmail: args.actorEmail,
      action: "JOB_FORCE_RETRY",
      targetResource: "dubbingJobs",
      targetId: args.jobId,
      changedFields: {
        status: { old: oldStatus, new: "QUEUED" },
        retry_count: { old: job.retry_count ?? 0, new: 0 },
        overrideParams: { old: job.overrideParams, new: args.overrideParams },
      },
    });

    return { success: true, jobId: args.jobId };
  },
});

export const failJobInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    jobId: v.id("dubbingJobs"),
    reason: v.string(),
    actorId: v.string(),
    actorEmail: v.string(),
    refundMinutes: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const job = await ctx.db.get(args.jobId);
    if (!job) throw new ConvexError("JOB_NOT_FOUND");

    const oldStatus = job.status;
    await ctx.db.patch(args.jobId, {
      status: "FAILED",
      error: args.reason,
      updatedAt: new Date().toISOString(),
    });

    // If refund requested, adjust workspace balance
    if (args.refundMinutes && args.refundMinutes > 0 && job.workspaceId) {
      const ws = await ctx.db.get(job.workspaceId);
      if (ws) {
        const oldBal = ws.dubbingMinutes ?? 0;
        const newBal = oldBal + args.refundMinutes;
        await ctx.db.patch(ws._id, { dubbingMinutes: newBal });

        await ctx.db.insert("ledger", {
          workspaceId: ws._id,
          referenceId: job.legacyId,
          delta: args.refundMinutes,
          type: "refund",
          resultingBalance: newBal,
          actor: `admin:${args.actorEmail}`,
          createdAt: Date.now(),
        });
      }
    }

    await logAuditWithOutbox(ctx, {
      actorId: args.actorId,
      actorEmail: args.actorEmail,
      action: "JOB_MARK_FAILED",
      targetResource: "dubbingJobs",
      targetId: args.jobId,
      changedFields: {
        status: { old: oldStatus, new: "FAILED" },
        error: { old: job.error, new: args.reason },
      },
    });

    return { success: true };
  },
});

export const nukeJobInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    jobId: v.id("dubbingJobs"),
    actorId: v.string(),
    actorEmail: v.string(),
    reason: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const job = await ctx.db.get(args.jobId);
    if (!job) throw new ConvexError("JOB_NOT_FOUND");

    const now = new Date().toISOString();

    // 1. Mark job as CANCELLED_PURGED
    await ctx.db.patch(args.jobId, {
      status: "CANCELLED_PURGED",
      isPurged: true,
      error: `NUKE: ${args.reason}`,
      updatedAt: now,
    });

    // 2. Ban & soft-delete user if associated
    if (job.ownerUserId) {
      const user = await ctx.db
        .query("users")
        .withIndex("by_clerk_id", (q: any) => q.eq("clerkId", job.ownerUserId))
        .first();
      if (user) {
        await ctx.db.patch(user._id, {
          isBanned: true,
          deletedAt: now,
          updatedAt: now,
        });
      }
    }

    // 3. Security alert entry
    await ctx.db.insert("securityAlerts", {
      type: "POISON_PILL_NUKE",
      referenceId: job.legacyId,
      details: {
        jobId: args.jobId,
        actorEmail: args.actorEmail,
        reason: args.reason,
        ownerUserId: job.ownerUserId,
      },
      createdAt: Date.now(),
    });

    // 4. Log audit outbox
    await logAuditWithOutbox(ctx, {
      actorId: args.actorId,
      actorEmail: args.actorEmail,
      action: "JOB_NUKE_AND_BAN",
      targetResource: "dubbingJobs",
      targetId: args.jobId,
      changedFields: {
        status: { old: job.status, new: "CANCELLED_PURGED" },
        isPurged: { old: false, new: true },
      },
      metadata: { reason: args.reason, ownerUserId: job.ownerUserId },
    });

    return {
      success: true,
      sourceVideoR2Key: job.sourceVideoR2Key,
      resultVideoR2Key: job.resultVideoR2Key,
      ownerUserId: job.ownerUserId,
    };
  },
});

// -------------------------------------------------------------
// User Intelligence & CRM Mutations
// -------------------------------------------------------------
export const adjustUserBalanceInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    userId: v.string(), // Clerk ID
    deltaMinutes: v.number(),
    reason: v.string(),
    actorId: v.string(),
    actorEmail: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);

    const ws = await ctx.db
      .query("workspaces")
      .withIndex("by_owner", (q: any) => q.eq("ownerUserId", args.userId))
      .first();

    if (!ws) throw new ConvexError("WORKSPACE_NOT_FOUND_FOR_USER");

    const oldBalance = ws.dubbingMinutes ?? 0;
    const newBalance = Math.max(0, oldBalance + args.deltaMinutes);

    await ctx.db.patch(ws._id, {
      dubbingMinutes: newBalance,
      updatedAt: new Date().toISOString(),
    });

    await ctx.db.insert("ledger", {
      workspaceId: ws._id,
      delta: args.deltaMinutes,
      type: "manual_adjustment",
      resultingBalance: newBalance,
      actor: `admin:${args.actorEmail}`,
      createdAt: Date.now(),
    });

    await logAuditWithOutbox(ctx, {
      actorId: args.actorId,
      actorEmail: args.actorEmail,
      action: "USER_BALANCE_ADJUSTMENT",
      targetResource: "workspaces",
      targetId: ws._id,
      changedFields: {
        dubbingMinutes: { old: oldBalance, new: newBalance },
      },
      metadata: { reason: args.reason, userId: args.userId },
    });

    return { success: true, newBalance };
  },
});

export const setUserBanStatusInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    userId: v.string(),
    isBanned: v.boolean(),
    actorId: v.string(),
    actorEmail: v.string(),
    reason: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const user = await ctx.db
      .query("users")
      .withIndex("by_clerk_id", (q: any) => q.eq("clerkId", args.userId))
      .first();

    if (!user) throw new ConvexError("USER_NOT_FOUND");

    const oldBanned = user.isBanned ?? false;
    const now = new Date().toISOString();

    await ctx.db.patch(user._id, {
      isBanned: args.isBanned,
      deletedAt: args.isBanned ? now : undefined,
      updatedAt: now,
    });

    await logAuditWithOutbox(ctx, {
      actorId: args.actorId,
      actorEmail: args.actorEmail,
      action: args.isBanned ? "USER_BAN" : "USER_UNBAN",
      targetResource: "users",
      targetId: user._id,
      changedFields: {
        isBanned: { old: oldBanned, new: args.isBanned },
      },
      metadata: { reason: args.reason },
    });

    return { success: true };
  },
});

// -------------------------------------------------------------
// Dual-Signoff Action Approvals Mutations
// -------------------------------------------------------------
export const createActionApprovalInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    requestedBy: v.string(),
    requestedByEmail: v.string(),
    actionType: v.string(),
    payload: v.any(),
    thresholdUsd: v.optional(v.number()),
    reason: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const legacyId = crypto.randomUUID();
    const now = new Date().toISOString();

    const approvalId = await ctx.db.insert("actionApprovals", {
      legacyId,
      requestedBy: args.requestedBy,
      requestedByEmail: args.requestedByEmail,
      actionType: args.actionType,
      payload: args.payload,
      thresholdUsd: args.thresholdUsd,
      status: "PENDING",
      reason: args.reason,
      createdAt: now,
    });

    await logAuditWithOutbox(ctx, {
      actorId: args.requestedBy,
      actorEmail: args.requestedByEmail,
      action: "ACTION_APPROVAL_REQUESTED",
      targetResource: "actionApprovals",
      targetId: approvalId,
      metadata: { actionType: args.actionType, payload: args.payload },
    });

    return { approvalId, legacyId };
  },
});

export const resolveActionApprovalInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    approvalId: v.id("actionApprovals"),
    status: v.union(v.literal("APPROVED"), v.literal("REJECTED")),
    resolvedBy: v.string(),
    resolvedByEmail: v.string(),
    reason: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const ticket = await ctx.db.get(args.approvalId);
    if (!ticket) throw new ConvexError("APPROVAL_TICKET_NOT_FOUND");
    if (ticket.status !== "PENDING") throw new ConvexError("TICKET_ALREADY_RESOLVED");

    // Strict Anti-Self-Approval Enforcement
    if (ticket.requestedBy === args.resolvedBy) {
      throw new ConvexError("ANTI_SELF_APPROVAL_VIOLATION: Requester cannot approve their own action.");
    }

    const now = new Date().toISOString();
    await ctx.db.patch(args.approvalId, {
      status: args.status,
      approvedBy: args.status === "APPROVED" ? args.resolvedBy : undefined,
      approvedByEmail: args.status === "APPROVED" ? args.resolvedByEmail : undefined,
      rejectedBy: args.status === "REJECTED" ? args.resolvedBy : undefined,
      resolvedAt: now,
    });

    await logAuditWithOutbox(ctx, {
      actorId: args.resolvedBy,
      actorEmail: args.resolvedByEmail,
      action: args.status === "APPROVED" ? "ACTION_APPROVAL_GRANTED" : "ACTION_APPROVAL_REJECTED",
      targetResource: "actionApprovals",
      targetId: args.approvalId,
      changedFields: {
        status: { old: "PENDING", new: args.status },
      },
      metadata: {
        actionType: ticket.actionType,
        requestedBy: ticket.requestedBy,
        lockedPayload: ticket.payload,
      },
    });

    return { success: true, ticket };
  },
});

// -------------------------------------------------------------
// Tiered Feature Flags Mutations
// -------------------------------------------------------------
export const setFeatureFlagInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    keyName: v.string(),
    isActive: v.boolean(),
    actorId: v.string(),
    actorEmail: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const now = new Date().toISOString();

    const existing = await ctx.db
      .query("featureFlags")
      .withIndex("by_key", (q: any) => q.eq("keyName", args.keyName))
      .first();

    if (existing) {
      const oldVal = existing.isActive;
      await ctx.db.patch(existing._id, {
        isActive: args.isActive,
        updatedBy: args.actorEmail,
        updatedAt: now,
      });

      await logAuditWithOutbox(ctx, {
        actorId: args.actorId,
        actorEmail: args.actorEmail,
        action: "FEATURE_FLAG_TOGGLE",
        targetResource: "featureFlags",
        targetId: existing._id,
        changedFields: {
          isActive: { old: oldVal, new: args.isActive },
        },
      });
    } else {
      await ctx.db.insert("featureFlags", {
        keyName: args.keyName,
        tier: args.keyName.startsWith("INFRA_") || args.keyName.includes("GPU") ? "TIER_2_INFRASTRUCTURE" : "TIER_1_OPERATIONAL",
        isActive: args.isActive,
        updatedBy: args.actorEmail,
        updatedAt: now,
      });
    }

    return { success: true };
  },
});

// -------------------------------------------------------------
// Telegram Command Center & Takeover
// -------------------------------------------------------------
export const setTelegramTakeoverInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    chatId: v.string(),
    isBotPaused: v.boolean(),
    pauseDurationMs: v.optional(v.number()), // default 3600000 (1 hour)
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const now = Date.now();
    const botPausedUntil = args.isBotPaused ? now + (args.pauseDurationMs ?? 3600000) : undefined;

    const session = await ctx.db
      .query("telegramSessions")
      .withIndex("by_chat_id", (q: any) => q.eq("chatId", args.chatId))
      .first();

    if (session) {
      await ctx.db.patch(session._id, {
        isBotPaused: args.isBotPaused,
        botPausedUntil,
        updatedAt: new Date().toISOString(),
      });
    } else {
      await ctx.db.insert("telegramSessions", {
        chatId: args.chatId,
        isBotPaused: args.isBotPaused,
        botPausedUntil,
        updatedAt: new Date().toISOString(),
      });
    }

    return { success: true, botPausedUntil };
  },
});

export const addTelegramMessageInternal = mutation({
  args: {
    __internalApiKey: v.string(),
    chatId: v.string(),
    sender: v.string(),
    message: v.string(),
    isHuman: v.boolean(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const now = new Date().toISOString();

    await ctx.db.insert("telegramInteractions", {
      chatId: args.chatId,
      sender: args.sender,
      message: args.message,
      isHuman: args.isHuman,
      createdAt: now,
    });

    const session = await ctx.db
      .query("telegramSessions")
      .withIndex("by_chat_id", (q: any) => q.eq("chatId", args.chatId))
      .first();

    if (session) {
      await ctx.db.patch(session._id, {
        lastMessage: args.message.slice(0, 100),
        updatedAt: now,
      });
    }

    return { success: true };
  },
});

// -------------------------------------------------------------
// Transactional Outbox Shipper & Dead Man's Switch
// -------------------------------------------------------------
export const getPendingOutboxBatch = internalQuery({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("auditOutbox")
      .withIndex("by_status", (q: any) => q.eq("status", "PENDING"))
      .take(args.limit ?? 50);
  },
});

export const markOutboxDelivered = internalMutation({
  args: {
    eventIds: v.array(v.id("auditOutbox")),
  },
  handler: async (ctx, args) => {
    const now = Date.now();
    for (const id of args.eventIds) {
      await ctx.db.patch(id, {
        status: "DELIVERED",
        deliveredAt: now,
      });
    }
  },
});

export const getOutboxHealthQuery = query({
  args: {},
  handler: async (ctx) => {
    const pending = await ctx.db
      .query("auditOutbox")
      .withIndex("by_status", (q: any) => q.eq("status", "PENDING"))
      .take(101);

    const now = Date.now();
    let oldestAgeSec = 0;
    if (pending.length > 0) {
      const oldestCreated = Math.min(...pending.map((p) => p.createdAt));
      oldestAgeSec = Math.floor((now - oldestCreated) / 1000);
    }

    return {
      pendingCount: pending.length,
      oldestPendingAgeSec: oldestAgeSec,
      isHealthy: pending.length < 100 && oldestAgeSec < 900,
    };
  },
});

// -------------------------------------------------------------
// Adaptive Cursor Migration State Machine
// -------------------------------------------------------------
export const runCursorMigration = internalMutation({
  args: {
    migrationName: v.string(),
  },
  handler: async (ctx, args) => {
    const now = new Date().toISOString();
    let state = await ctx.db
      .query("migrationState")
      .withIndex("by_name", (q: any) => q.eq("name", args.migrationName))
      .first();

    if (!state) {
      const stateId = await ctx.db.insert("migrationState", {
        name: args.migrationName,
        processedCount: 0,
        batchSize: 500,
        consecutiveBatchFailures: 0,
        status: "RUNNING",
        startedAt: now,
        updatedAt: now,
      });
      state = await ctx.db.get(stateId);
    }

    if (!state || state.status === "COMPLETED" || state.status === "FAILED_POISON_PILL") {
      return { status: state?.status ?? "UNKNOWN" };
    }

    // Check circuit breaker
    if (state.consecutiveBatchFailures >= 3) {
      await ctx.db.patch(state._id, {
        status: "FAILED_POISON_PILL",
        updatedAt: now,
      });
      return { status: "FAILED_POISON_PILL", error: "Exceeded 3 consecutive batch failures" };
    }

    try {
      const jobsQuery = ctx.db.query("dubbingJobs").withIndex("by_created");
      const page = await jobsQuery.paginate({
        numItems: state.batchSize ?? 500,
        cursor: state.lastProcessedCursor ?? null,
      });

      let patched = 0;
      const errors: Array<{ recordId: string; error: string; timestamp: string }> = [];

      for (const doc of page.page) {
        try {
          if (doc.retry_count === undefined || doc.max_retries === undefined) {
            await ctx.db.patch(doc._id, {
              retry_count: doc.retry_count ?? 0,
              max_retries: doc.max_retries ?? 3,
              api_cost: doc.api_cost ?? 0.0,
            });
            patched++;
          }
        } catch (rowErr: any) {
          errors.push({
            recordId: doc._id,
            error: String(rowErr?.message ?? rowErr),
            timestamp: new Date().toISOString(),
          });
        }
      }

      const isDone = page.isDone;
      await ctx.db.patch(state._id, {
        lastProcessedCursor: isDone ? undefined : page.continueCursor,
        processedCount: state.processedCount + patched,
        consecutiveBatchFailures: 0,
        status: isDone ? "COMPLETED" : "RUNNING",
        errorLog: errors.length > 0 ? [...(state.errorLog ?? []), ...errors] : state.errorLog,
        completedAt: isDone ? now : undefined,
        updatedAt: now,
      });

      return {
        status: isDone ? "COMPLETED" : "RUNNING",
        processedThisBatch: patched,
        isDone,
      };
    } catch (batchErr: any) {
      // Step down batch size
      const nextBatchSize = state.batchSize > 250 ? 250 : state.batchSize > 50 ? 50 : 50;
      await ctx.db.patch(state._id, {
        consecutiveBatchFailures: state.consecutiveBatchFailures + 1,
        batchSize: nextBatchSize,
        updatedAt: now,
      });
      return { status: "BATCH_ERROR", error: String(batchErr?.message ?? batchErr) };
    }
  },
});

// ==========================================
// --- SERVER-SIDE ARGON2ID PIN SECURITY ---
// ==========================================

export const getAdminPinStatusInternal = query({
  args: {
    userId: v.string(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const pinDoc = await ctx.db
      .query("adminPinSecurity")
      .withIndex("by_user", (q: any) => q.eq("userId", args.userId))
      .first();

    if (!pinDoc) {
      return {
        hasPin: false,
        isPermanentlyLocked: false,
        failedAttempts: 0,
        attemptsRemaining: 5,
      };
    }

    return {
      hasPin: true,
      isPermanentlyLocked: pinDoc.isPermanentlyLocked,
      failedAttempts: pinDoc.failedAttempts,
      attemptsRemaining: Math.max(0, 5 - pinDoc.failedAttempts),
    };
  },
});

export const getAdminPinHashInternal = query({
  args: {
    userId: v.string(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const pinDoc = await ctx.db
      .query("adminPinSecurity")
      .withIndex("by_user", (q: any) => q.eq("userId", args.userId))
      .first();

    if (!pinDoc) return null;
    return {
      argon2Hash: pinDoc.argon2Hash,
      isPermanentlyLocked: pinDoc.isPermanentlyLocked,
      failedAttempts: pinDoc.failedAttempts,
    };
  },
});

export const setupAdminPinInternal = mutation({
  args: {
    userId: v.string(),
    email: v.string(),
    argon2Hash: v.string(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const existing = await ctx.db
      .query("adminPinSecurity")
      .withIndex("by_user", (q: any) => q.eq("userId", args.userId))
      .first();

    const now = new Date().toISOString();
    if (existing) {
      await ctx.db.patch(existing._id, {
        argon2Hash: args.argon2Hash,
        failedAttempts: 0,
        isPermanentlyLocked: false,
        updatedAt: now,
      });
      return existing._id;
    }

    return await ctx.db.insert("adminPinSecurity", {
      userId: args.userId,
      email: args.email,
      argon2Hash: args.argon2Hash,
      failedAttempts: 0,
      isPermanentlyLocked: false,
      createdAt: now,
      updatedAt: now,
    });
  },
});

export const recordPinVerificationResultInternal = mutation({
  args: {
    userId: v.string(),
    email: v.string(),
    success: v.boolean(),
    ipAddress: v.optional(v.string()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const pinDoc = await ctx.db
      .query("adminPinSecurity")
      .withIndex("by_user", (q: any) => q.eq("userId", args.userId))
      .first();

    const now = new Date().toISOString();

    if (args.success) {
      if (pinDoc) {
        await ctx.db.patch(pinDoc._id, {
          failedAttempts: 0,
          lastVerifiedAt: Date.now(),
          updatedAt: now,
        });
      }
      return { success: true, attemptsRemaining: 5, isPermanentlyLocked: false };
    }

    // Failure branch
    const failedAttempts = (pinDoc?.failedAttempts ?? 0) + 1;
    const isPermanentlyLocked = failedAttempts >= 5;

    if (pinDoc) {
      await ctx.db.patch(pinDoc._id, {
        failedAttempts,
        isPermanentlyLocked,
        updatedAt: now,
      });
    }

    if (isPermanentlyLocked) {
      await emitAuditOutbox(ctx, {
        eventId: `pin_lockout_${args.userId}_${Date.now()}`,
        action: "ADMIN_SHIELD_MAX_ATTEMPTS_LOCKOUT",
        actorId: args.userId,
        actorEmail: args.email,
        targetResource: "adminPinSecurity",
        targetId: args.userId,
        changedFields: { failedAttempts: { old: failedAttempts - 1, new: failedAttempts }, isPermanentlyLocked: { old: false, new: true } },
        metadata: { ipAddress: args.ipAddress, reason: "5 consecutive failed PIN entries" },
      });
    }

    return {
      success: false,
      attemptsRemaining: Math.max(0, 5 - failedAttempts),
      isPermanentlyLocked,
    };
  },
});
