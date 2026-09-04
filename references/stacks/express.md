# Express

## detection signals
`express` in `package.json` dependencies and an `express()` call with an `app.listen(...)` somewhere. The entry point is `package.json`'s `main` or `scripts.start`; common paths are `server.js`, `app.js`, `index.js`, `src/index.ts`, `src/app.ts`, `src/server.ts`, and `bin/www` with `app.js` beside it (the express-generator layout). Routers usually live in `routes/`, `src/routes/`, or `src/api/`.

**Read the major version first** — `"express": "^4"` and `"express": "^5"` behave differently in three ways this audit cares about: async handler rejections (Express 5 forwards them to the error middleware, Express 4 does not), route path syntax (Express 5 uses path-to-regexp v8, where bare `*` and unnamed wildcards are invalid and `/*splat` / `{/:optional}` replace them), and a handful of removed helpers. Check `node_modules/express/package.json` or the lockfile for the resolved version, not just the range.

Also check what is layered on top: `@nestjs/core`, `feathers`, `loopback`, or `tsoa` mean the routing and DI are that framework's, though the Express idioms below still describe the underlying request pipeline. A `client/`, `frontend/`, or `public/` directory with its own `package.json` is a separate frontend with its own stack file, its own public env prefix, and its own build.

## dev server
`npm run dev` — read the script. Typically `nodemon src/index.js`, `ts-node-dev`, `tsx watch src/index.ts`, or `node --watch src/index.js`. There is no framework-imposed port: it comes from `app.listen(process.env.PORT || 3000)` and the literal in that `||` is the default. **Read the actual `app.listen` call** rather than assuming 3000, and if the port cannot be determined from the code or a `.env`, ask.

`NODE_ENV` is the mode switch and it matters more here than on most stacks: Express's built-in final error handler includes the stack trace in the response body whenever `NODE_ENV` is not `'production'`, view caching is off, and several libraries (`express-session`, `helmet`, `morgan`) change behaviour or emit warnings. Never measure error bodies, headers, or performance with `NODE_ENV` unset. See "build".

## build
Depends on the language:
- **Plain JavaScript**: no build step. `npm ci` then `NODE_ENV=production PORT=3100 node src/index.js` (or `npm start`). There is no build output directory, so SEC-003's "grep the bundle" step has nothing to grep on the server side — say so, and grep the frontend's build output instead if one exists in the repo.
- **TypeScript**: `npm run build` → `tsc` → `dist/` (see `outDir` in `tsconfig.json`), or a bundler (`esbuild`, `tsup`, `swc`, `rollup`) whose config names the output. Production start is `NODE_ENV=production PORT=3100 node dist/index.js`. `tsconfig.json`'s `sourceMap`/`inlineSourceMap`, or the bundler's `sourcemap` flag, decides whether `.map` files ship (SEC-007) — on a server-only API those maps are not publicly served unless `express.static` happens to expose `dist/`, which is worth checking rather than assuming.

Clean-clone reproduction for HYG-015: `npm ci` (not `npm install`) against the committed lockfile, and check that the lockfile's package manager matches the README — a `pnpm-lock.yaml` beside `npm install` instructions is a finding before anything runs. Node version from `engines` in `package.json`, `.nvmrc`, or `.tool-versions`.

Two things other domains ask of this section. Compression (PERF-003) is the `compression()` middleware, which is not installed or enabled by default — see "security headers". Deployment shape (PERF-016): Express normally runs as a long-lived Node process, so there is no cold start to measure and that check is `n/a — long-lived process`; the exception is an Express app wrapped in `serverless-http` or `@vendia/serverless-express` for Lambda or a scale-to-zero container, in which case there is one and the platform's stack file owns the number.

Process managers you may find wrapping the start command: `pm2` (`ecosystem.config.js`, and `instances: 'max'` means N copies of any in-process scheduler — see "background jobs"), `Dockerfile` with a `CMD`, a `Procfile`, or a systemd unit.

