# Nuxt

## detection signals
`nuxt` in package.json dependencies and `nuxt.config.ts|js|mjs` at the root. Generated `.nuxt/` (dev types and build artefacts) and `.output/` (production server). The server half is Nitro (`nitropack`), so `server/api/`, `server/routes/`, and `server/middleware/` are the runtime surface even when the docs you find talk about Vue.

**Directory layout differs by major version and this changes every path below.** Nuxt 3 puts app code at the root: `pages/`, `components/`, `layouts/`, `composables/`, `middleware/`, `plugins/`, `app.vue`, `error.vue`. Nuxt 4 moves that set under `app/` (`app/pages/`, `app/components/`, `app/app.vue`, `app/error.vue`) while `server/`, `public/`, `content/`, and `modules/` stay at the root. `compatibilityVersion` in `nuxt.config` and the presence or absence of an `app/` directory tell you which you are in — check the installed version's docs rather than assuming, and search both roots before concluding a file does not exist.

## dev server
`npm run dev` (or `pnpm|yarn|bun dev` per lockfile) → `nuxt dev`. Default port 3000. Ready when `GET /` returns 200. Override with `--port`, `PORT=`, or `NUXT_PORT=`; `devServer.port` in `nuxt.config` also sets it. Never measure performance, headers, or analytics gating against the dev server — see "build".

## build
`npm run build` → `nuxt build` → `.output/`. Production start is `node .output/server/index.mjs`, which listens on `PORT` (default 3000) and `HOST`; `NITRO_PORT` is honoured too. So the production probe is `npm run build && PORT=3100 node .output/server/index.mjs`. `npm run preview` (`nuxt preview`) does the same thing with `.env` loaded, and is the convenient form.

`nuxt generate` (or `nuxt build` with `ssr: false` plus prerendering) produces a fully static site in `.output/public/` with no server — in that case there is no runtime auth, no server route, and most local-tier server checks are `skipped` with the reason "statically generated". Client bundles live under `.output/public/_nuxt/`; grep those for leaked secrets (SEC-003). The deploy target is chosen by the `NITRO_PRESET` env var or `nitro.preset` in `nuxt.config` (`node-server`, `vercel`, `netlify`, `cloudflare-pages`, `bun`) and it changes the output shape — read it before assuming `.output/server/index.mjs` exists.

## env vars
Two layers, and confusing them is the most common Nuxt finding.

`.env` (plus `.env.<mode>` via Vite) is read by `nuxt dev`, `nuxt build`, and `nuxt preview`. It is **not** read by the built server in production: `node .output/server/index.mjs` takes its environment from the process. So a variable that only exists in `.env` works locally and is undefined in production (REL-008).

`runtimeConfig` in `nuxt.config` is the typed layer. Top-level keys are server-only; keys under `runtimeConfig.public` are serialized into the page payload and readable in the browser. Values are overridden at runtime by environment variables with the `NUXT_` prefix, camelCase flattened to underscores: `runtimeConfig.apiSecret` ← `NUXT_API_SECRET`, `runtimeConfig.public.siteUrl` ← `NUXT_PUBLIC_SITE_URL`. Read them with `useRuntimeConfig()` — on the server it returns everything, in the browser only `public`. **`NUXT_PUBLIC_*` and anything under `runtimeConfig.public` is the public prefix: a secret there is a leak (SEC-003).**

`process.env.X` and `import.meta.env.X` referenced inside client-side code (a component, a composable, a plugin without `.server`) are inlined by Vite at build time and are equally public; `VITE_`-prefixed variables are the Vite convention and are public by definition. Files under `server/` are never bundled for the browser, so `process.env` there is safe. For payment test-mode detection read `NUXT_STRIPE_SECRET_KEY` / `STRIPE_SECRET_KEY` from the running process, then `.env`; the `sk_test_` / `pk_test_` prefix is the tell.

## routes and handlers
**Server (Nitro), always at the repo root regardless of major version:**
- `server/api/**` → mounted under `/api/`. `server/api/users.get.ts` → `GET /api/users`; the `.get`/`.post`/`.put`/`.delete` suffix is the method, no suffix means any method. `[id].ts` and `[...slug].ts` are params.
- `server/routes/**` → mounted at the root with no `/api` prefix. `server/routes/webhooks/stripe.post.ts` → `POST /webhooks/stripe`. This is where webhooks, `sitemap.xml`, and `robots.txt` usually live.
- `server/middleware/**` → runs on **every** request before the matched handler, in filename order. It cannot return a response body to short-circuit cleanly unless it throws (`throw createError({ statusCode: 401 })`) or sets `event.node.res` directly.
- `server/plugins/**` → Nitro lifecycle hooks (`nitroApp.hooks.hook('request', ...)`), `server/utils/**` → auto-imported server helpers.

