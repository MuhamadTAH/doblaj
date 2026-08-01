import { ConvexError, v } from "convex/values";
import { action, internalAction, internalMutation, internalQuery, mutation, query } from "./_generated/server";
import type { ActionCtx } from "./_generated/server";
import { internal } from "./_generated/api";
import { requireWorkspace, asConvexWorkspaceId,
  requireInternalApiKey,} from "./lib/auth";

/**
 * Pird: voice catalog with cached intro audio.
 *
 * Architecture:
 *   1. `list` query returns each row with `introUrl` already resolved via
 *      `ctx.storage.getUrl(row.introStorageId)` server-side. The frontend
 *      gets a single round-trip with audio URLs attached. No N+1.
 *   2. `ensureIntro` action renders the brand-line once via Fish Audio,
 *      stores it in convex file storage, and writes introStorageId back
 *      to the row. Hard-fails on any non-200 from Fish — never writes a
 *      0-byte blob, never writes a silent placeholder. On failure, the
 *      row gets `introError` set instead so the UI can surface it.
 *   3. Re-renders are guarded by `introTextHash`: identical input → cache
 *      hit, zero Fish audio calls.
 *
 * Brand text is the message you specified — change BRAND_INTRO_AR to
 * rotate it (and run `npx convex run voices:warmAllIntros '{}'`).
 */
const BRAND_INTRO_AR =
  "صوت علامتك التجارية هو هويتك. نحن نضمن لك دبلجة احترافية، سلسة، وطبيعية، لنوصل رسالتك إلى الجمهور العربي بأعلى درجات الدقة والتأثير.";

const FISH_API_URL = "https://api.fish.audio/v1/tts";

// Resolved at action-load time from convex env (FISH_SPEECH_API_KEY or
// FISH_API_KEY — same fallback convention as the FastAPI backend).
function readFishKey(): string {
  const a = process.env.FISH_SPEECH_API_KEY ?? "";
  if (a) return a;
  return process.env.FISH_API_KEY ?? "";
}

// SHA-256 of the brand text → cache hits are deterministic regardless of
// any whitespace drift.
async function hashText(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Public list. Server-side resolves introStorageId → introUrl when present.
 * No additional round-trips for the client.
 *
 * Path B: no auth required. Voices are global reference data shared across
 * all workspaces. Returns active voices from every workspace. Filter by
 * `legacyId` prefix `fish-*` to get the seeded catalog.
 */
export const list = query({
  args: {
    workspaceId: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const rows = args.workspaceId
      ? await ctx.db
          .query("ttsVoices")
          .withIndex("by_workspace_id", (q) =>
            q.eq("workspaceId", asConvexWorkspaceId(args.workspaceId!)),
          )
          .collect()
      : await ctx.db.query("ttsVoices").collect();

    const active = rows.filter((r) => r.active !== false);

    // Resolve storage URLs in parallel.
    const withUrls = await Promise.all(
      active.map(async (r) => {
        const introUrl = r.introStorageId
          ? await ctx.storage.getUrl(r.introStorageId)
          : null;
        return { ...r, introUrl };
      }),
    );
    return withUrls;
  },
});

/**
 * Public: fetch a single voice by legacyId or _id. Called by the Python
 * FastAPI adapter (TTS generation pipeline) via ConvexClient.
 */
export const getById = query({
  args: { id: v.string() },
  handler: async (ctx, args) => {
    const byLegacy = await ctx.db
      .query("ttsVoices")
      .withIndex("by_legacy_id", (q) => q.eq("legacyId", args.id))
      .first();
    if (byLegacy) return byLegacy;
    return await ctx.db.get(args.id as any);
  },
});

/**
 * Public: stream the cached intro MP3 bytes for a voice row. Called by
 * the Python FastAPI adapter (TTS generation pipeline) via ConvexClient.
 */
export const getIntroBytes = query({
  args: { id: v.string() },
  handler: async (ctx, args) => {
    const row = await ctx.db
      .query("ttsVoices")
      .withIndex("by_legacy_id", (q) => q.eq("legacyId", args.id))
      .first();
    if (!row || !row.introStorageId) return null;
    const url = await ctx.storage.getUrl(row.introStorageId);
    return url ? { url } : null;
  },
});

/**
 * Internal list used by the warmAllIntros action. Bypasses workspace auth
 * (admin-only action).
 */
export const internalList = internalQuery({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("ttsVoices").collect();
  },
});