## env vars
`process.env.X` and `process.env['X']`, everywhere and unvalidated by default. Loaders:
- `dotenv` — `require('dotenv').config()` / `import 'dotenv/config'`. **It must run before any module that reads `process.env` at import time**; a config module imported above the `dotenv.config()` line gets `undefined` and silently falls back, which is a REL-008 finding with a real consequence. `dotenv/config` as the first import, or `node --env-file=.env` (Node 20.6+), avoids it.
- `dotenv-flow` for `.env.<NODE_ENV>` layering.
- A typed schema — `envalid`, `zod` parsing in `src/env.ts` or `src/config.ts`, `@t3-oss/env-core`. **When one of these exists it is the authoritative variable list for REL-008** and you should read it instead of grepping, since it names every variable, its type, and its default.

REL-008's second set — the variables that are *declared* — comes from `.env.example` / `.env.sample` if the project keeps one, plus the deploy config (`Dockerfile` `ENV` lines, `docker-compose.yml` `environment`, `fly.toml`, `render.yaml`, `ecosystem.config.js`'s `env`, the CI workflow's `env` blocks).

The REL-008 pattern to hunt is `process.env.X || 'fallback'` and `process.env.X ?? ''`. On a signing secret, an allowed-origins list, an admin email, or a feature flag, that fallback turns a missing production variable into silently wrong behaviour rather than a crash — `process.env.WEBHOOK_SECRET || 'dev'` means every forged webhook verifies.

**Public prefix**: none on the server; Node reads the whole environment and nothing is inlined into anything. If the repo also contains a frontend, that bundler's prefix (`VITE_`, `REACT_APP_`, `NEXT_PUBLIC_`, `PUBLIC_`) applies to its build and is where SEC-003 looks. The server-side leak to check instead is a route or config endpoint that returns `process.env` or a config object wholesale to the client.

**Payment test-mode detection**: `printenv | grep -i stripe` on the running process, then `.env` and `.env.local`. The `sk_test_` / `pk_test_` prefix is the tell.

## routes and handlers
Registration forms, all of which you need to grep for:
- `app.get('/path', handler)` and the other verbs, plus `app.all` and `app.use`.
- `app.route('/path').get(h1).post(h2)`.
- `const router = express.Router()` in a routes module, then `router.get(...)` and `app.use('/api/users', router)` — **the mount prefix is in a different file from the route paths**, so the full URL is the concatenation and you must trace both halves.
- `app.use(express.static('public'))` serving files with no route at all.
- Mounted sub-applications (`app.use('/admin', adminApp)`).

**Order is semantics.** Express runs the stack in registration order, so a middleware added after a router does not protect it, and a route registered before its router's own `router.use(auth)` line runs unguarded. This is the defining property of the stack and the source of most SEC-010 findings here: reading a file top to bottom is the correct way to audit it, and reading only the handler bodies is not.

To enumerate routes: `express-list-endpoints` if it is already a dependency; otherwise walk the internal stack — `app._router.stack` in Express 4, and the internal property was renamed in Express 5, so check what the running version exposes before scripting against it. Failing that, read the entry file and follow every `app.use` and `require`/`import` of a routes module; that is reliable and is what the ordering audit needs anyway.

Not-found handling: Express has no 404 page. Without a final catch-all `app.use((req, res) => res.status(404).json({...}))`, an unmatched path gets the built-in `Cannot GET /path` body with status 404.

## auth
There is no framework auth. Find what the app wrote or installed, then find **where it is applied** — the second half is the audit.

Mechanisms:
- **`express-session`** plus a store (`connect-redis`, `connect-mongo`, `connect-pg-simple`). Options that matter: `name` (the cookie, default `connect.sid`), `secret`, `cookie: { httpOnly, secure, sameSite, maxAge }` (SEC-025, SEC-026), `resave`, `saveUninitialized`, `rolling`, and `store` — **with no `store` the default is `MemoryStore`, which loses every session on restart, grows without bound, and prints a production warning**.
- **`passport`** — `passport.authenticate('local'|'jwt'|'google', ...)` as route middleware, `req.isAuthenticated()`, `passport.serializeUser`/`deserializeUser`, strategies configured in `config/passport.js` or similar.
- **A hand-written middleware** — this is the most common case. Grep for `requireAuth`, `authMiddleware`, `isAuthenticated`, `protect`, `verifyToken`, `ensureLoggedIn`, and for `jwt.verify(` / `jsonwebtoken`. Read it for: whether it verifies the signature (not just decodes — `jwt.decode()` verifies nothing), whether the algorithm is pinned (`jwt.verify(t, secret, { algorithms: ['HS256'] })` — SEC-027), whether it checks expiry, whether it re-loads the user from the database or trusts the claims, and whether it calls `next()` on the failure path (a middleware that logs and falls through is no middleware at all).
- **A managed provider** — `@clerk/express`, `express-oauth2-jwt-bearer` (Auth0), `@supabase/supabase-js` with a server client, `better-auth`.

