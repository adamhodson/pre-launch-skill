# Laravel

## detection signals
`artisan` at the repo root, `composer.json` requiring `laravel/framework`, and the `app/` `bootstrap/` `config/` `database/` `resources/` `routes/` `storage/` layout. `php artisan --version` prints the exact version and you should read it before anything else, because **the skeleton moved in Laravel 11**:
- **Laravel 10 and earlier**: `app/Http/Kernel.php` holds `$middleware`, `$middlewareGroups`, and `$routeMiddleware`/`$middlewareAliases`; `app/Console/Kernel.php` holds the schedule and command registration; `app/Exceptions/Handler.php` holds exception reporting and rendering; `app/Http/Middleware/VerifyCsrfToken.php`, `TrustProxies.php`, and `Authenticate.php` exist as editable files; `app/Providers/` has five or six providers.
- **Laravel 11 and later**: all of those are gone. `bootstrap/app.php` is the single configuration point, with `->withRouting(...)`, `->withMiddleware(function (Middleware $middleware) { ... })`, and `->withExceptions(function (Exceptions $exceptions) { ... })`. `routes/console.php` holds the schedule. `routes/api.php` is not created by default — `php artisan install:api` adds it along with Sanctum. Config files are only published on demand (`php artisan config:publish <name>`), so an absent `config/cors.php` means the framework default is in force, not that CORS is unconfigured.

Everything below names both locations where they differ. Frontend: `vite.config.js` plus `resources/js` and `resources/css` is the default; Livewire (`app/Livewire/`), Inertia (`resources/js/Pages/`), or a separate SPA change what the browser actually runs.

## dev server
`php artisan serve` on port 8000 (`--port=8001`, `--host=0.0.0.0`). It is PHP's built-in single-request server and is not a production server. Alternatives you will find: **Laravel Sail** (`./vendor/bin/sail up -d`) runs the app in Docker on `APP_PORT` (80 by default) with MySQL/Postgres, Redis, and **Mailpit on `8025`** already wired; **Herd** or **Valet** serve `<project>.test` over a local nginx; `composer run dev` in Laravel 11+ runs the server, queue worker, log tailer, and Vite concurrently. Assets need `npm run dev` (Vite dev server, hot module replacement, injects a `@vite` client) running alongside, or the pages will reference a build that is not there.

Never measure headers, caching, error bodies, or performance against `artisan serve` with `APP_ENV=local` — the error page, the debug bar, and the config cache all differ. See "build".

## build
1. `composer install --no-dev --optimize-autoloader --no-interaction` against the committed `composer.lock` for HYG-015's clean clone; note that `--no-dev` drops Telescope, Debugbar, and Ignition's dev features, which is part of why production behaves differently. The **declared runtime** HYG-015 compares against is `require.php` in `composer.json` (and the `config.platform.php` override if one is set), `.tool-versions`, or the Dockerfile base image — record the `php -v` you actually built with beside it, and note the Node version from `engines`/`.nvmrc` for the Vite half.
2. `npm ci && npm run build` → Vite → `public/build/` with `public/build/manifest.json`. `build.sourcemap` in `vite.config.js` decides whether `.map` files land there (SEC-007).
3. Production caches: `php artisan config:cache`, `php artisan route:cache`, `php artisan view:cache`, `php artisan event:cache` — or `php artisan optimize`, which runs the lot. `php artisan optimize:clear` reverses it.
4. Run: `APP_ENV=production APP_DEBUG=false php artisan serve --port=8100` is adequate for local-tier probing; the real deployment is php-fpm or Octane behind nginx. `php artisan about` prints the environment, debug flag, cache states, and driver selections in one table and is worth capturing as evidence.

**This build writes into the tree.** `npm run build` creates `public/build/`, and the `optimize` caches write `bootstrap/cache/config.php`, `routes-v7.php`, `events.php`, and compiled views into `storage/framework/views/`. All of it shows up in `git status` and, worse, a stale `bootstrap/cache/config.php` left behind changes how the app reads its own environment for every later check. Reverse it with `php artisan optimize:clear`. HYG-015's own run must happen in a throwaway clone rather than in the project directory precisely for this reason — follow that rule there, and if you cached config in the project tree to run a production-mode server, clear it afterwards and say you did.

