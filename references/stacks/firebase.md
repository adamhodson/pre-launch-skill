# Firebase

## detection signals
`firebase.json` at the root, with `.firebaserc` naming the project aliases. The rules and index files it points at: `firestore.rules`, `firestore.indexes.json`, `storage.rules`, `database.rules.json`. In dependencies: `firebase` (the client SDK, v9+ modular), `firebase-admin` and `firebase-functions` (server), `@react-native-firebase/*`, `@angular/fire`, `firebase_core` / `cloud_firestore` in a Flutter `pubspec.yaml`. Mobile config files `google-services.json` (Android) and `GoogleService-Info.plist` (iOS). A `functions/` directory with its own `package.json` is Cloud Functions.

**Read `firebase.json` before anything else**, because it decides which rules files are deployed. A `firestore.rules` sitting in the repo that `firebase.json` does not reference is not the file protecting the database — DAT-003 fails on that alone, and it is a failure that looks like a pass to anyone grepping the rules file. The same file also tells you which products are in use: `hosting`, `firestore`, `storage`, `functions`, `database`, `emulators`.

Which Firebase products the app uses matters more than the version. Firestore and Realtime Database are different databases with different rules languages, and a project can use both.

## dev server
`firebase emulators:start` boots the local suite; `firebase emulators:start --only firestore,auth,storage` narrows it; `firebase emulators:exec "<command>"` starts the suite, runs one command, and shuts down — that last form is what CI uses and what DAT-003 wants for the rules tests. Ports are configurable in `firebase.json` under `emulators`, so read that block; the defaults:

| emulator | default port |
|---|---|
| Emulator UI | 4000 |
| Authentication | 9099 |
| Firestore | 8080 |
| Realtime Database | 9000 |
| Functions | 5001 |
| Hosting | 5000 |
| Storage | 9199 |
| Pub/Sub | 8085 |

**The emulators enforce the same rules files the deploy uses**, which is what makes every DAT-003 and SEC-011 probe below meaningful without touching a real project. Two things to confirm before trusting a probe: `firebase emulators:start` prints which emulators actually started (a missing one means requests silently went to production), and the client SDK must be pointed at them explicitly — `connectFirestoreEmulator(db, 'localhost', 8080)`, `connectAuthEmulator(auth, 'http://localhost:9099')`, `connectStorageEmulator`, `connectFunctionsEmulator` — or, for Admin SDK and server code, the environment variables `FIRESTORE_EMULATOR_HOST=localhost:8080`, `FIREBASE_AUTH_EMULATOR_HOST=localhost:9099`, `FIREBASE_STORAGE_EMULATOR_HOST=localhost:9199`. Grep for those connect calls and check they are guarded by an environment condition; a `connectFirestoreEmulator` that runs unconditionally is a production app talking to nothing, and its absence in development means every local test just wrote to the real database.

The app's own dev server is the framework's — read that stack file. `firebase emulators:start` with the `hosting` emulator serves the built static site, not a dev server with hot reload.

## build
Not applicable for this stack directly; the app's framework owns the build. The Firebase-side commands the audit cares about are the deploys, because they are what makes rules real: `firebase deploy --only firestore:rules`, `--only storage:rules`, `--only functions`, `--only hosting`. Rules are deployed separately from code, so a corrected `firestore.rules` in a merged commit is still not in production until someone ran that command — check CI for a deploy step covering rules, and treat "the fix is in the repo" as unproven without one.

`functions/` builds independently (its own `package.json`, usually `npm run build` for TypeScript into `functions/lib/`). The client config object is embedded in the client bundle by design (see "env vars"), so grepping the bundle for `apiKey` is expected to hit and is not SEC-003; grep it for the *service account* fields instead.

## env vars
**The client config is public by design and this is the single most misunderstood thing about the stack.** `apiKey`, `authDomain`, `projectId`, `storageBucket`, `messagingSenderId`, `appId`, and `measurementId` are identifiers, not credentials — they ship in every web bundle and inside every mobile binary, Google's own documentation says to publish them, and `google-services.json` / `GoogleService-Info.plist` contain the same values. A `NEXT_PUBLIC_FIREBASE_API_KEY` is not a SEC-003 finding. What *is* true, and what makes DAT-003 critical rather than merely important, is that anyone who reads your bundle has a fully working client for your project — so the security rules are the only thing between them and the data.

