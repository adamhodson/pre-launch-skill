# Supabase

## detection signals
`supabase/config.toml` plus a `supabase/migrations/` directory is the strongest signal — that is a CLI-managed project. In dependencies: `@supabase/supabase-js`, `@supabase/ssr` (the current server-side helper), `@supabase/auth-helpers-nextjs` / `-react` / `-sveltekit` (the deprecated predecessor, and its presence usually means the auth code predates the `getUser()` guidance below), `supabase-py`, `supabase` (Dart/Flutter). Env names `SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `VITE_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`. A hosted URL has the shape `https://<project-ref>.supabase.co`, and that `<project-ref>` is the identity DAT-017 compares between preview and production.

A project can use Supabase as *only* a Postgres host — a `DATABASE_URL` pointing at `db.<ref>.supabase.co` or a pooler host (`aws-0-<region>.pooler.supabase.com`, ports 5432 session / 6543 transaction) with Prisma or Drizzle on top and no `@supabase/supabase-js` anywhere. That project has no PostgREST surface reachable by the browser, which changes DAT-001's threat model and removes the bearer probe entirely; read the prisma or drizzle stack file alongside this one and say which shape you found. Also check whether `supabase/` is CLI-managed at all: a project where the schema was edited in the dashboard has no migration files, which is a DAT-015 finding on its own.

Version matters here more than on most stacks. `supabase --version` for the CLI, and the `@supabase/supabase-js` major from the lockfile. Key naming, `config.toml` key names, the local mail catcher, and Realtime authorization all changed across releases; read the file and the CLI's own `--help` before asserting any default below.

## dev server
`supabase start` boots the local stack in Docker (Docker must be running; the first start pulls several images and is slow). `supabase status` prints the live values and is the only trustworthy source for them — ports are configurable in `config.toml` and a project with two stacks on one machine will have moved them. The defaults:

| service | default port | what it is |
|---|---|---|
| API gateway (Kong) | 54321 | REST, Auth, Storage, Realtime, Edge Functions all mount here |
| Postgres | 54322 | direct SQL, `postgres:postgres` superuser locally |
| Studio | 54323 | the local dashboard |
| mail catcher | 54324 | Inbucket in older CLI versions, Mailpit in newer ones (FLOW-001) |
| Edge Functions inspector | 8083 | only when `supabase functions serve` is running |

`supabase status` also prints the local `anon` and `service_role` keys and the JWT secret. Older CLI versions used a fixed demo keypair signed with the well-known local secret `super-secret-jwt-token-with-at-least-32-characters-long`; newer ones generate per-project values. Take them from `supabase status`, never from memory, and never treat a local key as evidence about production.

`supabase stop` halts the stack and keeps the data; `supabase stop --no-backup` discards it. **`supabase db reset` drops and recreates the local database, re-runs every migration, and runs `supabase/seed.sql`.** It is destructive and DAT-015 explicitly forbids running it against any database the app or the audit connects to — including the local development database, because the shared test account other checks depend on lives in it. If you need a clean database for the DAT-015 from-zero migration run, create a separate one (see "data access") rather than resetting this one.

Edge Functions run separately: `supabase functions serve` (all functions) or `supabase functions serve <name>`, reachable at `http://localhost:54321/functions/v1/<name>`.

## build
Not applicable for this stack — Supabase has no build step and the app's own framework owns that (see the framework's stack file). The deploy-side equivalents, which several checks care about, are: `supabase link --project-ref <ref>` to bind the local project to a hosted one, `supabase db push` to apply pending migrations to the linked project, `supabase functions deploy <name>` for Edge Functions, and `supabase gen types typescript` for the generated database types (a stale `database.types.ts` relative to the migrations is drift worth naming under DAT-015). Whether these run in CI is what tells you if the schema in the repo is actually the schema in production.

## env vars
| variable | prefix seen | secret? |
|---|---|---|
| `SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_URL` / `VITE_SUPABASE_URL` / `EXPO_PUBLIC_SUPABASE_URL` | public | no — the URL is public by design |
| `SUPABASE_ANON_KEY` (publishable) | public | no — it ships in the browser by design, and RLS is what makes that safe |
| `SUPABASE_SERVICE_ROLE_KEY` (secret) | **server only** | yes — bypasses every RLS policy |
| `SUPABASE_JWT_SECRET` | server only | yes |
| `DATABASE_URL` / `DIRECT_URL` | server only | yes |

