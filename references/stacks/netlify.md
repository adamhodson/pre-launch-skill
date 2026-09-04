# Netlify

## detection signals
`netlify.toml` at the repo root, a `.netlify/` directory (gitignored, holding local state), `netlify-cli` in devDependencies, a `netlify/functions/` or `netlify/edge-functions/` directory, or `public/_headers` / `public/_redirects` files in the publish directory. `@netlify/functions`, `@netlify/blobs`, or a `@netlify/plugin-*` in `package.json`. A `_redirects` or `_headers` file is a Netlify-specific artifact and is a signal on its own.

`netlify.toml` is optional — a project configured entirely through the dashboard deploys fine — so **absence of the file is not absence of Netlify**, and the dashboard overrides the file for build settings in some cases. A large share of what this file describes (environment-variable scoping, deploy-preview visibility, log retention, team access) is dashboard state that no repo file records. `not determinable from the repo; confirm in the Netlify dashboard` is a legitimate finding and is the honest one where it applies.

Runtime environment variables Netlify injects, and the fastest way to detect the platform and the deploy context from inside a build or a function:

| variable | value |
|---|---|
| `NETLIFY` | `true` |
| `CONTEXT` | `production`, `deploy-preview`, `branch-deploy`, or `dev` |
| `BRANCH` | the git branch being built |
| `HEAD` / `COMMIT_REF` | git provenance |
| `URL` | the site's primary production URL |
| `DEPLOY_URL` | this deploy's unique URL |
| `DEPLOY_PRIME_URL` | the branch-stable URL for this deploy (`deploy-preview-42--site.netlify.app`) |
| `REVIEW_ID` | the pull-request number, on deploy previews only |
| `SITE_NAME` / `SITE_ID` | the site's identity |

`CONTEXT` is the correct branch for "am I in production" — `NODE_ENV` is not, because Netlify sets `NODE_ENV=production` for the build in every context, so a deploy preview looks like production to any code that checks it. That single fact is behind a large share of the DAT-017 and HYG-001 findings on this platform.

## dev server
`netlify dev` runs the framework's dev server behind Netlify's routing layer, serving redirects, headers, functions, and edge functions locally, and injecting the site's environment variables when the CLI is linked.

```bash
netlify status                        # linked site, account, and whether the CLI is authenticated
netlify link                          # associates the directory with a site (writes .netlify/ — avoid during an audit)
netlify dev --port 8888
netlify env:list                      # variable names and their contexts
netlify env:list --context deploy-preview
netlify functions:list
```

`netlify env:list` prints names and, depending on flags and permissions, values — prefer the plain listing during an audit and do not dump values into evidence. It needs an authenticated CLI and a linked site; without those, the scoping question is dashboard-only and should be recorded as such rather than guessed. `netlify env:import`/`netlify env:set` write; never run them during an audit.

**Do not measure headers, caching, function timeouts, or performance against `netlify dev`.** Local functions run without the platform's execution ceiling and without the CDN in front of them. Every PERF and SEC-03x measurement belongs against a real deploy preview or the framework's production build.

## build
Build command, publish directory, and functions directory come from `netlify.toml`'s `[build]` block or from the dashboard (the dashboard wins for build settings on some fields, so read both and say which you used):

```toml
[build]
  command = "npm run build"
  publish = "dist"
  functions = "netlify/functions"

[build.environment]
  NODE_VERSION = "20"
```

`[build.environment]` values are **committed in the repo** and visible to anyone who can read it. That makes it fine for `NODE_VERSION` and a public API base URL, and a SEC-001 finding for anything else — grep it before anything else, because it is one of the easier places for a secret to end up on this platform.

Context-specific build configuration is the mechanism that answers DAT-017 and SEO-004 on Netlify:

```toml
[context.production]
  command = "npm run build"
[context.production.environment]
  DATABASE_URL = "..."          # do not do this — see "env vars"; contexts are for non-secret overrides

[context.deploy-preview.environment]
  NEXT_PUBLIC_API_URL = "https://staging.example.com"

[context.branch-deploy.environment]
  NEXT_PUBLIC_API_URL = "https://staging.example.com"

[context.staging]               # a named branch gets its own context
  command = "npm run build:staging"
```

