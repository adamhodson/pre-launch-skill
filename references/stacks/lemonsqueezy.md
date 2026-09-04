# Lemon Squeezy

## detection signals
`@lemonsqueezy/lemonsqueezy.js` in dependencies, or raw `fetch` calls to `https://api.lemonsqueezy.com/v1/`. Client-side: a `<script src="https://assets.lemonsqueezy.com/lemon.js">` tag, a link with `class="lemonsqueezy-button"`, or a `LemonSqueezy.Url.Open(...)` call for the overlay checkout. Env names `LEMONSQUEEZY_API_KEY`, `LEMON_SQUEEZY_API_KEY`, `LEMONSQUEEZY_WEBHOOK_SECRET`, `LEMONSQUEEZY_STORE_ID`, `LEMONSQUEEZY_VARIANT_ID`. Checkout URLs have the shape `https://<store>.lemonsqueezy.com/checkout/buy/<variant uuid>` or `/buy/<uuid>`.

**Lemon Squeezy is a merchant of record.** It is the legal seller: it collects and remits VAT and sales tax, issues the invoice, and handles the customer's payment relationship. That single fact resolves PAY-008 and PAY-010 by construction and changes the shape of PAY-011 and PAY-012 — see those entries below rather than auditing them as if the app were the seller.

The object model to keep straight while reading code: **store → product → variant → price**, and a **variant id** is what a checkout actually references. Orders are one-time purchases; subscriptions wrap an order and have their own lifecycle. `subscription_item` carries usage-based quantity where that is in play.

## dev server
Not applicable for this stack. There is **no CLI and no `stripe listen` equivalent**, which is the main practical difference when running FLOW-004 locally: to receive webhooks against a local server you need a public tunnel (`ngrok http 3000`, `cloudflared tunnel --url http://localhost:3000`) and a **separate webhook registered in the dashboard** pointing at the tunnel URL, with its own signing secret. Register it as a second webhook rather than repointing the production one, and delete it afterwards.

Test mode is a toggle in the dashboard rather than a separate set of credentials in the usual sense. Objects and webhook payloads created in test mode carry a `test_mode: true` flag, and that flag — not a key prefix — is the reliable tell (REL-007). Check the current dashboard for whether this account's API key is scoped to a mode or works across both, since that has changed; either way, read `test_mode` on the object.

The dashboard's webhook page lists recent deliveries with their payloads and response codes, and can resend one. That resend is the closest thing to `stripe trigger` and, unlike a synthetic fixture, it replays a real event with real ids — which makes it useful for PAY-003's dedup probe as well as for reachability.

## build
Not applicable for this stack.

## env vars
| variable | shape | where |
|---|---|---|
| `LEMONSQUEEZY_API_KEY` | a long opaque token, sent as `Authorization: Bearer` | **server only** |
| `LEMONSQUEEZY_WEBHOOK_SECRET` | the signing secret you set per webhook in the dashboard | server only |
| `LEMONSQUEEZY_STORE_ID` | a number | safe |
| variant ids | numbers or uuids | safe, but see PAY-014 |

**The API key is a full account credential** — it can create checkouts, read customers and orders, cancel subscriptions, and issue refunds. There is no publishable counterpart and no restricted-key mechanism comparable to Stripe's `rk_`, so PAY-013's answer on this stack is that scoped keys are not available; say that rather than reporting it as a missing control, and check instead that the one key is not shared with anything that does not need it. The key under `NEXT_PUBLIC_`, `VITE_`, `PUBLIC_`, or `EXPO_PUBLIC_`, or in a client bundle, is an immediate DAT-004 and SEC-003 fail.

The overlay checkout script (`lemon.js`) and a checkout URL are the only things that belong in the browser. A checkout can be opened from a plain link with no key at all, which is why a project can have a working paid flow with no server-side Lemon Squeezy code whatsoever — worth noting, because it changes what PAY-004 and PAY-014 can even examine (PAY-004 has an explicit exemption for a provider-hosted link with no server-side creation route).

