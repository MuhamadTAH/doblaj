import { ConvexError } from "convex/values";
import { Id } from "./_generated/dataModel";
import { QueryCtx, MutationCtx } from "./_generated/server";

export type WorkspaceContext = {
  userId: string;
  workspaceId: string;
};

export async function requireWorkspace(
  ctx: QueryCtx | MutationCtx,
): Promise<WorkspaceContext> {
  const identity = await ctx.auth.getUserIdentity();
  if (!identity) {
    throw new ConvexError("UNAUTHENTICATED");
  }
  const rawWorkspace =
    (identity as unknown as { workspace_id?: string }).workspace_id ??
    (identity as unknown as { org_id?: string }).org_id ??
    (identity as unknown as { orgId?: string }).orgId;
  const workspaceId =
    typeof rawWorkspace === "string" && rawWorkspace.length > 0
      ? rawWorkspace
      : null;
  if (!workspaceId) {
    throw new ConvexError(
      "WORKSPACE_REQUIRED: select or create a Clerk organization before using Dubbing Studio",
    );
  }
  return { userId: identity.subject, workspaceId };
}

export async function requireWorkspaceId(
  ctx: QueryCtx | MutationCtx,
  workspaceId: string,
): Promise<WorkspaceContext> {
  const auth = await requireWorkspace(ctx);
  if (auth.workspaceId !== workspaceId) {
    throw new ConvexError("FORBIDDEN: workspace mismatch");
  }
  return auth;
}

export function asConvexWorkspaceId(value: string): Id<"workspaces"> {
  return value as Id<"workspaces">;
}

/**
 * Pird (security review M5): defense in depth for `*Internal` mutations
 * called by the Python FastAPI adapter. Without this, the entire
 * workspace-isolation contract depends on every `*Internal` mutation
 * remembering to call `resolveWorkspaceId` and check `doc.workspaceId`.
 * One missed check breaks the model.
 *
 * This helper checks a shared secret read from the Convex env
 * (`INTERNAL_API_KEY`) at call time. The Python adapter sends the same
 * key as `args.__internalApiKey`. If the env vars don't match OR the
 * caller forgot to send the key, this throws — turning "remembered
 * check" into "enforced check".
 *
 * Set `INTERNAL_API_KEY` on both the Convex dashboard (Settings →
 * Environment Variables) and `studio/dubbing/.env` to the same value.
 */
export function requireInternalApiKey(provided: string | undefined): void {
  const expected = process.env.INTERNAL_API_KEY ?? "";
  if (!expected) {
    throw new ConvexError(
      "INTERNAL_API_KEY_NOT_CONFIGURED: set the env var on the Convex deployment",
    );
  }
  if (!provided || provided !== expected) {
    throw new ConvexError("FORBIDDEN: missing or invalid internal API key");
  }
}
