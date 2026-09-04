# Prisma

## detection signals
`prisma/schema.prisma` (or a `prisma/schema/` folder of `.prisma` files in versions with the multi-file schema enabled), `@prisma/client` in dependencies and `prisma` in devDependencies, `prisma/migrations/<timestamp>_<name>/migration.sql`, and a `DATABASE_URL` in the env examples. A `package.json` with a top-level `"prisma": { "seed": ... }` block, or `prisma generate` in a `postinstall`/`build` script, confirms it.

Read the `datasource` block first — it names the database and therefore which of the checks below apply:
```prisma
datasource db {
  provider  = "postgresql"   // or mysql, sqlite, sqlserver, mongodb, cockroachdb
  url       = env("DATABASE_URL")
  directUrl = env("DIRECT_URL")        // present when url points at a pooler
  relationMode = "prisma"              // if present, see "known traps" — no FKs in the database
}
```
`prisma --version` reports the CLI and engine versions; the majors differ enough on `createMany` support, transaction defaults, and the Rust-free client that you should read the version before asserting a default below. `prisma/migrations/` being absent while `schema.prisma` exists means the project uses `prisma db push` and has no migration history at all — that is a DAT-015 finding on its own, not a detection ambiguity.

Prisma is a data layer, not an application framework: read the app's framework stack file alongside this one for routes, auth, and the build.

## dev server
Not applicable for this stack. Two adjacent commands:
- `npx prisma studio` opens a database browser on port 5555. It is a full read/write client with no authentication — useful locally, and a critical exposure if it is ever run on a deployed host or port-forwarded (SEC-013 territory; check no start or deploy script launches it).
- `npx prisma generate` regenerates the client into `node_modules/.prisma/client`. It must run after every schema change and is normally wired into `postinstall`; a missing `generate` in the deploy pipeline produces a build that compiles against a stale client, which is REL-013's shape.

## build
`prisma generate` is the build step, and it is the one that gets skipped. Check `package.json` for `"postinstall": "prisma generate"` or a `build` script that runs it — some hosting platforms cache `node_modules` and skip `postinstall`, so a `build` script that runs `prisma generate && next build` is the safer form and its absence on such a platform is a real deploy failure.

**`prisma migrate deploy` is the production migration command.** It applies pending migrations and nothing else: it never resets, never prompts, never generates. `prisma migrate dev` is development-only — it can and does prompt to reset the database when it detects drift, and it runs the seed afterwards. **`prisma migrate reset` drops the database, re-applies every migration, and runs the seed; it is destructive and DAT-015 forbids running it against any database the app or the audit connects to.** Find which command the deploy runs (`Dockerfile` `CMD`, `release` command, `vercel-build`, a `predeploy` hook, the CI workflow) and record it; `migrate dev` or `db push` in a production deploy path is a finding on its own.

Whether migrations run at deploy time or as a separate step matters for DAT-015's rollback question: a migration executed inside the app's start command runs once per instance and races itself on a multi-instance rollout.

## env vars
`DATABASE_URL` is the only one Prisma requires, read through `env("DATABASE_URL")` in the datasource block; Prisma loads `.env` from the project root (and from `prisma/.env` in older layouts) itself, independent of whatever the framework loads. It never inlines anything into a client bundle — there is no public prefix here — but the connection string is a full database credential, so `DATABASE_URL` under `NEXT_PUBLIC_`, `VITE_`, `PUBLIC_`, or `EXPO_PUBLIC_` is an immediate DAT-004 fail, and so is any import of `@prisma/client` from a file inside a `"use client"` boundary (the client cannot run there, but the bundler will try, and the failure mode people reach for is moving the URL to a public variable).

`DIRECT_URL` appears when `DATABASE_URL` points at a connection pooler: the pooler cannot run migrations (they need session-level statements), so the CLI uses `DIRECT_URL` while the runtime uses the pooled one. Both are secrets. On a pooler, `?pgbouncer=true` and `connection_limit=` in the query string are the pool settings; on a serverless runtime, `connection_limit=1` per instance plus a pooler is the shape that does not exhaust the database.

For DAT-017, the value to compare between preview and production is the host and database name inside `DATABASE_URL` (and `DIRECT_URL`) — identical means previews are migrating and writing production data, which on this stack is worse than usual because a preview branch's `migrate deploy` applies its schema changes to the live database.

