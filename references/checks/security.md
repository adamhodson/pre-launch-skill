# Security checks (SEC)

Read `agents/domain-auditor.md` for procedure. Blocks below are checks; consult stack references for locations. Tools: gitleaks (SEC-001, 002), `npm audit`/`pip-audit`/`bundler-audit`/`composer audit` (SEC-057), `probe_url.py` (SEC-007, 032–036, 056, 065, 066).

### SEC-001 No hardcoded secrets or API keys in source
severity: critical
tier: static
fix: easy
why: A key in source ships to every clone, CI log, and bundle. Once leaked it must be rotated, and most teams find out from a bill.
verify:
  static: Run `gitleaks detect --no-git --source . --report-format json` if installed; otherwise grep the tree (excluding node_modules, .git, lockfiles, and build output) for provider prefixes: `sk_live_`, `sk_test_`, `rk_live_`, `whsec_`, `AKIA[0-9A-Z]{16}`, `AIza[0-9A-Za-z_-]{35}`, `ghp_`, `xox[bp]-`, `-----BEGIN (RSA |EC )?PRIVATE KEY`, `eyJhbGciOi` outside test fixtures, and any assignment of `SECRET|TOKEN|PASSWORD|API_KEY` to a literal longer than 16 chars. Values read from `process.env`, `os.environ`, `ENV[...]`, `env(...)` are fine (stack ref: "env vars"). Test fixtures with obviously fake values pass; note them.
evidence: file:line and the redacted first 6 characters of each match; tool name used.
fix_hint: Move the literal to the environment loader named under stack ref "env vars", add the variable to `.env.example` with a placeholder, and tell the user the key must be rotated because it is already in history (see SEC-002).

### SEC-002 No secrets in git history
severity: critical
tier: static
fix: guided
why: Deleting a key in a later commit does not remove it; anyone who cloned the repo, and every fork and CI cache, still has the old blob. Public repos are scraped for exactly this within minutes.
verify:
  static: Run `gitleaks detect --source . --report-format json --redact` over full history if installed. Without gitleaks, run `git log --all -p -S 'sk_live_' -S 'AKIA' -S 'BEGIN PRIVATE KEY' --oneline` for each prefix from SEC-001, and `git log --all --diff-filter=A --name-only -- '*.env' '*.env.*' '*.pem' '*.p12' '*serviceAccount*.json' 'id_rsa*'` to find secret-bearing files that were ever committed even if later deleted. A hit in any commit that is not the current HEAD state is still a fail. Also check whether the repo is public (`git remote -v` plus `gh repo view --json visibility` if available) — public plus a historical key is critical, private is still a fail.
evidence: commit sha, path, and the secret type (never the full value); repo visibility.
fix_hint: Rotate every exposed credential first, then rewrite history with `git filter-repo --invert-paths --path <file>` (or BFG) and force-push, warning that every collaborator must re-clone. Rotation is mandatory; purging alone is not a fix.

### SEC-003 No secrets in the frontend bundle; public env prefix audit
severity: critical
tier: static
fix: guided
why: Anything under the framework's public env prefix is inlined into JavaScript that every visitor downloads. A service key exposed this way gives strangers the same database access the server has.
verify:
  static: Read stack ref "env vars" for this stack's public prefix (`NEXT_PUBLIC_`, `VITE_`, `EXPO_PUBLIC_`, `NUXT_PUBLIC_`, `REACT_APP_`, `PUBLIC_`). Grep `.env*`, deployment config, CI config, and source for that prefix assigned to anything named like a secret: `SECRET`, `SERVICE_ROLE`, `PRIVATE`, `_KEY` that is not a publishable key, `PASSWORD`, `TOKEN`, `WEBHOOK`, `sk_`, `DATABASE_URL`. Publishable/anon keys (`pk_live_`, Supabase `anon`, Firebase web config) are expected and pass. Then check whether any non-prefixed secret is leaked another way: grep client-side files (components, pages, anything under a `client`/`app`/`src` tree that is not marked server-only) for `process.env.` reads of non-public names. If a build output directory exists (stack ref: "build"), grep it for the SEC-001 provider prefixes and for the values of secret-named variables in `.env`.
evidence: file:line for each public-prefixed secret; grep hits inside build output with file and redacted match; explicitly note the publishable keys you cleared.
fix_hint: Rename the variable without the public prefix, move its only read into server-side code (stack ref: "routes and handlers"), rotate the key, and rebuild so the old bundle is replaced.

### SEC-004 `.env*` ignored; `.env.example` holds no real values
severity: high
tier: static
fix: easy
why: An un-ignored `.env` is the single most common way a production database URL reaches a public repo, and a `.env.example` filled in with real values is the same leak wearing a disguise.
verify:
  static: Read `.gitignore` (and any nested one) and confirm a pattern covering `.env` and `.env.*` with `!.env.example` allowed. Run `git ls-files | grep -E '(^|/)\.env'` — anything tracked other than `.env.example`/`.env.sample`/`.env.template` is a fail. Open the example file and confirm every value is a placeholder (empty, `changeme`, `your-key-here`, `xxx`), not a real-looking key per the SEC-001 prefixes or a hostname with credentials.
evidence: `.gitignore:line` showing the pattern (or its absence); output of the `git ls-files` grep; file:line of any real-looking value in the example file.
fix_hint: Add `.env*` plus `!.env.example` to `.gitignore`, `git rm --cached` any tracked env file, replace real values in the example with placeholders, and rotate anything that was committed.

### SEC-005 CI and Docker do not bake or print secrets; build logs masked
severity: high
tier: static
fix: guided
why: A secret passed as a Docker build arg is stored in the image layer and readable by anyone who pulls it; a secret echoed in CI output is readable by anyone who can view the build log, including forks on public repos.
verify:
  static: Read every CI workflow (`.github/workflows/*.yml`, `.gitlab-ci.yml`, `bitbucket-pipelines.yml`, `circleci/config.yml`) and every `Dockerfile`/`docker-compose*.yml`. Fail on: a literal secret value in the file (SEC-001 patterns); `ARG`/`ENV` in a Dockerfile carrying a secret name and later present in the final image (as opposed to `RUN --mount=type=secret` or a multi-stage build that drops it); `env` or `echo`/`printenv`/`set -x` steps that print secret-named variables; `pull_request_target` or workflows that expose `secrets` to code from forks; `docker-compose` files with inline passwords instead of `env_file`. Confirm secrets come from the platform's secret store (`${{ secrets.X }}`, GitLab masked variables, `--build-arg` sourced from CI secrets is still a fail for images that ship).
evidence: file:line per issue with the offending directive quoted.
fix_hint: Move values into the CI provider's secret store and mark them masked; in Docker use BuildKit `RUN --mount=type=secret` or a multi-stage build so the secret never lands in a shipped layer; delete any `set -x`/`printenv` debugging step.

### SEC-006 Database connection strings not exposed
severity: critical
tier: static
fix: guided
why: A connection string is credentials plus a network address in one line — if it reaches the client bundle, a log, or the repo, the whole database is reachable by anyone who reads it.
verify:
  static: Grep the tree for connection-string shapes: `postgres://`, `postgresql://`, `mysql://`, `mongodb(\+srv)?://`, `redis://`, `amqp://`, `Server=.*Password=`, and for `DATABASE_URL` / `DB_PASSWORD` assigned to a literal. Confirm each hit is either a placeholder in `.env.example`, a localhost dev default, or a read from the environment (stack ref: "env vars"). Then confirm the string is server-only: it must not carry the public env prefix (SEC-003), must not be referenced in client components, and must not appear in build output (stack ref: "build"). Also check logging: grep for the connection variable being passed to a logger or printed at boot (stack ref: "error handling and logging").
evidence: file:line for each occurrence, with credentials redacted, and whether it is env-sourced, a localhost default, or a hardcoded production credential.
fix_hint: Read the URL only from the server-side env loader (stack ref: "env vars"), remove it from any client-reachable module and from boot logging, and rotate the database password if it was ever committed or printed.

### SEC-007 Source maps not publicly served in production
severity: medium
tier: remote
fix: easy
why: A published `.map` file hands over your original server-adjacent source, comments, and internal API shapes, which turns black-box probing into reading the code.
verify:
  static: Read the build configuration (stack ref: "build") for the source-map setting: Next.js `productionBrowserSourceMaps` (must be absent or false), Vite `build.sourcemap` (false or `hidden`), webpack `devtool` in the production config, CRA `GENERATE_SOURCEMAP=false`, Nuxt `sourcemap.client`. Also check whether a `.map` upload step (Sentry, Datadog) is followed by deletion of the files from the deploy artifact.
  remote: Fetch the deployed page HTML (`curl -s <remote.url>`), extract the `src` of each first-party `<script>`, and request each bundle URL with `.map` appended. Expect 404/403. Also fetch one bundle and check whether it ends with a `//# sourceMappingURL=` comment pointing at a URL that resolves. A 200 returning JSON with a `sources` array is a fail.
evidence: `GET /_next/static/chunks/main-abc.js.map → 200 (expected 404)` plus the first source path listed; and the build-config file:line.
fix_hint: Disable production browser source maps in the build config, or keep generating them for the error tracker and delete the `.map` files from the deploy artifact after upload.

### SEC-008 Debug pages, dev tools, and API playgrounds off in production
severity: high
tier: static
fix: easy
why: A debug page or GraphQL playground left on gives an attacker your routes, schema, environment, and often a stack trace with file paths for free.
verify:
  static: Grep for debug switches that are on in production or read from a variable that defaults to on: Django `DEBUG = True` in the production settings module, Rails `config.consider_all_requests_local = true` in `config/environments/production.rb`, Laravel `APP_DEBUG=true` in the deployed `.env` or `config/app.php` default, Flask `app.run(debug=True)` / `FLASK_DEBUG`, Express `errorhandler()` middleware mounted unconditionally, Symfony `_profiler` routes, Next.js `reactStrictMode` is not this check but `/__nextjs` and `/_next/webpack-hmr` in a production build are. Then grep the route table (stack ref: "routes and handlers") for exposed debug endpoints: `/_debug`, `/debug`, `/__nuxt`, `/__vite`, `/_profiler`, `/actuator`, `/admin/queues` without auth, `/graphql` with GraphiQL/Apollo Sandbox enabled unconditionally, `/swagger`, `/api-docs`, `/rails/info`. Each must be either absent from the production build, gated by `NODE_ENV !== 'production'` / equivalent, or behind auth.
  local: Against `local.url` built in production mode if available, request `/graphql` with GET (a rendered playground HTML page is a fail), `/_debug`, `/__nuxt`, `/actuator/env`, `/swagger`, `/api-docs`, `/rails/info/routes`. Expect 404 or 401.
evidence: file:line of the debug flag or ungated route, plus any `GET /graphql → 200 text/html (playground)` probe lines.
fix_hint: Gate the tool on the production environment check used elsewhere in the stack, or remove the middleware/route from the production build; for GraphQL disable the playground and introspection together (see SEC-054).

