# Django

## detection signals
`manage.py` at the repo root, a project package containing `settings.py` (or a `settings/` package with `base.py`, `production.py`, `local.py`), `wsgi.py` and/or `asgi.py`, and `Django` in `requirements.txt` / `pyproject.toml` / `Pipfile`. Apps are directories with `apps.py`, `models.py`, `views.py`, `urls.py`, `migrations/`. `INSTALLED_APPS` in settings is the inventory of what is actually wired up — read it before anything else, because `rest_framework`, `corsheaders`, `django_celery_beat`, `storages`, `allauth`, and `debug_toolbar` all announce themselves there. Version from `python -c "import django; print(django.get_version())"` or the pin in the requirements file; Django 4 and Django 5 differ on `STORAGES`, `LoginRequiredMiddleware`, and several security defaults, so read the version before assuming a default below.

## dev server
`python manage.py runserver` (`./manage.py runserver 0.0.0.0:8001` to change host/port), default port 8000. `DJANGO_SETTINGS_MODULE` selects the settings module and defaults to whatever `manage.py` hardcodes. The dev server runs with `DEBUG` as the settings say — usually `True`, which changes the error page, the 404 page, static file serving, and `ALLOWED_HOSTS` enforcement. Never measure error bodies, headers, caching, static assets, or performance against `runserver`: it is single-threaded by default, serves static files itself, and is explicitly not a production server. See "build" for the production-mode run every local-tier check wants.

## build
There is no bundler for the Python side. The production sequence is:
1. `pip install -r requirements.txt` (or `poetry install --only main` — `--no-dev` was deprecated in Poetry 1.2 and removed later — `uv sync --frozen`, `pipenv install --deploy`). Use the locked form for HYG-015's clean clone: a `requirements.txt` with pinned versions, `requirements.lock`, `poetry.lock`, `uv.lock`, or `Pipfile.lock`; an unpinned requirements file is itself a finding, since the clean build resolves differently from the one that shipped. The **declared runtime** HYG-015 compares against is `.python-version`, `requires-python` in `pyproject.toml`, `.tool-versions`, `runtime.txt`, or the Dockerfile base image — record the version you actually built with beside it.
2. `DJANGO_SETTINGS_MODULE=<project>.settings.production python manage.py collectstatic --noinput` → `STATIC_ROOT`. Whitenoise (`whitenoise.middleware.WhiteNoiseMiddleware` in `MIDDLEWARE`) serves that directory from the app process; otherwise a web server or CDN does. `STORAGES["staticfiles"]` set to `ManifestStaticFilesStorage` adds content hashes and is what makes PERF-004's immutable caching possible — Django 4.2+ uses the `STORAGES` dict, earlier versions use `STATICFILES_STORAGE` and `DEFAULT_FILE_STORAGE`; check the version.
3. `python manage.py migrate` (DAT-015 owns whether this is safe to run; do not run it against the project's own database as part of the audit).
4. Serve: `DJANGO_SETTINGS_MODULE=<project>.settings.production gunicorn <project>.wsgi:application --bind 127.0.0.1:8100 --workers 3`, or `uvicorn <project>.asgi:application --port 8100` / `daphne` for ASGI. Add `DEBUG=0` however the settings module reads it.

**Run `python manage.py check --deploy` before anything else.** It is Django's own production audit and reports `DEBUG`, `SECRET_KEY` strength, `ALLOWED_HOSTS`, `SECURE_SSL_REDIRECT`, HSTS, cookie flags, and `X_FRAME_OPTIONS` in one command. Run it with the production settings module. It is evidence for SEC-008, SEC-025, SEC-032, SEC-033, SEC-034 at once and its output should be quoted rather than re-derived.

**This build writes into the tree.** `collectstatic` copies every static file into `STATIC_ROOT` — often a `staticfiles/` or `static_root/` directory that did not exist before — and `ManifestStaticFilesStorage` also writes `staticfiles.json` there. Reverse it by deleting the directory, but only if the build created it: check `git status --porcelain` and whether `STATIC_ROOT` is gitignored before removing anything. HYG-015's own run must happen in a throwaway clone rather than in the project directory precisely for this reason — follow that rule there, and say so if you collected static in the project tree for some other check's production-mode server.

Two things other domains ask of this section. Compression (PERF-003) is `django.middleware.gzip.GZipMiddleware`, Whitenoise's own compression for static files, or the proxy in front — none is on by default. Deployment shape (PERF-016): Django normally runs as long-lived gunicorn or uvicorn workers, so there is no cold start to measure and that check is `n/a — long-lived process`; say so rather than leaving it blank, and defer to the platform's stack file if it is deployed scale-to-zero.

If the project ships a JavaScript frontend (`django-vite`, `django-webpack-loader`, a `frontend/` or `assets/` directory with its own `package.json`), that build is separate, has its own output directory, its own public env prefix (`VITE_`, `REACT_APP_`), and its own source-map setting (SEC-003, SEC-007).

## env vars
`os.environ['X']` (raises `KeyError` — loud), `os.environ.get('X')` (returns `None` silently), `os.environ.get('X', 'default')` and `os.getenv('X', 'default')` (the silent fallback REL-008 exists to catch). Wrappers, each of which has its own read syntax to grep:
- `django-environ`: `env = environ.Env(DEBUG=(bool, False))`, `environ.Env.read_env()`, then `env('X')`, `env.bool('DEBUG')`, `env.db()` parsing `DATABASE_URL`, `env.list('ALLOWED_HOSTS')`. The defaults passed to `Env(...)` are the fallbacks.
- `python-decouple`: `config('X')`, `config('DEBUG', default=False, cast=bool)`.
- `dj-database-url`: `DATABASES = {'default': dj_database_url.config()}` reading `DATABASE_URL`.
- `python-dotenv`: `load_dotenv()` at the top of settings or `manage.py`.
- `pydantic-settings` in newer projects: a `Settings` class whose fields are the authoritative variable list.

Settings themselves are the second env layer: code reads `settings.STRIPE_SECRET_KEY`, and settings reads the environment. For REL-008 build the set from both directions — grep the settings module for every assignment sourced from the environment, and grep the app code for `settings.<NAME>` reads that no settings module defines.

REL-008's second set — the variables that are *declared* — comes from `.env.example` / `.env.sample` if the project keeps one, plus the deploy config (`Dockerfile` `ENV` lines, `docker-compose.yml` `environment`, `fly.toml`, `render.yaml`, Kubernetes manifests, the CI workflow's `env` blocks).

