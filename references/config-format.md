# Config format

## Schema

```yaml
version: 1
stacks: [nextjs, supabase, stripe, vercel]
platforms: [web]                  # web | ios | android
local:
  url: http://localhost:3000
  start: npm run dev              # null = user starts it manually
  ready_path: /
  ready_timeout_s: 120
remote:
  url: null                       # staging/preview URL, optional
test_account:
  strategy: create                # create | provided | none
  email_pattern: prelaunch+{ts}@example.com
  email: null                     # used when strategy: provided
  credentials_env: PRELAUNCH_TEST_PASSWORD
features:
  payments: true
  subscriptions: true
  trials: true
  uploads: true
  ai: false
  user_content: true
  email_sending: true
  sms: false
  biometrics: false
  teams: false
  realtime: false
  graphql: false
  health_data: false
  minors_possible: false
  b2b: false
  multilingual: false
tools:
  declined: []
budget_minutes_per_domain: 20
skip:                              # consciously waived checks; reason appears in report
  - id: SEO-005
    reason: internal tool, not indexed
```

## Detection heuristics

Run these in order; each match appends to `stacks`, `platforms`, or sets a feature. Show the result to the user once and accept corrections before writing the file.

| Signal | Sets |
|---|---|
| `next` in package.json deps | stacks: nextjs; platforms: web |
| `nuxt` in deps | stacks: nuxt; platforms: web |
| `@sveltejs/kit` in deps | stacks: sveltekit; platforms: web |
| `@remix-run/*` in deps | stacks: remix; platforms: web |
| `astro` in deps | stacks: astro; platforms: web |
| `express` in deps | stacks: express |
| `fastapi` in requirements/pyproject | stacks: fastapi |
| `django` in requirements/pyproject | stacks: django |
| `rails` in Gemfile | stacks: rails |
| `laravel/framework` in composer.json | stacks: laravel |
| `supabase/` dir or `@supabase/supabase-js` | stacks: supabase |
| `firebase.json` or `firebase`/`firebase-admin` dep | stacks: firebase |
| `prisma/schema.prisma` | stacks: prisma |
| `drizzle.config.*` | stacks: drizzle |
| `stripe` dep | stacks: stripe; features.payments: true |
| `react-native-purchases` or `purchases-*` dep | stacks: revenuecat; features.payments: true |
| `@lemonsqueezy/*` dep | stacks: lemonsqueezy; features.payments: true |
| `app.json` with `expo` key or `expo` dep | stacks: expo; platforms: ios, android |
| `ios/` and `android/` dirs without expo | stacks: react-native; platforms: ios, android |
| `pubspec.yaml` | stacks: flutter; platforms: ios, android |
| `vercel.json` or `.vercel/` | stacks: vercel |
| `netlify.toml` | stacks: netlify |
| `wrangler.toml` | stacks: cloudflare |
| `fly.toml` | stacks: fly |
| `openai`, `@anthropic-ai/sdk`, `anthropic`, `ai` (Vercel AI SDK), `langchain*` dep | features.ai: true |
| grep `subscription` in schema/migrations or Stripe price objects with `recurring` | features.subscriptions: true |
| grep `trial` in schema, Stripe config, or pricing pages | features.trials: true |
| storage bucket config, `multer`, `formidable`, `busboy`, `<input type="file">` | features.uploads: true |
| tables/models named `comment`, `post`, `review`, `message` with a user FK | features.user_content: true |
| `resend`, `nodemailer`, `@sendgrid/mail`, `postmark`, ActionMailer, Django email backend | features.email_sending: true |
| `twilio`, `vonage` dep | features.sms: true |
| tables/models named `organization`, `team`, `workspace`, `membership` | features.teams: true |
| supabase realtime channel usage, `socket.io`, `ws` dep, Pusher/Ably | features.realtime: true |
| `graphql`, `apollo-server`, `graphql-yoga` dep | features.graphql: true |
| `expo-local-authentication`, `react-native-biometrics`, face/voice SDKs | features.biometrics: true |
| i18n libraries (`next-intl`, `i18next`, `vue-i18n`) with more than one locale | features.multilingual: true |

Undetectable flags (`health_data`, `minors_possible`, `b2b`) default to false and are listed explicitly in the confirmation prompt.

## Local environment

- `local.url`: default from framework default port (nextjs/nuxt/remix/astro 3000, sveltekit 5173, django 8000, rails 3000, laravel 8000, fastapi 8000, express: read `PORT` default or ask). Ask if none applies.
- `local.start`: package.json `dev` script → `npm run dev` (or `pnpm`/`yarn`/`bun` per lockfile); `Procfile` web line; `docker-compose.yml` → `docker compose up`; `manage.py` → `python manage.py runserver`; `bin/rails` → `bin/rails s`; `artisan` → `php artisan serve`. Ask if ambiguous. `null` means the user starts it.
- `ready_path` defaults to `/`.

## Skips

`skip` entries need a `reason`. Skipped checks appear in the report under Skipped with that reason so a reviewer sees what was consciously waived.