The credentials that are secret, and that DAT-004 and SEC-001 own:
- The **service account JSON** — `serviceAccountKey.json`, `firebase-adminsdk-*.json`, or the same fields split across `FIREBASE_PROJECT_ID` / `FIREBASE_CLIENT_EMAIL` / `FIREBASE_PRIVATE_KEY` env vars. The Admin SDK **bypasses all security rules**, exactly like a database superuser. Confirm the file is gitignored *and* absent from git history (`git log --all --oneline -- '*serviceAccount*' '*adminsdk*'`); if it was ever committed, it must be revoked in the Google Cloud console, not just deleted.
- `GOOGLE_APPLICATION_CREDENTIALS` pointing at that file.
- Any `FIREBASE_PRIVATE_KEY` carrying a public prefix (`NEXT_PUBLIC_`, `VITE_`, `EXPO_PUBLIC_`, `PUBLIC_`, `REACT_APP_`) is an immediate DAT-004 fail.
- The **Web API Key** used for the Auth REST API is the same public `apiKey`; it is not the secret.

Cloud Functions configuration has two generations. The older `functions.config()` values (`firebase functions:config:get`) are deprecated; the current form is a `functions/.env` / `.env.<project-alias>` file for non-secrets plus `defineSecret('NAME')` from `firebase-functions/params`, backed by Google Secret Manager and set with `firebase functions:secrets:set NAME`. Which one this project uses tells you where the production secrets actually live for the access checks. For DAT-017, the thing to compare between preview and production is the `projectId` — one Firebase project shared across environments means previews write to live data, and separate projects per environment (with `.firebaserc` aliases) is the passing shape.

## routes and handlers
Firebase serves no application routes of its own; the client SDK talks to Google's APIs directly. What is reachable:

- **Firestore** at `https://firestore.googleapis.com/v1/projects/<projectId>/databases/(default)/documents/...` with an ID token, and over gRPC from the SDKs. Rules are evaluated on every request.
- **Realtime Database** at `https://<db>.firebaseio.com/<path>.json`, likewise.
- **Storage** at `https://firebasestorage.googleapis.com/v0/b/<bucket>/o/<urlencoded path>`, with `?alt=media` for the bytes and a `token` query parameter for the long-lived download URLs `getDownloadURL()` mints.
- **Auth** at `https://identitytoolkit.googleapis.com/v1/accounts:*?key=<apiKey>`.
- **Cloud Functions** — `onRequest` handlers at `https://<region>-<projectId>.cloudfunctions.net/<name>` (1st gen) or a Cloud Run URL (2nd gen); `onCall` handlers at the same address but invoked through the SDK's callable protocol. Source in `functions/src/` or `functions/index.js`; enumerate them with `firebase functions:list`.
- **Hosting** rewrites in `firebase.json` (`hosting.rewrites`) can map a URL path onto a function or Cloud Run service — read them, because they create routes that exist in no source file.

For SEC-010, the surface list is: every `onRequest` function, every `onCall` function, every hosting rewrite, and the rules files (which are the authorization layer for all direct data access). A "route" here is frequently a rules `match` block rather than a handler.

## auth
Firebase Authentication issues an **ID token** (a signed JWT, ~1 hour lifetime, refreshed by the SDK). The client holds it; everything server-side verifies it.

**In security rules**, the identity is `request.auth`: `request.auth != null` for signed-in, `request.auth.uid` for the user id, `request.auth.token` for the claims (including custom claims set with `admin.auth().setCustomUserClaims(uid, {...})`, which is how roles are done — SEC-012). `request.auth != null` alone is *not* an authorization check; it means "any of my users", and on a product with open sign-up that is any of the internet's users who spent thirty seconds registering. DAT-003 fails on it for writes, and DAT-002's principle applies identically: the predicate must compare something on *this document* to `request.auth.uid`.

