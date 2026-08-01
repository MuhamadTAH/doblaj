import { ConvexError, v } from "convex/values";
import { internalMutation, internalQuery, mutation } from "./_generated/server";
import { asConvexWorkspaceId } from "./lib/auth";

/**
 * Pird: one-shot backfill of the 12 Fish Audio public voices you picked.
 *
 * Idempotent: re-running on an already-populated workspace reports
 * which rows were inserted vs skipped. Inserts only active voices;
 * does NOT touch existing rows.
 *
 * Invoke from the convex dashboard or:
 *   npx convex run seedVoices:backfill '{"workspaceId":"<id>"}'
 *
 * Also exposes `listMissing` to surface which voices haven't been
 * seeded yet (used by the operator before running `backfill`).
 */

type SeedVoice = {
  legacyId: string;
  name: string;
  provider: "fish_audio";
  providerVoiceId: string;
  language: string;
  gender: "male" | "female";
  description: string;
  tags: string[];
};

const VOICES: SeedVoice[] = [
  {
    legacyId: "fish-295e8c43",
    name: "Anwar",
    provider: "fish_audio",
    providerVoiceId: "295e8c434c03469198a02ed8650ed9c6",
    language: "ar-IQ",
    gender: "male",
    description: "Warm Iraqi Arabic male narrator",
    tags: ["arabic", "iq", "narrator"],
  },
  {
    legacyId: "fish-564ff4b2",
    name: "Layla",
    provider: "fish_audio",
    providerVoiceId: "564ff4b232d6427f91513321de5fb651",
    language: "ar-IQ",
    gender: "female",
    description: "Soft Iraqi Arabic female voice",
    tags: ["arabic", "iq", "narrator"],
  },
  {
    legacyId: "fish-93edb401",
    name: "Karwan",
    provider: "fish_audio",
    providerVoiceId: "93edb401ddf94e9a836a74f141be5258",
    language: "ckb",
    gender: "male",
    description: "Kurdish Sorani male narrator",
    tags: ["kurdish", "sorani", "narrator"],
  },
  {
    legacyId: "fish-18372167",
    name: "Najla",
    provider: "fish_audio",
    providerVoiceId: "183721675c2045499e8de847f4488b32",
    language: "ar-IQ",
    gender: "female",
    description: "Friendly Iraqi Arabic female",
    tags: ["arabic", "iq", "friendly"],
  },
  {
    legacyId: "fish-ca39ec48",
    name: "Hassan",
    provider: "fish_audio",
    providerVoiceId: "ca39ec4818f94e979bacb8dfb9c73a33",
    language: "ar-IQ",
    gender: "male",
    description: "Deep Iraqi Arabic male",
    tags: ["arabic", "iq", "deep"],
  },
  {
    legacyId: "fish-a381d0da",
    name: "Huda",
    provider: "fish_audio",
    providerVoiceId: "a381d0da904d402d82d457788d1b90fe",
    language: "ar-IQ",
    gender: "female",
    description: "Calm Iraqi Arabic female",
    tags: ["arabic", "iq", "calm"],
  },
  {
    legacyId: "fish-535fff20",
    name: "Shawkat",
    provider: "fish_audio",
    providerVoiceId: "535fff20b534436ba242e6b2a5a7588d",
    language: "ar-IQ",
    gender: "male",
    description: "Energetic Iraqi Arabic male",
    tags: ["arabic", "iq", "energetic"],
  },
  {
    legacyId: "fish-47aedfd4",
    name: "Maryam",
    provider: "fish_audio",
    providerVoiceId: "47aedfd446b54e69ab3b8de1f228a454",
    language: "ar-IQ",
    gender: "female",
    description: "Professional Iraqi Arabic female",
    tags: ["arabic", "iq", "professional"],
  },
  {
    legacyId: "fish-97de37d3",
    name: "Aram",
    provider: "fish_audio",
    providerVoiceId: "97de37d35791427b859be305d9138c51",
    language: "ckb",
    gender: "male",
    description: "Kurdish Sorani male voice",
    tags: ["kurdish", "sorani"],
  },
  {
    legacyId: "fish-b9884d77",
    name: "Bana",
    provider: "fish_audio",
    providerVoiceId: "b9884d77122d40688628d2ae22b6c44c",
    language: "ckb",
    gender: "female",
    description: "Kurdish Sorani female voice",
    tags: ["kurdish", "sorani"],
  },
  {
    legacyId: "fish-df6b40b9",
    name: "Chra",
    provider: "fish_audio",
    providerVoiceId: "df6b40b9b06345b9af70b4ffd9aac98d",
    language: "ar-IQ",
    gender: "female",
    description: "Young Iraqi Arabic female",
    tags: ["arabic", "iq", "young"],
  },
  {
    legacyId: "fish-8a8880cf",
    name: "Avin",
    provider: "fish_audio",
    providerVoiceId: "8a8880cf09d74f56beb05ae98f01f504",
    language: "ckb",
    gender: "female",
    description: "Soft Kurdish Sorani female",
    tags: ["kurdish", "sorani", "soft"],
  },
];

