// PIRD-013: GDPR consent ledger. Browser-facing recordConsent is
// guarded by requireWorkspace; getConsentFor is internal so the Python
// adapter can check whether a user has consented to a given policy
// version before any biometric file is written.
import { ConvexError, v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { requireWorkspace, requireInternalApiKey } from "./lib/auth";

export const recordConsent = mutation({
  args: {
    consentType: v.string(),
    consentTextVersion: v.string(),
    ipAddress: v.optional(v.string()),
    userAgent: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const { userId, workspaceId } = await requireWorkspace(ctx);
    return await ctx.db.insert("consent", {
      userId,
      workspaceId,
      consentType: args.consentType,
      consentTextVersion: args.consentTextVersion,
      ipAddress: args.ipAddress,
      userAgent: args.userAgent,
      timestamp: new Date().toISOString(),
    });
  },
});

export const getConsentFor = query({
  args: {
    userId: v.string(),
    consentType: v.string(),
    consentTextVersion: v.string(),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const row = await ctx.db
      .query("consent")
      .withIndex("by_user_type", (q) =>
        q.eq("userId", args.userId).eq("consentType", args.consentType),
      )
      .filter((q) => q.eq(q.field("consentTextVersion"), args.consentTextVersion))
      .first();
    return row !== null;
  },
});
