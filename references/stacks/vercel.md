# Vercel

## detection signals
`vercel.json` at the repo root, a `.vercel/` directory with `project.json` (holding `projectId` and `orgId` — it is gitignored on a well-configured project and harmless if not), `vercel` in devDependencies, or a `.vercelignore`. A `@vercel/*` package (`@vercel/blob`, `@vercel/postgres`, `@vercel/kv`, `@vercel/edge-config`, `@vercel/analytics`, `@vercel/speed-insights`) is a strong signal even with no config file. `.github/workflows/*` calling `vercel deploy` or `amondnet/vercel-action`.

`vercel.json` is optional — a Next.js project with zero configuration deploys fine — so **absence of the file is not absence of Vercel**, and most of what this file describes (env scoping, deployment protection, cron secrets, log retention) is dashboard state that no repo file records. Say so in evidence when a check's answer is dashboard-only: `not determinable from the repo; confirm in the Vercel dashboard` is a legitimate finding, and it is the honest one for a large slice of the platform's configuration.

Runtime environment variables Vercel injects, and which are the fastest way to detect the platform from inside a running process:

| variable | value |
|---|---|
| `VERCEL` | `1` |
| `VERCEL_ENV` | `production`, `preview`, or `development` |
| `VERCEL_URL` | the deployment's own host, without a scheme, unique per deployment |
| `VERCEL_BRANCH_URL` | the branch-stable alias for a preview |
| `VERCEL_PROJECT_PRODUCTION_URL` | the production domain, available in every environment |
| `VERCEL_GIT_COMMIT_REF` / `_SHA` / `VERCEL_GIT_REPO_SLUG` | git provenance |
| `VERCEL_REGION` | the region a function is executing in |

`VERCEL_ENV` is the correct branch for "am I in production", and `NODE_ENV` is not — `NODE_ENV` is `production` on preview deployments too, which is the reason preview builds so often behave as if they were live. Framework-prefixed copies (`NEXT_PUBLIC_VERCEL_ENV`, `VITE_VERCEL_ENV`) have to be created by hand; the unprefixed ones are server-side only.

## dev server
`vercel dev` runs the framework's dev server with Vercel's routing layer, function runtimes, and `vercel.json` rewrites/headers in front of it. It is the only local way to exercise `vercel.json` behaviour, and it is noticeably slower than the framework's own `next dev` / `vite`.

```bash
vercel link                       # associates the directory with a project (writes .vercel/ — do not run during an audit)
vercel env pull .env.local        # pulls the DEVELOPMENT-scoped env by default
vercel env pull .env.production.local --environment=production
vercel env ls                     # names, scopes, and last-updated — values are not printed
vercel dev --listen 3000
```

`vercel env pull` writes a file into the project; during an audit prefer `vercel env ls`, which lists variable names and their environment scopes without values and is enough to answer DAT-017 and HYG-001's scoping half. Both need an authenticated CLI (`vercel whoami`) and a linked project; if neither is available, the scoping question is dashboard-only and should be recorded as such rather than guessed.

**Do not measure headers, caching, function timeouts, or performance against `vercel dev`.** Local functions have no platform timeout, no body ceiling, and no edge cache. Every PERF and SEC-03x measurement belongs against a real preview deployment or the framework's production build — see "build".

## build
Build command and output directory come from the framework preset, from `vercel.json`'s `buildCommand` / `outputDirectory` / `installCommand`, or from the dashboard (which overrides the file). The build runs in a container with the Production or Preview environment variables injected according to which environment is being deployed — **not** with a `.env` from the repo, which is why a value that works locally and is empty in production is the single most common deploy bug here.

```bash
vercel build                      # produces .vercel/output/ locally, the Build Output API format
vercel deploy --prebuilt          # deploys that directory
vercel inspect <deployment url>   # what actually got built, including function config
vercel ls                         # recent deployments
```

`.vercel/output/config.json` is the resolved routing table — headers, redirects, rewrites, and function configuration after the framework adapter has run. When a check asks "is this header actually set", that file is the repo-side answer and `curl -I` against a deployment is the real one.