`SECRET_KEY` assigned to a literal in a tracked settings file is SEC-001 and rotating it invalidates every session and signed token, so say so in the finding. `.env` must be gitignored; the settings module usually is not, which is why `DATABASES` with a literal password there is SEC-006.

**Public prefix**: Django has none. Nothing is inlined into a client bundle by the framework; values reach the browser only through a template (`{{ settings.X }}` via a context processor, a `<script>` block, a `json_script` filter, or a `data-` attribute) or through a separate JS build. Grep templates for those three shapes for SEC-003.

**Payment test-mode detection**: `printenv | grep -i stripe` on the running process first, then `python manage.py shell -c "from django.conf import settings; print(str(settings.STRIPE_SECRET_KEY)[:8])"` — eight characters is enough to see `sk_test_`.

## routes and handlers
`ROOT_URLCONF` in settings names the root module, normally `<project>/urls.py`. Its `urlpatterns` list uses `path('prefix/', include('app.urls'))` to reach each app's own `urls.py`, so the full route table is a tree you have to walk. Two ways to get it flat:
- `python manage.py show_urls` if `django_extensions` is in `INSTALLED_APPS` (the fastest, but the package is often only a dev dependency).
- `python manage.py shell -c "from django.urls import get_resolver; [print(p) for p in get_resolver().url_patterns]"` and recurse into any `URLResolver`, or read `get_resolver().reverse_dict`.

Handlers are function views and class-based views in `<app>/views.py` or a `views/` package; DRF adds `APIView`, `GenericAPIView`, `ViewSet`, and `ModelViewSet` wired through `routers.DefaultRouter()` whose `router.urls` expands to a full CRUD set from one registration — so a `router.register(r'users', UserViewSet)` line is six endpoints, not one. Templates in `templates/` (per-app or a project-level `DIRS` entry); the base template is where analytics, consent gating, and `<html lang>` live. Forms `<app>/forms.py`, serializers `<app>/serializers.py`. Management commands `<app>/management/commands/*.py` are entry points too — cron and the scheduler call them.