Handlers are `export default defineEventHandler(async (event) => { ... })`. Read input with `readBody(event)`, `readRawBody(event)`, `getQuery(event)`, `getRouterParam(event, 'id')`, `getHeader(event, 'x-...')`, `getCookie(event, name)`; respond by returning a value (JSON-serialized), or with `setResponseStatus`, `setResponseHeader`, `sendRedirect(event, url, 302)`, `throw createError(...)`.

**App:** pages at `pages/**/*.vue` (`app/pages/**` on Nuxt 4) with file-based routing, `[id].vue`, `[...slug].vue`, and `index.vue`; the root component is `app.vue` and layouts are `layouts/default.vue` selected by `definePageMeta({ layout })`. Route middleware lives in `middleware/*.ts` — named middleware referenced by `definePageMeta({ middleware: 'auth' })`, or `middleware/auth.global.ts` which runs for every navigation. **Route middleware runs on the server for the first request and in the browser for every client-side navigation; it is a UX guard, not a security boundary** (SEC-010). The error page is `error.vue` at the app root. `<html lang>` is set through `app.head.htmlAttrs.lang` in `nuxt.config` or `useHead({ htmlAttrs: { lang } })`.

`routeRules` in `nuxt.config` is a per-path override layer that matters to several checks: it sets `prerender`, `ssr`, `swr`/`isr`/`cache`, `redirect`, `headers`, and `cors` per glob. Read it before trusting what a page component appears to do.

The AI/chat endpoint, when there is one, is a server route rather than a page — `server/api/chat.post.ts` is the convention, returning a stream. With the `ai` package it is `streamText(...).toDataStreamResponse()`; hand-rolled versions use h3's `sendStream(event, ...)` or an `EventStream` helper. Either way the response is server-sent events or the `ai` package's data-stream protocol, so a probe must read the whole stream and reassemble the text before judging it — the first chunk is not the answer.

To enumerate routes: `find server/api server/routes -type f` for the API surface, `find pages app/pages -name '*.vue'` for pages, and read the route table `nuxt build` prints. Nuxt also emits a generated route module (`.nuxt/routes.mjs` in current versions — a virtual module, not JSON) and `npx nuxi analyze` produces a build report; check the version's output rather than expecting a particular file.

## auth
Nuxt ships no auth. Identify the library first:
- **nuxt-auth-utils** — `server/api/auth/*.ts` calling `setUserSession(event, {...})`; server checks are `await requireUserSession(event)` or `getUserSession(event)`; client reads `useUserSession()`. Cookie is `nuxt-session` by default, sealed with `NUXT_SESSION_PASSWORD`.
- **@sidebase/nuxt-auth** — wraps Auth.js; config in `nuxt.config` `auth` plus `server/api/auth/[...].ts`; server check `getServerSession(event)`; Auth.js cookie names.
- **@nuxtjs/supabase** — `serverSupabaseUser(event)` / `serverSupabaseClient(event)` on the server, `useSupabaseUser()` in components; cookie `sb-<ref>-auth-token`. Use `serverSupabaseUser` (which revalidates) for authorization, never a decoded session.
- **Hand-rolled** — `getCookie(event, ...)` in `server/middleware/auth.ts` setting `event.context.user`, read by handlers.

The check to make: every `server/api/**` and `server/routes/**` handler that returns or mutates user data calls the session helper and throws or returns 401/403 before doing work. `event.context.user` being populated by `server/middleware` is not itself a guard — middleware that only annotates the event leaves every handler that forgets to read it open (SEC-010). OAuth providers are configured in the library's config or, for nuxt-auth-utils, as `NUXT_OAUTH_<PROVIDER>_CLIENT_ID` / `_CLIENT_SECRET` env pairs with a callback handler under `server/routes/auth/<provider>.get.ts`.

## webhook handlers
`server/routes/webhooks/<provider>.post.ts` (root-mounted, the usual choice) or `server/api/webhooks/<provider>.post.ts`. The raw body must be read with `readRawBody(event)` — it returns the body as a string by default, or a `Buffer` with `readRawBody(event, false)`. Calling `readBody(event)` first parses and caches the body, so a handler that parses before verifying cannot verify (SEC-051). Webhook paths must be exempted from any `server/middleware` that requires a session, and from `routeRules` redirects.