Build plugins (`[[plugins]]` in `netlify.toml`, or installed from the UI) run inside the build and can read every environment variable in it — `@netlify/plugin-lighthouse`, `netlify-plugin-submit-sitemap`, framework adapters like `@netlify/plugin-nextjs`. A third-party plugin is code you did not write executing with your build secrets; note any that are not first-party (SEC-005's dependency question, applied to the build).

**Certificates and domains (REL-017).** Netlify provisions and auto-renews TLS certificates through Let's Encrypt for every domain attached to a site, including deploy-preview subdomains, with no configuration and no cron. That half of REL-017 is a pass by construction — name the platform rather than leaving it implied. What still needs checking is the **canonical host**: Netlify sets one domain as primary and 301s the others to it, which is a dashboard domain setting rather than a `netlify.toml` entry, so an absence of redirects in the file is not evidence. Confirm with `curl -sI` on both apex and www and read the `Location`. Netlify also supports a `force = true` redirect in `netlify.toml` for the same purpose, and a project may do it either way.

## env vars
Netlify environment variables have **two independent axes**, and both matter:

1. **Scopes** — which part of the platform can read the variable: Builds, Functions, Runtime (edge functions and framework server runtimes), and Post-processing. A variable scoped only to Builds is invisible to a function at request time, which is the cause of "it works in the build and is undefined in the handler".
2. **Contexts** — which deploy context the value applies to: `production`, `deploy-preview`, `branch-deploy`, `dev`, plus a per-branch value for a named branch. A variable can hold a different value per context, or one value for all of them.

```bash
netlify env:list                                  # all contexts
netlify env:list --context production
netlify env:list --context deploy-preview
# compare the two listings by NAME and scope only — never print a value into evidence.
# Where a name exists in both, establish that the values differ by some other means
# (the database the site is attached to, the project ref, a host in a config file).
```

**DAT-017's whole question lives here.** The default when a variable is created without specifying a context is a single value used everywhere — so every deploy preview of every pull request holds the production `DATABASE_URL`, a migration on a feature branch runs against production, and the preview app writes live customer rows. What to compare between the production and deploy-preview contexts:

- `DATABASE_URL`, `DIRECT_URL`, `MONGODB_URI`, `REDIS_URL`
- `SUPABASE_URL` / the project ref, and the service-role key if one exists
- storage bucket names, `NETLIFY_BLOBS_*` if scoped manually
- `STRIPE_SECRET_KEY` and every other payment key — a preview pointed at live Stripe sends real charges from a branch
- `RESEND_API_KEY` / `SENDGRID_*` / `POSTMARK_*` — real mail to real addresses from a pull request

Identical production and deploy-preview values for any of those is the fail. What passes: a branch-database mechanism (Supabase branching, Neon or PlanetScale branches), a dedicated staging database, or deploy previews disabled entirely. Confirm which; do not assume. If deploy previews do not exist at all, that is a pass by absence and should be recorded as such.

**Secrets do not belong in `netlify.toml`.** Anything under `[build.environment]` or `[context.*.environment]` is committed. Netlify has a secrets-scanning step in the build that fails the deploy when it finds a known environment variable's value in the build output — useful, and worth noting whether `SECRETS_SCAN_ENABLED` has been set to `false` or `SECRETS_SCAN_OMIT_KEYS` used to silence it, because disabling a guard is itself a finding (SEC-001). ACC-007 passes on the platform's encrypted variable store scoped to production; the finding is usually a committed `.env` alongside it, or the `netlify.toml` case above.

**HYG-001's scoping half** is the same table read the other way. For each externally configured URL — OAuth redirect URIs, the auth provider's site URL and redirect allowlist, webhook endpoints — check that the production value is the custom domain and not a `*.netlify.app` URL. `DEPLOY_URL` changes on every deploy, so anything derived from it is wrong the moment it is registered anywhere; `URL` is the stable production one and `DEPLOY_PRIME_URL` the stable per-branch one.

## routes and handlers
Netlify serves four things:

- **Static assets** from the publish directory, served from the CDN. No function, no timeout.
- **Serverless Functions** — files in `netlify/functions/` (or whatever `[build] functions` names), one file per endpoint, reachable at `/.netlify/functions/<name>`. Modern ones export a default handler plus an optional `config` object with a `path` for a custom route; older ones export `handler(event, context)`. Framework adapters generate these behind the scenes (`@netlify/plugin-nextjs` compiles a Next.js app into functions).
- **Edge Functions** — Deno, in `netlify/edge-functions/`, declared either by a `config` export or by `[[edge_functions]]` in `netlify.toml`. They run before the CDN cache and can rewrite, transform, or short-circuit a request. Much tighter resource limits than a serverless function.
- **Redirects and rewrites** — `netlify.toml` `[[redirects]]` or a `_redirects` file in the publish directory.

```bash
ls netlify/functions netlify/edge-functions 2>/dev/null
grep -n 'redirects\|headers\|edge_functions\|\[functions\]\|schedule' netlify.toml
cat public/_redirects 2>/dev/null; cat public/_headers 2>/dev/null
netlify functions:list
```

**Redirects have real semantics worth reading carefully.** A rule with `status = 200` is a rewrite (the URL does not change, the content is proxied); `status = 301`/`302` is a redirect; `force = true` makes the rule win over an existing file at that path, and without it a static file shadows the rule silently. The SPA catch-all,

```toml
[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

means **every unmatched path returns 200**, not 404 — a soft 404 that SEO cares about and that makes any probe inferring route existence from a status code useless. A proxy rewrite to an external host (`to = "https://api.example.com/:splat"`, `status = 200`) turns your domain into a proxy for that host; check what it exposes and whether it forwards credentials (SEC-045's open-proxy shape, applied to redirects).

Rules in `_redirects` and `netlify.toml` are both evaluated, `netlify.toml` first in the current behaviour, and the first match wins — so a broad rule near the top of one file silently disables everything after it. When two files exist, read both and say which rule you believe is winning, or verify with `curl`.

**Role-based redirects** (`Role=admin` conditions with Netlify Identity JWTs) are a real access-control mechanism when Identity is in use. If a project relies on them, note it: they are enforced at the CDN, they are only as good as the JWT, and they are separate from whatever the application does.

## auth
Not applicable for this stack in the application sense — Netlify has no notion of your users by default, and the app's session handling belongs to the framework's stack file.

Platform-level access surfaces that do matter:

- **Deploy Preview and branch-deploy visibility.** Deploy previews are publicly reachable at their `deploy-preview-<n>--site.netlify.app` URL unless password protection or role-based access is configured — both of which are paid-plan features on most tiers. Check the site's Visitor Access settings and verify from a logged-out context with `curl -I`. A public deploy preview holding production data is DAT-017 and SEC-010 together.
- **Site-wide password protection** and **Netlify Identity** role gating, where present. Identity is legacy on new sites; a project still using it should know that, and REL-013 owns the deprecation risk.
- **Team access** — who can change environment variables, publish a deploy, or lock a deploy. That is ACC-001's territory and is entirely dashboard state.
- **Build hooks** are unauthenticated URLs that trigger a build. A build hook URL committed to the repo or pasted into a public issue lets anyone force a rebuild — annoying rather than catastrophic, but it is a credential and belongs with the others (SEC-001).

## webhook handlers
Nothing platform-specific about receiving a webhook — it is an ordinary function, and the raw-body rule belongs to the framework's stack file. Netlify facts that change whether one works:

1. **The execution ceiling applies.** A handler doing slow work before returning 2xx will be cut off, the provider will retry, and a non-idempotent handler duplicates its side effects (PAY-003 on the payment path).
2. **The payload ceiling applies.** A provider posting a body larger than the function payload limit gets a platform rejection your handler never sees.
3. **Base64 bodies.** In the older `handler(event, context)` signature, a binary or content-encoded body arrives with `event.isBase64Encoded: true` and `event.body` base64-encoded. A signature verification that hashes `event.body` directly in that case is verifying the wrong bytes and will fail every time — decode first (`Buffer.from(event.body, 'base64')`). This is the platform-specific way SEC-051 fails on Netlify.
4. **Password protection blocks providers.** A protected site returns an HTML challenge to Stripe, GitHub, or Twilio, and the provider records a delivery failure while your logs show nothing.

Netlify's own **outgoing notifications** (deploy succeeded/failed, form submission, and similar) can be sent to a URL you own and are signed with a JWS in an `X-Webhook-Signature` header when a JWS secret is configured on the notification. If a project consumes those, verify the signature; if the notification was configured without a secret, anyone who learns the URL can forge a deploy-failed alert.

## webhook verification snippet
The pattern that matters most on this platform is decoding the body before verifying it:

```js
// netlify/functions/stripe-webhook.js  (handler signature)
exports.handler = async (event) => {
  const raw = event.isBase64Encoded
    ? Buffer.from(event.body, 'base64')
    : Buffer.from(event.body, 'utf8')          // the exact bytes, never a re-serialized object
  try {
    const e = stripe.webhooks.constructEvent(raw, event.headers['stripe-signature'], process.env.STRIPE_WEBHOOK_SECRET)
    // ... handle e.type
    return { statusCode: 200, body: 'ok' }
  } catch {
    return { statusCode: 400, body: 'bad signature' }
  }
}
```

With the modern `(req: Request, context: Context)` signature there is no base64 wrapper — `await req.text()` gives the raw bytes directly, exactly as on any Fetch-API runtime. Establish which signature the project uses before reading the verification as broken.

Verifying a Netlify outgoing notification:
```js
const jwt = require('jsonwebtoken')                         // or any JWS verifier already in the project
const claims = jwt.verify(event.headers['x-webhook-signature'], process.env.NETLIFY_WEBHOOK_JWS_SECRET)
// claims.sha256 must equal the SHA-256 of the raw request body
```

For provider webhooks (Stripe, RevenueCat, Lemon Squeezy), see that provider's stack file.

## data access
Netlify runs no relational database of its own; it integrates. What you find:

- **An external Postgres/MySQL** (Supabase, Neon, PlanetScale, RDS) reached from a function. Every concurrent invocation is a separate process with its own connection, so a modest spike exhausts a small instance. The fixes are a pooled connection string (Supabase's pooler port, Neon's pooled endpoint, PgBouncer) or an HTTP driver (`@neondatabase/serverless`, Prisma Accelerate, PostgREST). Prisma additionally needs `DIRECT_URL` for migrations while the app uses the pooled URL (DAT-008, PERF-018).
- **Netlify Blobs** (`@netlify/blobs`) — a key-value store scoped per site and per deploy. `getStore()` versus `getDeployStore()` is the distinction that matters: a deploy-scoped store is wiped with the deploy, so anything durable must use the site-scoped one. It is also the closest thing Netlify has to a runtime-mutable config store, which makes it the natural home for a kill switch (see "background jobs").
- **Netlify Forms**, if enabled, captures form submissions into the dashboard. Any form with a `netlify` or `data-netlify="true"` attribute is collecting and storing whatever users type — which is personal data with a retention question attached (COMP-016), stored somewhere the team may not realise, and a spam magnet without the honeypot or reCAPTCHA options.
- **Edge Functions cannot open TCP connections** (Deno on the edge), so anything talking to Postgres from an edge function is going through an HTTP data proxy — identify which, because the authorization model differs.

**Caching is a data-access concern here.** Netlify's CDN caches on `Cache-Control` and on `Netlify-CDN-Cache-Control` / `Cache-Tag` for fine-grained control, and framework adapters set these on your behalf. A `Cache-Control: public` on an authenticated response, or a page pre-rendered at build time that reads a session, serves one user's data to the next from the CDN (SEC-036, SEC-011) with no error anywhere. Netlify's default for function responses is not to cache unless a caching header says so — but a framework adapter may set one, so read the actual response.

## file uploads
An upload proxied through a function is bounded by the function payload ceiling ("known traps"), and the rejection happens before the handler runs — the client sees an opaque failure and your logs show nothing.

The shapes that scale: a presigned direct-to-storage upload (S3, R2, Supabase Storage), or Netlify Blobs written from a function for small objects. Netlify Blobs is not a CDN-backed media store in the way object storage is; serving large media from it goes through a function on every request, which is both slow and costed per invocation.

**Netlify Large Media** is deprecated and should not be found in a new project; if it is, that is a REL-013 finding on its own.

For DAT-005, whatever bucket the presigned upload targets is the thing to check for public read access — Netlify has no bucket of its own to misconfigure, so the finding belongs to the storage provider's stack file.

## background jobs
**Scheduled Functions.** Declared either in the function itself or in `netlify.toml`:

```js
// netlify/functions/reconcile.mts
import type { Config } from "@netlify/functions"
export default async () => { /* the job */ }
export const config: Config = { schedule: "@hourly" }      // or a cron expression: "0 3 * * *"
```
```toml
[functions."reconcile"]
  schedule = "0 3 * * *"
```

The platform fact that decides SEC-014 here: **Netlify does not route public HTTP requests to a scheduled function in production.** It is invoked internally by the scheduler, so there is no public URL for an attacker to hit and no shared secret to check — which makes SEC-014 a pass by construction for a *scheduled* function, and worth recording as such with the mechanism named rather than as an unexplained pass. Verify it rather than asserting it:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/.netlify/functions/reconcile
```

Expect a 404 (or a 405) rather than the job running. **And check the other half:** any *ordinary* function used as a job endpoint — one triggered by GitHub Actions, an external scheduler, or a `curl` in a cron somewhere — is a fully public URL at `/.netlify/functions/<name>` and does need a secret guard exactly as SEC-014 describes. That is the common shape on this platform, because the scheduled-function limits push long jobs onto an external trigger.

Other REL-019 properties:
- Netlify does not retry a failed scheduled function and does not alert on one. Unless the handler pings a dead-man's-switch (Cronitor, Healthchecks.io, Sentry Cron Monitors), a job that stopped running two weeks ago looks exactly like one that runs fine. Its absence is the finding.
- The finest supported schedule granularity and the number of scheduled functions are plan-dependent — check the current plan limits.
- A scheduled function runs under the synchronous execution ceiling, not the background one. Anything long belongs in a background function or a real queue.

**Background Functions.** A function whose filename ends `-background` (`netlify/functions/import-background.mts`) returns 202 immediately and continues running, with a much longer ceiling — commonly documented at 15 minutes. It gives you duration; it does not give you retries, a queue, visibility, or durability. Anything that must not be lost belongs in a real queue (Inngest, Trigger.dev, QStash, or a database-backed job table), and PERF-013 owns that recommendation.

**Kill switch (REL-010).** Netlify has no Edge Config equivalent, so the two workable shapes are: an environment variable read by a function or edge function, which requires a redeploy to change and therefore takes minutes rather than seconds; or a value in Netlify Blobs / an external store read on each request, which is instant. If the project's kill switch is an environment variable, say so and say what the latency is — "we can turn it off" meaning "after a four-minute rebuild" is a materially different answer during an incident, and an edge function reading a Blobs value is the cheap fix.

**Email** is usually sent inline from a function. Inline sending makes the request as slow and as failure-prone as the provider, and inside the synchronous ceiling with a slow provider that is a real failure mode (PERF-014's timeout budget against PERF-020's ceiling).

## error handling and logging
**Function logs.** Everything a function writes to stdout/stderr appears in the site's Function log stream in the dashboard, and via the CLI:
```bash
netlify logs:function <function-name>
netlify logs:deploy
netlify watch                                  # follow the current build
```
**Retention is plan-dependent and short by default**, with Log Drains (Datadog, Axiom, an HTTP endpoint) as the way to keep anything longer — a paid feature. For REL-015 the consequence is concrete: if the only logging is `console.log` and there is no drain, the day after an incident there is nothing left to read, and that is the finding regardless of how good the log lines are.

There is no automatic trace id across functions. Structured logging (Pino, or `console.log(JSON.stringify(...))`) with a request id propagated in a header is what makes concurrent invocations readable; bare `console.log` interleaves into nonsense under concurrency (REL-015).

**Build logs** are separate from function logs and are where a failed deploy explains itself. They are also where secrets leak most often — a build script echoing an environment variable puts it in a log that everyone with site access can read, which is why the secrets-scanning step exists. Grep the build scripts for `echo $`, `env`, `printenv`, and `set -x` (SEC-001, REL-015).

**Error tracking (REL-001).** Sentry, or the framework's own integration. Netlify's function logs are not error tracking: no grouping, no alerting, and the retention above. On a framework adapter (`@netlify/plugin-nextjs`), remember that the server runtime and any edge functions are separate runtimes and each needs its own initialization — an edge middleware error will not reach a Node-only Sentry setup.

**Source maps (SEC-007).** Netlify does not decide this; the framework does. `productionBrowserSourceMaps` (Next.js), `build.sourcemap` (Vite), `sourcemap.client` (Nuxt). The correct shape is hidden maps uploaded to the error tracker during the build and then removed from the publish directory — and Netlify makes the failure easy to check, because the publish directory is served verbatim:
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/assets/<bundle>.js.map
```
A 200 means the map is public.

**Errors returned to clients.** Framework territory (SEC-009), except for one platform behaviour: a function that times out or crashes before responding produces Netlify's own error response, not yours, and your error tracker may never have run — a timeout is invisible to a handler that never got to report it.

## security headers
Two places, both of which apply at the CDN to every matching response including static assets:

```toml
# netlify.toml
[[headers]]
  for = "/*"
  [headers.values]
    Strict-Transport-Security = "max-age=63072000; includeSubDomains; preload"
    X-Content-Type-Options = "nosniff"
    Referrer-Policy = "strict-origin-when-cross-origin"
    Permissions-Policy = "camera=(), microphone=(), geolocation=()"
    Content-Security-Policy = "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
```

```
# public/_headers  (must be in the publish directory, so usually public/ or static/)
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
```

For SEC-031 and SEC-033 the configuration can live in **four** places and all must be checked before reporting a header absent: `netlify.toml` `[[headers]]`, a `_headers` file in the publish directory, an edge function setting headers on the response (the only place a per-request nonce for CSP can be generated), and the framework's own mechanism. When more than one sets the same header, read the actual response rather than reasoning about precedence:

```bash
curl -sI https://example.com/ | tr -d '\r'
curl -sI https://example.com/assets/<a static asset> | tr -d '\r'   # the commonly-missed half
```

Two Netlify-specific gotchas. A `_headers` file outside the publish directory is silently ignored — it must be in `publish`, which for most frameworks means `public/` or `static/` so the build copies it. And headers from `netlify.toml` do **not** apply to responses generated by a function unless the function sets them itself or an edge function adds them; a CSP configured for the static site and absent from every API and SSR response is a partial pass at best (SEC-031).

HTTPS is automatic — Netlify serves HTTPS and redirects HTTP with the "Force HTTPS" setting, which is on by default for sites with a provisioned certificate — so SEC-034's redirect half is normally a pass; name the platform and confirm with `curl -sI http://example.com`. HSTS is not automatic and is still worth verifying in the response above.

`X-Robots-Tag` for SEO-004: see "known traps".

## known traps
- **Function execution ceiling.** Synchronous functions are commonly documented with a ceiling around 10 seconds (raisable on higher plans, with figures around 26 seconds quoted), background functions — filenames ending `-background` — around 15 minutes, and edge functions with a much smaller CPU budget again. **These numbers differ by plan and have moved; check the current plan limits and treat any figure here as an illustration.** Record what the project's slowest handler actually does against the real ceiling, and remember PERF-014's arithmetic: three 5-second attempts do not fit in a 10-second function. PERF-020.
- **Function payload ceiling**, commonly documented around 6 MB for a synchronous request or response, inherited from the underlying Lambda payload limit. Check the current figure. The rejection is platform-level, so the handler never runs and your logs show nothing. PERF-020, and the fix is a presigned direct-to-storage upload ("file uploads").
- **Environment variables with one value for all contexts**, so deploy previews hold the production `DATABASE_URL` and every pull request writes live rows: DAT-017. This is the default shape when a variable is created without choosing a context.
- **`NODE_ENV` is `production` in every build context**, deploy previews included. Branch on `CONTEXT` instead. Code that gates seeding, test-mode payment keys, or debug endpoints on `NODE_ENV !== 'production'` is disabled on previews and enabled nowhere; code gating a destructive operation on the inverse runs its production branch against a preview database. DAT-017, HYG-001.
- **Secrets in `netlify.toml`** under `[build.environment]` or `[context.*.environment]`: SEC-001, committed and readable by anyone with repo access. Related: `SECRETS_SCAN_ENABLED = "false"` or a broad `SECRETS_SCAN_OMIT_KEYS`, which disables the platform's own guard — the disabling is itself worth a line.
- **A build hook URL committed to the repo**: an unauthenticated trigger for a production build (SEC-001).
- **Deploy previews are publicly reachable** unless password protection or role-based access is configured, both paid features on most tiers. Verify from a logged-out `curl -I` rather than asserting a default. A public preview holding production data is DAT-017 and SEC-010 together.
- **Preview indexing.** Netlify has for some time added `X-Robots-Tag: noindex` to deploy previews and branch deploys automatically, but this is exactly the kind of platform default worth verifying rather than trusting: `curl -sI https://deploy-preview-1--site.netlify.app/ | grep -i x-robots-tag`. An indexable preview duplicates the whole site under a `*.netlify.app` host and can outrank it. SEO-004. A custom staging domain attached to the site gets no such default and needs an explicit rule.
- **`_headers` outside the publish directory is silently ignored**, and `netlify.toml` headers do not reach function-generated responses: SEC-031, SEC-033. Verify with `curl -I` against both a static path and an API path rather than reading the config alone.
- **Redirect precedence.** `netlify.toml` rules and `_redirects` rules are both evaluated and the first match wins; a broad rule near the top silently disables everything after it. A `status = 200` rule is a rewrite, not a redirect, and `force = true` is what makes a rule beat an existing file.
- **The SPA catch-all returns 200 for every unmatched path**: a soft 404 for SEO, and a misleading result for any probe that infers route existence from a status code.
- **A proxy rewrite to an external host** (`to = "https://api.example.com/:splat"`, `status = 200`) makes your domain a proxy for that host. Check what it exposes and whether it forwards credentials or authorization headers (SEC-045's open-proxy shape).
- **Scheduled functions are not publicly invocable in production**, which makes SEC-014 a pass by construction for them — record it with the mechanism named. But **any ordinary function used as a job endpoint is a fully public URL** at `/.netlify/functions/<name>` and does need a secret guard, and that is the common shape here because long jobs get pushed onto an external trigger. A `===` comparison of that secret is SEC-052.
- **Nothing monitors a scheduled function.** No retry, no alert on failure; unless the handler pings a dead-man's-switch, a job that stopped two weeks ago is indistinguishable from one that works: REL-019.
- **Kill switch latency.** With no Edge Config equivalent, an environment-variable kill switch needs a full redeploy to take effect — minutes, during an incident. A value in Netlify Blobs or an external store read per request is instant. Say which the project has and what the latency is: REL-010.
- **Background functions treated as a queue.** They give duration, not retries, ordering, visibility, or durability: PERF-013.
- **Base64 request bodies** in the `handler(event, context)` signature: a signature verification that hashes `event.body` without decoding when `isBase64Encoded` is true verifies the wrong bytes and fails every delivery. SEC-051, in its Netlify-specific form.
- **`Cache-Control: public` on an authenticated response**, or a page pre-rendered at build time that reads a session: SEC-036, SEC-011. The CDN serves it to the next visitor with no error anywhere.
- **Connection exhaustion.** Every concurrent function invocation opens its own database connection; without a pooler or an HTTP driver a spike exhausts the instance: DAT-008, PERF-018. Prisma needs `DIRECT_URL` for migrations alongside the pooled `DATABASE_URL`.
- **Netlify Forms collecting personal data** that nobody has a retention policy for, and that is not in the privacy policy's list of what is stored: COMP-016. Check the honeypot or captcha too, or the submissions are mostly spam.
- **Netlify Identity or Large Media in a new project**: both are legacy, and depending on it is a REL-013 finding.
- **Log retention is short and plan-dependent**, with no drain by default: REL-015. Build logs are separate from function logs and are where an `echo $SECRET` in a build script ends up.
- **Publish-directory source maps.** The publish directory is served verbatim, so a `.map` in it is public source: SEC-007. Fetch one rather than reading the config.
- **Much of this platform is dashboard state.** Environment-variable scoping and contexts, visitor access, log drains, domain redirects, plan limits, and team access have no repo representation. `not determinable from the repo; confirm in the dashboard` is a legitimate and honest finding — an invented default is not.

## runtime probe hints
**Establish which deploy you are probing.** A `*--site.netlify.app` URL is a specific deploy; the production domain is whatever is currently published. `netlify status` and the dashboard's deploy list tell you which is which, and `curl -sI` for `x-nf-request-id` identifies the request in the logs.

```bash
netlify status                                   # is the CLI authenticated and linked?
netlify env:list                                 # names and contexts — the DAT-017/HYG-001 answer
netlify functions:list
netlify api listSiteDeploys --data '{"site_id":"<id>"}' | head -40    # raw API, read-only
curl -sI https://example.com/ | tr -d '\r'
```

Useful response headers: `x-nf-request-id` (the handle for a request in the logs), `server: Netlify`, `cache-status` / `netlify-cdn-cache-control` for the caching question (SEC-036's probe), and `age`.

**Is the deploy preview public and indexable?** From a context with no Netlify session:
```bash
curl -sI https://deploy-preview-<n>--<site>.netlify.app/ | tr -d '\r' | grep -iE 'HTTP/|x-robots-tag|www-authenticate'
```
A 401 with a basic-auth or password challenge means protection is on. A 200 with your app means it is not. Grep for `x-robots-tag: noindex` for SEO-004.

**Function ceiling and payload limit, measured rather than assumed** (against a deploy preview, never production, and only on an endpoint safe to call):
```bash
curl -s -o /dev/null -w 'status=%{http_code} total=%{time_total}\n' https://<preview>/.netlify/functions/<a slow but safe function>
head -c 7000000 /dev/zero | tr '\0' 'a' > .pre-launch/probe-body.bin
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<preview>/.netlify/functions/<upload> \
  -H 'content-type: text/plain' --data-binary @.pre-launch/probe-body.bin
rm -f .pre-launch/probe-body.bin
```
Record the observed numbers alongside the documented ones and say which is which. Delete the probe body afterwards, as the last line does.

**Job endpoints (SEC-014).** Two probes. First, confirm the scheduled function is not publicly invocable:
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/.netlify/functions/<scheduled function name>
```
Expect 404 or 405. Second, for any ordinary function acting as a job endpoint, call it with no `Authorization` header and expect 401:
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/.netlify/functions/<job function>
```
A 200, or any evidence the job ran, is the finding. Do not then call it with the real secret — a job endpoint has side effects by definition.

**Headers (SEC-031, SEC-033).** Check a page, a static asset, and a function response, because the three are configured separately here:
```bash
curl -sI https://example.com/ | tr -d '\r'
curl -sI https://example.com/favicon.ico | tr -d '\r'
curl -sI https://example.com/.netlify/functions/<any safe GET function> | tr -d '\r'
```

**Redirect behaviour.** Verify what a rule actually does rather than reading the file:
```bash
curl -sI https://example.com/<a redirected path> | tr -d '\r' | grep -iE 'HTTP/|location'
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/definitely-not-a-real-path-12345   # 200 here means a SPA catch-all
```

**Domains and certificates (REL-017).**
```bash
curl -sI https://www.example.com | tr -d '\r' | head -5
curl -sI http://example.com | tr -d '\r' | head -5
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | openssl x509 -noout -dates -issuer
```
Netlify-issued Let's Encrypt certificates renew automatically; a short remaining life is normal rather than a finding.

**Logs.** `netlify logs:function <name>` follows a function's output; `netlify logs:deploy` the build. Both are bounded by retention. If the answer to "what happened at 3am yesterday" is "nothing is retained", that is REL-015's finding and should be recorded as one rather than as a failure to investigate.

**Never** trigger a deploy, publish or lock a deploy, change an environment variable, run `netlify env:import`, or hit a build hook during an audit. Everything above is read-only apart from the deliberate negative probes, and those run against a deploy preview.