`MIDDLEWARE` in settings is ordered and the order is load-bearing: `SecurityMiddleware` first, `SessionMiddleware` before `AuthenticationMiddleware` before `MessageMiddleware`, `CsrfViewMiddleware` between session and auth. A middleware missing from the list simply does not run, which is how the security headers silently disappear.

The Django admin at `/admin/` (`path('admin/', admin.site.urls)`) is a full CRUD surface over every registered model (SEC-012, SEC-013). Static and media are served by the `static()` helper in the root urls only when `DEBUG` is true; in production something else serves them.

## auth
`django.contrib.auth` with `django.contrib.sessions`. The guards, in the order you should look for them:
- **Function views**: `@login_required` (redirects to `settings.LOGIN_URL`), `@user_passes_test(lambda u: u.is_staff)`, `@permission_required('app.change_thing')`, `@staff_member_required` for admin-adjacent views.
- **Class-based views**: `LoginRequiredMixin`, `PermissionRequiredMixin`, `UserPassesTestMixin` — and the mixin must come *first* in the base-class list to run before the view, which is a real and easy-to-miss ordering bug.
- **DRF**: `permission_classes = [IsAuthenticated]` on the view or viewset, plus `REST_FRAMEWORK = {'DEFAULT_PERMISSION_CLASSES': [...]}` in settings. **If `DEFAULT_PERMISSION_CLASSES` is not configured, DRF's default is `AllowAny`** — so a `ModelViewSet` with no `permission_classes` line is a fully public CRUD API over that model, which is the single most common SEC-010 finding on this stack. Check the settings default first, then list every view that neither sets `permission_classes` nor inherits one. `authentication_classes` and `DEFAULT_AUTHENTICATION_CLASSES` say how the identity is established (`SessionAuthentication`, `TokenAuthentication`, `JWTAuthentication`).
- **Project-wide**: Django 5.1 added `LoginRequiredMiddleware`, which flips the default to authenticated-unless-`@login_not_required`. Check the version and whether it is in `MIDDLEWARE` before assuming per-view decorators are the whole story.

Object-level authorization (SEC-011) is not provided: `get_object_or_404(Post, pk=pk)` with no owner predicate is the bug, `get_object_or_404(Post, pk=pk, owner=request.user)` or a filtered `get_queryset()` is the fix. DRF's `get_queryset` override and `has_object_permission` on a custom permission class are where it belongs. `django-guardian` and `django-rules` are the libraries.

Roles: `user.is_staff`, `user.is_superuser`, `user.groups`, `user.has_perm`. Reading a role from anywhere else — a request header, a body field, an unvalidated JWT claim — is SEC-012.

Third-party auth: `django-allauth` (`/accounts/login/`, `/accounts/signup/`, `ACCOUNT_*` and `SOCIALACCOUNT_PROVIDERS` settings), `djoser`, `dj-rest-auth`, `djangorestframework-simplejwt` (`/api/token/`, `/api/token/refresh/`, `SIMPLE_JWT` settings for lifetimes and rotation — SEC-027).

Session cookies: `SESSION_COOKIE_NAME` (default `sessionid`), `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY` (default `True`), `SESSION_COOKIE_SAMESITE` (default `'Lax'`), `SESSION_COOKIE_AGE` (default two weeks), `SESSION_EXPIRE_AT_BROWSER_CLOSE`, `SESSION_ENGINE` (database, cache, or signed-cookie — the signed-cookie backend cannot be invalidated server-side, which matters for SEC-026). Password hashing is `PASSWORD_HASHERS`, PBKDF2 by default with Argon2 available (SEC-019).

## webhook handlers
A normal view decorated `@csrf_exempt` (and, in DRF, a view with `authentication_classes = []` and `permission_classes = [AllowAny]`), routed with an explicit `path()`. The raw body is `request.body`, which is `bytes`. Read it **first**: touching `request.POST` or `request.data` consumes the stream and a later `request.body` raises `RawPostDataException`. Signature headers arrive as `request.headers['Stripe-Signature']` (or `request.META['HTTP_STRIPE_SIGNATURE']` on older code). Return 200 quickly and hand the work to a task (PERF-013); store the provider's event id for idempotency (SEC-051).

