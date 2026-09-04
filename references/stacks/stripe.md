# Stripe

## detection signals
`stripe` in `package.json` (Node), `stripe` in `requirements.txt`/`pyproject.toml` (Python), the `stripe` gem in a `Gemfile`, `stripe/stripe-php` in `composer.json`, `stripe-java`, `stripe-go`, or `StripePaymentSheet`/`stripe-android` on mobile. Client-side: `@stripe/stripe-js`, `@stripe/react-stripe-js`, or a `<script src="https://js.stripe.com/v3/">` tag. Env names `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`. A `stripe.toml` or a `stripe listen` line in a dev script means the CLI is part of the workflow.

Establish the **integration shape** early, because it decides PAY-009, PAY-004, and COMP-022 before any of them are individually examined:
- **Checkout** (`checkout.sessions.create` then a redirect to `session.url`) — hosted by Stripe, handles 3DS and card entry itself.
- **Payment Element / Elements** (`paymentIntents.create` server-side, `<PaymentElement>` client-side, `stripe.confirmPayment`) — Stripe's iframe inside your page.
- **Payment Links** — a URL created in the dashboard, no server code at all.
- **A custom card form** posting card fields to your server — the shape COMP-022 fails outright.

Also record whether it is subscriptions (`subscriptions`, `invoices`, `prices` with `recurring`) or one-time payments, since half the PAY domain applies only to the former.

## dev server
Not applicable for this stack. The Stripe CLI is the local tooling, and it is what makes FLOW-004 runnable at all:

```bash
stripe login                                                    # once, opens a browser
stripe listen --forward-to localhost:3000/api/webhooks/stripe   # prints "Ready! Your webhook signing secret is whsec_..."
stripe listen --events checkout.session.completed,invoice.paid --forward-to <url>
stripe trigger checkout.session.completed                       # fires a synthetic event
stripe logs tail                                                # live API request log for this account
```
**The `whsec_` that `stripe listen` prints is a different secret from the one in the dashboard**, generated for that session. Put it in the local env for the duration of the probe, and never let it reach a production environment — a production deployment holding a `stripe listen` secret is exactly the silent failure PAY-001 exists to catch, because every live event then arrives, fails verification, and is discarded with a 400 that only Stripe's dashboard records.

`stripe trigger` sends a **fixture** event, not one derived from your app's objects: a triggered `checkout.session.completed` has no `metadata.user_id`, no `client_reference_id`, and a customer that does not exist in your database. It proves the route is reachable and the signature verifies; it does not prove the grant works. For that, complete a real test-mode checkout (see "runtime probe hints") and watch the forwarded event.

Test clocks simulate the passage of time for trials, renewals, and dunning (FLOW-007, PAY-006):
```bash
stripe test_helpers test_clocks create --frozen-time $(date +%s)
# create the customer with test_clock=<clock id>, subscribe them, then:
stripe test_helpers test_clocks advance --frozen-time <a future unix timestamp> <clock id>
```
The customer must be created **on** the clock; an existing customer cannot be attached to one afterwards. The dashboard has the same feature under test mode. Advancing a clock fires the real renewal and trial-ending events through your webhook, which is the only way to exercise those paths without waiting a month.

## build
Not applicable for this stack.