For REL-007 and DAT-017, the discriminators are `test_mode` on the objects and the `LEMONSQUEEZY_STORE_ID` — a preview environment sharing the production store id sells real products from a branch.

## routes and handlers
The calls to find:

```ts
import { lemonSqueezySetup, createCheckout, getSubscription, updateSubscription,
         cancelSubscription, listProducts, getCustomer } from '@lemonsqueezy/lemonsqueezy.js'
lemonSqueezySetup({ apiKey: process.env.LEMONSQUEEZY_API_KEY! })

const { data } = await createCheckout(storeId, variantId, {
  checkoutData: {
    email: user.email,
    custom: { user_id: user.id },        // comes back as meta.custom_data on every webhook
  },
  productOptions: { redirectUrl: `${site}/welcome` },
  testMode: true,
})
// data.data.attributes.url is the checkout URL to redirect to
```
Or the raw API at `https://api.lemonsqueezy.com/v1/checkouts`, `/subscriptions/<id>`, `/orders`, `/customers`, `/license-keys`, with `Authorization: Bearer <key>`, `Accept: application/vnd.api+json`, `Content-Type: application/vnd.api+json`. **The API is JSON:API**, so responses nest under `data.attributes` and relationships under `data.relationships` — a handler reading `response.id` instead of `response.data.id` is a common shape bug.

```bash
grep -rn 'lemonsqueezy\|lemonSqueezy\|createCheckout\|lemon\.js\|LEMONSQUEEZY_' --include='*.ts' --include='*.tsx' --include='*.js' .
```

`checkoutData.custom` is the join key mechanism and it must be set **at checkout creation**: whatever object you put there comes back as `meta.custom_data` on every webhook for that order and its subscription. A checkout opened from a plain dashboard link carries no custom data, so the webhook can only join on email — which PAY-002 names as unstable. If the project uses plain links, that is the finding, and the fix is server-created checkouts with `custom.user_id`.

## auth
Not applicable for this stack — Lemon Squeezy has no notion of your sessions. The join between a Lemon Squeezy customer and an app user is the thing to audit, in this order of preference: `meta.custom_data.user_id` set at checkout creation (durable, opaque, correct); the `customer_id` stored on the user row with a unique constraint (DAT-014); email (unstable — the customer can change it, and PAY-002 calls it out).

Note that `custom_data` is set by whoever created the checkout. If the checkout is created from a client-supplied `user_id` rather than from the server's session, a caller can buy a subscription onto someone else's account or, more usefully to them, onto their own account at a price they chose — check where the value comes from, exactly as with Stripe's `client_reference_id`.

## webhook handlers
One route in your app receiving `POST` from Lemon Squeezy. Headers: `X-Signature` (the HMAC) and `X-Event-Name` (the event, also present as `meta.event_name` in the body). The body's shape is `{ meta: { event_name, custom_data, test_mode, ... }, data: { type, id, attributes, relationships } }` where `data` is the order or subscription object.

**Signature verification requires the raw body** (SEC-051) — the HMAC is over the exact bytes, and a re-serialized parsed object will not match. See the framework's stack file for how to get raw bytes on this stack.

Register the production webhook in the dashboard for the production store, subscribed to the events below, with the signing secret in the production environment (PAY-001's equivalent — the same two silent failure shapes apply: no endpoint, or a mismatched secret producing 100% verification failures visible only in the dashboard's delivery log). Lemon Squeezy retries failed deliveries and shows failures in that log; check the current docs for the retry count and schedule and whether failure notifications reach someone (PAY-016).

**PAY-002 — the event set:**