## webhook verification snippet
```python
# app/views/webhooks.py
import stripe
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponseBadRequest("bad signature")
    process_stripe_event.delay(event["id"], event["type"])
    return HttpResponse(status=200)
```
`stripe.SignatureVerificationError` is the modern path; older code raises `stripe.error.SignatureVerificationError` from the legacy `stripe.error` module, which still resolves in current releases — match whichever the project's pinned version uses rather than rewriting it. `stripe.Webhook.construct_event` enforces the timestamp tolerance itself (300 seconds by default), which is the replay defence SEC-051 asks about. This is the shape verification takes on this stack, not a file to drop in: the route, the settings accessor, and the dispatch call are the project's own. For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
The Django ORM. Models `<app>/models.py`, migrations `<app>/migrations/`, `DATABASES` in settings. There is no single schema file — the migration set *is* the schema, and `python manage.py sqlmigrate <app> <number>` prints the SQL for one.

**Connection pooling** (DAT-008): Django opens a connection per request and closes it unless `CONN_MAX_AGE` is set (persistent connections) or `CONN_HEALTH_CHECKS` is on; with many gunicorn workers and no external pooler that is a connection per worker per request, which is what exhausts Postgres. An external pooler (PgBouncer, RDS Proxy) in the `HOST`/`PORT` changes the answer. **Row-level security** (DAT-001, DAT-002): Django does not use it. The ORM connects as one database user with access to every row and all authorization is application code, so unless a migration contains `enable row level security` by hand, record RLS as not in use and let SEC-011 and DAT-026 carry that ground.

**SQL sinks** (SEC-038): `Model.objects.raw(f"select ... {x}")`, `Model.objects.raw("... %s" % x)`, `.extra(where=[f"..."], select={...})`, `connection.cursor().execute(f"...")`, `RawSQL("... " + x, [])`, `.annotate(v=RawSQL(...))`. Safe forms: `Model.objects.raw("select ... where id = %s", [x])`, `cursor.execute(sql, [x])`, and ordinary queryset filters. Note that `%s` here is the driver's placeholder, not Python string formatting — `execute("... %s" % x)` and `execute("... %s", [x])` look almost identical and one of them is an injection. `.extra()` has been documented as slated for deprecation for years without being removed, so it is still live code you will find in real projects — and its `where`/`tables` arguments are not escaped at all.

**Dynamic identifiers** (SEC-040): `order_by(request.GET['sort'])`, `filter(**request.GET.dict())`, `values(*request.GET.getlist('fields'))`. Django validates field names against the model for `order_by` and `filter`, which limits the damage to field enumeration and related-model traversal (`user__password` in a `values()` is a real leak), but a user-controlled `**kwargs` into `filter` can still reach relations the view never intended.

**Mass assignment** (SEC-041): the guard is the form or serializer field list. Failures: `ModelForm` with `fields = '__all__'` or with `exclude` (which admits any column added later), `ModelSerializer` with `fields = '__all__'` — that is both a write hole (SEC-041) and a read leak (SEC-042), since the same list drives the response — and `Model.objects.create(**request.data)` / `Model(**request.POST.dict())`. The fix is an explicit `fields = ['name', 'bio']` and `read_only_fields` for anything the server owns. Then list the privileged columns (`is_staff`, `is_superuser`, `role`, `plan`, `credits`, `balance`, `verified`, `org_id`, `stripe_customer_id`) and confirm no form or serializer reaches them.

**N+1 and pagination**: `select_related` (FK, join) and `prefetch_related` (M2M/reverse, second query) are the fixes; `django-debug-toolbar` or `nplusone` in the dev dependencies means the project already has the detector (DAT-010). Pagination: `django.core.paginator.Paginator` for views; DRF paginates only when `DEFAULT_PAGINATION_CLASS` **and** `PAGE_SIZE` are both set — a `ListAPIView` with neither returns every row (DAT-011).

**Migrations for DAT-015**: Django does not read `DATABASE_URL` unless the project uses `dj-database-url` or `django-environ` — grep `settings.py` for those before relying on an env override. Otherwise write a scratch settings module beside the project settings that does `from <project>.settings import *` then replaces `DATABASES`, and run `DJANGO_SETTINGS_MODULE=prelaunch_scratch_settings python manage.py migrate`; never edit the real settings file. Confirm the redirect took with `python manage.py showmigrations` under the same override before running anything that writes. Drift check: `python manage.py makemigrations --check --dry-run` must report no changes. Rollback is `python manage.py migrate <app> <previous_number>`, which requires the migration's operations to be reversible — `RunPython` with no `reverse_code` raises `IrreversibleError`, and `RunSQL` with no `reverse_sql` does the same.

