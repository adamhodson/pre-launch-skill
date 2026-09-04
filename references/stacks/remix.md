# Remix / React Router 7

## detection signals
`@remix-run/react` with `@remix-run/node` (or `@remix-run/cloudflare`, `@remix-run/deno`) in package.json, plus an `app/` directory containing `root.tsx` and `app/routes/`. Two build systems exist: the classic compiler, marked by `remix.config.js`, and the Vite plugin (Remix 2.x onwards), marked by `vite.config.ts` importing `vitePlugin as remix` from `@remix-run/dev`.

**Remix v2 became React Router 7.** A React Router 7 "framework mode" project is the same architecture with different package names: `react-router` and `@react-router/dev` (plus `@react-router/node`, `@react-router/serve`) in package.json, `react-router.config.ts` instead of `remix.config.js`, an `app/routes.ts` route-config file, and imports from `react-router` rather than `@remix-run/*`. Every concept below — loader, action, `ErrorBoundary`, `.server` modules, resource routes — carries over unchanged; only the import specifiers and the CLI names differ. Check `package.json` to see which you are in, and check the version's docs for anything version-shaped (middleware, upload helpers, `prerender`), because those moved.

## dev server
`npm run dev` (or `pnpm|yarn|bun dev` per lockfile). Port depends on the build system: the classic compiler with `remix-serve` runs on **3000**; the Vite plugin runs Vite's dev server, whose default is **5173** unless `server.port` in `vite.config.ts` says otherwise, and many Remix templates set it back to 3000. Read the banner the command prints rather than assuming either. Ready when `GET /` returns 200. Never measure performance, headers, or analytics gating against the dev server — see "build".

## build
`npm run build`:
- **Vite plugin** → `build/server/index.js` and `build/client/`. Production start is `npm start`, which runs `remix-serve ./build/server/index.js` (React Router 7: `react-router-serve ./build/server/index.js`) on **port 3000**, overridable with `PORT`. So the production probe is `npm run build && PORT=3100 npm start`.
- **Classic compiler** → `build/index.js` plus `public/build/` for client assets, same `remix-serve` start.
- **Custom server** — a `server.ts`/`server.js` at the root (Express, Hono, Fastify) that imports `createRequestHandler` and is started by `node ./server.js`. When this file exists it is the real entry point and `remix-serve` is not used; read its `app.listen` for the port and its middleware stack for headers, compression, and rate limiting, since those live there rather than in the framework.

`NODE_ENV=production` is what switches Remix from dev to production error behaviour, so set it explicitly. Client bundles under `build/client/assets/` (Vite) or `public/build/` (classic) — grep those for leaked secrets (SEC-003).

## env vars
**There is no public env prefix, and that is the thing to understand about this stack.** `process.env` exists only on the server. A component that references `process.env.FOO` and renders in the browser throws at runtime; it is not silently inlined. The only way a value reaches the client is that some code puts it there, which means the leak surface is not a naming convention but the loaders.

The standard pattern is a root loader publishing a whitelist:

```ts
// app/root.tsx
export const loader = () => json({ ENV: { SENTRY_DSN: process.env.SENTRY_DSN, APP_URL: process.env.APP_URL } })
// ...then <script dangerouslySetInnerHTML={{ __html: `window.ENV=${JSON.stringify(data.ENV)}` }} />
```

Audit that object as if it were the public prefix: everything in it is public (SEC-003). And audit every other loader the same way — **any value returned from any loader or action is serialized into the HTML payload (`window.__remixContext`) and into the fetch responses the client makes**, whether or not a component renders it.

With the Vite plugin, `import.meta.env.VITE_*` is also inlined into the client bundle by Vite's own rule, so a project that uses it has a public prefix after all — grep for `VITE_`.

Loading: `.env` is read by `remix-serve` and by `remix vite:dev` in development (via dotenv). In production the host provides the environment; `.env` is not read by the built server unless the custom server calls `dotenv/config` itself (REL-008). For payment test-mode detection read `STRIPE_SECRET_KEY` from the running process, then `.env`; the `sk_test_` / `pk_test_` prefix is the tell.