Application, in the order of decreasing safety:
1. `app.use(requireAuth)` above all protected routers — safe, but check nothing is mounted above it.
2. `app.use('/api/admin', requireAuth, requireAdmin, adminRouter)` — per-router, and the usual pattern.
3. `router.get('/x', requireAuth, handler)` — per-route, and the one that goes wrong: every new route must remember it, and the one that forgets is invisible.

For SEC-010, produce the list: every route, and the middleware chain that actually reaches it given registration order. For SEC-012, check that the role comes from the database or a freshly verified token rather than from a request header, a body field, or a JWT claim the app issues at sign-up and never re-checks.

## webhook handlers
The raw body is the whole problem. `express.json()` (or `body-parser.json()`) replaces `req.body` with a parsed object and discards the bytes, and a signature computed over `JSON.stringify(req.body)` will not match the provider's because key order and whitespace differ. Two correct patterns:

1. **Route-scoped raw parser, mounted so it wins**: `app.post('/webhooks/stripe', express.raw({ type: 'application/json' }), handler)` — and this route must be registered **before** any global `app.use(express.json())`, or the global parser consumes the body first. Registering it after is the single most common SEC-051 failure on this stack, and it fails silently in the sense that the handler still runs.
2. **Capture the buffer during parsing**: `app.use(express.json({ verify: (req, res, buf) => { req.rawBody = buf } }))`, then verify against `req.rawBody`. Works globally, at the cost of buffering every request.

Also note the size cap: `express.raw()` defaults to a 100 kB limit like the other parsers, so a large provider payload gets a 413 before the handler sees it — pass `{ limit: '1mb' }` where the provider sends big events. Webhook routes also need excluding from any global auth middleware and from CSRF.

## webhook verification snippet
```js
// routes/webhooks.js — register BEFORE app.use(express.json())
const express = require('express')
const Stripe = require('stripe')
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY)

app.post('/webhooks/stripe',
  express.raw({ type: 'application/json' }),
  async (req, res) => {
    const sig = req.headers['stripe-signature']
    let event
    try {
      event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET)
    } catch (err) {
      return res.status(400).send('bad signature')
    }
    await queue.add('stripe-event', { id: event.id, type: event.type })
    res.status(200).send('ok')
  })
```
`req.body` here is the raw `Buffer` because of `express.raw`, which is exactly what `constructEvent` needs; it enforces the timestamp tolerance itself (300 seconds by default), which is the replay defence SEC-051 asks about. For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
Whatever the project installed. Identify it from `package.json`, then locate the connection module (`db.js`, `src/db/index.ts`, `lib/prisma.ts`, `models/`).

- **`pg`** — `pool.query(text, values)`. Safe with `$1` placeholders and a values array; a template literal or `+` inside `query()` is SEC-038. One `new Pool()` module reused across the app; a pool created per request exhausts connections (DAT-008).
- **`mysql2`** — `conn.execute(sql, [values])` is prepared; `conn.query(sql)` with interpolation is not.
- **Prisma** — `prisma/schema.prisma` is the schema, `prisma/migrations/` the migrations. `$queryRaw` as a **tagged template** is parameterized and safe; `$queryRawUnsafe(string)` is not, and the name is the giveaway. `prisma.user.update({ data: req.body })` is mass assignment (SEC-041).
- **Drizzle** — `drizzle/schema.ts` plus generated SQL; `sql` tagged templates are parameterized, `sql.raw()` is not.
- **Knex** — `knex.raw('... ' + x)` is a sink; `knex.raw('... ?', [x])` is not. `knex('t').where({...})` is safe.
- **Sequelize** — `sequelize.query(sql, { replacements: {...} })` or `{ bind: [...] }` is safe; a bare interpolated string is not.
- **TypeORM** — `.where('x = :v', { v })` is safe; `.where(\`x = ${v}\`)` is not.
- **Mongoose / MongoDB** — SQL injection does not apply but operator injection does: `User.find(req.query)` lets a caller send `{"password": {"$ne": null}}` (SEC-039). `mongoose.Schema` with `strict: true` (the default) drops unknown keys on write, which is a partial mass-assignment guard; `new Model(req.body)` still sets every schema-declared field including a `role` (SEC-041).

