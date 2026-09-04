# Next.js

## detection signals
`next` in package.json dependencies. App Router if `app/` exists with `layout.tsx|jsx`; Pages Router if `pages/` exists. Both may coexist. Config at `next.config.js|mjs|ts`. Either directory may sit under `src/` (`src/app/`, `src/pages/`) — check both before concluding a route does not exist. Build output `.next/`.

## dev server
`npm run dev` (or `pnpm dev` / `yarn dev` / `bun dev` per lockfile). Default port 3000. Ready when `GET /` returns 200. Override port with `PORT=` or `-p`. Never measure performance, headers, or analytics gating against the dev server — see "build".

## build
`npm run build` → `.next/`. Production start: `npm run build && PORT=3100 npm start` (`next start`), which serves the production build on `PORT` (default 3000). `next start` does not work with `output: 'export'` (fully static — serve `out/` with any static server) and is unnecessary with `output: 'standalone'`, where `node .next/standalone/server.js` is the entry point and `.next/static` plus `public/` must be copied alongside it. Client bundles under `.next/static/chunks/`; grep those for leaked secrets (SEC-003). Build-time env is baked in, so a rebuild is required after changing any `NEXT_PUBLIC_` value. `next build` fails on type and lint errors unless `typescript.ignoreBuildErrors` or `eslint.ignoreDuringBuilds` is set in `next.config.*` — note either, they hide real defects.

## env vars
Loaded from `.env`, `.env.local`, `.env.production`, `.env.development` in that precedence (`.env.local` overrides `.env`; `.env.production` applies when `NODE_ENV=production`; `.env.local` is not loaded in the `test` environment). Server reads `process.env.X`. Anything prefixed `NEXT_PUBLIC_` is inlined into the client bundle at build time: a `NEXT_PUBLIC_` variable holding a secret is a leak (SEC-003). Runtime env on the server is fine; on the client only `NEXT_PUBLIC_` exists. `next.config.*` also has an `env` key that inlines values the same way — treat it as a second public prefix. Import `server-only` at the top of a module to make an accidental client import a build error. Platform env (Vercel, Netlify, Fly) overrides the files at runtime and is scoped per environment: read the platform's stack file for whether preview inherits production (DAT-017). For payment test-mode detection, read `STRIPE_SECRET_KEY` / `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` out of `.env.local` first, then `.env` — the `sk_test_` / `pk_test_` prefix is the tell.