## routes and handlers
Not applicable for this stack — the framework owns routes. What you need from here is *where the queries live*, since half the data checks start from that list. Conventional locations: `lib/db.ts`, `lib/prisma.ts`, `src/server/db.ts`, `server/`, `services/`, `repositories/`, or inline in the route handlers themselves. Find every query with:

```bash
grep -rn 'prisma\.\|\.findMany(\|\.findFirst(\|\.findUnique(\|\.create(\|\.createMany(\|\.update(\|\.updateMany(\|\.delete(\|\.deleteMany(\|\.upsert(\|\$queryRaw\|\$executeRaw\|\$transaction' --include='*.ts' --include='*.tsx' --include='*.js' src app lib server 2>/dev/null
```

The client should be a single shared instance. The standard pattern guards against hot-reload creating a new pool per module reload:
```ts
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient }
export const prisma = globalForPrisma.prisma ?? new PrismaClient()
if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = prisma
```
A `new PrismaClient()` constructed inside a request handler is a new connection pool per request and will exhaust the database under any load — grep for `new PrismaClient(` and expect exactly one hit outside tests.

## auth
Not applicable for this stack — Prisma has no concept of a caller. Read the framework's "auth" section for how the session is established. The consequence is the important part and it belongs to SEC-011: **Prisma connects as one database role with full rights to every row**, so identity has to be applied by the application in the `where` clause of every single query. There is no RLS, no policy, and no default scope. See "data access" for what that means in practice.

If the underlying database is Supabase or another Postgres with RLS policies already written, note that Prisma's connection normally uses the `postgres`/owner role, which **bypasses those policies entirely** — the policies are still there and still protect the PostgREST surface, and they do nothing for Prisma's queries. Read the supabase stack file alongside this one and do not let an RLS pass on one path be read as protection on the other.

## webhook handlers
Not applicable for this stack — the route belongs to the framework. Prisma's part is what the handler writes, and two checks land here. PAY-003's deduplication wants a table keyed on the provider's event id with a unique constraint, and the safe shape in Prisma terms is the insert that fails rather than the check that races:
```ts
try {
  await prisma.processedEvent.create({ data: { id: event.id } })
} catch (e) {
  if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') return ok() // already handled
  throw e
}
```
`findFirst` followed by `create` is the check-then-act that PERF-017 fails. DAT-013 wants the entitlement write and everything alongside it inside one `$transaction`, with the provider API call outside it.

## webhook verification snippet
Not applicable for this stack. See the framework's stack file for the raw-body read and the payment provider's stack file for the verification call.

## data access
**`prisma/schema.prisma` is the schema of record** and `prisma/migrations/*/migration.sql` is the SQL that actually ran. Read both: the `.prisma` file is what the developers believe, and the migration SQL is what the database has. `npx prisma migrate diff --from-migrations ./prisma/migrations --to-schema-datamodel ./prisma/schema.prisma --shadow-database-url <scratch url>` prints the difference, and an empty diff is the DAT-015 drift pass. `npx prisma migrate status` reports pending and failed migrations against whatever `DATABASE_URL` points at — read the connection it names before trusting the answer.

**DAT-009 — indexes.** Prisma creates indexes for `@id` and `@unique` and, on relational databases with real foreign keys, the FK constraint itself; it does **not** index a plain scalar column you filter on. The declarations to look for:
```prisma
model Post {
  id        String   @id @default(cuid())
  userId    String
  createdAt DateTime @default(now())
  user      User     @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@index([userId])
  @@index([userId, createdAt(sort: Desc)])   // for where userId = ? order by createdAt desc
  @@unique([userId, slug])
}
```
Build the FK list from every `@relation(fields: [...])` and every `*Id` scalar, then check each against the `@@index`/`@@unique` declarations and against the generated migration SQL. Where a live database is reachable, `select tablename, indexname, indexdef from pg_indexes where schemaname='public'` beats reading the schema, because an index added by hand and one dropped by a later migration are both invisible in `schema.prisma`. Note that a composite `@@index([a, b])` does nothing for a query filtering only on `b`.

**DAT-011 — pagination.** `findMany()` with no `take` returns the entire table. Every list query needs a `take`, and a caller-supplied page size needs a clamp before it reaches the query — `take: Math.min(Number(limit) || 20, 100)`. Offset pagination is `skip`/`take`; cursor pagination is `cursor: { id: lastId }, skip: 1, take: n` and is the one that stays fast on deep pages. Grep for `findMany(` and check each hit for a `take`; pay particular attention to `include`d relations, since `include: { comments: true }` on a list of posts is an unbounded fetch nested inside a bounded one — the relation needs its own `take`.