**DAT-004 is the load-bearing one on this stack.** The `service_role` key is the database with no rules: it bypasses RLS entirely, so it makes every DAT-001 and DAT-002 policy irrelevant wherever it is used. Fail immediately on `service_role` (or any variable holding an `sb_secret_` / service-role value) carrying a client-visible prefix — `NEXT_PUBLIC_`, `VITE_`, `PUBLIC_`, `EXPO_PUBLIC_`, `REACT_APP_` — regardless of what the code does with it, and on the same value appearing in a mobile app's `app.json`, `Info.plist`, or `strings.xml`. Then grep the built client bundle for the literal value and for the string `service_role`. A service-role JWT decodes to a payload containing `"role":"service_role"`, so `echo <token> | cut -d. -f2 | base64 -d` identifies one even when the variable is misleadingly named.

Supabase has been migrating from the legacy JWT-shaped `anon` / `service_role` keys to prefixed API keys — publishable keys starting `sb_publishable_` and secret keys starting `sb_secret_`. Both schemes may be present during a migration. Record the prefixes you actually see rather than the variable names, and check the current dashboard for which scheme this project is on; the rule is unchanged either way — exactly one of the two is safe on a client.

Local values live in `.env.local` / `.env` and come from `supabase status`. Hosted values come from the dashboard's API settings page. For DAT-017, the value that matters is the project ref inside the URL: the same ref in preview and production means previews are reading and writing live data, and Supabase's own branching (see "known traps") is the sanctioned fix.

## routes and handlers
Supabase serves no application routes; the app's framework owns those. What Supabase exposes, all under the API gateway (`<url>` = `http://localhost:54321` locally or `https://<ref>.supabase.co` hosted):

- `POST|GET|PATCH|DELETE <url>/rest/v1/<table>` — PostgREST. Every table in the exposed schemas is an endpoint. This is why RLS is the authorization layer and not a nicety.
- `POST <url>/rest/v1/rpc/<function>` — every Postgres function in the exposed schema, callable by anyone holding the anon key. These are the `security definer` functions DAT-007 audits.
- `<url>/auth/v1/*` — `signup`, `token?grant_type=password`, `token?grant_type=refresh_token`, `otp`, `verify`, `recover`, `user`, `logout`.
- `<url>/storage/v1/object/{public|sign|authenticated}/<bucket>/<path>` and `<url>/storage/v1/bucket`.
- `<url>/realtime/v1/websocket`.
- `<url>/functions/v1/<name>` — Edge Functions, source at `supabase/functions/<name>/index.ts` (Deno).

Which schemas PostgREST exposes is `[api] schemas` in `config.toml` (`public`, `graphql_public` by default) and the equivalent dashboard setting; anything outside them is not reachable over HTTP, which is a legitimate answer to several DAT-007 findings — confirm it rather than assuming.

Edge Functions have their own auth gate: the gateway verifies the caller's JWT before invoking, unless `verify_jwt` is turned off for that function (`--no-verify-jwt` on `serve`/`deploy`, or a `[functions.<name>] verify_jwt = false` block in `config.toml`). A function with `verify_jwt = false` is a fully public endpoint and needs its own check inside the handler (SEC-010) — which is correct and necessary for webhook receivers, and a hole for anything else. List every function and its `verify_jwt` state.

## auth
Users live in `auth.users`, which the app cannot query directly through PostgREST; the app's own profile data is conventionally a `public.profiles` table keyed on `id references auth.users(id)`, populated by an `on auth.users` insert trigger (grep migrations for `handle_new_user` or `create trigger` on `auth.users`). A `profiles` table needs its own RLS policies — it is a separate table and inherits nothing from `auth.users`.

Inside SQL, the caller's identity is `auth.uid()` (the `sub` claim) and `auth.jwt()` (the whole claim set); `auth.role()` returns `anon`, `authenticated`, or `service_role`. Every policy predicate DAT-002 wants is a comparison of a column on *this row* to `auth.uid()`. `auth.role() = 'authenticated'` or `auth.uid() is not null` alone is not ownership — it grants every logged-in user access to every row, which is exactly the shape DAT-002 fails.

