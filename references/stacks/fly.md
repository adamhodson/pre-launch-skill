# Fly.io

## detection signals
`fly.toml` at the repo root — the defining signal — usually alongside a `Dockerfile` (or a `.dockerignore`, or a `[build] builder` line naming a buildpack). `.fly/` if `fly launch` generated helper scripts. `fly` or `flyctl` in a CI workflow (`superfly/flyctl-actions`), and a `FLY_API_TOKEN` in repository secrets. Multiple `fly.*.toml` files mean multiple apps (a web app plus a worker, or a staging app), each deployed with `fly deploy -c <file>`.

Fly is **not serverless**: it runs your container as a long-lived process on Firecracker microVMs ("Machines"). That single fact changes the answer to a large number of checks — there is no function timeout, no request body ceiling imposed by the platform, no per-invocation CPU budget, and no cold start unless machine auto-stop is enabled. Say that explicitly where a check assumes a serverless shape (PERF-020, PERF-016); "not applicable, this is a long-lived server" is the correct finding and is more useful than a blank.

Runtime environment variables Fly injects, which are the fastest way to detect the platform from inside a running process:

| variable | value |
|---|---|
| `FLY_APP_NAME` | the app name |
| `FLY_MACHINE_ID` | this machine's id |
| `FLY_REGION` | the region this machine is in |
| `FLY_PUBLIC_IP` / `FLY_PRIVATE_IP` | the machine's addresses; the private one is a 6PN IPv6 address |
| `PRIMARY_REGION` | set by `fly launch`, and read by frameworks that do read-replica routing |
| `FLY_PROCESS_GROUP` | which `[processes]` entry this machine is running |

There is **no built-in environment marker** distinguishing production from staging — a staging deployment is simply a different app, so the convention is a separate app name plus an explicit `[env] ENVIRONMENT = "staging"`. A project without one has no way for code to tell where it is running, which is worth flagging on its own (HYG-001, DAT-017).

## dev server
Fly has no local development mode of its own; local development is whatever the framework does, and the closest Fly-specific equivalent is running the same container locally:

```bash
docker build -t app-local .           # the exact image Fly will run
docker run --rm -p 8080:8080 --env-file .env.local app-local
```

That is worth doing at least once before launch, because the container is where the difference between "works on my machine" and "works in production" actually lives — a missing system package, a wrong `WORKDIR`, an app bound to `127.0.0.1` instead of `0.0.0.0`.

Fly's own tooling for reaching a deployed app:

```bash
fly status                            # machines, regions, health, current release
fly logs                              # live log stream
fly ssh console                       # a shell inside a running machine
fly ssh console -C "printenv"         # the process's real environment — including secrets
fly proxy 5432 -a <postgres app>      # tunnel a private service to localhost over WireGuard
fly machine list
fly config show                       # the resolved configuration Fly actually has
```

`fly ssh console` gives a root shell inside production. It is the most useful diagnostic on the platform and the most dangerous thing in this file — use it read-only, and note that the fact it works at all means anyone with deploy access to the Fly org has a shell in production (ACC-001).

`fly config show` is better than reading `fly.toml`, because the deployed configuration can differ from the file in the working tree.

**Do not measure production performance from `fly proxy` or a WireGuard tunnel** — you are adding a VPN hop. Measure against the public hostname.

## build
Two paths, and which one is in use decides whether ACC-008 applies:

- **A `Dockerfile`** in the repo (the common case, and what `fly launch` generates for most stacks). Fly builds it remotely by default (`fly deploy` uses a remote builder machine) or locally with `--local-only`.
- **A buildpack** — `[build] builder = "paketobuildpacks/builder:base"` or similar in `fly.toml`, with no Dockerfile. Fly also supports `[build] image = "..."` to deploy a prebuilt image directly.

```bash
ls Dockerfile Containerfile docker-compose*.yml 2>/dev/null
grep -n -A10 '^\[build\]' fly.toml
fly deploy --build-only                    # build without releasing (still consumes a builder)
fly image show                             # what image the app is currently running
```

**ACC-008 lives here.** Where a `Dockerfile` exists, five things, and `fly launch`'s generated Dockerfiles frequently fail the first:

1. **`USER`** — a non-root user in the **final** stage, created earlier by `adduser`/`useradd`/`addgroup` or supplied by the base image (the `node` image's `node` user, `python`'s absence of one). No `USER` at all means root. `USER root` as the last one means root. A `USER` set in a build stage but not carried into the final stage does nothing — that is the one that reads as correct and is not. Fly's generated Dockerfiles for several stacks run as root, so assume it until you have read the file.
2. **Base image** — a pinned tag or digest, and a slim/distroless/alpine variant where the runtime allows. `FROM node:latest` is unpinned and unreproducible (REL-013).
3. **Secrets in layers** — `ARG`/`ENV` carrying a token, a `COPY . .` that pulls in `.env` because `.dockerignore` does not exclude it, an `npm config set //registry.../:_authToken` baked into a layer. Every one of those is readable with `docker history` or by extracting the layer, in the final image, forever. BuildKit's `--mount=type=secret` (and `fly deploy --build-secret`) is the shape that does not persist. Check `.dockerignore` exists and excludes `.env*`, `.git`, and any credential file (SEC-001).
4. **Multi-stage** — build tooling (compilers, dev dependencies, the whole `node_modules` with devDeps) should not survive into the runtime stage.
5. **What runs** — `CMD`/`ENTRYPOINT`, and whether it binds to `0.0.0.0` on the port `fly.toml`'s `internal_port` names. A server bound to `127.0.0.1` inside the container is unreachable from the Fly proxy and produces a health check that never passes.