/** Internal-only: which voices still need seeding for this workspace.
 *  Was public (PIRD-030) — information disclosure of seeding state. */
export const listMissing = internalQuery({
  args: { workspaceId: v.id("workspaces") },
  handler: async (ctx, { workspaceId }) => {
    const existing = await ctx.db
      .query("ttsVoices")
      .withIndex("by_workspace_id", (q) => q.eq("workspaceId", workspaceId))
      .collect();
    const existingIds = new Set(existing.map((r) => r.legacyId));
    return VOICES.filter((v) => !existingIds.has(v.legacyId)).map((v) => v.legacyId);
  },
});

/**
 * Inserts all 12 voice rows for the given workspace. Idempotent on
 * `(legacyId, workspaceId)` — re-running skips already-present rows
 * and reports counts.
 */
export const backfill = internalMutation({
  args: { legacyWorkspaceId: v.string() },
  handler: async (ctx, args) => {
    // Pird (security review M2): previously exposed as a public `mutation`
    // with no auth check — anyone with the Convex deployment URL could
    // seed voice rows or create new workspaces. Now an `internalMutation`,
    // callable only via `ctx.runMutation(internalApi.seedVoices.backfill, ...)`
    // from an authenticated action. Run it once with:
    //   npx convex run admin:seedVoicesInternal '{}'
    // (after wiring an admin action, see follow-up).
    let ws = await ctx.db
      .query("workspaces")
      .withIndex("by_legacy_id", (q) => q.eq("legacyId", args.legacyWorkspaceId))
      .first();
    if (!ws) {
      const wsId = await ctx.db.insert("workspaces", {
        legacyId: args.legacyWorkspaceId,
        name: `Workspace ${args.legacyWorkspaceId.slice(0, 8)}`,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      });
      ws = await ctx.db.get(wsId);
      if (!ws) throw new ConvexError("WORKSPACE_CREATE_FAILED");
    }
    const workspaceId = ws._id;

    const existing = await ctx.db
      .query("ttsVoices")
      .withIndex("by_workspace_id", (q) => q.eq("workspaceId", workspaceId))
      .collect();
    const existingIds = new Set(existing.map((r) => r.legacyId));

    let inserted = 0;
    let skipped = 0;
    const inserted_legacyIds: string[] = [];

    const now = new Date().toISOString();
    for (const v of VOICES) {
      if (existingIds.has(v.legacyId)) {
        skipped++;
        continue;
      }
      await ctx.db.insert("ttsVoices", {
        legacyId: v.legacyId,
        workspaceId: asConvexWorkspaceId(workspaceId.toString()),
        name: v.name,
        provider: v.provider,
        providerVoiceId: v.providerVoiceId,
        language: v.language,
        gender: v.gender,
        description: v.description,
        tags: v.tags,
        active: true,
        createdAt: now,
        updatedAt: now,
      });
      inserted++;
      inserted_legacyIds.push(v.legacyId);
    }

    return { inserted, skipped, total: VOICES.length, inserted_legacyIds };
  },
});