**DAT-012 — batching.** A loop of `await prisma.x.create()` is one round trip per row. `createMany({ data: rows })` is one statement (`skipDuplicates` is available on the databases that support it — not SQLite, and check your version). `updateMany`/`deleteMany` cover the write side. Two near-misses that still fail: `await Promise.all(rows.map(r => prisma.x.create(...)))` is concurrent rather than batched and exhausts the pool faster than the sequential version, and an unchunked `createMany` over unbounded input hits the driver's bind-parameter ceiling (65535 on Postgres) — chunk at roughly a thousand rows.

**DAT-013 — transactions.** Two forms:
```ts
await prisma.$transaction([ prisma.a.create(...), prisma.b.update(...) ])            // batch, independent ops
await prisma.$transaction(async (tx) => {                                            // interactive
  const order = await tx.order.create({ data: {...} })
  await tx.item.createMany({ data: items.map(i => ({ ...i, orderId: order.id })) })
})
```
Inside the interactive form **every query must use `tx`, not `prisma`** — a call on the outer client runs on a different connection outside the transaction and will not roll back, and it is the defect to grep for. Interactive transactions have a wall-clock timeout and a maximum wait for a connection (small defaults, on the order of a few seconds; the exact numbers move between versions, so read `timeout`/`maxWait` in the options rather than assuming), which is a second reason an external HTTP call inside a transaction is wrong: it holds row locks for a network round trip and then aborts.

**SEC-038 — raw SQL.** The tagged template `$queryRaw` is parameterized and safe:
```ts
await prisma.$queryRaw`select * from users where email = ${email}`        // safe: ${} becomes a bind parameter
```
The sinks, all of which must be traced to a trusted source:
- `$queryRawUnsafe(sql)` and `$executeRawUnsafe(sql)` — a plain string, interpolate anything and it is injected.
- `Prisma.raw(...)` inside an otherwise-safe tagged template — it splices text in verbatim, so `` prisma.$queryRaw`... order by ${Prisma.raw(col)}` `` is injectable through `col`.
- A string built with `+` or a template literal and *then* passed to `$queryRaw` — the tag only protects interpolations it performs itself, so `` prisma.$queryRaw(`select ... ${x}`) `` (note the call parentheses) is the unsafe form wearing the safe form's name. Grep for `$queryRaw(` with a paren as well as for `$queryRawUnsafe`.
- Dynamic identifiers — table, column, and sort direction cannot be bound as parameters and must come from a hardcoded allowlist (SEC-040). `Prisma.sql` and `Prisma.join` compose safely for value lists.

**SEC-011 — ownership filters, because there is no RLS.** Every query that returns or mutates user-owned data must carry the owner in its `where`, and "the route checked the session" is not enough: the query is what fetches the row. `findUnique({ where: { id } })` on a user-owned model is the canonical IDOR — it finds the row by id alone. The safe forms are `findFirst({ where: { id, userId: session.user.id } })`, or `updateMany({ where: { id, userId }, data })` which affects zero rows for a non-owner instead of throwing. Enforcing it once rather than per call site is a Prisma Client extension:
```ts
const scoped = (userId: string) => prisma.$extends({
  query: { post: { $allOperations({ args, query }) {
    args.where = { ...args.where, userId }
    return query(args)
  }}},
})
```
(`$use` middleware is the older, now-deprecated equivalent; note which one the project has.) Where the database is Postgres with RLS policies you want Prisma to respect, the only way is to set the role and claims on the same connection inside an interactive transaction — `await tx.$executeRaw`select set_config('request.jwt.claims', ${claims}, true)`` followed by `set local role authenticated` — and to connect as a role that RLS actually applies to. That is a deliberate architecture, not an accident; if you find it, check the role in `DATABASE_URL` is not the table owner, because an owner is exempt unless the table has `force row level security`.

