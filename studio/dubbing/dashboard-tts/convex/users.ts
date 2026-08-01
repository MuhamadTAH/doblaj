/**
 * Users table mutations/queries for Clerk webhook sync.
 *
 * The webhook handler in `http.ts` calls `upsertFromClerk` with the
 * decoded Clerk payload. We upsert by `clerkId` (primary key from
 * Clerk's side). `legacyId` is generated once on first insert and
 * never changes — same idempotency contract used by every other
 * Convex table in this project.
 */
import { mutation, internalMutation, query, internalQuery } from "./_generated/server";
import { v } from "convex/values";
import { requireInternalApiKey } from "./lib/auth";

/**
 * Public upsert keyed by clerkId. Safe to call repeatedly: re-runs
 * for the same clerkId just refresh email/name/image, never duplicate.
 *
 * Public on purpose so the Python backfill script can call it via the
 * Convex client without needing the admin key. The mutation is a pure
 * upsert keyed by `clerkId` — it cannot leak data, only mirror what
 * Clerk already knows.
 */
export const upsertFromClerk = internalMutation({
  args: {
    clerkId: v.string(),
    email: v.optional(v.string()),
    firstName: v.optional(v.string()),
    lastName: v.optional(v.string()),
    imageUrl: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const now = new Date().toISOString();
    const existing = await ctx.db
      .query("users")
      .withIndex("by_clerk_id", (q) => q.eq("clerkId", args.clerkId))
      .unique();

    if (existing) {
      await ctx.db.patch(existing._id, {
        email: args.email ?? existing.email,
        firstName: args.firstName ?? existing.firstName,
        lastName: args.lastName ?? existing.lastName,
        imageUrl: args.imageUrl ?? existing.imageUrl,
        updatedAt: now,
      });
      return existing._id;
    }

    // First time we see this clerkId — generate legacyId.
    // crypto.randomUUID is available in the Convex runtime (Node 18+).
    const legacyId = crypto.randomUUID();
    return await ctx.db.insert("users", {
      legacyId,
      clerkId: args.clerkId,
      email: args.email,
      firstName: args.firstName,
      lastName: args.lastName,
      imageUrl: args.imageUrl,
      updatedAt: now,
    });
  },
});

export const upsertFromClerkInternal = mutation({
  args: {
    clerkId: v.string(),
    email: v.optional(v.string()),
    firstName: v.optional(v.string()),
    lastName: v.optional(v.string()),
    imageUrl: v.optional(v.string()),
    __internalApiKey: v.string(),
  },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    const now = new Date().toISOString();
    const existing = await ctx.db
      .query("users")
      .withIndex("by_clerk_id", (q) => q.eq("clerkId", args.clerkId))
      .unique();

    if (existing) {
      await ctx.db.patch(existing._id, {
        email: args.email ?? existing.email,
        firstName: args.firstName ?? existing.firstName,
        lastName: args.lastName ?? existing.lastName,
        imageUrl: args.imageUrl ?? existing.imageUrl,
        updatedAt: now,
      });
      return existing._id;
    }

    const legacyId = crypto.randomUUID();
    return await ctx.db.insert("users", {
      legacyId,
      clerkId: args.clerkId,
      email: args.email,
      firstName: args.firstName,
      lastName: args.lastName,
      imageUrl: args.imageUrl,
      updatedAt: now,
    });
  },
});

/** Look up a user by Clerk ID (e.g. `user_xxx`). */
export const getByClerkId = query({
  args: { clerkId: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("users")
      .withIndex("by_clerk_id", (q) => q.eq("clerkId", args.clerkId))
      .unique();
  },
});

/** Look up a user by primary email. PII-enumeration vector — must
 *  NOT be public. Use Clerk's own backend API for legitimate lookups. */
export const getByEmail = internalQuery({
  args: { email: v.string() },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("users")
      .withIndex("by_email", (q) => q.eq("email", args.email))
      .unique();
  },
});

/** Internal delete — used when a Clerk `user.deleted` event fires. */
export const deleteByClerkId = internalMutation({
  args: { clerkId: v.string() },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("users")
      .withIndex("by_clerk_id", (q) => q.eq("clerkId", args.clerkId))
      .unique();
    if (existing) await ctx.db.delete(existing._id);
  },
});