**Server-side, `getUser()` is the auth check and `getSession()` is not** (SEC-010, and DAT-002 restates it). `getSession()` reads the session out of the cookie and returns it without contacting the auth server, and the cookie is client-writable, so a forged one passes. `getUser()` sends the token to `/auth/v1/user` and gets a verdict. Grep for `getSession()` in any server file, middleware, route handler, server action, or Edge Function that makes an authorization decision; on the client, where the session is the client's own, `getSession()` is fine.

Config for the auth behaviour that HYG-001 and REL-020 ask about lives in `config.toml` locally under `[auth]` and in the dashboard for the hosted project — and the two are configured independently, so the local file tells you what the developers intended and proves nothing about production. The settings to record: `site_url` and `additional_redirect_urls` (HYG-001 — the redirect allowlist; a wildcard or a leftover `http://localhost:3000` entry in production is the finding), `enable_signup` (an invite-only product with signup still enabled is open registration), `jwt_expiry`, `[auth.email] enable_confirmations` (whether email verification is enforced at all, which FLOW-001 needs to know before it looks for a message), and the OTP/magic-link expiry. Key names under `[auth]` have moved between CLI versions — read the file rather than grepping for a name from memory, and confirm the production values in the dashboard.

Client construction: `createBrowserClient` / `createServerClient` from `@supabase/ssr`, with the server variant taking cookie get/set callbacks. The session cookie is `sb-<project-ref>-auth-token`, frequently chunked as `.0` / `.1` — see "runtime probe hints".

## webhook handlers
Two directions, and they are different checks.

**Inbound** (Stripe and friends posting to you): normally an Edge Function at `supabase/functions/<name>/index.ts`, or a route in the app's own framework. An Edge Function receiving a provider webhook must have `verify_jwt = false` — the provider sends no Supabase JWT, so with verification on the gateway rejects every delivery with a 401 before your code runs, and the provider retries forever. With it off, the handler is public and the provider's signature is the only authentication, so SEC-051 applies in full. Read the raw body with `await req.text()` before parsing; `await req.json()` first makes verification impossible.

**Outbound** (Supabase telling you something). Two mechanisms, both worth listing:
- *Database webhooks* — a Postgres trigger that calls `net.http_post` from the `pg_net` extension on insert/update/delete. Find them by grepping migrations for `net.http_post`, `supabase_functions.http_request`, or a trigger on a table with an HTTP call in its body. The destination URL and any auth header are stored in the trigger definition or in `supabase_functions.hooks`, which means a URL change is a schema change. These fire outside any transaction guarantee you might assume: `pg_net` queues the request asynchronously, so a failed delivery is silent unless something reads the response table.
- *Auth hooks* — send-email, custom access token, and password-verification hooks, configured under `[auth.hook.*]` and in the dashboard. An HTTP auth hook receives a signed payload; verify it.

## webhook verification snippet
An Edge Function receiving a Stripe webhook. Note `verify_jwt = false` for this function, the raw-body read, and the async constructor — Deno has no synchronous crypto path, so the sync `constructEvent` used on Node throws here:

```ts
// supabase/functions/stripe-webhook/index.ts
import Stripe from 'https://esm.sh/stripe@14?target=deno'

const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY')!, {
  httpClient: Stripe.createFetchHttpClient(),
})

Deno.serve(async (req) => {
  const sig = req.headers.get('stripe-signature')
  if (!sig) return new Response('missing signature', { status: 400 })
  const body = await req.text()
  let event
  try {
    event = await stripe.webhooks.constructEventAsync(
      body, sig, Deno.env.get('STRIPE_WEBHOOK_SECRET')!,
      undefined, Stripe.createSubtleCryptoProvider(),
    )
  } catch (_e) {
    return new Response('bad signature', { status: 400 })
  }
  // handle event.type, dedup on event.id (PAY-003)
  return new Response('ok')
})
```

