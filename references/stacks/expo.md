# Expo

## detection signals
`expo` in `package.json` dependencies, plus `app.json`, `app.config.js`, or `app.config.ts` carrying an `expo` key. `eas.json` means EAS Build and/or EAS Update are in use. `.expo/` is the local tooling cache and is gitignored on every Expo project. `babel.config.js` with `babel-preset-expo`, `metro.config.js` extending `expo/metro-config`, and `expo-env.d.ts` are supporting signals. The Expo SDK version is the `expo` dependency's major (`"expo": "~52.0.0"` is SDK 52); write it down, because on a managed project it pins the default Android `targetSdkVersion`, the default iOS deployment target, and the React Native version underneath.

Routing: `expo-router` in dependencies with an `app/` directory of file-based screens, or `@react-navigation/*` with a hand-written navigator tree (usually `navigation/`, `src/navigation/`, or `App.tsx`).

**Establish managed versus bare before reading anything else** — it decides where every platform value lives, and getting it wrong makes half the mobile domain look like a fail:

- **Managed / CNG (Continuous Native Generation)** — no `ios/` or `android/` directory in the repo, or one that exists but is gitignored. Native config lives in the app config and is materialized by `expo prebuild` at build time (EAS does this for you). The app config is the source of truth.
- **Bare / prebuilt** — `ios/` and `android/` are committed. The native files are the source of truth and the app config's `ios.*` / `android.*` keys may be stale, because they only take effect on the next prebuild. When both exist, read the native file and note the drift; a committed native directory that disagrees with the app config is worth one line on its own.

**Do not run `npx expo prebuild`** to make the native directories appear. It writes `ios/` and `android/` into the project, and this audit never modifies project files. Read the app config instead.

Where each value lives, per mode:

| value | managed (app config) | bare (on disk) |
|---|---|---|
| iOS `Info.plist` keys, usage strings | `expo.ios.infoPlist` | `ios/<App>/Info.plist` |
| iOS entitlements | `expo.ios.entitlements` | `ios/<App>/<App>.entitlements` |
| Associated domains (universal links) | `expo.ios.associatedDomains` | the entitlements file's `com.apple.developer.associated-domains` |
| URL scheme | `expo.scheme` (string or array) | `Info.plist` `CFBundleURLTypes`, plus `android:scheme` in the manifest |
| Android permissions | `expo.android.permissions`, `expo.android.blockedPermissions` | `android/app/src/main/AndroidManifest.xml` |
| Android deep links | `expo.android.intentFilters` (with `autoVerify`) | manifest `<intent-filter android:autoVerify="true">` |
| `targetSdkVersion` / `compileSdkVersion` | the `expo-build-properties` plugin's `android` block, else the SDK default | `android/app/build.gradle`, root `build.gradle` `ext`, or `gradle.properties` |
| iOS privacy manifest | `expo.ios.privacyManifests` | `ios/<App>/PrivacyInfo.xcprivacy` |
| ATS / cleartext | `expo.ios.infoPlist.NSAppTransportSecurity`, `expo.android.usesCleartextTraffic` | `Info.plist`, `AndroidManifest.xml` `android:usesCleartextTraffic` |
| version / build number | `expo.version`, `expo.ios.buildNumber`, `expo.android.versionCode` (or `eas.json` `autoIncrement`) | `Info.plist` `CFBundleShortVersionString`/`CFBundleVersion`, `build.gradle` `versionName`/`versionCode` |
| build profiles | `eas.json` | `eas.json` (unchanged) |

`app.config.js`/`.ts` is **executed**, not parsed, so a value can be computed from `process.env` at config-evaluation time. Grep the config file for `process.env` before concluding a key is absent — `ios: { bundleIdentifier: process.env.BUNDLE_ID }` is common, and it means the effective config differs per build environment. The resolved config is readable with `npx expo config --type public` (or `--type prebuild`), which is the reliable way to see what a build will actually get; prefer it to reading the file by eye.

Native modules that need a config plugin appear in `expo.plugins` as strings or `[name, options]` pairs. That array is the second place native config hides, and a plugin's options (`expo-notifications` icons, `expo-tracking-transparency`'s prompt string, `expo-build-properties`' SDK levels) never appear anywhere else.

## dev server
`npx expo start` (Metro, default port 8081, `--port` to change). `npx expo start --dev-client` for a development build, `--go` to force Expo Go. The QR code and the printed `exp://` URL are how a device attaches.

Two clients, and the difference matters for what you can test at all:

- **Expo Go** — the prebuilt sandbox app from the store. It only contains the native modules Expo ships in it, so anything with custom native code (RevenueCat, most IAP libraries, `react-native-mmkv`, a pinning library, many analytics SDKs) will not run, and neither will config-plugin-driven behaviour. If purchases, push tokens, or ATT need testing and the project is on Expo Go, say so and record the runtime half as unrun rather than as a fail.
- **Development build** — your own binary built by `eas build --profile development` (or locally) with `expo-dev-client`. It contains the project's real native modules and is the only honest local target for the MOB domain's runtime work.

`npx expo run:ios` / `npx expo run:android` compile and install locally; both **run `prebuild` implicitly** and will write `ios/`/`android/` into a managed project, so treat them the same way as `expo prebuild` and do not run them on a managed repo. On a bare project they are the normal local build path.

A device on the same LAN reaches Metro by the LAN IP, not `localhost` — see "runtime probe hints" for the same trap applied to the app's own API.

Never measure launch time, bundle size, or crash rate against a dev-client run: the dev bundle is unminified, carries the dev menu and the fast-refresh runtime, and boots several seconds slower. Those measurements belong to a release build ("build").

## build
**EAS Build** is the normal path. Profiles live in `eas.json` under `build.<profile>` and the ones that matter are usually `development`, `preview`, and `production`. For MOB-010 the question is which profile produced the artifact the user is about to submit, and the answer is the one whose `distribution` is `store` (or absent, which defaults to store) and whose iOS `buildConfiguration` is not `Debug`:

```bash
eas build --profile production --platform all      # the release build
eas build --profile production --platform ios --local
eas build:list --limit 5                            # what has actually been built
eas build:configure                                 # (writes eas.json — do not run during an audit)
```

Read `eas.json` rather than trusting the profile name. The fields that decide whether a "production" profile is really a release build:

| field | release value | what a wrong value means |
|---|---|---|
| `distribution` | `store` (default) | `internal` produces an ad-hoc / internal-track artifact, not a store one |
| `ios.buildConfiguration` | `Release` (default) | `Debug` ships an unoptimized, unminified binary with dev tooling in it |
| `android.buildType` | `app-bundle` (default) | `apk` cannot be uploaded to Play as a release |
| `android.gradleCommand` | `:app:bundleRelease` | `:app:assembleDebug` is a debug build with the debug signing key |
| `developmentClient` | absent/false | `true` builds a dev client, which is never a store artifact |
| `channel` | the channel you publish OTA updates to | a mismatch means updates are published and never applied (MOB-003) |
| `env` | production values | see "env vars" — this is where a preview profile inherits production secrets |
| `autoIncrement` | `true` or a per-platform setting | otherwise `versionCode`/`buildNumber` must be bumped by hand (MOB-012) |

`eas submit --profile production` uploads; `submit.<profile>` in `eas.json` holds the App Store Connect and Play service-account references. The Play service-account JSON path in `submit.production.android.serviceAccountKeyPath` points at a credential file that must not be committed (SEC-001).

**Signing credentials are on EAS servers by default**, not in the repo: `eas credentials` lists them, and that is where the iOS distribution certificate, provisioning profile, and the Android upload keystore live unless the project opted into local credentials with `credentialsSource: "local"` and a `credentials.json`. That file, and any `*.keystore` or `*.p12` beside it, must be gitignored (MOB-013, SEC-001). A managed Expo project whose keystore exists only on EAS is a **pass** for backup as long as somebody has confirmed access to the EAS account — `eas credentials` can export it — but say that out loud, because "Expo has it" is a single point of failure nobody wrote down.

Local builds without EAS: `npx expo run:ios --configuration Release` and `npx expo run:android --variant release`, both of which prebuild first.

**Producing a JS bundle for MOB-011** without a native build:

```bash
npx expo export --platform ios --output-dir .pre-launch/mobile/export
grep -rniE 'sk_live|sk_test|service_role|BEGIN [A-Z ]*PRIVATE KEY|postgres://|mongodb\+srv://' .pre-launch/mobile/export | cut -c1-160
```

`expo export` also writes to the project's `.expo/` cache, which is normal tooling behaviour and already gitignored; the rule is only that the audit's own output goes under `.pre-launch/mobile/`. Always pass `--output-dir` explicitly — the default is `dist/` in the project root, which is a project file this audit must not create.

If a build artifact already exists, prefer it, because it proves what actually ships:

```bash
unzip -o <app>.apk -d .pre-launch/mobile/apk
strings .pre-launch/mobile/apk/assets/index.android.bundle | grep -niE '<the patterns above>'
cat .pre-launch/mobile/apk/res/values/strings.xml
```

Bundle size for MOB-017 comes from the export directory or the artifact, not from `node_modules`. Note whether the Android build produces an `.aab` (Play requires it) and what the download size estimate is; Play's console shows the post-split figure, which is smaller than the `.aab`.

## env vars
Three layers, and only the first is genuinely secret:

1. **EAS build-time env** — `build.<profile>.env` in `eas.json` (plaintext, committed) and EAS environment variables managed with `eas env:create` / `eas env:list`, which have a visibility of `plaintext`, `sensitive`, or `secret` and an environment of `production`, `preview`, or `development`. A `secret` variable is available to the build but not readable back. **These exist at build time, not at run time** — there is no server process to read them later, so whatever the JS references gets inlined into the bundle.
2. **`EXPO_PUBLIC_*`** — read from `.env` files by Metro and **inlined into the JS bundle at build time**. `process.env.EXPO_PUBLIC_API_URL` becomes a string literal in the shipped bundle. This is public by construction; a secret behind that prefix is SEC-003, and it is the single most common mobile secret leak.
3. **`expo.extra`** in the app config, readable at runtime via `expo-constants` (`Constants.expoConfig.extra`). This is shipped in the manifest and in the bundle. Same rule: public.

```bash
grep -rn 'EXPO_PUBLIC_' .env* app.config.* app.json src app 2>/dev/null
npx expo config --type public | head -80          # the whole public surface, resolved
grep -rn 'process\.env\.' app.config.js app.config.ts 2>/dev/null
```

**There is no server side on a mobile client.** Anything the app can read, a user with the artifact can read. Publishable identifiers are expected and pass — a Stripe `pk_`, a Supabase anon key (with RLS actually enforced, DAT-002), a RevenueCat public SDK key, the Firebase config in `google-services.json` / `GoogleService-Info.plist`. What fails is anything named `SECRET`, `SERVICE_ROLE`, `PRIVATE`, `ADMIN`, `WEBHOOK`, or `PASSWORD`, any `sk_` key, any database URL, and any third-party key that can do more than a client should (SEC-003, MOB-011). List the ones you cleared so the finding is not read as a false alarm.

The correct shape for a secret an app genuinely needs is: the app calls your backend, the backend holds the key. If a third-party call must happen from the device, it needs a scoped, revocable, per-user token minted server-side — not a shared API key.

`.env` files: Expo's CLI loads `.env`, `.env.local`, `.env.<mode>`, `.env.<mode>.local` with the usual precedence. `.env.local` must be gitignored. Note that EAS Build does **not** upload your local `.env` files unless they are committed (they should not be) — the build gets `eas.json` `env` plus EAS environment variables, which is why a value that works locally and is missing in the build is such a common failure.