## routes and handlers
Routes are modules under `app/routes/**`, one file per route, with the file name encoding the URL. Remix v2 flat routes: `.` is a path separator (`app/routes/posts.$id.tsx` → `/posts/:id`), `_index.tsx` is an index route, a leading `_` makes a pathless layout (`_auth.login.tsx`), a trailing `_` opts a segment out of its parent's layout, `$param` is a dynamic segment, `$.tsx` is a splat. A directory with a `route.tsx` inside works as one route module. React Router 7 can also declare routes explicitly in `app/routes.ts` — when that file exists it is the authoritative route list, so read it first.

Each route module exports some of:
- `loader` — server-only, handles `GET`, returns data (or a `Response`).
- `action` — server-only, handles `POST|PUT|PATCH|DELETE`.
- `default` — the React component.
- `ErrorBoundary` — the error UI for that route.
- `headers` — response headers for document requests.
- `meta`, `links` — head tags and preloads.
- `shouldRevalidate`, `handle`, `clientLoader`, `clientAction` — the client-side variants run **in the browser**; never put an authorization decision in a `clientLoader`.

**A route module with no `default` export is a resource route** — a pure API endpoint. That is where webhooks, JSON APIs, file downloads, streaming AI endpoints, `sitemap[.]xml.tsx`, and `robots[.]txt.tsx` live. There is no separate `api/` directory to look in, which is why an auditor who greps for one concludes wrongly that the app has no API.

Other files that matter: `app/root.tsx` — the root layout, the `<html lang>` tag, `<Meta>`, `<Links>`, `<Scripts>`, the root `ErrorBoundary`, and the place analytics and consent scripts are mounted. `app/entry.server.tsx` and `app/entry.client.tsx` — optional; if absent Remix uses built-in defaults, and `npx remix reveal` writes them out. `entry.server.tsx` is where the whole document response is assembled and is the one place to set headers for every route at once, plus it exports `handleError` for reporting. `app/session.server.ts`, `app/db.server.ts`, `app/models/*.server.ts` — the `.server` suffix convention (see "data access").

Forms post to their own route's `action` via `<Form method="post">` or `useFetcher()`; `<Form action="/other/route">` posts to another route's action. To enumerate routes: `find app/routes -type f`, or read `app/routes.ts` if it exists.

## auth
Nothing ships with Remix. The idiomatic implementation is cookie session storage in `app/session.server.ts`:

```ts
// app/session.server.ts
import { createCookieSessionStorage, redirect } from '@remix-run/node'

export const sessionStorage = createCookieSessionStorage({
  cookie: {
    name: '__session',
    httpOnly: true,
    path: '/',
    sameSite: 'lax',
    secrets: [process.env.SESSION_SECRET!],
    secure: process.env.NODE_ENV === 'production',
  },
})

export async function requireUserId(request: Request, redirectTo = new URL(request.url).pathname) {
  const session = await sessionStorage.getSession(request.headers.get('Cookie'))
  const userId = session.get('userId')
  if (!userId) throw redirect(`/login?redirectTo=${encodeURIComponent(redirectTo)}`)
  return userId
}
```

Variants: `createFileSessionStorage` and `createSessionStorage` for a database-backed session (the cookie session stores the data *in* the cookie, signed but readable, so nothing secret belongs in it); `remix-auth` with `authenticator.isAuthenticated(request, { failureRedirect: '/login' })` and strategy modules for OAuth; `@supabase/ssr` with a server client built per request from the cookie header and `getUser()` for authorization (never `getSession()` alone); Clerk's Remix SDK with `getAuth(args)` inside each loader.