## file uploads
`models.FileField` / `ImageField` with `upload_to=`, stored via the default storage backend. Locally that is `FileSystemStorage` writing under `MEDIA_ROOT` and served at `MEDIA_URL` — and in production Django does not serve `MEDIA_ROOT` at all, so something else does; find out what (SEC-048: uploads served from the app's own origin are an XSS vector).

`django-storages` is the usual production backend: `STORAGES["default"]` (Django 4.2+) or `DEFAULT_FILE_STORAGE` set to `storages.backends.s3.S3Storage`. The settings that matter:
- `AWS_DEFAULT_ACL` — `'public-read'` makes every uploaded object world-readable (DAT-005, DAT-006). `None` inherits the bucket's own policy.
- `AWS_QUERYSTRING_AUTH` — `True` (the default) makes `.url` a signed, expiring URL, which is SEC-050's mechanism; setting it `False` makes every URL permanent and public.
- `AWS_QUERYSTRING_EXPIRE` — the signature lifetime, default one hour.

Validation is not automatic. `ImageField` requires Pillow and does verify the file parses as an image, which is a real (if partial) content check; `FileField` verifies nothing. Look for `FileExtensionValidator`, a `validate_image_file_extension` call, a custom `clean_<field>`, or magic-byte sniffing (`python-magic`, `filetype`) — the client-supplied `content_type` on an `UploadedFile` is not evidence (SEC-047, SEC-049).

Size limits: `DATA_UPLOAD_MAX_MEMORY_SIZE` (default 2.5 MB) is the cap on a whole non-file request body and raises `RequestDataTooBig` above it — that is SEC-067's answer for JSON bodies. `FILE_UPLOAD_MAX_MEMORY_SIZE` (also 2.5 MB) is only the in-memory-versus-temp-file threshold and caps nothing. `DATA_UPLOAD_MAX_NUMBER_FIELDS` (default 1000) bounds form field count. Uploaded file size itself is unbounded by Django — the per-field cap has to be a validator, and the hard ceiling is the proxy's (`client_max_body_size`).

## background jobs
Nothing ships with Django. What to look for, and what each implies:
- **Celery**: `<project>/celery.py` with `app = Celery('<project>')` and `app.autodiscover_tasks()`, imported from `<project>/__init__.py`; tasks are `@shared_task` in `<app>/tasks.py`; called as `task.delay(...)` or `task.apply_async(...)`; worker `celery -A <project> worker -l info`; broker `CELERY_BROKER_URL` (Redis or RabbitMQ). **`CELERY_TASK_ALWAYS_EAGER = True` runs every task inline in the request** — fine in tests, PERF-013 in production. Scheduling is `celery -A <project> beat` with `CELERY_BEAT_SCHEDULE`, or `django-celery-beat` storing schedules in the database.
- **django-rq / RQ**: `RQ_QUEUES` in settings, `django_rq.enqueue(...)`, worker `python manage.py rqworker`, dashboard at `/django-rq/` if mounted (SEC-013).
- **django-q / django-q2**: `Q_CLUSTER` in settings, `async_task(...)`, worker `python manage.py qcluster`.
- **Huey, Dramatiq, django-tasks**: same shape, different names.
- **System cron** calling `python manage.py <command>` for a management command in `<app>/management/commands/`.

Confirm the worker process is actually started in production — `Procfile`, `docker-compose.yml`, the systemd unit, the platform's worker dyno. A configured broker with no running worker means every queued job sits forever and looks identical to success from the request side (REL-019).

Email: `send_mail` / `EmailMessage.send()` called inside a view is synchronous and is PERF-013's headline finding on this stack; the fix is a task.

## error handling and logging
`DEBUG = False` in production is the whole game. With `DEBUG = True` an unhandled exception renders Django's technical 500 page containing the traceback, every local variable at each frame, the full settings dict (with `SECRET_KEY` and `DATABASES` redacted only for names matching Django's own filter), the request META, and the installed apps; a 404 renders a page listing every URL pattern in the project. That is SEC-008 and SEC-009 in one setting. Watch for `DEBUG = os.environ.get('DEBUG', True)` and `DEBUG = env.bool('DEBUG', default=True)` — a defaulted-true debug flag is the version of this bug that survives code review.