Secrets for Edge Functions come from `supabase secrets set` (hosted) or `supabase/functions/.env` (local) — check that file is gitignored. Deploy this one with `supabase functions deploy stripe-webhook --no-verify-jwt`. For a handler living in the app's framework instead, use that framework's raw-body form from its own stack file; the rule is the same.

## data access
**Schema and policies both live in `supabase/migrations/*.sql`.** They are ordinary SQL files named `<timestamp>_<name>.sql`, applied in filename order. Everything DAT-001, DAT-002, DAT-005, and DAT-007 need is grep-able there:

```bash
grep -rn 'create table\|enable row level security\|create policy\|create view\|security definer\|security_invoker\|storage.buckets\|grant ' supabase/migrations/
```

Read them in order and take the *last* statement about each object as the truth — a later migration can `alter table ... disable row level security` or `drop policy` what an earlier one created, which is exactly why the live-database queries below beat grepping.

**The authoritative queries** (run against the local stack, never production):

```bash
psql postgresql://postgres:postgres@localhost:54322/postgres
```

```sql
-- DAT-001: which tables actually have RLS on, right now
select relname, relrowsecurity, relforcerowsecurity
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r' order by relname;

-- DAT-002: every policy, the command it covers, and its predicates
select schemaname, tablename, policyname, cmd, roles, qual, with_check
from pg_policies where schemaname in ('public','storage') order by tablename, policyname;

-- DAT-007: views, and whether they run as the invoker
select c.relname, c.relkind, c.reloptions, c.relacl
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind in ('v','m');

-- DAT-007: security definer functions and their search_path
select p.proname, p.prosecdef, p.proconfig
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public';

-- DAT-009: the index list
select tablename, indexname, indexdef from pg_indexes where schemaname = 'public';

-- DAT-005 / DAT-006: buckets and their public flag, then object names
select id, name, public, file_size_limit, allowed_mime_types from storage.buckets;
select bucket_id, name from storage.objects where bucket_id = '<bucket>' limit 500;
```

A view is `security_invoker` when `reloptions` contains `security_invoker=true` (Postgres 15+); a view without it runs as its owner and hands the anon key every row the policies were written to hide. `relkind = 'm'` is a materialized view, which never respects RLS at all. A function with `prosecdef = true` and a null `proconfig` is a `security definer` function with no pinned `search_path` — both halves of the DAT-007 fail in one row.

**Storage policies** are ordinary RLS policies on `storage.objects`, keyed on `bucket_id` and a path prefix. The canonical owner-scoped shape is `bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text`. A bucket with `public = true` needs no policy to be readable by anyone — the flag wins for reads — which is why DAT-005 asks about the flag first and the policies second.

**For DAT-015's from-zero migration run**, do not use `supabase db reset`. Create a separate empty database on the local Postgres and apply the files to it directly:

```bash
psql postgresql://postgres:postgres@localhost:54322/postgres -c 'create database prelaunch_scratch'
for f in supabase/migrations/*.sql; do
  psql -v ON_ERROR_STOP=1 postgresql://postgres:postgres@localhost:54322/prelaunch_scratch -f "$f" || break
done
psql postgresql://postgres:postgres@localhost:54322/postgres -c 'drop database prelaunch_scratch'
```
Run no seed. Note that this applies the migrations without the platform roles and extensions the Supabase image pre-creates, so a migration referencing `auth.uid()`, the `auth` schema, or `supabase_admin` will fail here for a reason that is not a defect — record that as the limitation rather than as a failing migration, and say so in the evidence. `supabase db diff` and `supabase db lint` are the drift and correctness tools; `supabase db lint` reports unindexed foreign keys and missing RLS among other things and is worth running for DAT-001 and DAT-009.

**`supabase/seed.sql` runs on every `supabase db reset` and must never reach production** (DAT-016). Read what it creates: a seeded account with a known password is SEC-060 as well. Check that no deploy command, CI job, or `package.json` script pipes it at a hosted connection string, and that no *migration* contains an `insert into` for demo data — a migration runs everywhere `db push` runs, production included.