**In Cloud Functions**, the two kinds differ and the difference is the whole check:
- `onCall` (callable): the SDK attaches and the platform verifies the ID token for you, so identity arrives as `context.auth` (1st gen: `functions.https.onCall((data, context) => ...)`) or `request.auth` (2nd gen: `onCall((request) => ...)`). It is `undefined`/`null` for an unauthenticated caller — and the function still runs. **A callable that reads `context.auth.uid` without first checking `context.auth` exists is not protected; it just throws for anonymous callers, which is a 500, not a 403.** The correct shape is an explicit `if (!context.auth) throw new functions.https.HttpsError('unauthenticated', ...)` at the top (SEC-010).
- `onRequest` (plain HTTP): **nothing is verified.** It is a public URL. Identity must be established by hand — read the `Authorization: Bearer <idToken>` header and call `admin.auth().verifyIdToken(token)` — and a handler that trusts a `uid` from the request body or a query parameter is SEC-010 and SEC-011 in one line. This is the most common auth defect on this stack, because the two function types look nearly identical in the source.

Sign-in providers, authorized domains, email templates, and the action-link continue URL are console state, not repo state — HYG-001 owns them, and `firebase.json` cannot answer any of it. The "Authorized domains" list in the Auth settings is the redirect allowlist; a production project still carrying only `localhost` breaks OAuth sign-in on the live domain, and one carrying a stale staging domain is the lower-severity half of the same finding.

## webhook handlers
Inbound webhooks are `onRequest` functions (never `onCall` — a provider does not speak the callable protocol). The signature-verification requirement of SEC-051 applies in full, and the raw body has a Firebase-specific trap: **`functions.https.onRequest` parses the body for you and exposes it as `req.body`, but 1st-gen functions also expose the unparsed bytes as `req.rawBody`, which is what the signature must be computed over.** Re-serializing `req.body` with `JSON.stringify` produces different bytes and verification fails or, worse, is silently skipped by a `catch` that returns 200. In 2nd gen the property may not be populated the same way — check what your version gives you and log `typeof req.rawBody` once rather than assuming.

Outbound, the Firebase-native equivalents are background triggers rather than webhooks: `onDocumentWritten` / `onDocumentCreated` (Firestore), `onObjectFinalized` (Storage), `beforeUserCreated` / `onUserCreated` (Auth), `onSchedule` (Cloud Scheduler), and Pub/Sub subscriptions. Those run with Admin privileges and bypass rules, which is fine and intended — but it means a Firestore trigger is a place where the rules you audited do not apply, so any authorization logic in it must be written out longhand.

## webhook verification snippet
```js
// functions/index.js — Stripe webhook as a 1st-gen HTTP function
const functions = require('firebase-functions')
const Stripe = require('stripe')
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY)

exports.stripeWebhook = functions.https.onRequest(async (req, res) => {
  const sig = req.headers['stripe-signature']
  let event
  try {
    // req.rawBody, NOT req.body — the parsed object will not verify
    event = stripe.webhooks.constructEvent(req.rawBody, sig, process.env.STRIPE_WEBHOOK_SECRET)
  } catch (err) {
    return res.status(400).send('bad signature')
  }
  // dedup on event.id before doing the work (PAY-003)
  res.status(200).send('ok')
})
```
The secret comes from `defineSecret`/Secret Manager or the functions `.env`, never from `functions.config()` in new code. Deploying this function makes its URL public, which is correct for a webhook and is the reason SEC-051's probe (a POST with a wrong signature, expecting 400) is meaningful against it.

## data access
**The rules files are the data access layer.** There is no server-side query layer to audit on a client-direct Firebase app: the browser talks to Firestore, and `firestore.rules` is the entire authorization boundary. That is what makes DAT-003 critical.