**Row-level security** (DAT-001, DAT-002): unless the app is fronting Supabase or another PostgREST-style service, it connects as one database user with access to every row and all authorization is application code — record RLS as not in use and let SEC-011 and DAT-026 carry that ground.

Validation (SEC-037): `zod`, `joi`, `yup`, `express-validator`, `celebrate`, `typebox`. The absence of any of these plus direct `req.body` use is the finding. Migrations for DAT-015: Prisma and Knex both read `DATABASE_URL` from the environment, so `DATABASE_URL=postgres://<user>@<host>/prelaunch_scratch npx prisma migrate deploy` (or `npx knex migrate:latest`) redirects them — confirm with `npx prisma migrate status` under the same override before running anything that writes, and never run `prisma migrate reset`.

Pagination (DAT-011): nothing is built in. A `findMany()` or `SELECT *` with no `take`/`limit`, or a `limit` taken from the query string with no ceiling, is the finding.

Response shaping (SEC-042): `res.json(user)` returns every column the query selected, including `password_hash` if the query was `SELECT *`. Look for an explicit `select`, a `toJSON` that deletes fields, or a serializer.

## file uploads
- **`multer`** — the default. `multer({ dest })` writes to disk; `multer({ storage: multer.memoryStorage() })` buffers in RAM (a memory exhaustion risk with no limit). **`limits: { fileSize, files, fields }` is not set by default**, so an upload route with no `limits` accepts an arbitrarily large file (SEC-067, SEC-047). `fileFilter` typically checks `file.mimetype`, which is **client-supplied and spoofable** — a real content check means magic bytes (`file-type`, `sharp`/`jimp` re-encode) after the upload lands (SEC-047, SEC-049 for SVG).
- **`busboy`, `formidable`, `express-fileupload`** — same questions, different option names.
- **Presigned direct-to-storage** — `@aws-sdk/s3-request-presigner`'s `getSignedUrl`, or the equivalent for GCS/R2/Supabase. The upload bypasses the app entirely, so any validation written in the handler does not run; the constraints have to be in the presign call (`ContentLength` range, content type) and in the bucket policy.

Serving uploads: `app.use('/uploads', express.static(uploadDir))` puts user-controlled files on the app's own origin, so a stored HTML or SVG file executes in the app's context (SEC-048). `res.sendFile(path.join(dir, req.params.name))` without normalizing and confining the resolved path is directory traversal (SEC-046) — the fix is `path.resolve` plus a `startsWith(dir)` check, or serving from storage by id rather than by name.

Body size (SEC-067): `express.json()` and `express.urlencoded()` default to a **100 kB** limit and reject larger bodies with 413. A raised `limit: '50mb'` is a denial-of-service surface; the absence of any explicit limit is fine for JSON and wrong for the webhook routes discussed above.

## background jobs
Nothing ships with Express. What you will find:
- **BullMQ / Bull** — Redis. `new Queue('name')` to enqueue, `new Worker('name', fn)` in a **separate process** to consume. Check the Procfile, `docker-compose.yml`, or pm2 config for that worker actually being started; a queue with no worker is jobs that never run (REL-019). Bull Board or Arena dashboards mounted at `/admin/queues` need their own auth (SEC-013).
- **`pg-boss`** (Postgres), **`graphile-worker`** (Postgres), **`agenda`** (Mongo) — same shape.
- **`node-cron` / `node-schedule` / `setInterval`** — in-process schedulers. They run in **every** instance, so two replicas or `pm2 -i max` means every scheduled job fires N times (REL-019), and they die with the process.
- **A platform cron hitting an HTTP endpoint** — then that endpoint needs a shared secret (`Authorization: Bearer ${CRON_SECRET}` compared in constant time) or anyone can trigger it (SEC-014, SEC-052).