/**
 * Public `ensureIntro`. Hard-fails on any failure path. Never writes
 * 0 bytes, never writes a silent fallback.
 */
export const ensureIntro = action({
  args: { voiceRowId: v.id("ttsVoices") },
  handler: async (ctx, { voiceRowId }) => {
    const identity = await ctx.auth.getUserIdentity();
    if (!identity) throw new ConvexError("UNAUTHENTICATED");
    return await renderAndStore(ctx, voiceRowId);
  },
});

/**
 * Internal version for use by other actions like warmAllIntros.
 */
export const ensureIntroInternal = internalAction({
  args: { voiceRowId: v.id("ttsVoices"),
    __internalApiKey: v.string(),},
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    return await renderAndStore(ctx, args.voiceRowId);
  },
});

/**
 * Backend-callable version for the Python FastAPI service.
 */
export const ensureIntroBackend = action({
  args: { voiceRowId: v.id("ttsVoices"), __internalApiKey: v.string() },
  handler: async (ctx, args) => {
    requireInternalApiKey(args.__internalApiKey);
    return await renderAndStore(ctx, args.voiceRowId as never);
  },
});

/**
 * Internal mutation helpers — actions have no `ctx.db`, so the action
 * routes its reads/writes through these via `ctx.runQuery`/`ctx.runMutation`.
 */
export const readVoiceRow = internalMutation({
  args: { voiceRowId: v.id("ttsVoices") },
  handler: async (ctx, { voiceRowId }) => {
    return await ctx.db.get(voiceRowId);
  },
});

export const patchVoiceRow = internalMutation({
  args: {
    voiceRowId: v.id("ttsVoices"),
    fields: v.record(v.string(), v.any()),
  },
  handler: async (ctx, { voiceRowId, fields }) => {
    await ctx.db.patch(voiceRowId as never, fields as never);
  },
});

/**
 * Shared render logic. Throws ConvexError on every failure path; on any
 * failure, persists the error to introError and re-raises.
 *
 * Runs inside an *action*, so DB access goes through `ctx.runMutation`
 * against `readVoiceRow`/`patchVoiceRow`. Storage calls (`ctx.storage.*`)
 * are valid on actions.
 */
async function renderAndStore(ctx: ActionCtx, voiceRowId: never) {
  const row = (await ctx.runMutation(internal.voices.readVoiceRow, {
    voiceRowId: voiceRowId as never,
  })) as {
    _id: never;
    providerVoiceId?: string;
    introStorageId?: never;
    introTextHash?: string;
    introError?: string;
  } | null;
  if (!row) throw new ConvexError("VOICE_NOT_FOUND");
  if (!row.providerVoiceId) throw new ConvexError("VOICE_MISSING_CHECKPOINT");

  const textHash = await hashText(BRAND_INTRO_AR);

  // Cache hit: same text + already rendered.
  if (row.introStorageId && row.introTextHash === textHash && !row.introError) {
    return { storageId: row.introStorageId, cached: true };
  }

  const apiKey = readFishKey();
  if (!apiKey) {
    await ctx.runMutation(internal.voices.patchVoiceRow, {
      voiceRowId: voiceRowId as never,
      fields: {
        introError: "FISH_KEY_MISSING",
        updatedAt: new Date().toISOString(),
      },
    });
    throw new ConvexError("FISH_KEY_MISSING_IN_CONVEX_ENV");
  }

  let r: Response;
  try {
    r = await fetch(FISH_API_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        model: "s2-pro",
      },
      body: JSON.stringify({
        text: BRAND_INTRO_AR,
        reference_id: row.providerVoiceId,
        format: "mp3",
        prosody: { speed: 1.0, volume: 0 },
      }),
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    await ctx.runMutation(internal.voices.patchVoiceRow, {
      voiceRowId: voiceRowId as never,
      fields: {
        introError: `FETCH_ERROR: ${msg.slice(0, 200)}`,
        updatedAt: new Date().toISOString(),
      },
    });
    throw new ConvexError(`FETCH_ERROR: ${msg}`);
  }

  if (r.status !== 200) {
    const body = await r.text().catch(() => "");
    await ctx.runMutation(internal.voices.patchVoiceRow, {
      voiceRowId: voiceRowId as never,
      fields: {
        introError: `FISH_${r.status}: ${body.slice(0, 200)}`,
        updatedAt: new Date().toISOString(),
      },
    });
    throw new ConvexError(`FISH_AUDIO_${r.status}: ${body.slice(0, 200)}`);
  }

  const buf = new Uint8Array(await r.arrayBuffer());
  if (buf.byteLength === 0) {
    await ctx.runMutation(internal.voices.patchVoiceRow, {
      voiceRowId: voiceRowId as never,
      fields: {
        introError: "FISH_RETURNED_ZERO_BYTES",
        updatedAt: new Date().toISOString(),
      },
    });
    throw new ConvexError("FISH_RETURNED_ZERO_BYTES");
  }

  // Sanity-check the magic bytes for MP3.
  const looksLikeMp3 =
    (buf[0] === 0x49 && buf[1] === 0x44 && buf[2] === 0x33) || // "ID3"
    (buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0); // MPEG frame sync
  if (!looksLikeMp3) {
    await ctx.runMutation(internal.voices.patchVoiceRow, {
      voiceRowId: voiceRowId as never,
      fields: {
        introError: "FISH_RETURNED_NON_MP3",
        updatedAt: new Date().toISOString(),
      },
    });
    throw new ConvexError("FISH_RETURNED_NON_MP3");
  }

  const blob = new Blob([buf], { type: "audio/mpeg" });
  const storageId = await ctx.storage.store(blob);

  // If we replaced a previous storage id, drop the old blob to keep
  // storage clean (1 GB free tier; cheap insurance).
  if (row.introStorageId) {
    try {
      await ctx.storage.delete(row.introStorageId);
    } catch {
      // ignore — old blob may already be gone
    }
  }

  await ctx.runMutation(internal.voices.patchVoiceRow, {
    voiceRowId: voiceRowId as never,
    fields: {
      introStorageId: storageId,
      introBytes: buf.byteLength,
      introTextHash: textHash,
      introGeneratedAt: Date.now(),
      introError: undefined,
      updatedAt: new Date().toISOString(),
    },
  });

  return { storageId, cached: false, bytes: buf.byteLength };
}