## webhook verification snippet
```ts
// server/routes/webhooks/stripe.post.ts
import Stripe from 'stripe'

export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  const stripe = new Stripe(config.stripeSecretKey)
  const sig = getHeader(event, 'stripe-signature')
  const raw = await readRawBody(event) // must come before any readBody()
  if (!sig || !raw) throw createError({ statusCode: 400, statusMessage: 'missing signature' })

  let stripeEvent: Stripe.Event
  try {
    stripeEvent = stripe.webhooks.constructEvent(raw, sig, config.stripeWebhookSecret)
  } catch {
    throw createError({ statusCode: 400, statusMessage: 'bad signature' })
  }
  // handle stripeEvent.type ...
  return { received: true }
})
```
For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
Depends on the data stack (supabase, prisma, drizzle, firebase). Clients live in `server/utils/db.ts` or `server/utils/supabase.ts` (auto-imported inside `server/`), sometimes `server/db/` or a `lib/` directory. Schema and policies belong to that stack: `prisma/schema.prisma`, `drizzle/schema.ts` plus generated SQL, `supabase/migrations/*.sql`.

The boundary is the `server/` directory: nothing under it reaches the browser. A composable in `composables/` or a plugin without a `.server.ts` suffix runs in both places, so a DB client imported there is a leak. Components fetch through `useFetch('/api/...')`, `useAsyncData`, or `$fetch`.

**Payload trap:** whatever `useAsyncData`/`useFetch` resolves on the server is serialized into the `__NUXT__` payload embedded in the HTML so the client can hydrate without refetching. Returning a full user or order row from a server route therefore publishes every column of it to the browser, even if the template renders only the name. `pick`/`transform` options on `useFetch`, or trimming the shape in the handler, are the fix.

## file uploads
Server routes reading `await readMultipartFormData(event)` (returns parts with `name`, `filename`, `type`, `data`) or `await readBody(event)` for a `FormData` post. Direct-to-storage uploads via a presigned URL from Supabase Storage, S3, or `@nuxthub/core` blob storage are common and bypass the server body limit.

`@nuxt/image` (`<NuxtImg>`, `<NuxtPicture>`) is configured under `image` in `nuxt.config`. The default `ipx` provider will fetch and re-serve remote URLs; `image.domains` is the allowlist for which remote hosts are permitted. An empty, wildcard, or absent allowlist combined with remote optimization makes the optimizer a proxy for arbitrary URLs (SEC-045). Note also `image.provider` when it points at a third-party CDN, since the allowlist then lives there instead.

Body size is bounded by Nitro's host, not by Nuxt: on a node server it is effectively memory, on a serverless preset it is the platform's request-body ceiling — read the deploy platform's stack file for the number.

## background jobs
No queue ships with Nuxt. Nitro has scheduled tasks (`server/tasks/**` with `defineTask`, scheduled via `nitro.scheduledTasks` in `nuxt.config`, and runnable with `runTask`), but they have been behind `experimental.tasks` and are preset-dependent — check the installed version's docs before treating a `server/tasks/` directory as a working scheduler, and note that most serverless presets cannot run them at all. In practice look for: a platform cron (`vercel.json` `crons`, a Netlify scheduled function, a Cloudflare cron trigger) hitting a `server/api/cron/*` route; Inngest, Trigger.dev, or QStash; a separate BullMQ worker process in the repo. A cron-triggered route must authenticate the caller — a shared bearer secret checked with `getHeader(event, 'authorization')` (SEC-014). Email sends are usually inline in a handler (`server/utils/email.ts` wrapping Resend, Postmark, SendGrid, or nodemailer), not queued.

## error handling and logging
`error.vue` at the app root renders any fatal error, receiving the error as a prop and using `clearError({ redirect })` to recover; `useError()` reads it. Handlers signal errors with `createError({ statusCode, statusMessage, message, data })`. **In production Nitro strips the detail from an error it did not expect — the stack, and the message of a plain thrown `Error` — while an error you built with `createError` is sent to the client as you wrote it, so putting a database message or an upstream response into its `message` or `data` leaks it (SEC-009).** The exact scrubbing rules differ across h3 and Nitro versions, so check the version's docs and, better, confirm it empirically: throw a test error from a scratch route in the production build and read what comes back. `nuxt.config` `debug: true` restores verbose errors and must not be on in production.