**`[deploy]` and migrations.**
```toml
[deploy]
  release_command = "npm run db:migrate"
  strategy = "rolling"          # or "bluegreen", "canary", "immediate"
```
`release_command` runs in a **temporary machine** with the app's environment and secrets, before the new version is released, and a non-zero exit aborts the deploy. That is the correct place for migrations and it is a genuinely good property — a failed migration means no deploy rather than a half-deployed app. Two things to check: the release machine gets the same secrets, so a migration needing `DATABASE_URL` works, but it is a separate machine with its own resources and a long migration can outrun its timeout; and `strategy = "immediate"` replaces all machines at once with no overlap, which means downtime (REL-012). `bluegreen` needs health checks to be meaningful — see "routes and handlers".

**Certificates and domains (REL-017).**
```bash
fly certs list
fly certs show example.com                 # issuance status, DNS validation state, and the expiry
fly ips list
```
Fly issues and auto-renews Let's Encrypt certificates for each hostname added with `fly certs add`. Renewal is automatic **while the DNS records still point at Fly** — an A/AAAA record moved elsewhere, or a `_acme-challenge` CNAME removed, silently breaks renewal and the failure surfaces months later as an expired certificate. `fly certs show` is where that state is visible, and it is the one platform-cert check on this stack that is not a pass by construction. The canonical-host redirect (apex to www or the reverse) is **your application's job** on Fly — there is no platform redirect setting — so look for it in the framework's config or a middleware, and confirm with `curl -sI` on both hosts.

## env vars
Two mechanisms, and the distinction is the whole of ACC-007 on this platform:

1. **`[env]` in `fly.toml`** — plaintext, committed to the repo, injected as environment variables. Correct for `PORT`, `NODE_ENV`, `PRIMARY_REGION`, a public API base URL, a log level. **A secret here is a committed secret** (SEC-001).
2. **`fly secrets`** — encrypted at rest, injected into the machine's environment at runtime, and **not readable back** through the CLI or the dashboard. This is the shape ACC-007 passes.

```bash
fly secrets list                           # names and digests only — no values
fly secrets set DATABASE_URL=... --stage   # --stage defers the restart; without it the app restarts NOW
fly secrets unset OLD_KEY
grep -n -A20 '^\[env\]' fly.toml
fly ssh console -C "printenv" | sort       # the real, merged environment of a running machine
```

Two operational facts worth stating. **Setting a secret triggers an immediate rolling restart of every machine by default** — `--stage` defers it to the next deploy, and a team that does not know this will restart production while rotating a key. And secrets are injected at machine start, so a running process does not see a change until it restarts; there is no live reload.

**DAT-017 has a different shape here than on the preview-deployment platforms.** Fly has **no built-in preview or branch deployments**. Each environment is a separate Fly app with its own secrets, which is a structurally safer default — cross-environment leakage requires someone to have deliberately set the same `DATABASE_URL` on two apps. So the question becomes:

- Is there a staging or review app at all? (`fly apps list`.) If not, that is a pass by absence and should be recorded as such.
- If review apps exist, they are almost always a GitHub Actions workflow creating `<app>-pr-<n>` with `fly deploy`. **Read that workflow**: it is where the secrets for the review app come from, and a workflow that copies the production `DATABASE_URL` from repository secrets into every PR app is DAT-017 in its clearest form. Check `.github/workflows/*` for `flyctl deploy` and what it passes.
- Compare the staging app's secret *names* against production (`fly secrets list -a staging-app` versus `-a prod-app`); the values are not readable, so where the names match, establish by some other means — the Postgres app they attach to, the `fly pg list` output, a `.flycast` hostname in a config — that they point at different databases.
- The same applies to `STRIPE_SECRET_KEY` (a staging app on a live key sends real charges) and the mail provider keys (real mail from staging).

**HYG-001's scoping half:** for each externally configured URL — OAuth redirect URIs, the auth provider's site URL and redirect allowlist, webhook endpoints — check that the production value is the custom domain and not `<app>.fly.dev`. The `.fly.dev` hostname stays live alongside the custom domain (see "known traps"), so anything registered against it keeps working, which is exactly why it survives to production unnoticed.