## env vars
| variable | value shape | where it may live |
|---|---|---|
| `STRIPE_SECRET_KEY` | `sk_test_...` / `sk_live_...` | server only |
| restricted key | `rk_test_...` / `rk_live_...` | server only (PAY-013) |
| `STRIPE_PUBLISHABLE_KEY` | `pk_test_...` / `pk_live_...` | safe in the client by design |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` | server only |
| price identifiers | `price_...`, `prod_...` | safe anywhere, but see PAY-014 |

Read the **prefix**, never the variable name: a variable called `STRIPE_RESTRICTED_KEY` holding an `sk_live_` value is the exact failure PAY-013 catches, and one called `STRIPE_TEST_KEY` holding a live secret is REL-007's failure in the other direction. `sk_` and `rk_` in a client bundle, a mobile `app.json`, or under `NEXT_PUBLIC_`/`VITE_`/`EXPO_PUBLIC_` is SEC-003 and hands a stranger your whole Stripe account.

Test and live objects are entirely separate universes: a `price_` created in test mode does not exist in live mode, and neither do customers, subscriptions, portal configurations, or webhook endpoints. That is why a launch checklist item is not "swap the key" but "swap the key and every id beside it" (REL-007), and it is why `sk_test_` in a production env file is a fail rather than a curiosity. **Key and webhook-secret mismatch is the silent one**: a live secret key with a test webhook secret produces successful charges and zero verified events, with no error anywhere in your own logs.

Pin the API version explicitly rather than inheriting the account default, which someone can change in the dashboard: `new Stripe(key, { apiVersion: '2024-06-20' })` in the SDK, or the `Stripe-Version` header on a raw call. Note the version the code pins and whether it matches what the webhook endpoint is registered to send — a webhook endpoint has its own API version, and an endpoint registered on an older version delivers a differently shaped payload than the SDK's types promise. An unpinned integration is a REL-013 risk: the payload changes under you on Stripe's schedule, not yours.

## routes and handlers
The calls to find, and the checks that start from each:

| call | where it lives | checks |
|---|---|---|
| `checkout.sessions.create` | checkout route | PAY-004 (idempotency key), PAY-014 (price id, not amount), PAY-008 (`automatic_tax`), PAY-015 (`allow_promotion_codes`, `trial_period_days`) |
| `paymentIntents.create` / `confirm` | custom flows | PAY-009 (`requires_action`), PAY-004 |
| `subscriptions.create` / `update` | plan changes | PAY-007 (proration), PAY-002 |
| `billingPortal.sessions.create` | billing screen | PAY-012 |
| `checkout.sessions.retrieve` | success route | PAY-018 (`payment_status`) |
| `customers.create` / `search` | signup or first checkout | PAY-002 (the join key), PAY-015 (one customer per person) |
| `refunds.create` | admin tooling | PAY-011 |
| `webhooks.constructEvent` | webhook route | SEC-051, PAY-003 |

```bash
grep -rn 'checkout\.sessions\|paymentIntents\|billingPortal\|subscriptions\.\|webhooks\.constructEvent\|stripe\.customers\|refunds\.create' --include='*.ts' --include='*.tsx' --include='*.js' --include='*.py' --include='*.rb' --include='*.php' .
```

The success and cancel pages are the `success_url` and `cancel_url` passed into the session — read those values to find the routes PAY-018 audits, and note whether `success_url` carries `{CHECKOUT_SESSION_ID}` (Stripe substitutes it), because that parameter is what a bad success handler trusts.

## auth
Not applicable for this stack — Stripe has no notion of your users. What matters is the **join between a Stripe customer and an app user**, which every entitlement write depends on:

- The durable form is a `stripe_customer_id` column on the user row, written once when the customer is created, with a unique constraint on it (DAT-014). The webhook then looks the user up by the event's `customer` field.
- `metadata.user_id` set on the customer, the subscription, or the checkout session works too, and survives into most events; read it from the object rather than from the session where the event is a subscription or invoice event, since not every event type carries the checkout session's metadata.
- `client_reference_id` on a checkout session is set by the client that created the session. It arrives on `checkout.session.completed` and is fine as a join key **when the server set it from the session identity**; a handler that trusts a `client_reference_id` supplied in the request body grants entitlement to whichever user id the caller typed. Check where it comes from.
- **Email is not a join key.** It changes, it is not unique in Stripe, and a customer can update it in the portal. PAY-002 names this specifically.

One person should have exactly one Stripe customer. A codebase that calls `customers.create` on every checkout accumulates duplicate customers, which breaks the portal (which customer's subscriptions?), breaks trial-abuse controls (PAY-015), and makes the webhook's lookup ambiguous.

## webhook handlers
The route that calls `stripe.webhooks.constructEvent`. It must read the **raw request body** — see the framework's stack file for how (App Router `await req.text()`, Express `express.raw({type:'application/json'})` mounted *before* the JSON parser, Rails `request.raw_post`, Django `request.body`, FastAPI `await request.body()`). A handler that calls `req.json()` first cannot verify (SEC-051), and the version of that bug that returns 200 anyway is worse than the version that crashes.

**PAY-001 — the live endpoint.** This is dashboard state, not repo state, and it is the piece that gets forgotten. In live mode, an endpoint must exist at the production URL, subscribed to the event set below, with its signing secret in the production environment. Two failure shapes, both silent at deploy time: no live endpoint at all (charges succeed, no event ever arrives, nobody is granted anything), or an endpoint whose secret does not match what production holds (every event arrives, fails verification, is discarded with a 400 that only Stripe records). Confirm it in the dashboard under Developers → Webhooks with the mode toggle on **live**, or with `stripe webhook_endpoints list` against a live key — and confirm the subscribed event list, not just the endpoint's existence.

**PAY-002 — the event set** a subscription product needs:

| event | what it means | direction |
|---|---|---|
| `checkout.session.completed` | first purchase completed | grant |
| `invoice.paid` **or** `invoice.payment_succeeded` | renewal succeeded | extend |
| `invoice.payment_failed` | renewal declined | mark `past_due`, start dunning |
| `customer.subscription.updated` | plan, status, or trial changed | reconcile |
| `customer.subscription.deleted` | subscription ended | revoke |
| `charge.refunded` | money returned | revoke |
| `charge.dispute.created` | chargeback opened | revoke, and PAY-011 |

`invoice.paid` and `invoice.payment_succeeded` fire on the same successful invoice; handling **either** satisfies the renewal case, and PAY-002 says explicitly not to report the other as absent. The four that constitute the revoke path — `subscription.updated`, `subscription.deleted`, `invoice.payment_failed`, `charge.refunded` — are the ones whose absence is the defect. Worth knowing about the two easy misreadings: `customer.subscription.deleted` fires when the subscription actually ends, which for a `cancel_at_period_end` cancellation is at the end of the paid period and not at the moment the user clicked cancel (FLOW-005 depends on this distinction); and `customer.subscription.updated` fires on plan changes, trial ends, and status transitions alike, so treating it as a cancel signal revokes paying customers. `customer.subscription.trial_will_end` (three days ahead, by default) is what FLOW-007's reminder hangs off. For asynchronous payment methods, `checkout.session.async_payment_succeeded` / `_failed` are the pair that completes later.

Delivery behaviour: Stripe retries failed deliveries with backoff over a period of days in live mode, and disables an endpoint that keeps failing, emailing the account — that is PAY-016's alert, and it is on by default, but confirm the notification address is one somebody reads. Return 2xx quickly and do the work durably; a handler doing thirty seconds of work before acknowledging will start collecting retries, and retries plus non-idempotent writes is PAY-003.

## webhook verification snippet
```ts
const event = stripe.webhooks.constructEvent(
  rawBody,                              // the exact bytes, not a re-serialized object
  req.headers['stripe-signature'],
  process.env.STRIPE_WEBHOOK_SECRET,
)
```
The `Stripe-Signature` header is `t=<unix timestamp>,v1=<hmac>`, and `constructEvent` checks the HMAC **and** the timestamp against a **default tolerance of 300 seconds**, throwing outside it. Leaving that default alone is the PAY-003 pass; a `tolerance` argument raised to a large value, or a hand-rolled verification that parses `t=` and never compares it to the clock, is the fail. Do not write the HMAC by hand — if someone has, SEC-052 applies to the comparison.

On an edge or Deno runtime there is no synchronous crypto, so the sync call throws: use `await stripe.webhooks.constructEventAsync(body, sig, secret, undefined, cryptoProvider)`. Then dedup:
```ts
// insert-first, not check-then-act (PAY-003, PERF-017)
try { await db.processedEvent.create({ data: { id: event.id } }) }
catch (e) { if (isUniqueViolation(e)) return ok(); throw e }
```
For PAY-003's third property, order tolerance: events are not guaranteed to arrive in the order they occurred, so a `customer.subscription.updated` carrying `active` that lands after the `deleted` for the same subscription will resurrect a cancelled plan if the payload is written blind. Either compare `event.created` (or the subscription's `current_period_start`) against the row's last-updated marker and ignore the older one, or — better on most stacks — re-fetch the subscription with `subscriptions.retrieve(id)` inside the handler and write the current truth, which sidesteps ordering entirely.

## data access
Not applicable for this stack — the app's database is the framework's and the data stack's business. What belongs here is **where entitlement state must live**: in your own database, written only by the webhook handler or by a server-side session retrieval (PAY-018), and read by the app to decide what a user may do. Two properties PAY-002 and PAY-006 need from that schema: the join key must be the stored `stripe_customer_id` (or `metadata.user_id`), unique-constrained; and the status column must be able to express `past_due` as a state distinct from both `active` and `cancelled`, or the grace period FLOW-006 tests has nowhere to live.

Do not treat Stripe as the source of truth at read time — calling `subscriptions.retrieve` on every page load makes Stripe's availability your availability and its rate limits your rate limits. Mirror the state, and reconcile.

Money on the wire is **integer minor units** (`amount_total: 1999` is $19.99), with zero-decimal exceptions such as JPY where the integer is the whole unit. Storing it the same way is PAY-005's clean pass, and it means no conversion at the boundary.

## file uploads
Not applicable for this stack.

## background jobs
Stripe runs the recurring machinery itself: billing cycles, invoice generation, **Smart Retries** for failed payments, and the dunning emails configured under the dashboard's revenue-recovery settings (PAY-006). None of that is in your repo, so PAY-006 is answered by reading the dashboard: what the retry schedule is, what happens at the end of it (cancel the subscription, mark unpaid, or leave it), and whether customer emails for failed payments are on. Your side is handling `invoice.payment_failed` for in-app messaging and `customer.subscription.deleted`/`updated` for the eventual revoke.

A reconciliation job is worth looking for and worth recommending where absent: a periodic sweep that lists active subscriptions from Stripe and compares them to the entitlement table catches every event that was dropped, mis-ordered, or discarded during an outage. It is the only thing that makes a webhook-only architecture self-healing.

Stripe's own emails (receipts, failed-payment notices, upcoming-invoice notices) are dashboard settings, and whether receipts are on is PAY-010.

## error handling and logging
Log `event.id`, `event.type`, and the customer id — never the whole payload, which carries billing addresses and card metadata (COMP-016 for what is retained, COMP-022 for what must never be there at all: a PAN or CVC in a log is a scope disaster).

Errors from the SDK carry a `type` worth branching on: `StripeCardError` (the customer's card was declined — surface `err.message`, which is written to be shown to a user), `StripeInvalidRequestError` (your bug), `StripeAPIError` and `StripeConnectionError` (retry-worthy), `StripeRateLimitError` (back off), `StripeIdempotencyKeyError` (the same key was reused with different parameters). Returning a raw `StripeInvalidRequestError` message to the client leaks your price ids and parameter names (SEC-009); card errors are the exception and are meant to be shown.

Every request has a `request_id` (`req_...`) in the error and in the response headers; log it, because it is the only handle Stripe support can act on. `stripe logs tail` shows the same requests live during a probe.

## security headers
Not applicable for this stack. One adjacent rule that belongs to COMP-022: **Stripe.js must be loaded from `https://js.stripe.com`, never bundled or self-hosted** — self-hosting it takes you out of the PCI scope reduction that the hosted script provides. If the app has a CSP, `js.stripe.com` needs to be in `script-src` and `api.stripe.com` in `connect-src`, with `frame-src` allowing `js.stripe.com` and `hooks.stripe.com` for 3DS challenge frames; a CSP that blocks those breaks payments in a way that only shows up on the live domain.