Reporting: `@sentry/nuxt` (adds `sentry.client.config.ts` and `sentry.server.config.ts` and a Nitro plugin), or manual init in `plugins/sentry.client.ts` plus `server/plugins/sentry.ts`. Both runtimes need initialising — the server half is the one usually missed. App-level Vue errors can also be trapped with `vueApp.config.errorHandler` in a client plugin and the `vue:error` / `app:error` hooks. Nitro's own hooks (`error`, `request`, `afterResponse`) in `server/plugins/*.ts` are the place for request logging; otherwise it is `console.log` to the platform stream.

## security headers
Three places, in order of how often they are used:
- **`nuxt-security`** module — sets a broad default header set (CSP, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, cross-origin policies) plus rate limiting and CSRF; configured under `security` in `nuxt.config`, and overridable per route via `routeRules[path].security`. Its defaults change between versions, so read the resolved headers from a live response rather than from the module docs.
- **`routeRules`** in `nuxt.config`: `routeRules: { '/**': { headers: { 'strict-transport-security': '...' } } }`.
- **`server/middleware/*.ts`** calling `setResponseHeader(event, ...)`, or the platform (`vercel.json`, `netlify.toml`, `public/_headers`, nginx).

`X-Robots-Tag` for an authenticated area is set the same way; per-page noindex is `useHead({ meta: [{ name: 'robots', content: 'noindex' }] })` or `routeRules`.

## known traps
- `runtimeConfig.public` / a `NUXT_PUBLIC_*` env var holding a secret, or `process.env.X` read in a component: SEC-003.
- `v-html` with user or CMS content without sanitization: SEC-043.
- `sourcemap.client: true` (or `vite.build.sourcemap`) in `nuxt.config` ships source maps: SEC-007.
- Route middleware in `middleware/` used as the only auth guard: it runs in the browser and every `server/api` route stays open (SEC-010, SEC-012).
- `server/middleware` that sets `event.context.user` but does not throw: handlers that forget to check are unprotected (SEC-010).
- `routeRules` with `swr`, `isr`, `cache`, or a `cache-control` header on a path that returns per-user data: one user's response is served to the next (SEC-036).
- `routeRules` with `prerender: true`, or `nuxt generate`, on a page that reads a session: the first user's data is baked into HTML (SEC-011).
- `ssr: false` turns the app into a SPA: every guard that appears to run server-side does not, and all data comes from `server/api` routes that must each be protected (SEC-010).
- A full DB row returned from a server route and hydrated into the `__NUXT__` payload: every column is public whatever the template renders (SEC-042, and SEC-003 if the row holds a credential).
- `@nuxt/image` with no `image.domains` allowlist while optimizing remote URLs: SEC-045.
- `navigateTo(route.query.redirect)` or `sendRedirect(event, getQuery(event).next)` without an allowlist: SEC-029. `navigateTo` with `external: true` on a user-supplied URL is the same bug.
- `.env` assumed to be read in production: it is not read by `node .output/server/index.mjs` (REL-008).
- Preview or branch deployments inheriting production env unless scoped per environment: DAT-017.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if already in devDependencies; never install one for the audit. Cited by the accessibility and compliance domain headers, COMP-007, and FLOW-018.

## runtime probe hints
**Session cookie for `curl`.** Log in through the app's own route and keep the jar:
```bash
# sign up a throwaway identity via the app's own handler
curl -s -c .pre-launch/flows/cookies.txt -X POST http://localhost:3100/api/auth/signup \
  -H 'content-type: application/json' \
  -d '{"email":"qa+'"$(date +%s)"'@example.com","password":"<from credentials_env>"}' -i
# or log in
curl -s -c .pre-launch/flows/cookies.txt -X POST http://localhost:3100/api/auth/login \
  -H 'content-type: application/json' -d '{"email":"...","password":"..."}' -i
# reuse
curl -s -b .pre-launch/flows/cookies.txt http://localhost:3100/api/me
```
Find the real handler paths from "routes and handlers" first (`find server/api server/routes -path '*auth*'`), since the route names are the project's own. If sign-up is a client-side form posting through a composable, drive it with the project's existing browser driver and say so.

**Cookie names.** nuxt-auth-utils `nuxt-session`; @sidebase/nuxt-auth uses Auth.js names (`authjs.session-token` / `next-auth.session-token`, `__Secure-` prefixed over HTTPS); @nuxtjs/supabase `sb-<project-ref>-auth-token`, sometimes chunked as `.0` / `.1` — send every chunk; hand-rolled sessions use whatever `setCookie(event, <name>, ...)` says, commonly `session` or `sid`. `grep -rn "setCookie(event" server/` finds it.