## routes and handlers
Fly does not route inside your app — it forwards to a port and your framework does the rest, so the route inventory belongs to the framework's stack file. What Fly decides is **which ports are exposed, whether HTTPS is forced, and what "healthy" means**.

```toml
app = "my-app"
primary_region = "iad"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "stop"        # or "suspend" / "off" (older configs use true/false)
  auto_start_machines = true
  min_machines_running = 0
  processes = ["app"]

  [[http_service.checks]]
    grace_period = "10s"
    interval = "30s"
    method = "GET"
    timeout = "5s"
    path = "/healthz"

[[services]]                          # the lower-level form, for non-HTTP or multi-port services
  internal_port = 8080
  protocol = "tcp"
  [[services.tcp_checks]]
    interval = "15s"
    timeout = "2s"
  [[services.http_checks]]
    path = "/healthz"

[checks]                              # machine-level checks, independent of a service
  [checks.alive]
    type = "http"
    port = 8080
    path = "/healthz"
    interval = "15s"
    timeout = "2s"
```

**REL-006's platform half lives in these blocks.** The check syntax has changed across `fly.toml` versions — `[[http_service.checks]]`, `[[services.http_checks]]`, and a top-level `[checks]` table all appear in real projects — so read whichever the file uses and confirm with `fly checks list` or `fly status`, which show the *live* check state rather than the intended one. Three questions:

1. **Is there a check at all?** A `[http_service]` with no checks means Fly will route traffic to a machine as soon as the process starts listening, including to one whose database connection failed. That is the finding.
2. **What path does it hit, and what does that handler do?** Trace it into the application (the framework's "routes and handlers"). A check pointed at `/` renders the whole home page on every interval, which at a 15-second interval is a self-inflicted load test; a check pointed at a handler returning a constant `200 OK` proves the process is alive and nothing else. The useful shape runs a trivial `select 1` against the primary database, pings the cache or queue if the app cannot serve without them, and returns non-200 when any of those fail. A handler that leaks version numbers, connection strings, environment variables, or dependency error text in its body is the other half of REL-006's finding.
3. **Does `grace_period` cover real startup?** A grace period shorter than the app's boot time makes Fly kill and restart machines in a loop during deploy, which looks like a crash loop and is a configuration bug.

`force_https = true` is SEC-034's redirect half on this platform: the Fly proxy 301s HTTP to HTTPS. Confirm it is present — it is the default in generated configs but it is one line and it can be removed.

**`auto_stop_machines` and cold starts (PERF-016).** With `auto_stop_machines` on and `min_machines_running = 0`, Fly stops idle machines and starts one when a request arrives — a genuine cold start of a few hundred milliseconds to a few seconds depending on the image and the framework's boot time. That is the *only* cold start on this platform, and it is opt-in. `min_machines_running = 1` keeps one warm and removes it. Read these three values together and say which configuration the app is in; PERF-016 is otherwise "not applicable, long-lived server" here.

**`[processes]`** defines multiple process groups from one image (`app = "npm start"`, `worker = "npm run worker"`), each scaled independently. A `[http_service] processes = ["app"]` means only the app group receives HTTP; the worker group has no public surface, which is correct.

## auth
Not applicable for this stack in the application sense — Fly has no notion of your users, and the app's session handling belongs to the framework's stack file. Platform surfaces that matter:

- **`fly ssh console` gives a root shell in production** to anyone with access to the Fly organization. That is a bigger grant than most deploy platforms make and it is worth naming in ACC-001's access review: list the org's members (`fly orgs show <org>`), check that access is not a shared login, and confirm 2FA is enforced on the Fly account.
- **`FLY_API_TOKEN`** in CI. A full org token can deploy, read logs, open a shell, and change secrets on every app in the org; a **deploy token** scoped to a single app (`fly tokens create deploy -a <app>`) is the correct shape for a workflow. A full-access token in a repository secret is a finding (ACC-007).
- **Private networking.** Every app in an organization shares a 6PN WireGuard network and can reach every other app's `<app>.internal` address with no authentication at all. That is convenient and it means an internal service exposing an unauthenticated admin API is reachable by any other app in the org, including a compromised one (SEC-010). Services intended to be internal should still authenticate.
- **`fly.toml` exposing an extra port.** A `[[services]]` block for a database, a metrics endpoint, or an admin port with `internal_port` published to the public proxy makes it internet-reachable. Read every `[[services]]` block, not just `[http_service]`.

## webhook handlers
Nothing platform-specific about receiving a webhook: it is an ordinary route in a long-lived process, the raw-body rule belongs to the framework's stack file, and **none of the serverless constraints apply** — no function timeout, no platform body ceiling, no cold-start-per-invocation. Say that where a check assumes otherwise.

Four Fly-specific facts that do change things:

1. **A deploy restarts the process.** With `strategy = "rolling"` (the default) machines are replaced one at a time and in-flight requests on a draining machine are given a window to finish; with `"immediate"` they are not. A webhook arriving mid-deploy on an `immediate` strategy is dropped and the provider retries — which is fine if the handler is idempotent and a duplicate side effect if it is not (PAY-003).
2. **Auto-stopped machines add latency to the first webhook after an idle period.** A provider with a short delivery timeout can time out on that first request and record a failure. `min_machines_running = 1` removes the issue.
3. **The proxy's idle timeout** bounds a connection that produces no data (see "known traps"). A webhook handler that acknowledges promptly never meets it.
4. **The real client IP is in `Fly-Client-IP`** (and `X-Forwarded-For`, which the Fly proxy sets). Anything keyed on the client address — rate limiting, an audit log, an allowlist of a provider's egress ranges — must read the forwarded value and must trust it only because the Fly proxy is the only thing that can set it; the app must not accept a client-supplied `Fly-Client-IP` from anywhere else (SEC-015).

## webhook verification snippet
Not applicable for this stack — Fly sends no signed requests to your app and verification is entirely the provider's and the framework's business (see stripe.md, revenuecat.md, lemonsqueezy.md for the provider half, and the framework's stack file for how to obtain raw bytes).

The one platform-adjacent rule: because a Fly app is a normal server behind a proxy, the raw body is available exactly as it would be anywhere else — `express.raw({ type: 'application/json' })` mounted before the JSON parser, `request.raw_post` in Rails, `await request.body()` in FastAPI. There is no base64 wrapper and no body-parsing middleware inserted by the platform, so a verification failure here is the application's, not Fly's.

## data access
**Fly Postgres.** Two products have carried the name and they behave differently, so establish which is in use before writing anything about backups:

- **Fly Postgres (the app you run)** — created with `fly pg create`, it is *your* Postgres running in *your* org as an ordinary Fly app. Fly's own documentation is explicit that it is **not a managed database**: automated backups, failover behaviour, and upgrades are your responsibility, and the snapshots that exist are volume snapshots with a retention window rather than logical backups. This is the most consequential fact in this file for DAT-018 — a team that believes their database is managed and has never tested a restore is the finding, and it is common.
- **Managed Postgres** — Fly's later managed offering, with the managed properties you would expect. Confirm which one `fly pg list` / `fly mpg list` shows rather than assuming.

**Connection addresses.** `fly pg attach` writes a `DATABASE_URL` secret pointing at an internal address:

- `<pg-app>.internal` — 6PN DNS, resolving to every node's private IPv6.
- `<pg-app>.flycast` — a private Fly-proxy address that load-balances and, importantly, routes to the current **primary** rather than to whichever node DNS returned. For a replicated setup, `.flycast` is the correct one for writes and `.internal` is how you accidentally send a write to a replica.
- Neither is reachable from the public internet, which is a real security property worth recording (DAT-008): the database has no public listener at all. Reaching it for a probe requires `fly proxy` over WireGuard.

Check the connection string for `sslmode` — over 6PN the traffic is already inside an encrypted private network, so `sslmode=disable` is defensible there and is *not* defensible if the same string is ever used from outside. Check `?sslmode=` and where else that URL travels.

**Pooling.** Long-lived processes hold connections, which is the opposite problem from serverless: a Fly app scaled to ten machines with a pool of twenty each is a hundred connections against a Postgres that may allow a hundred. Read the app's pool size against the database's `max_connections` (`fly pg config show`, or `show max_connections;` through a proxied psql). Fly Postgres ships PgBouncer on some versions; using it changes which pool size matters (DAT-008, PERF-018).

**Volumes.** `[mounts] source = "data" destination = "/data"` attaches a persistent volume. Three properties that decide checks:
- A volume is attached to **one machine in one region** and is not shared. Two machines cannot mount the same volume, so any app storing user uploads or SQLite on a volume cannot scale horizontally without either sticky routing or a different store.
- Volumes are **not replicated**. The daily snapshots Fly takes have a retention window (commonly around five days — check the current default) and are volume-level, not application-consistent for a running database unless the database was quiesced.
- Deleting a machine can destroy its volume depending on how it was created. `fly volumes list` and `fly volumes snapshots list <id>` are where this state lives.

Anything durable and important belongs in object storage (Tigris via `fly storage`, S3, R2) or a managed database, not on a volume — DAT-018 for the backup half, DAT-005 for the bucket's public-access flag on whichever store is used.

**Redis / caches** are usually Upstash via `fly redis` or a self-run app. A self-run Redis on a volume with no persistence configuration loses everything on a machine replacement, which matters if it holds sessions rather than cache.

## file uploads
**Fly imposes no request body limit** — it is a proxy in front of your server, and the ceiling is whatever your web server or framework enforces (`client_max_body_size` in nginx, Puma's and Gunicorn's buffering behaviour, Express's `limit` option, `MAX_CONTENT_LENGTH` in Flask). That is the opposite of every serverless platform in this directory, and PERF-020's payload half should be recorded as "no platform ceiling; the limit is the app's, at `<file:line>`" rather than left blank.

What that changes: an unbounded upload endpoint on Fly does not get rejected by a helpful platform — it gets accepted, buffered, and can exhaust the machine's memory. A `413` needs to come from your code. Check that a size limit exists and that it is enforced before the body is read into memory.

Uploads written to a **volume** inherit every volume property under "data access": single machine, single region, not replicated, snapshot-only backup. An app storing user uploads on a volume is a DAT-018 finding waiting to happen and cannot scale to a second machine.

The shapes that scale: Tigris (`fly storage create`, S3-compatible, sets `AWS_*` / `BUCKET_NAME` secrets), S3, R2, or Supabase Storage, with presigned direct-to-storage uploads so the bytes never pass through the app at all. DAT-005 applies to whichever bucket, and Tigris buckets have a public/private setting like any other.

## background jobs
**Fly has no built-in cron.** That is the headline fact and it decides SEC-014 and REL-019 here. Four shapes appear:

1. **A scheduled Machine** — `fly machine run <image> --schedule hourly|daily|monthly --command "..."`. Fly starts the machine on that schedule and it exits when the command finishes. Granularity is coarse (the accepted values are a short list, not cron expressions — check the current documentation) and there is no retry and no alerting. It is invoked internally with no public URL, so SEC-014 is a pass by construction for this shape.
2. **A cron process inside the container** — `supercronic` (the usual choice, since it logs to stdout and handles signals correctly), or a `[processes] cron = "supercronic /app/crontab"` group. Also internal, also no public URL, also no alerting. Check that it is not plain `cron`, which on a container with no syslog silently discards its output.
3. **An in-app scheduler** — Sidekiq-cron, Celery Beat, `node-cron`, `whenever`, a Quartz scheduler. Internal, and with the specific hazard that **every machine runs it**: an in-process scheduler on a three-machine deployment fires the job three times unless it takes a lock. Check for the lock (a Postgres advisory lock, a Redis `SET NX`, a `[processes]` group scaled to exactly one machine). This is REL-019's overlap question in its sharpest form and it is the most common real defect on this platform.
4. **An external scheduler hitting an HTTP endpoint** — GitHub Actions on a `schedule`, cron-job.org, an Upstash QStash schedule, another provider's cron calling `https://<app>/api/jobs/<name>`. **This path is fully public** and SEC-014 applies in full: the handler's first statements must compare a header against a secret and return 401, with a constant-time comparison (SEC-052). This is the shape that fails, and it is common because it is the easiest to set up.

```bash
grep -n 'processes\|schedule\|supercronic\|cron' fly.toml Dockerfile Procfile 2>/dev/null
fly machine list --json | python3 -c "import json,sys;[print(m.get('name'),m.get('config',{}).get('schedule')) for m in json.load(sys.stdin)]"
grep -rn 'schedule:' .github/workflows/ 2>/dev/null
```

REL-019's other properties, on every shape above: **nothing monitors any of them.** Fly does not retry a failed scheduled machine, does not alert on one, and has no cron dashboard. Unless the job pings a dead-man's-switch (Cronitor, Healthchecks.io, Sentry Cron Monitors) or writes a completion row something alerts on, a job that stopped running two weeks ago is indistinguishable from one that works. Its absence is the finding, and on this platform it is almost always absent.

**Queues.** Because the process is long-lived, the ordinary queue systems work normally and are the right answer: Sidekiq, Celery, BullMQ, Oban, `pg-boss` — all running as a `[processes] worker = "..."` group scaled independently of the web group. That is a genuinely better story than the serverless platforms and PERF-013 is usually satisfiable without adding a provider. Check the worker group actually has machines (`fly status` shows machines per process group); a `[processes]` entry with zero machines scaled is a queue nothing consumes, and the jobs pile up silently.

**Kill switch (REL-010).** Three shapes, with different latencies:
- `fly secrets set MAINTENANCE_MODE=1` — encrypted, and it triggers a rolling restart, so the change takes effect in the tens of seconds it takes machines to cycle. Reliable, but it restarts the app.
- A value in Redis or a `settings` row in Postgres read per request — instant, and it does not restart anything. This is the better shape and it is easy on Fly precisely because the process is long-lived and can cache the value with a short TTL.
- `fly scale count 0` or `fly apps suspend` — a very blunt instrument that takes the whole app down. It is a valid emergency answer but it is not a kill switch for one risky path.

Whichever exists, REL-010 wants it checked **before the expensive or risky paths** — payments, AI calls, sign-ups — and not only on the marketing page. Say which shape the project has and what its real latency is.

## error handling and logging
**Logs.**
```bash
fly logs                              # live stream, all machines
fly logs -i <machine id>
fly logs -a <app> --no-tail | tail -100
```

`fly logs` is a **live NATS stream with essentially no retention**. What scrolled past before you attached is gone. Fly's dashboard shows a short recent window, and anything durable requires shipping logs out — the `fly-log-shipper` app, a Vector or Fluent Bit sidecar, or the app writing directly to Datadog/Axiom/Better Stack. For REL-015 the consequence is blunt and worth stating plainly: **with no log shipper, the day after an incident there is nothing to read.** That is the finding on most Fly projects and it is more consequential here than on platforms that at least retain a day.

Everything the container writes to stdout/stderr becomes a log line. There is no request id for free — attach one (a generated uuid, or `Fly-Request-Id` from the proxy) to every line, or concurrent requests interleave into nonsense (REL-015). Structured logging (Pino, `structlog`, `lograge`, `slog`) is what makes the shipped logs queryable; bare `console.log`/`print` is the finding for that half.

**Metrics.** Fly exposes machine and proxy metrics (`fly dashboard metrics`) and scrapes a Prometheus endpoint from the app if `[metrics] port` / `path` is set in `fly.toml`. That is the platform's monitoring surface and it is worth noting whether anything is configured, because the alternative is that nobody would know the app was out of memory (REL-004's territory).

**OOM is the characteristic Fly failure.** A machine that exceeds its memory is killed and restarted; the symptom is a request that dies mid-flight and a log line about the process being killed, with nothing in the application's error tracker because the process did not get to report anything. `fly status` shows restart counts and `fly logs` shows the kill. Check the machine size against the app's real memory profile (`fly scale show`), because the default `shared-cpu-1x` with a small memory allocation is generous for a Go binary and tight for a JVM or a Rails app with several Puma workers.

**Error tracking (REL-001).** Ordinary server-side setup — Sentry's Node/Python/Ruby SDK, Bugsnag, Rollbar — with no platform-specific wrinkle, which is worth saying because it means there is no excuse for the edge/serverless gaps that catch people elsewhere. What to check is that a **worker process group** is instrumented too: an error in a Sidekiq or Celery worker on a separate machine reaches nothing unless that process initializes the SDK, and the web-only setup is the common half-done shape.

**Errors returned to clients** are entirely the framework's (SEC-009). Fly's proxy contributes its own pages for a few conditions — no healthy machine to route to, a connection refused on `internal_port` — and those are recognisable in the logs and are a symptom of the health-check and binding issues under "routes and handlers".

**Source maps (SEC-007).** The framework's decision, not Fly's; the app serves whatever is in its own static directory, so a `.map` alongside a bundle is public. Fetch one rather than reading the config.

## security headers
Not applicable at the platform level — **Fly sets no response headers of its own beyond the proxy's own plumbing, and has no header configuration.** Every security header must come from the application: the framework's header middleware (`helmet`, `secure_headers`, Django's `SECURE_*` settings, `next.config.*` `headers()`), or an nginx/Caddy layer inside the container if one exists.

That makes SEC-031 and SEC-033 purely the framework's answer here, and it also means there is **no platform safety net**: on Vercel or Netlify a project can get headers from a config file with no application change, and on Fly it cannot. Where a project has moved from one of those platforms to Fly, check specifically whether the headers came along — a `vercel.json` `headers` block left in the repo after a migration configures nothing and is a convincing-looking source of a false pass.

`force_https = true` under `[http_service]` is the one platform-level control, and it is SEC-034's redirect half. Verify:
```bash
curl -sI http://example.com | tr -d '\r' | head -5
curl -sI https://example.com/ | tr -d '\r'
```

If the container runs a reverse proxy (nginx, Caddy, Traefik) in front of the app, that is a second place headers can be set and a second place they can be missing — read its config file, which will be `COPY`ed in by the Dockerfile.

## known traps
- **Fly is not serverless, so several serverless checks do not apply and should be recorded as such rather than left blank.** There is no function timeout, no platform request-body ceiling, and no per-request cold start unless `auto_stop_machines` is on. PERF-020's duration and payload halves become "the limits are the app's own, at `<file:line>`", and PERF-016 becomes "not applicable, long-lived server" unless machines are auto-stopping.
- **The proxy's idle timeout** is the one duration limit that does exist: a connection that transfers no data for long enough is closed. The default has moved between releases and is configurable (`idle_timeout` under `[http_service]` in current schemas), so **check the current fly.toml reference rather than quoting a number** — and note that it bounds *silence*, not total duration, so a long-running request that streams anything is unaffected while a long poll that sends nothing is not. Your own web server's timeouts (Gunicorn `--timeout`, Puma, Node's `server.requestTimeout`, nginx's `proxy_read_timeout`) are the real ceilings on this platform and are yours to set: PERF-020.
- **No request body limit from the platform.** An unbounded upload endpoint is accepted, buffered, and can exhaust the machine's memory rather than being rejected with a helpful 413. The limit must come from the app (PERF-020, and the OOM shape under "error handling and logging").
- **`fly launch`'s generated Dockerfile often runs as root.** No `USER` in the final stage is the default outcome for several stacks: ACC-008. Also check `.dockerignore` excludes `.env*`, `.git`, and credential files, and that no `ARG`/`ENV` bakes a token into a layer where `docker history` finds it (SEC-001).
- **Secrets in `[env]` in `fly.toml`**: SEC-001, committed. `fly secrets` is the only correct home for a credential; `fly secrets list` shows names and digests without values, which is enough for an audit.
- **`fly secrets set` restarts every machine immediately** unless `--stage` is passed. Rotating a key during business hours without knowing that is an unintended restart of production.
- **No built-in environment marker.** Without an explicit `ENVIRONMENT` in `[env]`, code cannot tell production from staging — every "only in staging" guard is either always on or always off: HYG-001.
- **Review apps get their secrets from a CI workflow.** Fly has no preview deployments, so a `<app>-pr-<n>` app is created by `.github/workflows/*`, and a workflow that passes the production `DATABASE_URL` from repository secrets into every PR app is DAT-017 in its clearest form. Read the workflow; the repo is the whole answer here, which is unusual and useful.
- **`<app>.fly.dev` stays live alongside a custom domain.** It serves the same app, so it is a second public hostname that duplicates the site for search engines (SEO-004) and that any host-based logic (a cookie domain, a CORS allowlist, a canonical-URL redirect) may not account for. Redirect or noindex it, and check `curl -sI https://<app>.fly.dev/` for what it actually returns.
- **No canonical-host redirect from the platform.** Apex-to-www is your application's job on Fly; there is no dashboard setting. REL-017.
- **`fly certs` renewal depends on DNS still pointing at Fly.** A moved A/AAAA record or a deleted `_acme-challenge` CNAME breaks renewal silently and surfaces months later as an expired certificate. `fly certs show <hostname>` is where the state is visible: REL-017.
- **No health check, or one pointed at `/`.** With no check, Fly routes traffic to a machine whose database connection failed; with a check on `/`, you are rendering the home page every interval. With a check returning a constant, you learn only that the process is listening. REL-006 — and a `grace_period` shorter than real startup produces a restart loop that looks like a crash.
- **A `[[services]]` block exposing an extra port** (a metrics endpoint, an admin interface, a database) publishes it to the internet through the Fly proxy: SEC-010. Read every service block, not just `[http_service]`.
- **6PN private networking is unauthenticated.** Every app in the org can reach every other app's `.internal` address with no credential. An internal admin API that relies on being "internal" is reachable by any other app in the organization: SEC-010.
- **`fly ssh console` is a root shell in production** for anyone with org access: ACC-001. And a full-access `FLY_API_TOKEN` in CI can do the same on every app in the org — a per-app deploy token is the correct scope (ACC-007).
- **Fly Postgres created with `fly pg create` is not a managed database.** Backups, failover, and upgrades are yours; the snapshots that exist are volume snapshots with a short retention window. A team that believes it is managed and has never tested a restore is DAT-018's finding, and it is the most common serious one on this platform. Confirm which Postgres product is in use before writing the finding.
- **`.internal` versus `.flycast`.** `.internal` resolves to every node, so a write can land on a replica; `.flycast` routes through the Fly proxy to the primary. Check which the `DATABASE_URL` uses on a replicated setup: DAT-008.
- **Volumes are single-machine, single-region, and unreplicated.** User uploads or SQLite on a volume cannot scale to a second machine and are backed up only by snapshots with a retention window: DAT-018. Object storage is the answer, and DAT-005 then applies to the bucket's public-access setting.
- **Connection exhaustion from the other direction.** Long-lived processes hold their pools; machines multiplied by pool size can exceed the database's `max_connections`. Read both numbers: DAT-008, PERF-018.
- **An in-app scheduler runs on every machine.** Sidekiq-cron, Celery Beat, or `node-cron` on a three-machine deployment fires each job three times unless something takes a lock or the scheduler runs in a `[processes]` group scaled to exactly one: REL-019.
- **An HTTP job endpoint called by an external scheduler is fully public** and needs a secret guard with a constant-time comparison: SEC-014, SEC-052. Internal shapes — a scheduled machine, supercronic, an in-app scheduler — have no public URL and pass SEC-014 by construction; record which shape you found.
- **Nothing monitors any scheduled job.** No retry, no alert, no cron dashboard; without a dead-man's-switch ping, a job that stopped two weeks ago is invisible: REL-019.
- **A `[processes]` worker group scaled to zero machines** is a queue nothing consumes, and the jobs pile up silently. `fly status` shows machines per group.
- **`strategy = "immediate"` means downtime** and drops in-flight requests: REL-012. `bluegreen` is only meaningful with working health checks.
- **`fly logs` retains essentially nothing.** With no log shipper, there is nothing to read the day after an incident: REL-015. This is more consequential here than on platforms that retain a day.
- **OOM kills look like nothing.** The process is killed and restarted with no application error and nothing in the error tracker, because the process never got to report. Check machine size against the app's real memory use (`fly scale show`, `fly status` restart counts).
- **No platform header configuration at all.** Every security header must come from the application; a leftover `vercel.json` or `netlify.toml` in a migrated repo configures nothing and is a convincing false pass: SEC-031, SEC-033.
- **Some of this platform is CLI/dashboard state** — certificate status, org membership, token scopes, volume snapshots, machine sizes, and which Postgres product is attached. Rather less than on the other platforms in this directory, because `fly.toml` and the Dockerfile are committed, but `not determinable from the repo; confirm with fly certs show / fly status / the dashboard` is still the honest finding where it applies.

## runtime probe hints
**Establish what is deployed and how it is configured.** Almost all of this is read-only and available from the CLI, which makes Fly one of the better platforms to audit:

```bash
fly status                                 # machines, regions, health checks, current release
fly status --all
fly config show                            # the DEPLOYED configuration, which can differ from fly.toml
fly checks list                            # live health-check state
fly secrets list                           # names and digests, never values
fly scale show                             # machine size and count per process group
fly volumes list
fly volumes snapshots list <volume id>     # DAT-018's evidence
fly certs list && fly certs show example.com
fly ips list
fly machine list
fly image show                             # the running image and its digest
fly pg list                                # or: fly mpg list — establish WHICH Postgres product
fly apps list                              # is there a staging or review app?
```

**Health path (REL-006, and PERF-016's cold-start probe).** The path is in `fly.toml`'s check block — read it there rather than guessing, then hit it and read what it actually reports:
```bash
curl -s -w '\nstatus=%{http_code} ttfb=%{time_starttransfer}\n' https://example.com/healthz
```
A body containing version numbers, connection strings, or dependency error text is REL-006's leak half. A 200 from a handler that touches nothing is REL-006's constant half — confirm by reading the handler, not the response.

**Cold start (PERF-016), only where `auto_stop_machines` is on and `min_machines_running = 0`.** Leave the app idle long enough for machines to stop (`fly status` shows `stopped`), then:
```bash
curl -s -o /dev/null -w 'cold total=%{time_total} ttfb=%{time_starttransfer}\n' https://example.com/healthz
for i in 1 2 3; do curl -s -o /dev/null -w 'warm total=%{time_total} ttfb=%{time_starttransfer}\n' https://example.com/healthz; done
```
The first TTFB minus the median of the warm ones is the cold-start cost. This is explicitly not a load test. Where machines are always running, record PERF-016 as not applicable with the config values quoted.

**Job endpoints (SEC-014).** Internal shapes (a scheduled machine, supercronic, an in-app scheduler) have no public URL and there is nothing to probe — record the mechanism. For an HTTP job path called by an external scheduler, call it with no `Authorization` header and expect 401:
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/api/jobs/<name>
```
A 200, or any evidence the job ran, is the finding. Do not then call it with the real secret — a job endpoint has side effects by definition.

**Headers (SEC-031, SEC-033, SEC-034).** Everything comes from the app here, so one page and one API path is enough:
```bash
curl -sI https://example.com/ | tr -d '\r'
curl -sI https://example.com/api/<a safe GET> | tr -d '\r'
curl -sI http://example.com | tr -d '\r' | head -5           # force_https should 301
curl -sI https://<app>.fly.dev/ | tr -d '\r' | head -20      # the second hostname — same app, different story?
```

**Reaching the private network.** The database has no public listener, so a probe needs the WireGuard tunnel:
```bash
fly proxy 15432:5432 -a <postgres app>     # then connect to localhost:15432
psql "postgres://<user>:<pass>@localhost:15432/<db>" -c 'show max_connections;'
```
Do this read-only. Never run a migration, a `DELETE`, or a `pg_dump` of production data during an audit, and never leave the proxy open.

**Inside a machine.** `fly ssh console` is a root shell in production. Use it for reads only, and prefer the `-C` form so the command is explicit and recorded:
```bash
fly ssh console -C "printenv" | sort                 # the real merged environment; redact before quoting
fly ssh console -C "ps aux"
fly ssh console -C "id"                              # ACC-008's answer from the running container, not the Dockerfile
fly ssh console -C "cat /proc/meminfo" | head -3
```
`fly ssh console -C "id"` is worth calling out: it tells you what the container **actually** runs as, which beats reading the Dockerfile when there are multiple stages or a base image with its own `USER`. `uid=0(root)` is ACC-008's finding, confirmed rather than inferred.

**Logs.** `fly logs` is live-only. If the answer to "what happened at 3am yesterday" is "nothing is retained", that is REL-015's finding and should be recorded as one rather than as a failure to investigate. Check for a log shipper (`fly apps list` for a `*-log-shipper`, a Vector config in the image, or a Datadog/Axiom key in `fly secrets list`) before concluding.

**Never** run `fly deploy`, `fly secrets set`/`unset`, `fly scale`, `fly machine stop|destroy`, `fly apps suspend|destroy`, or `fly volumes destroy` during an audit, and never write through a `fly proxy` tunnel. Everything above is read-only apart from the deliberate negative probes.