`ALLOWED_HOSTS` is enforced only when `DEBUG` is False; empty is a hard error at that point, and `['*']` accepts any `Host` header, which lets an attacker poison absolute URLs the app builds for password-reset emails (SEC-022).

Custom error pages: `handler404`, `handler500`, `handler403`, `handler400` assigned in the root URLconf, with templates `404.html`, `500.html` in a template directory. The 500 handler runs with no template context by design — a handler that renders the exception into the page reintroduces SEC-009.

Sensitive-data controls: `@sensitive_variables()` and `@sensitive_post_parameters()` decorate views so the error report redacts those values, and `DEFAULT_EXCEPTION_REPORTER_FILTER` sets the global filter. Without them, a password submitted to a view that then raises appears in the error email and in whatever the error tracker captured (REL-002, REL-015).

Logging: the `LOGGING` dict in settings (`dictConfig` format). The `django.request` logger emits 4xx at WARNING and 5xx at ERROR; `django.db.backends` logs every query at DEBUG. `ADMINS` plus `mail_admins` sends error emails with the full traceback — check where that address goes. `structlog` and `python-json-logger` are the structured-logging options (REL-015).

Reporting: `sentry_sdk.init(dsn=..., integrations=[DjangoIntegration()])` in settings. The Celery worker is a separate process and needs `CeleryIntegration()` in its own init path, which is REL-001's usual gap on this stack. `send_default_pii=False` and a `before_send` scrubber for REL-002. Rollbar, Bugsnag, and Honeybadger install the same way.

## security headers
All of these are applied by `django.middleware.security.SecurityMiddleware` — if it is missing from `MIDDLEWARE`, none of them take effect regardless of the settings values, so check the list first.