**pgvector / AI retrieval** (AI-001): the extension is `create extension vector`, the embeddings table usually `documents` or `embeddings` with a `vector(1536)` column, and the retrieval entry point a `match_documents(query_embedding, match_threshold, match_count)` function called through `supabase.rpc('match_documents', ...)`. Two things decide AI-001 on this stack: the embeddings table needs RLS with an owner predicate like any other table (DAT-001, DAT-002), **and** `match_documents` must not be `security definer` — the reference implementation people copy frequently is, and a definer function ignores the caller's policies and returns the whole corpus regardless of how good the RLS is. If it must be definer, it has to filter on `auth.uid()` in its own body. Cite DAT-007 for the function and DAT-002 for the table.

**No ORM here.** If the project also uses Prisma or Drizzle against the same database, read that stack file too: those tools do not know about RLS, they connect as a privileged role, and their queries need explicit ownership filters (SEC-011).

## file uploads
Client-side: `supabase.storage.from('<bucket>').upload(path, file)`, `.createSignedUrl(path, expiresIn)` for private reads (SEC-050), `.getPublicUrl(path)` for public buckets. Server-side signed upload URLs come from `.createSignedUploadUrl(path)`, which is the shape that keeps large files off the app server.

Buckets are created either in a migration (`insert into storage.buckets (id, name, public) values ('avatars','avatars', false)`) or in the dashboard or, in newer CLI versions, declared in `config.toml` under `[storage.buckets.<name>]`. Enumerate them from the live database with the `storage.buckets` query above rather than from any one of those sources — a bucket created in the dashboard exists in none of them. `supabase storage ls` lists objects in newer CLI versions; run `supabase storage ls --help` for this version's path syntax before relying on it, and fall back to the `storage.objects` query, which always works.

Per-bucket limits worth recording: `file_size_limit` and `allowed_mime_types` on the bucket row, and the global `[storage] file_size_limit` in `config.toml`. Absent limits mean the upload endpoint accepts whatever a client sends up to the platform ceiling. The `owner` column on `storage.objects` is set to the uploading user's id and is what an ownership policy can key on, though the path prefix convention above is the more common and more readable form.

## background jobs
Supabase has no general job queue in the way a framework does. What exists, in rough order of how often you will find it:
- **Edge Functions invoked on a schedule** by `pg_cron` (`select cron.schedule('name', '*/5 * * * *', $$ select net.http_post(...) $$)`) — grep migrations for `cron.schedule`, and read `select * from cron.job` on the live database, since a job scheduled from the SQL editor exists in no file.
- **Database webhooks / `pg_net`**, as described under "webhook handlers" — asynchronous, fire-and-forget, and silent on failure.
- **Queues** (`pgmq`-backed) in newer versions, if enabled.
- Anything else is the app's own platform: a framework cron route, Inngest, Trigger.dev. Read that stack file.

Long work inside an Edge Function is bounded by the platform's per-invocation wall-clock and CPU limits, which differ by plan — check the current docs for this project's plan rather than quoting a number (REL-020, PERF-020).

Email sending in the sign-up and reset paths is done by Auth, not by the app, and the built-in SMTP service is explicitly development-grade with a low hourly cap — a launch on it means verification emails stop arriving partway through the first day (REL-020, FLOW-001). Check whether custom SMTP is configured in the dashboard's auth settings and record the provider; "we are using the built-in sender" is the REL-020 finding, with the current cap read from the dashboard's rate-limit page rather than asserted from here.

## error handling and logging
Every Supabase client call returns `{ data, error }` and **throws nothing** — an unchecked `const { data } = await supabase.from(...)` swallows the failure silently and the caller sees an empty result, which is the most common reliability defect on this stack and looks exactly like "no rows". Grep for destructuring that drops `error`.

RLS denials are not errors on reads: a select the policy forbids returns zero rows with `error: null`. On writes it is a `42501` / "new row violates row-level security policy". Do not read a zero-row select as proof that a table is protected without checking that a permitted query returns rows in the same probe.

Logs: local Edge Function output goes to the `supabase functions serve` terminal; hosted logs (API, Postgres, Auth, Storage, Functions, plus the pg_net response table) are in the dashboard's logs explorer and via `supabase functions logs <name>` in newer CLI versions. Postgres errors are in the database logs. There is no error tracker here — the app's own Sentry or equivalent is in the framework's stack file (REL-001).