Two things other domains ask of this section. Compression (PERF-003) comes from nginx, Cloudflare, or the platform — Laravel ships no compression middleware. Deployment shape (PERF-016): Laravel normally runs under php-fpm or Octane as a long-lived process pool, so there is no cold start to measure and that check is `n/a — long-lived process`; say so rather than leaving it blank, and defer to the platform's stack file if it is deployed scale-to-zero.

**The config-cache trap, which belongs to REL-008**: once `config:cache` has run, the `.env` file is not read at runtime and `env('ANYTHING')` **returns null everywhere outside `config/*.php`**. Code that calls `env()` from a controller, model, or service works perfectly in development and silently gets `null` in production. Grep for `env(` outside the `config/` directory — every hit is a REL-008 finding with a concrete consequence, and if the value feeds a signature check or an allowlist it is a security finding too.

## env vars
`.env` at the repo root, loaded by `vlucas/phpdotenv`. `.env.example` is committed and is REL-008's second set. `.env.testing` is used by the test suite.

The intended layering is: `.env` → `config/*.php` via `env('KEY', 'default')` → application code via `config('services.stripe.secret')`. Only `config/` should call `env()`; see the config-cache trap under "build". Grep both `env(` and `config(` for the two halves of REL-008, and read the second argument to every `env()` call — that default is the silent fallback.

`APP_KEY` is a base64 32-byte key generated by `php artisan key:generate`. It encrypts the session cookie and everything passed through `Crypt`/`encrypted` casts. A missing `APP_KEY` breaks sessions; a committed one is SEC-001 and rotating it invalidates every session and makes every encrypted column unreadable, so say that in the finding.

Other names that matter across checks: `APP_ENV`, `APP_DEBUG`, `APP_URL` (used by `url()`, `asset()`, and every link in a queued mail, so a stale value is HYG-002 and SEC-022), `DB_*`, `QUEUE_CONNECTION`, `SESSION_DRIVER`, `CACHE_STORE`, `MAIL_MAILER` and `MAIL_HOST`, `FILESYSTEM_DISK`.

**Public prefix**: Vite. Any variable named `VITE_*` is exposed to the client bundle as `import.meta.env.VITE_*` and is inlined at build time — that is this stack's public prefix for SEC-003, and a `VITE_STRIPE_SECRET` or a `VITE_` copy of any server key is an immediate fail. Blade can also leak by echoing config into a script block (`<script>window.config = @json(config('services'))</script>`), so grep `resources/views/` for `@json(config(` and `{{ config(` inside `<script>`.

**Payment test-mode detection**: `printenv | grep -i stripe` on the running process, then `php artisan tinker --execute="echo substr(config('services.stripe.secret'), 0, 8);"` — and remember the config cache may be stale relative to `.env`, so if the two disagree the cached value is the one in force.

## routes and handlers
Route files, each with its own middleware group applied by `withRouting()` in `bootstrap/app.php` (11+) or `RouteServiceProvider` (10 and earlier):
- `routes/web.php` — the `web` group: session, cookies, flash, **CSRF**, and `SubstituteBindings`.
- `routes/api.php` — the `api` group: stateless, prefixed `/api`, throttled, **no CSRF and no session**. In Laravel 11+ this file only exists after `php artisan install:api`.
- `routes/console.php` — Artisan closures and, in 11+, the scheduled tasks.
- `routes/channels.php` — broadcast channel authorization callbacks (SEC-055).

**`php artisan route:list` is the authoritative route table** and the first command to run: `php artisan route:list --except-vendor` hides package routes, `--path=api` filters, `--json` gives you something to process, and each row shows the method, URI, name, action, and **the full middleware stack** — which is exactly what SEC-010 needs. A route that appears with no `auth` in its middleware column is unprotected, whatever the file it lives in suggests.

Handlers: `app/Http/Controllers/`, single-action controllers with `__invoke`, or closures inline in the route file. `app/Http/Requests/` holds form requests, whose `rules()` is the server-side validation (SEC-037) and whose `authorize()` is a per-request gate — an `authorize()` returning a bare `true` means the check is somewhere else or nowhere. Views `resources/views/**/*.blade.php`, layout normally `resources/views/layouts/app.blade.php` (analytics, consent, `<html lang>`). Livewire components in `app/Livewire/` are HTTP endpoints in their own right, reachable at `/livewire/update`, and their public methods are callable by anyone who can reach the component — each needs its own authorization. Mailables `app/Mail/`, notifications `app/Notifications/`, events/listeners `app/Events/` and `app/Listeners/`, console commands `app/Console/Commands/`.