The two impostors PERF-013 names, both common here: a floating promise (`sendEmail(user)` with no `await` and no `.catch()`) — the response returns, the rejection is unhandled, and on a serverless host the process may freeze before it completes; and `setTimeout(() => doWork(), 5000)` in a request handler, which does not survive a restart and holds nothing accountable. Neither is a queue.

Email sent inline (`await transporter.sendMail(...)`, `await resend.emails.send(...)`) inside a request handler is PERF-013's headline finding on this stack.

## error handling and logging
**The error middleware** is a function with exactly four parameters, `(err, req, res, next)`, registered with `app.use` **after every route**. Arity is what identifies it to Express, so a four-argument function that omits `next` is not an error handler and will never be called.

Grep the handler for what it sends: `res.status(500).json({ error: err.message })` leaks internals, and `err.stack` in the response is SEC-009 outright. The correct shape is a generic body plus a correlation id, with the full error logged server-side.

**Express's built-in final handler**, which runs when the app has no error middleware, includes the stack trace in the response body unless `NODE_ENV === 'production'`. So a deployment that forgets `NODE_ENV` leaks every stack trace with no code change anywhere (SEC-009) — confirm the running process's `NODE_ENV`, do not read it from a config file.

**Async handlers**: in **Express 4** a rejected promise from an `async` route handler is *not* caught — the request hangs until the client or a proxy times out, nothing reaches the error middleware, and nothing reaches the error tracker (REL-001). The fixes are `express-async-errors` (imported once, patches the router), an `asyncHandler(fn)` wrapper on every route, or try/catch in each handler. **Express 5** forwards rejections to the error middleware automatically. Check the resolved major version before reporting this; on Express 4 with no wrapper it is a real finding and the symptom is a hung request rather than a 500.

404: a final `app.use((req, res) => res.status(404).json({ error: 'Not Found' }))` after all routes.

Logging: `morgan` for HTTP access logs (`morgan('combined')` logs the full URL including the query string — SEC-064 and REL-015 if tokens travel there), `pino`/`pino-http` (structured, fast, with `redact` paths for REL-015), `winston`. `console.log` straight to the platform log stream is common and is what HYG-004 looks at.

Reporting: `@sentry/node`. In v8 and later `Sentry.init` must run **before** the application modules are imported (the convention is an `instrument.js` imported first, or `--import ./instrument.mjs`), and the Express integration is wired with `Sentry.setupExpressErrorHandler(app)` after the routes; older versions used `Sentry.Handlers.requestHandler()` and `errorHandler()`. Check which the installed version expects. A separate worker process needs its own init (REL-001).

## security headers
`helmet()` is the convention: with no options it sets `Content-Security-Policy` (a restrictive default), `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: no-referrer`, `Strict-Transport-Security`, `X-DNS-Prefetch-Control`, and removes `X-Powered-By`. Read the options object, because the common finding is a disabled sub-policy: `helmet({ contentSecurityPolicy: false })` turns CSP off entirely (SEC-031), and `crossOriginEmbedderPolicy: false` or `hsts: false` do the same for those.

Without helmet: `app.disable('x-powered-by')` (SEC-065) and hand-set headers in a middleware. HSTS is pointless unless TLS terminates in front and the app knows it — `app.set('trust proxy', 1)` makes `req.secure` and `req.ip` reflect `X-Forwarded-*` (SEC-034, SEC-016).

**`trust proxy` is a two-sided setting.** Unset behind a load balancer, `req.ip` is the balancer's address and every rate limiter keys every user to one bucket. Set to `true` (blanket trust), a client can spoof `X-Forwarded-For` and get a fresh bucket per request, defeating the limiter entirely (SEC-016) — recent `express-rate-limit` versions detect and warn about exactly this. The correct value is the number of proxies in front, or a specific address list.

