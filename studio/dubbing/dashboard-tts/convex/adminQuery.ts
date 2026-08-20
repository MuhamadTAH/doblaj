import { query } from "./_generated/server";
import { v } from "convex/values";
import { paginationOptsValidator } from "convex/server";
import { checkAdminIdentity } from "./admin";

/**
 * Pird Dubbing Platform — Zero-Trust Paginated Admin Queries
 */

export const getAdminMetrics = query({
  args: {},
  handler: async (ctx) => {
    await checkAdminIdentity(ctx);

    const queuedJobs = await ctx.db
      .query("dubbingJobs")
      .withIndex("by_status", (q) => q.eq("status", "QUEUED"))
      .take(100);

    const processingJobs = await ctx.db
      .query("dubbingJobs")
      .withIndex("by_status", (q) => q.eq("status", "PROCESSING"))
      .take(100);

    const deadLetterJobs = await ctx.db
      .query("dubbingJobs")
      .withIndex("by_status", (q) => q.eq("status", "DEAD_LETTER"))
      .take(100);

    const failedJobs = await ctx.db
      .query("dubbingJobs")
      .withIndex("by_status", (q) => q.eq("status", "FAILED"))
      .take(100);

    const completedJobs = await ctx.db
      .query("dubbingJobs")
      .withIndex("by_status", (q) => q.eq("status", "COMPLETED"))
      .take(100);

    const pendingApprovals = await ctx.db
      .query("actionApprovals")
      .withIndex("by_status", (q) => q.eq("status", "PENDING"))
      .take(50);

    const recentAlerts = await ctx.db
      .query("securityAlerts")
      .order("desc")
      .take(10);

    // Compute estimated 24h burn rate
    const recentTelemetry = await ctx.db
      .query("aiUsageLogs")
      .order("desc")
      .take(50);

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
  },
});

export const listJobsPaginated = query({
  args: {
    paginationOpts: paginationOptsValidator,
    statusFilter: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
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
  },
});

export const listUsersPaginated = query({
  args: {
    paginationOpts: paginationOptsValidator,
  },
  handler: async (ctx, args) => {
    await checkAdminIdentity(ctx);

    const page = await ctx.db
      .query("users")
      .withIndex("by_deleted_created")
      .order("desc")
      .paginate(args.paginationOpts);

    // Enrich with workspace balance
    const enrichedUsers = await Promise.all(
      page.page.map(async (u) => {
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
      })
    );

    return {
      ...page,
      page: enrichedUsers,
    };
  },
});

export const listAuditLogsPaginated = query({
  args: {
    paginationOpts: paginationOptsValidator,
    targetFilter: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
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
  },
});

export const listPendingApprovals = query({
  args: {},
  handler: async (ctx) => {
    await checkAdminIdentity(ctx);
    return await ctx.db
      .query("actionApprovals")
      .withIndex("by_status", (q) => q.eq("status", "PENDING"))
      .order("desc")
      .take(50);
  },
});

export const listFeatureFlags = query({
  args: {},
  handler: async (ctx) => {
    await checkAdminIdentity(ctx);
    return await ctx.db.query("featureFlags").collect();
  },
});

export const listTelegramSessions = query({
  args: {},
  handler: async (ctx) => {
    await checkAdminIdentity(ctx);
    return await ctx.db.query("telegramSessions").order("desc").take(50);
  },
});

export const getTelegramChatHistory = query({
  args: {
    chatId: v.string(),
    limit: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    await checkAdminIdentity(ctx);
    return await ctx.db
      .query("telegramInteractions")
      .withIndex("by_chat_id", (q) => q.eq("chatId", args.chatId))
      .order("asc")
      .take(args.limit ?? 100);
  },
});

export const listAdminRoles = query({
  args: {},
  handler: async (ctx) => {
    await checkAdminIdentity(ctx);
    const roles = await ctx.db.query("adminRoles").collect();
    const permissions = await ctx.db.query("adminPermissions").collect();
    const userRoles = await ctx.db.query("adminUserRoles").collect();
    return { roles, permissions, userRoles };
  },
});

export const listTransactionsPaginated = query({
  args: {
    paginationOpts: paginationOptsValidator,
  },
  handler: async (ctx, args) => {
    await checkAdminIdentity(ctx);
    return await ctx.db
      .query("transactions")
      .order("desc")
      .paginate(args.paginationOpts);
  },
});