Third-party admin surfaces mounted by their service providers: Telescope `/telescope`, Horizon `/horizon`, Nova `/nova`, Filament `/admin`, Debugbar `/_debugbar`. Each is SEC-013's business and each has its own gate (see "auth").

## auth
The guard is the `auth` middleware. Applied as `Route::middleware('auth')->group(...)`, `->middleware(['auth', 'verified'])` on a single route, or `$this->middleware('auth')` in a controller constructor (older style). `auth:sanctum` uses the Sanctum guard; the guard names come from `config/auth.php`, where `guards` maps a name to a driver (`session`, `token`) and a provider, and `providers` maps to the model (`App\Models\User`).

**The gap to hunt**: a route defined outside the `auth` group. Read `php artisan route:list` and list every row whose middleware column lacks `auth` yet whose URI is not obviously public. That table is more reliable than reading the route file, because a `Route::middleware('auth')->group()` block that closes early, or a route added below the group, looks fine in the file and appears unguarded in the table (SEC-010). The same applies to `admin` routes (SEC-012).

Packages, and where their config lives:
- **Sanctum** — SPA cookie auth (`EnsureFrontendRequestsAreStateful` plus `SANCTUM_STATEFUL_DOMAINS`) or personal access tokens (`$user->createToken()`, `Authorization: Bearer`). The two modes have different CSRF consequences: cookie mode needs CSRF, token mode does not.
- **Fortify** — the backend for Breeze and Jetstream; `config/fortify.php` `features` array decides whether registration, password reset, email verification, and two-factor are enabled (SEC-023, SEC-024). Registration disabled there means there is no `/register` route to probe.
- **Breeze / Jetstream** — scaffolding that publishes the controllers and views.
- **Passport** — full OAuth2 server, `/oauth/token`.
- **Socialite** — OAuth providers, callback routes, `services.php` client ids and secrets (SEC-028).

Authorization (SEC-011, SEC-012): policies in `app/Policies/` registered by convention or in a service provider; called as `$this->authorize('update', $post)`, `Gate::allows(...)`, `$user->can(...)`, the `can:update,post` route middleware, or `@can` in Blade. A policy method that only checks the record exists, rather than that it belongs to the user, is the IDOR. Role packages: `spatie/laravel-permission` (`role:admin` and `permission:x` middleware, `hasRole`), or a `role` column checked by hand. **Filament** panels gate on `canAccessPanel(Panel $panel)` on the User model — the scaffolded implementation frequently returns `true` for everyone, which makes `/admin` a full CRUD surface for any authenticated user (SEC-012). Nova gates on `NovaServiceProvider::gate()`, Telescope on `TelescopeServiceProvider::gate()`, Horizon on `HorizonServiceProvider::gate()` — all three ship with a gate that allows only a hardcoded email list in `local`, so read what each actually returns.

Session: `config/session.php` — `driver` (`file`, `cookie`, `database`, `redis`; the `cookie` driver stores the session client-side and cannot be invalidated server-side, which matters for SEC-026), `lifetime` (minutes, default 120), `expire_on_close`, `encrypt`, `http_only` (true), `same_site` (`lax`), `secure` (from `SESSION_SECURE_COOKIE`, and it must be true in production — SEC-025), and `cookie`, which defaults to a slug of `APP_NAME` plus `_session`.

## webhook handlers
A POST route with CSRF excepted. Two ways depending on version: in Laravel 11+, `->withMiddleware(fn (Middleware $m) => $m->validateCsrfTokens(except: ['stripe/*', 'webhooks/*']))` in `bootstrap/app.php`; in 10 and earlier, the `$except` array in `app/Http/Middleware/VerifyCsrfToken.php`. Putting the route in `routes/api.php` also avoids CSRF, since the `api` group does not include it.

The raw body is `$request->getContent()` — a string, and the thing to sign against. `$request->all()`, `$request->input()`, and `$request->json()` are parsed copies and will not verify.