**`firestore.rules`** — read the whole file top to bottom, since a broad `match` above a narrow one still grants:
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /notes/{noteId} {
      allow read: if request.auth != null && resource.data.owner == request.auth.uid;
      allow create: if request.auth != null && request.resource.data.owner == request.auth.uid;
      allow update, delete: if request.auth != null
        && resource.data.owner == request.auth.uid
        && request.resource.data.owner == resource.data.owner;
    }
  }
}
```
The distinctions DAT-003 turns on:
- `allow read, write: if true` — the whole database, to anyone with the public config. Immediate fail.
- The dated test-mode rule `allow read, write: if request.time < timestamp.date(2026, 1, 1)` — a fail whether or not the date has passed, because after it passes the app is broken instead and someone will "fix" it by going back to `true`.
- `resource.data` is the document **as it currently is**; `request.resource.data` is **what the write would produce**. An update rule checking only `resource.data.owner == request.auth.uid` lets the owner rewrite the `owner` field and hand the document to someone else, or rewrite a `role`, `plan`, or `credits` field the app trusts. Every `allow update` needs a `request.resource.data` clause.
- `match /{document=**}` is a recursive wildcard that matches everything below it. One permissive recursive block above your careful per-collection rules makes the careful ones irrelevant.
- **Rules are not filters.** A query is rejected if the rules cannot prove that *every* document it could return is allowed, so a rule requiring `resource.data.owner == request.auth.uid` forces the client to issue `where('owner', '==', uid)`. This is why "it works in the app" is not evidence that the rules are tight and why a rule loosened to make a list screen work is such a common regression — grep the client queries alongside the rules.

**`storage.rules`** has the same shape under `service firebase.storage { match /b/{bucket}/o { ... } }`, with the path as the ownership key: `match /users/{userId}/{allPaths=**} { allow write: if request.auth.uid == userId; }`. Size and type constraints belong here too — `request.resource.size < 5 * 1024 * 1024` and `request.resource.contentType.matches('image/.*')` — since there is no server in the upload path to enforce them.

**`database.rules.json`** (Realtime Database) is a different language with one rule that catches people out: **`.read`/`.write` cascade downward and cannot be revoked by a child.** A `true` at the root grants the entire tree regardless of every rule beneath it. Read from the root down and stop at the first `true`.

**Testing the rules** is the second half of DAT-003 and the only way to know they are right:
```js
// test/rules.test.js — @firebase/rules-unit-testing
const { initializeTestEnvironment, assertFails, assertSucceeds } = require('@firebase/rules-unit-testing')
const fs = require('fs')

const env = await initializeTestEnvironment({
  projectId: 'demo-test',
  firestore: { rules: fs.readFileSync('firestore.rules', 'utf8'), host: 'localhost', port: 8080 },
})
const alice = env.authenticatedContext('alice').firestore()
const bob = env.authenticatedContext('bob').firestore()
const anon = env.unauthenticatedContext().firestore()