## security headers
Not applicable for this stack. Responses from `<ref>.supabase.co` are the platform's; the app's framework or CDN owns its own headers. Two adjacent things do belong here: CORS on Edge Functions is set by your handler (the usual copied `corsHeaders` object with `Access-Control-Allow-Origin: '*'` is fine for a public function and wrong for one carrying a session — HYG-001 owns the production origin allowlist), and Storage responses for public buckets are served with permissive caching, so a file made public is public in every CDN between you and the user even after the bucket is flipped back (DAT-006).

## known traps
- `service_role` in any client-reachable variable, or in a mobile app's config: DAT-004. Rotate after, because the old bundle is already out.
- RLS enabled with no policy at all: blocks everyone rather than leaking, but it is still a DAT-001/DAT-002 fail and it usually means the developer disabled RLS somewhere else to make the app work.
- A policy of `using (true)`, or one satisfied by `auth.role() = 'authenticated'`: DAT-002. Also `for select` only, leaving insert/update/delete uncovered, and an insert/update policy with no `with check`, which lets a user write rows they cannot read.
- `getSession()` used server-side for an authorization decision: SEC-010, DAT-002.
- A view over an RLS table without `security_invoker = true`, or a materialized view over user data, granted to `anon`/`authenticated`: DAT-007. Same for any `security definer` function without `set search_path` and an internal `auth.uid()` filter — and every such function is an HTTP endpoint at `/rest/v1/rpc/<name>`.
- A copied `match_documents` RPC left `security definer`: DAT-007 plus AI-001, since it returns the whole corpus to every user.
- `insert into storage.buckets (..., public) values (..., true)` for a bucket holding user files: DAT-005, and DAT-006 for what is already in it.
- Realtime enabled on a table whose RLS does not restrict select: SEC-055. Broadcast and presence channels are authorized by RLS policies on `realtime.messages` in the versions that support Realtime Authorization — check which version this project is on; where that mechanism is not in use, channel names are the only thing standing between one tenant and another, and guessable names are the finding.
- `pg_net`'s `net.http_post` called with a URL from a table row or from user input: SEC-045, and it runs from inside the database with whatever network reach the platform has.
- `supabase/seed.sql`, or an `insert into` inside a migration, reaching production: DAT-016 (and SEC-060 if it creates an account with a known password).
- Preview deployments pointed at the production project ref: DAT-017. Supabase branching gives each branch its own project ref and its own keys — confirm branching is actually on and the preview env is scoped to the branch ref, rather than assuming it from the presence of the feature.
- The built-in Auth email sender in production, with its development-grade hourly cap: REL-020, and FLOW-001 fails downstream when the cap is hit.
- `Site URL` and the redirect allowlist still pointing at localhost, or containing a wildcard: HYG-001. This is dashboard state, so `config.toml` cannot answer it.
- An Edge Function deployed with `verify_jwt = false` that is not a webhook receiver: SEC-010, it is an open endpoint.
- `supabase db reset` run to "get a clean state" during the audit: it destroys the local database and the shared test account with it, which DAT-015 forbids outright.
- Auth rate limits are configurable in the dashboard and their defaults are low enough to look like a bug during testing — a 429 from `/auth/v1/token` during a SEC-015 probe may be Supabase's own limiter rather than the app's. Say which one answered.

## runtime probe hints
**Ports and keys.** Run `supabase status` first and use its output for everything below; do not assume the defaults hold. `<url>` below is the API URL (`http://localhost:54321` locally), `<anon>` the anon/publishable key.

**A JWT for the test account.** Sign in against the Auth API and read the token straight out of the response — this is the reliable path, and the one DAT-002, SEC-011, and AI-001 need:

```bash
curl -s -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" -H 'content-type: application/json' \
  -d '{"email":"<test account>","password":"<from credentials_env>"}' | jq -r .access_token
```
A 400 with `email_not_confirmed` means confirmations are on and the account has not verified — confirm it through the mail catcher first (below). To create a second identity for the "another user" half of DAT-002 and SEC-011, `POST $SUPABASE_URL/auth/v1/signup` with the same `apikey` header and a `qa+<unix-ts>@example.com` address, then read its `sub` from the returned token. Decode any token's claims with `cut -d. -f2 | base64 -d` to get the `sub` (the user id) and the `role`.

