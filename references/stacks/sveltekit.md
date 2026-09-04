# SvelteKit

## detection signals
`@sveltejs/kit` in package.json (usually devDependencies) alongside `svelte`, plus `svelte.config.js` and a `src/routes/` directory. `vite.config.js|ts` with the `sveltekit()` plugin. An adapter in devDependencies decides the deploy shape and the build output: `@sveltejs/adapter-auto` (picks by platform at build time), `adapter-node`, `adapter-static`, `adapter-vercel`, `adapter-netlify`, `adapter-cloudflare`. Generated `.svelte-kit/`.

Major-version differences matter: SvelteKit 1 required `throw redirect(...)` and `throw error(...)`, SvelteKit 2 lets you call them without `throw` (both still work), and SvelteKit 2 changed cookie defaults and the `use:enhance` API in places. Svelte 5 replaced `export let` props and stores-in-components with runes (`$state`, `$derived`, `$props`). Check `package.json` for both versions before reading a pattern as wrong.

## dev server
`npm run dev` (or `pnpm|yarn|bun dev` per lockfile) → `vite dev`. Default port **5173**; Vite increments to 5174 and up if the port is taken, so read the banner rather than assuming. Ready when `GET /` returns 200. Override with `--port`, `-- --port 5180` through npm, or `server.port` in `vite.config`. Never measure performance, headers, or analytics gating against the dev server — see "build".

## build
`npm run build` → `vite build`, which writes `.svelte-kit/output/{client,server}` and then hands off to the adapter, whose output is what actually runs:
- **adapter-node** → `build/`. Start with `node build` (or `ORIGIN=http://localhost:3100 PORT=3100 node build`). Default port **3000**, set by `PORT`; `HOST`, `ORIGIN`, `BODY_SIZE_LIMIT`, and `ADDRESS_HEADER`/`XFF_DEPTH` are its other env knobs. `ORIGIN` matters: without it, form POSTs can fail the built-in origin check behind a proxy.
- **adapter-static** → a directory of HTML (`build/` by default). No server: runtime auth, server routes, and most local-tier server checks are `skipped` with the reason "statically generated".
- **adapter-vercel / netlify / cloudflare** → platform-shaped output (`.vercel/output`, `.netlify/`, `.svelte-kit/cloudflare`); run it through that platform's local CLI if one is available, otherwise use `npm run preview`.

`npm run preview` (`vite preview`) serves the built client and a dev-adapter server on port **4173** and is the portable way to probe a production build when the adapter's own output is awkward to run. Say which you used. Client bundles live under `.svelte-kit/output/client/_app/immutable/` (and, after the adapter runs, under `build/_app/immutable/` or the platform equivalent) — grep those for leaked secrets (SEC-003).

## env vars
Vite loads `.env`, `.env.local`, `.env.[mode]`, `.env.[mode].local`. SvelteKit then exposes them through four modules, and which one a file imports is the whole security story:

- `$env/static/private` — build-time inlined, server-only. **Importing it from client-reachable code is a build error**, which is SvelteKit's real safety net.
- `$env/dynamic/private` — read from `process.env` at runtime, server-only, same import restriction. Use this one when the value must be settable without a rebuild.
- `$env/static/public` — build-time inlined, available everywhere. Requires the `PUBLIC_` prefix.
- `$env/dynamic/public` — runtime, available everywhere. Requires the `PUBLIC_` prefix.

**`PUBLIC_` is the public prefix: a secret in a `PUBLIC_`-named variable is a leak (SEC-003).** The prefixes are configurable — `kit.env.publicPrefix` (default `PUBLIC_`) and `kit.env.privatePrefix` (default empty) in `svelte.config.js` — so read that config before trusting the default. `import.meta.env.VITE_*` also works and is public by Vite's own rule; a project mixing `VITE_` and `PUBLIC_` has two public prefixes to audit. On the server with adapter-node, plain `process.env` works as well and bypasses the module system entirely — grep for it.

