# Astro

## detection signals
`astro` in package.json dependencies plus `astro.config.mjs|ts|js` and a `src/pages/` directory. `.astro` component files. Generated `dist/` and `.astro/`.

**The first thing to establish, before any other check, is whether this site has a server at all.** Astro builds a fully static site unless an adapter is installed: look for `@astrojs/node`, `@astrojs/vercel`, `@astrojs/netlify`, or `@astrojs/cloudflare` in dependencies and an `adapter:` entry in `astro.config`. With no adapter, there is no runtime: no server routes, no middleware at request time, no sessions, and every local-tier check that needs a running handler is `skipped` with the reason "statically generated, no adapter". Integrations in `astro.config` (`@astrojs/react`, `svelte`, `vue`, `tailwind`, `mdx`, `sitemap`) tell you what else is in play.

The `output` option changed meaning between majors: Astro 4 had `output: 'static' | 'hybrid' | 'server'`; Astro 5 removed `'hybrid'` and made `'static'` the default with per-route opt-in via `export const prerender = false`, while `output: 'server'` inverts the default to on-demand with `export const prerender = true` opting a route back out. Read `astro.config` **and** the `prerender` exports together, and check the installed major's docs before concluding what a given route does.

## dev server
`npm run dev` (or `pnpm|yarn|bun dev` per lockfile) → `astro dev`. Default port **4321**. Ready when `GET /` returns 200. Override with `--port`, `--host`, or `server: { port }` in `astro.config`. Never measure performance, headers, or analytics gating against the dev server — see "build". Note that the dev server runs every route on demand, including ones that will be prerendered in the build, so an auth check that appears to work in dev can be baked into static HTML in production; that gap is exactly what the production-build rule exists to catch.

## build
`npm run build` → `astro build` → `dist/`.

- **Static (no adapter)** — `dist/` is HTML plus assets. `npm run preview` (`astro preview`) serves it on port **4321** and honours `dist/404.html`. Any static server works; `python3 -m http.server` will not serve the 404 page correctly, so prefer `astro preview` when the not-found behaviour is being checked.
- **`@astrojs/node`, `mode: 'standalone'`** — `dist/server/entry.mjs` is a runnable server: `HOST=127.0.0.1 PORT=3100 node ./dist/server/entry.mjs`. Default port 4321 unless `PORT` says otherwise. This is the production probe target.
- **`@astrojs/node`, `mode: 'middleware'`** — the build exports a handler that the project's own `server.mjs`/Express file mounts. Find that file; it is the real entry point and its port and middleware stack are what production uses.
- **Vercel / Netlify / Cloudflare adapters** — platform-shaped output (`.vercel/output`, `.netlify/`, `dist/_worker.js`); run through that platform's local CLI if available, otherwise use `astro preview`, which those adapters support to varying degrees — say which you used.

Client-side JS lands in `dist/_astro/`; grep there for leaked secrets (SEC-003). A static build additionally bakes anything a page's frontmatter printed into the generated HTML, so grep `dist/**/*.html` too, which is a step other frameworks do not need.

## env vars
Vite loads `.env`, `.env.production`, `.env.development`, and their `.local` variants. Two mechanisms:

**`import.meta.env`** — the classic route. `import.meta.env.PUBLIC_*` is exposed to the browser and inlined at build time; everything else is server-only and stripped from the client bundle. **`PUBLIC_` is the public prefix: a secret in a `PUBLIC_`-named variable is a leak (SEC-003).** `process.env` also works on the server with the node adapter.

**`astro:env`** — the typed route (Astro 5; experimental from 4.10). A schema in `astro.config` declares each variable with `context: 'client' | 'server'` and `access: 'public' | 'secret'`, and code imports from `astro:env/client` or `astro:env/server`. A `client` variable is public whatever it is called, so read the schema rather than the names. Check the installed major's docs for whether it is stable in this project.

**The static-build wrinkle, and it is specific to Astro:** on a prerendered page, "server-only" means *build machine only*. Frontmatter runs once at build time, so `const key = import.meta.env.STRIPE_SECRET_KEY` interpolated into markup, into a data attribute, or into a serialized island prop is written straight into `dist/**/*.html` and shipped, prefix or no prefix (SEC-003). Grep the built HTML, not just the JS chunks.