| event | meaning |
|---|---|
| `order_created` | a purchase completed — grant, and the one-time-product path in full |
| `order_refunded` | money returned — **revoke** |
| `subscription_created` | subscription started (including a trial) — grant |
| `subscription_updated` | status, plan, or renewal date changed — reconcile |
| `subscription_cancelled` | auto-renew off; access continues to `ends_at` — do **not** revoke yet |
| `subscription_resumed` | a cancelled subscription was reinstated |
| `subscription_expired` | access has actually ended — **revoke** |
| `subscription_paused` / `subscription_unpaused` | pause window start and end |
| `subscription_payment_success` | a renewal invoice was paid — extend |
| `subscription_payment_failed` | a renewal failed — `past_due`, dunning (PAY-006) |
| `subscription_payment_recovered` | a previously failed payment succeeded — clear `past_due` |
| `subscription_payment_refunded` | a specific renewal was refunded |
| `subscription_plan_changed` | variant changed |
| `license_key_created` / `_updated` | only for license-key products |

The `cancelled` / `expired` distinction is the same trap as everywhere: `subscription_cancelled` means the customer turned off renewal and has paid through `attributes.ends_at`; `subscription_expired` is where access stops. Revoking on `cancelled` cuts off a paying customer, which FLOW-005 tests directly. The subscription's `attributes.status` (`on_trial`, `active`, `paused`, `past_due`, `unpaid`, `cancelled`, `expired`) is the field to mirror, and it gives PAY-002 the distinct `past_due` state it asks for without inventing one.

**Dedup and replay** (PAY-003) need care here. The signature carries **no timestamp**, so there is no provider-enforced replay window the way Stripe's 300-second tolerance is one — a captured delivery replays forever, and your dedup is the whole defence. The classic payload's `meta` block carries a webhook identifier rather than an obvious per-delivery event id; check what this account's deliveries actually contain (the dashboard's delivery log shows a full payload) and key the dedup table on a per-delivery id if one is present, otherwise on the combination of event name, the object's `data.id`, and the object's `updated_at`. Whichever key you use, insert-first with a unique constraint rather than select-then-work. Re-fetching the subscription from the API inside the handler and writing its current state sidesteps ordering entirely and is the better fix.

## webhook verification snippet
```ts
import { createHmac, timingSafeEqual } from 'node:crypto'

export async function POST(req: Request) {
  const raw = await req.text()                       // raw bytes, before any JSON parsing
  const secret = process.env.LEMONSQUEEZY_WEBHOOK_SECRET!
  const digest = Buffer.from(createHmac('sha256', secret).update(raw).digest('hex'), 'utf8')
  const given = Buffer.from(req.headers.get('x-signature') ?? '', 'utf8')

  // length guard first — timingSafeEqual throws on unequal lengths, which is itself an oracle (SEC-052)
  if (given.length !== digest.length || !timingSafeEqual(digest, given)) {
    return new Response('invalid signature', { status: 401 })
  }

  const payload = JSON.parse(raw)
  const eventName = payload.meta.event_name          // or the X-Event-Name header
  const userId = payload.meta.custom_data?.user_id
  // dedup before the work (PAY-003), then handle eventName
  return new Response('ok')
}
```
The digest is hex-encoded SHA-256. Comparing with `===` is SEC-052; comparing without the length guard turns `timingSafeEqual`'s throw into a length oracle and, worse, usually into a 500 that the provider retries.