await assertSucceeds(alice.doc('notes/n1').set({ owner: 'alice', body: 'hi' }))
await assertFails(bob.doc('notes/n1').get())
await assertFails(bob.doc('notes/n1').update({ owner: 'bob' }))
await assertFails(anon.doc('notes/n1').get())
```
Run it with `firebase emulators:exec --only firestore,storage "npm test"`. `env.withSecurityRulesDisabled(ctx => ...)` is the seeding escape hatch — seed with it, never assert with it. A project with no rules tests is part of the DAT-003 finding rather than a blocker; write the three assertions above during the audit if the emulator is available, since they take minutes and they are the evidence.

**Query and schema concerns** in Firestore terms:
- DAT-011 — `.limit(n)` on every list query, with `startAfter(lastDoc)` for the next page. A `getDocs(collection(db,'x'))` with no limit reads and bills for the whole collection.
- DAT-012 — `writeBatch()` (up to 500 operations per batch) or `BulkWriter` instead of a loop of `setDoc`. A loop of awaited writes is one round trip each.
- DAT-013 — `runTransaction()`, which retries on contention; note that all reads must precede all writes inside it.
- DAT-009 — composite indexes are **required**, not an optimization: a compound query fails at runtime with an error containing a console link until the index exists. They belong in `firestore.indexes.json` and must be deployed (`firebase deploy --only firestore:indexes`); an index created by clicking the error link exists in the console and not in the repo, which is drift worth naming.
- DAT-014 — there are no unique constraints. Uniqueness is done by using the value as a document id in a dedicated collection (`usernames/{username}`) written inside a transaction; a check-then-write in application code loses the race.
- PAY-005 — Firestore numbers are IEEE-754 doubles unless written as integers; store money as integer minor units with a currency field, never as a fractional number.
- SEC-038 — not applicable, there is no SQL. The equivalent injection surface is a document path or collection name built from user input, which lets a caller read a sibling path; check any `doc(db, userSuppliedPath)`.
- DAT-015 — Firestore is schemaless, so there are no migrations to replay. The DAT-015 question becomes whether backfill scripts exist and are committed, whether the rules and indexes files are versioned and deployed from CI, and whether a rollback of a rules change is possible (it is: redeploy the previous file, and the console keeps a rules history).

## file uploads
`uploadBytes` / `uploadBytesResumable` / `putFile` write directly from the client to Cloud Storage — **there is no server in the path**, so `storage.rules` is the only enforcement point for who may write, where, how large, and of what type (see "data access"). A server-side upload through the Admin SDK bypasses rules entirely.

`getDownloadURL()` returns a URL carrying a long-lived, unguessable `token` query parameter. It is a bearer capability with no expiry: anyone the URL is shared with can read the file forever, and revoking it means rotating the token in the console. That is materially different from the signed expiring URL SEC-050 asks for — where the check wants expiry, the correct answer on this stack is a server-minted signed URL from the Admin SDK (`getSignedUrl({ expires })` via the underlying `@google-cloud/storage` bucket) rather than `getDownloadURL()`. Say which one the app uses.

The underlying bucket is a GCS bucket, so DAT-005's other half applies: check it has no `allUsers` or `allAuthenticatedUsers` IAM binding, which would make objects readable outside the rules entirely (`gsutil iam get gs://<bucket>` if the CLI is authenticated). Firebase Storage rules do not constrain access granted at the IAM layer.

## background jobs
`onSchedule` functions (backed by Cloud Scheduler) — `exports.daily = onSchedule('every 24 hours', handler)` — plus Pub/Sub triggers, Firestore/Storage/Auth background triggers, and Cloud Tasks for anything that needs a real queue with retries. Enumerate with `firebase functions:list`; the emulator suite can run scheduled functions only when explicitly triggered, so a scheduled job is usually verified by reading it.