**JWT for API probes.** A cookie is not always the credential. DAT-002's RLS probe and the AI domain's per-user retrieval checks call the data API directly as the user, which needs `Authorization: Bearer <jwt>` — and that is **Supabase-specific**, because PostgREST is what makes a per-user bearer probe possible. With any other auth library there is no equivalent surface: record `n/a — no PostgREST surface` for the bearer half and rely on the cookie probes above.

On Supabase, two ways to get the token. The `@nuxtjs/supabase` module reads `SUPABASE_URL` and `SUPABASE_KEY`, while a project wiring the client through `runtimeConfig` will have them as `NUXT_PUBLIC_SUPABASE_URL` / `NUXT_PUBLIC_SUPABASE_KEY` — grep for both before assuming a name. Sign in against the auth API and read `access_token` straight out of the response, which is the reliable one:
```bash
curl -s -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_KEY" -H 'content-type: application/json' \
  -d '{"email":"...","password":"..."}' | jq -r .access_token
```
Or lift it from the cookie the app already set: `sb-<project-ref>-auth-token` holds a base64-encoded JSON session object, chunked across `.0` / `.1` when it is large, and the JWT is its `access_token` field:
```bash
echo "<the chunk values joined in order>" | sed 's/^base64-//' | base64 -d | jq -r .access_token
```
Check the cookie's shape in this version before trusting that pipeline — the `base64-` prefix and the chunking were not always there, and older releases stored the JSON directly. Then probe with both headers, since PostgREST wants the `apikey` as well as the bearer:
```bash
curl -s "$SUPABASE_URL/rest/v1/<table>?select=*" -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer <jwt>"
```
For the other libraries, so you do not waste time looking: an Auth.js session cookie is either an encrypted JWE (the JWT strategy — not readable by you and not a bearer token for anything) or an opaque database session id; Clerk's `__session` is a JWT but is meant to be verified by Clerk's backend SDK, not replayed at a data API; Lucia and hand-rolled sessions are opaque ids. In all of those the cookie is the only credential the audit can use.

**Health path.** No convention. Look for `server/api/health.ts`, `server/api/healthz.ts`, `server/routes/health.ts`, or a `_health` route. If none exists, use the cheapest static page for cold-start timing and say which you used.

**Not-found behaviour.** An unmatched path renders `error.vue` with status 404 (Nitro returns a JSON error for `/api/*` paths instead of the HTML page). `throw createError({ statusCode: 404 })` in a page or handler does the same. Check the status code, not just the body: a `[...slug].vue` catch-all rendering a "not found" message with status 200 is a soft 404 (SEO) unless it also calls `setResponseStatus(404)`.

**Test-mode provider keys.** Read the environment of the running process (`printenv | grep -i stripe`) rather than `.env` alone, because the built server ignores `.env`. Stripe `sk_test_` / `pk_test_` / `rk_test_` and a `whsec_` issued by `stripe listen`; PayPal pointing at `api-m.sandbox.paypal.com`; Paddle, Lemon Squeezy, RevenueCat a sandbox host, flag, or key. Note that a value may arrive as `NUXT_STRIPE_SECRET_KEY` (the runtimeConfig override) rather than `STRIPE_SECRET_KEY` — grep for both. Published test card numbers live in the payment provider's own stack file. If the classification is ambiguous, treat the keys as live and stop.

**Local mail catcher.** None ships with Nuxt. Check `docker-compose.yml` / `compose.yaml` for `axllent/mailpit` (SMTP `1025`, HTTP `8025`, `curl -s http://localhost:8025/api/v1/messages`), `mailhog/mailhog` (API `/api/v2/messages` on `8025`), or `inbucket/inbucket`; a Supabase local stack runs Inbucket on `54324` (`curl -s http://localhost:54324/api/v1/mailbox/<mailbox>`). Otherwise read the mail env: `SMTP_HOST=localhost` with port `1025` means a catcher is expected, and `RESEND_API_KEY` / `POSTMARK_*` / `SENDGRID_*` in test mode means the "inbox" is the provider's test-mode log or the app's own log line. No reachable catcher is `error: no mail capture`, never a pass.

**Throwaway identity.** Sign up through the app's own route with `qa+<unix-ts>@example.com` and the password from the config's `credentials_env`, as above; never reuse the shared test account where a check needs a second identity, and delete the rows the audit created afterwards.
