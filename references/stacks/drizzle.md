# Drizzle ORM

## detection signals
`drizzle-orm` in dependencies and `drizzle-kit` in devDependencies, plus a `drizzle.config.ts` (or `.js`/`.json`) at the root. The schema is TypeScript rather than a DSL file, conventionally at `src/db/schema.ts`, `src/db/schema/*.ts`, `db/schema.ts`, or `lib/db/schema.ts` — find it from the config's `schema` field rather than guessing. Generated migrations land in the config's `out` directory, `./drizzle` by default, as numbered `.sql` files plus a `meta/_journal.json` that records which have been applied.

Read the config first; it names the database and the credentials path, both of which several checks need:
```ts
// drizzle.config.ts
export default defineConfig({
  schema: './src/db/schema.ts',
  out: './drizzle',
  dialect: 'postgresql',                          // 'postgresql' | 'mysql' | 'sqlite' | 'turso'
  dbCredentials: { url: process.env.DATABASE_URL! },
})
```
Older versions used `driver: 'pg'` with `connectionString` instead of `dialect`/`url`, and the `generate:pg` style subcommands rather than plain `generate`. Check `drizzle-kit --version` and the config's own shape before running a command from memory — this is the stack where the CLI surface has moved most between minor versions.

The driver in use is a separate dependency and decides some behaviour: `pg` (node-postgres), `postgres` (postgres.js), `@neondatabase/serverless`, `@vercel/postgres`, `mysql2`, `better-sqlite3`, `@libsql/client` (Turso), or D1 on Cloudflare. Note which, because `db.batch()` and connection pooling differ across them.

Drizzle is a data layer, not an application framework: read the app's framework stack file alongside this one for routes, auth, and the build.

## dev server
Not applicable for this stack. `npx drizzle-kit studio` opens a database browser (it serves locally, commonly on port 4983, and the UI is loaded from Drizzle's hosted domain — run it with `--help` for this version's flags). It is an unauthenticated read/write client: fine locally, a critical exposure if any start or deploy script launches it on a deployed host (SEC-013). Check no `package.json` script does.

## build
Drizzle generates no client — the schema is TypeScript and is type-checked by the app's own build, so there is no `generate` step to forget. What replaces it:

- `drizzle-kit generate` diffs the schema against the existing migration files and writes a new `.sql` migration plus a journal entry. It touches no database.
- `drizzle-kit migrate` applies pending migrations using the config's `dbCredentials`. This is the production command.
- `drizzle-kit push` synchronises the database to the schema **directly, with no migration file**. It is the development shortcut and, in a deploy path, a DAT-015 finding: the schema has no versioned history, nothing can be replayed into a fresh environment, and nothing can be rolled back.
- `drizzle-kit pull` (introspect) generates a schema from an existing database.
- `drizzle-kit check` reports collisions in the migration journal, and `drizzle-kit up` upgrades the journal's snapshot format.

Many projects apply migrations from application code at boot instead of via the CLI:
```ts
import { migrate } from 'drizzle-orm/node-postgres/migrator'
await migrate(db, { migrationsFolder: './drizzle' })
```
If you find that, check two things: the `drizzle/` folder has to be present in the deployed artifact (bundlers routinely drop it, and the app then boots against an unmigrated database), and a multi-instance rollout runs it concurrently on every instance — Drizzle takes a lock for this on most drivers, but confirm rather than assume, and note it for DAT-015's rollback question.