## known traps
- Granting access on the success URL, or from a `?paid=true`-style parameter: PAY-018. The redirect target is an ordinary public route — it can be typed, bookmarked, edited, and shared — so anything that writes entitlement there is writing it on a query parameter.
- A success handler that retrieves the session but never reads `payment_status`, or reads it and writes anyway: PAY-018. And the opposite error, checking only for `"paid"` — `"no_payment_required"` is the second legitimate value, so a check on `"paid"` alone silently refuses every trial and every fully-discounted purchase.
- Handling only `checkout.session.completed`: PAY-002. Everything that takes money back out arrives later.
- Revoking on the wrong event: `customer.subscription.deleted` is the end of access; the user's click on "cancel" produces `customer.subscription.updated` with `cancel_at_period_end: true`, and revoking there cuts off a customer who has paid through the period (FLOW-005).
- `req.json()` (or a framework body parser) before `constructEvent`: SEC-051. Verification cannot work on re-serialized bytes.
- A raised `tolerance` argument, or a hand-rolled signature check with no timestamp comparison: PAY-003. And SEC-052 if that hand-rolled check uses `===`.
- No `event.id` dedup, with an incremental write in the handler (`credits += n`, `period_end += 30 days`): retries are a promise, not a risk, and one increment makes the whole handler non-idempotent. PAY-003.
- No idempotency key on `checkout.sessions.create` / `paymentIntents.create`: PAY-004. The key goes in the **request options**, not the parameters — `stripe.checkout.sessions.create(params, { idempotencyKey })` — which is why it is omitted so often: the call looks complete without it. A `crypto.randomUUID()` generated inside the handler is not a key, because a retry generates a new one; derive it from user id plus price id plus a client-supplied request id. Stripe remembers keys for a limited window (on the order of a day — check the current docs), so it protects against double-submit, not against next week.
- An amount taken from the request body and passed as `unit_amount`, or a client-supplied `price` id used without an allowlist: PAY-014. Reference a server-chosen price id.
- Card fields in your own markup, or a server-side call constructing a card object: COMP-022, and it changes your PCI obligations permanently.
- A custom Payment Intents flow that ignores the `requires_action` status: PAY-009 — the payment silently never completes for every European customer. Checkout and the Payment Element handle the challenge themselves, and where one of those is in use the correct finding is that SCA is the provider's surface.
- Customer portal features are **off until a configuration is saved in the dashboard**, and the test-mode and live-mode configurations are separate: PAY-012. A portal session that creates fine and shows a page with no cancel button is this.
- `automatic_tax: { enabled: true }` absent, or present with no customer address collected (`customer_update: { address: 'auto' }`, billing address collection, `tax_id_collection`): PAY-008 — automatic tax cannot compute anything without a location. Also check each price's `tax_behavior` (`inclusive` vs `exclusive`), which decides whether the pricing page's number is what the customer pays.
- Promotion codes with no restriction: PAY-015. The `customer` field on a promotion code pins it to one customer; `max_redemptions` caps total use; `restrictions.first_time_transaction` limits it to customers with no prior successful payment. Note that `trial_settings.end_behavior.missing_payment_method` is **not** a once-per-customer trial guarantee and must not be reported as one.
- A full `sk_` key where a restricted `rk_` would do, or one key shared by the web app, the background worker, and a scripts directory: PAY-013.
- A `whsec_` from someone's `stripe listen` session sitting in the production environment: PAY-001, and it fails silently.
- Test-mode price ids, portal configurations, or webhook endpoints referenced by a production deployment: REL-007. Test and live are separate object universes.
- Calling `customers.create` on every checkout instead of reusing one customer per user: breaks the portal, PAY-015's trial control, and the webhook's lookup.
- An unpinned `apiVersion`, or a webhook endpoint registered on a different API version than the SDK expects: REL-013 — the payload shape changes on Stripe's schedule.
- Trials and renewals left untested because a month is a month: FLOW-007 — test clocks simulate the passage of time and fire the real events through your webhook. See "dev server".
- Webhook delivery-failure alerting assumed absent: PAY-016 — Stripe retries, then disables a persistently failing endpoint and emails the account. It is on by default, so the finding is usually that the notification address is nobody's inbox. See "webhook handlers".
- Dunning treated as something to build: PAY-006 — Smart Retries and the failed-payment customer emails are dashboard settings, so the retry schedule, the end-of-schedule behaviour, and whether those emails are on are read there rather than from the repo. Your side is `invoice.payment_failed`. See "background jobs".

