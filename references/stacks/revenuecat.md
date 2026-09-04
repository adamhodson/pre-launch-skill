# RevenueCat

## detection signals
`react-native-purchases` (and `react-native-purchases-ui` for paywalls), `purchases_flutter`, `purchases-ios` / `RevenueCat` in a `Podfile` or Swift package list, `com.revenuecat.purchases:purchases` in a Gradle file, `cordova-plugin-purchases`, the Unity SDK, or `@revenuecat/purchases-js` for RevenueCat's web billing. Env or constant names `REVENUECAT_API_KEY`, `RC_API_KEY`, `REVENUECAT_PUBLIC_KEY`, `REVENUECAT_SECRET_KEY`, `REVENUECAT_WEBHOOK_AUTH`. A `Purchases.configure(` call is the definitive one.

RevenueCat sits **in front of** the app stores: the actual money is Apple's and Google's, and RevenueCat is the receipt validator, entitlement store, and event source on top. That framing decides several checks by construction — the stores are the merchant of record, so tax (PAY-008) and receipts (PAY-010) are theirs; and it means the store consoles, not just RevenueCat's dashboard, are places production configuration lives.

Record which stores are configured (App Store, Play Store, Amazon, Stripe, and RevenueCat's own web billing can all sit behind one project) and whether the app is mobile-only, since a web checkout alongside the mobile IAP is usually a second provider entirely and needs its own stack file.

## dev server
Not applicable for this stack. Local purchase testing is store tooling, and it differs per platform:

- **iOS** — either a **StoreKit configuration file** in Xcode, which simulates purchases entirely on-device with no App Store Connect round trip (fastest, and it can simulate renewals at accelerated rates and failures), or an **App Store Connect sandbox tester** account signed in under Settings → App Store → Sandbox Account. Sandbox subscription periods are heavily compressed — a month is minutes — which is what makes renewal and expiry testable at all.
- **Android** — a **licence tester** account added in the Play Console, with the app published to an internal, closed, or internal-app-sharing track. Licence testers get test purchases with no charge, and Play likewise compresses subscription periods.
- Neither requires a real payment method, and neither should ever be a real Apple ID or Google account with a card attached.

RevenueCat routes sandbox purchases to a sandbox environment automatically and marks the resulting events `environment: "SANDBOX"` — see "runtime probe hints" for using that as the test-mode signal.

There is no local webhook forwarder equivalent to `stripe listen`. To receive webhooks against a local server, run a tunnel (`ngrok http 3000`, `cloudflared tunnel`) and point a **separate** webhook URL at it from the dashboard; the dashboard also has a "send test event" control, which verifies reachability and the header check but carries a synthetic `app_user_id` that will not match a real user (FLOW-004's caveat, exactly as on Stripe).

## build
Not applicable for this stack. Two build-adjacent facts: the SDK is a native dependency, so a purchase path cannot be exercised in a web preview or an Expo Go client without a development build; and product identifiers must exist in the store console before they resolve, so an offering that returns empty in a build is usually a store-configuration problem rather than a code one.

## env vars
| value | shape | where |
|---|---|---|
| public SDK key | `appl_...` (App Store), `goog_...` (Play), `amzn_...`, `strp_...`, and a distinct prefix for web billing | **in the client, by design** |
| secret API key | `sk_...` | server only |
| webhook authorization value | whatever you choose | server only, and in the dashboard |

**The public SDK key belongs in the app.** It is shipped in every binary, it can only do what a customer can do, and reporting it as a leak wastes attention. The **secret API key** (`sk_`) is the one that matters: it can read and modify any subscriber in the project, grant promotional entitlements, and refund. It is a DAT-004 fail in a client bundle, in `app.json`, in `Info.plist`, in `strings.xml`, or under any public env prefix, and unlike a Stripe key it will not announce itself by failing — a mobile binary is trivially unpacked. RevenueCat has been rolling out a V2 API with its own key format and per-key permissions; check the current dashboard for which key types this project has and whether a scoped key would cover what the server actually does (PAY-013's principle, applied here).

There is **no test/live key prefix**. Sandbox versus production is decided by which store account made the purchase, not by which key was used, so REL-007's usual "read the prefix" method does not work — the signal is the `environment` field on the event and on the subscriber record. Say so rather than reporting the check as unanswerable.

Store credentials also live in the RevenueCat dashboard rather than in the repo: the App Store Connect **in-app purchase key** and shared secret, the Play Service Account JSON, and the App Store Server Notifications URL. Those are HYG-001's rows for this stack — a project whose Play service account has expired stops validating Android purchases silently.

## routes and handlers
RevenueCat exposes no routes in your app; the SDK talks to `api.revenuecat.com` directly. The surfaces to enumerate:

**Client SDK calls** (find these to answer MOB-001, FLOW-008, PAY-002's read side):
```
Purchases.configure({ apiKey, appUserID })   // or configure(with:) on iOS
Purchases.logIn(appUserId) / logOut()
getOfferings()          -> the paywall's products
purchasePackage(pkg)    -> the purchase
getCustomerInfo()       -> customerInfo.entitlements.active['<entitlement>']
restorePurchases()      -> MOB-001, FLOW-008
customerInfo.managementURL -> the store's subscription management page (PAY-012)
```

**Server REST API** (`https://api.revenuecat.com/v1/...` or `/v2/...`, `Authorization: Bearer <sk_ key>`): `GET /v1/subscribers/<app_user_id>` returns the subscriber with their entitlements — this is the server-side source of truth and the thing a webhook handler should re-fetch rather than trusting the event payload. There are also endpoints to grant and revoke promotional entitlements, which is what a support tool would use.

**Your own webhook route**, which is the only handler in your codebase (see "webhook handlers").

For SEC-010, note where entitlement is *enforced*. A mobile app that gates a screen on `customerInfo.entitlements.active` is enforcing on the client, which is fine for UI and worth nothing for anything the server does. If the product has a backend, the backend must have its own entitlement record fed by the webhook — a server endpoint that trusts an `isPro` flag sent by the app is SEC-010, and an app that is purely client-side has no server to protect, which is a legitimate answer that must be stated rather than assumed.

## auth
Not applicable for this stack in the session sense. What matters is **app user id identity**, and it decides FLOW-008 and MOB-001:

- Configuring without an `appUserID` gives an **anonymous** id (RevenueCat generates one prefixed `$RCAnonymousID:`). Anonymous ids are device-local: a reinstall or a second device is a different customer, and the purchase does not follow the account. That is the less obvious version of "entitlement stored on the device" that FLOW-008 exists to catch.
- The correct shape is `Purchases.logIn(<your stable user id>)` after the user authenticates, and `logOut()` on sign-out, so entitlements attach to the account. Grep for `logIn(` and check the id passed is the app's own user id and not an email or a device id.
- **Never pass an email or anything guessable as the app user id**: it is effectively a bearer identifier — anyone who can call the SDK with a known id can inherit that customer's entitlements. Use an opaque, non-enumerable id.
- Transfers: when a purchase made anonymously is later attached to a signed-in id, RevenueCat applies the project's configured transfer behaviour and emits a `TRANSFER` event. If the app supports purchase-before-signup, read that setting, because it decides who keeps the subscription.

The webhook's `app_user_id` and `original_app_user_id` are how the server joins an event to a user. Store the id you passed to `logIn` on the user row so the lookup is a unique-constrained column (DAT-014), exactly as with a Stripe customer id.

## webhook handlers
One route in your app, receiving `POST` from RevenueCat with a JSON body of the shape `{ "api_version": "1.0", "event": { ... } }`.

**There is no HMAC signature.** RevenueCat authenticates the delivery by sending an `Authorization` header whose value you set in the dashboard when configuring the webhook, verbatim. So SEC-051's "verify the provider's signature" becomes "compare the `Authorization` header to a stored secret", and three things follow:
1. The comparison must be **constant-time** — `crypto.timingSafeEqual`, `hmac.compare_digest`, `secure_compare` — because a `===` on a shared secret leaks it by timing over many requests. SEC-052 owns this and it applies here more than on any signature-based provider, since the header **is** the secret rather than a derivative of it.
2. The secret is a bearer credential in transit on every delivery. HTTPS only, never logged (see "error handling and logging"), rotated if it ever appears in a log or a screenshot.
3. **There is no timestamp and therefore no replay window.** A captured delivery can be replayed forever with the same header. PAY-003's replay half has to be answered by your own dedup rather than by the provider: store `event.id` with a unique constraint and short-circuit on conflict, and prefer re-fetching the subscriber from the REST API over trusting the payload, which also solves ordering.

Register the production URL in the dashboard for the production project (PAY-001's equivalent) and confirm the header value there matches production's env. RevenueCat retries failed deliveries and surfaces failures in the dashboard's webhook log — check the current docs for the retry schedule and whether alerting on repeated failure is on, which is PAY-016.

**PAY-002 — the event set**, and the semantics are the part that gets this wrong:

| event | meaning | what to do |
|---|---|---|
| `INITIAL_PURCHASE` | first purchase or trial start | grant |
| `RENEWAL` | renewed successfully | extend |
| `CANCELLATION` | **auto-renew turned off** — access continues to the end of the paid period | mark "will not renew"; **do not revoke** |
| `UNCANCELLATION` | auto-renew turned back on | clear the flag |
| `EXPIRATION` | the subscription actually ended | **revoke** |
| `BILLING_ISSUE` | a renewal failed; the store is retrying | mark `past_due`, notify (PAY-006) |
| `PRODUCT_CHANGE` | the customer switched plan | reconcile the plan, not the access |
| `SUBSCRIPTION_PAUSED` | Android pause | suspend access for the pause window |
| `TRANSFER` | entitlements moved between app user ids | re-key the entitlement |
| `NON_RENEWING_PURCHASE` | consumable or one-time product | grant per your product rules |
| refund | money returned by the store | revoke |

**`CANCELLATION` is not the revoke event and `EXPIRATION` is** — an integration that revokes on `CANCELLATION` cuts off a customer who has paid through the end of the month, which is a support ticket and a refund from a working integration. PAY-002 names this specifically. Refunds have been surfaced both as a distinct `REFUND` event type and as a `CANCELLATION` carrying a refund-related `cancel_reason` (the `cancel_reason` field distinguishes an unsubscribe from a billing error, a developer-initiated cancel, a price-increase decline, and a customer-support refund); read the current webhook documentation for the exact set this project receives and handle whichever shape arrives, rather than branching on a name from memory. The useful fields on every event are `id`, `type`, `event_timestamp_ms`, `app_user_id`, `original_app_user_id`, `product_id`, `entitlement_ids`, `period_type` (`TRIAL`, `INTRO`, `NORMAL`), `store`, `expiration_at_ms`, and `environment`.

## webhook verification snippet
```ts
import { timingSafeEqual } from 'node:crypto'

const expected = Buffer.from(process.env.REVENUECAT_WEBHOOK_AUTH!)

export async function POST(req: Request) {
  const given = Buffer.from(req.headers.get('authorization') ?? '')
  // length check first: timingSafeEqual throws on a length mismatch, which is itself an oracle
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) {
    return new Response('unauthorized', { status: 401 })
  }
  const { event } = await req.json()          // no signature over the raw body, so parsing first is fine here

  // dedup: insert-first, never check-then-act (PAY-003)
  try { await db.processedEvent.create({ data: { id: event.id } }) }
  catch (e) { if (isUniqueViolation(e)) return new Response('ok'); throw e }

  // prefer the API's truth over the payload's (order tolerance, PAY-003)
  const sub = await fetch(`https://api.revenuecat.com/v1/subscribers/${event.app_user_id}`, {
    headers: { Authorization: `Bearer ${process.env.REVENUECAT_SECRET_KEY!}` },
  }).then(r => r.json())
  // write entitlement from sub.subscriber.entitlements, keyed on app_user_id
  return new Response('ok')
}
```
Note what is different from a signature-based provider: the raw body does not matter here, so the framework's body-parser rules do not apply — but the header comparison does, and getting it wrong is the same critical hole. If you find `req.headers.authorization === process.env.X`, that is SEC-052.

## data access
Not applicable for this stack — your database belongs to the framework and the data stack. What belongs here is where entitlement lives, and RevenueCat's answer is unusually clear: **entitlements are the source of truth, not products.** `customerInfo.entitlements.active['pro']` is the question the app should ask; `product_id` is an implementation detail that changes when you add a plan, an intro price, or a second store, and code branching on product ids breaks the first time pricing changes.

For a product with a backend, mirror the entitlement into your own table from the webhook — `user_id`, `entitlement`, `active`, `expires_at`, `store`, `period_type`, and the RevenueCat `app_user_id` as a unique-constrained join key (DAT-014). Read your own table for authorization (SEC-010), and re-fetch from the REST API on the paths where staleness matters. A backend that calls `getCustomerInfo` on the client and trusts what the client reports is not an entitlement check.

Money: the stores report proceeds after their commission and in the buyer's local currency; RevenueCat's events carry price and currency fields for reporting. If you store them, store minor units with the currency code (PAY-005) — but note that for revenue reporting the store's own figures, not the event's, are the ones that reconcile.

## file uploads
Not applicable for this stack.

## background jobs
Not applicable for this stack in the queue sense — renewals, retries, and grace periods are run by Apple and Google, and RevenueCat reflects them. That means PAY-006's dunning answer is mostly store configuration rather than repo state: the stores retry a failed renewal over a **billing grace period** and an **account hold** window whose lengths are configured in App Store Connect and the Play Console, and during that window `BILLING_ISSUE` has fired but the subscription has not expired. Whether your app keeps access during grace, and whether it tells the user, is the product decision PAY-006 audits — check both consoles for the configured windows and check the app does something with `BILLING_ISSUE` beyond logging it.

Two jobs worth having on your side, and worth recommending where absent: a reconciliation sweep that re-reads subscribers from the REST API and repairs entitlement rows the webhook dropped, and an expiry sweep for anything that stores `expires_at` locally, since `EXPIRATION` arriving late leaves a user with access past their period.

## error handling and logging
Log `event.id`, `event.type`, `app_user_id`, and `environment`. **Never log the `Authorization` header or the request headers wholesale** — it is the shared secret in cleartext, and unlike a signature it grants forgery to anyone who reads the log. That is a real and easy mistake in a handler that logs `JSON.stringify(req.headers)` while debugging.

Client-side, purchase errors arrive with a RevenueCat error code and a `userCancelled` flag; treating a user cancellation as a failure produces an error dialog after someone taps "Cancel", which is a bad-review-shaped defect rather than a security one. Check the purchase path distinguishes them. Network failures during a purchase leave the store transaction complete and the app unaware — which is the case `restorePurchases()` and the webhook both exist to repair, and another reason entitlement must not be a local boolean.

The dashboard has a per-customer event history and a webhook delivery log; both are the place to check when a grant did not land, and both are dashboard state you cannot read from the repo.

## security headers
Not applicable for this stack.

## known traps
- Revoking access on `CANCELLATION`: that event means auto-renew was turned off and the customer has paid through the period. `EXPIRATION` is the revoke event. PAY-002, and FLOW-005 tests exactly this boundary.
- Handling only `INITIAL_PURCHASE` and `RENEWAL`: PAY-002. `EXPIRATION`, `BILLING_ISSUE`, and the refund case are the paths that take access back.
- `req.headers.authorization === secret` with `===`: SEC-052, and here the header is the secret itself rather than a derived signature.
- No dedup on `event.id`, or a `select`-then-work-then-`insert`: PAY-003, PERF-017. There is no signature timestamp on this provider, so a captured delivery replays forever and your dedup is the only defence.
- The secret `sk_` API key shipped in the app binary, in `app.json`, or under a public env prefix: DAT-004. The public SDK key in the app is correct and is not a finding.
- The `Authorization` header logged with the rest of the request: the shared secret in plaintext in your log sink.
- `Purchases.configure` with no `appUserID` and no later `logIn`: the customer is anonymous and device-local, so a reinstall or a second device loses the purchase. FLOW-008, and MOB-001's account-linking half.
- An email address or another guessable value used as the app user id: anyone who can guess it inherits the entitlement.
- Entitlement cached in `UserDefaults` / `SharedPreferences` / `AsyncStorage` and trusted after a reinstall: FLOW-008. Recompute from `getCustomerInfo()` or from the server.
- No restore control, or one that exists in code but is not reachable from a screen a user can navigate to: MOB-001, and Apple rejects for it.
- A backend endpoint that trusts an `isPro` flag sent by the app: SEC-010. The server's entitlement must come from the webhook or the REST API.
- Branching on `product_id` instead of on the entitlement: breaks the first time a plan is added or a price is changed.
- Assuming your app can change prices: it cannot. Price changes go through App Store Connect and the Play Console, each with its own consent and notification rules for existing subscribers — Apple's differ by whether the increase is above a threshold, and Google requires the user to accept in some cases. PAY-017 is answered from those consoles, and the app's job is to handle a subscriber who declines and lapses.
- Expecting a customer portal: there is none. Management is the store's own subscription page — `customerInfo.managementURL` gives the right per-store URL, `https://apps.apple.com/account/subscriptions` on iOS and the Play subscriptions page on Android. PAY-012 is satisfied by linking to it from a place the user can find, and failing to link it at all is the finding.
- Expecting to handle tax or receipts: the stores are the merchant of record and handle both. PAY-008 and PAY-010 pass by construction on IAP revenue — say so with that reason rather than leaving them blank, and note that any non-IAP revenue path (a web checkout, a Stripe integration behind the same RevenueCat project) is **not** covered by it.
- Selling digital goods for the app's own functionality through anything other than IAP: MOB-006, and it is a store rejection rather than a technical defect.
- An expired Play service account or App Store in-app purchase key in the RevenueCat dashboard: purchase validation stops silently. HYG-001.
- Testing with a real Apple ID or Google account with a payment method attached: real money. Sandbox testers and licence testers only.

## runtime probe hints
**Test-mode detection has no key prefix here.** The signals are: the store account making the purchase (a sandbox tester or licence tester), and the `environment` field, which reads `"SANDBOX"` on sandbox events and subscriber records and `"PRODUCTION"` otherwise. Read `environment` on the event or on `GET /v1/subscribers/<id>` and write the determination down before doing anything that could spend money. If you cannot establish it, stop — treat it as live.

**Reading a subscriber's state** (read-only, needs the secret key, so run it server-side and never from a client):
```bash
curl -s "https://api.revenuecat.com/v1/subscribers/<app_user_id>" \
  -H "Authorization: Bearer $REVENUECAT_SECRET_KEY" | jq '.subscriber.entitlements'
```
This is the authoritative entitlement state and the right thing to compare your own table against for PAY-002's evidence.

**The webhook probe** for SEC-051 needs no store at all and is safe:
```bash
# wrong header
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:3000/api/webhooks/revenuecat \
  -H 'authorization: wrong' -H 'content-type: application/json' \
  -d '{"api_version":"1.0","event":{"id":"probe","type":"INITIAL_PURCHASE","app_user_id":"probe"}}'
# no header at all
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:3000/api/webhooks/revenuecat \
  -H 'content-type: application/json' -d '{"api_version":"1.0","event":{"id":"probe","type":"INITIAL_PURCHASE"}}'
```
Expect 401 or 400 both times. A 200, or any sign the payload was processed, is the finding. Then send the same body twice **with the correct header** to test PAY-003's dedup, and confirm the entitlement was written once.

**The purchase flow itself** (MOB-001, FLOW-004, FLOW-008) is device tooling and is slower than every other probe here:
- iOS: run the app on a simulator with a StoreKit configuration file for the fastest loop, or on a device signed into a sandbox tester for the true path. `xcrun simctl uninstall booted <bundle id>` destroys local state for the restore test.
- Android: a licence tester on an internal track. `adb uninstall <package>` for the same purpose.
- The sequence FLOW-008 wants: buy the cheapest product in sandbox, confirm the entitlement is active, uninstall and reinstall (or sign out and back in, or use a second device), tap Restore, and confirm the entitlement returns without a second purchase. Test both orders — restore-then-login and login-then-restore — because a reviewer will do the first.
- Sandbox renewal periods are compressed to minutes, which is what makes `RENEWAL`, `BILLING_ISSUE`, and `EXPIRATION` observable in one sitting. Keep the webhook log open while you wait.

**Where no simulator, device, or sandbox tester is available**, the mobile checks downgrade rather than stop: run the static entry, record `verified_by: static-fallback`, and name exactly what was missing.

**Never** use a real store account with a payment method, never call the entitlement-granting REST endpoints against production, and delete or reset the sandbox customer afterwards where the dashboard allows it.
