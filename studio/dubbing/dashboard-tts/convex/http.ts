/**
 * Clerk webhook receiver.
 *
 * Flow:
 *   1. Clerk POSTs a signed JSON body to /clerk-webhook
 *   2. We read the RAW text body (must be unmodified for Svix HMAC)
 *   3. We verify the Svix signature using CLERK_WEBHOOK_SIGNING_SECRET
 *   4. We dispatch by event type to upsert/delete the matching user
 *
 * Security:
 *   - Missing or invalid signature -> 400, no DB write
 *   - Missing CLERK_WEBHOOK_SIGNING_SECRET -> 500 (fail closed)
 *   - Raw body is required for HMAC; we never JSON.parse before verify
 *
 * Endpoint URL to paste into Clerk Dashboard -> Webhooks:
 *   https://<your-convex-deployment>.convex.site/clerk-webhook
 *
 * Subscribe to events: user.created, user.updated, user.deleted
 */
import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { Webhook } from "svix";
import { internal } from "./_generated/api";

const http = httpRouter();

http.route({
  path: "/clerk-webhook",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    const secret = process.env.CLERK_WEBHOOK_SIGNING_SECRET;
    if (!secret) {
      console.error("[clerk-webhook] CLERK_WEBHOOK_SIGNING_SECRET not set");
      return new Response("server misconfigured", { status: 500 });
    }

    // Svix headers — Clerk forwards them as-is on every webhook call.
    const svixId = request.headers.get("svix-id");
    const svixTimestamp = request.headers.get("svix-timestamp");
    const svixSignature = request.headers.get("svix-signature");

    if (!svixId || !svixTimestamp || !svixSignature) {
      return new Response("missing svix headers", { status: 400 });
    }

    // CRITICAL: must be raw body string, not JSON.parse -> JSON.stringify round-trip.
    const payload = await request.text();

    let event: ClerkWebhookEvent;
    try {
      const wh = new Webhook(secret);
      event = wh.verify(payload, {
        "svix-id": svixId,
        "svix-timestamp": svixTimestamp,
        "svix-signature": svixSignature,
      }) as ClerkWebhookEvent;
    } catch (err) {
      console.error("[clerk-webhook] signature verification failed", err);
      return new Response("invalid signature", { status: 400 });
    }

    try {
      switch (event.type) {
        case "user.created":
        case "user.updated": {
          const u = event.data;
          const primaryEmailId = u.primary_email_address_id;
          const primaryEmail =
            u.email_addresses?.find((e) => e.id === primaryEmailId)?.email_address ??
            u.email_addresses?.[0]?.email_address;
          await ctx.runMutation(internal.users.upsertFromClerk, {
            clerkId: u.id,
            email: primaryEmail,
            firstName: u.first_name ?? undefined,
            lastName: u.last_name ?? undefined,
            imageUrl: u.image_url ?? undefined,
          });
          break;
        }
        case "user.deleted": {
          const u = event.data;
          if (u?.id) {
            await ctx.runMutation(internal.users.deleteByClerkId, {
              clerkId: u.id,
            });
          }
          break;
        }
        default:
          // Unhandled event type — ack so Clerk doesn't retry forever.
          console.log("[clerk-webhook] ignored event type", event.type);
      }
    } catch (err) {
      console.error("[clerk-webhook] handler error", err);
      return new Response("handler error", { status: 500 });
    }

    return new Response(null, { status: 200 });
  }),
});

// ---------------------------------------------------------------------------
// Types — minimal subset of the Clerk webhook payload we actually use.
// Keeping them local avoids pulling in @clerk/types into the convex runtime.
// ---------------------------------------------------------------------------
type ClerkWebhookEvent = {
  type: string;
  data: {
    id: string;
    primary_email_address_id?: string;
    email_addresses?: Array<{ id: string; email_address: string }>;
    first_name?: string | null;
    last_name?: string | null;
    image_url?: string | null;
    deleted?: boolean;
  };
};

export default http;