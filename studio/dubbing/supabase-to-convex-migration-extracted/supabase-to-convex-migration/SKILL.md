---
name: supabase-to-convex-migration
description: Guides migrating an application's backend from Supabase (Postgres) to Convex — translating SQL schemas into Convex TypeScript schemas, rewriting Row Level Security policies as function-level authorization checks, converting Supabase Realtime subscriptions into Convex reactive queries, moving Edge Functions and Postgres triggers into Convex actions or mutations, and re-linking foreign keys to native Convex document IDs during data import. Use this whenever the user is moving off Supabase onto Convex, converting a Postgres/SQL schema to Convex's schema format, migrating RLS policies to Convex, importing Supabase data dumps (SQL/JSONL/CSV) into Convex, or asking for help with any single piece of this migration — e.g. "write a Convex schema for my Supabase tables," "how do I replace this RLS policy in Convex," or "my foreign keys broke after importing into Convex."
---

# Supabase → Convex Migration

This is an architecture migration, not a syntax port. Supabase is Postgres with a REST/Realtime layer on top; Convex is a transactional document database with TypeScript functions as its only API surface. A correct migration changes how data is modeled, how access control is enforced, and how the frontend gets data — not just which client library is imported. Read this whole file before touching the user's code. Read the linked reference files when you reach the phase they cover, not all up front.

## The non-negotiables

Get these wrong and everything downstream breaks, so internalize them before auditing or writing anything.

**No SQL, no joins, no ALTER TABLE.** Convex has no relational engine underneath. There's nothing to `JOIN` — related data is fetched with multiple lookups (usually in parallel with `Promise.all`) or denormalized. If you catch yourself reaching for SQL-shaped thinking — normalizing into many small tables that get joined at read time, writing a migration as a `.sql` file — stop; that instinct is exactly what breaks Convex ports.

**The schema is TypeScript, enforced at runtime.** `convex/schema.ts` uses `defineSchema` / `defineTable` with the `v` validator builder from `convex/values` (`v.string()`, `v.number()`, `v.id("otherTable")`, `v.object()`, `v.union()`, `v.optional()`, etc.). Once deployed, Convex enforces that every document matches the schema — you'll lean on this as *proof the migration finished* in Phase 3, not just for type-checking.

**Two fields, and Convex owns both.** Every document automatically gets `_id` (a table-scoped document ID) and `_creationTime` (ms since epoch). Never write code that manufactures either. This matters immediately: a Postgres primary-key UUID is not a Convex `_id` and can never be forced to become one — that mismatch is the entire reason Phase 3 exists.

**Three function types, and the boundary is load-bearing, not stylistic:**
- **Queries** — read-only, must be deterministic given their arguments and the DB state. Automatically reactive and cached; the frontend subscribes and re-renders on change. Calling `fetch()` or anything non-deterministic here breaks caching guarantees, not just style.
- **Mutations** — transactional writes. Everything inside one commits atomically, so cross-table writes that used to need a Postgres transaction now just live in one mutation.
- **Actions** — the only place allowed to call external third-party APIs (Stripe, OpenAI, Resend, etc.) or do other non-deterministic work. Actions aren't transactional the way mutations are, so an action that needs to persist a result calls a mutation to actually write it (`ctx.runMutation`).

The instinct to move "side effects" to Actions gets over-applied. A Postgres trigger or Supabase Edge Function that only reads/writes rows inside the database — no outbound HTTP call — should become logic inside a **mutation**, not an action, because mutations already get atomic cross-table access. Reserve actions strictly for what leaves Convex's servers. Before deciding where code goes, check: does this call anything external? If not, it's a mutation.

## Workflow

Work through these phases in order.

### Phase 1 — Audit
Before writing any Convex code, inventory what actually exists in the Supabase project. Run `scripts/audit_supabase_project.py <project-root>` first — it's read-only and greps out the SQL schema, RLS policies, edge functions, and (with `--frontend-src`) client-side Supabase usage into a structured report, so you're not manually skimming every file by hand. Then read what it flags before drawing conclusions. Full checklist, including the categories most migration plans forget — auth provider, file storage, secrets, complex queries — is in `references/supabase-audit-checklist.md`.

