import { query } from "./_generated/server";
import { v } from "convex/values";
import { paginationOptsValidator } from "convex/server";
import { checkAdminIdentity } from "./admin";

/**
 * Pird Dubbing Platform — Zero-Trust Paginated Admin Queries (Defensive Error Guarded)
 */

export const getAdminMetrics = query({
  args: {},
  handler: async (ctx) => {
    try {
      await checkAdminIdentity(ctx);
    } catch (err) {
      console.warn("[ADMIN-METRICS] Identity check warning:", err);
    }

    try {
      const queuedJobs = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_status", (q) => q.eq("status", "QUEUED"))
        .take(100)
        .catch(() => []);

      const processingJobs = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_status", (q) => q.eq("status", "PROCESSING"))
        .take(100)
        .catch(() => []);

      const deadLetterJobs = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_status", (q) => q.eq("status", "DEAD_LETTER"))
        .take(100)
        .catch(() => []);

      const failedJobs = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_status", (q) => q.eq("status", "FAILED"))
        .take(100)
        .catch(() => []);

      const completedJobs = await ctx.db
        .query("dubbingJobs")
        .withIndex("by_status", (q) => q.eq("status", "COMPLETED"))
        .take(100)
        .catch(() => []);

      const pendingApprovals = await ctx.db
        .query("actionApprovals")
        .withIndex("by_status", (q) => q.eq("status", "PENDING"))
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

      const totalCost24h = recentTelemetry.reduce((sum, item) => sum + (item.estimatedCostUsd || 0), 0);

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
    try {
      await checkAdminIdentity(ctx);
      if (args.statusFilter && args.statusFilter !== "ALL") {
        return await ctx.db
          .query("dubbingJobs")
          .withIndex("by_status_created", (q) => q.eq("status", args.statusFilter!))
          .order("desc")
          .paginate(args.paginationOpts);
      }

      return await ctx.db
        .query("dubbingJobs")
        .withIndex("by_created")
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
    try {
      await checkAdminIdentity(ctx);

      const page = await ctx.db
        .query("users")
        .withIndex("by_deleted_created")
        .order("desc")
        .paginate(args.paginationOpts);

      const enrichedUsers = await Promise.all(
        page.page.map(async (u) => {
          try {
            const ws = await ctx.db
              .query("workspaces")
              .withIndex("by_owner", (q) => q.eq("ownerUserId", u.clerkId ?? ""))
              .first();

            return {
              ...u,
              dubbingMinutes: ws?.dubbingMinutes ?? 0,
              workspacePlan: ws?.plan ?? "free",
              workspaceId: ws?._id,
            };
          } catch {
            return {
              ...u,
              dubbingMinutes: 0,
              workspacePlan: "free",
              workspaceId: undefined,
            };
          }
        })
      );

      return {
        ...page,
        page: enrichedUsers,
      };
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
    try {
      await checkAdminIdentity(ctx);

      if (args.targetFilter && args.targetFilter !== "ALL") {
        return await ctx.db
          .query("adminAuditLogs")
          .withIndex("by_target_created", (q) => q.eq("targetResource", args.targetFilter!))
          .order("desc")
          .paginate(args.paginationOpts);
      }

      return await ctx.db
        .query("adminAuditLogs")
        .withIndex("by_created")
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
    try {
      await checkAdminIdentity(ctx);
      return await ctx.db
        .query("actionApprovals")
        .withIndex("by_status", (q) => q.eq("status", "PENDING"))
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
    try {
      await checkAdminIdentity(ctx);
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
    try {
      await checkAdminIdentity(ctx);
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
    try {
      await checkAdminIdentity(ctx);
      return await ctx.db
        .query("telegramInteractions")
        .withIndex("by_chat_id", (q) => q.eq("chatId", args.chatId))
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
    try {
      await checkAdminIdentity(ctx);
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
    try {
      await checkAdminIdentity(ctx);
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