## routes and handlers
App Router: pages at `app/**/page.tsx`; API at `app/**/route.ts` exporting `GET|POST|...`; server actions are functions with `'use server'` in `app/**/*.ts(x)` or `actions.ts` files; middleware at `middleware.ts` (root or `src/`) with a `matcher` config. Pages Router: pages at `pages/**/*.tsx`, API at `pages/api/**/*.ts` default-exporting a handler. Not-found page: `app/not-found.tsx` or `pages/404.tsx`. Error boundaries: `app/**/error.tsx`, `app/global-error.tsx`. Root layout `app/layout.tsx` or `pages/_app.tsx` (with `pages/_document.tsx` for the `<html>` tag and head) is where global scripts, analytics, and consent gating live; the `<html lang>` attribute is set there. Forms are usually in `components/` and call server actions or `fetch('/api/...')`. Route groups `app/(dashboard)/**` do not affect the URL but are the usual marker for an authenticated area. `app/sitemap.ts`, `app/robots.ts`, and `app/opengraph-image.tsx` are generated routes. Streaming AI endpoints are normally `app/api/chat/route.ts` returning a `ReadableStream` or the `ai` package's `toDataStreamResponse()`. To enumerate every route quickly: `find app pages src/app src/pages -name 'page.tsx' -o -name 'route.ts' -o -name '*.tsx' -path '*pages/*' 2>/dev/null`, or read the route manifest at `.next/server/app-paths-manifest.json` and `.next/routes-manifest.json` after a build.

## auth
Session is read server-side via the auth library: Auth.js `auth()` / `getServerSession()`, Clerk `auth()` / `currentUser()`, Supabase `createServerClient(...).auth.getUser()` (never trust `getSession()` on the server for authorization). A protected route or action must call one of these and return 401/403 or redirect before doing work. Middleware protects paths only if the `matcher` covers them; a route outside the matcher is unprotected even if middleware exists (SEC-010). Server actions are public HTTP endpoints: each needs its own auth check (SEC-010, known traps). Config lives at `auth.ts` / `auth.config.ts` (Auth.js v5), `app/api/auth/[...nextauth]/route.ts` (Auth.js), `middleware.ts` with `clerkMiddleware()` (Clerk), or `utils/supabase/server.ts` + `middleware.ts` (Supabase). OAuth providers are listed in that config's `providers` array; their client id/secret pairs are the `AUTH_<PROVIDER>_ID` / `GOOGLE_CLIENT_ID`-style env vars. Cookie options are set by the library, overridable via `cookies` in the Auth.js config or `cookieOptions` in the Supabase client.

## webhook handlers
`app/api/webhooks/**/route.ts` or `pages/api/webhooks/**.ts`. Must read the raw body: App Router `await req.text()`; Pages Router needs `export const config = { api: { bodyParser: false } }` and a raw-body read. A handler that calls `req.json()` before verification cannot verify (SEC-051). Webhook routes are legitimately exempt from CSRF and must be excluded from any middleware `matcher` that redirects unauthenticated requests, or the provider gets a 302 and retries forever.

## webhook verification snippet
```ts
// app/api/webhooks/stripe/route.ts
import Stripe from 'stripe'
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!)
export async function POST(req: Request) {
  const sig = req.headers.get('stripe-signature')
  if (!sig) return new Response('missing signature', { status: 400 })
  let event: Stripe.Event
  try {
    event = stripe.webhooks.constructEvent(await req.text(), sig, process.env.STRIPE_WEBHOOK_SECRET!)
  } catch { return new Response('bad signature', { status: 400 }) }
  // handle event.type ...
  return new Response('ok')
}
```
For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
Depends on the data stack (supabase, prisma, drizzle, firebase). Look in `lib/db*`, `lib/supabase*`, `server/`, `db/`, or `utils/supabase/`. Schema and policies live with that stack: `prisma/schema.prisma`, `drizzle/schema.ts` plus `drizzle/*.sql`, `supabase/migrations/*.sql`. Server components and route handlers may query directly; client components must go through routes or actions. Direct DB calls from a file without `'use server'` or under `app/**/page.tsx` marked `'use client'` are a bug. Anything a server component passes as a prop to a client component, and anything a server action returns, is serialized into the HTML payload and readable in the browser — returning a whole user row leaks its columns.

## file uploads
Route handlers reading `req.formData()`, `next-s3-upload`, UploadThing (`app/api/uploadthing`), Vercel Blob (`@vercel/blob`), or Supabase Storage client uploads. `next.config.*` `images.remotePatterns` controls which hosts `next/image` will proxy; `hostname: '**'` makes the image optimizer an open proxy (SEC-045, known traps). Body size for a route handler is bounded by the platform, not by Next (`api.bodyParser.sizeLimit` caps Pages Router API routes; App Router route handlers have no framework cap) — see the deploy platform's stack file for the real ceiling, and prefer a presigned direct-to-storage upload, which bypasses it.

## background jobs
No built-in queue. Look for Vercel Cron (`vercel.json` `crons` → `app/api/cron/**`), Inngest, Trigger.dev, QStash, or BullMQ. Vercel cron routes must check `Authorization: Bearer ${CRON_SECRET}` (SEC-014). Long work inside a route handler is bounded by the platform timeout (PERF-020, see vercel stack ref); `export const maxDuration = <seconds>` raises it up to the plan's ceiling. Email sending is usually inline in a route or action (Resend, Postmark, SendGrid clients in `lib/email*` or `emails/`) rather than queued — note that, since an inline send makes the request as slow and as failure-prone as the provider.

## error handling and logging
`error.tsx` boundaries per segment; `global-error.tsx` for the root; `app/not-found.tsx` for 404s. Route handlers should catch and return JSON errors without stack traces; in production Next.js hides server error details by default, but custom `catch` blocks that return `err.message` or `err.stack` leak (SEC-009). Sentry via `@sentry/nextjs` with `sentry.client.config.ts`, `sentry.server.config.ts`, `sentry.edge.config.ts` and `instrumentation.ts` — all four runtimes (client, node server, edge/middleware, and any worker) need initialising, and edge is the one usually missed (REL). `instrumentation.ts` also exports `onRequestError` in recent versions. Structured logging is normally `console.log` straight to the platform log stream unless `pino`/`winston` is present.

## security headers
`next.config.*` `headers()` returning a `source: '/(.*)'` entry with `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options` or CSP `frame-ancestors`, `Referrer-Policy`, `Permissions-Policy`. Or `middleware.ts` setting them on the response (the usual place for a nonce-based CSP). Or the platform (`vercel.json` `headers`, `netlify.toml`, `public/_headers`). `poweredByHeader: false` in `next.config.*` removes `X-Powered-By`. `X-Robots-Tag` for noindexing an authenticated area is set the same way, or per-route with `export const metadata = { robots: { index: false } }`.

## known traps
- Server actions are callable by anyone who can reach the site; missing auth inside the action is SEC-010.
- `middleware.ts` `matcher` gaps leave routes unprotected: SEC-010, SEC-012.
- `NEXT_PUBLIC_` on a secret, or the same value under `next.config.*` `env`: SEC-003.
- `images.remotePatterns` with `hostname: '**'` or `domains` too broad: SEC-045.
- `dangerouslySetInnerHTML` with user or CMS content without sanitization: SEC-043.
- `productionBrowserSourceMaps: true` ships source maps: SEC-007.
- `export const dynamic = 'force-static'` on a page that reads session: serves one user's data to everyone (SEC-011).
- Route handlers with `export const revalidate`, or `Cache-Control: public` set by hand, on authenticated responses: SEC-036. `fetch(url, { cache: 'force-cache' })` on a per-user upstream is the same bug one layer down.
- `redirect(searchParams.next)` without an allowlist: SEC-029.
- Supabase `getSession()` on the server for authorization decisions: SEC-010 (use `getUser()`).
- Preview deployments inherit production env unless scoped per environment: DAT-017.
- `typescript.ignoreBuildErrors` / `eslint.ignoreDuringBuilds` in `next.config.*`: the build passes while the code does not compile cleanly.
- A server component prop or server-action return value carrying a full DB row: it is serialized into the page payload (SEC-003, DAT).
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if already in devDependencies; never install one for the audit.

## runtime probe hints
**Session cookie for `curl`.** Prefer the app's own endpoints over the library's internals. Keep a cookie jar and reuse it for every probe:
```bash
# 1. sign up a throwaway identity through the app's own route
curl -s -c .pre-launch/flows/cookies.txt -X POST http://localhost:3100/api/auth/signup \
  -H 'content-type: application/json' \
  -d '{"email":"qa+'"$(date +%s)"'@example.com","password":"<from credentials_env>"}' -i
# 2. or log in and keep the Set-Cookie
curl -s -c .pre-launch/flows/cookies.txt -X POST http://localhost:3100/api/auth/login \
  -H 'content-type: application/json' -d '{"email":"...","password":"..."}' -i
# 3. reuse
curl -s -b .pre-launch/flows/cookies.txt http://localhost:3100/dashboard -o /dev/null -w '%{http_code}\n'
```
Route names vary — find the real sign-up and login handlers from "routes and handlers" first; a credentials login on Auth.js is `POST /api/auth/callback/credentials` and needs the CSRF token from `GET /api/auth/csrf` posted alongside it, which is why the app's own route is easier when one exists. If the form is client-rendered and posts through a server action, drive it with the project's existing browser driver instead and say so.

**Cookie names.** Auth.js/NextAuth `authjs.session-token` or `next-auth.session-token`, prefixed `__Secure-` over HTTPS (and `__Host-`/`__Secure-` for the CSRF and callback cookies); Clerk `__session` plus `__client_uat`; Supabase `sb-<project-ref>-auth-token`, often split across `sb-<ref>-auth-token.0` / `.1` chunks — send all chunks or the session will not resolve; Lucia and hand-rolled sessions use whatever `cookies().set(<name>, ...)` says, commonly `session` or `sid`.

**Health path.** No convention. Look for `app/api/health/route.ts`, `app/api/healthz/route.ts`, `pages/api/health.ts`. If none exists, use the cheapest static page for cold-start timing and say which you used.

**Not-found behaviour.** Any unmatched path renders `app/not-found.tsx` (or `pages/404.tsx`) with status 404; `notFound()` called inside a page or handler does the same. A project with neither file still returns 404 with the built-in page. Check the status code and not just the body: a catch-all route (`app/[...slug]/page.tsx`) that renders a "not found" message with status 200 is a soft 404 (SEO).

**Test-mode provider keys.** Read the env the running process actually uses, in precedence order `.env.local` then `.env.production` then `.env`; a platform-injected value beats all of them, so if the app is running check `printenv` in that shell rather than the files alone. Stripe `sk_test_` / `pk_test_` / `rk_test_` and a `whsec_` from `stripe listen` rather than the dashboard; PayPal `PAYPAL_API_BASE` pointing at `api-m.sandbox.paypal.com`; Paddle and Lemon Squeezy a `sandbox` flag or host; RevenueCat a sandbox key. Published test card numbers live in the payment provider's own stack file, not here. If the classification is ambiguous, treat the keys as live and stop.

**Local mail catcher.** Next ships none. Check `docker-compose.yml` / `compose.yaml` for an `axllent/mailpit` service (SMTP `1025`, HTTP UI and API on `8025`, `curl -s http://localhost:8025/api/v1/messages`), `mailhog/mailhog` (same ports, API `/api/v2/messages`), or `inbucket/inbucket`; a Supabase local stack (`supabase/config.toml`, `supabase start`) runs Inbucket on `54324` (`curl -s http://localhost:54324/api/v1/mailbox/<mailbox>`). Otherwise read the mail env: `SMTP_HOST=localhost` with port `1025` means a catcher is expected even if the compose file does not start it, and `RESEND_API_KEY`/`POSTMARK_*`/`SENDGRID_*` in test mode means the "inbox" is the provider's test-mode log or the app's own log line. No reachable catcher is `error: no mail capture`, never a pass.

**Throwaway identity.** Sign up through the app's own sign-up route with `qa+<unix-ts>@example.com` and the password from the config's `credentials_env`, exactly as above; never reuse the shared test account where a check needs a second identity, and delete the rows the audit created afterwards.