CORS: `cors()` with **no options** sets `Access-Control-Allow-Origin: *` for every route (SEC-035). `cors({ origin: true })` reflects whatever `Origin` the request carried, which combined with `credentials: true` is a wildcard-with-credentials in everything but name. The safe form is an explicit array or a function checking an allowlist.

Rate limiting: `express-rate-limit` (keyed on `req.ip`, see `trust proxy` above; the default in-memory store is per-instance, so N replicas means N times the limit — use a Redis store), `rate-limiter-flexible`, or the platform's. Nothing is applied by default, so the login and password-reset routes are unthrottled unless someone said otherwise (SEC-015, SEC-017).

Compression: `compression()` (PERF-003). Not enabled by default.

## known traps
- `app.use(express.json())` registered above the webhook route, so `req.body` is a parsed object and the signature can never match: SEC-051.
- `cors()` with no options, or `origin: true` together with `credentials: true`: SEC-035.
- An auth middleware registered *after* the router it should protect, or applied to `/api/orders` but not to a separately mounted `/api/orders/:id/items` router: SEC-010, SEC-012.
- A per-route `requireAuth` pattern where one route forgot it — enumerate the routes and their real middleware chains rather than trusting the pattern: SEC-010.
- `jwt.decode()` used where `jwt.verify()` was meant, or `jwt.verify` with no `algorithms` option pinned: SEC-027, SEC-010.
- A role read from a JWT claim the app issued at sign-up and never re-validates against the database: SEC-012.
- `NODE_ENV` unset in production: Express's built-in error handler puts the stack trace in the response body (SEC-009), and several libraries stay in development mode.
- `res.status(500).json({ error: err.message })` or `err.stack` in any response: SEC-009.
- Express 4 with `async` route handlers and no `express-async-errors` or wrapper: rejections are unhandled, the request hangs, and nothing reaches the error tracker (REL-001). Express 5 forwards them — check the major version before reporting.
- `express-session` with no `store` (the default `MemoryStore`): sessions are lost on every restart and memory grows unbounded (PERF-015).
- `app.set('trust proxy', true)` blanket-trusting `X-Forwarded-For`, letting a client rotate its own rate-limit key: SEC-016.
- `express-rate-limit` with the default memory store behind more than one instance: the effective limit is N times what the code says (SEC-015).
- `helmet({ contentSecurityPolicy: false })`, or no helmet at all: SEC-031, SEC-033.
- `Object.assign(user, req.body)`, `new Model(req.body)`, or `prisma.x.update({ data: req.body })`: SEC-041.
- A template literal or `+` concatenation inside `pool.query`, `knex.raw`, or `$queryRawUnsafe`: SEC-038. A mongoose `find(req.query)`: SEC-039.
- EJS `<%- value %>`, Pug `!= value`, or Handlebars `{{{ value }}}` with user content — those are the unescaped forms: SEC-043.
- `res.sendFile` or `fs.readFile` on a path built from `req.params` / `req.query` without resolving and confining it: SEC-046.
- `express.static` serving the upload directory from the app's own origin: SEC-048.
- `multer` with no `limits.fileSize`, or a `fileFilter` trusting `file.mimetype`: SEC-047, SEC-067.
- `express.json({ limit: '50mb' })` or similar, raising the 100 kB default without a reason: SEC-067.
- `dotenv.config()` called after a module that reads `process.env` at import time: the value is `undefined` and a `||` fallback hides it (REL-008).
- `node-cron` or `setInterval` scheduling inside the web process with more than one instance running: every job fires once per instance (REL-019).
- A Bull Board, Arena, or `/admin/queues` dashboard mounted with no auth: SEC-013.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if already in devDependencies; never install one for the audit. Cited by the accessibility and compliance domain headers, COMP-007, and FLOW-018.