Only `$env/static/*` values are baked into the build; `$env/dynamic/*` reads the live process environment, so the built server needs the variables present at start (REL-008). For payment test-mode detection read `STRIPE_SECRET_KEY` and `PUBLIC_STRIPE_PUBLISHABLE_KEY` from the running process and from `.env`/`.env.local`; the `sk_test_` / `pk_test_` prefix is the tell.

## routes and handlers
Everything lives under `src/routes/**`, with the directory path becoming the URL. The special files:

- `+page.svelte` — the page component (browser and SSR).
- `+page.ts` — **universal** load: runs on the server for the first render **and in the browser** on client-side navigation. Never put a secret or an authorization decision here.
- `+page.server.ts` — **server-only** load, plus `export const actions = { default, named }` for form posts (`POST /path?/actionName`).
- `+layout.svelte`, `+layout.ts`, `+layout.server.ts` — same split, applied to every child route.
- `+server.ts` — a pure API endpoint exporting `GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD`, each `({ request, locals, cookies, url, params })` returning a `Response` (or `json(...)` from `@sveltejs/kit`).
- `+error.svelte` — the error page for that subtree; `src/error.html` is the fallback when even the root layout fails.
- `src/hooks.server.ts` — `handle({ event, resolve })` wraps every request (auth, headers, locals), `handleFetch` rewrites server-side `fetch`, `handleError` is the reporting hook. `src/hooks.client.ts` has the client `handleError`. `src/hooks.ts` (universal) has `reroute`/`transport` in recent versions.
- `src/app.html` — the root document template, where `<html lang>`, analytics snippets, and `%sveltekit.head%` live.
- `src/lib/**` — aliased as `$lib`; `src/lib/server/**` is aliased as `$lib/server` and importing it from client code is a build error.

Params are `[id]`, optional `[[lang]]`, rest `[...path]`, matchers `[id=integer]` defined in `src/params/`. Route groups `(app)`, `(marketing)` do not affect the URL and are the usual marker for an authenticated area. Page-level options are module-level exports: `prerender`, `ssr`, `csr`, `trailingSlash`, `config`.

To enumerate routes: `find src/routes -name '+page.svelte' -o -name '+server.ts' -o -name '+page.server.ts'`, and read the route list printed by `npm run build`.

## auth
No auth ships with SvelteKit; the idiomatic shape is a session read in `src/hooks.server.ts`:

```ts
// src/hooks.server.ts
export const handle = async ({ event, resolve }) => {
  const token = event.cookies.get('session')
  event.locals.user = token ? await validateSession(token) : null
  return resolve(event)
}
```

`event.locals` is then read by every `+page.server.ts` load, every form action, and every `+server.ts` handler. **Populating `locals` is not a guard.** The check to make is that each protected surface calls it and returns early:

```ts
// src/routes/(app)/+layout.server.ts  — guards child *pages*
export const load = async ({ locals, url }) => {
  if (!locals.user) redirect(303, `/login?redirectTo=${url.pathname}`)
  return { user: { id: locals.user.id, email: locals.user.email } }
}
```

The trap that follows from this: a `+layout.server.ts` guard covers the pages beneath it because their loads run in the same chain, but **`+server.ts` endpoints do not run layout loads at all**, so an API route inside a guarded group is unprotected unless it checks `locals` itself (SEC-010). Form actions are the same — each `action` is a public POST endpoint and needs its own check.

Libraries you will see: `@auth/sveltekit` (Auth.js — `SvelteKitAuth` in `hooks.server.ts`, `event.locals.auth()`, providers array, `AUTH_SECRET`), Lucia (hand-rolled sessions in a `session` table with a `validateSessionToken` helper — Lucia v3 was a library, later versions are a documented pattern, so expect the code in `src/lib/server/auth.ts`), `@supabase/ssr` (`createServerClient` in `hooks.server.ts` with `cookies.getAll`/`setAll`, then `safeGetSession()` calling `getUser()` — never trust `getSession()` alone for authorization), and Clerk's SvelteKit SDK. Cookies are set with `cookies.set(name, value, { path: '/', httpOnly: true, secure: true, sameSite: 'lax' })` — SvelteKit 2 requires an explicit `path`.