**DAT-014 — constraints.** `@unique`, `@@unique([a, b])`, and `@@id` become real database constraints. `@relation` becomes a real foreign key with the `onDelete`/`onUpdate` behaviour you declare — **unless `relationMode = "prisma"` is set in the datasource**, in which case Prisma emulates relations in the client and creates **no foreign key constraints in the database at all**, leaving referential integrity to application code and to nothing else if anything writes to the database outside Prisma. That flag is required by some hosted MySQL products (PlanetScale historically) and is a legitimate choice there; anywhere else it is a DAT-014 finding, and either way it must be named. Also check for the check-then-insert pattern (`findUnique` then `create`) backed by no `@unique` — that is the race PERF-017 owns.

**PAY-005 — money.** `Float` maps to `double precision` and is an unconditional fail for money. `Decimal` maps to a fixed-point column and is a pass **with an explicit scale**: `amount Decimal @db.Decimal(12, 2)`. An unqualified `Decimal` takes the provider's default precision, which is large and unhelpful — declare it. The cleanest shape remains `Int`/`BigInt` minor units with a `currency String` beside it, which is also what Stripe and most processors put on the wire. Note that `Decimal` values arrive in JavaScript as a `Decimal.js` object, not a number, so anything doing arithmetic on them with `+` has already converted to float somewhere — grep for `Number(` around them.

**DAT-015 — from-zero migration run.** Prisma reads `DATABASE_URL` from the environment, so a one-shot prefix is enough to redirect it. Confirm the redirect took *before* running anything that writes:
```bash
createdb prelaunch_scratch
DATABASE_URL=postgres://<user>@<host>/prelaunch_scratch npx prisma migrate status   # read the connection it prints
DATABASE_URL=postgres://<user>@<host>/prelaunch_scratch npx prisma migrate deploy
dropdb prelaunch_scratch
```
`migrate deploy` runs no seed and never resets, which is why it is the right command here. If `migrate status` names anything other than the scratch database, stop and record `error: could not redirect migrate tool to scratch database`. Never run `prisma migrate reset` or `prisma migrate dev` for this — both destroy the target database, and DAT-015 forbids it.

**DAT-016 — seeds.** The seed command is declared in `package.json`:
```json
"prisma": { "seed": "tsx prisma/seed.ts" }
```
`prisma db seed` runs it explicitly, and **`prisma migrate dev` and `prisma migrate reset` run it automatically** — which is the path by which seed data reaches an environment nobody intended. `prisma migrate deploy` does not. Read `prisma/seed.ts` for what it creates, check for an environment guard, and check no deploy or release command invokes `db seed`, `migrate dev`, or `migrate reset`. A seeded account with a known password is SEC-060 as well as DAT-016.

## file uploads
Not applicable for this stack. Prisma stores the metadata row (key, bucket, content type, owner, size); the bytes go to object storage. Check that the row records the owner so the ownership filter above has something to key on, and that the `Bytes` column type is not being used to store file contents in the database, which is a different problem.

## background jobs
Not applicable for this stack — the queue belongs to the framework or a separate service. Two Prisma-specific concerns that land in a job:
- **Connection pool exhaustion.** Each `PrismaClient` holds its own pool (`connection_limit` in the URL, defaulting to a formula based on CPU count). A worker process and a web process each open one; a serverless function opens one per warm instance. Against a database with a hard connection ceiling this is REL-020's arithmetic, and the fix is a pooler plus `connection_limit=1`.
- **Long-running jobs inside a transaction.** The interactive transaction timeout applies to jobs exactly as it does to requests; a bulk import inside one `$transaction` will abort partway. Chunk it, and make the chunks idempotent.

`$disconnect()` matters for a script that should exit; a long-lived server should not call it per request.

## error handling and logging
Errors are `Prisma.PrismaClientKnownRequestError` with a code. The ones worth branching on: `P2002` unique constraint violation (the `meta.target` names the columns), `P2003` foreign key constraint failure, `P2025` record not found (thrown by `update`/`delete` on a missing row, which is why `updateMany` is the friendlier ownership-scoped form). `PrismaClientValidationError` is a programming error. **These messages include table and column names and often the offending value**, so returning `err.message` to a client leaks the schema and sometimes the data — SEC-009. Map them to an application error at the boundary.

Logging: `new PrismaClient({ log: ['query', 'warn', 'error'] })` prints every query, and depending on the version and whether events or stdout are used, the bound parameters with them — which puts emails, tokens, and personal data in the logs (COMP-016 territory for what gets retained). Check that query logging is not enabled in production, and that any `emit: 'event'` handler is not writing params to the log sink.

## security headers
Not applicable for this stack.