## runtime probe hints
**Session cookie or token for `curl`.** Most Express APIs take JSON and return either a `Set-Cookie` or a token in the body — read the login handler to see which, then:
```bash
JAR=.pre-launch/flows/cookies.txt
# cookie session
curl -s -c "$JAR" -X POST http://localhost:3100/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"qa+'"$(date +%s)"'@example.com","password":"<from credentials_env>"}' -i
curl -s -b "$JAR" http://localhost:3100/api/me -w '\n%{http_code}\n'

# bearer token
TOKEN=$(curl -s -X POST http://localhost:3100/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"...","password":"..."}' | jq -r '.token // .accessToken // .access_token')
curl -s http://localhost:3100/api/me -H "Authorization: Bearer $TOKEN" -w '\n%{http_code}\n'
```
The route paths vary completely — find the real sign-up and login handlers from "routes and handlers" first, including the mount prefix, since `/login` in a routes file mounted at `/api/auth` is `/api/auth/login`. The JSON field name for the token is equally arbitrary; the `//` fallbacks above cover the three common ones.

**Cookie names.** `connect.sid` is `express-session`'s default; a `name:` option overrides it, so grep for `session({` and read it. A hand-rolled cookie session uses whatever `res.cookie('<name>', ...)` says — `grep -rn "res.cookie(" src/` gives the list, and that grep is also how you check SEC-025's `httpOnly`, `secure`, and `sameSite` flags, since they are set at each call site rather than centrally.

**JWT for API probes.** On this stack the bearer token is usually the app's *own*, from the login route above, and it is the primary credential rather than a fallback — use it for SEC-011's second-identity probe and anywhere a check wants an authenticated API call. Decode the payload to see what the app trusts (`echo "<jwt>" | cut -d. -f2 | base64 -d 2>/dev/null | jq .`) — a `role` or `isAdmin` claim there that the server never re-checks is the SEC-012 finding, and you can demonstrate it without forging anything by comparing the claim against the database row. DAT-002's per-user RLS probe needs a data API that authorizes as the end user; unless the app is fronting Supabase or PostgREST there is no such surface, so record `n/a — no PostgREST surface` and rely on the two-account probes.

**Health path.** No convention. `grep -rn "'/health\|'/healthz\|'/ping\|'/status\|'/_health" src/` covers the usual names. If nothing exists use the cheapest route (often `GET /`) for cold-start timing and say which you used.

**Not-found behaviour.** Without a catch-all, an unmatched path returns Express's built-in `Cannot GET /path` with status 404 — that string in a response is itself the evidence that no 404 handler exists. With a catch-all, whatever it sends. Check the status code and not just the body: a handler that returns `{ error: 'not found' }` with status 200 breaks every client that checks the status.

**Test-mode provider keys.** Read the running process first (`printenv | grep -iE 'stripe|paypal|paddle'`), then `.env.local`, then `.env` — a platform-injected value beats all of them. Stripe `sk_test_` / `pk_test_` / `rk_test_` and a `whsec_` from `stripe listen` rather than the dashboard; PayPal pointing at `api-m.sandbox.paypal.com`; Paddle, Lemon Squeezy, and RevenueCat a sandbox host, flag, or key. Published test card numbers live in the payment provider's own stack file. If the classification is ambiguous, treat the keys as live and stop.

**Local mail catcher.** Express ships none, so read the mail client the app uses. `nodemailer` with `createTransport({ host, port })` — `host: 'localhost'` and port `1025` means a catcher is expected; `jsonTransport: true` or `streamTransport: true` means messages go to the process log rather than out, which is a usable capture if you redirected the server's output. Check `docker-compose.yml` / `compose.yaml` for `axllent/mailpit` (SMTP `1025`, HTTP `8025`, `curl -s http://localhost:8025/api/v1/messages`), `mailhog/mailhog` (API `/api/v2/messages` on `8025`), or `inbucket/inbucket`. A provider SDK (`RESEND_API_KEY`, `POSTMARK_*`, `SENDGRID_*`) in test mode means the inbox is the provider's test-mode log or the app's own log line. Start the production-mode server with its output redirected (`node dist/index.js > .pre-launch/flows/server.log 2>&1 &`) so a log-based capture is available at all. No reachable catcher is `error: no mail capture`, never a pass.

**Throwaway identity.** Sign up through the app's own sign-up route with `qa+<unix-ts>@example.com` and the password from the config's `credentials_env`, exactly as above; never insert the user straight into the database, because that skips the flow FLOW-001 is testing. Never reuse the shared test account where a check needs a second identity, and delete the rows the audit created afterwards — through the app's own account-deletion endpoint if one exists, which doubles as DAT-020's evidence.