Background triggers run with Admin privileges, so rules do not apply inside them (see "webhook handlers"). Two failure modes worth checking: a Firestore `onDocumentWritten` trigger that writes back to the same document, which re-triggers itself — an infinite loop that bills — unless it compares before and after and returns early; and retries, which are off by default for background functions and, when enabled, mean the handler must be idempotent (PAY-003's rule, applied to triggers).

Timeouts and memory are per-function (`runWith({ timeoutSeconds, memory })` in 1st gen, options in the 2nd-gen constructor) with a plan-dependent ceiling — check the current docs rather than quoting a number (PERF-020). Cloud Functions require the Blaze (pay-as-you-go) plan at all; a project still on Spark has no functions and no outbound network from the backend, which is a REL-020 conversation.

Email: Firebase Auth sends verification, reset, and email-change messages itself, from a Google sender unless a custom SMTP and sender domain are configured in the console (HYG-001 for the domain and its SPF/DKIM records, REL-020 for the sending quota). Product email is the app's own provider.

## error handling and logging
Cloud Functions log to Cloud Logging: `functions.logger.info/warn/error` (structured) or plain `console.log` (captured too, less usefully). Read them with `firebase functions:log`, `firebase functions:log --only <name>`, or the Google Cloud console. In `onCall` handlers, only `HttpsError` is returned to the client with its message intact — every other thrown error is flattened to `INTERNAL` with no detail, which is good for SEC-009 and bad for debugging, so check the handler logs the real error before throwing the sanitized one.

Client-side, Firestore permission denials surface as `FirebaseError` with `code: 'permission-denied'`. An app that catches those and renders an empty state hides a rules bug indefinitely — grep for a broad `catch` around a Firestore call that neither logs nor surfaces.

Crashlytics (`firebase/crashlytics`, `@react-native-firebase/crashlytics`) is the mobile error tracker; Sentry or equivalent for web (REL-001). Firebase Performance Monitoring and Google Analytics for Firebase are separate SDKs, and both count for MOB-004's privacy-label question.

## security headers
`firebase.json` under `hosting.headers` — an array of `{ source, headers: [{ key, value }] }` entries. That is where `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy`, and `Permissions-Policy` go for a Firebase Hosting deployment:
```json
"hosting": {
  "headers": [
    { "source": "**", "headers": [
      { "key": "X-Content-Type-Options", "value": "nosniff" },
      { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" }
    ]}
  ]
}
```
HSTS is applied by Firebase Hosting on its own domains; add the header explicitly for a custom domain and check the value rather than assuming. If the app is hosted somewhere else, this section belongs to that platform's stack file and only the Firebase APIs are Google's. CORS for direct browser access to the Storage bucket is a bucket-level GCS setting (`gsutil cors set`), not a Firebase one, and is a separate thing from the Hosting headers.

## known traps
- `allow read, write: if true`, or the dated test-mode rule, in `firestore.rules` or `storage.rules`: DAT-003.
- A rules file present in the repo but not referenced from `firebase.json`, or corrected in a commit but never deployed: DAT-003, and it reads as a pass to anyone who only greps the file.
- `request.auth != null` as the whole predicate: DAT-003 — it means "any registered user", not "the owner". DAT-002 states the same principle for SQL stacks.
- An `allow update` that checks `resource.data` but not `request.resource.data`: the caller rewrites the owner, role, or plan field. DAT-003.
- `match /{document=**}` granting more than the specific rules below it: DAT-003.
- Realtime Database `.read`/`.write` cascading — a `true` near the root cannot be revoked by any child rule: DAT-003.
- A committed `serviceAccountKey.json` or `firebase-adminsdk-*.json`, or `FIREBASE_PRIVATE_KEY` under a public env prefix: SEC-001, DAT-004. The Admin SDK bypasses every rule, so this is the whole database.
- Treating the client `apiKey` as a leak: it is not (see "env vars"), and reporting it wastes the reader's attention on the one thing that is public by design.
- `onCall` reading `context.auth.uid` with no `if (!context.auth)` guard, and `onRequest` doing no `verifyIdToken` at all: SEC-010. Any handler taking a `uid` from the request rather than the token is SEC-011.
- App Check never enabled, or enabled but left in monitoring rather than enforcement mode: SEC-015. Without it the public config is a working client for scripted abuse of Auth, Firestore, Storage, and callable functions, and rules alone cannot rate-limit anything. Enforcement is per-service console state, so it cannot be confirmed from the repo.
- No rate limiting anywhere: Firebase provides none for Firestore or Storage, and the Auth quotas are Google's, not yours. SEC-015 has to be answered by App Check, a Cloud Armor / WAF rule, or logic in a callable function.
- A Firestore trigger that writes to the document that triggered it, with no before/after comparison: an infinite loop that bills. Cite PERF-020 for the runaway-cost shape and DAT-012 if it also writes per-row.
- A composite index created by clicking the console's error link and never added to `firestore.indexes.json`: DAT-009 drift — it works in production and fails in a fresh project.
- Uniqueness enforced by a read-then-write in application code rather than by a document id in a dedicated collection inside a transaction: DAT-014, and PERF-017 for the race.
- `getDownloadURL()` tokens treated as expiring links: they do not expire. SEC-050.
- One Firebase project shared by development, preview, and production: DAT-017. Separate projects with `.firebaserc` aliases is the fix.
- An `allUsers` IAM binding on the storage bucket, which makes objects public underneath the rules: DAT-005, DAT-006.
- Emulator connect calls (`connectFirestoreEmulator` and friends) that are unconditional, or absent so local development wrote to the live project: DAT-017 in the second case, and a broken production app in the first.

## runtime probe hints
**Start the emulators and confirm which came up.** `firebase emulators:start --only auth,firestore,storage` prints a table of what is running and on which port; the Emulator UI at `http://localhost:4000` is the fastest way to see data and rule evaluations. Every probe below is against the emulator suite — never against a live project.

**An ID token for the test account.** The Auth emulator speaks the real Identity Toolkit REST API, and it accepts any string as the API key:
```bash
# create
curl -s -X POST 'http://localhost:9099/identitytoolkit.googleapis.com/v1/accounts:signUp?key=fake-api-key' \
  -H 'content-type: application/json' \
  -d '{"email":"qa+'"$(date +%s)"'@example.com","password":"<from credentials_env>","returnSecureToken":true}'
# sign in
curl -s -X POST 'http://localhost:9099/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=fake-api-key' \
  -H 'content-type: application/json' \
  -d '{"email":"...","password":"...","returnSecureToken":true}' | jq -r .idToken
```
The response carries `idToken`, `refreshToken`, and `localId` (the uid). Against a real project the same calls go to `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<the public web apiKey>` — which is how a client signs in, and worth knowing, but do not use it against production during an audit. Decode the token's claims with `cut -d. -f2 | base64 -d`; the emulator signs tokens with a fake key, so anything verifying signatures must be pointed at the emulator too.

**Probing Firestore as a user** (DAT-003, SEC-011). The emulator exposes the Firestore REST API on its own port, and rules are evaluated against the bearer token:
```bash
P=<projectId>
curl -s "http://localhost:8080/v1/projects/$P/databases/(default)/documents/notes/n1" \
  -H "Authorization: Bearer $ID_TOKEN"
```
Expect `403`/`PERMISSION_DENIED` when the rules should deny. The emulator also honours `Authorization: Bearer owner` as an admin bypass that ignores rules — use it only to seed a document as another user, never to assert a result, and say in the evidence which mode each request used. Where the REST shape fights you, the `@firebase/rules-unit-testing` script under "data access" is the more reliable probe and produces better evidence; prefer it.

**No mail catcher.** The Auth emulator does not send email and there is no SMTP server in the suite (FLOW-001, FLOW-003). The verification and password-reset links appear in two places instead: the `firebase emulators:start` terminal log, which prints the full out-of-band link for each request, and the Emulator UI's Authentication tab. There is also an emulator-only REST endpoint listing pending out-of-band codes — `http://localhost:9099/emulator/v1/projects/<projectId>/oobCodes` — which returns the `oobLink` for each; confirm the path against this emulator version's own docs before relying on it, and fall back to scraping the terminal log, which has been stable. Record which method you used. Against a real project no such surface exists and the mail goes to a real inbox — that is a reason to run FLOW-001 on the emulator, not a reason to run it on production.

**Resetting emulator state between probes** (safe — this touches only the emulator):
```bash
curl -s -X DELETE "http://localhost:8080/emulator/v1/projects/$P/databases/(default)/documents"   # clear Firestore
curl -s -X DELETE "http://localhost:9099/emulator/v1/projects/$P/accounts"                        # clear Auth users
```

**Health path.** None by convention. `http://localhost:4000` answers when the suite is up, and each emulator's port answers on `/`. For the app's own health route, read the framework's stack file.

**Test-mode detection.** There is no key prefix to read (see "env vars"), so the only signals are the `projectId` and whether the emulator host variables are set in the running process. A `projectId` that matches production, with `FIRESTORE_EMULATOR_HOST` unset, means the probe is about to hit live data — stop and record `error: production project detected`. A conventional `demo-` prefix on the project id makes the emulator refuse to reach any real service, and a project set up that way is the safest thing to probe against.

**Throwaway identity.** Create it through the Auth emulator's `accounts:signUp` above with `qa+<unix-ts>@example.com`; delete it with the accounts endpoint when done. Never reuse the shared test account where a check needs a second identity (DAT-003's second-user assertion, SEC-011, AI-001).
