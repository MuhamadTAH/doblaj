# Phase 1: Supabase Audit Checklist

Run `scripts/audit_supabase_project.py` first to get a structured starting inventory, then work through these categories by hand. The script covers the mechanical grep work for categories 1–4; categories 5–8 need a closer read because they're about what's *absent* from the code as much as what's in it — a script can't tell you "there's no `legacyId` field" or "there's no rollback plan."

Every one of these eight categories has to be checked. The first four are the obvious ones. The last four are the ones migration plans skip, and they're the ones that cause mid-migration surprises, not schema-mapping errors.

## 1. SQL schema & relationships
- Pull the full schema: `supabase db dump --schema public -f schema.sql`, or connect with `psql` and run `\d+ <table>` per table.
- For every table, record: columns + types, primary key, foreign keys (and their `ON DELETE` behavior — `CASCADE` in particular has no automatic Convex equivalent), `UNIQUE` constraints, `CHECK` constraints, and any column with a database-computed `DEFAULT` (e.g. `gen_random_uuid()`, `now()`).
- Note which foreign keys are nullable — a nullable FK needs `v.optional(v.union(v.string(), v.id(...)))`, not just the union.

## 2. Row Level Security policies
- Extract every policy: `SELECT * FROM pg_policies;` or read the `CREATE POLICY` statements out of the migration files directly.
- For each policy, record which command it applies to (`SELECT`/`INSERT`/`UPDATE`/`DELETE` — Supabase policies are often per-command, and a single Convex mutation usually needs to reproduce all the write-side ones at once), and separate the policy's logic into the two things it's actually doing: an identity/role check ("is this user an admin"), and a row-filter ("only rows where `org_id = auth.jwt() ->> 'org_id'`"). You'll need both pieces in Phase 2, and they don't move to the same place in Convex (see SKILL.md).

## 3. Client-side data fetching & realtime
- Search the frontend for `.from(`, `.select(`, `.channel(`, `.on('postgres_changes'`, and any hand-rolled `useEffect`/`useState` pair that fetches on mount. Each of these is a candidate for deletion and replacement with `useQuery`.
- Also search for `.rpc(` calls — these invoke a Postgres function directly from the client, bypassing the normal table read pattern. Cross-reference each one against category 8 below; an RPC call is usually there precisely because the logic didn't fit a simple `SELECT`.
- Note anywhere the frontend does its own joining (fetching table A, then looping to fetch related rows from table B) — that pattern actually transfers fairly directly to Convex (parallel lookups), unlike a real SQL `JOIN` would.

## 4. Edge Functions & Postgres triggers
- List every function under `supabase/functions/`, and every `CREATE TRIGGER` in the SQL migrations.
- For each one, answer one question before anything else: does it make an outbound network call (payment processor, email, third-party API)? That answer determines whether it becomes a Convex **action** or just logic inside a **mutation** — see the non-negotiables in SKILL.md. Record the answer per function/trigger now so Phase 2 isn't a judgment call under time pressure.

## 5. Auth / identity provider
- Confirm whether the app uses Supabase Auth (GoTrue) for login, and if so, which providers are enabled (email/password, magic link, OAuth providers, phone).
- This is not a schema-translation item. Supabase Auth is a hosted identity provider; Convex has none built in. Record which replacement (Clerk, Auth0, WorkOS, Convex Auth) the team has chosen, or flag it as an open decision — either way, this needs to be scoped as its own workstream with its own timeline, not folded into the RLS→auth-check translation work in Phase 2.
- Note any place `auth.uid()` is used inside RLS policies or SQL functions — every one of those is a policy that needs the new identity check wired in during Phase 2.

## 6. File storage
- List every Supabase Storage bucket and its access policy (public vs. RLS-gated).
- Every file referenced from the database (avatar URLs, attachment paths, etc.) needs to be re-uploaded into Convex file storage and re-linked to a new storage ID — this is the same foreign-key-style re-linking problem as Phase 3, just for files instead of rows. Flag it now so it isn't discovered mid-migration.

## 7. Environment variables & secrets
- List the *names* only (never commit or paste values) of every secret used by Edge Functions and by the frontend build (`STRIPE_SECRET_KEY`, `OPENAI_API_KEY`, `RESEND_API_KEY`, etc.).
- These need to be re-set as Convex environment variables (`npx convex env set KEY value`, or via the dashboard) separately for the dev and prod deployments — they do not carry over automatically, and a migration that gets the data and schema right but forgets this will pass every test locally and then fail the first time an action tries to call Stripe in production.

## 8. Complex, aggregate, or full-text queries
- Search for `GROUP BY`, window functions, `to_tsvector`/`to_tsquery` (Postgres full-text search), and any Postgres-side stored procedures or views.
- None of these have a direct Convex equivalent — Convex has no query language beyond TypeScript over indexed reads. Each one needs to be either hand-written as JS/TS logic over an indexed subset of documents, or handled by a purpose-built Convex component (e.g. a search component for full-text search) rather than reimplemented from scratch. Flag these explicitly rather than discovering them when a page silently returns wrong results.