/**
 * One-shot backfill across the entire ttsVoices catalog. Skips voices
 * that already have a valid intro. Invoke from the convex dashboard or:
 *   npx convex run voices:warmAllIntros '{}'
 *
 * Returns a structured per-voice report so the operator can see which
 * voices succeeded and which need attention.
 */
export const warmAllIntros = action({
  args: {},
  handler: async (ctx) => {
    const rows = (await ctx.runQuery(internal.voices.internalList, {})) as Array<{
      _id: never;
      introStorageId?: never;
      introError?: string;
      legacyId: string;
      name: string;
    }>;

    let attempted = 0;
    let succeeded = 0;
    let cached = 0;
    const failed: { legacyId: string; name: string; error: string }[] = [];

    for (const r of rows) {
      if (r.introStorageId && !r.introError) {
        cached++;
        continue;
      }
      attempted++;
      try {
        await ctx.runAction(internal.voices.ensureIntroInternal, {
          voiceRowId: r._id,
          __internalApiKey: process.env.INTERNAL_API_KEY!,
        });
        succeeded++;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        failed.push({
          legacyId: r.legacyId,
          name: r.name,
          error: msg.slice(0, 200),
        });
      }
    }

    return { attempted, succeeded, cached, failed };
  },
});

/**
 * patchIntroFields — internal-only. Reached via ctx.runMutation from
 * trusted server contexts (backfill script via INTERNAL_API_KEY, or
 * via the internal Convex HTTP endpoint). No public surface.
 */
export const patchIntroFields = internalMutation({
  args: {
    voiceRowId: v.id("ttsVoices"),
    storageId: v.id("_storage"),
    bytes: v.number(),
    textHash: v.string(),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.voiceRowId, {
      introStorageId: args.storageId,
      introBytes: args.bytes,
      introTextHash: args.textHash,
      introGeneratedAt: Date.now(),
      updatedAt: new Date().toISOString(),
    });
  },
});

/**
 * Public: counts all ttsVoices rows vs rows with introStorageId set.
 * Used by the warm script to verify completion.
 */
export const getCachedCount = query({
  args: {},
  handler: async (ctx) => {
    const all = await ctx.db.query("ttsVoices").collect();
    const cached = all.filter((r) => !!r.introStorageId).length;
    return { total: all.length, cached };
  },
});
