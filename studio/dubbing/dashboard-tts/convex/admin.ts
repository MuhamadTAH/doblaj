import { internalMutation } from "./_generated/server";
import { ConvexError } from "convex/values";
import { internal } from "./_generated/api";

/**
 * Pird (security review M3): the previous `grantInfiniteMinutes` was a
 * public `mutation` with NO auth check — anyone with the Convex
 * deployment URL could grant 99,999,999 minutes to every workspace.
 *
 * Now an `internalMutation`, callable only via
 * `ctx.runMutation(internal.admin.grantInfiniteMinutes, {})` from an
 * authenticated admin action. The exported `grantInfiniteMinutes` is
 * intentionally NOT callable from the client anymore.
 *
 * The exposed `runGrantInfiniteMinutes` is the gated action: it requires
 * the calling Clerk user to be listed in the `adminUsers` env var.
 */
export const grantInfiniteMinutes = internalMutation({
  args: {},
  handler: async (ctx) => {
    const workspaces = await ctx.db.query("workspaces").collect();
    let updated = 0;

    for (const ws of workspaces) {
      await ctx.db.patch(ws._id, { dubbingMinutes: 99999999 });
      updated++;
    }

    return { success: true, updatedWorkspaces: updated };
  },
});

/**
 * Admin action — Clerk-authenticated, role-gated by ADMIN_CLERK_IDS env.
 * Set ADMIN_CLERK_IDS="user_xxx,user_yyy" on the Convex dashboard.
 */
export const runGrantInfiniteMinutes = async (
  ctx: { auth: { getUserIdentity: () => Promise<{ subject: string } | null> }; runMutation: (fn: any, args: any) => Promise<any> },
): Promise<{ success: boolean; updatedWorkspaces: number }> => {
  const identity = await ctx.auth.getUserIdentity();
  if (!identity) {
    throw new ConvexError("UNAUTHENTICATED");
  }
  const allowed = (process.env.ADMIN_CLERK_IDS ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  if (allowed.length === 0) {
    throw new ConvexError("ADMIN_NOT_CONFIGURED");
  }
  if (!allowed.includes(identity.subject)) {
    throw new ConvexError("FORBIDDEN");
  }
  return await ctx.runMutation(internal.admin.grantInfiniteMinutes, {});
};