- `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD` (SEC-032). Zero or unset means no HSTS.
- `SECURE_SSL_REDIRECT` plus `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` behind a terminating proxy (SEC-034, SEC-016 — trusting that header without a trusted proxy in front lets a client claim HTTPS).
- `SECURE_CONTENT_TYPE_NOSNIFF` and `SECURE_REFERRER_POLICY` (SEC-033). Both have had secure defaults for several releases; confirm the value the running version actually uses rather than assuming, and quote `check --deploy`.
- `X_FRAME_OPTIONS`, applied by `XFrameOptionsMiddleware` — `DENY` in recent defaults, `SAMEORIGIN` in older ones; check the version.
- `SECURE_CROSS_ORIGIN_OPENER_POLICY`.
- Cookies: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE`, `CSRF_COOKIE_SAMESITE` (SEC-025).

CSP is not part of Django in the 4.x and 5.x line — it comes from `django-csp` (`csp.middleware.CSPMiddleware` plus `CSP_*` settings in older releases, or a single `CONTENT_SECURITY_POLICY` dict in newer ones; check which the installed version uses). Its absence is SEC-031.

CSRF: `django.middleware.csrf.CsrfViewMiddleware` is in the default `MIDDLEWARE`; templates emit `{% csrf_token %}`; the cookie is `csrftoken` and the header `X-CSRFToken`. `CSRF_TRUSTED_ORIGINS` must list the production origin (scheme included) when the app is behind a proxy. Opt-outs are `@csrf_exempt` on a view and `csrf_exempt` wrapping in the URLconf — each must be a signature-verified webhook or an equivalent (SEC-030). DRF's `SessionAuthentication` enforces CSRF; `TokenAuthentication` and JWT do not, and do not need to, provided no cookie fallback exists.

CORS: `django-cors-headers` with `corsheaders.middleware.CorsMiddleware` high in `MIDDLEWARE`. `CORS_ALLOW_ALL_ORIGINS = True` is SEC-035; `CORS_ALLOWED_ORIGINS` is the allowlist; `CORS_ALLOW_CREDENTIALS = True` combined with a wildcard or a regex that matches everything is the dangerous pair.

## known traps
- `DEBUG = True` in the production settings module, or `DEBUG = env.bool('DEBUG', default=True)`: SEC-008 and SEC-009 together — the technical 500 page prints settings, locals, and SQL.
- `ALLOWED_HOSTS = ['*']` or empty with `DEBUG` false: SEC-022.
- `SECRET_KEY` as a literal in a tracked settings file, or a `DATABASES` block with a real password: SEC-001, SEC-006.
- A DRF view or `ModelViewSet` with no `permission_classes` while `DEFAULT_PERMISSION_CLASSES` is unset — DRF defaults to `AllowAny`, so the whole model is public CRUD: SEC-010, and SEC-012 where the model is administrative.
- `LoginRequiredMixin` listed after the view class in the bases, so it never runs: SEC-010.
- `get_object_or_404(Model, pk=pk)` with no owner predicate: SEC-011.
- `@csrf_exempt` on anything that is not a signature-verified webhook: SEC-030.
- `ModelForm`/`ModelSerializer` with `fields = '__all__'` or only an `exclude` list: SEC-041 for writes and SEC-042 for the response.
- `.raw()` or `cursor.execute()` with an f-string or `%`-formatting, or any `.extra()`: SEC-038. `order_by(request.GET['sort'])` or `filter(**request.GET.dict())`: SEC-040.
- `mark_safe`, `|safe`, `{% autoescape off %}`, or `format_html` with an unescaped interpolation on user content: SEC-043.
- `SecurityMiddleware` or `CsrfViewMiddleware` removed from `MIDDLEWARE`: SEC-030, SEC-032, SEC-033 all silently off.
- `CORS_ALLOW_ALL_ORIGINS = True`, or a `CORS_ALLOWED_ORIGIN_REGEXES` that matches everything, with credentials on: SEC-035.
- `AWS_DEFAULT_ACL = 'public-read'` or `AWS_QUERYSTRING_AUTH = False` in django-storages: DAT-005, DAT-006, SEC-050.
- A DRF list endpoint with no `DEFAULT_PAGINATION_CLASS` and `PAGE_SIZE`: DAT-011.
- `CELERY_TASK_ALWAYS_EAGER = True` outside tests, or `send_mail` called inline in a view: PERF-013.
- A broker configured with no worker process started in the deploy, or `celery beat` never run: REL-019.
- `debug_toolbar` in `INSTALLED_APPS` or `MIDDLEWARE` for production, and `INTERNAL_IPS` widened to make it show: SEC-008, SEC-013.
- A superuser created by a seed or fixture with a known password: SEC-060, DAT-016.
- `python manage.py check --deploy` never run: it is the cheapest evidence available for SEC-025, SEC-032, SEC-033, and SEC-034 on this stack, so run it against the production settings module and quote its output rather than re-deriving each setting by hand.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if the project already depends on one (`package.json` devDependencies, or `selenium`/`playwright`/`pytest-playwright` in the dev requirements); never install one for the audit. Cited by the accessibility and compliance domain headers, COMP-007, and FLOW-018.

## runtime probe hints
**Session cookie for `curl`.** Django's login is a form POST guarded by CSRF, so it needs the `csrftoken` cookie, the matching `csrfmiddlewaretoken` field, and a `Referer` that satisfies the origin check when the request is HTTPS:
```bash
JAR=.pre-launch/flows/cookies.txt
curl -s -c "$JAR" http://localhost:8100/accounts/login/ -o .pre-launch/flows/login.html
TOKEN=$(grep -o 'name="csrfmiddlewaretoken" value="[^"]*"' .pre-launch/flows/login.html | head -1 | sed 's/.*value="//;s/"$//')
curl -s -b "$JAR" -c "$JAR" -X POST http://localhost:8100/accounts/login/ \
  -H 'Referer: http://localhost:8100/accounts/login/' \
  --data-urlencode "csrfmiddlewaretoken=$TOKEN" \
  --data-urlencode 'login=qa+1700000000@example.com' \
  --data-urlencode 'password=<from credentials_env>' -i
curl -s -b "$JAR" http://localhost:8100/dashboard/ -o /dev/null -w '%{http_code}\n'
```
The field names vary: plain `django.contrib.auth` uses `username` and `password` at `/accounts/login/` or wherever `LoginView` is routed; `django-allauth` uses `login` and `password` at `/accounts/login/` and `/accounts/signup/`. Read the rendered form's `<input name=...>` rather than trusting either. The `csrftoken` cookie value and the form token are different encodings of the same secret in modern Django, so send both — the cookie from the jar and the field from the HTML.

**Cookie names.** `sessionid` and `csrftoken` unless `SESSION_COOKIE_NAME` / `CSRF_COOKIE_NAME` are set — grep settings for both. `messages` carries flash messages and is not a credential.

**JWT for API probes.** DRF makes a bearer probe easy when it is configured:
```bash
# djangorestframework-simplejwt
curl -s -X POST http://localhost:8100/api/token/ -H 'content-type: application/json' \
  -d '{"username":"...","password":"..."}' | jq -r .access
