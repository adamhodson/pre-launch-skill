# FastAPI

## detection signals
`fastapi` in `requirements.txt`, `pyproject.toml`, or `Pipfile`, and a `FastAPI()` instantiation — usually `app = FastAPI(...)` in `app/main.py`, `main.py`, `src/main.py`, or `app/__init__.py` behind a `create_app()` factory. Routers are `APIRouter()` objects in `app/routers/`, `app/api/`, or `app/api/v1/endpoints/`. `uvicorn`, `hypercorn`, or `gunicorn` in the dependencies is the server; `alembic.ini` plus `alembic/versions/` is the migration system; `sqlalchemy`, `sqlmodel`, `tortoise-orm`, `beanie`, or `prisma` is the data layer.

**Check the Pydantic major version before reading any model** — `python -c "import pydantic; print(pydantic.VERSION)"` or the pin. Pydantic v2 uses `model_config = ConfigDict(...)`, `model_validate`, `model_dump`, `@field_validator`, and `pydantic-settings` as a separate package; v1 uses an inner `class Config`, `parse_obj`, `.dict()`, `@validator`, and `BaseSettings` from `pydantic` itself. The two look similar enough to misread and the settings class is where REL-008's variable list lives.

A `frontend/` or `client/` directory with its own `package.json` is a separate SPA with its own stack file, build, and public env prefix.

## dev server
`uvicorn app.main:app --reload --port 8000` (the module path before the colon, the `FastAPI` instance name after it). Newer releases ship `fastapi dev app/main.py`, which is the same thing with reload and a nicer banner — check whether `fastapi-cli` is installed before recommending it. Default port 8000.

Readiness: in development `GET /docs` or `GET /openapi.json` returning 200 is the quickest signal — but `/docs` is exactly what SEC-008 wants disabled in production, so for the production-mode run use `GET /` or the health route instead and note which you used.

`--reload` runs a file watcher and a single worker and changes traceback behaviour; never measure headers, error bodies, or performance against it. See "build".