## webhook handlers
`src/routes/api/webhooks/<provider>/+server.ts` exporting `POST`. The raw body is `await request.text()`; SvelteKit does not parse the body for you, so nothing is consumed before you ask — but calling `await request.json()` first consumes the stream and a later `request.text()` throws, which is how a handler ends up unable to verify (SEC-051). Webhook routes must not sit behind a `handle` hook that redirects unauthenticated requests, and they are legitimately exempt from CSRF: add the path to `kit.csrf` handling or make sure the origin check does not reject a provider POST (webhooks send no `Origin` header, which SvelteKit's check allows, but a custom check may not).

## webhook verification snippet
```ts
// src/routes/api/webhooks/stripe/+server.ts
import Stripe from 'stripe'
import { error, json } from '@sveltejs/kit'
import { STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET } from '$env/static/private'
import type { RequestHandler } from './$types'

const stripe = new Stripe(STRIPE_SECRET_KEY)

export const POST: RequestHandler = async ({ request }) => {
  const sig = request.headers.get('stripe-signature')
  const raw = await request.text() // raw first; never request.json() before this
  if (!sig) error(400, 'missing signature')

  let event: Stripe.Event
  try {
    event = stripe.webhooks.constructEvent(raw, sig, STRIPE_WEBHOOK_SECRET)
  } catch {
    error(400, 'bad signature')
  }
  // handle event.type ...
  return json({ received: true })
}
```
For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
The server-only boundary is `src/lib/server/**`: SvelteKit refuses to build if client-reachable code imports anything under it, so the DB client belongs there — `src/lib/server/db.ts`, `src/lib/server/db/schema.ts`, `src/lib/server/supabase.ts`. Schema and policies belong to the data stack: `drizzle/` or `src/lib/server/db/schema.ts` plus `drizzle.config.ts` and generated SQL, `prisma/schema.prisma`, `supabase/migrations/*.sql`. `.env`'s `DATABASE_URL` is read through `$env/static/private` or `$env/dynamic/private`.

Query from `+page.server.ts` loads, form actions, and `+server.ts` handlers only. A `+page.ts` universal load runs in the browser too, so a query there either fails to build or ships the credentials.

**Payload trap:** everything a server load returns is serialized into the HTML (`__sveltekit_*` / the hydration payload) and is readable in the browser regardless of what the template renders. Returning a whole user row publishes its password hash, its Stripe customer id, and every internal flag on it. Return an explicit, narrow shape. The same applies to a form action's return value.

## file uploads
Form actions and `+server.ts` handlers reading `await request.formData()` and pulling `File` objects out of it; check `file.size`, `file.type`, and re-derive the type from magic bytes rather than trusting the client. Direct-to-storage presigned uploads (S3, Supabase Storage, R2) are common and bypass the server entirely.

Size limits: adapter-node enforces `BODY_SIZE_LIMIT` (a default in the low hundreds of kilobytes — check the adapter version's docs for the exact number and set it explicitly rather than relying on it); serverless adapters inherit the platform's request-body ceiling, which is smaller than most people expect — read the deploy platform's stack file. SvelteKit has no image optimizer of its own; projects use `@sveltejs/enhanced-img` (build-time, local files only, no remote-host allowlist to get wrong), `unpic`, or an external CDN whose allowlist lives at the CDN.

## background jobs
Nothing built in. Look for: a platform cron (`vercel.json` `crons`, a Netlify scheduled function, a Cloudflare cron trigger, a Fly machine schedule) hitting a `+server.ts` route; Inngest, Trigger.dev, or QStash; a separate worker process (BullMQ, a `worker.ts` started by the Procfile or compose file) importing the same `src/lib/server` modules. A cron-triggered endpoint must authenticate its caller with a shared bearer secret checked in the handler (SEC-014); a `+server.ts` route named `/api/cron/*` with no check is callable by anyone. Email sends are usually inline in an action or load (`src/lib/server/email.ts` wrapping Resend, Postmark, SendGrid, or nodemailer), which makes the request as slow and as failure-prone as the provider.

## error handling and logging
`+error.svelte` renders the nearest error boundary and reads `page.error` (`$page.error` in Svelte 4); `src/error.html` is the last-resort template with `%sveltekit.status%` and `%sveltekit.error.message%`. `error(status, message)` from `@sveltejs/kit` throws an *expected* error whose message **is** sent to the client — putting a database or upstream message in there leaks it (SEC-009). An unexpected thrown error is scrubbed to a generic "Internal Error" for the client, and passed to `handleError`.

`handleError` in `src/hooks.server.ts` is both the reporting hook and a leak vector: **its return value becomes `page.error` in the browser**, so returning `{ message: err.message }` or anything carrying a stack undoes the scrubbing. Report to Sentry there and return a safe shape:

```ts
export const handleError = async ({ error, event, status, message }) => {
  Sentry.captureException(error, { extra: { url: event.url.pathname } })
  return { message: 'Something went wrong' } // never error.message or error.stack
}
```

`@sentry/sveltekit` provides `sentryHandle()` (compose it into `handle` with `sequence`) and `handleErrorWithSentry()`, plus a Vite plugin for source-map upload. Both `hooks.server.ts` and `hooks.client.ts` need initialising. Request logging is normally a `console.log` inside `handle` to the platform stream.

## security headers
Set them in `src/hooks.server.ts` around `resolve`:

```ts
export const handle = async ({ event, resolve }) => {
  const response = await resolve(event)
  response.headers.set('X-Content-Type-Options', 'nosniff')
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin')
  return response
}
```

CSP specifically has first-class support: `kit.csp` in `svelte.config.js` with `mode: 'auto' | 'hash' | 'nonce'` and `directives` / `reportOnly` — SvelteKit then hashes or nonces its own inline scripts, which hand-written CSP usually breaks. `kit.csrf.checkOrigin` (default true) is the built-in cross-origin form-POST defence. HSTS and the rest are often set at the platform instead (`vercel.json` `headers`, `netlify.toml`, `static/_headers`, nginx). `X-Robots-Tag` for an authenticated area goes in the same `handle` hook, or per-page with a `<svelte:head><meta name="robots" content="noindex"></svelte:head>`.

## known traps
- A secret in a `PUBLIC_`-prefixed variable, or read through `import.meta.env.VITE_*`: SEC-003. Check `kit.env.publicPrefix` before assuming the prefix.
- `{@html ...}` with user or CMS content without sanitization: SEC-043.
- `build.sourcemap: true` in `vite.config`, or an adapter/Sentry plugin that uploads maps but also leaves them served: SEC-007.
- A `+server.ts` endpoint inside a guarded route group: layout loads do not run for endpoints, so it is unprotected (SEC-010, SEC-012).
- A form action with no `locals.user` check: it is a public POST endpoint (SEC-010).
- Authorization done in `+page.ts` (universal load) instead of `+page.server.ts`: it runs in the browser and can be skipped (SEC-010).
- `export const prerender = true` on a page whose load reads a session: one user's data is baked into HTML (SEC-011).
- `setHeaders({ 'cache-control': 'public, max-age=...' })` in a load returning per-user data, or a CDN rule doing the same: SEC-036.
- `redirect(303, url.searchParams.get('redirectTo'))` without an allowlist: SEC-029.
- No image optimizer ships with SvelteKit, so SEC-045's remote-host allowlist question is usually "not applicable — no image proxy". It becomes applicable if the project added one: a `+server.ts` route that fetches a URL from a query parameter and re-serves it is an open proxy, and an external image CDN moves the allowlist to that CDN's config.
- `csrf: { checkOrigin: false }` in `svelte.config.js`: disables the built-in cross-origin POST defence for every form action (SEC).
- A full DB row returned from a load or action: serialized into the page payload and public (SEC-003, DAT).
- `cookies.set` without `path: '/'`: SvelteKit 2 requires it, and a missing or wrong path silently scopes the session to one route.
- adapter-node behind a proxy without `ORIGIN` set: form POSTs fail the origin check in production but not locally.
- Preview or branch deployments inheriting production env unless scoped per environment: DAT-017.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if already in devDependencies; never install one for the audit.

## runtime probe hints
**Session cookie for `curl`.** Log in through the app's own endpoint and keep the jar. Note that SvelteKit form actions are posted as form-encoded to `?/<action>`, not as JSON:
```bash
# sign up a throwaway identity through the app's own form action
curl -s -c .pre-launch/flows/cookies.txt -X POST 'http://localhost:3100/signup?/default' \
  -H 'origin: http://localhost:3100' \
  --data-urlencode "email=qa+$(date +%s)@example.com" \
  --data-urlencode 'password=<from credentials_env>' -i
# or a JSON API route, if the project has one
curl -s -c .pre-launch/flows/cookies.txt -X POST http://localhost:3100/api/login \
  -H 'content-type: application/json' -d '{"email":"...","password":"..."}' -i
# reuse
curl -s -b .pre-launch/flows/cookies.txt http://localhost:3100/dashboard -o /dev/null -w '%{http_code}\n'
```
The `origin` header matters: with `csrf.checkOrigin` on (the default), a cross-origin form POST is rejected with 403, and a probe that forgets the header will read that as a broken sign-up. Find the real action name from `src/routes/**/+page.server.ts` (`export const actions = { ... }`) before writing the URL.

**Cookie names.** No framework default — grep for it: `grep -rn "cookies.set(" src/`. Common values: `session`, `sessionid`, `auth_session` (the Lucia convention), `@auth/sveltekit` uses the Auth.js names `authjs.session-token` / `next-auth.session-token` with a `__Secure-` prefix over HTTPS, `@supabase/ssr` uses `sb-<project-ref>-auth-token` and may chunk it as `.0` / `.1` — send every chunk.

**Health path.** No convention. Look for `src/routes/health/+server.ts`, `src/routes/healthz/+server.ts`, or `src/routes/api/health/+server.ts`. If none exists, use the cheapest static page for cold-start timing and say which you used.

**Not-found behaviour.** An unmatched path renders the nearest `+error.svelte` with status 404, or `src/error.html` if no error page exists. `error(404)` in a load does the same. Check the status code and not just the body: a `[...path]` catch-all rendering a "not found" message with status 200 is a soft 404 (SEO).

**Test-mode provider keys.** Read the environment of the running process first (`printenv | grep -i stripe`), then `.env.local` and `.env` — `$env/static/*` values are baked in at build time, so a key changed after the build is not the one in use; rebuild if you change it. Stripe `sk_test_` / `pk_test_` / `rk_test_` and a `whsec_` from `stripe listen`; PayPal on `api-m.sandbox.paypal.com`; Paddle, Lemon Squeezy, RevenueCat a sandbox host, flag, or key. Published test card numbers live in the payment provider's own stack file. If the classification is ambiguous, treat the keys as live and stop.

**Local mail catcher.** None ships with SvelteKit. Check `docker-compose.yml` / `compose.yaml` for `axllent/mailpit` (SMTP `1025`, HTTP `8025`, `curl -s http://localhost:8025/api/v1/messages`), `mailhog/mailhog` (API `/api/v2/messages` on `8025`), or `inbucket/inbucket`; a Supabase local stack runs Inbucket on `54324` (`curl -s http://localhost:54324/api/v1/mailbox/<mailbox>`). Otherwise read the mail env: `SMTP_HOST=localhost` with port `1025` means a catcher is expected, and `RESEND_API_KEY` / `POSTMARK_*` / `SENDGRID_*` in test mode means the "inbox" is the provider's test-mode log or the app's own log line. No reachable catcher is `error: no mail capture`, never a pass.

**Throwaway identity.** Sign up through the app's own sign-up action with `qa+<unix-ts>@example.com` and the password from the config's `credentials_env`, as above; never reuse the shared test account where a check needs a second identity, and delete the rows the audit created afterwards.