Lifting the token from the app's cookie also works but is fiddlier: `sb-<project-ref>-auth-token` holds a base64-encoded JSON session object, chunked across `.0` / `.1` when large, with the JWT in its `access_token` field. Check the cookie's shape in this version before relying on it — the `base64-` prefix and the chunking were not always there.

**The PostgREST bearer probe** (DAT-002's local entry). Both headers are required; the `apikey` is not optional even when a bearer is present:

```bash
# as anon, no session — expect an empty array for any protected table
curl -s "$SUPABASE_URL/rest/v1/<table>?select=*" -H "apikey: $SUPABASE_ANON_KEY"
# as the test account
curl -s "$SUPABASE_URL/rest/v1/<table>?select=*" \
  -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $JWT"
# WITH CHECK: as user B, try to insert a row owned by user A — expect 401/403, not 201
curl -s -X POST "$SUPABASE_URL/rest/v1/<table>" \
  -H "apikey: $SUPABASE_ANON_KEY" -H "Authorization: Bearer $JWT_B" \
  -H 'content-type: application/json' -H 'Prefer: return=representation' \
  -d '{"user_id":"<user A uuid>","title":"probe"}'
```
`[]` with a 200 is the pass for the anon read; a populated array is the finding. Add `-i` and read the status when a write is expected to fail — an RLS refusal on a write is a `401`/`403` with a `42501` in the body.

**Policy probes in `psql`**, which test the policy directly without needing the app at all. Wrap each in a transaction so the role and claims do not leak into the next probe:

```sql
-- as anon
begin;
set local role anon;
select count(*) from public.<table>;   -- expect 0
rollback;

-- as a specific authenticated user
begin;
set local role authenticated;
set local request.jwt.claims = '{"sub":"<user uuid>","role":"authenticated"}';
select count(*) from public.<table>;   -- expect only that user's rows
rollback;
```
`set local request.jwt.claims = '...'` and `select set_config('request.jwt.claims', '<json>', true)` are equivalent — the `true` means transaction-local, and the `set_config` form is the one to use when the JSON needs building from a variable. `auth.uid()` reads the `sub` out of those claims, so a policy comparing a column to `auth.uid()` will now behave exactly as it does for a real request. Two things that make this probe lie: connecting as `postgres` and forgetting `set role` (the superuser bypasses RLS and every table looks readable), and a table with `relforcerowsecurity` off where the *owner* is also exempt. Check the role you are actually running as with `select current_user, current_setting('request.jwt.claims', true);` inside the same transaction.

**Mail catcher** (FLOW-001, FLOW-003). The local stack runs one on port 54324 — Inbucket in older CLI versions, Mailpit in newer ones, and the two have different APIs. Take the URL from `supabase status`, open it in a browser to confirm which, then:
```bash
# Inbucket
curl -s http://localhost:54324/api/v1/mailbox/<mailbox>            # list, newest last
curl -s http://localhost:54324/api/v1/mailbox/<mailbox>/<id>       # one message with body
# Mailpit
curl -s http://localhost:54324/api/v1/messages
```
The mailbox for Inbucket is the local part of the address (`qa+1234@example.com` → the API accepts the full address or the local part depending on version; try both). Pull the confirmation link out of the body with a regex on `href="([^"]*verify[^"]*)"` and follow it. No reachable catcher is `error: no mail capture`, never a pass.

**Health path.** `$SUPABASE_URL/rest/v1/` returns the PostgREST root and `$SUPABASE_URL/auth/v1/health` reports the Auth service. Neither says anything about the app's own health — use the framework's health route for that.

**Test-mode detection.** A local stack is unambiguous (localhost URLs, keys from `supabase status`). For a hosted one, the only tell is the project ref, so compare it against the ref the production deployment uses; there is no `test`/`live` prefix on Supabase keys the way there is on Stripe. If the ref matches production, every probe below is running against live data — stop and record `error: production project ref detected`.

**Never** run `supabase db reset`, `drop`, `truncate`, or `delete` without a `where` during any probe, and delete the rows the audit created afterwards using the same JWT that created them.