## env vars
`DATABASE_URL` (or whatever the config's `dbCredentials` reads) is the whole surface, and it is a full database credential. Drizzle inlines nothing into a client bundle and has no public prefix; the failure to grep for is the connection string under `NEXT_PUBLIC_`, `VITE_`, `PUBLIC_`, `EXPO_PUBLIC_`, or `REACT_APP_`, which is an immediate DAT-004 fail. Note that `drizzle.config.ts` reads `process.env` at CLI time, so the project usually loads `dotenv` at the top of that file — check which file it loads, because that is the env the migration commands will use and it is frequently not the same one the app uses.

Serverless drivers take their own variables: `@vercel/postgres` reads `POSTGRES_URL` and its pooled/unpooled variants; Neon's serverless driver takes the connection string with a pooler host. Where a pooler is in play, migrations may need the direct (unpooled) URL while the runtime uses the pooled one, exactly as on any Postgres stack — check whether the config and the app read different variables.

For DAT-017, compare the host and database name inside the connection string between preview and production. Identical means a preview branch's `drizzle-kit migrate` alters the live schema, which is the worst version of that finding.

## routes and handlers
Not applicable for this stack — the framework owns routes. What matters is where the queries live, since the data checks start from that list. Conventional locations: `src/db/index.ts` (the client), `src/db/queries/`, `lib/db/`, `server/`, or inline in route handlers. Find them with:

```bash
grep -rn 'db\.select(\|db\.insert(\|db\.update(\|db\.delete(\|db\.query\.\|db\.transaction(\|db\.execute(\|db\.batch(\|sql`\|sql\.raw(' --include='*.ts' --include='*.tsx' src app lib server 2>/dev/null
```

The client is constructed once and exported:
```ts
import { drizzle } from 'drizzle-orm/node-postgres'
export const db = drizzle(pool, { schema })
```
A `drizzle(...)` call or a new `Pool`/`postgres()` client constructed inside a request handler is a new connection per request — grep for the driver's constructor and expect one hit outside tests. On a serverless runtime the connection ceiling is REL-020's arithmetic; that is what the HTTP-based drivers (Neon serverless, `@vercel/postgres`) exist to sidestep.

## auth
Not applicable for this stack — Drizzle has no concept of a caller; read the framework's "auth" section. The consequence belongs to SEC-011 and is the same as on any ORM: **the connection has full rights to every row, so identity lives in the `where` clause of every query** and nowhere else, unless RLS is deliberately in play (see "data access"). If the database is Supabase, note that a Drizzle connection using the owner or `postgres` role bypasses the RLS policies entirely — those policies protect the PostgREST surface and do nothing here, so an RLS pass on one path must not be read as protection on the other.

## webhook handlers
Not applicable for this stack — the route belongs to the framework. Drizzle's part is the write, and PAY-003's dedup wants the insert-that-fails rather than the check-that-races:
```ts
const inserted = await db.insert(processedEvents).values({ id: event.id })
  .onConflictDoNothing().returning({ id: processedEvents.id })
if (inserted.length === 0) return ok()   // already handled
```
`onConflictDoNothing()` (Postgres/SQLite) or `onDuplicateKeyUpdate` (MySQL) with a `returning`/rowcount check is the safe shape; a `select` for the event id followed by the work followed by an insert is the PERF-017 race. Everything the handler writes alongside the entitlement belongs in one `db.transaction` (DAT-013), with the provider API call outside it.

## webhook verification snippet
Not applicable for this stack. See the framework's stack file for the raw-body read and the payment provider's stack file for the verification call.

## data access
**The schema is TypeScript**, so the schema of record and the migrations can disagree in a way that is invisible until you look at both. Read `src/db/schema*.ts` for what the developers declared and `drizzle/*.sql` for what actually ran; `drizzle-kit generate` producing a non-empty migration on a supposedly clean tree is the drift signal DAT-015 wants (generate it into a scratch `out` directory so you do not leave a file behind, and delete it after).

A representative table declaration, with everything the data checks look for:
```ts
export const posts = pgTable('posts', {
  id: uuid('id').primaryKey().defaultRandom(),
  userId: uuid('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  slug: text('slug').notNull(),
  amountCents: integer('amount_cents').notNull(),
  currency: text('currency').notNull(),
  createdAt: timestamp('created_at').notNull().defaultNow(),
}, (t) => [
  index('posts_user_id_idx').on(t.userId),
  index('posts_user_created_idx').on(t.userId, t.createdAt.desc()),
  uniqueIndex('posts_user_slug_uq').on(t.userId, t.slug),
])
```
The third argument's shape changed across versions — older Drizzle returns an object (`(t) => ({ ... })`), newer returns an array. Both declare the same things; read what this project uses rather than expecting one.

**DAT-009 — indexes.** Drizzle indexes primary keys and unique constraints and creates the foreign key constraint for `references()`, but **a plain scalar column you filter on gets nothing** unless you declare `index()`. Build the FK list from every `references(() => ...)` and every `*Id`/`*_id` column, then check each against the declared indexes *and* against the generated SQL, since an index declared in a schema that was never regenerated into a migration does not exist. Where the database is reachable, `select tablename, indexname, indexdef from pg_indexes where schemaname='public'` is authoritative. A composite `index().on(a, b)` does nothing for a query filtering only on `b`, and a `where userId = ? order by createdAt desc` wants the composite with the sort direction, as in the example above.

**DAT-011 — pagination.** `.limit(n)` is the ceiling and `.offset(n)` or a cursor `where(gt(t.id, lastId))` is the next page; on the relational API it is `db.query.posts.findMany({ limit, offset })`. A `db.select().from(posts)` with no `.limit()` returns the whole table. Two Drizzle-specific traps: `db.query.*.findMany({ with: { comments: true } })` fetches every related row unless the nested relation gets its own `limit`, and `.limit()` applied after a join limits *rows*, not parent entities, so a one-to-many join with a limit silently truncates a parent's children. Clamp any caller-supplied page size before it reaches the query.

**DAT-012 — batching.** `db.insert(t).values([row, row, row])` is one statement — the array form is the batched form, and a loop of `await db.insert(t).values(row)` is one round trip per row. `db.batch([...])` exists on the drivers that support it (libsql/Turso, D1) and sends several statements in one round trip; it is **not** a transaction on every driver, so do not read it as one for DAT-013. `Promise.all` over per-row inserts is concurrent, not batched, and exhausts the pool faster than the sequential version. Chunk large inserts at roughly a thousand rows to stay under the 65535 bind-parameter ceiling on Postgres.

**DAT-013 — transactions.**
```ts
await db.transaction(async (tx) => {
  const [order] = await tx.insert(orders).values({...}).returning()
  await tx.insert(items).values(rows.map(r => ({ ...r, orderId: order.id })))
})
```
**Every query inside must use `tx`, not `db`** — a call on the outer client runs on a different connection outside the transaction and will not roll back. That is the defect to grep for. `tx.rollback()` aborts explicitly. Nested `transaction` calls become savepoints. Keep external HTTP calls out: they hold row locks for a network round trip. Note that transactions are not supported on some serverless HTTP drivers (a single-shot HTTP driver has no session to hold one) — if the project uses one, check whether `db.transaction` is a real transaction on it or a no-op wrapper, because that changes the DAT-013 verdict entirely.

**SEC-038 — raw SQL.** The `sql` tagged template parameterizes its interpolations and is safe:
```ts
await db.execute(sql`select * from users where email = ${email}`)      // ${} becomes a bind parameter
```
The sinks:
- `sql.raw(str)` — splices text verbatim. Anything user-influenced inside it is injected, including the common `` sql`order by ${sql.raw(col)}` ``.
- `db.execute()` given a plain string rather than a `sql` template.
- A string built with `+` or a template literal and then wrapped — the tag only protects interpolations it performs itself.
`sql.identifier(name)` quotes an identifier safely, but it does not validate it, so a table or column name from user input still needs a hardcoded allowlist (SEC-040). `sql.join` and `inArray()` compose value lists safely; hand-building an `IN (...)` list by string concatenation does not.

**SEC-011 — ownership filters.** Every query returning or mutating user-owned data needs the owner in its `where`. `db.select().from(posts).where(eq(posts.id, id))` is the canonical IDOR; `where(and(eq(posts.id, id), eq(posts.userId, session.user.id)))` is the fix, and the same `and(...)` belongs on updates and deletes so a non-owner's mutation affects zero rows. Drizzle has no middleware layer to enforce this globally, which is a real difference from other ORMs — the mitigations that exist are wrapping every table's access in a `queries/` module that takes the user id as a required argument, or `.$dynamic()` query builders that always apply the predicate. Whichever the project uses, the audit is a per-call-site read; there is no single place that guarantees it.

**RLS.** Newer Drizzle versions can declare Postgres policies in the schema — `pgPolicy('name', { for: 'select', to: authenticatedRole, using: sql\`...\` })` attached to a table, plus `.enableRLS()`, and helper packs such as `crudPolicy` for Neon and Supabase setups. Where you find these, the policies are generated into migrations and the DAT-001/DAT-002 analysis is the same as on any Postgres stack — read the generated SQL, and verify with `pg_policies` rather than with the TypeScript. Where you do not find them, there is no RLS: say so explicitly rather than leaving it implied, because the absence is what makes SEC-011 critical here. And note the role question either way: policies do not apply to the table owner unless the table has `force row level security`, so a Drizzle connection using the owner role bypasses its own policies.

**DAT-014 — constraints.** `.unique()`, `uniqueIndex()`, `primaryKey()`, and `references()` all become real database constraints, with the `onDelete`/`onUpdate` behaviour declared in the `references()` options — an omitted `onDelete` is Postgres's `no action` default and worth naming. Check for the check-then-insert pattern (a select for an existing row followed by an insert) with no unique index behind it: that is DAT-014 and PERF-017 together, and `onConflictDoNothing()` is the one-line fix.

**PAY-005 — money.** `real()` and `doublePrecision()` are floats and an unconditional fail. `numeric('amount', { precision: 12, scale: 2 })` is a fixed-point pass with an explicit scale — but note that `numeric` comes back from the driver as a **string** in JavaScript, so any arithmetic on it has gone through `Number()` or `parseFloat` somewhere; grep for that. The cleanest shape is `integer`/`bigint` minor units with a currency column beside it. `bigint(..., { mode: 'number' })` silently loses precision above 2^53 — use `mode: 'bigint'` for anything that could exceed it.

**DAT-015 — from-zero migration run.** `drizzle-kit` reads its target from `drizzle.config.ts`'s `dbCredentials`, **not** from `DATABASE_URL` directly — so a `DATABASE_URL=` prefix works only if the config reads that variable, which it usually does but must be confirmed by opening the file. Where it does:
```bash
createdb prelaunch_scratch
DATABASE_URL=postgres://<user>@<host>/prelaunch_scratch npx drizzle-kit migrate
dropdb prelaunch_scratch
```
Where the config hardcodes the URL or reads a different variable, copy the config to a temporary file with the scratch URL and pass `--config <tmp config>` rather than editing the real one. Confirm the target before running anything that writes — the safest confirmation is that the scratch database is empty and `\dt` in `psql` shows nothing before and the full schema after. Use `migrate`, never `push` (which has no migration files to prove anything about) and never a reset. Run no seed. Delete the temporary config and drop the scratch database afterwards.

**DAT-016 — seeds.** Drizzle has no seed convention of its own, so look for a `package.json` script (`"db:seed": "tsx src/db/seed.ts"`), a `scripts/seed.ts`, a `drizzle-seed` dependency in newer projects, or an `insert` inside a migration file — that last one runs everywhere `migrate` runs, production included, and is a fail on its own. Read what the seed creates, check for an environment guard, and check no deploy or release command invokes it. A seeded account with a known password is SEC-060 as well as DAT-016.

## file uploads
Not applicable for this stack. Drizzle stores the metadata row (key, bucket, content type, owner, size); the bytes go to object storage. Check the row records an owner so the ownership filter has something to key on.

## background jobs
Not applicable for this stack — the queue belongs to the framework or a separate service. The Drizzle-specific concerns inside a job are connection pooling (a worker process opens its own pool; against a database with a hard connection ceiling that is REL-020's arithmetic) and chunking: a bulk import inside one `db.transaction` holds locks for its whole duration, so chunk it and make the chunks idempotent.

## error handling and logging
Drizzle surfaces the **driver's** errors rather than wrapping them in its own taxonomy, so branch on the Postgres SQLSTATE: `23505` unique violation, `23503` foreign key violation, `23502` not-null violation, `22P02` invalid input syntax. Those messages name the constraint, the table, and often the offending value, so returning `err.message` to a client leaks the schema and sometimes the data — SEC-009. Map them at the boundary.

Query logging is `drizzle(client, { logger: true })` or a custom logger implementing `logQuery(query, params)`. It prints the SQL **and the bound parameters**, which puts emails, tokens, and personal data into the logs — check it is off in production (COMP-016 for what is retained). A `db.select().toSQL()` call is the safe way to inspect a single query while auditing.

## security headers
Not applicable for this stack.

## known traps
- `where(eq(t.id, id))` with no owner predicate on a user-owned table: the id is the only thing needed. SEC-011 — and there is no middleware layer here that can fix it in one place.
- Assuming Postgres RLS protects Drizzle's queries: it does not, unless policies are declared and the connection role is not the table owner. DAT-001 and DAT-002 apply to the policies; SEC-011 owns the query path.
- `db.select().from(t)` with no `.limit()`, or a `with:` relation in the relational API with no limit of its own: DAT-011.
- A loop of awaited inserts instead of `values([...])`, or `Promise.all` over per-row writes: DAT-012.
- Queries inside `db.transaction(async (tx) => ...)` issued on the outer `db`: they run outside the transaction and do not roll back. DAT-013.
- `db.batch()` read as a transaction: on most drivers it is a batched round trip, not an atomic unit. DAT-013.
- `db.transaction` on a single-shot HTTP serverless driver, where it may not be a real transaction at all: DAT-013 — confirm against the driver's docs.
- `sql.raw()` on anything user-influenced, or `db.execute()` given a concatenated string: SEC-038.
- `drizzle-kit push` in a deploy, release, or CI path: no migration files, so nothing is replayable and nothing is reversible. DAT-015.
- The `drizzle/` migrations folder missing from the deployed bundle when migrations run at boot: the app starts against an unmigrated database. DAT-015.
- A schema change made in TypeScript but never `generate`d into a migration: the types compile and the column does not exist. DAT-015.
- An `insert` for demo data inside a migration file, or a seed script reachable from a deploy command: DAT-016, and SEC-060 if it creates an account with a known password.
- `real()`/`doublePrecision()` on a money column, or arithmetic on a `numeric` column that has been through `Number()`: PAY-005.
- A missing `onDelete` on `references()`, leaving Postgres's `no action` default: DAT-014, and it interacts with the unindexed-FK half of DAT-009 because every parent delete then scans the child table.
- A check-then-insert with no unique index behind it: DAT-014, PERF-017. `onConflictDoNothing()` plus the index is the fix.
- `drizzle-kit studio` launched by a script that runs on a deployed host: an unauthenticated database browser. SEC-013.
- Preview deployments sharing the connection string with production, so a branch's `drizzle-kit migrate` alters the live schema: DAT-017.

## runtime probe hints
There is no HTTP surface to probe — every probe here is SQL or CLI, and all of it is read-only unless stated.

**Confirm the target first.** Read the connection string out of the running process (`printenv | grep -iE 'database|postgres'`) rather than out of `.env`, redact the password when recording it, and open `drizzle.config.ts` to see which variable the CLI itself will read — the config and the app do not always read the same one, and that difference is how a migration lands in the wrong database. If either names anything resembling production, stop.

**Read-only schema questions** go to `psql` against the same URL, because it sees what the database has rather than what the TypeScript claims:
```bash
psql "$DATABASE_URL" -c "select tablename, indexname, indexdef from pg_indexes where schemaname='public' order by tablename"
psql "$DATABASE_URL" -c "\d+ <table>"
psql "$DATABASE_URL" -c "select conname, contype, pg_get_constraintdef(oid) from pg_constraint where connamespace='public'::regnamespace"
psql "$DATABASE_URL" -c "select relname, relrowsecurity from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r'"
psql "$DATABASE_URL" -c "select tablename, policyname, cmd, qual, with_check from pg_policies where schemaname='public'"
```
The last two matter whenever `pgPolicy` or `.enableRLS()` appears in the schema: verify the policies against `pg_policies`, not against the TypeScript, and check whether the role in the connection string is the table owner (owners are exempt without `force row level security`).

For DAT-009's measurement half, `explain (analyze, buffers) <the slowest list query>` — on a **select only**, since `analyze` executes the statement. `db.select()...toSQL()` prints the SQL and parameters for a query you want to explain without running the app.

**Drift** (DAT-015): run `npx drizzle-kit generate --out <a scratch directory>` and read whether it emits a migration. An empty result is the pass; a generated file means the schema and the migrations disagree. Delete the scratch directory afterwards so nothing is left in the tree.

**Never** run `drizzle-kit push` or any reset during an audit — `push` mutates the target database's schema in place to match the TypeScript, which on a development database is a silent, unversioned change and on anything else is worse. The from-zero migration run for DAT-015 is `drizzle-kit migrate` against a freshly created scratch database, exactly as written under "data access".

**Ownership probes** (SEC-011) go through the app's own HTTP endpoints, since Drizzle has no notion of a caller: create a row as test account A, then read and mutate it as test account B and expect 401/403/404. See the framework's "runtime probe hints" for obtaining the two sessions.