`.env` is read at build and in dev. An on-demand build takes its environment from the process at runtime, so a variable that exists only in `.env` is undefined in production (REL-008), and any value read on a prerendered page is frozen at build time and needs a rebuild to change. For payment test-mode detection read `STRIPE_SECRET_KEY` / `PUBLIC_STRIPE_PUBLISHABLE_KEY` from the running process, then `.env`; the `sk_test_` / `pk_test_` prefix is the tell.

## routes and handlers
- **Pages** — `src/pages/**/*.astro`, `.md`, `.mdx`, and framework components (`.tsx`, `.svelte`, `.vue`) used as pages. File path becomes the URL; `index.astro` is the directory root, `[id].astro` a param, `[...slug].astro` a rest param. A prerendered dynamic route must export `getStaticPaths()` listing every path to build; an on-demand one must not.
- **Endpoints** — `src/pages/**/*.ts|.js` exporting `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `ALL` as `async ({ request, params, locals, cookies, url, redirect })` returning a `Response`. `src/pages/api/thing.ts` → `/api/thing`. `src/pages/rss.xml.ts` and `sitemap` routes are the same mechanism. **In a static build an endpoint is executed at build time and its output written as a file** — a webhook receiver or a login handler therefore needs `export const prerender = false` and an adapter, and without them it silently becomes a static file. This is the single most common Astro misconfiguration to look for.
- **Middleware** — `src/middleware.ts` (or `src/middleware/index.ts`) exporting `onRequest(context, next)`, composed with `sequence()` from `astro:middleware`. It sets `context.locals`, can short-circuit with a `Response`, and can post-process `(await next()).headers`. **It runs for on-demand routes; for prerendered routes it runs at build time with a synthetic request, or not at all depending on the version — either way it is not a request-time guard there** (see "known traps").
- **Layouts and components** — `src/layouts/*.astro` (where `<html lang>`, `<head>`, analytics and consent scripts live) and `src/components/`. A `.astro` component's frontmatter runs on the server (build time or request time); its template can hydrate framework islands with `client:load`, `client:idle`, `client:visible`, `client:only`, and those run in the browser.
- **Actions** — `src/actions/index.ts` with `defineAction({ input, handler })` from `astro:actions`, called from the client as `actions.name(input)` (Astro 5; experimental in 4.15). These are **public HTTP endpoints** served under `/_actions/*` and each needs its own auth check inside the handler (SEC-010). Check the version's docs; if the project has no `src/actions/`, this does not apply.
- **Server islands** — `server:defer` on a component (Astro 5) fetches that fragment from the server after the shell renders; the fragment endpoint is public and its props are encrypted-but-round-tripped, so it needs the same auth check as any other handler.
- Special pages: `src/pages/404.astro` (built to `dist/404.html` in a static build, rendered on demand in SSR) and `src/pages/500.astro` (SSR only).

The AI/chat endpoint, when there is one, is an endpoint rather than a page — `src/pages/api/chat.ts` with `export const prerender = false` is the convention, returning a stream. With the `ai` package it is `streamText(...).toDataStreamResponse()`; hand-rolled versions return `new Response(readableStream, { headers: { 'content-type': 'text/event-stream' } })`. Either way the response is server-sent events or the `ai` package's data-stream protocol, so a probe must read the whole stream and reassemble the text before judging it — the first chunk is not the answer. On a static build there is no such endpoint: a chat UI on a static Astro site is calling a third-party API from the browser, which is a different finding (a key in the client bundle) rather than a route to probe.

To enumerate routes: `find src/pages -type f`, then `grep -rn 'export const prerender' src/pages src/` to see which are on-demand.

## auth
Nothing ships with Astro. The shape is middleware plus a per-route check:

```ts
// src/middleware.ts
import { defineMiddleware } from 'astro:middleware'

export const onRequest = defineMiddleware(async (context, next) => {
  const token = context.cookies.get('session')?.value
  context.locals.user = token ? await validateSession(token) : null
  return next()
})
```

...and then, in every on-demand page and endpoint that needs it:

```ts
// src/pages/dashboard.astro (frontmatter)
export const prerender = false
if (!Astro.locals.user) return Astro.redirect('/login')
```

Libraries: `auth-astro` / `@auth/astro` (Auth.js — `authjs.session-token`), `@clerk/astro` (`clerkMiddleware()`, `Astro.locals.auth()`, `__session`), `@supabase/ssr` with `createServerClient` reading `Astro.cookies` and `getUser()` for authorization (never `getSession()` alone), Lucia-style hand-rolled sessions in `src/lib/auth.ts`, or Astro 5's experimental `session` support — check the version's docs before treating a `session` API as present.

**Two Astro-specific failure modes for SEC-010 and SEC-011.** First, an authenticated page that is prerendered: the check runs on the build machine, where there is no user, and whatever it renders is served to everyone. Any page reading `Astro.locals`, `Astro.cookies`, or `Astro.request.headers` must be on-demand — verify `prerender` for each one rather than assuming the `output` setting covers it. Second, middleware alone is not a guard for API endpoints unless it actually returns a `Response` for the unauthenticated case; middleware that only annotates `locals` leaves every endpoint that forgets to read it open.

## webhook handlers
`src/pages/api/webhooks/<provider>.ts` exporting `POST`, and it **must** carry `export const prerender = false` and run under an adapter, or it is not a runtime route at all. The raw body is `await request.text()`; Astro does not parse the body for you, but `await request.json()` consumes the stream and a later `request.text()` throws, which is how a handler ends up unable to verify (SEC-051). Exempt the webhook path from any middleware that requires a session, and from any middleware that rewrites or redirects.

## webhook verification snippet
```ts
// src/pages/api/webhooks/stripe.ts
import type { APIRoute } from 'astro'
import Stripe from 'stripe'

export const prerender = false // required: without this the route is built as a static file

const stripe = new Stripe(import.meta.env.STRIPE_SECRET_KEY)

export const POST: APIRoute = async ({ request }) => {
  const sig = request.headers.get('stripe-signature')
  const raw = await request.text() // raw first; never request.json() before this
  if (!sig) return new Response('missing signature', { status: 400 })

  let event: Stripe.Event
  try {
    event = stripe.webhooks.constructEvent(raw, sig, import.meta.env.STRIPE_WEBHOOK_SECRET)
  } catch {
    return new Response('bad signature', { status: 400 })
  }
  // handle event.type ...
  return new Response('ok', { status: 200 })
}
```
For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
Three separate things live under this heading in an Astro project and they are easy to confuse:

- **Content collections** — `src/content/config.ts` (Astro 4) or `src/content.config.ts` (Astro 5, with the `glob()`/`file()` loader API) define Zod-validated schemas over `src/content/<collection>/**` Markdown/MDX, read with `getCollection()` and `getEntry()` from `astro:content`. This is build-time content, not user data; it has no access control and everything in it is public by construction.
- **Astro DB** — `db/config.ts` (`defineTable`, `defineDb`), `db/seed.ts`, queried with `db.select().from(Table)` from `astro:db`. Check the version's docs for its current status before treating it as the app's primary store.
- **An external database** — a Supabase, Prisma, or Drizzle client in `src/lib/db.ts` / `src/lib/supabase.ts`. Policies and schema belong to that stack: `supabase/migrations/*.sql`, `prisma/schema.prisma`, `drizzle/schema.ts`.

There is no `.server` suffix and no `$lib/server` alias in Astro, so **the boundary is where the code runs, not where it lives**: `.astro` frontmatter and endpoint modules are server-side; a framework component with a `client:*` directive, and anything it imports, ships to the browser. A shared `src/lib/db.ts` imported by both is a leak with no build error to catch it — grep every `client:` island's import graph.

**Payload trap:** props passed to a hydrated island are serialized into the HTML as a `<script type="application/json">` payload so the client can hydrate. `<UserCard client:load user={user} />` with a full DB row publishes every column of it. Pass a narrow object. On a prerendered page the same serialization happens at build time and is baked into the static file.

## file uploads
Only meaningful with an adapter. An endpoint with `export const prerender = false` reading `await request.formData()` and pulling `File` entries out of it; check `file.size` and re-derive the type from magic bytes rather than trusting `file.type`. Direct-to-storage presigned uploads (S3, R2, Supabase Storage) are the common pattern and bypass the server body limit entirely. Astro actions can also accept `FormData` input with a Zod schema.

`astro:assets` (`<Image />`, `<Picture />`, `getImage()`) optimizes images. Local images imported from `src/assets/` are processed at build time and are not an SSRF surface. **Remote images are:** `image.domains` (an exact-host allowlist) and `image.remotePatterns` (protocol/hostname/pathname patterns) in `astro.config` decide which remote URLs the optimizer will fetch. A pattern as loose as `{ protocol: 'https' }`, or a `domains` list containing a wildcard, lets the optimizer fetch arbitrary URLs on request — with an adapter that makes it a live proxy (SEC-045). Files in `public/` are copied verbatim and never optimized or validated.

Body size ceilings come from the adapter's host, not from Astro — read the deploy platform's stack file for the number.

## background jobs
Nothing built in, and there is no runtime at all in a static build. Look for: a platform cron (`vercel.json` `crons`, a Netlify scheduled function, a Cloudflare cron trigger, a system crontab) hitting an on-demand endpoint; Inngest, Trigger.dev, or QStash; a scheduled rebuild — a deploy hook fired on a schedule, which is Astro's idiomatic "job" for content freshness and is worth recording as such; a separate worker process in the repo. A cron-triggered endpoint must authenticate its caller with a shared bearer secret checked in the handler (SEC-014). Email sends are inline in an endpoint or action (`src/lib/email.ts` wrapping Resend, Postmark, SendGrid, or nodemailer). Build-time work (feed generation, search index building) lives in `astro.config` integrations hooking `astro:build:done` — note those, since they are jobs that only run on deploy.

## error handling and logging
`src/pages/404.astro` handles not-found; `src/pages/500.astro` handles server errors and only exists meaningfully with an adapter. In recent versions the 500 page receives the thrown error as a prop — check the version's docs, and if it does, rendering that error (or its stack) into the page is a leak (SEC-009). Astro does not scrub error detail as aggressively as some frameworks do, so read what the 500 page and any endpoint `catch` block actually returns; `return new Response(err.message, { status: 500 })` is the common leak.

Middleware is the one place to wrap every on-demand request in a `try`/`catch` and report centrally. Reporting integrations: `@sentry/astro` added as an integration in `astro.config` (it wires the client and server halves and a source-map upload step) — confirm both halves are configured and that maps are uploaded rather than served. Otherwise it is `console.error` to the platform log stream. A static site has no server logs at all; error visibility there is entirely client-side, which is worth stating rather than reporting as missing instrumentation.

## security headers
**Astro has no `headers()` config option**, so do not go looking for one. Where they are set depends on the deployment:

- **Static** — the host or CDN owns them: `vercel.json` `headers`, `netlify.toml` `[[headers]]`, `public/_headers` (Netlify and Cloudflare Pages read this file, and Astro copies `public/` verbatim so it lands at the site root), an S3/CloudFront response-headers policy, or nginx. For a static site this is the *only* place; a middleware file setting headers does nothing at runtime.
- **On-demand** — `src/middleware.ts`, post-processing the response:
  ```ts
  export const onRequest = defineMiddleware(async (context, next) => {
    const response = await next()
    response.headers.set('X-Content-Type-Options', 'nosniff')
    response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin')
    return response
  })
  ```
- **CSP** — Astro has an experimental `experimental.csp` option that emits a policy covering its own inline scripts and styles; check the version's docs for whether it is available and enabled. Hand-written CSP frequently breaks Astro's inline hydration scripts, so a `Content-Security-Policy` with no `unsafe-inline`, no hashes and no nonce is likely to be reported broken rather than absent.

`X-Robots-Tag` for an authenticated area is set the same way; per-page noindex is a `<meta name="robots" content="noindex">` in that page's layout.

## known traps
- A secret in a `PUBLIC_`-prefixed variable, or in an `astro:env` entry declared `context: 'client'`: SEC-003.
- A secret read in the frontmatter of a **prerendered** page and interpolated into markup or into an island's props: it is baked into `dist/**/*.html` and shipped (SEC-003). Grep the built HTML, not just the JS.
- `set:html` with user or CMS content without sanitization: SEC-043. Markdown and MDX content rendered without sanitization is the same sink one layer up.
- `vite: { build: { sourcemap: true } }` in `astro.config`, or a Sentry integration that uploads maps and also leaves them served: SEC-007.
- An endpoint or auth-checking page without `export const prerender = false` in a static-default project: the handler is executed at build time and served as a file, so the check never runs (SEC-010, SEC-011).
- Middleware treated as the guard: it does not run at request time for prerendered routes, and for on-demand routes it only guards if it returns a `Response` rather than just setting `locals` (SEC-010, SEC-012).
- An Astro action (`src/actions/`) or a `server:defer` island without its own auth check: both are public endpoints (SEC-010).
- A page that reads `Astro.locals`, `Astro.cookies`, or a session and is prerendered: one user's data baked into HTML for everyone (SEC-011).
- `Cache-Control: public, max-age=...` set in middleware or at the CDN on an on-demand authenticated response: SEC-036.
- `Astro.redirect(Astro.url.searchParams.get('redirect'))` without an allowlist: SEC-029.
- `image.domains` or `image.remotePatterns` broad enough to fetch arbitrary hosts (`{ protocol: 'https' }` with no hostname): the optimizer becomes a proxy (SEC-045).
- A DB client imported by a component that also carries a `client:*` directive: no build error, and the module and its credentials ship to the browser (SEC-003).
- A full DB row passed as a prop to a hydrated island: it is serialized into the HTML for hydration, so every column is public whatever the component renders (SEC-042).
- Preview or branch deployments inheriting production env unless scoped per environment: DAT-017.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if already in devDependencies; never install one for the audit. Cited by the accessibility and compliance domain headers, COMP-007, and FLOW-018.

## runtime probe hints
**First decide whether there is anything to probe.** With no adapter the built site is static files: there is no login endpoint, no session, and no server route. Record that once, mark the runtime halves of auth, flows, and payments checks `skipped — statically generated, no adapter`, and do the static entries. Everything below assumes an adapter is present.

**Session cookie for `curl`.** Post to the app's own endpoint and keep the jar:
```bash
# sign up a throwaway identity via the app's own endpoint
curl -s -c .pre-launch/flows/cookies.txt -X POST http://localhost:3100/api/auth/signup \
  -H 'content-type: application/json' \
  -d '{"email":"qa+'"$(date +%s)"'@example.com","password":"<from credentials_env>"}' -i