## build
There is no build step for the Python code. The production sequence is:
1. `pip install -r requirements.txt` (or `poetry install --only main`, `uv sync --frozen`, `pdm install --prod`) — locked form for HYG-015's clean clone. Python version from `.python-version`, `pyproject.toml`'s `requires-python`, or the Dockerfile base image.
2. Migrations if any: `alembic upgrade head` (DAT-015 owns whether that is safe to run; do not run it against the project's own database as part of the audit).
3. Serve without reload, with more than one worker:
   `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 127.0.0.1:8100`, or `uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 4`, or `fastapi run app/main.py --port 8100`.
4. Set whatever environment flag the app uses to mean production — FastAPI has no built-in notion of one. Grep the settings class for `ENV`, `APP_ENV`, `ENVIRONMENT`, `DEBUG`, or `is_production`; that flag is usually what gates `docs_url`, CORS origins, and the log level, and if the app has no such flag then production and development behave identically, which is itself worth reporting.

There is no server-side bundle, so SEC-003's "grep the build output" step has nothing to grep here — say so, and point it at the SPA's build directory if the repo contains one (which is also where SEC-007's source maps would be). Compression (PERF-003) is Starlette's `GZipMiddleware` or the proxy in front; neither is on by default. Deployment shape (PERF-016): uvicorn or gunicorn workers are long-lived, so there is no cold start to measure and that check is `n/a — long-lived process` unless the app is deployed to Lambda through Mangum or to a scale-to-zero container, in which case the platform's stack file owns the number.

The real deployable is usually a container: `Dockerfile` is the build, `docker build` is the clean-clone reproduction, and the `CMD`/`ENTRYPOINT` is the authoritative production start command — read it rather than inventing one.

## env vars
`os.environ['X']` (raises — loud), `os.environ.get('X')` (silent `None`), `os.getenv('X', 'default')` (the silent fallback), `python-dotenv`'s `load_dotenv()`.

**`pydantic-settings` is the common pattern and, where it exists, the authoritative list for REL-008.** Look for `app/config.py` or `app/core/config.py`:
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")  # v2; v1 uses `class Config: env_file = ".env"`
    database_url: str
    secret_key: str = "changeme"      # <- a defaulted secret is REL-008 and SEC-001 at once
    stripe_webhook_secret: str | None = None
```
Read every field: one with **no default** fails validation at import and takes the app down loudly if the variable is missing, which is the good case. One **with a default** silently runs production in a different mode — and a default on `secret_key`, a signing secret, an allowed-origins list, or an admin email is the failure REL-008 exists to catch. Field names map to environment variables case-insensitively, optionally with an `env_prefix`, so `database_url` reads `DATABASE_URL`; note the prefix if one is set or the diff against `.env.example` will be wrong.

`@lru_cache` around a `get_settings()` function is the usual accessor, injected as `Depends(get_settings)`. REL-008's second set — the variables that are *declared* — comes from `.env.example` / `.env.sample` if the project keeps one, plus the deploy config (`Dockerfile` `ENV` lines, `docker-compose.yml` `environment`, `fly.toml`, `render.yaml`, Kubernetes manifests, the CI workflow's `env` blocks).

**Public prefix**: none. FastAPI serves no client bundle and inlines nothing. A secret reaches the browser only through a response body — check for a `/config` or `/api/settings` endpoint returning the settings object, and for `settings.model_dump()` / `settings.dict()` being returned anywhere (that dumps every field including the secrets). If the repo contains an SPA, its bundler's prefix applies to that build.

**Payment test-mode detection**: `printenv | grep -i stripe` on the running process, then `.env`, then `python -c "from app.core.config import settings; print(settings.stripe_secret_key[:8])"` with the project's import path. The `sk_test_` / `pk_test_` prefix is the tell.

## routes and handlers
Decorators on the app (`@app.get("/health")`) or, far more often, on a router:
```python
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_current_user)])
@router.get("/{user_id}")
async def read_user(user_id: int, ...): ...
```
wired in `main.py` with `app.include_router(router, prefix="/api/v1", dependencies=[...])`. **The full path is the concatenation of the `include_router` prefix, the `APIRouter` prefix, and the decorator path**, and the guard can be attached at any of those three levels — which is why reading a handler alone tells you nothing about whether it is protected.

**The best route enumeration of any stack in this reference is the app's own OpenAPI document.** Against a running instance:
```bash
curl -s http://localhost:8100/openapi.json > .pre-launch/openapi.json
jq -r '.paths | to_entries[] | .key as $p | .value | to_entries[] | "\(.key|ascii_upcase) \($p)"' .pre-launch/openapi.json | sort
```
Without a running instance, import the app and read `app.routes`:
```bash
python -c "from app.main import app; [print(sorted(r.methods), r.path) for r in app.routes if hasattr(r,'methods')]"
```
That list is complete, includes the prefixes, and is what SEC-010's route inventory should be built from. If `openapi_url` has been disabled for production (which SEC-008 wants), use the import form.

Other surfaces: `app.mount("/static", StaticFiles(directory="static"))`, `app.add_middleware(...)` and `@app.middleware("http")`, WebSocket routes (`@router.websocket("/ws")` — SEC-055), and the documentation routes `/docs` (Swagger UI), `/redoc`, and `/openapi.json`, all on by default and disabled with `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`.

Dependencies are the shared-logic mechanism: `Depends(get_db)`, `Depends(get_current_user)`, `Depends(get_settings)`. `dependencies=[Depends(...)]` on the router or `include_router` applies one to every route beneath without injecting its value.

## auth
The mechanism is a dependency. `Depends(get_current_user)` as a parameter default, or `dependencies=[Depends(get_current_user)]` on the router, `include_router`, or the whole app. FastAPI provides the *scheme* helpers, not the verification:
- `OAuth2PasswordBearer(tokenUrl="token")` — reads `Authorization: Bearer`, and its `tokenUrl` names the login route.
- `HTTPBearer()`, `HTTPBasic()`, `APIKeyHeader(name="X-API-Key")`, `APIKeyCookie`.
- `Security(get_current_user, scopes=["items:write"])` with `SecurityScopes` for scope checks.

The verification is in the `get_current_user` function, and it is where SEC-027 lives: `jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])` with `python-jose` or `pyjwt`. Read it for a pinned `algorithms` list (a missing one, or one including `"none"`, is the classic), `options={"verify_signature": False}` or `verify_exp: False`, and whether the user is re-loaded from the database or the claims are trusted whole.

**The SEC-010 gap on this stack** is a path operation with no `Depends(get_current_user)` in its signature, on a router that was included without `dependencies=[...]`. The OpenAPI document makes this checkable in one command, because a route whose guard is a declared security scheme carries a `security` key:
```bash
jq -r '.paths | to_entries[] | .key as $p | .value | to_entries[] | select(.value.security == null) | "\(.key|ascii_upcase) \($p)"' .pre-launch/openapi.json
```
That list is a strong first pass, not a verdict — a hand-rolled dependency that reads a cookie or header without using a `SecurityBase` scheme will not appear in `security` even though it does guard the route, so confirm each hit against the source. Do the reverse too: a route in the list that turns out to be genuinely public should be named as such.

Roles (SEC-012): a `require_admin` dependency reading `current_user.is_admin` or `current_user.role` from the database row, or a `Security(..., scopes=["admin"])`. A role taken from a JWT claim that the app issues at sign-up and never re-checks is the trap. Admin UIs: `sqladmin` (mounted with `Admin(app, engine)`, and it takes an `authentication_backend=` argument that is **optional** — without it `/admin` is a full unauthenticated CRUD interface over every registered model, which is SEC-012 and SEC-013 at once), `fastapi-admin`, `starlette-admin`.

Sessions: FastAPI is stateless by default. `SessionMiddleware` from Starlette adds an itsdangerous-signed cookie (default name `session`, `session_cookie=` to rename, `https_only=` and `same_site=` for SEC-025) — its presence means cookie auth, and therefore that CSRF applies. `fastapi-users` and `authlib` bring their own flows.

## webhook handlers
An ordinary POST route that declares `request: Request` and **no Pydantic body model** — declaring one makes FastAPI read and validate the body before your code runs, and then the signature is computed over a re-serialization rather than the bytes. Read the raw body with `await request.body()`, which returns `bytes`; Starlette caches it, so a later `await request.json()` on the same request is fine.

Webhook routes must also be excluded from any app-wide auth dependency (the provider has no session) and, if `SessionMiddleware` and a CSRF scheme are in play, from that too. Return 200 quickly and hand the work to a real queue (PERF-013); store the provider's event id for idempotency (SEC-051).

## webhook verification snippet
```python
# app/routers/webhooks.py
import stripe
from fastapi import APIRouter, Request, Response, HTTPException
from app.core.config import settings