**The check to make: `requireUserId(request)` (or the project's equivalent) is called at the top of every protected `loader` and `action`, including every resource route.** Remix v2 has no middleware layer — a parent route's loader does not protect a child, and it does not run at all for a resource route or for a client-side `fetcher` hitting a sibling. React Router 7 added a middleware API that has been unstable/opt-in; if the project uses it, read the version's docs before treating it as a complete guard. Every unguarded loader is SEC-010.

## webhook handlers
A resource route: `app/routes/webhooks.stripe.tsx` (or `app/routes/api.webhooks.stripe.tsx`) exporting only an `action`. The raw body is `await request.text()`. Remix does not parse the body for you, so nothing is consumed before you ask — but `await request.json()` or `await request.formData()` consumes the stream, and a later `request.text()` throws, which is how a handler ends up unable to verify (SEC-051). Webhook routes are legitimately exempt from CSRF checks and must not be behind a session guard; if a custom server mounts auth middleware, the webhook path needs an exemption there too.

## webhook verification snippet
```tsx
// app/routes/webhooks.stripe.tsx  — resource route: no default export
import type { ActionFunctionArgs } from '@remix-run/node'
import Stripe from 'stripe'

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!)

export async function action({ request }: ActionFunctionArgs) {
  if (request.method !== 'POST') return new Response('method not allowed', { status: 405 })
  const sig = request.headers.get('stripe-signature')
  const raw = await request.text() // raw first; never request.json() before this
  if (!sig) return new Response('missing signature', { status: 400 })

  let event: Stripe.Event
  try {
    event = stripe.webhooks.constructEvent(raw, sig, process.env.STRIPE_WEBHOOK_SECRET!)
  } catch {
    return new Response('bad signature', { status: 400 })
  }
  // handle event.type ...
  return new Response('ok')
}
```
For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
The server-only boundary is the **`.server` filename suffix**: `app/db.server.ts`, `app/models/user.server.ts`, `app/utils/stripe.server.ts` are excluded from the client bundle, and importing one from a module that ships to the browser is a build error with the Vite plugin (the classic compiler tree-shook instead, which was quieter and less safe — note which build system the project uses). A `.client.ts` suffix does the reverse. Schema and policies belong to the data stack: `prisma/schema.prisma` with `app/db.server.ts` exporting a singleton client, `drizzle/schema.ts` plus `drizzle.config.ts`, or `supabase/migrations/*.sql`.

Query from `loader` and `action` only. `clientLoader` and `clientAction` run in the browser.

**Payload trap, and it is the biggest one in this stack:** everything a loader returns is serialized into the initial HTML and into every client-side navigation's fetch response. `return json({ user })` where `user` is the row Prisma handed back publishes the password hash, the Stripe customer id, the internal flags, and the soft-delete column — regardless of what the component renders. Loaders must return an explicit narrow shape (`{ id, email, name }`), and actions the same. Grep for loaders returning a bare model object or spreading one.

## file uploads
`await request.formData()` in an action gives you `File` entries for small posts. For real uploads Remix v2 used `unstable_parseMultipartFormData(request, uploadHandler)` with `unstable_createFileUploadHandler` (streams to disk) or `unstable_createMemoryUploadHandler` (buffers, with a `maxPartSize`); newer Remix and React Router 7 moved to `@mjackson/form-data-parser` (`parseFormData`) — check the version's docs and the installed packages before assuming which. Direct-to-storage presigned uploads (S3, R2, Supabase Storage, UploadThing) are common and bypass the server entirely, which is also the fix for platform body limits.

Always check `maxPartSize` is set (the memory handler's default is small but the file handler's is not a substitute for a real check), that the content type is re-derived from magic bytes rather than trusted, and that the filename is not used to build a path. Remix has no image optimizer and no remote-host allowlist of its own, so SEC-045's optimizer question usually resolves to "not applicable — no image proxy" unless the project added one (`remix-image`, an external CDN, `sharp` in a resource route that fetches a URL from the query string, which *is* an open proxy).

## background jobs
Nothing built in. Look for: a platform cron (`vercel.json` `crons`, a Netlify scheduled function, a Fly machine schedule, a Kubernetes CronJob) hitting a resource route; Inngest, Trigger.dev, or QStash; a separate worker process (BullMQ, `worker.ts` in the Procfile or compose file) importing the same `.server` modules. A cron-triggered resource route must authenticate its caller with a shared bearer secret checked inside the action (SEC-014). Email sends are usually inline in an action (`app/utils/email.server.ts` wrapping Resend, Postmark, SendGrid, or nodemailer), which makes the request as slow and as failure-prone as the provider.

## error handling and logging
Each route may export `ErrorBoundary`, read with `useRouteError()` and narrowed with `isRouteErrorResponse(error)` to tell a thrown `Response` (a 404 or 403 you threw deliberately) from an unexpected exception. The root `ErrorBoundary` in `app/root.tsx` is the last catch and must render a full document (`<html>`, `<Meta>`, `<Links>`, `<Scripts>`) or the error page renders blank.

In production Remix scrubs unexpected server errors before they reach the client, sending a generic message. Two ways to undo that: throwing `json({ message: err.message }, { status: 500 })` yourself, which is an *expected* response and is sent verbatim; and an `ErrorBoundary` that renders `error.stack` or `JSON.stringify(error)` (SEC-009). Grep for both.

Reporting: `export function handleError(error, { request })` in `app/entry.server.tsx` is the server-side hook for every unhandled error — `@sentry/remix` provides `sentryHandleError` for it, plus `withSentry()` around the root component for the browser half. Both halves need wiring; the `entry.server.tsx` half is the one usually missed, and on a project that never ran `remix reveal` the file does not exist at all, which means there is no server error reporting even though the client shows errors in Sentry. A custom `server.ts` is the other place request logging and error middleware live.

## security headers
Three places:
- **`entry.server.tsx`** — inside `handleRequest`, `responseHeaders.set('Content-Security-Policy', ...)` before returning the response. This covers every document request in one place and is the usual home for a nonce-based CSP (generate the nonce here, pass it through to `<Scripts nonce=...>`).
- **A route's `headers` export** — `export function headers({ loaderHeaders, parentHeaders }) { return { 'Cache-Control': '...' } }`. This is per-route and applies to document requests; the resolution between parent and leaf changed across versions, so read the version's docs before concluding a parent's headers are inherited. Use it for caching, not as the security-header home.
- **The custom server or the platform** — `helmet()` in an Express `server.ts`, `vercel.json` `headers`, `netlify.toml`, `public/_headers`, nginx.

`X-Robots-Tag` for an authenticated area goes in `entry.server.tsx` or the platform config; per-route noindex is a `meta` export returning `{ name: 'robots', content: 'noindex' }`.

## known traps
- Anything returned from a loader or action is public — a full DB row, an internal flag, an API key put in `window.ENV`: SEC-003. There is no prefix to grep for, so read the loaders.
- `import.meta.env.VITE_*` used in a Vite-based project: it is inlined into the client bundle (SEC-003).
- `dangerouslySetInnerHTML` with user or CMS content without sanitization: SEC-043. Note the root `window.ENV` script uses it legitimately — check the payload, not the call.
- `build.sourcemap: true` in `vite.config.ts`, or `sourcemap: true` in `remix.config.js`: SEC-007.
- A `loader` or `action` with no `requireUserId`-style check: it is a public HTTP endpoint, and there is no middleware layer to catch it in Remix v2 (SEC-010, SEC-012).
- A resource route (no default export) inside an otherwise-guarded area: parent loaders never run for it (SEC-010).
- Authorization in a `clientLoader` or `clientAction`: it runs in the browser (SEC-010).
- A `headers` export returning `Cache-Control: public, max-age=...` on a route whose loader returns per-user data, or a CDN rule doing the same: SEC-036.
- `redirect(new URL(request.url).searchParams.get('redirectTo'))` without an allowlist: SEC-029. The `redirectTo` pattern is idiomatic in Remix's own templates, which is exactly why it is usually unvalidated.
- No image optimizer ships with Remix, so SEC-045's remote-host allowlist question is usually "not applicable — no image proxy". It becomes applicable if the project added one: a resource route that fetches a URL from a query parameter and re-serves or resizes it is an open proxy, and an external image CDN moves the allowlist to that CDN's config.
- `createCookieSessionStorage` used to store more than an id: the cookie is signed, not encrypted, and its contents are readable with base64 (SEC).
- `secrets: ['default']` or a hardcoded `SESSION_SECRET` fallback: session forgery (SEC-001).
- `secure: process.env.NODE_ENV === 'production'` with `NODE_ENV` unset in production: the session cookie ships without `Secure` (SEC-025).
- `entry.server.tsx` absent, so `handleError` is never defined and server errors are unreported (REL).
- React Router 7 `prerender` or SPA mode on a route that reads a session: one user's data baked into HTML (SEC-011).
- Preview or branch deployments inheriting production env unless scoped per environment: DAT-017.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if already in devDependencies; never install one for the audit.

## runtime probe hints
**Session cookie for `curl`.** Remix actions take form-encoded posts by default (`<Form method="post">`), so post to the route's own path:
```bash
# sign up a throwaway identity through the app's own route action
curl -s -c .pre-launch/flows/cookies.txt -X POST http://localhost:3100/join \
  --data-urlencode "email=qa+$(date +%s)@example.com" \
  --data-urlencode 'password=<from credentials_env>' -i
# or log in
curl -s -c .pre-launch/flows/cookies.txt -X POST http://localhost:3100/login \
  --data-urlencode 'email=...' --data-urlencode 'password=...' -i
# reuse
curl -s -b .pre-launch/flows/cookies.txt http://localhost:3100/dashboard -o /dev/null -w '%{http_code}\n'
```
A successful login normally answers `302` with `Set-Cookie`, so use `-i` and follow with `-L -b` only after you have the cookie. The route paths are the project's own — find them from `app/routes/` (`login`, `join`, `signup`, `auth.login`) or `app/routes.ts` before writing the URL. If the project ships a JSON API route instead, post JSON to that.

**Cookie names.** Whatever `createCookieSessionStorage({ cookie: { name } })` says — `grep -rn "createCookie" app/`. The Remix templates default to `__session`, and `_session` and `__remix_session` are common. `remix-auth` reuses the app's own session storage, so the same name. `@supabase/ssr` uses `sb-<project-ref>-auth-token`, possibly chunked as `.0` / `.1` — send every chunk. Clerk uses `__session` plus `__client_uat`.

**Health path.** No convention. Look for `app/routes/healthcheck.tsx` — the Remix Indie/Blues stacks ship exactly that name, so it is more likely here than on other stacks — plus `health`, `healthz`, `api.health`. If none exists, use the cheapest static route for cold-start timing and say which you used.

**Not-found behaviour.** An unmatched path throws a 404 `Response` caught by the root `ErrorBoundary`, which renders with status 404. `throw new Response('Not Found', { status: 404 })` in a loader does the same. Check the status code and not just the body: a splat route (`app/routes/$.tsx`) rendering a "not found" message without throwing returns 200 and is a soft 404 (SEO).

**Test-mode provider keys.** Read the environment of the running process (`printenv | grep -i stripe`), then `.env` — the built server does not read `.env` unless a custom server calls `dotenv/config`, so the file and the process can disagree. Stripe `sk_test_` / `pk_test_` / `rk_test_` and a `whsec_` from `stripe listen`; PayPal on `api-m.sandbox.paypal.com`; Paddle, Lemon Squeezy, RevenueCat a sandbox host, flag, or key. Published test card numbers live in the payment provider's own stack file. If the classification is ambiguous, treat the keys as live and stop.

**Local mail catcher.** None ships with Remix. Check `docker-compose.yml` / `compose.yaml` for `axllent/mailpit` (SMTP `1025`, HTTP `8025`, `curl -s http://localhost:8025/api/v1/messages`), `mailhog/mailhog` (API `/api/v2/messages` on `8025`), or `inbucket/inbucket`; a Supabase local stack runs Inbucket on `54324` (`curl -s http://localhost:54324/api/v1/mailbox/<mailbox>`). Otherwise read the mail env: `SMTP_HOST=localhost` with port `1025` means a catcher is expected, and `RESEND_API_KEY` / `POSTMARK_*` / `SENDGRID_*` in test mode means the "inbox" is the provider's test-mode log or the app's own log line. No reachable catcher is `error: no mail capture`, never a pass.

**Throwaway identity.** Sign up through the app's own sign-up action with `qa+<unix-ts>@example.com` and the password from the config's `credentials_env`, as above; never reuse the shared test account where a check needs a second identity, and delete the rows the audit created afterwards.