### SEC-009 Errors do not leak stack traces or internals
severity: high
tier: local
fix: easy
why: A stack trace in an HTTP response tells an attacker your framework version, file layout, ORM, and often the failing SQL — everything needed to aim the next attempt.
verify:
  static: Read the error handler (stack ref: "error handling and logging"). Confirm the response body sent to clients is a generic message plus optionally a correlation id, and that `err.message`, `err.stack`, `str(e)`, `e.getMessage()`, or the raw exception is logged server-side but not serialized into the response. Grep handlers for `res.status(500).json({ error: err.message })`, `return jsonify(str(e))`, `throw` reaching a default framework handler in production, and `console.error` output being echoed to the client.
  local: Against `local.url`, trigger errors and read the bodies: request a route with a deliberately malformed payload (invalid JSON body, wrong type for a required field), request a resource id in an impossible format, and request `/__prelaunch_missing__`. Inspect each response body for file paths (`/Users/`, `/var/www/`, `/app/`), `at Object.<anonymous>`, `Traceback (most recent call last)`, SQL fragments, ORM class names, or dependency version strings. Any of these is a fail.
evidence: `POST /api/x with malformed body → 500` plus the leaking excerpt (first 200 chars); handler file:line.
fix_hint: In the central error handler return a generic body plus a request id and log the full error server-side; make sure the framework's production error page is the one that renders, not the development one.

### SEC-010 Server-side auth check on every protected route, action, and RPC
severity: critical
tier: static
fix: guided
why: A page that only hides its link, or only redirects in a client component, is still served by its API route — the data is one `fetch` away for anyone who reads the bundle.
verify:
  static: Build the list of protected surfaces from stack ref "routes and handlers": API routes, server actions, RPC/tRPC procedures, form endpoints, and rendered pages under an authenticated area. For each, find the server-side session check (stack ref: "auth") — a `getSession`/`auth()`/`requireUser()` call, a middleware matcher that covers the path, a `@login_required`/`before_action :authenticate_user!`, or a `protectedProcedure` base. Fails: a route in the protected area with no check and not covered by a middleware matcher; a check that only happens in a client component or a `useEffect` redirect; a middleware `matcher` whose pattern misses sibling paths (e.g. matches `/dashboard` but not `/api/dashboard`); a check whose result is not returned early (`if (!user) {}` with execution continuing). List every unprotected route explicitly rather than concluding "mostly protected".
  local: Pick three protected routes including at least one API/mutation endpoint and request them with no cookies at all against `local.url`. Expect 401/403 or a redirect to login — never 200 with data.
evidence: table of `route — file:line — checked by <mechanism>` or `route — NO server-side check`; probe lines `GET /api/me (no cookie) → 200 (expected 401)`.
fix_hint: Add the stack's session guard at the top of each unguarded handler, or widen the middleware matcher to cover the missed paths, and prefer a shared `requireUser()` helper over per-handler checks so new routes inherit it.

### SEC-011 Object-level authorization on reads, mutations, and subresources (IDOR)
severity: critical
tier: local
fix: guided
why: Sequential or guessable IDs plus a missing ownership check is the most common way one user reads another user's invoices, messages, or files.
verify:
  static: List every route, server action, or RPC that takes an ID parameter (stack ref: "routes and handlers"). For each, confirm the query is scoped by the current user or org (a `where user_id = session.user.id`, an RLS policy covering the table per DAT-002, or an explicit ownership check) before returning or mutating. Subresources count: `/orders/:id/invoice` must check the order's owner, not just that the order exists.
  local: Using the test account (stack ref: "runtime probe hints" for the auth cookie), create a resource, note its ID, then request it with a second test account or no auth. Expect 401/403/404, never 200 with the first account's data. Try at least one read, one mutation, and one subresource.
evidence: per route: `file:line — scoped by <what>` or `file:line — NOT scoped`; probe lines `GET /api/orders/<id> as other user → 200 (expected 403)`.
fix_hint: Add the ownership predicate to the query in the data access layer (stack ref: "data access") rather than in each handler, or enable the RLS policy that enforces it; re-run the probe.

### SEC-012 Admin routes require an admin role server-side
severity: critical
tier: local
fix: guided
why: Hiding the admin nav link from non-admins is not authorization; a logged-in customer who guesses `/admin` should not be able to read the user table or refund themselves.
verify:
  static: Find every admin surface: routes under `/admin`, handlers named `admin*`, server actions performing destructive or cross-tenant operations, and any query that reads all rows without a user predicate. For each, confirm a server-side role check (stack ref: "auth") — `user.role === 'admin'`, `is_staff`, a `requireAdmin()` guard, an RLS policy keyed on role, or a middleware matcher covering `/admin/:path*`. Fails: the role read from a client-supplied value (a cookie, header, or request body field rather than the session/database); a check on the page but not on the API route it calls; role stored in a JWT claim that the app never re-validates and that users can influence at sign-up.
  local: Sign in as the ordinary test account (stack ref: "runtime probe hints") and request the admin page and at least one admin API endpoint. Expect 403 or a redirect. Then repeat with no session. A 200 with admin data, or a page shell that then fetches admin data successfully, is a fail.
evidence: `route — file:line — role check <mechanism>` per admin surface; probe lines `GET /admin/users as normal user → 200 (expected 403)`.
fix_hint: Add the role guard to the admin API handlers as well as the pages, reading the role from the session or database rather than a client-controlled value; a single `requireAdmin()` helper applied in one place is preferable.

### SEC-013 Internal and sensitive endpoints locked down
severity: high
tier: local
fix: guided
why: Health, metrics, queue dashboards, and internal tooling routes are written for operators and assumed private; served publicly they expose environment variables, job payloads, and often a trigger button.
verify:
  static: Enumerate operational endpoints in the route table and framework config (stack ref: "routes and handlers"): `/health`, `/healthz`, `/metrics`, `/status`, `/actuator/*`, `/admin/queues`, Bull/Sidekiq/Celery dashboards (stack ref: "background jobs"), `/api/internal/*`, seed/migrate/reset endpoints, feature-flag or config dump routes, and anything mounted from an ops library. For each, note whether it is unauthenticated and what it returns. A liveness probe returning `{"ok":true}` is acceptable unauthenticated; anything returning versions, env, queue contents, DB status detail, or accepting a mutation is not.
  local: Request each of those paths against `local.url` with no credentials and record status plus a body excerpt. Any 200 exposing internals or accepting a state-changing request is a fail.
evidence: `GET /metrics (no auth) → 200` with the first line of the body; file:line where the endpoint is mounted.
fix_hint: Put internal endpoints behind the same session/role guard as admin routes, or bind them to an internal-only path with a shared-secret header (see SEC-014); reduce the public health endpoint to a bare liveness response.

### SEC-014 Cron and internal job endpoints require a secret
severity: high
tier: static
fix: easy
why: A cron route that anyone can hit is a free way to re-send emails, re-charge jobs, or hammer your queue; scheduler platforms call these over the public internet, so obscurity is the only thing protecting them by default.
verify:
  static: Find scheduled and job-trigger endpoints (stack ref: "background jobs" and "routes and handlers"): `vercel.json` `crons` entries, `/api/cron/*`, `/api/jobs/*`, `/api/tasks/*`, GitHub Actions or scheduler configs that curl a URL, Supabase/Cloudflare scheduled functions. For each handler, confirm the first statements compare a request header or query secret against an env value — `CRON_SECRET`, `Authorization: Bearer`, Vercel's `x-vercel-signature`, an HMAC — and return 401 on mismatch before doing any work. Fails: no check; a check against a hardcoded string; a check that runs after the job has already started; comparison with `==`/`===` on a secret (also flag under SEC-052).
evidence: handler file:line with the guard quoted, or `file:line — no secret check`; the list of cron paths found in scheduler config.
fix_hint: Add an early guard that compares the `Authorization` header against the `CRON_SECRET` environment value and returns 401 on mismatch (constant-time compare per SEC-052), and set the same secret in the scheduler's request headers.

### SEC-015 Rate limiting on auth, forms, expensive operations, and API
severity: high
tier: local
fix: guided
why: Without a limiter, one script can exhaust your email quota, your AI spend, or your database connections in minutes, and password guessing becomes a matter of patience.
verify:
  static: Look for a limiter (Upstash Ratelimit, express-rate-limit, `rack-attack`, `django-ratelimit`, `slowapi`, Cloudflare/WAF rules, an API gateway policy) and list which paths it covers. The endpoints that must be covered: login, sign-up, password reset, OTP/magic-link send, contact and other public forms, email/SMS send, AI or LLM calls, data export or report generation, and search. For each of those that exists in this app, record whether it is limited, by what key, and with what window. A global limiter with a very high ceiling (e.g. 1000/min per IP) does not count as protection for login.
  local: Against `local.url`, send 20 rapid requests to the login endpoint with a wrong password and 20 to one unauthenticated public form or expensive endpoint. Expect a 429 (or a documented lockout) before request 20. All 20 returning 200/401 is a fail. Use the test account's identifiers only.