**Build-time versus runtime env.** Anything inlined into a client bundle (`NEXT_PUBLIC_*`, `VITE_*`, `PUBLIC_*`) is fixed at build time, so changing it in the dashboard does nothing until a redeploy. Server-side `process.env` reads in a Node function are resolved at invocation, so those do pick up a change — but only on the *next* deployment for values consumed during the build. Redeploying without rebuilding (the dashboard's "Redeploy" with the existing build cache) does **not** pick up a changed build-time variable, which is the trap behind "we changed the env var and nothing happened".

**The platform's execution limits** — function duration, request body size, response size, and the edge runtime's smaller surface — are all plan-dependent and are collected under "known traps" rather than repeated here; PERF-020 reads them from there, and none of them can be measured against `vercel dev`.

**Skew protection**, when enabled, pins a client's requests to the deployment that served its HTML, which prevents the mid-deploy mismatch where a stale client calls a route that no longer exists. Worth noting for REL-012's deploy-safety story; it is a dashboard/`vercel.json` setting, not a default.

**Certificates and domains (REL-017).** Vercel provisions and auto-renews TLS certificates for every domain attached to a project, including preview subdomains, with no configuration and no cron. That half of REL-017 is a pass by construction — say which platform provisions it rather than leaving it implied. The half that still needs checking is the **canonical host**: apex-to-www or www-to-apex must be configured, and on Vercel that is a dashboard domain setting (one domain marked as the redirect target of the other) rather than something in `vercel.json`, so a `vercel.json` with no redirects is not evidence of absence. Confirm with `curl -sI https://example.com` and `curl -sI https://www.example.com` and read the `Location` headers; both resolving 200 with the same content is the duplicate-content finding.

## env vars
Environment variables are scoped to one or more of three environments: **Production**, **Preview**, and **Development**. A Preview-scoped variable can additionally be pinned to a specific git branch. The dashboard is the source of truth; `vercel.json` has an `env` key only in older/legacy usage and should not be relied on. Secrets are encrypted at rest and injected at build and invocation time, which is a shape ACC-007 passes — the finding there is usually not Vercel but a `.env.production` committed alongside it.

```bash
vercel env ls                     # name, environments, created — the scoping answer without values
vercel env ls preview
```

**DAT-017's whole question lives here.** A variable created with all three environments checked — which is the default when you paste one in quickly — means every preview deployment of every pull request holds the production `DATABASE_URL`. Then a migration on a feature branch runs against production, and a preview app writes live customer rows. What to compare:

- `DATABASE_URL`, `DIRECT_URL`, `POSTGRES_URL` and its `@vercel/postgres` siblings
- `SUPABASE_URL` / the project ref, `NEXT_PUBLIC_SUPABASE_URL`
- `MONGODB_URI`, `REDIS_URL`, `KV_URL`
- storage bucket names, `BLOB_READ_WRITE_TOKEN`
- `STRIPE_SECRET_KEY` and every other payment key — a preview pointed at live Stripe sends real charges and real email from a branch
- `RESEND_API_KEY` / `SENDGRID_*` / `POSTMARK_*` — same reasoning, real mail to real addresses

Identical Production and Preview values for any of those is the fail. What passes: a branch-database mechanism (Supabase branching, Neon or PlanetScale branches, a per-preview database provisioned by an integration), a dedicated staging database, or previews disabled entirely. Confirm which; do not assume. If preview deployments do not exist at all, that is a pass by absence and should be recorded as such.

**HYG-001's scoping half** is the same table read the other way: for each externally configured URL — OAuth redirect URIs, the auth provider's site URL and redirect allowlist, webhook endpoints — check that the value in the Production environment is the production domain and not a `*.vercel.app` deployment URL. `VERCEL_URL` changes on every deployment, so anything derived from it (a `NEXTAUTH_URL` computed as `https://${process.env.VERCEL_URL}`) is stable on preview and wrong in production, where it should be the custom domain. `VERCEL_PROJECT_PRODUCTION_URL` exists precisely to fix that.

**System variables** are injected automatically and cannot be overridden; the "Automatically expose System Environment Variables" toggle controls whether they reach the build. Sensitive variables (a dashboard flag) are write-only — they can be set and used but not read back in the UI or by `vercel env pull`, which is the right setting for anything genuinely secret and is worth recommending where a project has none.

## routes and handlers
Vercel serves three things and the distinction decides most of the platform's limits:

- **Static assets** — files from the output directory, served from the edge cache. No function invocation, no timeout, no cost per request.
- **Functions** (formerly "Serverless Functions", now also "Fluid compute" on plans that have it) — Node.js, Python, Go, or Ruby handlers. In a framework project these are generated by the adapter (`app/api/**/route.ts` in Next.js, `+server.ts` in SvelteKit); in a bare project they are files under `api/` at the repo root, one file per route, default-exporting a handler.
- **Edge Functions and Middleware** — the lighter runtime, no Node built-ins, no filesystem, a much smaller CPU budget, executed close to the user. Next.js `middleware.ts` runs here, as does any route with `export const runtime = 'edge'`.

```bash
ls api/ 2>/dev/null                             # bare-project functions
cat .vercel/output/config.json 2>/dev/null | python3 -m json.tool | head -60
grep -n 'functions\|rewrites\|redirects\|headers\|crons\|regions\|cleanUrls\|trailingSlash' vercel.json
```

`vercel.json`'s `functions` block sets per-path `memory`, `maxDuration`, and `runtime`:
```json
{ "functions": { "app/api/report/route.ts": { "maxDuration": 60, "memory": 1024 } } }
```
Next.js's `export const maxDuration = 60` in a route file does the same thing. Record whichever is present and check it against the plan's ceiling ("known traps").

`rewrites` are internal and invisible to the client; `redirects` emit a real 3xx and are what SEO checks care about; `headers` is covered under "security headers". A catch-all rewrite to `/index.html` (`{ "source": "/(.*)", "destination": "/index.html" }`) is the SPA pattern, and on Vercel it also means every unmatched path returns **200**, not 404 — a soft 404 that SEO-004's sibling checks care about and that a naive not-found probe will read as "the route exists".

**Deployment protection** is where preview access is decided (DAT-017's exposure half, SEO-004's indexing half, and SEC-010 for anyone who assumed previews were private). The options are Vercel Authentication (SSO — only team members can open a preview), Password Protection, and Trusted IPs, with a Protection Bypass token for automated testing. Availability and defaults differ by plan and have changed, so **check the project's Deployment Protection settings in the dashboard rather than asserting a default**, and verify by fetching a preview URL from a logged-out context:
```bash
curl -sI https://<preview-deployment>.vercel.app/ | head -20
```
A 200 with real content means the preview is public. A preview holding production data *and* publicly reachable is the compound failure worth calling out explicitly.

## auth
Not applicable for this stack in the application sense — Vercel has no notion of your users, and the app's session handling belongs to the framework's stack file.

Three platform-level access surfaces do matter:

- **Deployment Protection** (above) — who can open a preview or a production deployment URL. It is the platform's only request-level authentication, it is coarse (all-or-nothing per deployment), and it is not a substitute for application authorization.
- **Team and project access** — who can change environment variables, promote a deployment, or add a domain. That is ACC-001's territory: check that the team has more than one owner, that access is not a shared login, and that SSO/2FA is enforced where the plan supports it. None of this is in the repo.
- **Protection Bypass for Automation** — a token that lets CI reach a protected preview. It is a bearer secret; if it appears in a committed workflow file rather than in repository secrets, that is SEC-001.

## webhook handlers
Nothing platform-specific about receiving a webhook — it is an ordinary function, and the raw-body rule belongs to the framework's stack file. Three Vercel facts change whether one works:

1. **The body limit applies.** A provider posting more than the request-body ceiling (see "known traps") gets a platform-level rejection your handler never sees, and the provider records a delivery failure while your logs show nothing.
2. **The function timeout applies.** A handler doing slow work before returning 2xx will hit the ceiling and the provider will retry, which turns a non-idempotent handler into duplicated side effects (PAY-003 on the payment path).
3. **Deployment Protection blocks providers.** A protected preview deployment returns Vercel's SSO challenge — an HTML 401 — to Stripe, GitHub, or Twilio. Webhook testing against a preview needs the bypass token or an unprotected path.

Vercel itself sends two kinds of signed request you may need to verify: **cron invocations**, which carry `Authorization: Bearer $CRON_SECRET` when a `CRON_SECRET` environment variable exists, and **integration/webhook events** for teams building Vercel integrations, signed with `x-vercel-signature` as an HMAC-SHA1 over the raw body using the integration's client secret.

## webhook verification snippet
The cron guard, which is what SEC-014 is looking for on this platform:

```ts
// app/api/cron/reconcile/route.ts — the first statements, before any work
export async function GET(req: Request) {
  const expected = `Bearer ${process.env.CRON_SECRET}`
  const got = req.headers.get('authorization') ?? ''
  const a = Buffer.from(got), b = Buffer.from(expected)
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return new Response('unauthorized', { status: 401 })
  }
  // ... the job
}
```

Two things about it. Vercel adds that header automatically when a `CRON_SECRET` environment variable is set on the project — you do not configure it on the cron entry — so the *absence* of a `CRON_SECRET` variable means every cron route is an unauthenticated public URL (SEC-014). And the comparison must be constant-time; `got === expected` on a secret is SEC-052.

For Vercel integration webhooks:
```ts
const sig = req.headers.get('x-vercel-signature')
const body = await req.text()                                  // raw bytes, before any JSON parse
const digest = crypto.createHmac('sha1', process.env.INTEGRATION_SECRET!).update(body).digest('hex')
if (!sig || !crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(digest))) return new Response(null, { status: 401 })
```

For provider webhooks (Stripe, RevenueCat, Lemon Squeezy), see that provider's stack file; the raw-body rule and the framework's way of getting raw bytes come from the framework's file.

## data access
Vercel runs no database of its own; it resells and integrates. What you find, and what it changes:

- **Vercel Postgres / Neon / Supabase / PlanetScale via the Marketplace** — an integration writes `DATABASE_URL`, `POSTGRES_URL`, `POSTGRES_PRISMA_URL`, `POSTGRES_URL_NON_POOLING` and friends into the project's environment automatically, **scoped to all environments by default in some integration flows**. That is DAT-017's most common cause on this platform and is worth checking explicitly rather than assuming a human chose the scope.
- **Connection pooling** is the serverless failure mode. Every concurrent invocation is a separate process with its own connection; a Postgres instance with a 100-connection limit is exhausted by a modest traffic spike. The fixes are a pooled connection string (`POSTGRES_URL` pooled versus `POSTGRES_URL_NON_POOLING` direct, PgBouncer, Supabase's pooler on port 6543, Neon's pooled endpoint) or a driver that speaks HTTP instead of TCP (`@neondatabase/serverless`, `@vercel/postgres`). Prisma additionally needs `DIRECT_URL` for migrations while the app uses the pooled URL — a project with only the pooled URL will fail to migrate, and one with only the direct URL will exhaust connections. Check both are present and pointed correctly (DAT-008, PERF-018).
- **Vercel KV / Upstash Redis, Vercel Edge Config, Vercel Blob** — each injects its own token. `BLOB_READ_WRITE_TOKEN` is a write credential and must be server-side only; an `EDGE_CONFIG` connection string is a read URL and is still not something to put in a client bundle.
- The **Edge runtime cannot open TCP connections**, so a middleware or edge route cannot talk to Postgres over the normal driver at all. If one appears to, it is going through an HTTP data proxy (Prisma Accelerate, Neon serverless, Supabase PostgREST) — identify which, because the authorization model differs.

Caching is a data-access concern here more than on most platforms: Vercel's CDN caches on `Cache-Control` / `CDN-Cache-Control` / `Vercel-CDN-Cache-Control` and on the framework's ISR configuration. A `Cache-Control: public` on an authenticated response, or a page rendered statically that reads a session, serves one user's data to another from the edge (SEC-036, SEC-011). This is the platform's sharpest data-leak shape and it produces no error anywhere.

## file uploads
An upload proxied through a function is bounded by the request-body ceiling ("known traps"), and the rejection happens at the platform edge before your handler runs — so a client uploading a 20 MB file gets an opaque 413 with no application error and nothing in your logs.

**Vercel Blob** (`@vercel/blob`) is the first-party store. Two modes: server upload (`put()` inside a function, which is subject to the body limit because the bytes pass through the function) and **client upload** (`upload()` from the browser against a token minted by your own `handleUpload` route), which streams directly to Blob storage and bypasses the function ceiling entirely. Only the second scales; a project doing server uploads of user media has a size cliff it has not met yet.

For DAT-005, note that Vercel Blob objects have historically been publicly readable by URL — the URL is unguessable, which is obscurity rather than access control. Check the current access options rather than asserting, and treat "the URL is long" as a fail when the object is genuinely sensitive (a passport scan, an invoice). S3 with presigned GETs, or Supabase Storage with RLS policies, are the shapes that pass.

Presigned direct-to-storage against S3/R2/Supabase works identically here and is the recommendation whenever the body ceiling is in play (PERF-020's fix path).

## background jobs
**Vercel Cron.** Defined in `vercel.json`:
```json
{ "crons": [{ "path": "/api/cron/reconcile", "schedule": "0 3 * * *" }] }
```
Facts that decide the checks:

- Crons are **HTTP GET requests to a public URL** on your production deployment. They are not privileged, they are not internal, and anyone who knows the path can call them. `CRON_SECRET` is the only thing between the path and the internet (SEC-014, and see "webhook verification snippet").
- They run against the **production** deployment only. A cron defined on a branch does not fire from a preview.
- The number of cron jobs and the finest schedule granularity are **plan-limited** — the Hobby plan is restricted to a small number of jobs at daily granularity, paid plans allow many more and per-minute schedules. These numbers have changed; check the current plan limits rather than quoting one.
- A cron invocation is a function invocation and is bound by the same duration ceiling. Anything longer belongs in a queue (PERF-013).
- Vercel does **not** retry a failed cron, and does not alert on one. REL-019's "does anything know the job ran" question therefore almost always answers "no" on this platform unless the handler pings a dead-man's-switch (Cronitor, Healthchecks.io, Sentry Cron Monitors) itself. Look for that ping; its absence is the finding.
- Overlap: a long-running job whose next invocation starts before the previous finished will simply run twice concurrently. There is no platform lock (REL-019).

**Queues and durable work.** Vercel runs no queue of its own that you should assume. What you will find: Inngest, Trigger.dev, QStash (Upstash), Defer, or a database-backed job table polled by a cron. `waitUntil()` from `@vercel/functions` (and `event.waitUntil` in edge/middleware) extends a function's life past the response for fire-and-forget work — it is bounded by the same duration ceiling and gives no retry, no visibility, and no durability, so anything that must not be lost does not belong there.

**Kill switch (REL-010).** Vercel's first-party mechanism is **Edge Config** — a globally replicated read-optimized store, read with `get()` from `@vercel/edge-config` at the top of middleware or a route, with reads designed to be fast enough to sit in the request path. Changing a value takes effect without a redeploy, in the low seconds, which makes it the only shape on this platform with genuinely incident-grade latency. The alternatives and their real costs: an environment variable read in middleware, which needs a **redeploy** to change and therefore takes minutes; a feature-flag provider (LaunchDarkly, PostHog, Statsig), which is fine and has its own latency; or a `settings` row in the database read per request, which works and adds a query to every request.

Whichever exists, REL-010 wants the flag checked **before the expensive or risky paths** — the payment route, the AI endpoint, the sign-up handler — and not only on the marketing page; "routes and handlers" is where to trace that. Say which shape the project has and what its actual latency is: "we can turn it off" meaning "after a four-minute rebuild" is a materially different answer during an incident, and a project with an env-var switch and Edge Config already on the account has a cheap fix.

**Email** is usually sent inline from a route (Resend, Postmark, SendGrid). Inline sending makes the request as slow and as failure-prone as the provider, and inside a 10-second ceiling with a slow provider that is a real failure mode (PERF-014's timeout budget against PERF-020's ceiling).

## error handling and logging
**Runtime logs.** Everything written to stdout/stderr from a function goes to Vercel's log stream.
```bash
vercel logs <deployment-url>          # runtime logs for a deployment
vercel inspect --logs <deployment-url>
```
**Retention is short and plan-dependent** — on the order of an hour on the free plan and a day or so on paid, with Log Drains (Datadog, Axiom, Better Stack, an HTTP endpoint) as the way to keep anything longer. Check the current plan limits. For REL-015 the consequence is concrete: if the only logging is `console.log` and there is no drain, then the day after an incident there is nothing left to read, and that is the finding regardless of how good the log lines are.

Log lines are attributed to a request id; there is no automatic trace id across functions. Structured logging (Pino, Winston with a JSON formatter) plus a request id propagated in a header is what makes concurrent invocations readable — bare `console.log` interleaves into nonsense under any concurrency (REL-015).

**Error tracking (REL-001).** Sentry via `@sentry/nextjs` or the platform-agnostic SDK, or the Vercel/Sentry integration. On Next.js the thing most often missed is that the **edge runtime needs its own initialization** — `sentry.edge.config.ts` — and middleware errors otherwise vanish entirely. Vercel's own "Runtime Logs" error view is not error tracking: it has no grouping, no alerting, and the retention above.

**Source maps (SEC-007).** Vercel does not decide this; the framework does. `productionBrowserSourceMaps: true` in `next.config.*` publishes browser source maps to `/_next/static/`, where anyone can fetch them and read your original source. Vite's `build.sourcemap` and Nuxt's `sourcemap.client` are the equivalents. The correct shape is `hidden` source maps uploaded to Sentry during the build and then removed from the deploy artifact — check that a `.map` is not fetchable:
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/_next/static/chunks/<chunk>.js.map
```

**Errors returned to clients.** Framework territory (SEC-009), except for one platform behaviour: when a function times out or crashes before responding, Vercel returns its own error page with a code such as `FUNCTION_INVOCATION_TIMEOUT` or `FUNCTION_INVOCATION_FAILED` and a request id. That page leaks nothing, but it also means the user sees a Vercel error rather than yours, and your error tracker may never have been reached — a timeout is invisible to a Sentry handler that never got to run. Look for those codes in the logs when diagnosing "the page is just broken sometimes".

## security headers
Headers are set in `vercel.json`, which applies them at the edge to every matching response — including static assets, which framework-level middleware often misses:

```json
{
  "headers": [{
    "source": "/(.*)",
    "headers": [
      { "key": "Strict-Transport-Security", "value": "max-age=63072000; includeSubDomains; preload" },
      { "key": "X-Content-Type-Options", "value": "nosniff" },
      { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" },
      { "key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()" },
      { "key": "Content-Security-Policy", "value": "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'" }
    ]
  }]
}
```

For SEC-031 and SEC-033 the header configuration can live in **three** places and you have to check all of them before reporting one absent: `vercel.json` `headers`, the framework's own mechanism (`next.config.*` `headers()`, `middleware.ts` setting response headers — which is where a nonce-based CSP has to live because a static config cannot generate a nonce), and nothing at all. When both `vercel.json` and the framework set the same header, read the actual response rather than reasoning about precedence:

```bash
curl -sI https://example.com/ | tr -d '\r'
curl -sI https://example.com/_next/static/chunks/main.js | tr -d '\r'   # static assets, the commonly-missed half
```

HTTPS is automatic — Vercel serves only HTTPS and redirects HTTP, so SEC-034's redirect half is a pass by construction; name the platform rather than leaving it implied. HSTS is **not** automatic on custom domains in all configurations, so it is still worth verifying in the response above.

`X-Robots-Tag` for SEO-004: see "known traps" for the preview-indexing question.

## known traps
- **Function duration.** The commonly quoted figures are a 10-second default on the Hobby plan and 60 seconds on Pro, configurable up to 300 seconds on paid plans via `maxDuration`, with higher ceilings on Enterprise and different accounting under Fluid compute. **These numbers have moved more than once — check the current plan limits in the dashboard and treat any figure here as an illustration.** Record the configured `maxDuration` (from `vercel.json` `functions` or the route's export) and whether it is inside the plan's ceiling; a `maxDuration: 300` on a Hobby project is a config that silently does not apply. PERF-020.
- **Request body limit, commonly documented at 4.5 MB** for a function invocation. Check the current limit. The rejection happens at the edge, so the handler never runs and your logs show nothing — the client sees a 413 with no application error. PERF-020, and the fix is a presigned direct-to-storage upload ("file uploads").
- **Response size and streaming.** Non-streamed responses have their own ceiling; a large export generated in memory hits it. Streaming responses are the way past it and are supported on both runtimes. PERF-020.
- **The Edge runtime is a different machine.** No Node built-ins (`fs`, `net`, `crypto`'s Node API), no TCP, a much smaller CPU budget, and a smaller code-size limit. A dependency that works in a Node function will fail at build or at runtime in middleware. PERF-020's "other ceilings" clause.
- **Environment variables scoped to all three environments**, so preview holds the production `DATABASE_URL` and every pull request writes live rows: DAT-017. This is the default shape when a variable is pasted in quickly and when a marketplace integration provisions one.
- **`NODE_ENV` is `production` on preview deployments.** Branch on `VERCEL_ENV` instead. Code that gates seeding, test-mode payment keys, or debug endpoints on `NODE_ENV !== 'production'` is disabled on previews and enabled nowhere — or, worse, code gating a destructive operation on `NODE_ENV === 'development'` runs its production branch against a preview database. DAT-017, HYG-001.
- **No `CRON_SECRET` variable set**, which means Vercel sends no `Authorization` header and every path in `vercel.json` `crons` is an unauthenticated public GET: SEC-014. A `===` comparison of the secret is SEC-052.
- **Nothing monitors a cron.** Vercel does not retry a failed cron and does not alert on one; unless the handler pings a dead-man's-switch, a job that stopped running two weeks ago looks identical to one that runs fine: REL-019.
- **Preview deployments are publicly reachable unless Deployment Protection is enabled.** Availability and defaults vary by plan and have changed — check the project's settings and verify with a logged-out `curl -I` rather than asserting. A public preview holding production data is DAT-017 and SEC-010 together.
- **Preview indexing.** Vercel has for some time added `X-Robots-Tag: noindex` to preview deployment URLs automatically, but this is exactly the kind of platform default worth verifying rather than trusting: `curl -sI https://<preview>.vercel.app/ | grep -i x-robots-tag`. A preview that is indexable duplicates the whole site under a `*.vercel.app` host and can outrank it. SEO-004. The same check belongs on any custom staging domain attached to the project, which gets no such default.
- **Log retention is short and plan-dependent**, with no drain by default: REL-015. The day after an incident there may be nothing to read.
- **`productionBrowserSourceMaps: true`** (or the Vite/Nuxt equivalent) publishes readable source to `/_next/static/`: SEC-007. Verify by fetching a `.map` rather than by reading the config alone.
- **Redeploying from cache does not pick up a changed build-time variable.** `NEXT_PUBLIC_*` and every other inlined value needs a rebuild. This is the mechanism behind "we rotated the key and it is still using the old one" (REL-007).
- **A SPA catch-all rewrite makes every unmatched path return 200**, not 404: a soft 404 for SEO and a misleading result for any probe that infers route existence from a status code.
- **`Cache-Control: public` (or a statically rendered page) on an authenticated response** is served from the edge cache to the next visitor: SEC-036, SEC-011. Vercel's CDN is aggressive and this failure produces no error anywhere.
- **Connection exhaustion.** Every concurrent invocation opens its own database connection; without a pooler or an HTTP driver a traffic spike exhausts the instance: DAT-008, PERF-018. Prisma additionally needs `DIRECT_URL` for migrations alongside the pooled `DATABASE_URL`.
- **Kill switch latency.** An environment-variable kill switch needs a full redeploy to take effect — minutes, during an incident — while an Edge Config read takes effect in seconds without one: REL-010. State which the project has and what the latency actually is, and check the flag gates the payment, AI, and sign-up paths rather than only the marketing page.
- **`waitUntil()` treated as a queue.** It extends the invocation past the response but is still bounded by the duration ceiling, with no retry and no durability. Anything that must not be lost belongs in a real queue: PERF-013.
- **Deployment Protection blocks webhook providers.** A protected preview returns an HTML 401 to Stripe and friends; the provider records a delivery failure and your logs show nothing.
- **`VERCEL_URL` used as the canonical URL.** It is per-deployment and changes every time; anything registered with a third party (an OAuth redirect, a webhook endpoint, `NEXTAUTH_URL`) built from it is wrong in production. Use `VERCEL_PROJECT_PRODUCTION_URL` or a hardcoded domain: HYG-001.
- **`.vercel/project.json` committed** is not a secret leak (`projectId`/`orgId` are identifiers, not credentials) but it should be gitignored; a **Protection Bypass token** or a `VERCEL_TOKEN` in a committed workflow file is SEC-001 and grants deploy access to the project.
- **Much of this platform is dashboard state.** Deployment Protection, env scoping, log drains, cron plan limits, domain redirects, and team access have no repo representation. `not determinable from the repo; confirm in the dashboard` is a legitimate and honest finding — an invented default is not.

## runtime probe hints
**Establish which deployment you are probing.** A `*.vercel.app` deployment URL is a specific immutable build; the production domain is whatever is currently promoted. They can differ. `vercel ls` and `vercel inspect <url>` tell you which is which, and `curl -sI` for the `x-vercel-id` header identifies the region and deployment that served a response.

```bash
vercel whoami                                    # is the CLI authenticated at all?
vercel ls                                        # deployments, newest first
vercel inspect https://example.com               # what is currently promoted to production
vercel env ls                                    # names and scopes, no values — the DAT-017/HYG-001 answer
curl -sI https://example.com/ | tr -d '\r'
```

Useful response headers: `x-vercel-id` (region plus deployment id), `x-vercel-cache` (`HIT`, `MISS`, `STALE`, `PRERENDER`, `REVALIDATED` — the fastest way to see whether a response is being cached at the edge, which is SEC-036's probe), `age`, and `server: Vercel`.

**Is the preview public and indexable?** From a context with no Vercel session:
```bash
curl -sI https://<branch-preview>.vercel.app/ | tr -d '\r' | grep -iE 'HTTP/|x-robots-tag|set-cookie'
```
A 401 with a Vercel SSO page means Deployment Protection is on. A 200 with your app means it is not. Grep for `x-robots-tag: noindex` for SEO-004.

**Function timeout and body limit, measured rather than assumed** (run against a preview, never production, and only on an endpoint that is safe to call):
```bash
# duration: how long before the platform cuts it off
curl -s -o /dev/null -w 'status=%{http_code} total=%{time_total}\n' https://<preview>/api/<a slow but safe endpoint>
# body ceiling: a body just over the documented limit should be rejected at the edge, before the handler
head -c 5000000 /dev/zero | tr '\0' 'a' > /tmp/big.txt
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<preview>/api/<an upload endpoint> \
  -H 'content-type: text/plain' --data-binary @/tmp/big.txt
```
A 413 with no application error in the logs confirms the edge rejected it. Record the observed numbers alongside the documented ones and say which is which.

**Cron secret (SEC-014).** The negative probe is safe and needs no credentials — call the cron path with no `Authorization` header and expect 401:
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/api/cron/<path from vercel.json>
```
A 200, or any evidence the job ran, is the finding. Do not then call it with the real secret: a cron handler is by definition a job with side effects.

**Headers (SEC-031, SEC-033).** Check a page and a static asset, since `vercel.json` `headers` covers both and framework middleware usually covers only the first:
```bash
curl -sI https://example.com/ | tr -d '\r'
curl -sI https://example.com/favicon.ico | tr -d '\r'
```

**Domains and certificates (REL-017).**
```bash
curl -sI https://www.example.com | tr -d '\r' | head -5     # is one host redirecting to the other?
curl -sI http://example.com | tr -d '\r' | head -5          # HTTP → HTTPS
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | openssl x509 -noout -dates -issuer
```
Vercel-issued certificates renew automatically; the `notAfter` date is informational, and a short remaining life is normal rather than a finding.

**Logs.** `vercel logs <deployment-url>` is live-tail-shaped and only reaches back as far as retention allows. If the answer to "what happened at 3am yesterday" is "nothing is retained", that is REL-015's finding and should be recorded as one rather than as a failure to investigate.

**Never** deploy, promote, roll back, change an environment variable, or delete a deployment during an audit. Everything above is read-only apart from the deliberate negative probes, and those must run against a preview.
