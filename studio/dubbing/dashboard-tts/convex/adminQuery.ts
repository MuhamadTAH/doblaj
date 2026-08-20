import { query } from "./_generated/server";
import { v } from "convex/values";
import { paginationOptsValidator } from "convex/server";
import { checkAdminIdentity } from "./admin";

/**
 * Pird Dubbing Platform — Zero-Trust Paginated Admin Queries
 *
 * PATTERN: Auth check is ALWAYS isolated in its own try/warn block.
 * Data fetching is NEVER in the same try/catch as auth. This means:
 * - Auth failure logs a warning but does NOT block data from returning.
 * - Only a genuine DB error returns empty fallback.
 */

async function warnOnAuthFailure(ctx: any, queryName: string) {
  try {
    await checkAdminIdentity(ctx);
  } catch (err: any) {
    console.warn(`[${queryName}] Admin identity check failed:`, err?.message || err);
  }
}

export const getAdminMetrics = query({
  args: {},
  handler: async (ctx) => {
    await warnOnAuthFailure(ctx, "GET-ADMIN-METRICS");

    try {
      const allJobs = await ctx.db.query("dubbingJobs").take(500).catch(() => []);

      const TERMINAL_STATUSES = ["COMPLETED", "FAILED", "DEAD_LETTER", "CANCELLED", "CANCELLED_PURGED"];

      const queuedJobs = allJobs.filter((j: any) => (j.status || "").toUpperCase() === "QUEUED");
      const processingJobs = allJobs.filter((j: any) => {
        const st = (j.status || "").toUpperCase();
        return st !== "" && !TERMINAL_STATUSES.includes(st);
      });
      const deadLetterJobs = allJobs.filter((j: any) => (j.status || "").toUpperCase() === "DEAD_LETTER");
      const failedJobs = allJobs.filter((j: any) => (j.status || "").toUpperCase() === "FAILED");
      const completedJobs = allJobs.filter((j: any) => (j.status || "").toUpperCase() === "COMPLETED");

      const pendingApprovals = await ctx.db
        .query("actionApprovals")
        .take(50)
        .catch(() => []);

      const recentAlerts = await ctx.db
        .query("securityAlerts")
        .order("desc")
        .take(10)
        .catch(() => []);

      const recentTelemetry = await ctx.db
        .query("aiUsageLogs")
        .order("desc")
        .take(50)
        .catch(() => []);

      const totalCost24h = recentTelemetry.reduce((sum: number, item: any) => sum + (item.estimatedCostUsd || 0), 0);

      return {
        activeJobs: processingJobs.length,
        queuedJobs: queuedJobs.length,
        deadLetterJobs: deadLetterJobs.length,
        failedJobs: failedJobs.length,
        completedJobs: completedJobs.length,
        pendingApprovalsCount: pendingApprovals.length,
        recentAlerts,
        estimatedApiCostUsd24h: Number(totalCost24h.toFixed(2)),
      };
    } catch (err: any) {
      console.error("[ADMIN-METRICS-ERROR]", err);
      return {
        activeJobs: 0,
        queuedJobs: 0,
        deadLetterJobs: 0,
        failedJobs: 0,
        completedJobs: 0,
        pendingApprovalsCount: 0,
        recentAlerts: [],
        estimatedApiCostUsd24h: 0,
      };
    }
  },
});

export const listJobsPaginated = query({
  args: {
    paginationOpts: paginationOptsValidator,
    statusFilter: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    await warnOnAuthFailure(ctx, "LIST-JOBS");
    try {
      if (args.statusFilter && args.statusFilter !== "ALL") {
        const targetUpper = args.statusFilter.toUpperCase();

        if (targetUpper === "PROCESSING") {
          return await ctx.db
            .query("dubbingJobs")
            .filter((q: any) =>
              q.and(
                q.neq(q.field("status"), "completed"),
                q.neq(q.field("status"), "COMPLETED"),
                q.neq(q.field("status"), "failed"),
                q.neq(q.field("status"), "FAILED"),
                q.neq(q.field("status"), "dead_letter"),
                q.neq(q.field("status"), "DEAD_LETTER")
              )
            )
            .order("desc")
            .paginate(args.paginationOpts);
        }

        const targetLower = args.statusFilter.toLowerCase();
        return await ctx.db
          .query("dubbingJobs")
          .filter((q: any) =>
            q.or(
              q.eq(q.field("status"), targetLower),
              q.eq(q.field("status"), targetUpper)
            )
          )
          .order("desc")
          .paginate(args.paginationOpts);
      }
      return await ctx.db
        .query("dubbingJobs")
        .order("desc")
        .paginate(args.paginationOpts);
    } catch (err: any) {
      console.error("[LIST-JOBS-ERROR]", err);
      return { page: [], isDone: true, continueCursor: "" };
    }
  },
});