`laravel/cashier` ships its own `WebhookController` mounted at `/stripe/webhook`; it verifies the signature through the `VerifyWebhookSignature` middleware when `STRIPE_WEBHOOK_SECRET` (or `CASHIER_WEBHOOK_SECRET`) is set, and **skips verification silently when it is not** — so check the env value, not just the presence of the controller (SEC-051). `spatie/laravel-webhook-client` is the other common package and configures its signature validator in `config/webhook-client.php`.

## webhook verification snippet
```php
// app/Http/Controllers/StripeWebhookController.php
use Illuminate\Http\Request;
use Stripe\Webhook;
use Stripe\Exception\SignatureVerificationException;

public function handle(Request $request)
{
    $payload = $request->getContent();
    $sig = $request->header('Stripe-Signature');

    try {
        $event = \Stripe\Webhook::constructEvent(
            $payload, $sig, config('services.stripe.webhook_secret')
        );
    } catch (\UnexpectedValueException|SignatureVerificationException $e) {
        return response('bad signature', 400);
    }

    ProcessStripeEvent::dispatch($event->id, $event->type);
    return response('ok', 200);
}
```
`Webhook::constructEvent` enforces the timestamp tolerance itself (300 seconds by default), which is the replay defence SEC-051 asks about. This is the shape verification takes on this stack, not a file to drop in: the controller, the config key, and the dispatch call are the project's own, and an app using Cashier gets this controller from the package instead — check `config/cashier.php` and the webhook secret rather than expecting to find this code. For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
Eloquent. Models `app/Models/`, migrations `database/migrations/`, factories `database/factories/`, seeders `database/seeders/`. Connections in `config/database.php` driven by `DB_CONNECTION`, `DB_HOST`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD`. There is no schema dump by default unless the project ran `php artisan schema:dump`, which writes `database/schema/<connection>-schema.sql` — the migration set is otherwise the schema.

**Connection pooling** (DAT-008): php-fpm opens a connection per request and closes it, so the pool is really the fpm worker count against the database's `max_connections`; `'options' => [PDO::ATTR_PERSISTENT => true]` in `config/database.php` or an external pooler (PgBouncer, RDS Proxy) changes that. Octane keeps connections alive across requests instead. **Row-level security** (DAT-001, DAT-002): Laravel does not use it. The app connects as one database user with access to every row and all authorization is application code, so unless a migration contains `enable row level security` by hand, record RLS as not in use and let SEC-011 and DAT-026 carry that ground.

**SQL sinks** (SEC-038): `DB::raw("... $x")`, `whereRaw("col = $x")`, `havingRaw`, `orderByRaw`, `selectRaw`, `DB::select("... $x")`, `DB::statement`, `DB::unprepared` (which disables prepared statements entirely). Safe forms: `where('col', $x)`, `whereRaw('col = ?', [$x])`, `DB::select('... where id = ?', [$x])`, `DB::raw` over a constant. Dynamic identifiers cannot be bound: `orderBy($request->input('sort'))` and `select($request->input('fields'))` must map through a hardcoded allowlist (SEC-040).

**Mass assignment** (SEC-041): every Eloquent model declares either `$fillable` (an allowlist — good) or `$guarded` (a denylist). **`protected $guarded = [];` disables mass-assignment protection entirely** and is the finding to grep for first; `Model::unguard()` and `$model->forceFill()` do the same locally. `Model::create($request->all())` and `$model->update($request->all())` with an empty `$guarded` let a user set `is_admin`, `role`, `credits`, or `stripe_id` on themselves. The correct pattern is `$request->validated()` from a form request, or `$request->only(['name', 'bio'])`. Then list the privileged columns from the migrations and confirm no `$fillable` reaches them.

**N+1 and pagination**: `with()` eager loading is the fix (DAT-010); `Model::preventLazyLoading()` in `AppServiceProvider::boot()` turns a lazy load into an exception in non-production and means the project already guards this. Telescope's queries tab and `barryvdh/laravel-debugbar` are the detectors. Pagination is `->paginate($n)` / `->simplePaginate($n)` / `->cursorPaginate($n)`; a bare `Model::all()` or `->get()` on a user-facing list is DAT-011, and a `per_page` taken straight from the query string with no ceiling is the unbounded variant.

**Serialization** (SEC-042): `return $model;` from a controller serializes every column except those in the model's `$hidden` array — so `$hidden = ['password', 'remember_token']` is the only thing standing between a `return $user;` and a full row dump. API resources (`app/Http/Resources/`, `php artisan make:resource`) are the explicit alternative.

**Migrations for DAT-015**: define a scratch connection in `config/database.php` (or set the `DB_*` variables for a one-shot run) and use `php artisan migrate --database=<connection>`; `--pretend` prints the SQL without running it, and `php artisan migrate:status --database=<connection>` confirms which database you are actually pointed at before anything writes. **Never run `migrate:fresh`, `migrate:reset`, or `db:wipe`** — all three drop every table in the target database. Rollback is `php artisan migrate:rollback --step=1`, which requires each migration's `down()` to have a real body; Laravel 11's anonymous-class migrations still have `down()` and an empty one is the finding.

## file uploads
`$request->file('avatar')->store('avatars', 's3')`, `->storeAs(...)`, `->storePublicly(...)`, or `Storage::disk('s3')->put(...)`.

`config/filesystems.php` defines the disks and is where DAT-005 lives:
- `local` → `storage/app` (or `storage/app/private` in newer skeletons), not web-reachable.
- `public` → `storage/app/public` with `'visibility' => 'public'`, exposed to the web by the `php artisan storage:link` symlink at `public/storage`. Everything written to this disk is world-readable by URL, so an upload path that defaults to `public` for private documents is DAT-006.
- `s3` → with its own `'visibility'` key; `'public'` sets a public-read ACL on every object.

`Storage::url($path)` gives a permanent public URL; `Storage::temporaryUrl($path, now()->addMinutes(5))` gives a signed expiring one and is SEC-050's mechanism (it is supported on S3 and compatible drivers, not on the plain local driver unless the project wired a `buildTemporaryUrlsUsing` callback). Laravel's own signed routes — `URL::temporarySignedRoute(...)` plus the `signed` middleware — are the other way to serve a private file.

Validation (SEC-047, SEC-049): `$request->validate(['file' => 'required|file|mimes:jpg,png,pdf|max:5120'])`. `mimes` and `mimetypes` check the guessed type from the file's content rather than the client's header, which is a real content check; `max` is in **kilobytes**. `dimensions` bounds image size. An `image` rule accepts SVG in some versions — exclude `svg` explicitly or re-encode (SEC-049). The hard ceiling is PHP's `upload_max_filesize` and `post_max_size` in `php.ini`, which reject the request before Laravel sees it and produce an empty `$request` rather than a validation error (SEC-067).

## background jobs
`app/Jobs/`, dispatched with `dispatch(new SendInvoice($id))` or `SendInvoice::dispatch($id)`, `->onQueue('emails')`, `->delay(...)`.

`QUEUE_CONNECTION` in `.env` and `config/queue.php` decides everything:
- **`sync`** — the job runs inline, in the request, before the response is sent; a `dispatch()` call under `sync` is PERF-013 no matter how the code reads. It is `config/queue.php`'s fallback (`env('QUEUE_CONNECTION', 'sync')`), so it is what you get when the variable is unset — but it is not necessarily what the skeleton ships: Laravel 10 and earlier generate `QUEUE_CONNECTION=sync` in `.env.example`, and Laravel 11+ generate `QUEUE_CONNECTION=database`. Read the actual value in the running environment (`php artisan about` shows it) rather than either default.
- `database` — a `jobs` table, worker `php artisan queue:work`.
- `redis` — worker `php artisan queue:work`, or **Horizon** (`php artisan horizon`, dashboard `/horizon`, config `config/horizon.php`).
- `sqs`, `beanstalkd`.

Failed jobs land in the `failed_jobs` table: `php artisan queue:failed`, `queue:retry`, `queue:flush`. `queue:work` caches the code, so a deploy needs `php artisan queue:restart` — a worker running stale code after a deploy is a real and confusing production failure.

Confirm a worker is actually running in production (Procfile, supervisor config, systemd unit, Sail's `laravel.test` container, the platform's worker process). A queue with no worker is jobs that never run and looks like success from the request side (REL-019).

**Scheduling**: `routes/console.php` with `Schedule::command('report:daily')->dailyAt('03:00')` in Laravel 11+, or `app/Console/Kernel.php`'s `schedule(Schedule $schedule)` method in 10 and earlier. Either way it requires **one system cron entry running `php artisan schedule:run` every minute**; without that entry nothing scheduled ever fires, and nothing in the codebase reveals its absence. That is the classic REL-019 finding on this stack — check the deploy config, the Dockerfile, the supervisor config, or the platform's cron settings for it. `->withoutOverlapping()` and `->onOneServer()` are the overlap and multi-instance guards.

Mail: `Mail::to($u)->send(new Welcome)` is synchronous; `Mail::to($u)->queue(new Welcome)` or a Mailable implementing `ShouldQueue` is not (PERF-013).

## error handling and logging
**`APP_DEBUG`** is the setting. With `APP_DEBUG=true` an unhandled exception renders Ignition: the full stack trace with source excerpts, the request payload, the session contents, the environment, and the executed queries. In production that is SEC-008 and SEC-009 together and it is the highest-value single thing to check on this stack. `APP_ENV=production` alone does not suppress it; both must be right. Confirm with `php artisan about` or by triggering an error against the production-mode build.

Handler location: `bootstrap/app.php`'s `->withExceptions(function (Exceptions $exceptions) { $exceptions->dontReport([...]); $exceptions->render(...); })` in Laravel 11+; `app/Exceptions/Handler.php` with `$dontReport`, `$dontFlash`, `register()`, `report()`, and `render()` in 10 and earlier. `$dontFlash` is the list of input keys kept out of the session on a validation redirect and defaults to password fields — anything sensitive not in it gets flashed (REL-015).

Custom error pages: `resources/views/errors/404.blade.php`, `500.blade.php`, `503.blade.php` (the maintenance-mode page, rendered by `php artisan down`).

Logging: `config/logging.php` channels — `stack` (the default, composing others), `single` (`storage/logs/laravel.log`), `daily`, `stderr` (what you want in a container), `slack`, `papertrail`. `LOG_CHANNEL` and `LOG_LEVEL` in `.env`. `Log::info()`, `Log::error()`; `Log::withContext()` for request-scoped fields. A `daily` channel with no `days` limit accumulates forever (DAT-022).

**Telescope** (`laravel/telescope`) records every request with its full input, every query with bindings, every job payload, and every mail — into the application's own database. Left enabled in production it is both a route (SEC-013, gated in `TelescopeServiceProvider::gate()`) and a store of exactly the data REL-015 says must not be logged. Check `TELESCOPE_ENABLED` and whether the package is in `require` rather than `require-dev`.

Reporting: `sentry/sentry-laravel` (`config/sentry.php`, `SENTRY_LARAVEL_DSN`, and in 11+ a `->withExceptions(fn ($e) => Integration::handles($e))` wiring; in 10 it is a `report()` call in the Handler). It captures queue jobs and scheduled commands too once registered, which is the REL-001 gap otherwise. Bugsnag, Flare, and Honeybadger install the same way.

## security headers
Laravel ships **no** security-header middleware. Look for, in order of likelihood: a hand-written middleware in `app/Http/Middleware/` appending headers in `handle()` and registered globally; `bepsvpt/secure-headers` (`config/secure-headers.php`); `spatie/laravel-csp` (`config/csp.php` naming a policy class); or the headers being set by nginx, Cloudflare, or the platform in front, in which case the local-tier probe will not see them and the remote-tier one will (SEC-031, SEC-032, SEC-033).

HTTPS: `URL::forceScheme('https')` in `AppServiceProvider::boot()`, or a correct `APP_URL` plus a terminating proxy (SEC-034). HSTS almost always comes from the web server rather than Laravel.

Proxies: `TrustProxies` — `$proxies = '*'` in `app/Http/Middleware/TrustProxies.php` (10 and earlier) or `$middleware->trustProxies(at: '*')` in `bootstrap/app.php` (11+). It must be set for `$request->ip()`, `$request->secure()`, and therefore rate limiting to be correct behind a load balancer, and `'*'` is only safe when nothing untrusted can reach the app directly (SEC-016).

CORS: `config/cors.php` (published on demand in 11+) driving the `HandleCors` middleware. `'allowed_origins' => ['*']` together with `'supports_credentials' => true` is SEC-035; so is an `allowed_origins_patterns` regex that matches everything.

Rate limiting: `RateLimiter::for('api', ...)` in a service provider (10 and earlier) or `bootstrap/app.php`/`AppServiceProvider` (11+), applied as `throttle:api` middleware. The `api` group carries `throttle:api` by default; `routes/web.php` carries none, so a login POST in `web.php` is unthrottled unless the route says otherwise (SEC-015, SEC-017). Fortify adds its own throttle to the login route — check whether the app uses it.

## known traps
- `APP_DEBUG=true` in the production environment: Ignition renders the stack trace, source, session, and queries to any visitor (SEC-008, SEC-009).
- `protected $guarded = [];` on a model, or `Model::unguard()`, or `Model::create($request->all())`: SEC-041.
- `{!! $value !!}` in Blade with user, database, or CMS content (`{{ }}` escapes, `{!! !!}` does not): SEC-043.
- A `$except` entry in `VerifyCsrfToken` (or `validateCsrfTokens(except: [...])`) covering anything but a signature-verified webhook, and especially a `'*'` entry: SEC-030.
- `DB::raw`, `whereRaw`, `orderByRaw`, or `DB::select` with an interpolated variable: SEC-038. `orderBy($request->input('sort'))`: SEC-040.
- A route that `php artisan route:list` shows without `auth` in its middleware column, or a route added after the `Route::middleware('auth')->group()` block closes: SEC-010, SEC-012.
- A Filament panel whose `canAccessPanel()` returns `true`, or a Nova/Horizon/Telescope gate left at its scaffolded default: SEC-012, SEC-013.
- `/telescope`, `/horizon`, or `/_debugbar` reachable in production, and Telescope storing request payloads and query bindings: SEC-013, REL-015.
- `QUEUE_CONNECTION=sync` in production, or `Mail::send` instead of `queue`: PERF-013.
- No cron entry running `php artisan schedule:run` every minute: every scheduled task silently never runs (REL-019).
- `env()` called outside `config/` in a deployment that runs `config:cache`: the value is `null` in production and correct in development (REL-008).
- `APP_KEY` missing, or committed to the repo: SEC-001, and every session cookie and encrypted column is forgeable or readable.
- A `filesystems.php` disk with `'visibility' => 'public'` used for private documents, or `storage:link` exposing a directory of them: DAT-005, DAT-006.
- `VITE_`-prefixed variables carrying a secret, or `@json(config(...))` echoed into a Blade `<script>`: SEC-003.
- `php artisan migrate:fresh`, `migrate:reset`, or `db:wipe` — never run any of them during the audit; DAT-015 says so explicitly.
- A seeded admin user with a known password in `database/seeders/`: SEC-060, DAT-016.
- `return $model;` from a controller with no `$hidden` list and no API resource: every column ships (SEC-042).
- `build.sourcemap: true` in `vite.config.js`: SEC-007.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if the project already depends on one (`package.json` devDependencies, or `laravel/dusk` in `composer.json`'s `require-dev`); never install one for the audit. Cited by the accessibility and compliance domain headers, COMP-007, and FLOW-018.

## runtime probe hints
**Session cookie for `curl`.** A `web`-group login is a form POST guarded by CSRF, so fetch the form, lift the `_token`, and post it back with the same jar:
```bash
JAR=.pre-launch/flows/cookies.txt
TOKEN=$(curl -s -c "$JAR" http://localhost:8100/login \
  | grep -o 'name="_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"$//')