evidence: `POST /api/login x20 → 20x401, no 429 (expected 429)`; limiter config file:line and the covered path list.
fix_hint: Apply the existing limiter (or add the stack's standard one) to each uncovered endpoint with a per-endpoint budget — tight on auth and send-email routes, looser on read APIs — keyed per SEC-016.

### SEC-016 Rate limit keyed correctly behind proxy; only trusted forwarded headers
severity: medium
tier: static
fix: easy
why: Behind a CDN every request arrives from the proxy's IP, so an IP-keyed limiter either throttles all users as one or, if it trusts a client-set `X-Forwarded-For`, can be bypassed by changing one header per request.
verify:
  static: Find where the limiter derives its key (SEC-015) and where the app reads the client IP. Correct: the platform's verified header (`CF-Connecting-IP` on Cloudflare, `X-Vercel-Forwarded-For`/`request.ip` on Vercel, `X-Real-IP` set by your own nginx), or the leftmost untrusted entry of `X-Forwarded-For` combined with a trust-proxy hop count. Fails: `req.headers['x-forwarded-for']` used raw with no trust configuration; `app.set('trust proxy', true)` with no hop limit while also keying on the forwarded header; Django `USE_X_FORWARDED_HOST`/`SECURE_PROXY_SSL_HEADER` set without a proxy actually stripping it. Also confirm auth limiters key on the account identifier (email/user id) in addition to IP, so a distributed guessing attack against one account is still caught.
evidence: file:line of the key derivation and of the proxy-trust setting, with the expression quoted.
fix_hint: Key the limiter on the CDN's verified client-IP header for this platform and set the framework's trust-proxy hop count to the real number of proxies; add the account identifier as a second key on auth routes.

### SEC-017 Brute-force protection on login, reset, and OTP
severity: high
tier: local
fix: guided
why: A six-digit OTP with unlimited attempts is guessed in under a million tries, which is minutes for a script; password spraying against a known email list needs even fewer.
verify:
  static: In the auth code (stack ref: "auth"), look for per-account failure counting: a `failed_attempts` column or cache counter, a lockout window, exponential backoff, or a managed provider's built-in protection (Auth0, Clerk, Supabase Auth, Cognito — name it and its configured threshold if visible). For OTP/magic-link verification, confirm the code has a max attempt count and is invalidated after it, plus a short expiry (SEC-021). Fails: only an IP-based limiter (bypassed by rotating IPs); a counter that resets on every successful request from that IP; OTP verification with no attempt cap.
  local: Against `local.url`, attempt login for the test account with 15 wrong passwords in a row, then attempt with the correct password. Expect lockout, a challenge, or a delay before attempt 15; if the correct password succeeds immediately after 15 failures with no delay, that is a fail. If OTP exists, submit 15 wrong codes for one issued code and confirm the code is burned.
evidence: `POST /login wrong password x15 → all 401, correct password → 200 immediately (no lockout)`; auth code file:line for any counter found.
fix_hint: Add per-identifier failure counting with a lockout or exponential delay in the auth handler (or enable the provider's brute-force setting), and invalidate an OTP after a small number of wrong attempts.

### SEC-018 No account enumeration via login, reset, or sign-up responses
severity: medium
tier: local
fix: easy
why: A different message for "no such user" than "wrong password" lets anyone turn an email list into a confirmed customer list — useful for phishing and for targeting the accounts worth attacking.
verify:
  static: Read the login, password-reset, and sign-up handlers (stack ref: "auth") and compare the responses on the unknown-account and wrong-credential paths: status code, message text, and any field-level error. Reset should always respond "if that address exists we sent a link". Sign-up should not say "email already registered" in the public response unless the product deliberately accepts that trade-off — note it either way. Also check for timing branches that short-circuit before the password hash comparison for unknown users.
  local: Against `local.url`, POST login with the test account's email plus a wrong password, then with a random non-existent address plus any password; compare status, body, and rough response time. Repeat for password reset and sign-up. Different status codes or distinguishable messages are a fail.
evidence: the two response bodies side by side with statuses, e.g. `known+wrong → 401 "Incorrect password" / unknown → 404 "No account found"`.
fix_hint: Return one identical generic response for both branches in the login and reset handlers, and run the password hash comparison (or a dummy one) even when the user is not found so timing does not distinguish them.

### SEC-019 Passwords hashed with bcrypt/argon2/scrypt
severity: critical
tier: static
fix: guided
why: A breach with plaintext or reversibly encrypted passwords hands over every account here and every site where the user reused that password; a fast hash like SHA-256 is cracked at billions of guesses per second.
verify:
  static: Find where a password is written and where it is compared (stack ref: "auth", "data access"). Confirm the hash function is `bcrypt`, `argon2id`, `scrypt`, or PBKDF2 with a high iteration count, applied server-side. Check the cost factor: bcrypt rounds >= 10, argon2 memory/time at defaults or higher. Fails: `md5`, `sha1`, `sha256`/`sha512` used directly on the password; any `encrypt`/`decrypt` pair applied to a password; a password column compared with `=` against the submitted value; a password stored anywhere besides the hash column (a log line, an audit table, a `password_plain` field, an email body). If the stack delegates auth to a provider (stack ref: "auth"), confirm no local password column exists at all and record that.
evidence: file:line of the hash call with the algorithm and cost, or file:line of the plaintext/weak-hash write; the password column definition from the schema.
fix_hint: Switch to argon2id or bcrypt via the stack's standard library, and migrate existing users by re-hashing on next successful login (verify against the old scheme once, then store the new hash); never attempt to convert stored plaintext silently without forcing a reset.

### SEC-020 Max password length; email case and unicode normalization
severity: low
tier: static
fix: easy
why: bcrypt silently truncates at 72 bytes and an unbounded password field is a cheap CPU denial-of-service; unnormalized emails let `User@x.com` and `user@x.com` become two accounts, which breaks reset and invites confusion.
verify:
  static: In the sign-up and password-change validation (stack ref: "auth"), confirm a maximum password length (roughly 64–128 characters; anything unbounded when using bcrypt is a fail) alongside the minimum. In user lookup and creation, confirm the email is lowercased and trimmed before both the uniqueness check and the login lookup — and that the same normalization is applied on both paths, since normalizing only on sign-up still allows a mismatched login. Check for a unique index on the normalized column. If unicode identifiers are accepted, note whether NFKC normalization is applied.
evidence: file:line of the length rule (or its absence) and of the email normalization on each of the create and lookup paths; the unique index definition.
fix_hint: Add a max-length rule to the password schema and a shared `normalizeEmail()` used by sign-up, login, and reset, backed by a unique index on the lowercased column.

### SEC-021 Reset and verify tokens single-use, expiring, and never logged
severity: high
tier: static
fix: guided
why: A reset token that stays valid after use, or for days, is a permanent backdoor into the account for anyone who ever sees the email — including a forwarded mail, a support ticket, or a log aggregator.
verify:
  static: Find the reset/verify token issue and consume paths (stack ref: "auth"). Confirm: the token is generated with a CSPRNG (`crypto.randomBytes`, `secrets.token_urlsafe`, `SecureRandom.urlsafe_base64`) and at least 128 bits, never `Math.random()` or a sequential id; an expiry column is set and checked on consume (minutes to an hour, not days); the token row is deleted or marked used inside the same transaction as the password change, so a replay fails; the comparison is constant-time or the token is looked up by hash (see SEC-052). Then grep for the token reaching a log or analytics call (stack ref: "error handling and logging") and for it appearing in a redirect URL that a third-party script could read via `document.referrer`. Fails: no expiry check, token reusable, token stored in plaintext in a widely readable table with no other control, token logged.
evidence: file:line for generation, expiry check, and invalidation-on-use; any log call carrying the token.
fix_hint: Store a hash of the token with an `expires_at`, check both on consume, and delete the row in the same transaction as the password update; strip tokens from log output.

### SEC-022 Reset and verify links built from a configured origin, not the Host header
severity: high
tier: static
fix: easy
why: If the email link is built from the incoming `Host`, an attacker requests a reset with a spoofed host and the victim's real token arrives as a link to the attacker's domain.
verify:
  static: Find where the reset/verify/magic-link email body is composed (stack ref: "auth", "routes and handlers") and trace the base URL. It must come from a configured value — `NEXT_PUBLIC_APP_URL`, `APP_URL`, `SITE_URL`, `settings.SITE_URL`, `default_url_options` — not from `req.headers.host`, `request.get_host()`, `request.url`, `$_SERVER['HTTP_HOST']`, or `X-Forwarded-Host`. If the framework derives URLs from the host by default (Django, Rails), confirm `ALLOWED_HOSTS` / `config.hosts` is a real allowlist rather than `['*']`. Also check any redirect target embedded in the link against SEC-029.
evidence: file:line of the base-URL expression with the source named; the ALLOWED_HOSTS / hosts setting value.
fix_hint: Read the origin from the configured app-URL environment variable in the email builder, and tighten the framework's allowed-hosts list so host-derived URLs cannot be spoofed.

### SEC-023 Email verification required before sensitive actions
severity: medium
tier: static
fix: guided
why: Without verification anyone can sign up as someone else's address, and unverified accounts become the vector for spam, abuse of free credits, and confused password resets later.
verify:
  static: Determine whether the product requires a verified email and for what (stack ref: "auth"). Find the `email_verified`/`confirmed_at` field and grep for where it is checked. The actions that should require it: inviting others, sending outbound email on the user's behalf, publishing public content, consuming paid or free-tier credits, changing the account email, and any team/org join. Record which of the app's sensitive actions check the flag and which do not. A product that deliberately allows unverified use (note it) still needs verification before outbound email and before the address is trusted for password reset.
evidence: field name and file:line of each check found; the list of sensitive actions with `verified check: yes/no`.
fix_hint: Add the verified-email predicate to the guard used by the sensitive handlers (the same place as the session check), and re-send the verification mail from the blocked path so the user can proceed.

### SEC-024 MFA available for admin accounts
severity: medium
tier: attest
fix: none
why: Admin accounts are the highest-value target and a single reused password is usually all that stands behind them; a second factor is the difference between a phished password and a breach.
verify:
  attest: Determine whether a second factor is available and enabled for accounts with admin privileges. If auth is delegated to a provider (stack ref: "auth"), check whether MFA/2FA is configured in that provider's settings or SDK usage (`mfa`, `totp`, `enrollMFA`, `webauthn`, Clerk/Auth0/Supabase MFA calls). If auth is local, look for a TOTP/WebAuthn implementation and an enforcement path for admin roles. Then ask the user, or record as unconfirmed: is MFA actually turned on for every human admin account today, including any provider console (hosting, database, email, payments) that shares the blast radius? Code showing MFA machinery exists is `attest` with machinery found; no machinery and no provider support is `attest` with the gap stated plainly.
evidence: what machinery was found (file:line or provider setting) and what could not be confirmed — specifically whether real admin accounts have it enrolled.
### SEC-025 Session cookies HttpOnly, Secure, SameSite
severity: high
tier: local
fix: easy
why: A session cookie readable by JavaScript turns any XSS into full account takeover, and one without SameSite or Secure can be replayed cross-site or captured on a plain-HTTP hop.
verify:
  static: Find the cookie configuration (stack ref: "auth"): `cookies().set` options, `res.cookie` options, `SESSION_COOKIE_*` in Django settings, `config.session_store` in Rails, the auth library's cookie options. Required: `httpOnly: true`, `secure: true` in production, `sameSite` `lax` or `strict` (`none` is only acceptable with a stated cross-site need and always with `secure`), a `path` of `/`, and a sensible `maxAge` (SEC-026). Fails: any auth token stored in `localStorage` or a non-HttpOnly cookie — grep for `localStorage.setItem` with a token-like key.
  local: Against `local.url`, log in with the test account and read the `Set-Cookie` headers from the response (`curl -si`). Confirm each session/auth cookie carries `HttpOnly`, `Secure`, and `SameSite=`. Missing attributes on the session cookie are a fail; note that `Secure` may legitimately be absent on plain-HTTP localhost — in that case rely on the static check of the production config.
evidence: the raw `Set-Cookie` line(s) with values redacted; cookie-config file:line.
fix_hint: Add the missing attributes to the cookie options in the auth config (and move any token out of `localStorage` into an HttpOnly cookie); gate `secure` on the production environment so local development still works.

### SEC-026 Session expiry, rotation on login, invalidation on logout and password change
severity: high
tier: static
fix: guided
why: A session that never expires and survives a password change means a stolen token stays valid forever — the user's "I changed my password" does nothing about the attacker already inside.
verify:
  static: In the session layer (stack ref: "auth") confirm four behaviors and cite each: (1) an absolute or idle expiry is configured (`maxAge`, `SESSION_COOKIE_AGE`, JWT `exp`) and is not measured in months; (2) the session identifier is regenerated at login (`req.session.regenerate`, `reset_session`, `request.session.cycle_key()`, a new token issued rather than the pre-auth one reused) — its absence is session fixation; (3) logout deletes the server-side session record or revokes the token, not only the cookie — a stateless JWT with no denylist means logout is cosmetic, note that explicitly; (4) changing a password or email invalidates other sessions (a `session_version`/`tokens_valid_after` bump, `revokeRefreshTokens`, deleting the user's session rows).
evidence: file:line for each of the four behaviors, marked present or absent.
fix_hint: Set a finite session lifetime, regenerate the session id inside the login handler, delete the server-side session on logout, and bump a per-user session-version claim on password change so older tokens fail validation.

### SEC-027 JWT algorithm pinned, expiry set, strong secret, refresh rotation
severity: high
tier: static
fix: guided
why: A verifier that accepts whatever `alg` the token declares can be handed an `alg: none` or an HMAC forged with the public key; a weak HMAC secret is brute-forced offline in hours.
verify:
  static: Find every JWT sign and verify call (stack ref: "auth"). Confirm: verify passes an explicit `algorithms: ['RS256']` / `algorithm=` allowlist rather than defaulting; `alg: none` is impossible; the HMAC secret comes from the environment and is long and random, never a literal like `"secret"`, `"changeme"`, or a short word (also flag under SEC-001); `exp` is set on every issued token and actually checked (`ignoreExpiration` must not be true); `aud`/`iss` are validated when the token comes from a third-party issuer; refresh tokens, if used, are rotated on use and the old one is invalidated (reuse detection). Fails: `jwt.decode()` used where `jwt.verify()` was meant — grep for `decode(` on an incoming token and confirm the result is not trusted for authorization.
evidence: file:line for each of algorithm pinning, expiry, secret source, and refresh rotation, with the call quoted.
fix_hint: Pass an explicit algorithm allowlist to every verify call, set a short access-token `exp` with rotating refresh tokens, and replace any short or literal HMAC secret with a 256-bit random value from the environment (rotating invalidates existing tokens — plan for that).

### SEC-028 OAuth uses state, PKCE, and a redirect URI allowlist
severity: high
tier: static
fix: guided
why: Without `state` an attacker can graft their own OAuth response onto a victim's session (login CSRF); without a redirect allowlist the authorization code can be delivered to a domain the attacker controls.
verify:
  static: Find the OAuth/OIDC flow (stack ref: "auth"). If it is handled by a library (NextAuth/Auth.js, Passport, Devise/OmniAuth, Authlib, Supabase Auth, Clerk), confirm the library version does state and PKCE by default and that no option disables them (`checks: []`, `state: false`, `pkce: false`). If it is hand-rolled: confirm a random `state` is generated, stored server-side or in a signed cookie, and compared on callback; that `code_challenge`/`code_verifier` (PKCE, S256) is used for any public client; that the `redirect_uri` sent is a constant from config, not built from a request parameter; and that the callback validates the returned `state` before exchanging the code. Also check the provider console values if visible in config: the registered redirect URIs should be exact production URLs, not wildcards or `http://localhost` left in the production app.
evidence: file:line for state generation and comparison, PKCE usage, and the redirect_uri source; the configured redirect URI list.
fix_hint: Use the library's built-in state and PKCE checks rather than a hand-rolled flow, build `redirect_uri` from configuration only, and remove wildcard or localhost redirect URIs from the production OAuth client.

### SEC-029 No open redirect via next/return/redirect parameters
severity: medium
tier: local
fix: easy
why: A link on your own domain that bounces to an attacker's login page is the ideal phishing bait — the user checks the domain, sees yours, and trusts what follows.
verify:
  static: Grep for redirect targets built from request input: `searchParams.get('next'|'redirect'|'redirectTo'|'returnTo'|'return_url'|'callbackUrl'|'url'|'continue')`, `request.GET.get('next')`, `params[:return_to]`, then `redirect(...)`/`res.redirect(...)`/`window.location =` with that value. For each, confirm validation: the value must be rejected unless it is a relative path starting with a single `/` (and not `//` or `/\`), or a member of an explicit allowlist of hosts. A check for `startsWith('http')` alone is insufficient — `//evil.com` and `/\evil.com` still redirect off-site.
  local: Against `local.url`, request the login (and any other redirect-taking route) with `?next=https://example.com`, `?next=//example.com`, and `?next=/\example.com`. Follow one hop and inspect the `Location` header. A `Location` pointing off-origin is a fail.
evidence: `GET /login?next=//example.com → 302 Location: //example.com (expected same-origin)`; validation file:line or its absence.
fix_hint: Validate the parameter with a helper that accepts only paths matching `^/(?!/|\\)` (or an explicit host allowlist) and falls back to a default destination, then apply it everywhere a redirect parameter is read.

### SEC-030 CSRF protection on state-changing endpoints
severity: high
tier: static
fix: guided
why: With cookie-based sessions and no CSRF defense, a page the user visits elsewhere can silently POST to your app as them — changing their email, deleting data, or sending money.
verify:
  static: First determine the session mechanism (stack ref: "auth"). If auth rides on cookies, every state-changing endpoint needs a defense: a synchronizer token (`csrfToken` hidden field verified server-side, Django `CsrfViewMiddleware`, Rails `protect_from_forgery with: :exception`, Laravel `VerifyCsrfToken`), a double-submit cookie, or `SameSite=Lax|Strict` on the session cookie combined with rejecting cross-site simple requests. If auth is a bearer token in an `Authorization` header only (never a cookie), CSRF does not apply — say so and confirm no cookie fallback exists. Then look for opt-outs: `csrf_exempt`, `skip_before_action :verify_authenticity_token`, `$except` entries in the CSRF middleware, `csrf: false` in config — each must be justified (webhook endpoints legitimately exempt, since they authenticate by signature per SEC-051). Framework server actions (Next.js) have built-in origin checks; confirm the version rather than assuming.
evidence: the protection mechanism with file:line, plus a list of every exemption and its justification.
fix_hint: Re-enable the framework's CSRF middleware globally and exempt only signature-verified webhook paths; where the app is API-only, ensure the session is not readable as an ambient cookie.

### SEC-031 Content-Security-Policy present and not trivially bypassable
severity: medium
tier: local
fix: guided
why: CSP is the backstop that turns a successful XSS into a blocked script instead of a stolen session; a policy that allows `unsafe-inline` on scripts blocks essentially nothing.
verify:
  static: Find where response headers are set (stack ref: "security headers") and read the CSP: framework middleware, `next.config.js` headers, `helmet`, `nginx.conf`, `_headers`, `vercel.json`. Judge the policy: a `script-src` that is `*`, or includes `'unsafe-inline'` without a nonce/hash companion, or `'unsafe-eval'` with no stated need, is a fail. A policy delivered only as `Content-Security-Policy-Report-Only` is a fail — it enforces nothing; say so explicitly. Also confirm `object-src 'none'` and a `base-uri` restriction, and that `frame-ancestors` is present (it is the modern replacement for X-Frame-Options, see SEC-033).
  local: Run `python3 scripts/probe_url.py <local.url>` and read `pages["/"].headers["content-security-policy"]`. No header at all is a fail; grade the value by the rules above. Cross-check with `content-security-policy-report-only`.
evidence: the full header value as returned by the probe, plus the config file:line that sets it, and the specific directive that fails.
fix_hint: Set an enforcing policy in the stack's header config, starting from `default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'` and adding the specific origins the app actually loads; use per-request nonces rather than `'unsafe-inline'`.

### SEC-032 HSTS with a sensible max-age
severity: medium
tier: remote
fix: easy
why: Without HSTS the very first request to `http://` can be intercepted and downgraded before the redirect ever happens; the header tells the browser never to try plain HTTP again.
verify:
  static: Look for the header in the stack's header configuration (stack ref: "security headers") — `Strict-Transport-Security`, `helmet.hsts`, `SECURE_HSTS_SECONDS` in Django, `config.force_ssl` in Rails, or the platform's automatic HSTS (some hosts add it at the edge, in which case only the remote check can confirm).
  remote: Run `python3 scripts/probe_url.py <remote.url>` and read `pages["/"].headers["strict-transport-security"]`. Pass requires `max-age` of at least 15552000 (180 days). Absent header, or `max-age=0`, or a max-age of a few hours, is a fail. Note whether `includeSubDomains` and `preload` are present — their absence is a note, not a fail, unless subdomains serve the same session cookie.
evidence: the header value from the probe (or `absent`), plus the config file:line if set in code.
fix_hint: Add `Strict-Transport-Security: max-age=31536000; includeSubDomains` in the stack's header config or enable it at the CDN; only add `preload` once every subdomain is HTTPS-only, because preload is hard to undo.

### SEC-033 nosniff, frame-ancestors, Referrer-Policy, Permissions-Policy set
severity: medium
tier: local
fix: easy
why: These four headers each close a cheap attack: MIME sniffing that turns an upload into script, clickjacking your own dashboard inside an attacker's iframe, leaking full URLs (with tokens) to third parties via Referer, and silently granting camera or geolocation to embedded frames.
verify:
  static: Read the header configuration (stack ref: "security headers") and note which of the four are set and where.
  local: Run `python3 scripts/probe_url.py <local.url>` and read `pages["/"].headers`. Require: `x-content-type-options: nosniff`; clickjacking protection via CSP `frame-ancestors` (in the `content-security-policy` value) or `x-frame-options: DENY|SAMEORIGIN`; `referrer-policy` set to `strict-origin-when-cross-origin`, `same-origin`, or `no-referrer` (`unsafe-url` is a fail); `permissions-policy` present and at minimum disabling the features the app does not use (`camera=(), microphone=(), geolocation=()`). Report each of the four separately as present/absent so the fix is scoped.
evidence: each header name with its value or `absent`, taken from the probe output.
fix_hint: Add the missing headers in the one place the stack already sets headers (middleware, `next.config.js` headers, helmet, or the CDN rules) rather than per route.

### SEC-034 HTTPS enforced with redirect; no mixed content
severity: high
tier: remote
fix: easy
why: A page served over HTTP exposes the session cookie to anyone on the network path, and a single `http://` script tag on an HTTPS page is either blocked or, if allowed, a way to inject code.
verify:
  static: Look for the redirect: `config.force_ssl = true`, `SECURE_SSL_REDIRECT`, middleware redirecting on `x-forwarded-proto !== 'https'`, or the host platform's automatic HTTPS (name it). Grep templates, components, and CSS for hardcoded `http://` resource URLs (`src=`, `href=` to stylesheets, `url(` in CSS, fetch/axios calls) that are not localhost or a documentation link.
  remote: Run `python3 scripts/probe_url.py <remote.url>` and check `pages["/"].redirects` for the `http://` → `https://` hop; separately request the site over `http://` and confirm a 301/308 to HTTPS. Fetch the HTTPS page HTML and grep for `http://` in `src`/`href` attributes pointing at loadable subresources — each is mixed content and a fail.
evidence: `GET http://host/ → 301 https://host/` or the missing redirect; file:line and URL of each mixed-content reference.
fix_hint: Turn on the platform's or framework's force-HTTPS redirect, and change hardcoded `http://` subresource URLs to `https://` (or to protocol-relative paths served from your own origin).

### SEC-035 CORS not wildcard; credentials handling correct
severity: high
tier: local
fix: easy
why: `Access-Control-Allow-Origin` reflecting any origin together with credentials lets any website read your authenticated API responses using the visitor's own session.
verify:
  static: Find the CORS configuration (middleware, `cors()` options, `CORS_ALLOWED_ORIGINS`, `rack-cors`, platform header rules). Fails: `origin: '*'` or `origin: true` on an API that serves authenticated data; an origin function that echoes back `req.headers.origin` without checking it against an allowlist; a regex allowlist that is not anchored (`/mysite\.com/` also matches `mysite.com.evil.com`); `credentials: true` combined with a reflected origin. A truly public read-only endpoint may use `*` — but then it must not accept cookies.
  local: `probe_url.py` cannot set an `Origin` header, so use curl here. Against `local.url`, send a request to an authenticated API endpoint with `Origin: https://evil.example` and inspect the response headers: `curl -si -H 'Origin: https://evil.example' <local.url>/api/<authenticated endpoint>`. `access-control-allow-origin: https://evil.example` or `*` alongside `access-control-allow-credentials: true` is a fail. Repeat as an OPTIONS preflight.
evidence: `OPTIONS /api/x with Origin: https://evil.example → access-control-allow-origin: https://evil.example` plus the config file:line.
fix_hint: Replace the wildcard or reflection with an explicit allowlist of your own origins compared by exact string, and only set `credentials: true` for those.

### SEC-036 Authenticated responses marked private and not CDN-cacheable
severity: medium
tier: local
fix: easy
why: One user's dashboard cached at the CDN and served to the next visitor is a data breach with no attacker involved; it happens whenever a personalized response carries a public cache header.
verify:
  static: Find where cache headers are set for authenticated pages and API routes (stack ref: "routes and handlers", "security headers"): `Cache-Control` values, Next.js `revalidate`/`force-static` on pages that read the session, `s-maxage` in `vercel.json`, CDN page rules. Any route that reads the session must send `Cache-Control: private, no-store` (or at least `private, no-cache`) and must not be statically rendered.
  local: `probe_url.py` sends no cookies, so use curl with the test account's session here. Against `local.url`, request an authenticated page and an authenticated API endpoint with the test account's cookie and read the response headers: `cache-control`, `vary`, and any CDN header (`x-vercel-cache`, `cf-cache-status`, `age`). Fail on `public`, `s-maxage` > 0, `max-age` > 0 without `private`, a missing `Vary: Cookie` where caching is allowed, or a CDN header reporting `HIT` for a personalized response.
evidence: `GET /dashboard (authed) → cache-control: public, s-maxage=3600` plus the config file:line.
fix_hint: Set `Cache-Control: private, no-store` on session-reading routes (in the shared handler or middleware) and mark those pages dynamic so the framework does not pre-render or edge-cache them.

### SEC-037 Server-side schema validation on all inputs
severity: high
tier: static
fix: guided
why: Client validation is a UX feature, not a control — every field can be re-sent with curl, so anything the server accepts unvalidated is what an attacker actually gets to send.
verify:
  static: For every endpoint that accepts a body, query, or route parameter (stack ref: "routes and handlers"), find the server-side validation: a schema (`zod`, `yup`, `valibot`, `joi`, pydantic, `marshmallow`, DRF serializer, Rails strong parameters plus model validations, Laravel FormRequest) parsed before the value is used. Record endpoints with none. Fails: reading `req.body.x` straight into a query or a write; validation only in the React form and not in the handler; a schema declared but never `.parse()`d (grep for `safeParse` results whose `success` is never checked); numeric and enum fields accepted as arbitrary strings; `any`-typed handler input relied on because TypeScript types are erased at runtime. Pay attention to fields that control behavior: `role`, `plan`, `price`, `isAdmin`, `status`, `userId`.
evidence: per endpoint `file:line — validated by <schema>` or `file:line — unvalidated`; call out any behavior-controlling field accepted from the body.
fix_hint: Define one schema per endpoint and parse at the top of the handler, returning 400 on failure; derive the handler's types from the schema so an unvalidated field is a type error rather than a silent hole.

### SEC-038 No SQL built by string concatenation
severity: critical
tier: static
fix: guided
why: One concatenated user value is enough to dump every table or drop them; SQL injection remains the fastest total compromise of an application.
verify:
  static: Grep for raw SQL construction across the data layer (stack ref: "data access"): template literals or `+` inside `query(...)`, `execute(...)`, `raw(...)`, `$queryRawUnsafe`, `sequelize.query`, `knex.raw`, `db.exec`, `cursor.execute("... %s" % ...)` or f-strings in Python, `find_by_sql("... #{...}")` in Rails, `DB::select("... $var")` in Laravel. For each hit, trace whether the interpolated value comes from request input or from a trusted constant. Parameterized forms pass: `$1` placeholders with an args array, `?` with bindings, `Prisma.sql` tagged templates, `text=` with `params=`. Also check dynamic identifiers (table/column names) which cannot be parameterized — those must come from a hardcoded allowlist, never from input (see SEC-040).
evidence: file:line of each raw query with the interpolation quoted and the source of the value (`request body`, `constant`, `internal id`).
fix_hint: Replace the interpolation with the driver's parameter binding (placeholders plus a values array, or the ORM's tagged-template helper); for dynamic identifiers map the user's choice through a fixed allowlist object.

### SEC-039 NoSQL operator injection prevented
severity: critical
tier: static
fix: guided
why: In MongoDB a JSON body of `{"password": {"$ne": null}}` matches every document, so a login query built from an unvalidated body logs in as the first user in the collection.
verify:
  static: Find queries built from request input against a document store (stack ref: "data access"): `collection.find(req.body)`, `findOne({ email, password })` where either value comes straight from the body, Mongoose queries taking spread request objects, Firestore `where(field, op, value)` with `field` or `op` from input. Confirm each user-supplied value is coerced to its expected primitive type (a schema per SEC-037, `String(x)`, a pydantic model) before it reaches the query, or that the driver is configured to reject operator keys (`sanitizeFilter`, `express-mongo-sanitize`). Fails: a body object passed wholesale into a query; a value used without type coercion where a `$`-prefixed key would be honoured; query parameters parsed as objects (`?filter[$ne]=`) with the extended query parser enabled.
evidence: file:line of each query with the input path traced, and whether a schema or sanitizer stands between them.
fix_hint: Parse the request into a typed schema and pass only the coerced scalars into the query, or enable the driver's filter sanitization so `$`-prefixed keys from input are stripped.

### SEC-040 ORM dynamic where/order/select never built from raw user input
severity: high
tier: static
fix: guided
why: A sort or filter parameter fed straight into the ORM lets a caller order by a password hash, join in a table they should not see, or select columns you never intended to expose.
verify:
  static: Grep for query fragments assembled from input: `orderBy: req.query.sort`, `[Op[req.query.op]]`, `order(params[:sort])`, `select(req.query.fields)`, `where: JSON.parse(req.query.filter)`, Prisma/Drizzle objects spread from the request, `.filter(**request.GET.dict())` in Django, `whereRaw` with interpolation. For each, confirm the value passes through an allowlist — an object mapping permitted sort keys to column references, an enum in the validation schema (SEC-037), or a switch. A regex like `/^[a-z_]+$/` on a column name is weaker than an allowlist and should be noted. Also confirm relation includes/`populate` from input cannot pull in restricted relations.
evidence: file:line of each dynamic fragment with the allowlist quoted, or noted as absent.
fix_hint: Map the request value through a fixed dictionary of allowed sort/filter/select keys and reject anything not in it, rather than passing the string into the query builder.

### SEC-041 No mass assignment; request body never saved wholesale
severity: high
tier: static
fix: easy
why: `update(user.id, req.body)` lets a user set `role: "admin"`, `credits: 999999`, or `stripeCustomerId` on themselves — the field does not need to be in your form for the database to accept it.
verify:
  static: Grep for whole-object writes: `create(req.body)`, `update({ data: req.body })`, `...req.body` spread into a model, `Object.assign(entity, req.body)`, `Model(**request.data)`, `User.new(params[:user])` without `permit`, `$model->fill($request->all())`, `save(**form.cleaned_data)` where the form is unbounded. For each, confirm the write uses an explicit field list, a validated schema whose shape excludes privileged fields, `permit(:a, :b)`, `$fillable`/`$guarded`, or a DTO. Then list the privileged columns in the schema (`role`, `is_admin`, `plan`, `credits`, `balance`, `verified`, `org_id`, `stripe_*`, `created_at`, `id`) and confirm none is reachable from any write path.
evidence: file:line of each wholesale write, and the list of privileged columns with whether a write path can reach them.
fix_hint: Pick fields explicitly from the validated schema before writing (`{ name, bio }` rather than the body), and add the privileged columns to the ORM's guarded list as a second layer.

### SEC-042 API responses expose only the fields they need
severity: high
tier: static
fix: guided
why: Returning the whole user row ships the password hash, reset token, internal notes, and other users' emails to the browser — the UI does not render them, but the network tab does.
verify:
  static: For each endpoint returning entity data (stack ref: "routes and handlers", "data access"), check whether it selects fields explicitly or returns the model as-is (`res.json(user)`, `return user`, `serializers.ModelSerializer` with `fields = '__all__'`, `render json: @user`, `->toArray()`). For every as-is return, list the model's columns from the schema and flag any of: password/hash, reset or verification tokens, `stripe_*` secrets, API keys, internal flags, soft-delete or moderation notes, other users' PII carried through a join or `include`, and raw sequential internal ids where the API otherwise uses public ids. Also check list endpoints that `include` related records for over-fetching relations belonging to other users.
evidence: per endpoint `file:line — returns model wholesale, leaking <columns>` or `file:line — selects <fields>`.
fix_hint: Add an explicit `select`/serializer per endpoint listing exactly the fields the client renders, defined once per entity and reused, so new columns are private by default.

### SEC-043 XSS: user content never rendered as raw HTML
severity: critical
tier: static
fix: guided
why: One stored script in a display name or comment runs in every viewer's session, and with a JavaScript-readable token that is instant account takeover across your whole user base.
verify:
  static: Grep for every raw-HTML sink and audit each one's input: `dangerouslySetInnerHTML`, `v-html`, `{@html }` (Svelte), `innerHTML =`, `outerHTML =`, `insertAdjacentHTML`, `document.write`, `html_safe` / `raw()` (Rails), `|safe` / `mark_safe` / `autoescape off` (Django/Jinja), `{!! !!}` (Blade), `<%= raw %>`, `Html.Raw`, `element.setHTML` without a sanitizer config. For each, trace the value: a hardcoded string or build-time content passes; anything derived from user input, a database column, or a third-party API must go through a sanitizer (DOMPurify, `sanitize-html`, `bleach`, Rails `sanitize`) with a restrictive allowlist, and a Markdown renderer must have raw HTML disabled (`marked` with sanitize is deprecated — look for DOMPurify after render). Also check attribute sinks: `href={userValue}` allowing `javascript:` URLs, and `style`/`srcdoc` from input. Note CSP as a mitigation only (SEC-031), never as the fix.
evidence: file:line of each sink with the value's origin and the sanitizer applied, or `unsanitized user input`.
fix_hint: Sanitize at render with an allowlist-based sanitizer, or stop using the raw sink and render text; for Markdown, disable raw HTML in the parser and sanitize the output HTML.

### SEC-044 No template injection, eval, or unsafe deserialization of user input
severity: critical
tier: static
fix: guided
why: Each of these turns data into code on your server — `eval` on a request value, a template compiled from user text, or a pickle/YAML load of an uploaded blob is remote code execution, not a bug.
verify:
  static: Grep for the sinks and trace their input: `eval(`, `new Function(`, `setTimeout`/`setInterval` with a string argument, `vm.runInNewContext`, `child_process.exec`/`execSync` with an interpolated string, `os.system`, `subprocess` with `shell=True`, `exec(`, `Kernel#system` with interpolation, `require(variable)`/dynamic `import(variable)`; template compilation from a variable (`Handlebars.compile(userString)`, `ejs.render(userString)`, `Template(user_input)` in Jinja, `render_template_string`, `ERB.new(user_input)`); deserialization (`pickle.loads`, `yaml.load` without `SafeLoader`, `Marshal.load`, PHP `unserialize`, Java `readObject`, `JSON.parse` is fine but `eval`-based parsing is not). Every hit must be fed only a constant or a value from a fixed allowlist. For shell calls prefer argument arrays over a shell string — flag any interpolation into a shell command.
evidence: file:line of each sink, the exact expression, and where its input comes from.
fix_hint: Replace the sink with a safe equivalent — an argument-array `spawn` instead of an interpolated `exec`, `yaml.safe_load`, a precompiled template with the user value as a variable rather than as template source — and remove `eval` entirely.

### SEC-045 SSRF: server fetches only allowlisted hosts
severity: high
tier: static
fix: guided
why: A URL parameter your server fetches becomes a window into your private network — cloud metadata at 169.254.169.254 hands out instance credentials, and internal admin services usually have no auth at all.
verify:
  static: Find every server-side fetch whose URL is influenced by input: `fetch(url)`, `axios.get(url)`, `requests.get(url)`, `HTTParty`, `curl_exec`, plus the features that hide one — image proxy/resizer, link preview and OG scraping, webhook-out or "callback URL" settings, HTML-to-PDF and screenshot rendering, RSS/import-by-URL, avatar-from-URL, and any integration where the user supplies a base URL. For each, confirm: the URL is parsed and its host checked against an allowlist (not a `startsWith`/substring test, which `https://evil.com/?x=https://allowed.com` defeats); the scheme is restricted to http/https (no `file:`, `gopher:`, `dict:`); redirects are not followed blindly to a new host; and private ranges are blocked after DNS resolution (127.0.0.0/8, 10/8, 172.16/12, 192.168/16, 169.254/16, `::1`, and `localhost`). Note that the app running behind a cloud provider with IMDSv1 raises the severity of any gap.
evidence: file:line of each outbound fetch with the URL's origin and the validation performed, or `no host validation`.
fix_hint: Route these fetches through one helper that parses the URL, enforces an https-only scheme, resolves the host and rejects private/link-local addresses, checks an allowlist where one is possible, and disables automatic redirect following.

### SEC-046 Path traversal prevented on file reads and downloads
severity: high
tier: static
fix: easy
why: A filename parameter joined onto a directory lets `../../.env` or `../../../etc/passwd` be downloaded through your own file endpoint.
verify:
  static: Grep for filesystem access built from input: `fs.readFile`/`createReadStream`/`sendFile`/`res.download` with a path containing a request value, `path.join(dir, req.query.file)`, `open(os.path.join(...))`, `File.read`, `send_file`, `Storage::get($request->...)`, and static-file middleware rooted at a user-controlled directory. For each, confirm the input is validated: an allowlist or database lookup that maps an id to a stored path (best), or normalization plus a containment check (`const p = path.resolve(base, name); if (!p.startsWith(base + path.sep)) reject`). Fails: stripping `../` by replacement (defeated by `....//`); checking the raw string before decoding (`%2e%2e%2f`); `path.join` with no containment check; allowing absolute paths to override the base. Also check archive extraction for zip-slip (entry names joined onto a destination without containment).
evidence: file:line of each file access with the input path and the containment check quoted, or noted absent.
fix_hint: Look the file up by database id and use the stored path, or resolve the joined path and reject anything that does not start with the base directory after normalization.

### SEC-047 Upload validation: extension allowlist, content sniffing, size limit
severity: critical
tier: local
fix: guided
when: features.uploads
why: An upload endpoint that trusts the filename or the client-sent content type is how a web shell gets onto your server; even without execution, an unbounded upload fills your disk or your storage bill.
verify:
  static: Read the upload handler (stack ref: "file uploads"). Confirm: an extension allowlist (not a denylist), a MIME check based on the file's own magic bytes (`file-type`, `python-magic`, `Marcel`, `mime_content_type` on the stored file) rather than the client's `Content-Type` header, a maximum size enforced server-side, and a maximum count per request. Fails: validation only in the browser; trusting `file.mimetype` from multipart headers; a denylist of `.php`/`.exe`; no size limit (see SEC-067); double-extension names accepted (`shell.php.jpg`); the original filename used as the stored name (see SEC-048).
  local: Against `local.url` with the test account, attempt three uploads and record the responses: (1) a file named `photo.jpg` whose bytes begin with `<?php system($_GET[0]); ?>` — expect rejection, since a real content sniff sees text, not an image; (2) a file named `shell.php.jpg` with valid JPEG magic bytes — expect rejection or storage under a rewritten, non-executable name; (3) a file larger than the documented limit — expect 413 or a validation error, not a timeout. Any 200 that stores file (1) as an image is a fail.
evidence: `POST /api/upload photo.jpg (php content) → 200, stored at <url>` plus the handler file:line for each missing control.
fix_hint: Validate in the handler by sniffing magic bytes against an extension allowlist, enforce a byte limit before buffering the whole file, and reject anything whose sniffed type does not match its extension.

### SEC-048 Uploads stored non-executable, on a separate origin, with sanitized filenames
severity: high
tier: static
fix: guided
when: features.uploads
why: A file served from your own origin can run scripts in your session context, and one written into a web-served directory with its original name can be executed by the server that hosts it.
verify:
  static: Read the storage path (stack ref: "file uploads"). Confirm: files go to object storage (S3/R2/GCS/Supabase Storage) or a directory outside the web root, never into `public/`/`static/` where the app server would execute or serve them directly; the stored key is generated (UUID or hash) rather than taken from the user's filename, with the original name kept only as metadata; if a filename is reused, it is sanitized (path separators, `..`, null bytes, leading dots, control characters and non-ASCII stripped or encoded); the serving origin is a separate domain or a storage host, not the app origin, so a stored HTML/SVG file cannot script against the app's cookies; and the response sets `Content-Disposition: attachment` plus `X-Content-Type-Options: nosniff` for user files that are not images.
evidence: file:line of the storage call showing the key generation and destination; the serving origin; the disposition/nosniff headers if set in code.
fix_hint: Store under a generated key in object storage and serve from the storage domain (or a dedicated user-content subdomain) with `nosniff` and an attachment disposition for non-image types.

### SEC-049 SVG uploads sanitized or blocked; images re-encoded
severity: medium
tier: static
fix: easy
when: features.uploads
why: An SVG is a document that can carry `<script>`, so an "image" upload is an XSS upload unless it is sanitized; and image parsers are a long-running source of memory-corruption CVEs.
verify:
  static: In the upload validation (stack ref: "file uploads") check whether `image/svg+xml` and `.svg` are in the accepted set. If accepted, confirm the file is sanitized server-side (DOMPurify with an SVG profile, `svg-sanitizer`, `sanitize-svg`) or served with `Content-Disposition: attachment` from a separate origin so it cannot execute against the app. If images are re-encoded (sharp, Pillow, ImageMagick, imgproxy), that strips embedded payloads and passes — confirm the re-encode happens before storage, not just on display. Then check the image library version against known advisories (see SEC-057), particularly ImageMagick policy files (`policy.xml` should disable `MSL`, `MVG`, `EPHEMERAL`, `URL`, `HTTPS` coders) and any `sharp`/`libvips` version pinned in the lockfile.
evidence: file:line showing whether SVG is accepted and how it is handled; the image library and version from the lockfile; the ImageMagick policy state if used.
fix_hint: Drop SVG from the accepted types, or sanitize it with an SVG-aware sanitizer before storing; re-encode raster uploads through the image library so metadata and payloads are dropped.

### SEC-050 Private files served via signed, expiring URLs
severity: high
tier: static
fix: guided
when: features.uploads
why: A permanent public URL to a private document is a credential anyone can forward, and guessable object keys mean a stranger can walk the bucket.
verify:
  static: Find how uploaded files are served (stack ref: "file uploads", "data access"). For files that are not intended to be public, confirm the bucket is private (see DAT-005) and access goes through a signed URL with a short expiry (`getSignedUrl` with an `expiresIn` of minutes to an hour, `createSignedUrl`, a CloudFront signed URL, a Rails `expires_in` blob URL) or a server route that checks ownership before streaming. Fails: public-read buckets holding user documents; signed URLs with multi-day or year-long expiries; a "private" file protected only by a random path with no expiry; a signing endpoint that issues a URL for any key the caller names without an ownership check (that is an IDOR — cross-reference SEC-011).
evidence: file:line of the signing call with its expiry; the bucket ACL setting; the ownership check before signing, or its absence.
fix_hint: Make the bucket private and issue short-lived signed URLs from a server route that first verifies the requester owns the object, rather than storing long-lived public links.

### SEC-051 Webhook signature verification on every webhook handler
severity: critical
tier: local
fix: guided
why: An unverified webhook endpoint accepts a POST from anyone, so a stranger can announce a successful payment, a completed subscription, or a delivered order and your app will believe it.
verify:
  static: List every inbound webhook route (stack ref: "webhook handlers") — payments, email delivery, auth provider, storage, queue, CI, and any partner integration. For each, confirm the handler verifies the provider's signature before doing any work, using the provider's own library where one exists (`stripe.webhooks.constructEvent`, `svix`, `@octokit/webhooks`, Twilio `validateRequest`) — see stack ref "webhook verification snippet" for the shape on this stack. Check three things that commonly break verification: the raw request body must be used, not a re-serialized parsed object (grep for `express.json()` applied before the webhook route, or a framework that parses the body by default); the signing secret must come from the environment and be the live-mode one for production; and a timestamp tolerance must be enforced so old requests cannot be replayed. Also confirm the handler is idempotent (a duplicate delivery must not double-credit).
  local: Against `local.url`, POST to each webhook path a plausible provider payload with a signature header that is present but wrong, and again with the header absent. Expect 400/401 both times. A 200 — or any sign the payload was processed — is a fail. Use test-mode payloads only; never replay a real event.
evidence: `POST /api/webhooks/stripe with bad signature → 200 (expected 400)` plus handler file:line showing verification present or absent.
fix_hint: Verify with the provider's SDK against the raw body at the top of the handler and return 400 on failure; disable body parsing for that route so the raw bytes survive, and store the event id to make retries idempotent.

### SEC-052 Constant-time comparison for tokens and signatures
severity: medium
tier: static
fix: easy
why: A byte-by-byte `===` on a secret leaks how many leading characters matched through response timing, which is enough to recover an API key or signature over many requests.
verify:
  static: Find every comparison of a secret value: cron secrets (SEC-014), API keys, webhook signatures verified by hand, reset/verify tokens (SEC-021), invite codes, and admin passphrases. Each should use a constant-time function — `crypto.timingSafeEqual`, `hmac.compare_digest`, `ActiveSupport::SecurityUtils.secure_compare`, `hash_equals` — or a database lookup by hashed value (which sidesteps the issue). Fails: `===`, `==`, `.equals()`, or `strcmp` on a secret; `timingSafeEqual` called on buffers of different lengths without a guard (it throws, which is itself a length oracle — a length check on the token format first is fine).
evidence: file:line of each secret comparison with the operator or function used.
fix_hint: Swap the equality operator for the runtime's constant-time compare, normalizing both sides to fixed-length buffers (or comparing hashes) first.

### SEC-053 ReDoS on user-input regexes; archive limits; XXE disabled
severity: medium
tier: static
fix: easy
why: One catastrophically backtracking regex on a crafted 50-character input pins a CPU core indefinitely; an XML parser with external entities enabled reads local files for whoever uploads a document.
verify:
  static: Three sweeps. (1) Regexes: grep for patterns applied to request input containing nested quantifiers or overlapping alternation — `(a+)+`, `(.*)*`, `(\w+\s?)*`, long email/URL validators copied from the internet — and for `new RegExp(userValue)`, which lets the caller supply the pattern. (2) Archives and decompression: any `unzip`, `tar` extraction, or gzip decode of user input must cap the entry count, the uncompressed size, and the compression ratio; unbounded extraction is a zip bomb. (3) XML: any XML parse of user input (`libxmljs`, `xml2js`, `lxml`, `SAXParser`, `DocumentBuilderFactory`, PHP `simplexml`) must disable DTD/external entities — `resolve_entities=False`, `noent` off, `setFeature(disallow-doctype-decl, true)`, `libxml_disable_entity_loader`; also applies to SVG parsing and to any office-document or feed importer.
evidence: file:line for each risky regex with the pattern quoted, each unbounded extraction, and each XML parser with its entity setting.
fix_hint: Replace the backtracking pattern with a linear one or a non-regex check and never compile a pattern from user input; cap decompressed size and entry count before extracting; pass the parser's no-external-entities option everywhere XML is read.

### SEC-054 GraphQL: introspection off in production; depth and complexity limits
severity: high
tier: static
fix: easy
when: features.graphql
why: Introspection publishes your entire schema including internal mutations, and without depth limits one deeply nested query multiplies into millions of resolver calls — a denial of service in a single request.
verify:
  static: Read the GraphQL server setup (stack ref: "routes and handlers"). Confirm in production: `introspection: false` (or the framework's equivalent), the playground/sandbox disabled (see SEC-008), a depth limit (`graphql-depth-limit`, `@apollo/server` plugin, Yoga's `maxDepth`), a cost/complexity limit, an alias or batching cap (arrays of operations and repeated aliased fields both multiply work), and a query-size or timeout guard. Also confirm field-level authorization exists — GraphQL bypasses route-level guards, so every resolver returning user data needs its own check (cross-reference SEC-010, SEC-011). Persisted queries in production are a strong pass for the DoS half; note them if present.
  local: Against `local.url`, POST an introspection query (`{__schema{types{name}}}`) and a deliberately nested query about 12 levels deep. A full schema in the response or a completed deep query is a fail.
evidence: `POST /graphql {__schema...} → 200 with type list (expected error)`; config file:line for each limit found or missing.
fix_hint: Set `introspection` to false outside development and add the depth and complexity plugins to the server config, with a batching cap; add per-resolver authorization where field checks are missing.

### SEC-055 Realtime and websocket channels authorized per user
severity: high
tier: static
fix: guided
when: features.realtime
why: Realtime channels are usually named after the resource, so without a server-side subscribe check any client can subscribe to another org's channel and stream their messages live.
verify:
  static: Find the realtime layer (Supabase Realtime, Pusher/Ably, Socket.IO, Phoenix Channels, Firebase listeners, a raw `ws` server) and locate the authorization point: the channel-auth endpoint (`/pusher/auth`, `/broadcasting/auth`), the `join`/`subscribe` handler, or the RLS policies backing the realtime publication. Confirm the server verifies the connecting user's session and their right to that specific channel or row, and that the check uses the session identity rather than a user id sent by the client. Fails: an auth endpoint that signs any channel name it is given; Socket.IO handlers that read `socket.handshake.query.userId` as identity; presence channels leaking member lists across tenants; Supabase Realtime enabled on a table whose RLS does not restrict select (cross-reference DAT-001); broadcast payloads that include fields the recipient is not allowed to see even when the channel is right.
evidence: file:line of the subscribe/auth handler with the check quoted, and the channel naming scheme; note any channel whose name is fully guessable.
fix_hint: Authorize inside the channel-auth handler against the session's user and the channel's owning resource, and rely on RLS for row-level realtime rather than on channel naming.

### SEC-056 Third-party script inventory; SRI on static third-party scripts
severity: medium
tier: remote
fix: easy
why: Every third-party script runs with full access to your pages, so a compromised analytics or widget vendor becomes a compromise of your checkout; SRI makes a swapped file fail closed.
verify:
  static: Grep templates, layouts, and components for external `<script src=`, injected script tags, tag managers, and any `next/script`/`svelte:head` usage. Build the inventory: vendor, purpose, and whether it loads on every page or only where needed. Note any script from a domain the team does not recognize.
  remote: Run `python3 scripts/probe_url.py <remote.url>`, then fetch the page HTML (`curl -s <remote.url>`) and list every `<script>` with a cross-origin `src`. For each pinned-version script from a CDN (cdnjs, jsdelivr, unpkg), require an `integrity=` attribute plus `crossorigin="anonymous"`. Scripts whose vendor requires a mutable URL (Google Tag Manager, Stripe.js, Intercom) cannot use SRI — record them as accepted risk with the vendor name rather than as failures, and confirm the CSP (SEC-031) names them explicitly.
evidence: the script inventory as `vendor — url — SRI yes/no/not-possible`; the specific tags missing `integrity` where it is possible.
fix_hint: Add `integrity` and `crossorigin` to pinned CDN script tags (or self-host the file), remove vendors no one owns, and list the remaining third-party origins explicitly in the CSP.

### SEC-057 Dependency audit: no known critical/high vulnerabilities; lockfile committed
severity: high
tier: static
fix: guided
why: Most breaches at this size come through a dependency someone else already found and published a fix for; without a committed lockfile you also cannot say which versions production actually runs.
verify:
  static: Confirm a lockfile is committed for each ecosystem present (`package-lock.json`/`pnpm-lock.yaml`/`yarn.lock`, `poetry.lock`/`requirements.txt` pinned, `Gemfile.lock`, `composer.lock`, `go.sum`, `Cargo.lock`) — `git ls-files` it, since an ignored lockfile is a common miss. Then run the ecosystem's audit and read the summary: `npm audit --omit=dev --json`, `pnpm audit --prod`, `pip-audit`, `bundler-audit check --update`, `composer audit`, `govulncheck ./...`. Report critical and high advisories with the package, installed version, fixed version, and whether the vulnerable path is production or dev-only. Dev-only advisories are a note, not a fail. If the tool is unavailable offline, say so and fall back to reading the lockfile for packages with well-known unfixed advisories, marking the finding `static-fallback`.
evidence: the audit tool's summary line plus one line per critical/high advisory (`package@version — CVE/GHSA — fixed in X — prod/dev`); lockfile paths confirmed tracked.
fix_hint: Run the ecosystem's fix command for the non-breaking upgrades, handle the majors individually, and commit the updated lockfile; where no fix exists, record the exposure and whether the vulnerable code path is reachable.

### SEC-058 Email header injection prevented in contact and notification forms
severity: medium
tier: static
fix: easy
when: features.email_sending
why: A newline in a user-supplied name or subject can inject `Bcc:` headers, turning your contact form into an open relay for spam sent from your verified domain — which is how a sending reputation dies.
verify:
  static: Find every place mail is composed from user input (stack ref: "routes and handlers", "background jobs"): contact forms, invite emails, share-by-email, notification subjects. Confirm user values are not concatenated into header fields — `from`, `replyTo`, `to`, `cc`, `bcc`, `subject` — without stripping CR/LF, and that the recipient list is server-controlled rather than taken from the request. Modern SDKs (Resend, Postmark, SendGrid, SES) pass headers as JSON and are safe by construction — note that as the pass reason; raw SMTP composition, PHP `mail()` with a fifth argument, or template-built header blocks are where injection lives. Also confirm the reply-to address is validated as a single address and that the user cannot control `from`.
evidence: file:line of each mail call, the fields carrying user input, and the sanitization or the SDK that makes it safe.
fix_hint: Pass user values only as body content or as SDK header parameters (never string-concatenated), strip `\r` and `\n` from any value that reaches a header, and keep the recipient list server-side.

### SEC-059 Admin actions and impersonation audit-logged
severity: medium
tier: static
fix: guided
why: When an admin account is misused — by an attacker or by a person — an audit trail is the only way to know what was touched; impersonation without logging means support can read any account with no record at all.
verify:
  static: Find the admin action handlers (SEC-012) and any impersonation / "log in as user" feature. Confirm each destructive or cross-tenant action writes an audit record with actor id, target, action, timestamp, and request context, to a store that ordinary application code cannot delete (an append-only table, a separate log sink). Check that impersonation sessions are marked as such in the session and that the log records both the real admin and the impersonated user. Fails: no audit table at all; `console.log` used as the audit trail (stack ref: "error handling and logging") with no retention; audit rows written by the same code path that can also delete them with no restriction; sensitive values (passwords, tokens) copied into the audit payload.
evidence: the audit table or sink with file:line of the write; the list of admin actions with `logged: yes/no`; whether impersonation is recorded.
fix_hint: Write an audit row from the shared admin handler (or a middleware wrapping admin routes) capturing actor, target, action and timestamp, and flag impersonated sessions so their actions are attributable to the real admin.

### SEC-060 Default admin credentials changed; no seed users with known passwords in production
severity: critical
tier: attest
fix: guided
why: A seeded `admin@example.com / password123` account is the first thing an attacker tries, and seed scripts get run against production more often than anyone admits.
verify:
  attest: Read the seed and fixture files (`prisma/seed.*`, `db/seeds.rb`, `seeders/`, `fixtures/`, migration files, docker-compose init scripts, `Makefile` targets) and list every user account they create with the password used. Then check whether the seed can run in production: is it guarded by an environment check, is it part of the deploy or start command, does the production database plausibly contain those rows? Also check any admin panel or self-hosted dependency shipped with the app (a database UI, a queue dashboard, Keycloak, a CMS) for documented default credentials. Because whether production actually contains these accounts cannot be proven from the repo, record what you found and state clearly what the user must confirm: that no seeded account exists in the production database and that any real admin password is unique and strong.
evidence: file:line of each seeded account with its literal password; whether the seed is environment-guarded; the exact question the user must answer about the production database.
fix_hint: Guard the seed script on a non-production environment check, remove hardcoded passwords from it, and have the user query the production database for the seeded addresses and delete or reset any that exist.

### SEC-061 Teams: org-scoped role checks; invites expire; removal revokes access
severity: critical
tier: local
fix: guided
when: features.teams
why: In a multi-tenant app the org id is the security boundary; a query that checks the role but not the org lets a member of one company act as admin inside another, and a removed employee who keeps a working session is a breach with a name attached.
verify:
  static: In the team/org code (stack ref: "auth", "data access"), confirm three things. (1) Every authorization check tests both membership of the specific org in the request and the role within that org — grep for role checks that read a global `user.role` instead of the membership row, and for queries filtered by `user_id` but not `org_id` (or vice versa). (2) Invites carry an expiry and a single-use token (SEC-021 applies), are bound to the invited email rather than accepting any signed-in user, and the invite endpoint checks that the inviter may invite at that role — a member must not be able to invite themselves as owner. (3) Removal deletes the membership row and invalidates the removed user's sessions or forces a permission re-read on every request; a role or org list cached in a long-lived JWT means removal takes effect only at expiry — call that out with the token lifetime.
  local: With two test accounts in different orgs against `local.url`: request an org-scoped resource of org A while authenticated as the member of org B (expect 403/404), attempt an admin-only mutation in org A as a non-admin member (expect 403), and, if the app allows it, accept an invite link with an account other than the invited address (expect rejection).
evidence: probe lines with org ids, e.g. `GET /api/orgs/<A>/members as member of B → 200 (expected 403)`; file:line for each of the three static checks.
fix_hint: Resolve the membership row (org + role) once per request in a shared helper and authorize from it rather than from a global role field; expire invites, bind them to the invited email, and clear cached claims on removal.

### SEC-062 Third-party API keys scoped to minimum, server-only, rotatable
severity: medium
tier: static
fix: guided
why: An over-scoped key turns a small leak into a large one — a full-access token for your email or payments provider does far more damage than a send-only or read-only one, and a key nobody knows how to rotate stays leaked.
verify:
  static: Build an inventory of third-party keys from `.env.example`, deployment config, and SDK initialization (stack ref: "env vars"). For each: which provider, where it is used, whether it is server-only (must not carry the public prefix — SEC-003), and what scope it plausibly has. Look for restricted-key usage where the provider offers it: Stripe restricted keys rather than the secret key, Supabase anon key on the client with the service-role key server-only (DAT-004), a send-only email API key, GitHub fine-grained tokens, scoped S3 IAM policies rather than an admin key. Also check that each key is read from the environment in exactly one place so rotation is a one-value change, and note any key with no expiry or rotation story.
evidence: table of `provider — env var — server-only? — scope observed or unknown — read at file:line`.
fix_hint: Issue restricted or scoped keys per provider for the operations the app actually performs, keep them server-side behind a single accessor per key, and record where each is rotated.

### SEC-063 Bot protection on sign-up, login, and public forms
severity: high
tier: local
fix: guided
why: Unprotected sign-up is a free resource for spam accounts, and unprotected public forms become the outbound spam and abuse channel that gets your sending domain and IP blocked.
verify:
  static: Look for a challenge on the public entry points (stack ref: "routes and handlers"): Cloudflare Turnstile, hCaptcha, reCAPTCHA, or an equivalent, plus any WAF bot rules. Critically, confirm the token is verified server-side — a widget rendered in the form with no `siteverify`/`/turnstile/v0/siteverify` call in the handler is decoration. List which of sign-up, login, password reset, and each public form is covered. Also check disposable-email handling if the product gives away anything free: a blocklist, an MX check, or a verification requirement (SEC-023) before the free resource is granted. Note honeypot fields and rate limits (SEC-015) as partial mitigations where no challenge exists.
  local: Against `local.url`, submit the sign-up form and one public form via direct POST with no challenge token at all (curl, not the browser). A 200 that creates the account or sends the message is a fail — it proves the token is not verified server-side.
evidence: `POST /api/signup without turnstile token → 201 created (expected 400)`; handler file:line showing the siteverify call or its absence.
fix_hint: Verify the challenge token server-side at the top of the handler and reject on failure; add the challenge to the uncovered forms and pair it with the rate limits from SEC-015.

### SEC-064 No tokens, secrets, or PII in URLs or query strings
severity: medium
tier: static
fix: easy
why: URLs are logged everywhere — server logs, proxy logs, browser history, and the `Referer` header sent to every third-party script — so a token in a query string leaks to places you do not control and cannot purge.
verify:
  static: Grep for sensitive values placed in URLs: `?token=`, `?api_key=`, `?key=`, `?password=`, `?email=`, `?session=`, `?access_token=` in fetch calls, redirects, link builders, and email templates; and route definitions that put an email or a raw token in the path. Magic-link and reset URLs necessarily carry a token — for those, confirm the token is single-use and short-lived (SEC-021), that the landing page consumes it and redirects to a clean URL, and that the page carries `Referrer-Policy` (SEC-033) so third-party scripts on it cannot read the token from the referrer. Also check the logging configuration (stack ref: "error handling and logging") for full-URL logging with query strings and whether sensitive parameters are redacted, and check analytics/error-tracker initialization for URL scrubbing.
evidence: file:line for each sensitive parameter in a URL, and the logger's URL-redaction setting.
fix_hint: Move the value into a POST body or an `Authorization` header; where a link must carry a token, exchange it for a session on landing and immediately replace the URL, and add the parameter to the logger's redaction list.

### SEC-065 Version-disclosing headers removed
severity: low
tier: remote
fix: easy
why: `X-Powered-By: Express` or a Server header with an exact version tells a scanner which published exploits to try first; removing it is not security, but it costs nothing and shortens the list.
verify:
  static: Look for the header being disabled in config (stack ref: "security headers"): `app.disable('x-powered-by')`, `poweredByHeader: false` in `next.config.js`, `helmet.hidePoweredBy()`, `server_tokens off` in nginx, `expose_php = Off`.
  remote: Run `python3 scripts/probe_url.py <remote.url>` and read `pages["/"].headers` for `x-powered-by`, `server`, `x-aspnet-version`, `x-generator`, and `x-drupal-*`. A `server` value naming only the CDN (`cloudflare`, `Vercel`) is fine; one carrying a version (`nginx/1.18.0`, `Apache/2.4.41 (Ubuntu)`) or `x-powered-by` at all is a fail.
evidence: the offending header names and values from the probe output; the config file:line if a disable is present but ineffective.
fix_hint: Disable the framework's powered-by header in config and set the reverse proxy or CDN to strip or overwrite `Server`.

### SEC-066 No sensitive paths publicly served
severity: critical
tier: remote
fix: easy
why: A served `.git` directory hands over your entire source and history including any secret ever committed, and a served `.env` hands over production credentials directly — both are found by automated scanners within hours of going live.
verify:
  static: Check what the deployment actually publishes: the static/public directory contents (`git ls-files public/ static/ dist/`), `.dockerignore` and `.vercelignore`/`.gcloudignore` for `.git` and `.env` exclusions, the web-server root configuration, and whether directory listing is enabled (`autoindex on` in nginx, `Options +Indexes` in Apache, a static middleware with directory listing). Flag any backup, dump, or config file inside a served directory: `*.sql`, `*.bak`, `*.zip`, `.DS_Store`, `config.json` with real values, `phpinfo.php`.
  remote: Run `python3 scripts/probe_url.py <remote.url>` and read `sensitive_paths`. It covers `/.git/HEAD`, `/.env`, `/backup.sql`, `/config.json`, `/.DS_Store`, `/phpinfo.php`, `/server-status`. Any status of 200 is a fail — check the body to be sure it is the real file and not a 200-returning SPA fallback (`/.git/HEAD` should contain `ref: refs/heads/`; `/.env` should contain `KEY=value` lines). Also request one directory path (e.g. `/uploads/`) and confirm it does not return a file listing.
evidence: each path with its status from the probe, plus a short body excerpt for any 200 proving it is the real file rather than an SPA fallback.
fix_hint: Exclude `.git`, `.env`, and backup artifacts from the deployment artifact (ignore files and build config), block those paths at the web server or CDN, disable directory listing, and rotate every credential that a served `.env` exposed.

### SEC-067 Request body size limits enforced
severity: medium
tier: static
fix: easy
why: Without a body limit, a single request with a hundred-megabyte JSON payload can exhaust memory on the instance parsing it — a denial of service that needs no vulnerability, just bandwidth.
verify:
  static: Find the body-parser configuration for each entry point: `express.json({ limit })` / `body-parser` (default 100kb — an explicit larger value needs justification), `bodyParser.sizeLimit` in Next.js API route config, `DATA_UPLOAD_MAX_MEMORY_SIZE` and `FILE_UPLOAD_MAX_MEMORY_SIZE` in Django, `client_max_body_size` in nginx, `post_max_size`/`upload_max_filesize` in PHP, the platform's own request limit (Vercel, Cloudflare Workers — name it, since it may be the only limit). Confirm upload routes have a deliberate limit matching SEC-047 rather than an unbounded stream, and that multipart parsing enforces a per-file and total size cap before writing to disk. Fails: `limit: '50mb'` set globally to make one upload route work; a raw-body webhook route reading the whole stream with no cap; no limit anywhere and no platform limit.
evidence: file:line of each limit with its value, plus the platform default where it applies; note any route that opts out.
fix_hint: Set a small global body limit and raise it only on the specific routes that need it, and cap multipart uploads at the parser before the bytes are buffered.
