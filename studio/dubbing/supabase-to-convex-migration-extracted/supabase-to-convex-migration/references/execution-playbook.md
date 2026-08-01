# Execution Playbook & Pitfalls

This is Phase 3 in full, plus the complete pitfall list referenced from SKILL.md. The ID re-linking sequence below mirrors Convex's own documented approach to migrating off Postgres — it isn't improvised, so don't simplify it to save steps; each step exists because skipping it is a specific, real failure mode described under it.

## The sequence

### 1. Export the Postgres data
For each table, dump rows as JSON Lines. From `psql`:
```sql
\copy (SELECT row_to_json(t) FROM your_table t) TO '/path/to/your_table.jsonl';
```
For large tables (multi-GB), a one-shot dump may not be practical — Convex's import path also supports a streaming integration (Airbyte) for that case instead of a flat-file dump.

### 2. Import with loose types
```bash
npx convex import --format jsonLines --replace --table your_table /path/to/your_table.jsonl
```
Before this will succeed, `convex/schema.ts` needs a table definition matching the dumped shape. Any field that used to be a foreign key gets typed as `v.string()` for now — not `v.id()` yet, and definitely not a made-up `v.uuid()` (there is no such validator). Give the table an index on that field so it can be looked up by the old ID:

```ts
// convex/schema.ts — first pass, intentionally loose
export default defineSchema({
  customers: defineTable({
    legacyId: v.string(), // old Postgres UUID, kept permanently — see step 5
    name: v.string(),
    email: v.string(),
  }).index("by_legacy_id", ["legacyId"]),

  orders: defineTable({
    customerId: v.union(v.string(), v.id("customers")), // old UUID OR real Convex id
    total: v.number(),
  }),
});
```

If several tables reference each other and you don't want to hand-hold every field through this two-phase typing, Convex also supports deploying with `schemaValidation: false` for the duration of the migration, then turning it back on once every table is re-linked. Either approach works; the union-type approach is more precise about which fields are still mid-migration, which is usually worth the extra typing.

### 3. Write the re-linking migration
Write a helper that resolves either an old ID or a real one, then a migration that walks every row and rewrites it:

```ts
// convex/migrations.ts
import { migrations } from "./migrations_setup"; // per the migrations component's own setup docs
import { QueryCtx } from "./_generated/server";
import { Id } from "./_generated/dataModel";

async function resolveCustomer(ctx: QueryCtx, ref: string | Id<"customers">) {
  const asId = ctx.db.normalizeId("customers", ref);
  if (asId !== null) return ctx.db.get(asId); // already re-linked
  return ctx.db
    .query("customers")
    .withIndex("by_legacy_id", (q) => q.eq("legacyId", ref))
    .unique();
}

export const relinkOrderCustomerId = migrations.define({
  table: "orders",
  migrateOne: async (ctx, doc) => {
    const customer = await resolveCustomer(ctx, doc.customerId);
    if (!customer) throw new Error(`No customer found for order ${doc._id}`);
    if (customer._id !== doc.customerId) {
      await ctx.db.patch(doc._id, { customerId: customer._id });
    }
  },
});
```

Use the official `migrations` component (`@convex-dev/migrations`) for the walk itself rather than a hand-rolled loop — see the read-limit pitfall below for why that matters once a table has any real size to it.

### 4. Tighten the schema
Once the migration has run and every `orders.customerId` holds a real Convex ID, change the field type:
```ts
orders: defineTable({
  customerId: v.id("customers"),
  total: v.number(),
}),
```
Deploy. If any document still has a bare string in that field, the deploy fails — that failure is the migration telling you it isn't done yet, not a bug. Treat a clean deploy here as your actual completion signal for this table, not "the migration script ran without throwing."

### 5. Keep `legacyId`, don't drop it
Once `customerId` is a strict `v.id()`, it's tempting to also delete the `legacyId` field on `customers` itself since "the migration is done." Don't, at least not immediately. Keep it, indexed, as permanent metadata: it's the only way to trace a support ticket, an old email, or an external webhook that still references the Postgres UUID back to the right document, and it's your fastest way to debug a bad re-link if Phase 5 verification turns up a mismatch.

## Pitfalls

**The foreign-key trap.** Postgres uses UUIDs for relationships; Convex uses table-scoped native IDs. Importing a UUID straight into a `v.id()` field doesn't "mostly work" — it fails to deploy, because a `v.id("table")` value has to actually resolve to a document in that table. Fix: the loose-union import → migration → tighten sequence above, not a cast or a type assertion.

**ID re-linking silently skipped.** The union type compiles happily forever. Nothing forces you to actually run the migration and tighten the schema — a team can ship with every relationship field still holding raw strings and not notice until a query that assumes a real `v.id()` throws in production. Fix: treat "schema successfully redeployed with the strict `v.id()` type" as the actual finish line for this step, not "the import command exited 0."

**Security logic left half-applied.** RLS did two jobs — gatekeeping and row-filtering — in one policy. It's easy to port only the gatekeeping (an identity check at the top of the function) and forget the row-filtering, because the function "has an auth check now" and looks done. It isn't: without a matching `.withIndex`/`.filter` on the ownership/tenant field, an authenticated user can read every other user's rows. Fix: for every ported policy, write down both halves separately and confirm both landed, not just the first one.

**Reactivity code left in place.** It's common to keep the old `useEffect`/`useState` fetch logic "temporarily" alongside a new `useQuery` call, planning to remove it later. This isn't neutral — Convex's automatic re-render on data change plus a manual refetch on the same data can produce double-fetches or a stale-then-flash UI. Fix: delete the manual fetching code in the same change that adds `useQuery`, not after.

**Read limits on large-table migrations.** Convex caps how many documents a single query or mutation can read, to keep the database fast. A migration script that does `ctx.db.query("orders").collect()` and loops over everything in one call works fine against seed data and throws against a real production-sized table. Fix: use the official `migrations` component (it paginates internally) instead of a hand-rolled `.collect()` loop, and in general prefer `.take(n)` or `.paginate()` over `.collect()` anywhere a table could grow unbounded.

**No verification or rollback plan.** A migration plan that ends at "the new backend compiles" is a plan to find out about data-migration bugs in production. Fix: run the full sequence against a Convex dev deployment loaded with a copy of prod data first, diff document counts against the Postgres source per table, spot-check a sample of re-linked IDs by hand, and keep the old Supabase project intact and read-only until that verification is signed off — see Phase 5 in SKILL.md.