curl -s -b "$JAR" -c "$JAR" -X POST http://localhost:8100/login \
  --data-urlencode "_token=$TOKEN" \
  --data-urlencode "email=qa+$(date +%s)@example.com" \
  --data-urlencode 'password=<from credentials_env>' -i
curl -s -b "$JAR" http://localhost:8100/dashboard -o /dev/null -w '%{http_code}\n'
```
`/login` and `/register` exist only if Breeze, Jetstream, or Fortify is installed and the feature is enabled in `config/fortify.php` — confirm with `php artisan route:list --path=login`. For an SPA using Sanctum cookie auth, the sequence is `GET /sanctum/csrf-cookie` first (it sets `XSRF-TOKEN`), then POST `/login` with the token echoed in an `X-XSRF-TOKEN` header, URL-decoded, rather than as a form field.

**Cookie names.** The session cookie is `SESSION_COOKIE` from `.env`, defaulting to a slug of `APP_NAME` plus `_session` — so `laravel_session` in an unrenamed app and `<app-name>_session` otherwise; read `config/session.php` and `.env` rather than guessing. `XSRF-TOKEN` is the readable CSRF cookie for header-based clients. `remember_web_<hash>` is the remember-me cookie.

**Bearer token for API probes.** Sanctum personal access tokens are the easy path when no login API exists:
```bash
php artisan tinker --execute="echo App\Models\User::where('email','qa@example.com')->first()->createToken('prelaunch-audit')->plainTextToken;"
curl -s http://localhost:8100/api/user -H "Authorization: Bearer <token>" -w '\n%{http_code}\n'
```
Delete the token afterwards (`$user->tokens()->where('name','prelaunch-audit')->delete()`). If the app exposes its own `POST /api/login` returning a token, prefer that — it exercises the real path. Passport uses `POST /oauth/token`. DAT-002's per-user RLS probe wants a data API that authorizes as the end user, which Laravel does not provide — the app connects as one database user for everyone — so record `n/a — no PostgREST surface` there and cover the ground with SEC-011's two-account probe and DAT-026's privilege check.

**Health path.** Laravel 11+ registers `/up` by default via `->withRouting(health: '/up')` in `bootstrap/app.php`; it returns 200 once the framework boots and checks no dependency, which is REL-006's finding rather than a pass. Earlier versions have no convention — `php artisan route:list --path=health` and grep for `health`, `healthz`, `ping`, `status`. If nothing exists use the cheapest static page for cold-start timing and say which you used.

**Not-found behaviour.** An unmatched route returns 404 rendering `resources/views/errors/404.blade.php` or the framework's page. `abort(404)`, `findOrFail`, and an unresolved route-model binding all produce the same. With `APP_DEBUG=true` a 500 renders Ignition instead of `errors/500.blade.php`, and that difference is itself the evidence SEC-009 wants. Check the status code and not just the body: a catch-all route rendering a "not found" view with 200 is a soft 404 (SEO).

**Test-mode provider keys.** `printenv | grep -iE 'stripe|paypal|paddle'` on the running process, then `php artisan tinker --execute="echo substr(config('services.stripe.secret'), 0, 8);"`. If `config:cache` has run, the cached value wins over `.env`, so trust `config()` over the file. Stripe `sk_test_` / `pk_test_` / `rk_test_` and a `whsec_` from `stripe listen`; PayPal on `api-m.sandbox.paypal.com`; Paddle, Lemon Squeezy, and RevenueCat a sandbox host, flag, or key. Cashier's own `CASHIER_*` variables may shadow the `STRIPE_*` ones. Published test card numbers live in the payment provider's own stack file. If the classification is ambiguous, treat the keys as live and stop.

**Local mail catcher.** Read `MAIL_MAILER` first:
- **`smtp` with `MAIL_HOST=mailpit`** — Sail's default. Mailpit's UI and API are on `8025`: `curl -s http://localhost:8025/api/v1/messages | jq '.messages[0]'`, and a single message body at `/api/v1/message/<id>`. Inside Sail the host is `mailpit`; from your shell it is `localhost`.
- **`log`** — every message is written to `storage/logs/laravel.log` as plain text. Grep it: `grep -A40 'Subject:' storage/logs/laravel.log | tail -60`. This is a real capture and is the most common non-Sail setup.
- **`array`** — collected in memory for tests only; unreadable from outside, so treat it as no capture.
- **`smtp` with `MAIL_HOST=localhost` and `MAIL_PORT=1025`** — a catcher is expected: check `docker-compose.yml` for `axllent/mailpit` (HTTP `8025`) or `mailhog/mailhog` (API `/api/v2/messages` on `8025`).
- A provider mailer (`resend`, `postmark`, `ses`, `mailgun`) in test mode means the inbox is the provider's own test log.

No reachable catcher is `error: no mail capture`, never a pass.

**Throwaway identity.** Register through the app's own `/register` route with `qa+<unix-ts>@example.com` and the password from the config's `credentials_env`, using the token dance above; never create the user with `tinker` or a factory, because that skips exactly the flow FLOW-001 is testing. Use tinker only for cleanup: `php artisan tinker --execute="App\Models\User::where('email','like','qa+%@example.com')->each(fn(\$u) => \$u->delete());"` — and what that cascade does or fails to do is also DAT-020's evidence.