## runtime probe hints
**Confirm test mode before anything.** Read `STRIPE_SECRET_KEY` out of the running process (`printenv | grep -i stripe`) rather than out of a file, since the platform's value wins, and check the prefix: `sk_test_` / `rk_test_` / `pk_test_` is test mode, `sk_live_` is not. Write the determination down before the first request. If the classification is ambiguous, treat the keys as live and stop — every probe below spends real money against a live key.

**Test cards** (test mode only; any future expiry, any 3-digit CVC, any postal code):

| number | behaviour | what it exercises |
|---|---|---|
| `4242 4242 4242 4242` | succeeds | FLOW-004's happy path |
| `4000 0000 0000 0002` | generic decline | FLOW-006 |
| `4000 0000 0000 9995` | decline, insufficient funds | FLOW-006, dunning |
| `4000 0025 0000 3155` | requires 3DS authentication | PAY-009 |
| `4000 0000 0000 0341` | attaches successfully, then the charge fails | the "saved card, failed renewal" path |
| `4000 0000 0000 0259` | succeeds, then is disputed as fraudulent | `charge.dispute.created`, PAY-011 |

Stripe publishes a much larger set by brand, country, and decline code — check the current testing docs for anything not listed here rather than guessing a number.

**Webhook delivery locally** (FLOW-004 cannot pass without it):
```bash
stripe listen --forward-to localhost:3000/api/webhooks/stripe | tee .pre-launch/flows/webhook.log &
# use the whsec_ it prints as STRIPE_WEBHOOK_SECRET for the app process, then run the checkout
```
Watch that log for the event and then assert the **grant** — query the entitlement row the app itself reads and load a gated page — rather than asserting the redirect. `stripe trigger <event>` is for reachability and signature verification only; see "dev server" for why its payload cannot exercise the grant.

**SEC-051's negative probe** is safe and requires no keys: POST a plausible payload to the webhook path with a wrong `Stripe-Signature` header, then with none at all. Expect 400 both times.
```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:3000/api/webhooks/stripe \
  -H 'content-type: application/json' -H 'stripe-signature: t=1,v1=deadbeef' -d '{"type":"checkout.session.completed"}'
```

**Reading the account's state** (all read-only, all against the test key):
```bash
stripe checkout sessions list --limit 5          # PAY-004: did a double-submit create two?
stripe products list --limit 20
stripe prices list --limit 20                    # PAY-014: the real amounts behind the ids
stripe webhook_endpoints list                    # PAY-001, per mode — check with the LIVE key too
stripe subscriptions list --limit 5
```
`stripe webhook_endpoints list` run with a live key is the closest thing to a repo-side answer for PAY-001; it still does not tell you the signing secret, so the secret half stays an attest question.

**Time travel** for trials and renewals is the test clock under "dev server" (FLOW-007, PAY-006). Advancing a clock fires real events through the forwarder, so keep it running.

**Never** run a probe with a live key, never complete a real payment, and never replay a captured production event. Delete the test-mode objects the audit created where the CLI supports it, and note that test-mode data can also be wiped wholesale from the dashboard.