## known traps
- `findUnique({ where: { id } })` on a user-owned model: the ownership check is missing and the id is the only thing needed. SEC-011.
- A query relying on RLS policies that exist in the database, while Prisma connects as the owner role and bypasses them: DAT-001 and DAT-002 pass on the PostgREST path and mean nothing here. SEC-011 owns the verdict.
- `findMany()` with no `take`, or an `include`d relation with no `take` inside a paginated parent: DAT-011.
- A loop of awaited `create` calls, or `Promise.all` over per-row writes: DAT-012.
- Queries inside `$transaction(async (tx) => ...)` issued on the outer `prisma` client rather than `tx`: they run outside the transaction and do not roll back. DAT-013.
- An external API call (Stripe, email, fetch) inside a transaction: holds locks for a network round trip and trips the transaction timeout. DAT-013.
- `$queryRawUnsafe` / `$executeRawUnsafe`, `Prisma.raw()` on a value from the request, or `$queryRaw(` called with a pre-built string instead of used as a tag: SEC-038.
- `relationMode = "prisma"`: no foreign keys exist in the database, so nothing outside Prisma is constrained. DAT-014.
- `Float` on a money column, or an unqualified `Decimal` with no `@db.Decimal(p, s)`: PAY-005.
- `prisma migrate dev`, `prisma db push`, or `prisma migrate reset` anywhere in a deploy, release, or start command: `dev` and `reset` destroy data and run the seed (DAT-016), and `db push` leaves no migration history (DAT-015).
- `prisma migrate reset` run "to get a clean state" during the audit: it drops the database and takes the shared test account with it. DAT-015 forbids it.
- `prisma db seed` reachable from a production command, or a seed that creates an account with a known password: DAT-016, SEC-060.
- `new PrismaClient()` inside a request handler or module that reloads: a pool per instance, and connection exhaustion under load. REL-020.
- `prisma generate` missing from the deploy pipeline on a platform that skips `postinstall`: the build ships a stale client. REL-013.
- Returning `err.message` from a Prisma error to the client: leaks table, column, and sometimes the value. SEC-009.
- `prisma studio` started by any script that runs on a deployed host: an unauthenticated read/write database browser. SEC-013.
- Preview deployments sharing `DATABASE_URL` with production, so a branch's `migrate deploy` alters the live schema: DAT-017.

## runtime probe hints
There is no HTTP surface to probe — every probe here is SQL or CLI, and all of it is read-only unless stated.

**Confirm which database you are pointed at before anything else.** Read `DATABASE_URL` out of the running process (`printenv | grep -i database`) rather than out of `.env`, since the platform's value wins, and redact the password when recording it. `npx prisma migrate status` prints the connection it used; treat that output as the ground truth for which database subsequent commands will touch. If it names anything resembling production, stop.

**Read-only schema and index questions** are best answered by `psql` against the same URL, because they see what the database has rather than what the schema file claims:
```bash
psql "$DATABASE_URL" -c "select tablename, indexname, indexdef from pg_indexes where schemaname='public' order by tablename"
psql "$DATABASE_URL" -c "\d+ <table>"     # columns, types, constraints, FK actions
psql "$DATABASE_URL" -c "select conname, contype, pg_get_constraintdef(oid) from pg_constraint where connamespace='public'::regnamespace"
```
For DAT-009's measurement half, `explain (analyze, buffers) <the slowest list query>` — on a **select only**, since `analyze` executes the statement. Use plain `explain` for anything that writes. A `Seq Scan` on a large table is the finding.

**Drift** (DAT-015): `npx prisma migrate diff --from-migrations ./prisma/migrations --to-schema-datamodel ./prisma/schema.prisma --shadow-database-url postgres://<user>@<host>/prelaunch_shadow` — it needs a scratch shadow database it may create and drop, so give it one that is not the development database. An empty diff is the pass.

**Never** run `prisma migrate reset`, `prisma migrate dev`, `prisma db push`, or `prisma db seed` during an audit. The from-zero migration run for DAT-015 is `migrate deploy` against a freshly created scratch database, exactly as written under "data access", and the scratch database is dropped afterwards.

**Ownership probes** (SEC-011, DAT-002's spirit) go through the app's own HTTP endpoints rather than through Prisma, since Prisma has no notion of a caller: create a row as test account A, then request and mutate it as test account B and expect 401/403/404. See the framework's "runtime probe hints" for obtaining the two sessions.