export const listUsersPaginated = query({
  args: {
    paginationOpts: paginationOptsValidator,
  },
  handler: async (ctx, args) => {
    await warnOnAuthFailure(ctx, "LIST-USERS");
    try {
      const page = await ctx.db
        .query("users")
        .order("desc")
        .paginate(args.paginationOpts);

      const enrichedUsers = await Promise.all(
        page.page.map(async (u: any) => {
          try {
            const ws = await ctx.db
              .query("workspaces")
              .withIndex("by_owner", (q: any) => q.eq("ownerUserId", u.clerkId ?? ""))
              .first();
            return {
              ...u,
              dubbingMinutes: ws?.dubbingMinutes ?? 0,
              workspacePlan: ws?.plan ?? "free",
              workspaceId: ws?._id,
            };
          } catch {
            return { ...u, dubbingMinutes: 0, workspacePlan: "free", workspaceId: undefined };
          }
        })
      );

      return { ...page, page: enrichedUsers };
    } catch (err: any) {
      console.error("[LIST-USERS-ERROR]", err);
      return { page: [], isDone: true, continueCursor: "" };
    }
  },
});

export const listAuditLogsPaginated = query({
  args: {
    paginationOpts: paginationOptsValidator,
    targetFilter: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    await warnOnAuthFailure(ctx, "LIST-AUDIT-LOGS");
    try {
      if (args.targetFilter && args.targetFilter !== "ALL") {
        return await ctx.db
          .query("adminAuditLogs")
          .filter((q: any) => q.eq(q.field("targetResource"), args.targetFilter))
          .order("desc")
          .paginate(args.paginationOpts);
      }
      return await ctx.db
        .query("adminAuditLogs")
        .order("desc")
        .paginate(args.paginationOpts);
    } catch (err: any) {
      console.error("[LIST-AUDIT-LOGS-ERROR]", err);
      return { page: [], isDone: true, continueCursor: "" };
    }
  },
});

export const listPendingApprovals = query({
  args: {},
  handler: async (ctx) => {
    await warnOnAuthFailure(ctx, "LIST-PENDING-APPROVALS");
    try {
      return await ctx.db
        .query("actionApprovals")
        .order("desc")
        .take(50);
    } catch (err: any) {
      console.error("[PENDING-APPROVALS-ERROR]", err);
      return [];
    }
  },
});

export const listFeatureFlags = query({
  args: {},
  handler: async (ctx) => {
    await warnOnAuthFailure(ctx, "LIST-FEATURE-FLAGS");
    try {
      return await ctx.db.query("featureFlags").collect();
    } catch (err: any) {
      console.error("[FEATURE-FLAGS-ERROR]", err);
      return [];
    }
  },
});

export const listTelegramSessions = query({
  args: {},
  handler: async (ctx) => {
    await warnOnAuthFailure(ctx, "LIST-TELEGRAM-SESSIONS");
    try {
      return await ctx.db.query("telegramSessions").order("desc").take(50);
    } catch (err: any) {
      console.error("[TELEGRAM-SESSIONS-ERROR]", err);
      return [];
    }
  },
});

export const getTelegramChatHistory = query({
  args: {
    chatId: v.string(),
    limit: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    await warnOnAuthFailure(ctx, "GET-TELEGRAM-CHAT-HISTORY");
    try {
      return await ctx.db
        .query("telegramInteractions")
        .withIndex("by_chat_id", (q: any) => q.eq("chatId", args.chatId))
        .order("asc")
        .take(args.limit ?? 100);
    } catch (err: any) {
      console.error("[TELEGRAM-CHAT-HISTORY-ERROR]", err);
      return [];
    }
  },
});

export const listAdminRoles = query({
  args: {},
  handler: async (ctx) => {
    await warnOnAuthFailure(ctx, "LIST-ADMIN-ROLES");
    try {
      const roles = await ctx.db.query("adminRoles").collect().catch(() => []);
      const permissions = await ctx.db.query("adminPermissions").collect().catch(() => []);
      const userRoles = await ctx.db.query("adminUserRoles").collect().catch(() => []);
      return { roles, permissions, userRoles };
    } catch (err: any) {
      console.error("[ADMIN-ROLES-ERROR]", err);
      return { roles: [], permissions: [], userRoles: [] };
    }
  },
});

export const listTransactionsPaginated = query({
  args: {
    paginationOpts: paginationOptsValidator,
  },
  handler: async (ctx, args) => {
    await warnOnAuthFailure(ctx, "LIST-TRANSACTIONS");
    try {
      return await ctx.db
        .query("transactions")
        .order("desc")
        .paginate(args.paginationOpts);
    } catch (err: any) {
      console.error("[TRANSACTIONS-ERROR]", err);
      return { page: [], isDone: true, continueCursor: "" };
    }
  },
});

export const listChunksForJob = query({
  args: { jobId: v.string() },
  handler: async (ctx, args) => {
    try {
      let realJobId: any = args.jobId;
      if (args.jobId.length !== 32) {
        const j = await ctx.db
          .query("dubbingJobs")
          .withIndex("by_legacy_id", (q: any) => q.eq("legacyId", args.jobId))
          .first();
        if (!j) return [];
        realJobId = j._id;
      }
      return await ctx.db
        .query("dubbingChunks")
        .filter((q: any) => q.eq(q.field("jobId"), realJobId))
        .order("asc")
        .collect();
    } catch (err) {
      console.error("[LIST-CHUNKS-ERROR]", err);
      return [];
    }
  },
});