router = APIRouter()

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()                     # raw bytes, no body model declared
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="bad signature")

    await enqueue_stripe_event(event["id"], event["type"])   # a real queue, not BackgroundTasks
    return Response(status_code=200)
```
`stripe.Webhook.construct_event` enforces the timestamp tolerance itself (300 seconds by default), which is the replay defence SEC-051 asks about. For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
SQLAlchemy is the usual choice, in one of two shapes that behave very differently:
- **Sync** — `create_engine`, `sessionmaker`, `Session`, a `get_db()` dependency yielding a session. Correct, and safe inside a `def` (non-async) path operation, which FastAPI runs in a threadpool.
- **Async** — `create_async_engine`, `async_sessionmaker`, `AsyncSession`, `await session.execute(...)`, with `asyncpg` or `aiomysql` as the driver.

**The FastAPI-specific performance bug is mixing them**: a synchronous database call, a `requests.get(...)`, or any other blocking IO inside an `async def` path operation blocks the whole event loop, so one slow query stalls every concurrent request in that worker (PERF-019). The fix is either an async driver or declaring the handler as plain `def`. Grep for `async def` handlers containing `session.query(`, `requests.`, `time.sleep`, or `open(`.

Other layers: **SQLModel** (SQLAlchemy plus Pydantic in one class — see the mass-assignment note below), **Tortoise ORM**, **Beanie/Motor** for MongoDB (SEC-039 operator injection applies), **`databases`/asyncpg** raw, **Prisma Client Python**.

**SQL sinks** (SEC-038): `session.execute(text(f"select * from users where email = '{email}'"))`, `conn.execute(f"...")`, `.filter(text(f"..."))`, and any `text()` whose argument is built by formatting. The safe form is bound parameters: `session.execute(text("select * from users where email = :e"), {"e": email})`, or ORM expressions. Dynamic identifiers cannot be bound — `order_by(text(request_sort))` needs a hardcoded allowlist (SEC-040).

**Mass assignment and over-exposure** (SEC-041, SEC-042): Pydantic is the guard, and it works exactly as well as the schema is drawn.
- A request model containing only the fields the user may set (`class UserCreate(BaseModel): email: str; password: str`) is a correct guard, and `User(**payload.model_dump())` is then safe.
- A request model that mirrors the ORM model, or **SQLModel used as both the table class and the request body**, hands the user every column including `is_admin` and `credits` — that is SEC-041 on this stack, and the same class used as `response_model` is SEC-042 (it will serialize `hashed_password` if the column is on it).
- A handler taking `payload: dict`, `payload: Any`, or `await request.json()` bypasses validation entirely: SEC-037.
- `response_model=UserRead` on the decorator is what actually trims the response; without it FastAPI serializes whatever the function returns, ORM object included.

**Connection pooling** (DAT-008): SQLAlchemy's engine pools by default — `pool_size` and `max_overflow` on `create_engine`/`create_async_engine`, multiplied by the number of uvicorn workers, is the real ceiling against the database's `max_connections`. `poolclass=NullPool` disables pooling and is correct in front of PgBouncer and wrong otherwise. Creating an engine per request instead of once at module scope is the bug. **Row-level security** (DAT-001, DAT-002): unless the app is fronting Supabase or another PostgREST-style service, it connects as one database user with access to every row and all authorization is application code — record RLS as not in use and let SEC-011 and DAT-026 carry that ground.

**Pagination** (DAT-011): nothing is built in. `limit: int = 20` as a query parameter with `le=100` in a `Query(...)` is the pattern; a `.all()` with no limit, or a `limit` with no ceiling, is the finding. `fastapi-pagination` is the library.

**Migrations for DAT-015**: Alembic. `alembic upgrade head`, `alembic current`, `alembic check`, `alembic history`, `alembic downgrade -1`. Vanilla `env.py` reads `sqlalchemy.url` **from `alembic.ini`**, not from `DATABASE_URL` — so open `alembic/env.py` and check before relying on an env override. Many projects patch it to read `os.environ["DATABASE_URL"]` or the settings object; if it does, a one-shot prefix works. If it does not, copy `alembic.ini` to a temporary file, set `sqlalchemy.url` in the copy, and run `alembic -c /tmp/prelaunch-alembic.ini upgrade head`; `alembic -x db_url=... upgrade head` works only if `env.py` reads the `-x` argument. Confirm the target with `alembic -c <tmp ini> current` before anything writes. A `downgrade()` body that is `pass` is no rollback. A production `alembic.ini` with a real password in `sqlalchemy.url` is SEC-006.

## file uploads
`async def upload(file: UploadFile = File(...))` — `UploadFile` is a `SpooledTemporaryFile`, held in memory up to a threshold (around 1 MB in current Starlette) and then written to a temp file, so it does not load a large upload into RAM. Declaring the parameter as `bytes = File(...)` instead reads the **entire** body into memory, which is a denial-of-service surface on any large upload. `python-multipart` must be installed or form and file parsing raises at import.

**FastAPI enforces no size limit at all.** There is no `MAX_UPLOAD_SIZE` setting. The cap has to come from the reverse proxy (`client_max_body_size`), the platform, or a manual check — reading `request.headers.get("content-length")` before consuming, or counting bytes while chunk-reading `await file.read(size)` in a loop and aborting past a threshold. Its absence is SEC-067 and, for uploads, SEC-047.

Content validation: `file.content_type` and `file.filename` are **client-supplied**. A real check is magic bytes (`python-magic`, `filetype`) or a Pillow open-and-re-encode, which also strips EXIF and neutralizes a polyglot (SEC-047, SEC-049 for SVG — SVG is XML and executes script when served inline, so block it or sanitize it).

Storage: a local path (then something else has to serve it — SEC-048 if that is the app's own origin), or `boto3`/`aioboto3` to S3. `ExtraArgs={'ACL': 'public-read'}` on an upload makes the object world-readable (DAT-005, DAT-006); `generate_presigned_url('get_object', ..., ExpiresIn=300)` is the signed-expiring pattern SEC-050 wants, and `generate_presigned_post` is the direct-to-bucket upload that bypasses the app (so its constraints must be in the presign call).

Serving: `FileResponse(os.path.join(UPLOAD_DIR, name))` with `name` from the request is path traversal (SEC-046) — resolve and confine the path, or address files by database id.

## background jobs
**`BackgroundTasks` is not a queue.** `tasks.add_task(send_email, ...)` runs the function in the same process after the response is sent: it is lost on restart or crash, it has no retry, no visibility, and no dead-letter, and while it runs it occupies the worker (or the event loop, if the task is `async def`). PERF-013 accepts it only for genuinely trivial work — a fire-and-forget log write, a cache invalidation. Email, PDF generation, an AI call, an export, or an image resize belongs in a real queue, and finding those in `BackgroundTasks` is the expected finding on this stack. `asyncio.create_task(...)` with no reference kept is worse: the task can be garbage-collected mid-flight.

Real queues, in rough order of frequency: **Celery** (`app/worker.py` or `celery_app.py`, `@celery_app.task`, `.delay()`, worker `celery -A app.worker worker`, beat for schedules), **ARQ** (redis, asyncio-native, `WorkerSettings`, `arq app.worker.WorkerSettings`), **Dramatiq**, **RQ**, **SAQ**, **TaskIQ**, or a platform queue consumed by a separate service.

Scheduling: celery beat, **APScheduler** started in the app's lifespan (in-process — with `--workers 4` every job fires four times, REL-019), a system cron running a script, or a platform scheduler calling an HTTP endpoint (which then needs a shared secret compared in constant time — SEC-014, SEC-052).

Startup and shutdown: the `lifespan` async context manager passed as `FastAPI(lifespan=...)` is the current mechanism; `@app.on_event("startup")` / `("shutdown")` is the deprecated one. Check which the version uses. Anything started there runs once per uvicorn worker, which is the multiplication behind the APScheduler trap.

Confirm the worker process is actually started in production — the Dockerfile's second service, `docker-compose.yml`, the Procfile, the systemd unit. A broker configured with no consumer means every queued job sits forever and looks like success from the request side (REL-019).

## error handling and logging
FastAPI's **default** behaviour is safe: an unhandled exception produces `{"detail":"Internal Server Error"}` with status 500 and the traceback goes to the server log. The leaks are what people add on top:
- `FastAPI(debug=True)`, or Starlette's `ServerErrorMiddleware(debug=True)`, renders a full interactive traceback page with source and local variables into the response (SEC-008, SEC-009).
- A custom `@app.exception_handler(Exception)` returning `{"detail": str(exc)}` or `traceback.format_exc()` (SEC-009).
- `uvicorn --reload` in production, which prints tracebacks liberally.

Handlers: `@app.exception_handler(HTTPException)`, `@app.exception_handler(RequestValidationError)`, `@app.exception_handler(Exception)`. Note that a `RequestValidationError` response (422) **echoes the submitted input back** in the `input` field of each error entry — usually harmless, but a password or a token submitted to a route that then fails validation appears in the response body and in whatever logged it (REL-015). A custom validation handler that returns only the field names and messages avoids that.

`HTTPException(status_code=..., detail=...)` is the intentional-error mechanism; a `detail` built from an exception message reintroduces the leak.

Logging: `logging.config.dictConfig` in the app's startup, `structlog`, or `loguru`. Uvicorn has its own loggers — `uvicorn.error` and `uvicorn.access`, and the access logger records the **full path including the query string**, so any token or PII in a URL lands in the log (SEC-064, REL-015). `--no-access-log` or a custom formatter is the control. A `@app.middleware("http")` request logger that logs the body is REL-015's usual finding here.

Reporting: `sentry_sdk.init(dsn=..., integrations=[FastApiIntegration(), StarletteIntegration()])` called before the app is created. `send_default_pii` must stay `False` (REL-002), and a `before_send` scrubber for anything the app puts on the scope. The Celery or ARQ worker is a separate process and needs its own `sentry_sdk.init` with `CeleryIntegration()` — that is REL-001's usual gap on this stack.

## security headers
FastAPI and Starlette set **no** security headers. Everything is added deliberately:
- A `@app.middleware("http")` that sets headers on the response, or a custom `BaseHTTPMiddleware` subclass.
- The `secure` package (`secure.Secure()` with a headers set applied in middleware).
- The reverse proxy or CDN in front, in which case the local-tier probe sees nothing and the remote-tier probe sees everything — say which tier the evidence came from.

The absence of CSP is SEC-031, of HSTS SEC-032, of nosniff/frame-ancestors/Referrer-Policy/Permissions-Policy SEC-033. For a pure JSON API several of these matter less, but say that explicitly rather than passing silently: `X-Content-Type-Options: nosniff` still matters, and if the API serves any HTML (including `/docs`) so does the rest.

Starlette middleware worth finding:
- `TrustedHostMiddleware(allowed_hosts=[...])` — the `ALLOWED_HOSTS` equivalent, and its absence means the app will answer to any `Host` header and build absolute URLs from it (SEC-022).
- `HTTPSRedirectMiddleware` (SEC-034).
- `GZipMiddleware` (PERF-003) — not enabled by default.
- `CORSMiddleware` — `allow_origins=["*"]` together with `allow_credentials=True` is SEC-035. Browsers refuse that exact combination, which is why the workaround people reach for, `allow_origin_regex=".*"` or a middleware echoing the request's `Origin` back, is the finding that actually bites: it is a credentialed wildcard that works.

Rate limiting: nothing built in. `slowapi` (a `Limiter` keyed on `get_remote_address`) or the proxy's. `get_remote_address` reads `request.client.host`, which behind a proxy is the proxy — uvicorn's `--proxy-headers` with `--forwarded-allow-ips` is what makes `X-Forwarded-For` trusted, and trusting it from anywhere lets a client rotate its own limit key (SEC-016).

## known traps
- `/docs`, `/redoc`, and `/openapi.json` served in production: they hand over every route, every parameter, and every schema. `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` is the fix (SEC-008).
- A path operation with no `Depends(get_current_user)` on a router included without `dependencies=[...]` — check with the `security == null` jq filter above and confirm each hit in the source: SEC-010, SEC-012.
- `sqladmin`'s `Admin(app, engine)` mounted with no `authentication_backend`: `/admin` is unauthenticated CRUD over every model (SEC-012, SEC-013).
- `jwt.decode` with no `algorithms=[...]` pinned, or `options={"verify_signature": False}`, or a token whose `role` claim is never re-checked against the database: SEC-027, SEC-012.
- `CORSMiddleware(allow_origins=["*"], allow_credentials=True)`, or `allow_origin_regex=".*"`, or a middleware reflecting the request `Origin`: SEC-035.
- `text(f"...")`, `session.execute(f"...")`, or any SQL built by formatting: SEC-038. `order_by` built from a query parameter: SEC-040.
- A request schema that mirrors the ORM model, or SQLModel used as both the table and the request body: SEC-041. The same class as `response_model`, or no `response_model` at all: SEC-042.
- A handler taking `payload: dict`, `payload: Any`, or reading `await request.json()` directly, so nothing is validated: SEC-037.
- `BackgroundTasks` used for email, PDF generation, an AI call, an export, or an image resize: it is in-process and lost on restart, so PERF-013 wants a real queue.
- A sync database call, `requests.get`, or `time.sleep` inside an `async def` path operation: the event loop stalls for every concurrent request in that worker (PERF-019).
- `UploadFile` with no size check anywhere, or a parameter declared `bytes = File(...)`: SEC-067, SEC-047.
- No `TrustedHostMiddleware` behind a proxy that forwards the client's `Host`: SEC-022.
- `FastAPI(debug=True)` in production, or an exception handler returning `str(exc)`: SEC-008, SEC-009.
- The default `RequestValidationError` response echoing submitted values back, on a route that takes a password or token: REL-015.
- A `Settings` field with a default on a secret, a signing key, or an allowed-origins list: REL-008, and SEC-001 if the default is a real-looking value.
- A list endpoint with no `limit` ceiling: DAT-011.
- `alembic.ini` committed with a real production password in `sqlalchemy.url`: SEC-006.
- APScheduler started in the lifespan with `--workers 4`: every scheduled job fires four times (REL-019).
- Uvicorn's access log recording full URLs with query strings, where the app puts tokens in URLs: SEC-064, REL-015.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if the project already depends on one (`playwright`/`pytest-playwright`/`selenium` in the dev requirements, or a `package.json` devDependency); never install one for the audit. Cited by the accessibility and compliance domain headers, COMP-007, and FLOW-018.

## runtime probe hints
**Bearer token for `curl`.** This is the primary credential on this stack, not a fallback. The shape depends on the login route's signature, and there is one gotcha worth memorizing: **a route using `OAuth2PasswordRequestForm` takes form-encoded `username` and `password`, not JSON** — posting JSON to it returns 422 and looks like a broken login.
```bash
# OAuth2PasswordRequestForm (the FastAPI tutorial pattern) — form-encoded, field is "username"
TOKEN=$(curl -s -X POST http://localhost:8100/api/v1/login/access-token \
  -d 'username=qa@example.com&password=<from credentials_env>' | jq -r .access_token)

# a hand-written JSON login
TOKEN=$(curl -s -X POST http://localhost:8100/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"...","password":"..."}' | jq -r '.access_token // .token')

curl -s http://localhost:8100/api/v1/users/me -H "Authorization: Bearer $TOKEN" -w '\n%{http_code}\n'
```
Find the real login path from `/openapi.json` rather than guessing: `jq -r '.paths | keys[] | select(test("login|token|auth"))' .pre-launch/openapi.json`. The OpenAPI document also names the scheme and the `tokenUrl` under `.components.securitySchemes`, which tells you the header format before you send anything.

Decode the payload to see what the server trusts (`echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq .`) — a `role`, `is_superuser`, or `scopes` claim that is never re-checked against the database is the SEC-012 finding, demonstrable by comparing the claim against the row rather than by forging anything.

**Session cookie.** Only if `SessionMiddleware` is installed (cookie name `session` unless `session_cookie=` says otherwise) or the app sets one by hand — `grep -rn "set_cookie" app/` gives the list, and that grep is also how you check SEC-025's `httponly`, `secure`, and `samesite` flags, since they are per-call-site here rather than central. When a cookie session exists, CSRF applies and FastAPI supplies nothing for it, so SEC-030's answer is whatever the app wrote (`fastapi-csrf-protect`, a double-submit) or "none".

**Health path.** No convention. From the OpenAPI document: `jq -r '.paths | keys[] | select(test("health|healthz|ping|status|live|ready"))' .pre-launch/openapi.json`. A `/health` that returns `{"status":"ok"}` without touching the database is REL-006's finding rather than a pass. If nothing exists, use the cheapest route for cold-start timing and say which you used.

**Not-found behaviour.** An unmatched path returns `{"detail":"Not Found"}` with status 404 as JSON; `raise HTTPException(404)` produces the same shape with whatever `detail` was given. `405 Method Not Allowed` comes back for a known path with the wrong verb, which is a useful signal when mapping routes without the OpenAPI document. Check the status code and not just the body.

**Test-mode provider keys.** `printenv | grep -iE 'stripe|paypal|paddle'` on the running process first, then `.env`, then the settings object via the project's import path. Stripe `sk_test_` / `pk_test_` / `rk_test_` and a `whsec_` from `stripe listen` rather than the dashboard; PayPal on `api-m.sandbox.paypal.com`; Paddle, Lemon Squeezy, and RevenueCat a sandbox host, flag, or key. Published test card numbers live in the payment provider's own stack file. If the classification is ambiguous, treat the keys as live and stop.

**Local mail catcher.** Nothing ships with FastAPI, so read the mail client. `fastapi-mail` (`ConnectionConfig` with `MAIL_SERVER`, `MAIL_PORT`, and a `SUPPRESS_SEND` flag that swallows sends entirely — that flag on means no mail at all, which is `error: no mail capture`, not a pass), `smtplib` directly, `emails`, or a provider SDK. `MAIL_SERVER=localhost` with port `1025` means a catcher is expected: check `docker-compose.yml` / `compose.yaml` for `axllent/mailpit` (SMTP `1025`, HTTP `8025`, `curl -s http://localhost:8025/api/v1/messages`), `mailhog/mailhog` (API `/api/v2/messages` on `8025`), or `inbucket/inbucket`. A provider key (`RESEND_API_KEY`, `POSTMARK_*`, `SENDGRID_*`) in test mode means the inbox is the provider's own test log. Start the production-mode server with its output redirected (`uvicorn app.main:app --port 8100 > .pre-launch/flows/server.log 2>&1 &`) so a log-line capture is available at all. No reachable catcher is `error: no mail capture`, never a pass.

**Throwaway identity.** Sign up through the app's own registration route with `qa+<unix-ts>@example.com` and the password from the config's `credentials_env`; find that route in the OpenAPI document rather than assuming `/register`. Never create the user with a Python shell or a direct SQL insert, because that skips exactly the flow FLOW-001 is testing. Never reuse the shared test account where a check needs a second identity, and delete what the audit created afterwards — through the app's own account-deletion endpoint if one exists, which doubles as DAT-020's evidence.