# DRF TokenAuthentication (note the scheme is "Token", not "Bearer")
curl -s -X POST http://localhost:8100/api-token-auth/ -d 'username=...&password=...' | jq -r .token
```
Then `-H "Authorization: Bearer <access>"` for SimpleJWT or `-H "Authorization: Token <key>"` for DRF tokens. Find the real token route in the URLconf first; both paths above are conventions, not defaults. If neither exists, the session cookie is the only credential: record `n/a — no token endpoint`. DAT-002's per-user RLS probe needs a data API that authorizes as the end user, which Django does not provide — the ORM connects as one database user for everyone — so record `n/a — no PostgREST surface` there and cover the same ground with SEC-011's two-account probe and DAT-026's privilege check.

**Health path.** No convention. Grep the URLconf for `health`, `healthz`, `ping`, `status`; `django-health-check` mounts at `/ht/` by default and reports database, cache, and storage status, which is what REL-006 wants. If nothing exists use the cheapest static page for cold-start timing and say which you used.

**Not-found behaviour.** With `DEBUG = False` an unmatched path renders `404.html` (or Django's plain page) with status 404. With `DEBUG = True` it renders a page listing every URL pattern in the project, which is a route-table disclosure and is itself SEC-008 evidence if it appears against the production build. `Http404` and `get_object_or_404` produce the same 404. Check the status code and not just the body: a catch-all pattern rendering a "not found" template with status 200 is a soft 404 (SEO).

**Test-mode provider keys.** `printenv | grep -iE 'stripe|paypal|paddle'` on the running process first, then `.env`, then `python manage.py shell -c "from django.conf import settings; print(str(settings.STRIPE_SECRET_KEY)[:8])"`. Stripe `sk_test_` / `pk_test_` / `rk_test_` and a `whsec_` from `stripe listen`; PayPal on `api-m.sandbox.paypal.com`; Paddle, Lemon Squeezy, and RevenueCat a sandbox host, flag, or key. Published test card numbers live in the payment provider's own stack file. If the classification is ambiguous, treat the keys as live and stop.

**Local mail catcher.** Read `EMAIL_BACKEND` first, because it decides where the "inbox" is:
- `django.core.mail.backends.console.EmailBackend` prints the whole message to the server process's stdout. That is capturable only if you started the server with its output redirected — so start the production-mode server as `gunicorn ... > .pre-launch/flows/server.log 2>&1 &` and grep that file for the message.
- `django.core.mail.backends.filebased.EmailBackend` with `EMAIL_FILE_PATH` writes one file per message; that directory is the most reliable capture on this stack.
- `django.core.mail.backends.locmem.EmailBackend` collects into `django.core.mail.outbox` inside the process and is unreadable from outside — treat it as no capture.
- `smtp.EmailBackend` with `EMAIL_HOST=localhost` and `EMAIL_PORT=1025` means a catcher is expected: check `docker-compose.yml` for `axllent/mailpit` (HTTP `8025`, `curl -s http://localhost:8025/api/v1/messages`), `mailhog/mailhog` (API `/api/v2/messages`), or `inbucket/inbucket`.
- A provider backend (`django-anymail` with `RESEND_API_KEY`, `SENDGRID_*`, `POSTMARK_*`) in test mode means the inbox is the provider's own test log.

No reachable catcher is `error: no mail capture`, never a pass.

**Throwaway identity.** Sign up through the app's own sign-up route with `qa+<unix-ts>@example.com` and the password from the config's `credentials_env`, using the CSRF dance above; never create the user with `manage.py shell` or `createsuperuser`, because that skips exactly the flow FLOW-001 is testing. Use the shell only for cleanup: `python manage.py shell -c "from django.contrib.auth import get_user_model; get_user_model().objects.filter(email__startswith='qa+').delete()"` — the cascade that runs there is also DAT-020's evidence.