### Phase 2 — Translate schema & security model
Full mapping table and the reasoning behind each row: `references/translation-matrix.md`. Two things worth stating here because they're the most commonly half-done:
- Authorization checks go at the top of **every query and every mutation** — not just queries. A query with no auth check is a public read endpoint whether anyone intended that or not.
- RLS policies usually encode two separate concerns: who's allowed to call a function, and which rows come back to them. A function-level auth check only answers the first. You still have to filter the query itself (`.withIndex`/`.filter` on the relevant tenant/owner field) to answer the second — copying an identity check to the top of a query and then returning every row regardless of ownership is a silent multi-tenant data leak, not a finished migration.

### Phase 3 — Data migration & ID re-linking
Full step-by-step with Convex's own documented pattern for this exact problem (Postgres → Convex, this is not improvised): `references/execution-playbook.md`. The shape of it: import with foreign-key fields typed loosely as `v.union(v.string(), v.id(...))`, write a migration that walks every document and rewrites the loose field to a real `v.id()` once the referenced document is found, then tighten the schema to `v.id()` only — at which point Convex's schema validation becomes your proof the migration is complete, since it refuses to deploy if any document still holds a bare string where an ID belongs.

### Phase 4 — Frontend reactivity cleanup
Delete manual fetch/refetch/subscription code — `useEffect` + `useState` for data fetching, manual realtime channel management, polling. Replace with Convex's `useQuery` hook. This isn't just less code: Convex tracks which documents a query read and invalidates automatically, so hand-rolled refetch logic left in place actively fights the reactivity system (double-fetches, stale-then-flash UI) instead of just being redundant.

### Phase 5 — Verify before cutover
Run the migration against a Convex **dev** deployment loaded with a copy of production data, not directly against prod. Compare document counts per table against the Postgres source, spot-check a sample of re-linked foreign keys by hand, and confirm every query and mutation has an auth check before pointing the frontend at Convex. Keep the Supabase project intact and read-only for a rollback window instead of deleting it the moment the new backend compiles — this phase doesn't exist in a lot of migration plans, and its absence is the actual reason migrations fail in production instead of in staging.

## What NOT to do

- Don't invent `v.uuid()`. It doesn't exist — an old Postgres UUID is `v.string()` until it's been re-linked to a real `v.id()`.
- Don't move a Postgres trigger to an action just because "trigger" sounds like "action." Check for an outbound call first (see Non-negotiables above).
- Don't write an auth "check" that only `console.log`s a warning. Convex doesn't stop a mutation unless the handler actually `throw`s.
- Don't treat Supabase Auth as something you translate. Convex has no built-in identity provider — you're integrating a separate one (Clerk, Auth0, WorkOS, or Convex Auth) and re-pointing existing users at it. That's its own workstream with its own migration risk (sessions, password resets, social logins), not a schema-mapping exercise. Scope and staff it separately; don't let it hide inside "Phase 2."
- Don't delete the old Supabase project or the `legacyId` fields the moment the new backend compiles. Keep them until Phase 5 sign-off — they're cheap insurance and the only way to debug a bad re-link after the fact.
- Don't loop over an entire table with a hand-rolled `.collect()` to do the ID re-link. Convex caps how many documents a single query/mutation can read; use the official `migrations` component (it paginates internally) or `.paginate()` yourself. See the pitfalls section in `references/execution-playbook.md`.

## Reference files
- `references/supabase-audit-checklist.md` — full Phase 1 extraction checklist, including the categories not in a typical first draft (auth provider, storage, env vars/secrets, complex/aggregate queries)
- `references/translation-matrix.md` — complete Supabase → Convex mapping table with the reasoning per row
- `references/execution-playbook.md` — Phase 3 step-by-step with Convex's actual documented migration code pattern, plus the full pitfall list
- `scripts/audit_supabase_project.py` — run first; read-only static scan of a Supabase project that seeds Phase 1