Test-mode payment detection: read `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` for the `pk_test_` prefix, the RevenueCat key against its dashboard project, and for store billing the **store account** rather than a key (see revenuecat.md's "runtime probe hints" — a sandbox tester is the tell, not a prefix).

## routes and handlers
There is no HTTP surface here; the equivalents are **screens**, **deep links**, and **the client calls the app makes to its backend**.

**Screens.** With `expo-router`, files under `app/` map to paths exactly like a web router: `app/(tabs)/index.tsx`, `app/settings.tsx`, `app/[id].tsx`, with `app/_layout.tsx` as the root layout and `app/+not-found.tsx` as the fallback. Route groups `app/(auth)/**` are the usual marker for a protected area. With React Navigation, the screen list is the `Stack.Screen` / `Tab.Screen` entries in the navigator, plus a `linking` config object that maps URLs to screens.

```bash
find app src/app -name '*.tsx' -not -name '_*' 2>/dev/null   # expo-router screens
grep -rn 'Stack.Screen\|Tab.Screen\|linking\s*[:=]' src app 2>/dev/null
```

**Deep links (MOB-008, MOB-018).** Three mechanisms, and a launchable app usually has all three:

- **Custom scheme** — `expo.scheme` in the app config (`"myapp"` → `myapp://path`). Always works, never verified, so anything can claim it. Never treat a scheme link as authenticated.
- **iOS universal links** — `expo.ios.associatedDomains: ["applinks:example.com"]`, which Expo turns into the `com.apple.developer.associated-domains` entitlement. Apple fetches `https://example.com/.well-known/apple-app-site-association` (no redirects, `content-type: application/json`, served over HTTPS, no `.json` extension needed).
- **Android app links** — `expo.android.intentFilters` entries with `"autoVerify": true` and a `data` block naming the scheme `https` and the host. Android fetches `https://example.com/.well-known/assetlinks.json`, which must list the package name and the **SHA-256 fingerprint of the signing key that actually signs the uploaded artifact** — with Play App Signing that is Play's key, not your upload key, and using the upload fingerprint is the classic reason verification silently fails.

```bash
curl -sS -L -o /dev/null -w '%{http_code} %{content_type} %{num_redirects}\n' https://example.com/.well-known/apple-app-site-association
curl -sS https://example.com/.well-known/assetlinks.json | python3 -m json.tool
```

`expo-linking`'s `Linking.createURL()` and the `useURL()` / `addEventListener('url')` handlers are where an incoming link is consumed; `expo-router` handles it automatically from the path. **The handler is the auth boundary** (MOB-018): a link that navigates straight to `app/(app)/orders/[id].tsx` must still resolve a session before rendering, because a deep link bypasses whatever the tab bar was guarding.

**Backend calls.** Grep for the base URL and the fetch layer — `EXPO_PUBLIC_API_URL`, an axios instance in `lib/api.ts` / `src/api/`, a TanStack Query client, tRPC, or a Supabase/Firebase client in `lib/supabase.ts`. That list is the app's real attack surface and is what the SEC and DAT domains actually audit; the server side of it lives in the backend framework's stack file.

## auth
Session lives on the device, and where it is stored is the check.

**Storage.** `expo-secure-store` (`SecureStore.setItemAsync`) is the correct home for a token: Keychain on iOS, EncryptedSharedPreferences-backed Keystore on Android. `@react-native-async-storage/async-storage` is **not** encrypted — it is a plaintext SQLite/plist file readable on a jailbroken or rooted device and included in unencrypted device backups. A refresh token, session JWT, or API key in AsyncStorage is the finding (SEC-002 for the session handling, MOB-011 for what ends up extractable). `react-native-mmkv` with an `encryptionKey` is acceptable; without one it is AsyncStorage with better performance.

```bash
grep -rn 'SecureStore\|AsyncStorage\|MMKV\|Keychain' src app lib 2>/dev/null
```

`expo-secure-store` has a small value-size limit (kilobytes, not megabytes) — a large session blob gets chunked or silently falls back in some wrappers, so check what a Supabase or Auth0 adapter is actually doing.

**Providers.** Supabase with a `SecureStore` storage adapter passed to `createClient({ auth: { storage } })` (and `detectSessionInUrl: false` on native) is the common shape; Clerk via `@clerk/clerk-expo` with `tokenCache` backed by SecureStore; Firebase Auth via `@react-native-firebase/auth` or the JS SDK with `getReactNativePersistence`; Auth0 via `react-native-auth0`. A hand-rolled login posting to your own `/api/login` and storing the returned token is equally common and equally fine, provided the token goes to SecureStore.

**OAuth.** `expo-auth-session` with `expo-web-browser` opens the system browser (`ASWebAuthenticationSession` / Custom Tabs) and returns via the redirect URI. Two things to check: the redirect URI registered in each provider's dashboard must match what `AuthSession.makeRedirectUri()` produces for the **production** build (HYG-001 — the Expo proxy URL used in development is not the production one, and shipping with the proxy is a real launch bug), and PKCE must be on, which `expo-auth-session` does by default but a hand-rolled flow may not.

**Biometrics.** `expo-local-authentication` gates a screen locally. It is a UX lock, not an authorization boundary — the token is still in SecureStore and the server still decides. Do not report a biometric prompt as satisfying a server-side auth check.

**Sign in with Apple (MOB-023).** `expo-apple-authentication`, plus `expo.ios.usesAppleSignIn: true` in the app config so the entitlement is generated. If the app offers Google, Facebook, or another social login on iOS, Apple's guideline requires this one alongside — check both the dependency and the button.

## webhook handlers
Not applicable for this stack. A mobile client receives no webhooks; it receives **push messages** (see "background jobs") and **deep links** (see "routes and handlers"), and neither is a webhook.

The webhooks that matter to a paid mobile app land on your **server**: Apple's App Store Server Notifications V2 (a signed JWS posted to a URL configured in App Store Connect), Google Play's Real-time Developer Notifications (delivered via Pub/Sub, not HTTP), or RevenueCat's webhook if the app uses it. All three are audited against the backend framework's stack file and revenuecat.md, not here.

## webhook verification snippet
Not applicable for this stack. The verification the client does perform is receipt/entitlement validation, and the rule is that it must not be local: an entitlement recomputed from `Purchases.getCustomerInfo()`, from a server-validated receipt, or from your own backend is correct; one read from an `AsyncStorage` boolean survives no reinstall and is trivially edited (MOB-001).

## data access
Whatever client the app embeds, plus the device's own storage — and both are public surfaces.

**Remote.** A Supabase client with the anon key means Row Level Security is the *only* thing between a user and every row in every table, because the key ships in the binary (DAT-002; supabase.md has the RLS probe). A Firebase client means Firestore/RTDB/Storage security rules are the whole boundary (firebase.md). A REST or tRPC client against your own backend means the backend's authorization is the boundary and this file has nothing to add. Whichever it is, name it explicitly — a lot of mobile apps are audited as if they had a server-side data layer they do not have.

**Local.** `expo-sqlite`, `expo-file-system` (`FileSystem.documentDirectory` is app-private but is included in device backups unless excluded), AsyncStorage, MMKV. Cached personal data on device is in scope for the compliance domain (COMP-016 for retention) and for MOB-011 if a credential is in it. `expo-secure-store` is the only one of these that is encrypted at rest by the OS.

**Offline (MOB-015).** Look for `@react-native-community/netinfo`, a TanStack Query persister, a WatermelonDB/Realm sync layer, or a hand-rolled queue. The failure to look for is not "no offline mode" — that is a legitimate choice — but an app that shows an infinite spinner instead of an error when the request fails.

## file uploads
`expo-image-picker` (needs `NSPhotoLibraryUsageDescription`, and `NSCameraUsageDescription` for the camera), `expo-document-picker`, `expo-camera`, `expo-media-library` (a broader permission than the picker, and one that often gets requested when the picker would do — MOB-007). The upload itself is `FileSystem.uploadAsync`, a `fetch` with `FormData`, or a direct-to-storage call (Supabase Storage, S3 presigned PUT, Vercel Blob).

Two things to check: the request goes to a presigned URL or an authenticated endpoint that validates type and size server-side (a client-side size check is advisory only), and the resulting object is not world-readable unless it is meant to be (DAT-005). Cellular uploads of large media without a size guard are also a PERF-016 concern on a phone.

## background jobs
There is no cron on a device. What exists:

- **Push notifications** — `expo-notifications`. Permission is requested with `Notifications.requestPermissionsAsync()`; the token comes from `getExpoPushTokenAsync()` (Expo's push service) or `getDevicePushTokenAsync()` (the raw APNs/FCM token). **Both require a real device** — the iOS simulator cannot register for remote push. Delivery needs credentials configured: an APNs key on EAS (`eas credentials`) and `google-services.json` with FCM V1 configured for Android. For MOB-009 the three things are: the permission is requested at a moment the user understands rather than on first launch; `POST_NOTIFICATIONS` is declared and requested at runtime on Android 13+ (API 33 made it a runtime permission); and the token is re-registered on change (`addPushTokenListener`) and cleared on logout, or the next person to use the device gets the previous user's notifications.
- **Background execution** — `expo-background-fetch` / `expo-background-task` with `expo-task-manager`, and `expo-location` background updates. iOS schedules these at its own discretion, so nothing time-critical can live here; both need background modes declared in `expo.ios.infoPlist.UIBackgroundModes` and the corresponding Android permissions.
- **Everything real** — runs on your server. Scheduled work, email, billing reconciliation, and cleanup are the backend's, and the deploy platform's stack file (vercel.md, netlify.md, cloudflare.md, fly.md) owns the cron mechanism and SEC-014's secret.

**OTA updates (MOB-003).** `expo-updates` plus an `expo.updates` block (`url`, `fallbackToCacheTimeout`, `checkAutomatically`) and `expo.runtimeVersion`. EAS Update publishes with `eas update --branch <branch>`; branches map to **channels**, and channels are bound to build profiles by `eas.json`'s `build.<profile>.channel`. The four ways this breaks:

1. The production build's `channel` does not match the branch you publish to — updates go out and the installed app never sees them. `eas channel:list` and `eas update:list` show the truth.
2. `runtimeVersion` policy. `"appVersion"` invalidates every published update on each `expo.version` bump; `"fingerprint"` (or a manual string) tracks the native layer instead. A mismatch between the binary's runtime version and the update's means the update is skipped silently, with no error anywhere the user or you can see.
3. `checkAutomatically: "ON_ERROR_RECOVERY"` or `"NEVER"` means the update is only fetched in cases the team probably did not intend; the default `"ON_LOAD"` fetches on launch and applies on the *next* launch, so a hotfix is one restart behind.
4. Store rules. JS-only updates are permitted by both stores; an OTA that changes the app's purpose, adds features that were not reviewed, or introduces a new purchase mechanism is not. Say this out loud when the mechanism exists, because it is the part teams discover during an incident.

A project with no OTA mechanism at all is a **pass** for MOB-003, recorded as `no OTA path — every fix requires a store release`, with the latency stated so the trade is deliberate. REL-011 owns whether that latency is acceptable.

**Force update (MOB-012).** No built-in mechanism. Look for a version check against a remote value (a `/config` endpoint, Firebase Remote Config, an `expo-updates` manifest field) that renders a blocking screen. Confirm the version and build number were actually bumped for this release — `expo.version` plus `ios.buildNumber` / `android.versionCode`, or `eas.json` `autoIncrement`.

## error handling and logging
**Crash reporting (REL-001).** `@sentry/react-native` is the usual choice; on Expo it is installed with `npx expo install @sentry/react-native` and wired through the `@sentry/react-native/expo` config plugin, which is what uploads source maps during an EAS build so a stack trace is readable rather than a list of minified frames. Check three things: `Sentry.init` runs at the top of the app entry (`app/_layout.tsx` for expo-router, `App.tsx` otherwise) and not inside a component; the DSN is present in the production build (a DSN is public by design and belongs in `EXPO_PUBLIC_SENTRY_DSN` or the plugin options); and source-map upload is configured with an auth token supplied as an EAS secret rather than committed. Alternatives: `@react-native-firebase/crashlytics`, Bugsnag, or the store consoles' own crash reporting — Xcode Organizer and Play Console Vitals, which cost nothing and are the fallback when nothing else is installed. "Nothing installed and nobody has looked at Play Vitals" is the common answer and is the finding.

Native crashes and JS errors are different populations: a JS error caught by a React error boundary never reaches a native crash reporter, and an unhandled JS rejection may only surface as a red screen in development and silence in production. Check that the reporter is initialized for both halves, and that `Sentry.init` includes `enableNative`.

**Console output.** `console.log` in a release build goes nowhere useful — there is no log stream to read — so logging is either the crash reporter's breadcrumbs or nothing. Grep for `console.log` calls that pass tokens, request bodies, or user records; in a release build they are dead weight, but on a rooted device or through `adb logcat` they are readable (REL-015).

**User-facing errors.** A native crash is an instant, silent app termination; the user sees the home screen. That makes an error boundary (`react-error-boundary`, expo-router's `ErrorBoundary` export in a layout) and a graceful offline state the only thing standing between a failed request and an app that appears broken (MOB-015). Check that errors from the API are surfaced as text and not as a thrown render.

## security headers
Not applicable in the HTTP sense — an app serves no responses. The transport-security equivalents, which MOB-010 and MOB-019 audit, are:

**iOS App Transport Security.** `expo.ios.infoPlist.NSAppTransportSecurity` (managed) or `Info.plist` (bare). ATS is on by default and requires HTTPS. `NSAllowsArbitraryLoads: true` disables it globally and is a fail; `NSExceptionDomains` with a named `localhost` or dev host is the acceptable narrow form, and even that should not ship. `NSAllowsLocalNetworking` is fine. Anything permitting arbitrary loads in a store build is MOB-010.

**Android cleartext.** `expo.android.usesCleartextTraffic: true` sets `android:usesCleartextTraffic="true"` on the application tag and permits plain HTTP app-wide — a fail in a release build. The narrow form is a network security config XML with a `<domain-config cleartextTrafficPermitted="true">` limited to a dev host, referenced from `android:networkSecurityConfig`. From API 28 onward cleartext is off by default, so the presence of an explicit `true` is deliberate and worth quoting.

**Certificate pinning (MOB-019).** Not on by default and not required; the check wants a *documented decision*. If pinning is in use (`react-native-ssl-pinning`, a `network_security_config.xml` `<pin-set>`, `expo-build-properties`' iOS settings, or a Cloudflare/Firebase App Check equivalent), confirm there is a backup pin and a pin expiry, because a pinned app with one certificate bricks itself on renewal and only a store release fixes it.

**WebViews.** `react-native-webview` rendering remote or user content inherits the whole web threat model. `originWhitelist={['*']}`, `javaScriptEnabled` with `injectedJavaScript` interpolating user data, and `allowFileAccessFromFileURLs` are the ones to flag (SEC-043 for the injection half).

## known traps
- A secret behind `EXPO_PUBLIC_` or under `expo.extra`: SEC-003, and MOB-011 once it is in the bundle. There is no server side to hide it behind.
- An `eas.json` `preview` or `development` profile whose `env` block carries production values: DAT-017 in the mobile shape — an internal build reaching the production database.
- Session tokens in `AsyncStorage` instead of `expo-secure-store`: SEC-002, and MOB-011 for what a device dump yields.
- **Play target API level (MOB-022).** As of the August 2026 deadline, new apps and updates must target API 36 (Android 16); the floor rises each August — confirm in Play Console. On a managed project the effective value is whatever the Expo SDK pins unless `expo-build-properties` overrides it, which means raising the target usually means upgrading Expo. Record `compileSdk` and `minSdk` alongside it, and name the behaviour changes the gap crosses: API 33 makes `POST_NOTIFICATIONS` a runtime permission, 34 requires a declared foreground-service type and tightens implicit intents, and 35 makes edge-to-edge display mandatory, which visibly breaks layouts that assumed system-bar insets.
- No `ios.privacyManifests` in the app config and no `PrivacyInfo.xcprivacy` in a bare project: MOB-020. Expo generates the file from that config key, so on a managed project the config *is* the manifest. The SDK half is the harder one — vendored pods that predate manifest support (older Firebase, Facebook, AppsFlyer, Adjust, Sentry builds) will fail App Store validation, and Apple's list of SDKs and required-reason APIs grows, so read the current one and mark the finding `verify current rules`.
- IDFA-reading or attribution SDKs present with no `expo-tracking-transparency` and no `NSUserTrackingUsageDescription`: MOB-021. The prompt must precede any tracking-identifier access, and `requestTrackingPermissionsAsync()` must actually be awaited before the SDK initializes — calling it after `AppsFlyer.initSdk()` is the ordering bug that passes code review and fails review. Answer it consistently with the App Privacy answers MOB-004 checks and the manifest's `NSPrivacyTracking` flag.
- A permission in `android.permissions` or a `NS*UsageDescription` in `ios.infoPlist` for a feature the app does not have: MOB-007. Expo's config plugins add permissions implicitly — installing `expo-camera` adds the camera permission whether or not you use it — so the manifest is often broader than the code. `expo.android.blockedPermissions` removes them.
- A purpose string that says "This app needs camera access": MOB-007 again, and a routine rejection. It must say what for.
- `expo.scheme` deep links treated as trusted, or a link routing into an authenticated screen without a session check: MOB-018.
- `associatedDomains` set but the AASA file returning 404, a redirect, or `text/plain`: MOB-008. Same for `assetlinks.json` carrying the upload-key fingerprint instead of the Play App Signing fingerprint.
- The production build profile bound to a different EAS Update channel than the branch being published: MOB-003 — updates ship into a void.
- `runtimeVersion: "appVersion"` with a version bump between the binary and the update: MOB-003, silent.
- `NSAllowsArbitraryLoads: true` or `usesCleartextTraffic: true` in a store build: MOB-010.
- A `credentials.json`, `*.keystore`, `*.p12`, or a Play service-account JSON committed to the repo: SEC-001, and MOB-013 for the other half — an upload key that exists only on one laptop and nowhere else.
- No restore-purchases path, or one recomputing entitlement from a local flag: MOB-001. Reinstalling clears the flag and the user has paid for nothing.
- Account deletion absent or reachable only by emailing support: MOB-005. Both stores require it to be initiated in-app for any app with account creation, and Apple wants it discoverable rather than buried.
- No review demo account for an app behind a login wall: MOB-014 — the single most common cause of a first-submission rejection.
- Measuring launch time, bundle size, or crash rate against a dev client: MOB-017 is a release-build measurement. See "dev server".
- Testing purchases on Expo Go: impossible, because the billing native module is not in it. Record the runtime half as unrun with the reason rather than as a fail (MOB-001).
- Running `npx expo prebuild` or `npx expo run:ios` on a managed project during an audit: it writes `ios/` and `android/` into the repo. This audit does not modify project files.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if already in devDependencies; never install one for the audit. Cited by the accessibility and compliance domain headers, COMP-007, and FLOW-018. Mobile runtime work uses the simulator and `xcrun`/`adb`, not a browser driver.

## runtime probe hints
**Which client can run what.** Establish this before planning any runtime probe, because it decides what is even possible:

| target | custom native modules | push tokens | in-app purchases | how to start |
|---|---|---|---|---|
| Expo Go | no | Expo push only, device only | no | `npx expo start --go` |
| Dev build (simulator) | yes | no (simulator cannot register) | StoreKit config file on iOS only | `eas build --profile development`, then `npx expo start --dev-client` |
| Dev build (device) | yes | yes | yes, with a sandbox tester | same, installed on the device |
| Release build | yes | yes | yes | `eas build --profile production` |

Where no simulator, device, or sandbox tester is available, the mobile checks downgrade rather than stop: run the static entry, record `verified_by: static-fallback`, and name exactly what was missing.

**Simulators and emulators.**
```bash
xcrun simctl list devices available            # iOS simulators
xcrun simctl boot "iPhone 16"                  # or open -a Simulator
xcrun simctl uninstall booted <bundle id>      # destroy local state for the restore test
adb devices                                    # Android emulator/device
adb shell pm list packages | grep <package>
adb uninstall <package>
adb logcat --pid=$(adb shell pidof -s <package>)
```

**Reaching the app's own API from a device.** `localhost` on a phone is the phone. Point the app at the machine's LAN address (`ipconfig getifaddr en0` on macOS) and start the backend bound to `0.0.0.0`, not `127.0.0.1`. The Android emulator reaches the host at `10.0.2.2`; the iOS simulator shares the host's network stack and `localhost` works there. If the API is HTTPS-only, an ATS exception or a tunnel (`ngrok http 3000`, `cloudflared tunnel`) is needed — and note in evidence if a probe required loosening ATS, since that configuration must not be the one that ships (MOB-010).

**Purchases are sandbox-only, always.** iOS: an App Store Connect sandbox tester signed in under Settings → App Store → Sandbox Account, or a StoreKit configuration file in Xcode for a purely local simulation. Android: a Play licence tester with the app on an internal or closed track. Never sign in with a real Apple ID or Google account that has a payment method. The restore sequence MOB-001 wants: buy the cheapest product in sandbox, confirm the entitlement is active, uninstall (`xcrun simctl uninstall` / `adb uninstall`), reinstall, tap Restore, and confirm the entitlement returns with no second purchase. The call names to look for are `Purchases.restorePurchases` (RevenueCat), `getAvailablePurchases` (react-native-iap), and `restoreCompletedTransactions` (StoreKit directly). If only live billing credentials are present, do not purchase: verify the restore path statically, record `error: live billing credentials detected`, and leave the runtime half unrun.

**Deep links.**
```bash
xcrun simctl openurl booted "myapp://orders/123"
xcrun simctl openurl booted "https://example.com/orders/123"      # universal link
adb shell am start -W -a android.intent.action.VIEW -d "myapp://orders/123" <package>
adb shell pm get-app-links <package>                              # verification state per host
```
`pm get-app-links` is the definitive Android answer for MOB-008: it prints `verified`, `legacy_failure`, or `1024` per host. On iOS there is no equivalent command; test by tapping the link from Notes or Messages (Safari's address bar will not trigger a universal link), and remember that a device caches its AASA fetch, so reinstalling the app is how you force a re-check.

**Push.** `getExpoPushTokenAsync()` needs a device and a `projectId`. Send a test with:
```bash
curl -sS -X POST https://exp.host/--/api/v2/push/send -H 'content-type: application/json' \
  -d '{"to":"ExponentPushToken[...]","title":"probe","body":"probe"}'
```
Confirm the token is cleared on logout by logging out and re-reading the stored token.

**Reading platform files.** A built `Info.plist` inside an artifact is binary and will not grep:
```bash
plutil -p ios/<App>/Info.plist
python3 -c "import plistlib,sys;print(plistlib.load(open(sys.argv[1],'rb')))" <path>
npx expo config --type prebuild | python3 -m json.tool | head -100   # what a managed project would generate
```

**Release-build measurements (MOB-017).** App size from the `.aab`/`.ipa` or from `eas build:list`; launch time from a release build on a mid-range device, not a simulator on an M-series Mac; crash-free rate from Sentry, Play Console Vitals, or Xcode Organizer — and if the app has never shipped, the honest answer is that there is no crash-free rate yet, and the finding is whether the reporting is wired up to produce one.

**Never** point a probe at production billing keys, never publish an EAS Update during an audit, never run `eas build` against the production profile just to look at something, and delete any sandbox purchases and test accounts the audit created.