# or a form-encoded page action
curl -s -c .pre-launch/flows/cookies.txt -X POST http://localhost:3100/login \
  --data-urlencode 'email=...' --data-urlencode 'password=...' -i
# reuse
curl -s -b .pre-launch/flows/cookies.txt http://localhost:3100/dashboard -o /dev/null -w '%{http_code}\n'
```
Find the real handler from `src/pages/api/` or `src/actions/` first. An Astro action is called as `POST /_actions/<name>` with a JSON body, so a project using actions is probed that way rather than through a page route.

**Cookie names.** Whatever `Astro.cookies.set(<name>, ...)` or `context.cookies.set(...)` says — `grep -rn "cookies.set(" src/`. Common values: `session`, `sid`, `auth_session`; `auth-astro`/`@auth/astro` uses the Auth.js names `authjs.session-token` / `next-auth.session-token` (`__Secure-` prefixed over HTTPS); `@clerk/astro` uses `__session` plus `__client_uat`; `@supabase/ssr` uses `sb-<project-ref>-auth-token`, possibly chunked as `.0` / `.1` — send every chunk.

**JWT for API probes.** A cookie is not always the credential. DAT-002's RLS probe and the AI domain's per-user retrieval checks call the data API directly as the user, which needs `Authorization: Bearer <jwt>` — and that is **Supabase-specific**, because PostgREST is what makes a per-user bearer probe possible. With any other auth library there is no equivalent surface: record `n/a — no PostgREST surface` for the bearer half and rely on the cookie probes above.

On Supabase, two ways to get the token. Sign in against the auth API and read `access_token` straight out of the response, which is the reliable one:
```bash
curl -s -X POST "$PUBLIC_SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $PUBLIC_SUPABASE_ANON_KEY" -H 'content-type: application/json' \
  -d '{"email":"...","password":"..."}' | jq -r .access_token
