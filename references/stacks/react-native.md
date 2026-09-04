# React Native (bare)

## detection signals
`react-native` in `package.json` dependencies **without** `expo` (or with `expo` present only as a library dependency rather than as the framework — check for `app.json`/`app.config.*` with an `expo` key, which means expo.md is the right file). Committed `ios/` and `android/` directories are the defining signal: the native projects are on disk and are the source of truth. Supporting signals: `metro.config.js`, `react-native.config.js`, `ios/Podfile` and `ios/Podfile.lock`, `android/settings.gradle`, `android/gradle.properties`, and a `jest.config.js` with `preset: 'react-native'`.

New Architecture (Fabric/TurboModules) is signalled by `newArchEnabled=true` in `android/gradle.properties` and `RCT_NEW_ARCH_ENABLED=1` in the iOS build settings or `Podfile`; note it, because it changes which third-party native modules work.

Where every platform value lives — unlike a managed Expo project, all of it is a real file:

| value | file |
|---|---|
| iOS usage strings, ATS, URL schemes | `ios/<App>/Info.plist` |
| iOS entitlements (associated domains, push, Sign in with Apple) | `ios/<App>/<App>.entitlements` |
| iOS build config, signing, deployment target | `ios/<App>.xcodeproj/project.pbxproj`, `ios/<App>.xcworkspace` |
| CocoaPods dependencies | `ios/Podfile`, `ios/Podfile.lock`, `ios/Pods/` |
| Android permissions, intent filters, cleartext, app tag | `android/app/src/main/AndroidManifest.xml` (plus `src/debug/` and `src/release/` variants, which are merged) |
| `targetSdkVersion`, `compileSdkVersion`, `minSdkVersion`, `versionCode`, `versionName` | `android/app/build.gradle`, often via an `ext` block in the root `android/build.gradle` or `android/gradle.properties` |
| signing configs | `android/app/build.gradle` `signingConfigs`, with values usually from `android/gradle.properties` or `~/.gradle/gradle.properties` |
| network security config | `android/app/src/main/res/xml/network_security_config.xml`, referenced from the manifest |
| iOS privacy manifest | `ios/<App>/PrivacyInfo.xcprivacy` (must be added to the target's Copy Bundle Resources) |
| Firebase config | `ios/<App>/GoogleService-Info.plist`, `android/app/google-services.json` |

**Manifest merging is real and is a common source of confusion.** `android/app/src/main/AndroidManifest.xml` is merged with `src/debug/AndroidManifest.xml`, `src/release/`, and with every library's manifest. A permission you cannot find in the main manifest may still ship because a dependency declared it. The merged result is at `android/app/build/intermediates/merged_manifests/release/AndroidManifest.xml` after a release build, and Android Studio's Merged Manifest view shows the same thing with provenance. Read the merged file when one exists rather than only the source (MOB-007).

## dev server
`npx react-native start` (Metro, default port 8081, `--port` to change) — or `npm start` / `yarn start`, whichever the `scripts` block wires up.

Build and install locally:
```bash
npx react-native run-ios                      # default simulator, Debug configuration
npx react-native run-ios --simulator "iPhone 16"
npx react-native run-ios --configuration Release
npx react-native run-android                  # Debug variant
npx react-native run-android --mode release   # (older CLI versions: --variant release)
```

`run-ios` and `run-android` require the native toolchains — Xcode with a simulator runtime, Android Studio with an SDK and an AVD — and `cd ios && pod install` must have been run at least once. If `ios/Pods/` is absent, `run-ios` will fail; running `pod install` writes into the project, so on an audit prefer reading `Podfile.lock` (which is committed) over installing.

Debug builds load JS from Metro over the network. That is why the debug binary must never be what gets measured or submitted: it is unminified, carries the dev menu, the LogBox overlay, and a network dependency on your laptop, and it is signed with the debug key. Every performance and size figure MOB-017 wants comes from a release build ("build").

Reaching your own API from a device or emulator is the same trap as on any mobile stack — see "runtime probe hints".

## build
**iOS release.** Either through Xcode (Product → Archive on the `Release` scheme, then Distribute App) or from the CLI:
```bash
# do not run during an audit — invokes release signing / writes ios/build; see MOB-011 for the profile build
cd ios && xcodebuild -workspace <App>.xcworkspace -scheme <App> -configuration Release \
  -archivePath build/<App>.xcarchive archive
xcodebuild -exportArchive -archivePath build/<App>.xcarchive -exportOptionsPlist ExportOptions.plist -exportPath build/
```
For MOB-010 the question is whether the artifact the user is about to submit came from the `Release` configuration with the distribution signing identity — not from `Debug`, and not from an ad-hoc profile. `xcodebuild -showBuildSettings -scheme <App> -configuration Release | grep -E 'CONFIGURATION|CODE_SIGN|PROVISIONING'` answers it without building.

**Android release.**
```bash
# do not run during an audit — invokes release signing / writes android/app/build; see MOB-011 for the profile build
cd android && ./gradlew bundleRelease      # .aab for Play — this is the submittable artifact
cd android && ./gradlew assembleRelease    # .apk, for sideloading and for inspection
```
Output lands in `android/app/build/outputs/bundle/release/` and `.../apk/release/`. Play requires the `.aab`.

**The signing trap that decides whether the release build is real.** React Native's template ships a `debug` signing config, and `android/app/build.gradle` frequently contains:
```groovy
buildTypes {
    release {
        signingConfig signingConfigs.debug   // <- template default, ships a debug-signed build
    }
}
```
A release variant wired to `signingConfigs.debug` produces an artifact Play will reject and that cannot be updated later by the real key. Read the `signingConfigs` and `buildTypes` blocks and quote them (MOB-010, MOB-013). The correct shape reads the keystore path, alias, and passwords from `gradle.properties` (ideally `~/.gradle/gradle.properties`, outside the repo) or from environment variables.

**Keystore (MOB-013, SEC-001).** `android/app/*.keystore` or `*.jks` must be gitignored, and `git log --all --oneline -- 'android/app/*.keystore'` should return nothing — a keystore that was ever committed is compromised and, unlike a leaked API key, cannot be rotated without Play's key-reset process. The passwords in `android/gradle.properties` are the same problem; check whether that file is committed. On the iOS side the equivalents are `*.p12`, `*.mobileprovision`, and the App Store Connect API key `AuthKey_*.p8`.

The other half of MOB-013 is backup: with Play App Signing enabled, Google holds the app signing key and losing the *upload* key is recoverable; without it, losing the keystore ends the app's ability to ship updates permanently. Establish which is in use — Play Console shows it — and confirm the keystore and its passwords are somewhere other than one developer's laptop.

**Producing a JS bundle for MOB-011** without a native build:
```bash
mkdir -p .pre-launch/mobile/export
npx react-native bundle --entry-file index.js --platform ios --dev false \
  --bundle-output .pre-launch/mobile/export/main.jsbundle --sourcemap-output .pre-launch/mobile/export/main.jsbundle.map
grep -aniE 'sk_live|sk_test|service_role|BEGIN [A-Z ]*PRIVATE KEY|postgres://|mongodb\+srv://' .pre-launch/mobile/export/main.jsbundle | cut -c1-160
```
`--dev false` is what applies the production transform and minifier; without it you are grepping a development bundle and the result does not represent what ships. Always pass `--bundle-output` explicitly — the audit's output goes under `.pre-launch/mobile/`, never into the project.

If an artifact already exists, prefer it:
```bash
unzip -o <app>.apk -d .pre-launch/mobile/apk
strings .pre-launch/mobile/apk/assets/index.android.bundle | grep -niE '<the patterns above>'
cat .pre-launch/mobile/apk/res/values/strings.xml            # Firebase keys and build-injected strings land here
unzip -o <app>.ipa -d .pre-launch/mobile/ipa
strings .pre-launch/mobile/ipa/Payload/<App>.app/<App> | grep -niE '<the patterns above>'
strings .pre-launch/mobile/ipa/Payload/<App>.app/main.jsbundle | grep -niE '<the patterns above>'
```
Redact matches in evidence to the first six characters.

**Hermes** is the default JS engine in current versions. It compiles the bundle to bytecode, so `strings` over `index.android.bundle` yields less than it would from plain JavaScript — string literals survive, but the surrounding code does not, and a hit is still a hit. `npx hermes-engine ... ` or `hbcdump` can disassemble it if needed; usually the `strings` pass is enough because credentials are string literals by nature. Note in evidence whether Hermes was in use, because "the grep found nothing" means less on a Hermes bundle than on a plain one.

**Source maps.** `--sourcemap-output` above, and the Sentry/Bugsnag Gradle and Xcode build-phase plugins that upload them. Confirm maps are uploaded and then **not shipped inside the artifact** — a `.map` file in `assets/` is a full deobfuscated copy of the app's source (SEC-007).

## env vars
There is no framework-provided env layer in bare React Native. Whatever exists was added, and there are three common shapes — all of which end up **inside the binary**:

1. **`react-native-config`** — reads a `.env` file at *build time* and generates `BuildConfig` fields on Android and a `Config` class on iOS, plus a `Config` object importable from JS. Values land in `res/values/strings.xml` (grep-able from any APK) and in the compiled binary. The `.env` file is selected by `ENVFILE=.env.production` at build time.
2. **`react-native-dotenv`** (a Babel plugin) — inlines `process.env.X` into the JS bundle at transform time, exactly like a web bundler. Nothing is looked up at runtime.
3. **Xcode build settings / Gradle `buildConfigField`** — values written into `Info.plist` via `$(VARIABLE)` substitution or into `BuildConfig` by Gradle. Same outcome.

```bash
grep -rn 'react-native-config\|react-native-dotenv\|@env' --include='*.js' --include='*.ts' --include='*.tsx' src App.tsx 2>/dev/null
ls -a .env*
grep -rn 'buildConfigField\|resValue' android/app/build.gradle
grep -rn 'ENVFILE' package.json android ios fastlane 2>/dev/null
```

**Every one of these is public.** There is no server side on a device: the binary is a file a user can download, unzip, and read. Publishable identifiers are expected and pass — a Stripe `pk_`, a Supabase anon key (with RLS actually enforced, DAT-002), a RevenueCat public SDK key, the Firebase config in `google-services.json` / `GoogleService-Info.plist`. What fails is anything named `SECRET`, `SERVICE_ROLE`, `PRIVATE`, `ADMIN`, `WEBHOOK`, or `PASSWORD`, any `sk_` key, any database URL, and any third-party key that can do more than a client should (SEC-003, MOB-011). List what you cleared so the finding reads as deliberate rather than as a false alarm.

The correct shape for a secret the app genuinely needs is: the app calls your backend and the backend holds the key. Where a third-party call must originate on the device, it needs a scoped, revocable, per-user token minted server-side.

`.env` files must be gitignored, and `.env` under `react-native-config` is loaded at build time — so a CI build without the right `ENVFILE` produces a binary with empty or stale values, which is a launch failure that only shows up on device. Check what CI passes.

Test-mode payment detection: read the publishable key literal out of the bundle or `.env` for a `pk_test_` prefix. For store billing there is no key prefix at all — a sandbox tester account is the tell (revenuecat.md's "runtime probe hints").

## routes and handlers
No HTTP surface. The equivalents are **screens**, **deep links**, and **the calls the app makes outward**.

**Screens.** React Navigation is near-universal in bare projects: the screen inventory is the `Stack.Screen` / `Tab.Screen` / `Drawer.Screen` entries in the navigator tree, usually under `src/navigation/`, plus a `linking` config that maps URLs onto them.
```bash
grep -rn '\.Screen\b\|createNativeStackNavigator\|createBottomTabNavigator\|linking\s*[:=]' src App.tsx 2>/dev/null
```
The authenticated area is normally a conditional in the root navigator (`user ? <AppStack/> : <AuthStack/>`). That conditional is a *rendering* decision, not an authorization one — see MOB-018 below.

**Deep links (MOB-008, MOB-018).** Three mechanisms:

- **Custom scheme** — `CFBundleURLTypes` in `Info.plist` on iOS, and an `<intent-filter>` with `<data android:scheme="myapp"/>` in the manifest. Unverified: any app can register the same scheme, so a scheme link is never evidence of anything.
- **iOS universal links** — `com.apple.developer.associated-domains` in `ios/<App>/<App>.entitlements`, with an `applinks:example.com` entry. Apple fetches `https://example.com/.well-known/apple-app-site-association`: HTTPS, no redirects, `content-type: application/json`, no extension.
- **Android app links** — an `<intent-filter android:autoVerify="true">` with `<data android:scheme="https" android:host="example.com"/>`. Android fetches `https://example.com/.well-known/assetlinks.json`, which must carry the package name and the **SHA-256 fingerprint of the key that actually signs the uploaded artifact** — with Play App Signing that is Google's key from the Play Console, not your upload key. Using the upload fingerprint is why verification silently fails on a real release while working on a locally signed build.

```bash
grep -n 'associated-domains' -A5 ios/*/*.entitlements
grep -n 'autoVerify\|android:scheme\|android:host' android/app/src/main/AndroidManifest.xml
curl -sS -L -o /dev/null -w '%{http_code} %{content_type} %{num_redirects}\n' https://example.com/.well-known/apple-app-site-association
curl -sS https://example.com/.well-known/assetlinks.json | python3 -m json.tool
```

`Linking.getInitialURL()` and `Linking.addEventListener('url', ...)` are where a link is consumed, or React Navigation's `linking` config does it. **That handler is the auth boundary** (MOB-018): a deep link jumps straight to a screen, bypassing the navigator conditional that was standing in for a guard, so the screen itself must resolve a session and the data it fetches must be authorized server-side.

**Outward calls.** The fetch layer — an axios instance, a `fetch` wrapper, TanStack Query, tRPC, Apollo, or a Supabase/Firebase client — usually under `src/api/`, `src/services/`, or `src/lib/`. That list is the app's real surface; the server side of each call belongs to the backend's stack file.

## auth
Session lives on the device.

**Storage.** `react-native-keychain` (`Keychain.setGenericPassword`) is the correct home for a token — Keychain on iOS, Keystore-backed on Android — as is `expo-secure-store` where the Expo modules are installed into a bare project. `@react-native-async-storage/async-storage` is **not encrypted**: it is a plaintext file readable on a jailbroken or rooted device and, on iOS, included in unencrypted iTunes/Finder backups. A refresh token, session JWT, or API key in AsyncStorage is the finding (SEC-002, and MOB-011 for what a device dump yields). `react-native-mmkv` with an `encryptionKey` is acceptable; without one it is AsyncStorage with better performance. `react-native-encrypted-storage` is a thin wrapper over the platform stores and is fine.

```bash
grep -rn 'Keychain\|AsyncStorage\|EncryptedStorage\|MMKV\|SecureStore' src 2>/dev/null
```

**Providers.** Supabase with a Keychain/SecureStore storage adapter passed to `createClient`; `@react-native-firebase/auth`; `react-native-auth0`; Clerk's React Native SDK with a `tokenCache`; or a hand-rolled login posting to your own endpoint. All are fine provided the token goes somewhere encrypted.

**OAuth.** `react-native-app-auth` (AppAuth, which uses `ASWebAuthenticationSession` / Chrome Custom Tabs and does PKCE properly) is the right shape. A WebView-based OAuth flow is not: it is against most providers' policies, it hides the URL bar from the user, and it makes credential phishing indistinguishable from the real thing. The redirect URI registered in each provider's dashboard must match the production scheme and be listed there (HYG-001).

**Biometrics.** `react-native-biometrics` or `react-native-keychain`'s `accessControl` options gate a screen or gate reading the Keychain item. The second is real (the OS refuses to hand over the secret); the first is a UX lock only. Either way the server still decides authorization — do not report a biometric prompt as satisfying a server-side check.

**Sign in with Apple (MOB-023).** `@invertase/react-native-apple-authentication` plus the `com.apple.developer.applesignin` entitlement. If the app offers Google, Facebook, or another social login on iOS, Apple's guideline requires this one alongside; check for both the dependency and a rendered button, not just one.

## webhook handlers
Not applicable for this stack. A mobile client receives no webhooks. What it receives is **push messages** (see "background jobs") and **deep links** (see "routes and handlers"), and neither is a webhook — in particular, a push payload is not authenticated to the app and must never be trusted as a source of entitlement or state; it is a signal to go and fetch.

The webhooks that matter to a paid app land on your **server**: Apple's App Store Server Notifications V2 (a signed JWS), Google Play's Real-time Developer Notifications (via Pub/Sub), or RevenueCat's webhook. Those are audited against the backend framework's stack file and revenuecat.md.

## webhook verification snippet
Not applicable for this stack. The client-side equivalent worth stating is that entitlement must be recomputed from an authoritative source — a store receipt validated server-side, `Purchases.getCustomerInfo()`, or your own backend — and never from a local boolean, which a reinstall clears and a rooted device edits (MOB-001).

## data access
Whatever client the app embeds, plus the device's own storage. Both are public surfaces.

**Remote.** A Supabase client with the anon key means Row Level Security is the *entire* boundary, because the key is in the binary (DAT-002; supabase.md carries the RLS probe). A Firebase client means Firestore/RTDB/Storage rules are the entire boundary (firebase.md). A REST/GraphQL/tRPC client against your own backend means the backend's authorization is the boundary and this file adds nothing. Say which it is explicitly — bare React Native apps are frequently audited as though they had a server-side data layer they do not have.

**Local.** `react-native-sqlite-storage` / `op-sqlite`, WatermelonDB, Realm, `react-native-fs`, AsyncStorage, MMKV. Personal data cached on device is in scope for COMP-016 (retention) and for MOB-011 if a credential sits in it. Realm supports encryption with an `encryptionKey`; SQLite does not unless SQLCipher is in use. None of these are encrypted by default.

**Offline (MOB-015).** `@react-native-community/netinfo`, a query persister, or a hand-rolled mutation queue. The failure to look for is not the absence of offline support — that is a legitimate product choice — but an app that shows an indefinite spinner instead of an error when the request fails, and a mutation queue that replays without idempotency keys and so duplicates the write.

## file uploads
`react-native-image-picker`, `react-native-document-picker`, `react-native-vision-camera`, or `@react-native-camera-roll/camera-roll`. Each pulls in permissions: `NSPhotoLibraryUsageDescription`, `NSCameraUsageDescription`, `NSMicrophoneUsageDescription` on iOS; `READ_MEDIA_IMAGES` / `READ_MEDIA_VIDEO` (API 33+, replacing `READ_EXTERNAL_STORAGE`) and `CAMERA` on Android. Requesting the broad media permission when the system picker would need none is MOB-007's classic over-request, and on Android 34+ the photo picker is the preferred path precisely because it needs no permission at all.

The upload is a `fetch` with `FormData`, `react-native-blob-util`, or a direct-to-storage PUT against a presigned URL. Two things to check: it goes to a presigned URL or an authenticated endpoint that validates content type and size **server-side** (a client-side size check is advisory), and the resulting object is not world-readable unless intended (DAT-005). Large uploads over cellular without a size guard are also a PERF-016 concern.

## background jobs
There is no cron on a device.

- **Push notifications** — `@react-native-firebase/messaging` (FCM, both platforms) or `@react-native-community/push-notification-ios` / `notifee` for local and display concerns. iOS needs the `aps-environment` entitlement (`development` in debug, `production` in a release build — shipping with `development` means push silently never arrives, which is MOB-009's quietest failure), an APNs key or certificate uploaded wherever the sender lives, and `UIBackgroundModes` containing `remote-notification` for silent pushes. Android needs `google-services.json` and, from API 33, the `POST_NOTIFICATIONS` runtime permission — declared in the manifest **and** requested at runtime; declaring it alone shows no prompt and delivers no notifications. For MOB-009 also check the permission is requested at a moment the user understands rather than on first launch, that `onTokenRefresh` re-registers the token, and that the token is deleted on logout or the next user of the device inherits the previous one's notifications.
- **Background execution** — `react-native-background-fetch`, `react-native-background-actions`, `WorkManager` via a native module on Android, `BGTaskScheduler` on iOS with `BGTaskSchedulerPermittedIdentifiers` in `Info.plist`. iOS schedules these when it feels like it, so nothing time-critical belongs here. Android 34 requires a declared `foregroundServiceType` on every foreground service.
- **Everything real** runs on your server. Scheduled work, email, billing reconciliation, and cleanup are the backend's, and the deploy platform's stack file (vercel.md, netlify.md, cloudflare.md, fly.md) owns the cron mechanism and SEC-014's shared secret.

**OTA updates (MOB-003).** `react-native-code-push` (Microsoft's CodePush, historically via App Center — note that App Center's shutdown pushed teams to self-hosted CodePush servers or to alternatives, so confirm what the deployment key actually points at before treating the mechanism as live). The things that break it: the deployment key baked into the binary (`CodePushDeploymentKey` in `Info.plist`, `android:value` under `CodePushDeploymentKey` in the manifest, or `codePush.deploymentKey` in JS) must be the **Production** deployment key in a release build and the **Staging** one in a preview build — the two are swapped often enough that it is worth quoting the value's source; `checkFrequency` decides whether an update is even fetched; `mandatoryInstallMode` decides whether a critical fix waits for the next cold start; and a `targetBinaryVersion` mismatch means the release is published and applied to nobody. `appcenter codepush deployment history <app> Production` (or the self-hosted equivalent) is how you see what has actually gone out.

A project with no OTA mechanism at all is a **pass** for MOB-003, recorded as `no OTA path — every fix requires a store release`, with the latency stated so the trade is deliberate. REL-011 owns whether that latency is acceptable.

**Force update (MOB-012).** Nothing built in. Look for a version check against a remote value (a `/config` endpoint, Firebase Remote Config, `react-native-version-check`) that renders a blocking screen. Then confirm the version and build number were bumped for this release: `versionName`/`versionCode` in `android/app/build.gradle` and `CFBundleShortVersionString`/`CFBundleVersion` in `Info.plist` — Play refuses a duplicate `versionCode` and App Store Connect refuses a duplicate `CFBundleVersion`, so this one usually fails loudly, but a `versionName` that never moves while `versionCode` increments leaves users unable to say which build they have.

## error handling and logging
**Crash reporting (REL-001).** `@sentry/react-native` or `@react-native-firebase/crashlytics`. Both need native initialization as well as JS: Sentry's iOS half runs from `AppDelegate` (or from `Sentry.init` with `enableNative`) and its Android half from a Gradle plugin, and Crashlytics needs the `com.google.firebase.crashlytics` Gradle plugin plus the pod. A JS-only initialization catches JS errors and misses every native crash, which on React Native is a large fraction of them — check both halves are wired, because "Sentry is installed" is usually asserted from `package.json` alone.

Source maps are what make a stack trace readable rather than a list of minified frames. The Sentry Xcode build phase and Gradle plugin upload them during a release build; confirm the upload runs in CI (an auth token from an environment variable, never committed) and that the maps do not then ship inside the artifact (SEC-007).

Fall back to the store consoles when nothing is installed: Xcode Organizer for iOS crashes and Play Console Vitals for Android. They cost nothing and are always available. "Nothing installed and nobody has looked at Vitals" is the common answer and is the finding.

**Console output.** In a release build `console.log` goes to the native log — `adb logcat` on Android, the device console on iOS — which is readable by anyone with the device attached, and to nowhere you can query. Grep the call sites for tokens, request bodies, and user records (REL-015). `babel-plugin-transform-remove-console` in the production Babel config strips them; note whether it is present.

**User-facing errors.** A native crash terminates the app instantly and silently; the user is returned to the home screen with no message. That makes an error boundary (`react-error-boundary`, or a class component with `componentDidCatch`) and a real offline state the only thing between a failed request and an app that appears broken (MOB-015). LogBox and the red screen exist only in debug, so a rendering error that shows a helpful overlay in development shows a blank screen in production.

## security headers
Not applicable in the HTTP sense — the app serves no responses. The transport-security equivalents, which MOB-010 and MOB-019 audit:

**iOS App Transport Security.** `NSAppTransportSecurity` in `ios/<App>/Info.plist`. ATS is on by default and requires HTTPS with TLS 1.2+. `NSAllowsArbitraryLoads: true` disables it app-wide and is a fail in a store build; the acceptable narrow form is an `NSExceptionDomains` entry for a specific dev host, and even that should not ship. `NSAllowsLocalNetworking` is benign. React Native's own template historically added an ATS exception for `localhost` so Metro could load over HTTP — check whether that exception is still there and whether it is scoped to `localhost` only, because a broadened version of it is one of the most common findings on a bare project.

```bash
plutil -p ios/<App>/Info.plist | grep -A20 NSAppTransportSecurity
```

**Android cleartext.** `android:usesCleartextTraffic="true"` on the `<application>` tag permits plain HTTP app-wide and is a fail in a release build. From API 28 cleartext is off by default, so an explicit `true` is a deliberate act. The narrow form is `android:networkSecurityConfig="@xml/network_security_config"` with a `<domain-config cleartextTrafficPermitted="true">` limited to a dev host — and note that `src/debug/AndroidManifest.xml` is the right place for a dev-only override, since it does not merge into the release variant.

```bash
grep -n 'usesCleartextTraffic\|networkSecurityConfig' android/app/src/main/AndroidManifest.xml android/app/src/*/AndroidManifest.xml
cat android/app/src/main/res/xml/network_security_config.xml 2>/dev/null
```

**Certificate pinning (MOB-019).** Not on by default and not required; the check wants a *documented decision*. If pinning is in use — `react-native-ssl-pinning`, `react-native-cert-pinner`, a `<pin-set>` in the network security config, or a native `URLSessionDelegate` — confirm there is a backup pin and an expiry, because a pinned app with a single certificate bricks itself on renewal and only a store release fixes it. A `<pin-set>` with an `expiration` attribute that has already passed silently disables pinning, which is the failure mode nobody notices.

**WebViews.** `react-native-webview` rendering remote or user-supplied content inherits the whole web threat model. Flag `originWhitelist={['*']}`, `injectedJavaScript` interpolating user data, `allowFileAccessFromFileURLs`, `allowUniversalAccessFromFileURLs`, and `mixedContentMode="always"` (SEC-043 for the injection half).

## known traps
- `android/app/build.gradle` wiring `release { signingConfig signingConfigs.debug }`: MOB-010 — the "release" build is debug-signed and cannot be shipped or updated by the real key. This is the template default, so assume it until you have read the file.
- A `*.keystore`, `*.jks`, `*.p12`, `*.mobileprovision`, or `AuthKey_*.p8` committed, or keystore passwords in a committed `android/gradle.properties`: SEC-001. Check `git log --all` as well as the working tree; a keystore that was ever committed cannot be rotated the way a key can (MOB-013).
- The upload keystore existing only on one laptop, with Play App Signing off: MOB-013 — losing it ends the app's ability to ship updates permanently.
- A secret in `.env` under `react-native-config`, or inlined by `react-native-dotenv`: SEC-003, and MOB-011 once it is in `strings.xml` or the bundle. There is no server side on a device.
- Grepping a `--dev true` bundle and concluding the app is clean: MOB-011 needs `--dev false`, and on Hermes the bytecode hides code but not string literals — say which you inspected.
- **Play target API level (MOB-022).** As of the August 2026 deadline, new apps and updates must target API 36 (Android 16); the floor rises each August — confirm in Play Console. Read `targetSdkVersion`/`targetSdk` from `android/app/build.gradle`, an `ext` block in the root `build.gradle`, or `gradle.properties`, and record `compileSdk` (must be at least as high) and `minSdk` alongside. Name the behaviour changes the gap crosses: API 33 makes `POST_NOTIFICATIONS` a runtime permission, 34 requires a declared foreground-service type and tightens implicit intents, and 35 makes edge-to-edge display mandatory, which visibly breaks layouts written against system-bar insets.
- No `PrivacyInfo.xcprivacy` in `ios/<App>/`, or one present but not added to the target's Copy Bundle Resources so it never ships: MOB-020. The SDK half fails more often than yours — `find ios/Pods -name PrivacyInfo.xcprivacy` and compare against the pods list; older Firebase, Facebook, AppsFlyer, Adjust, and Sentry builds predate manifest support. Apple's lists of required-reason APIs and manifest-requiring SDKs grow, so read the current one and mark the finding `verify current rules`.
- An attribution or IDFA-reading SDK with no ATT prompt and no `NSUserTrackingUsageDescription`: MOB-021. `requestTrackingAuthorization` must be awaited **before** the SDK initializes — calling it afterwards is the ordering bug that passes code review and fails App Review. Keep the answer consistent with MOB-004's App Privacy answers and the privacy manifest's `NSPrivacyTracking` flag.
- A permission in the *merged* manifest that the app does not use: MOB-007. Libraries contribute permissions you never wrote; read `android/app/build/intermediates/merged_manifests/release/AndroidManifest.xml` when it exists, and use `tools:node="remove"` to strip one. Same check on iOS for a `NS*UsageDescription` whose feature was removed — a leftover usage string prompts App Review to ask what it is for.
- A purpose string that says "This app needs camera access": MOB-007, and a routine rejection. It must say what for.
- `NSAllowsArbitraryLoads: true` or `usesCleartextTraffic="true"` in the release variant: MOB-010. A `localhost` exception in the debug manifest is fine; the same exception in `src/main/` is not.
- A universal link entitlement present but the AASA returning 404, a redirect, or `text/plain`, or `assetlinks.json` carrying the upload-key SHA-256 instead of the Play App Signing one: MOB-008. `adb shell pm get-app-links <package>` is the definitive Android answer.
- A deep link routing into an authenticated screen without a session check, on the assumption that the navigator conditional was a guard: MOB-018.
- Session tokens in AsyncStorage rather than Keychain/Keystore: SEC-002, and MOB-011 for a device dump.
- OAuth in a `WebView` rather than `ASWebAuthenticationSession`/Custom Tabs via `react-native-app-auth`: against most providers' policies and indistinguishable from phishing. The redirect URIs must also be registered for the production scheme (HYG-001).
- A release build shipping with the `development` APNs entitlement: MOB-009 — push silently never arrives in production.
- `POST_NOTIFICATIONS` declared in the manifest but never requested at runtime on Android 13+: MOB-009 — no prompt, no notifications, no error.
- A CodePush deployment key pointing at Staging in the release binary, or at an App Center deployment that no longer exists: MOB-003.
- Measuring launch time, size, or crash rate against a debug build loading from Metro: MOB-017 wants release-build numbers.
- No restore-purchases path, or entitlement recomputed from a local flag: MOB-001.
- Account deletion absent or reachable only by emailing support: MOB-005 — both stores require it to be initiated in-app for any app with account creation.
- No review demo account for an app behind a login wall: MOB-014, the most common first-submission rejection.
- Running `pod install`, `./gradlew`, or a build that writes into `ios/` and `android/` when only a read was needed: this audit does not modify project files. Read `Podfile.lock` and the Gradle files instead, and where a build is genuinely required for MOB-011, use a profile/debug-signed variant and say so.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if already in devDependencies; never install one for the audit. Cited by the accessibility and compliance domain headers, COMP-007, and FLOW-018. Mobile runtime work uses the simulator and `xcrun`/`adb` instead.

## runtime probe hints
**Simulators, emulators, devices.**
```bash
xcrun simctl list devices available
xcrun simctl boot "iPhone 16"                     # or: open -a Simulator
xcrun simctl uninstall booted <bundle id>         # destroy local state for the restore test
xcrun simctl get_app_container booted <bundle id> data   # inspect the app's sandbox
adb devices
adb shell pm list packages | grep <package>
adb uninstall <package>
adb logcat --pid=$(adb shell pidof -s <package>)
adb shell dumpsys package <package> | grep -A20 'requested permissions'
```
`dumpsys package` is the fastest way to see the *effective* permission set on an installed build, which is the merged manifest's answer rather than the source file's (MOB-007).

**Running the app.** `npx react-native run-ios` and `npx react-native run-android` for debug; append `--configuration Release` / `--mode release` for the honest build. Release on a simulator still needs a signing identity on iOS; if none is available, record the runtime half as unrun rather than as a fail. Where no simulator, device, or sandbox tester is available at all, the mobile checks downgrade: run the static entry, record `verified_by: static-fallback`, and name exactly what was missing.

**Reaching the app's own API from a device.** `localhost` on a phone is the phone. Bind the backend to `0.0.0.0` (not `127.0.0.1`) and point the app at the machine's LAN address — `ipconfig getifaddr en0` on macOS. The Android emulator reaches the host at `10.0.2.2`; the iOS simulator shares the host's network stack, so `localhost` works there and only there. `adb reverse tcp:3000 tcp:3000` forwards a host port to a connected Android device, which is cleaner than a LAN address when the device is on USB. If the API is HTTPS-only, a tunnel (`ngrok http 3000`, `cloudflared tunnel`) avoids loosening ATS — and if a probe did require an ATS or cleartext exception, say so in evidence, because that configuration must not be the one that ships (MOB-010).

**Purchases are sandbox-only, always.** iOS: an App Store Connect sandbox tester signed in under Settings → App Store → Sandbox Account, or a StoreKit configuration file in Xcode for a fully local simulation (fastest, and it can accelerate renewals). Android: a Play licence tester with the app on an internal or closed track. Never sign in with a real Apple ID or Google account carrying a payment method. MOB-001's sequence: buy the cheapest sandbox product, confirm the entitlement is active, uninstall (`xcrun simctl uninstall` / `adb uninstall`), reinstall, tap Restore, and confirm the entitlement returns without a second purchase. The call names to look for are `getAvailablePurchases` (react-native-iap), `Purchases.restorePurchases` (RevenueCat), `queryPurchases` (Play Billing), and `restoreCompletedTransactions` (StoreKit). If only live billing credentials are present, do not purchase: verify the path statically, record `error: live billing credentials detected`, and leave the runtime half unrun.

**Deep links.**
```bash
xcrun simctl openurl booted "myapp://orders/123"
xcrun simctl openurl booted "https://example.com/orders/123"
adb shell am start -W -a android.intent.action.VIEW -d "myapp://orders/123" <package>
adb shell pm get-app-links <package>          # prints verified | legacy_failure | <error code> per host
adb shell pm verify-app-links --re-verify <package>
```
On iOS there is no equivalent verification command: test by tapping the link from Notes or Messages, since typing it into Safari's address bar will not trigger a universal link, and remember the device caches its AASA fetch — reinstalling forces a re-check.

**Reading platform files.** A built `Info.plist` inside an artifact is binary and will not grep:
```bash
plutil -p ios/<App>/Info.plist
plutil -p .pre-launch/mobile/ipa/Payload/<App>.app/Info.plist
python3 -c "import plistlib,sys;print(plistlib.load(open(sys.argv[1],'rb')))" <path>
unzip -p <app>.apk AndroidManifest.xml | strings | head -50    # binary XML; aapt2 dump badging is better if present
```

**Release-build measurements (MOB-017).** App size from the `.aab`/`.apk`/`.ipa` on disk (and Play Console's download-size estimate, which is smaller than the `.aab` because of splits); launch time from a release build on a mid-range physical device, never from a simulator on an M-series Mac; crash-free rate from Sentry, Crashlytics, Play Console Vitals, or Xcode Organizer — and if the app has never shipped, the honest answer is that there is no crash-free rate yet, and the finding is whether the reporting is wired up to produce one.

**Never** point a probe at production billing keys, never invoke the release signing key for an audit build, never publish a CodePush release during an audit, and delete any sandbox purchases and test accounts the audit created.