## data access
Not applicable for this stack. Entitlement state lives in your database, written only by the webhook (PAY-018 — there is no server-side session-retrieval fast path on this provider comparable to Stripe's `checkout.sessions.retrieve`, so the webhook is the grant path and the redirect target must not write anything). Mirror: the `user_id` from `custom_data`, the Lemon Squeezy `customer_id` and `subscription_id` (both unique-constrained, DAT-014), the `status`, the `variant_id`, `renews_at` / `ends_at`, and `test_mode` so a test-mode order can never be mistaken for a real one.

**Amounts are in minor units.** `total`, `subtotal`, `tax`, `discount_total`, and the subscription's price fields are integers in cents, alongside `*_formatted` strings meant for display only. Store the integer with the currency code (PAY-005); never parse the formatted string.

Because Lemon Squeezy is the merchant of record, the amount your business receives is not the amount the customer paid — `total` includes tax that is remitted by Lemon Squeezy, and their fee comes off the rest. Anything computing revenue from `total` is overstating it; the payout figures are the ones that reconcile.

## file uploads
Not applicable for this stack, with one exception worth naming: Lemon Squeezy hosts digital-product files and license keys, so a product delivering a downloadable file may have no upload path in your app at all. If the app also serves the file itself, SEC-050's signed-expiring-URL rule applies to that path and the entitlement check in front of it is SEC-011.

## background jobs
Not applicable for this stack — renewals, retries, and dunning emails are Lemon Squeezy's. PAY-006's answer therefore comes from the dashboard: what the retry schedule is, what emails go to the customer on a failed payment, and how long a subscription sits in `past_due` before it expires. Your side is handling `subscription_payment_failed` (mark `past_due`, message the user in-app) and `subscription_payment_recovered` (clear it), which is a pair people frequently implement only half of — the half that revokes.

A reconciliation sweep is worth having and worth recommending where absent: list subscriptions from the API periodically and repair rows the webhook dropped. The dashboard's delivery log will tell you whether anything ever has.

## error handling and logging
Log `meta.event_name`, the object's `data.id`, and `test_mode`; do not log the whole payload, which carries the customer's name, email, and billing country (COMP-016), nor the `X-Signature` header.

API errors come back in JSON:API's `errors` array with `status`, `title`, and `detail`. A 422 usually means a malformed JSON:API body (the `type`/`attributes`/`relationships` nesting), and a 404 on a checkout creation usually means the store or variant id belongs to the other mode. Surfacing `detail` to the client leaks store and variant ids (SEC-009) — map it.

## security headers
Not applicable for this stack. If the app uses the overlay checkout, a CSP needs `assets.lemonsqueezy.com` in `script-src` and the checkout domain in `frame-src`; a CSP that omits them breaks the overlay only on the live domain, which is the classic launch-day payment failure.

## known traps
- Granting access on the redirect target (`redirectUrl`) or from a query parameter: PAY-018. There is no session-retrieval verification path here, so the webhook is the only legitimate grant.
- Revoking on `subscription_cancelled`: the customer has paid through `ends_at`. `subscription_expired` is the revoke event. PAY-002, FLOW-005.
- Handling only `order_created` and `subscription_created`: PAY-002. `order_refunded`, `subscription_expired`, and `subscription_payment_failed` are the paths that take access back.
- Verifying the signature against a re-serialized body rather than the raw bytes: SEC-051 — the HMAC will never match, and the version of this bug that returns 200 anyway is worse than the one that 500s.
- `===` on the signature, or `timingSafeEqual` with no length guard: SEC-052.
- No dedup, or a select-then-work-then-insert: PAY-003, PERF-017. The signature carries no timestamp, so there is **no replay window** on this provider and dedup is the only defence against a replayed capture.
- A checkout opened as a plain dashboard link with no `custom_data`, leaving the webhook to join on email: PAY-002 calls email an unstable key. Create checkouts server-side with `custom.user_id`.
- `custom_data.user_id` taken from the request body rather than from the server session: the caller chooses whose account gets the subscription.
- The API key in a client bundle or under a public env prefix: DAT-004, SEC-003. There is no publishable counterpart, so anything in the browser that looks like a Lemon Squeezy credential is the full one.
- Test-mode orders written into the same entitlement rows as real ones with no `test_mode` flag stored: REL-007, and it makes the launch-day "is anyone actually paying" question unanswerable.
- Parsing `total_formatted` instead of `total`: PAY-005. The integers are minor units; the formatted strings are for display.
- Treating `total` as revenue: Lemon Squeezy remits the tax inside it and takes a fee. Not a launch blocker, but it is the number people put in a spreadsheet.
- Auditing tax as if you were the seller: you are not. As merchant of record, Lemon Squeezy handles registration, collection, and remittance, and issues the invoice — PAY-008 and PAY-010 pass with that reason stated, and the app's remaining job is to display the right price and to link the invoice.
- Expecting to build a cancel-and-update-card screen: PAY-012 is satisfied by the signed customer-portal URL on the subscription object (`attributes.urls.customer_portal`, with a separate `update_payment_method` URL). Those URLs are **signed and expiring** — check the current docs for the window, and generate one on demand from the server rather than storing it, since a stored one will be dead when the user clicks it. Failing to surface any link at all is the finding; so is emailing a stored URL.
- Refunds and disputes: PAY-011 runs through Lemon Squeezy's dashboard because they are the seller of record, and a chargeback is theirs to contest. Confirm someone owns the queue and that `order_refunded` revokes; the app cannot issue the refund itself except through the API.
- A single API key shared by the web app, workers, and scripts, with no scoping available: PAY-013 has no restricted-key mechanism here — record the absence as a provider limitation and check the blast radius instead.
- Preview environments pointed at the production store id: DAT-017, and here it means a branch can sell.

## runtime probe hints
**Test-mode detection.** There is no key prefix (see "env vars"). The tell is the `test_mode` boolean on objects and on `meta.test_mode` in webhook payloads, plus the dashboard's mode toggle. Confirm it by reading one object through the API before doing anything that could create a real order:
```bash
curl -s 'https://api.lemonsqueezy.com/v1/stores' \
  -H "Authorization: Bearer $LEMONSQUEEZY_API_KEY" -H 'Accept: application/vnd.api+json' | jq '.data[].attributes.name'
curl -s 'https://api.lemonsqueezy.com/v1/subscriptions?page[size]=5' \
  -H "Authorization: Bearer $LEMONSQUEEZY_API_KEY" -H 'Accept: application/vnd.api+json' \
  | jq '.data[] | {id, status: .attributes.status, test: .attributes.test_mode}'
```
If you cannot establish that the environment is in test mode, stop and record `error: could not confirm test mode`.

**The signature probe** (SEC-051) is safe and needs no account:
```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:3000/api/webhooks/lemonsqueezy \
  -H 'content-type: application/json' -H 'x-signature: deadbeef' -H 'x-event-name: order_created' \
  -d '{"meta":{"event_name":"order_created","test_mode":true},"data":{"id":"1","attributes":{}}}'
# and again with no x-signature header at all
```
Expect 400 or 401 both times. To test the positive path and the dedup at once, compute a valid signature over a fixed body and send it twice:
```bash
BODY='{"meta":{"event_name":"order_created","test_mode":true,"custom_data":{"user_id":"<test user>"}},"data":{"id":"probe-1","attributes":{}}}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$LEMONSQUEEZY_WEBHOOK_SECRET" | awk '{print $2}')
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:3000/api/webhooks/lemonsqueezy \
  -H 'content-type: application/json' -H "x-signature: $SIG" -H 'x-event-name: order_created' -d "$BODY"
```
Send it twice and confirm the entitlement was written once (PAY-003). Use a **test** user and a synthetic id; never replay a real captured payload, and clean the rows up afterwards.

**Webhook delivery for FLOW-004** needs a tunnel and a second dashboard-registered webhook (see "dev server"), because there is no CLI forwarder. Where no tunnel is available, record `error: webhook delivery not reachable locally`, quote the exact steps a human should take, and complete only the checkout half.

**A real test-mode purchase.** With the dashboard in test mode, open a checkout and pay with the test card the provider's current docs publish (`4242 4242 4242 4242` is the standard Stripe-backed test number and is what Lemon Squeezy's test mode has accepted — confirm against their current testing page rather than assuming, since the accepted set can change). Then assert the **grant**, not the redirect: watch the tunnel log for `order_created` / `subscription_created`, query the entitlement row the app itself reads, and load a page gated on it.

**Never** run any of this with the dashboard in live mode, never issue a refund or cancel through the API as a probe, and delete the test-mode orders and subscriptions afterwards where the dashboard allows it.