```
Or lift it from the cookie the app already set: `sb-<project-ref>-auth-token` holds a base64-encoded JSON session object, chunked across `.0` / `.1` when it is large, and the JWT is its `access_token` field:
```bash
echo "<the chunk values joined in order>" | sed 's/^base64-//' | base64 -d | jq -r .access_token
```
Check the cookie's shape in this version before trusting that pipeline — the `base64-` prefix and the chunking were not always there, and older releases stored the JSON directly. Then probe with both headers, since PostgREST wants the `apikey` as well as the bearer:
```bash
curl -s "$PUBLIC_SUPABASE_URL/rest/v1/<table>?select=*" -H "apikey: $PUBLIC_SUPABASE_ANON_KEY" -H "Authorization: Bearer <jwt>"
```
For the other libraries, so you do not waste time looking: an Auth.js session cookie is either an encrypted JWE (the JWT strategy — not readable by you and not a bearer token for anything) or an opaque database session id; Clerk's `__session` is a JWT but is meant to be verified by Clerk's backend SDK, not replayed at a data API; Lucia and hand-rolled sessions are opaque ids. In all of those the cookie is the only credential the audit can use.

**Health path.** No convention. Look for `src/pages/health.ts`, `src/pages/healthz.ts`, `src/pages/api/health.ts`. A static site has no meaningful health endpoint and no cold start; say so rather than substituting a page.

**Not-found behaviour.** On-demand: an unmatched path renders `src/pages/404.astro` with status 404. Static: the build writes `dist/404.html` and it is up to the host to serve it — `astro preview`, Netlify, Vercel, and Cloudflare Pages do, a bare `http.server` does not, so a 404 finding measured against the wrong server is a false positive; use `astro preview` or the platform's CLI. A project with no `src/pages/404.astro` gets a bare framework/host page. Check the status code and not just the body: a `[...slug].astro` catch-all rendering a "not found" message returns 200 unless it also sets the status via an on-demand `Response`, which is a soft 404 (SEO).

**Test-mode provider keys.** Read the environment of the running process (`printenv | grep -i stripe`), then `.env` and `.env.production`. Remember that a value used on a prerendered page was frozen at build time, so the process env and the shipped HTML can disagree — for anything that a static page baked in, grep `dist/` for the value rather than trusting the environment. Stripe `sk_test_` / `pk_test_` / `rk_test_` and a `whsec_` from `stripe listen`; PayPal on `api-m.sandbox.paypal.com`; Paddle, Lemon Squeezy, RevenueCat a sandbox host, flag, or key. Published test card numbers live in the payment provider's own stack file. If the classification is ambiguous, treat the keys as live and stop.

**Local mail catcher.** None ships with Astro. Check `docker-compose.yml` / `compose.yaml` for `axllent/mailpit` (SMTP `1025`, HTTP `8025`, `curl -s http://localhost:8025/api/v1/messages`), `mailhog/mailhog` (API `/api/v2/messages` on `8025`), or `inbucket/inbucket`; a Supabase local stack runs Inbucket on `54324` (`curl -s http://localhost:54324/api/v1/mailbox/<mailbox>`). Otherwise read the mail env: `SMTP_HOST=localhost` with port `1025` means a catcher is expected, and `RESEND_API_KEY` / `POSTMARK_*` / `SENDGRID_*` in test mode means the "inbox" is the provider's test-mode log or the app's own log line. On a static site the "contact form" is usually a third-party service (Formspree, Netlify Forms, a form action posting to an external host) and no local mail exists at all — say that rather than recording a missing catcher. No reachable catcher where the code does send mail is `error: no mail capture`, never a pass.

**Throwaway identity.** Sign up through the app's own sign-up endpoint with `qa+<unix-ts>@example.com` and the password from the config's `credentials_env`, as above; never reuse the shared test account where a check needs a second identity, and delete the rows the audit created afterwards.
