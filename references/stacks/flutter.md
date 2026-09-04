# Flutter

## detection signals
`pubspec.yaml` at the repo root with an `environment: sdk:` constraint and a `flutter:` section, plus `lib/main.dart`. `pubspec.lock` is committed for an application (and should be — it is the reproducible-build guarantee, and its absence is worth a line under REL-013). `analysis_options.yaml` with `include: package:flutter_lints/flutter.yaml`. Platform directories `ios/`, `android/`, and possibly `web/`, `macos/`, `windows/`, `linux/`. `.dart_tool/` and `build/` are generated and gitignored.

The Flutter SDK version comes from `environment: flutter:` in `pubspec.yaml`, from an `.fvmrc` / `.fvm/` directory (FVM pinning), or from a `.tool-versions` line. Note it — Dart and Flutter both move fast and a project two majors behind is a REL-013 finding on its own.

Unlike React Native, **Dart compiles ahead of time to a native library**. There is no JavaScript bundle, which changes what MOB-011 can look at: on Android the compiled Dart lives in `lib/<abi>/libapp.so` inside the APK, and on iOS inside `Frameworks/App.framework/App`. String literals survive compilation; the code around them does not.

Where every platform value lives — all of it is a real file, as in a bare React Native project:

| value | file |
|---|---|
| iOS usage strings, ATS, URL schemes | `ios/Runner/Info.plist` |
| iOS entitlements (associated domains, push, Sign in with Apple) | `ios/Runner/Runner.entitlements` |
| iOS build config and signing | `ios/Runner.xcodeproj/project.pbxproj`, `ios/Runner.xcworkspace`, `ios/Flutter/*.xcconfig` |
| CocoaPods dependencies | `ios/Podfile`, `ios/Podfile.lock`, `ios/Pods/` |
| Android permissions, intent filters, cleartext | `android/app/src/main/AndroidManifest.xml` (plus `src/debug/` and `src/profile/` variants, which are merged per build type) |
| `targetSdk`, `compileSdk`, `minSdk`, `versionCode`, `versionName` | `android/app/build.gradle` or `android/app/build.gradle.kts` |
| signing configs | `android/app/build.gradle` `signingConfigs`, usually reading `android/key.properties` |
| network security config | `android/app/src/main/res/xml/network_security_config.xml` |
| iOS privacy manifest | `ios/Runner/PrivacyInfo.xcprivacy` (must be in the Runner target's Copy Bundle Resources) |
| Firebase config | `ios/Runner/GoogleService-Info.plist`, `android/app/google-services.json`, and `lib/firebase_options.dart` if FlutterFire CLI generated it |
| app version | `version: 1.2.3+45` in `pubspec.yaml` — the part before `+` is `versionName`/`CFBundleShortVersionString`, after `+` is `versionCode`/`CFBundleVersion` |

That last row is the one people miss: the Android and iOS version fields are **generated from `pubspec.yaml`** by default, via `$(FLUTTER_BUILD_NAME)` / `$(FLUTTER_BUILD_NUMBER)` in `Info.plist` and `flutterVersionName` / `flutterVersionCode` in `build.gradle`. So MOB-012's version bump is a one-line change in `pubspec.yaml` unless someone has hardcoded the native fields, which is worth checking for because a hardcoded value silently stops tracking.

**Manifest merging applies here too.** A permission you cannot find in `android/app/src/main/AndroidManifest.xml` may still ship because a plugin declared it — and Flutter plugins do this constantly. The merged result is at `android/app/build/intermediates/merged_manifests/release/AndroidManifest.xml` after a release build; read it when it exists (MOB-007).

## dev server
`flutter run` — debug mode, with hot reload, attached to a connected device or simulator.

```bash
flutter devices                       # what is attachable right now
flutter run                           # debug on the default device
flutter run -d <device id>
flutter run --release                 # release mode locally (no hot reload, no debug tooling)
flutter run --profile                 # AOT-compiled with tracing left in — the mode for performance work
flutter run --dart-define=API_URL=https://example.com
flutter doctor -v                     # toolchain state; run this first when anything fails
```

The three build modes are not interchangeable and choosing the wrong one invalidates the measurement:

- **debug** — JIT, with the observatory/DevTools service, assertions on, and a much larger and slower binary. Never measure size, startup, or frame timing here, and never ship it (MOB-017).
- **profile** — AOT-compiled like release, with tracing and DevTools still attached. This is the mode for performance measurement, and — importantly for MOB-011 — it produces a real `libapp.so` with the `--dart-define` constants baked in, while defaulting to the **debug** signing configuration so no release key is touched.
- **release** — AOT, tracing stripped, assertions off. What ships.

DevTools (`flutter run` prints its URL, or `dart devtools`) carries the performance overlay, the widget inspector, and the memory view; the frame-timing numbers PERF work wants come from a profile-mode run on a physical device, not from a simulator.

Reaching your own API from a device is the same trap as on any mobile stack — see "runtime probe hints".

## build
**Android.**
```bash
flutter build appbundle --release      # .aab — the submittable Play artifact
flutter build apk --release            # .apk, for sideloading and inspection
flutter build apk --release --split-per-abi
flutter build apk --profile            # AOT, debug-signed by default — the MOB-011 inspection build
```
Output lands under `build/app/outputs/bundle/release/` and `build/app/outputs/flutter-apk/`. Play requires the `.aab`.

**iOS.**
```bash
flutter build ipa --release            # produces build/ios/archive/Runner.xcarchive and, with an export options plist, an .ipa
flutter build ios --release --no-codesign
open ios/Runner.xcworkspace            # then Product → Archive for the interactive path
```

**The signing trap.** Flutter's Android template ships:
```groovy
buildTypes {
    release {
        signingConfig signingConfigs.debug   // TODO: Add your own signing config for the release build.
    }
}
```
That TODO is in the generated project and survives to production more often than anyone would like. A release variant wired to `signingConfigs.debug` produces an artifact Play rejects and that can never be updated by the real key (MOB-010, MOB-013). The correct shape reads `android/key.properties` — which must be gitignored — for `storeFile`, `storePassword`, `keyAlias`, and `keyPassword`. Quote the block you find.

**Keystore (MOB-013, SEC-001).** `android/key.properties` and any `*.jks` / `*.keystore` must be gitignored, and `git log --all --oneline -- android/key.properties 'android/**/*.jks'` should return nothing; a keystore that was ever committed is compromised and, unlike an API key, cannot simply be rotated. On the iOS side the equivalents are `*.p12`, `*.mobileprovision`, and `AuthKey_*.p8`. Then check the backup half: with Play App Signing on, Google holds the app signing key and losing the *upload* key is recoverable; without it, losing the keystore permanently ends the app's ability to ship updates. Establish which is in use and confirm the keystore lives somewhere other than one laptop.

**Inspecting the artifact for MOB-011.** There is no JavaScript bundle, so the only path is a built binary — and the build mode decides whether the check works at all:

```bash
flutter build apk --profile
mkdir -p .pre-launch/mobile/apk
cp build/app/outputs/flutter-apk/app-profile.apk .pre-launch/mobile/
unzip -o .pre-launch/mobile/app-profile.apk -d .pre-launch/mobile/apk
strings .pre-launch/mobile/apk/lib/*/libapp.so | grep -niE 'sk_live|sk_test|service_role|BEGIN [A-Z ]*PRIVATE KEY|postgres://|mongodb\+srv://|AIza[0-9A-Za-z_-]{20,}' | cut -c1-160
cat .pre-launch/mobile/apk/res/values/strings.xml
```

Use `--profile`, **not** `--debug`. A debug build is JIT: it ships the engine plus a kernel snapshot under `assets/flutter_assets/` with no AOT `libapp.so` to read, so the grep finds nothing and you would wrongly report the app clean. A profile build is AOT like release, bakes in the `--dart-define` constants you are hunting, and uses the debug signing configuration by default so no release key is touched. **Check that before running it:** if `android/app/build.gradle` wires the profile build type to the release signing config, stop — do not invoke the release key for an audit — and fall back to reading an existing release artifact the user provides, recording why you did not build.

Always copy the artifact out to `.pre-launch/mobile/` rather than unzipping in place; the audit's output never goes into the project tree, and `build/` is the project's.

For an existing IPA:
```bash
unzip -o <app>.ipa -d .pre-launch/mobile/ipa
strings .pre-launch/mobile/ipa/Payload/Runner.app/Frameworks/App.framework/App | grep -niE '<the patterns above>'
```
Redact matches in evidence to the first six characters.

**Obfuscation and symbols.** `flutter build apk --obfuscate --split-debug-info=build/symbols` renames Dart symbols and writes the mapping out of the binary. It makes `strings` output noisier but does **not** hide string literals — a hardcoded key is still a hardcoded key, so obfuscation is never an answer to MOB-011. It does mean crash reports arrive unreadable unless the symbol files are uploaded to the crash reporter (`sentry-cli debug-files upload`, `firebase crashlytics:symbols:upload`), which is a REL-001 half worth checking. The symbol directory must not ship inside the artifact (SEC-007).

**App size (MOB-017).** `flutter build apk --analyze-size --target-platform android-arm64` writes a size report readable in DevTools. Compare against the Play Console's download-size estimate, which is smaller than the `.aab` because of ABI and density splits.

## env vars
Flutter has **no runtime environment**. There is no `process.env` on a device, and `dotenv`-style packages do not change that — they read a file that was bundled as an asset, which means the file ships inside the artifact and is trivially extractable. The mechanisms, all of which are public:

1. **`--dart-define`** — compile-time constants read with `String.fromEnvironment('API_URL')` / `bool.fromEnvironment` / `int.fromEnvironment`. The value is **baked into the compiled binary** and appears in `strings libapp.so`. This is the idiomatic approach and it is correct for public configuration and wrong for secrets.
2. **`--dart-define-from-file=config.json`** — the same thing sourced from a JSON file. The file itself is usually gitignored while its values still end up in the binary; grep the build scripts, `Makefile`, `melos.yaml`, `fastlane/Fastfile`, and CI workflows to find which file a release build actually uses.
3. **`flutter_dotenv`** — loads a `.env` file that must be declared under `flutter: assets:` in `pubspec.yaml` to be readable at all. That declaration ships the raw `.env` file inside the app, where `unzip` finds it in one step. This is the worst of the three and worth flagging on sight.
4. **Native-side values** — `Info.plist` entries, `strings.xml`, `buildConfigField`, `google-services.json`, `GoogleService-Info.plist`.

```bash
grep -rn 'String.fromEnvironment\|bool.fromEnvironment\|int.fromEnvironment' lib
grep -rn 'dart-define' . --include='*.yaml' --include='*.sh' --include='Makefile' --include='Fastfile' --include='*.json' 2>/dev/null
grep -rn 'flutter_dotenv\|dotenv.load' lib pubspec.yaml
grep -n -A15 '^flutter:' pubspec.yaml            # the assets list — is a .env in it?
```

**Every one of these is public.** There is no server side on a device: the binary is a file a user can download, unzip, and read. Publishable identifiers are expected and pass — a Stripe `pk_`, a Supabase anon key (with RLS actually enforced, DAT-002), a RevenueCat public SDK key, the Firebase config in `firebase_options.dart` or the platform config files. What fails is anything named `SECRET`, `SERVICE_ROLE`, `PRIVATE`, `ADMIN`, `WEBHOOK`, or `PASSWORD`, any `sk_` key, any database URL, and any third-party key that can do more than a client should (SEC-003, MOB-011). List what you cleared so the finding is not read as a false alarm.

The correct shape for a secret the app genuinely needs is: the app calls your backend and the backend holds the key. Where a third-party call must originate on the device, it needs a scoped, revocable, per-user token minted server-side.

`--dart-define` values missing at build time silently become the `defaultValue` of `String.fromEnvironment` — usually an empty string — rather than failing the build. A release built by CI without the right defines produces an app that points at nothing, which is a launch failure only visible on device. Check what CI passes, and prefer `const apiUrl = String.fromEnvironment('API_URL', defaultValue: '')` guarded by an assertion at startup over a silent empty default.

Test-mode payment detection: read the publishable key literal out of `--dart-define` values or the source for a `pk_test_` prefix. For store billing there is no key prefix at all — a sandbox tester account is the tell (revenuecat.md's "runtime probe hints").

## routes and handlers
No HTTP surface. The equivalents are **routes/screens**, **deep links**, and **the calls the app makes outward**.

**Routes.** Either the built-in `Navigator` with a `routes:` map or `onGenerateRoute` in `MaterialApp`, or a router package — `go_router` (a `GoRouter(routes: [...])` with `GoRoute(path:)` entries and a `redirect` callback), `auto_route` (annotated pages, generated `*.gr.dart`), or `beamer`. The route table is the screen inventory.

```bash
grep -rn 'GoRoute\|onGenerateRoute\|routes:\s*{\|AutoRoute(' lib | head -40
```

`go_router`'s top-level `redirect` is the closest thing Flutter has to middleware and is usually where the authenticated-area guard lives. Read it: a redirect that checks a local `isLoggedIn` boolean is a UI convenience, not authorization — the server still has to decide (MOB-018).

**Deep links (MOB-008, MOB-018).** Three mechanisms:

- **Custom scheme** — `CFBundleURLTypes` in `ios/Runner/Info.plist`, and an `<intent-filter>` with `<data android:scheme="myapp"/>` in the Android manifest. Unverified: any app can claim the same scheme, so a scheme link is never evidence of anything.
- **iOS universal links** — `com.apple.developer.associated-domains` in `ios/Runner/Runner.entitlements` with an `applinks:example.com` entry. Apple fetches `https://example.com/.well-known/apple-app-site-association`: HTTPS, no redirects, `content-type: application/json`, no extension.
- **Android app links** — `<intent-filter android:autoVerify="true">` with `<data android:scheme="https" android:host="example.com"/>`. Android fetches `https://example.com/.well-known/assetlinks.json`, which must carry the package name and the **SHA-256 fingerprint of the key that actually signs the uploaded artifact** — with Play App Signing that is Google's key from the Play Console, not your upload key. Using the upload fingerprint is why verification silently fails on a real release while working on a locally signed build.

Flutter also has `flutter:deeplinking_enabled` in `Info.plist` and `flutter_deeplinking_enabled` as an Android meta-data flag, which hand incoming links to the Flutter router directly rather than to a plugin. Note which mechanism the project uses, because with the flag on, `app_links`/`uni_links` listeners may never fire.

```bash
grep -n 'associated-domains' -A5 ios/Runner/Runner.entitlements
grep -n 'autoVerify\|android:scheme\|android:host\|deeplinking' android/app/src/main/AndroidManifest.xml
grep -rn 'app_links\|uni_links\|getInitialLink\|uriLinkStream' lib
curl -sS -L -o /dev/null -w '%{http_code} %{content_type} %{num_redirects}\n' https://example.com/.well-known/apple-app-site-association
curl -sS https://example.com/.well-known/assetlinks.json | python3 -m json.tool
```

The link handler — `app_links`' `uriLinkStream`, `uni_links`' `getInitialLink`, or `go_router` receiving the path directly — **is the auth boundary** (MOB-018). A deep link jumps straight to a route, past whatever the shell was guarding, so the destination must resolve a session and the data it fetches must be authorized server-side.

**Outward calls.** `http`, `dio`, `chopper`, a generated OpenAPI client, `graphql_flutter`, or a `supabase_flutter` / `firebase_*` client — usually under `lib/services/`, `lib/data/`, `lib/api/`, or a `repository` layer. That list is the app's real surface; the server side of each call belongs to the backend's stack file.

## auth
Session lives on the device.

**Storage.** `flutter_secure_storage` is the correct home for a token: Keychain on iOS, and on Android either EncryptedSharedPreferences or a Keystore-wrapped preference file depending on the version and options. `shared_preferences` is **not** encrypted — it is a plist on iOS and an XML file on Android, readable on a jailbroken or rooted device and included in unencrypted backups. A refresh token, session JWT, or API key in `shared_preferences` is the finding (SEC-002, and MOB-011 for what a device dump yields). `hive` and `isar` are encrypted only when opened with an encryption key, and that key then has to live somewhere — usually `flutter_secure_storage`, which is the right answer.

```bash
grep -rn 'flutter_secure_storage\|SharedPreferences\|Hive.openBox\|shared_preferences' lib pubspec.yaml
```

Two `flutter_secure_storage` details worth checking on Android: `encryptedSharedPreferences: true` in `AndroidOptions` selects the stronger backend, and auto-backup can restore an old encrypted blob whose key no longer exists, producing a permanent read failure — projects usually fix that by setting `android:allowBackup="false"` or excluding the file, and either is worth noting since it also affects what leaves the device.

**Providers.** `supabase_flutter` (which by default persists the session via `shared_preferences` unless a `LocalStorage` implementation backed by secure storage is supplied — check this, it is a common quiet finding), `firebase_auth`, `auth0_flutter`, `flutter_appauth` for generic OIDC, or a hand-rolled login posting to your own endpoint.

**OAuth.** `flutter_appauth` or `flutter_web_auth_2` open the system browser (`ASWebAuthenticationSession` / Chrome Custom Tabs) and do PKCE. An OAuth flow inside a `webview_flutter` widget is not acceptable: it is against most providers' policies, hides the URL bar, and is indistinguishable from phishing. The redirect URIs registered in each provider's dashboard must match the production scheme (HYG-001).

**Biometrics.** `local_auth` gates a screen locally, and `flutter_secure_storage`'s iOS `accessibility`/access-control options can gate the Keychain read itself. The second is real; the first is a UX lock. Neither replaces server-side authorization — do not report a biometric prompt as satisfying an auth check.

**Sign in with Apple (MOB-023).** `sign_in_with_apple` plus the `com.apple.developer.applesignin` entitlement in `Runner.entitlements`. If the app offers Google, Facebook, or another social login on iOS, Apple's guideline requires this one alongside; check for the dependency and a rendered button, not just one of the two.

## webhook handlers
Not applicable for this stack. A mobile client receives no webhooks. What it receives is **push messages** (see "background jobs") and **deep links** (see "routes and handlers"), and neither is a webhook — in particular, a push payload is not authenticated to the app and must never be trusted as a source of entitlement or state; it is a signal to go and fetch.

The webhooks that matter to a paid app land on your **server**: Apple's App Store Server Notifications V2 (a signed JWS), Google Play's Real-time Developer Notifications (via Pub/Sub), or RevenueCat's webhook. Those are audited against the backend framework's stack file and revenuecat.md.

## webhook verification snippet
Not applicable for this stack. The client-side equivalent worth stating is that entitlement must be recomputed from an authoritative source — a store receipt validated server-side, `Purchases.getCustomerInfo()` from `purchases_flutter`, or your own backend — and never from a local boolean, which a reinstall clears and a rooted device edits (MOB-001).

## data access
Whatever client the app embeds, plus the device's own storage. Both are public surfaces.

**Remote.** `supabase_flutter` with the anon key means Row Level Security is the *entire* boundary, because the key is compiled into the binary (DAT-002; supabase.md carries the RLS probe). `cloud_firestore` / `firebase_database` / `firebase_storage` means the security rules are the entire boundary (firebase.md). A `dio`/`http` client against your own backend means the backend's authorization is the boundary and this file adds nothing. Say which it is explicitly.

**Local.** `sqflite`, `drift` (which generates SQL over sqflite), `hive`, `isar`, `objectbox`, `path_provider` plus raw files. None are encrypted by default; `sqflite_sqlcipher`, `drift` with SQLCipher, and `hive`/`isar` opened with an encryption key are the encrypted variants. Personal data cached on device is in scope for COMP-016 (retention) and for MOB-011 if a credential sits in it.

**Offline (MOB-015).** `connectivity_plus` for the network state, `drift`/`isar` as a local cache, or a hand-rolled mutation queue. Note that `connectivity_plus` reports the *interface* (wifi/cellular/none), not reachability — a device on a captive-portal wifi reports connected and every request fails, so an app that branches only on it will show the wrong state. The failure to look for is not the absence of offline support, which is a legitimate product choice, but an app that shows an indefinite spinner instead of an error, and a mutation queue that replays without idempotency keys and duplicates the write.

## file uploads
`image_picker` (needs `NSPhotoLibraryUsageDescription`, and `NSCameraUsageDescription` for the camera), `file_picker`, `camera`, `photo_manager` (a much broader permission than `image_picker`, and a common MOB-007 over-request). On Android 33+ the media permissions split into `READ_MEDIA_IMAGES` / `READ_MEDIA_VIDEO` / `READ_MEDIA_AUDIO`, replacing `READ_EXTERNAL_STORAGE`; on 34+ the system photo picker needs no permission at all, which is the preferred path. `permission_handler` is the usual runtime-request wrapper — and note that it declares a wide set of permissions in its own manifest unless the project uses its Gradle-flag mechanism to strip the unused ones, which is exactly the merged-manifest surprise MOB-007 catches.

The upload is a `dio` `FormData` post, `http.MultipartRequest`, or a direct-to-storage PUT against a presigned URL. Two things to check: it goes to a presigned URL or an authenticated endpoint that validates content type and size **server-side** (a client-side size check is advisory), and the resulting object is not world-readable unless intended (DAT-005). Large uploads over cellular without a size guard are also a PERF-016 concern.

## background jobs
There is no cron on a device.

- **Push notifications** — `firebase_messaging` (FCM, both platforms) with `flutter_local_notifications` for display, or `apns` directly on iOS. iOS needs the `aps-environment` entitlement (`development` in debug, `production` in a release build — shipping with `development` means push silently never arrives, MOB-009's quietest failure), an APNs key uploaded to Firebase, and `UIBackgroundModes` containing `remote-notification` for silent pushes. Android needs `google-services.json` and, from API 33, the `POST_NOTIFICATIONS` runtime permission, declared in the manifest **and** requested at runtime — declaring it alone shows no prompt and delivers nothing. For MOB-009 also check the permission is requested at a moment the user understands rather than on first launch, that `onTokenRefresh` re-registers, and that the token is deleted on logout (`FirebaseMessaging.instance.deleteToken()`) or the next user of the device inherits the previous one's notifications. Background message handlers must be top-level functions annotated `@pragma('vm:entry-point')`, or they are tree-shaken out of the release build and silently never run — a release-only failure that debug testing cannot find.
- **Background execution** — `workmanager`, `background_fetch`, `flutter_background_service`. iOS schedules these at its own discretion, so nothing time-critical belongs here; `BGTaskSchedulerPermittedIdentifiers` must be in `Info.plist`. Android 34 requires a declared `foregroundServiceType` on every foreground service.
- **Everything real** runs on your server. Scheduled work, email, billing reconciliation, and cleanup are the backend's, and the deploy platform's stack file (vercel.md, netlify.md, cloudflare.md, fly.md) owns the cron mechanism and SEC-014's shared secret.

**OTA updates (MOB-003).** Flutter has no first-party OTA mechanism, because the store rules that permit JavaScript hot-fixes were written for interpreted code and Dart AOT is not that. **Shorebird** (`shorebird_code_push`, a `shorebird.yaml` with an `app_id`, and `shorebird release` / `shorebird patch` replacing `flutter build`) is the established option: it patches the compiled Dart layer while leaving the native binary untouched. If it is in use, check that the release the patch targets is the release actually in the store (`shorebird releases list`, `shorebird patches list`), that `shorebird.yaml` is bundled as an asset (it must be listed under `flutter: assets:` or the client cannot find its app id), that the update check runs on launch, and that patches are limited to what the stores permit — a patch that changes the app's purpose or adds an unreviewed purchase mechanism is a violation regardless of the delivery mechanism. Firebase Remote Config is *not* an OTA mechanism; it changes values, not code, and should be recorded as configuration rather than as a hotfix path.

A project with no OTA mechanism at all is a **pass** for MOB-003, recorded as `no OTA path — every fix requires a store release`, with the latency stated so the trade is deliberate. REL-011 owns whether that latency is acceptable.

**Force update (MOB-012).** Nothing built in. Look for a version check against a remote value (a `/config` endpoint, Firebase Remote Config, `upgrader`, `in_app_update` on Android for Play's own flexible/immediate update flow) that renders a blocking screen. Then confirm the version was bumped: the `version: x.y.z+n` line in `pubspec.yaml` drives both platforms unless the native fields were hardcoded — grep `Info.plist` for `FLUTTER_BUILD_NAME` / `FLUTTER_BUILD_NUMBER` and `build.gradle` for `flutterVersionCode` to confirm the wiring is intact.

## error handling and logging
**Crash reporting (REL-001).** `firebase_crashlytics` or `sentry_flutter`. Both need three things wired, and a project usually has one or two of them:

```dart
// the shape both packages document
await SentryFlutter.init((o) { o.dsn = const String.fromEnvironment('SENTRY_DSN'); },
    appRunner: () => runApp(MyApp()));
// or, with Crashlytics
FlutterError.onError = FirebaseCrashlytics.instance.recordFlutterFatalError;
PlatformDispatcher.instance.onError = (e, s) {
  FirebaseCrashlytics.instance.recordError(e, s, fatal: true); return true;
};
```

1. `FlutterError.onError` — framework errors raised during build/layout/paint. Without it these print to the console and vanish.
2. `PlatformDispatcher.instance.onError` (or a `runZonedGuarded` wrapper on older versions) — uncaught asynchronous errors, which is where most production failures actually live.
3. Native crashes — Crashlytics' and Sentry's platform SDKs, wired by their Gradle plugin and pod. A Dart-only setup misses every engine and plugin crash.

Then check symbol upload, which is what makes a report readable: with `--obfuscate --split-debug-info` the Dart symbols leave the binary, and `sentry-cli debug-files upload` or `firebase crashlytics:symbols:upload` must run in the release pipeline. Without it, every crash arrives as unresolved addresses and the reporter is technically installed and practically useless.

Fall back to the store consoles when nothing is installed: Xcode Organizer for iOS and Play Console Vitals for Android. "Nothing installed and nobody has looked at Vitals" is the common answer and is the finding.

**Console output.** `print` and `debugPrint` write to the native log — `adb logcat` on Android, the device console on iOS — readable by anyone with the device attached and queryable by nobody. `debugPrint` throttles but does not disable itself in release. Grep the call sites for tokens, request bodies, and user records (REL-015). `dart:developer`'s `log()` with a level, or a `logger` package configured to no-op in release, is the better shape.

**User-facing errors.** A Dart error during build renders the grey-and-red error widget in debug and, in release, a bare grey box — which looks exactly like a broken app. `ErrorWidget.builder` overrides it with something honest. A network failure with no `catch` produces an unresolved `Future` and an indefinite spinner (MOB-015). Check that API errors are surfaced as text with a retry rather than thrown into the widget tree.

## security headers
Not applicable in the HTTP sense — the app serves no responses. The transport-security equivalents, which MOB-010 and MOB-019 audit:

**iOS App Transport Security.** `NSAppTransportSecurity` in `ios/Runner/Info.plist`. ATS is on by default and requires HTTPS with TLS 1.2+. `NSAllowsArbitraryLoads: true` disables it app-wide and is a fail in a store build; the acceptable narrow form is an `NSExceptionDomains` entry for a specific dev host, and even that should not ship.

```bash
plutil -p ios/Runner/Info.plist | grep -A20 NSAppTransportSecurity
```

**Android cleartext.** `android:usesCleartextTraffic="true"` on the `<application>` tag permits plain HTTP app-wide and is a fail in a release build; from API 28 it is off by default, so an explicit `true` is deliberate. The narrow form is `android:networkSecurityConfig="@xml/network_security_config"` with a `<domain-config cleartextTrafficPermitted="true">` limited to a dev host — and `android/app/src/debug/AndroidManifest.xml` is the right place for a dev-only override, since it does not merge into the release variant. Flutter's own template puts the Dart VM's development-mode manifest additions in `src/debug/` for exactly this reason.

```bash
grep -n 'usesCleartextTraffic\|networkSecurityConfig' android/app/src/*/AndroidManifest.xml
cat android/app/src/main/res/xml/network_security_config.xml 2>/dev/null
```

**Certificate pinning (MOB-019).** Not on by default and not required; the check wants a *documented decision*. In Flutter the mechanisms are `dio` with a `badCertificateCallback` or a custom `HttpClient` comparing the certificate's SHA-256, `http_certificate_pinning`, or a `<pin-set>` in the Android network security config. Two failure shapes specific to Dart: a `badCertificateCallback` that returns `true` unconditionally is not pinning, it is disabling validation entirely and is a serious finding; and a pin set with a single certificate and no backup bricks the app on renewal, fixable only by a store release. Check for a backup pin and an expiry.

**WebViews.** `webview_flutter` rendering remote or user-supplied content inherits the whole web threat model. Flag `JavaScriptMode.unrestricted` combined with `runJavaScript` interpolating user data, `onNavigationRequest` handlers that allow any URL, and Android's `setAllowFileAccessFromFileURLs` (SEC-043 for the injection half).

## known traps
- `android/app/build.gradle` still carrying the template's `release { signingConfig signingConfigs.debug }` with its TODO comment: MOB-010 — the "release" build is debug-signed, Play will reject it, and it could never be updated by the real key. Assume this until you have read the file.
- `android/key.properties`, a `*.jks`/`*.keystore`, `*.p12`, `*.mobileprovision`, or `AuthKey_*.p8` committed: SEC-001. Check `git log --all` as well as the working tree; a committed keystore cannot be rotated the way a key can (MOB-013).
- The upload keystore existing only on one laptop, with Play App Signing off: MOB-013 — losing it permanently ends the app's ability to ship updates.
- A `.env` listed under `flutter: assets:` for `flutter_dotenv`: SEC-003 and MOB-011 — the file ships verbatim inside the artifact and `unzip` reads it in one step. Same verdict for any `--dart-define` or `--dart-define-from-file` value that is a real secret; a compile-time constant is a public constant.
- Running `flutter build apk --debug` for MOB-011 and finding nothing: a debug build is JIT with no AOT `libapp.so`, so the grep is meaningless. Use `--profile`, and first confirm the profile build type is not wired to the release signing config.
- Treating `--obfuscate` as protection for a secret: it renames symbols, not string literals. MOB-011 stands. It does, separately, require symbol upload or every crash report is unreadable (REL-001), and the symbol directory must not ship (SEC-007).
- **Play target API level (MOB-022).** As of the August 2026 deadline, new apps and updates must target API 36 (Android 16); the floor rises each August — confirm in Play Console. Read `targetSdk` from `android/app/build.gradle` (or `.kts`), remembering that recent Flutter templates write `targetSdk = flutter.targetSdkVersion`, which resolves to whatever the installed Flutter SDK pins — so on those projects the real answer is "whatever this Flutter version ships" and raising it means upgrading Flutter. Record `compileSdk` (must be at least as high) and `minSdk` alongside. Name the behaviour changes the gap crosses: API 33 makes `POST_NOTIFICATIONS` a runtime permission, 34 requires a declared foreground-service type and tightens implicit intents, and 35 makes edge-to-edge display mandatory — which for Flutter means `SystemChrome.setEnabledSystemUIMode` and `SafeArea` usage that assumed opaque system bars now needs revisiting.
- No `PrivacyInfo.xcprivacy` in `ios/Runner/`, or one present but not added to the Runner target's Copy Bundle Resources so it never ships: MOB-020. The SDK half fails more often than yours — `find ios/Pods -name PrivacyInfo.xcprivacy` and compare against `Podfile.lock`; older Firebase, Facebook, AppsFlyer, Adjust, and Sentry builds predate manifest support. Apple's lists of required-reason APIs and manifest-requiring SDKs grow, so read the current one and mark the finding `verify current rules`. Note that `shared_preferences` and several other common plugins use `UserDefaults`, which needs `NSPrivacyAccessedAPICategoryUserDefaults` with a reason code.
- An attribution or IDFA-reading SDK (`app_tracking_transparency` absent while `appsflyer_sdk`, `adjust_sdk`, `facebook_app_events`, or Firebase Analytics with IDFA collection is present) and no `NSUserTrackingUsageDescription`: MOB-021. `AppTrackingTransparency.requestTrackingAuthorization()` must be awaited **before** the SDK initializes — calling it afterwards is the ordering bug that passes code review and fails App Review. Keep the answer consistent with MOB-004's App Privacy answers and the privacy manifest's `NSPrivacyTracking` flag.
- A permission in the *merged* manifest that the app does not use: MOB-007. Flutter plugins contribute permissions constantly, and `permission_handler` declares a wide set unless the project uses its Gradle flags to strip the unused ones. Read `android/app/build/intermediates/merged_manifests/release/AndroidManifest.xml` when it exists, and `tools:node="remove"` to strip one. The iOS mirror is a leftover `NS*UsageDescription` for a feature that was removed, which prompts App Review to ask what it is for.
- A purpose string that says "This app needs camera access": MOB-007, and a routine rejection. It must say what for.
- `NSAllowsArbitraryLoads: true` or `usesCleartextTraffic="true"` in the release variant: MOB-010. A `localhost` exception in `src/debug/` is fine; the same exception in `src/main/` is not.
- A `dio` `badCertificateCallback` returning `true`: this disables certificate validation entirely rather than pinning anything, and it is frequently added to make a self-signed dev certificate work and never removed — MOB-019, and it makes every TLS connection in the app interceptable.
- A universal link entitlement present but the AASA returning 404, a redirect, or `text/plain`, or `assetlinks.json` carrying the upload-key SHA-256 instead of the Play App Signing one: MOB-008. `adb shell pm get-app-links <package>` is the definitive Android answer.
- A deep link routing into an authenticated route because `go_router`'s `redirect` checked a local boolean: MOB-018 — the redirect is UI, the server is the boundary.
- Session tokens in `shared_preferences` rather than `flutter_secure_storage` — including `supabase_flutter`'s default session persistence, which uses `shared_preferences` unless a secure `LocalStorage` is supplied: SEC-002, and MOB-011 for a device dump.
- OAuth inside `webview_flutter` rather than `flutter_appauth`/`flutter_web_auth_2`: against most providers' policies and indistinguishable from phishing. Redirect URIs must also be registered for the production scheme (HYG-001).
- A release build shipping with the `development` APNs entitlement: MOB-009 — push silently never arrives in production.
- `POST_NOTIFICATIONS` declared but never requested at runtime on Android 13+: MOB-009 — no prompt, no notifications, no error.
- A background FCM handler that is not a top-level function annotated `@pragma('vm:entry-point')`: it is tree-shaken out of the release build and never runs, and only in release (MOB-009).
- Shorebird patching a release that is not the one in the store, or `shorebird.yaml` not bundled as an asset: MOB-003 — patches publish and reach nobody.
- Firebase Remote Config presented as the hotfix mechanism: it changes values, not code. Record it as configuration and let REL-011 own the hotfix latency.
- Measuring size, startup, or frame timing from a debug build: MOB-017 wants release (or profile, for frame timing) numbers from a physical device.
- A `--dart-define` absent at build time silently becoming an empty string: the app points at nothing and only a device shows it. Guard with an assertion at startup.
- No restore-purchases path, or entitlement recomputed from a local flag: MOB-001 — `in_app_purchase`'s `restorePurchases()` or `purchases_flutter`'s `Purchases.restorePurchases()`.
- Account deletion absent or reachable only by emailing support: MOB-005 — both stores require it to be initiated in-app for any app with account creation.
- No review demo account for an app behind a login wall: MOB-014, the most common first-submission rejection.
- Running a build or `pub get` that writes into the project when only a read was needed: this audit does not modify project files. Read `pubspec.lock` and the platform files, and where a build is genuinely required for MOB-011, use the profile variant and say so.
- Browser drivers, when a check needs one: only use `playwright`, `puppeteer`, `@playwright/test`, `cypress`, or `selenium` if already in devDependencies; never install one for the audit. Cited by the accessibility and compliance domain headers, COMP-007, and FLOW-018. Mobile runtime work uses the simulator and `xcrun`/`adb`, and Flutter's own `flutter drive` / `integration_test` where the project already has it.

## runtime probe hints
**Toolchain and devices.**
```bash
flutter doctor -v                                  # run first; a missing toolchain explains every later failure
flutter devices
flutter --version && cat pubspec.lock | head -5
xcrun simctl list devices available
xcrun simctl boot "iPhone 16"
xcrun simctl uninstall booted <bundle id>          # destroy local state for the restore test
adb devices
adb uninstall <package>
adb logcat --pid=$(adb shell pidof -s <package>)
adb shell dumpsys package <package> | grep -A20 'requested permissions'
```
`dumpsys package` gives the *effective* permission set on an installed build — the merged manifest's answer rather than the source file's (MOB-007).

**Running the app.** `flutter run` for debug, `flutter run --profile` for anything performance-related, `flutter run --release` for the honest build. Release on an iOS device needs a signing identity; if none is available, record the runtime half as unrun rather than as a fail. Where no simulator, device, or sandbox tester is available at all, the mobile checks downgrade: run the static entry, record `verified_by: static-fallback`, and name exactly what was missing.

**Reaching the app's own API from a device.** `localhost` on a phone is the phone. Bind the backend to `0.0.0.0` (not `127.0.0.1`) and point the app at the machine's LAN address — `ipconfig getifaddr en0` on macOS — passed in as `flutter run --dart-define=API_URL=http://192.168.x.x:3000`. The Android emulator reaches the host at `10.0.2.2`; the iOS simulator shares the host's network stack, so `localhost` works there and only there. `adb reverse tcp:3000 tcp:3000` forwards a host port to a USB-connected Android device. If the API is HTTPS-only, a tunnel (`ngrok http 3000`, `cloudflared tunnel`) avoids loosening ATS — and if a probe did require an ATS or cleartext exception, say so in evidence, because that configuration must not be what ships (MOB-010).

**Purchases are sandbox-only, always.** iOS: an App Store Connect sandbox tester signed in under Settings → App Store → Sandbox Account, or a StoreKit configuration file in Xcode for a fully local simulation. Android: a Play licence tester with the app on an internal or closed track. Never sign in with a real Apple ID or Google account carrying a payment method. MOB-001's sequence: buy the cheapest sandbox product, confirm the entitlement is active, uninstall (`xcrun simctl uninstall` / `adb uninstall`), reinstall, tap Restore, and confirm the entitlement returns without a second purchase. The call names to look for are `InAppPurchase.instance.restorePurchases()` (the `in_app_purchase` package) and `Purchases.restorePurchases()` (`purchases_flutter`/RevenueCat). If only live billing credentials are present, do not purchase: verify the path statically, record `error: live billing credentials detected`, and leave the runtime half unrun.

**Deep links.**
```bash
xcrun simctl openurl booted "myapp://orders/123"
xcrun simctl openurl booted "https://example.com/orders/123"
adb shell am start -W -a android.intent.action.VIEW -d "myapp://orders/123" <package>
adb shell pm get-app-links <package>            # prints verified | legacy_failure | <error code> per host
adb shell pm verify-app-links --re-verify <package>
```
On iOS there is no equivalent verification command: tap the link from Notes or Messages (Safari's address bar will not trigger a universal link), and remember the device caches its AASA fetch, so reinstalling forces a re-check.

**Reading platform files.** A built `Info.plist` inside an artifact is binary and will not grep:
```bash
plutil -p ios/Runner/Info.plist
python3 -c "import plistlib,sys;print(plistlib.load(open(sys.argv[1],'rb')))" <path>
unzip -p <app>.apk AndroidManifest.xml | strings | head -50   # binary XML; aapt2 dump badging is better where available
```

**Release-build measurements (MOB-017).** Size from `flutter build apk --analyze-size` and from the artifact on disk, compared against Play Console's download-size estimate; startup and frame timing from a **profile** build on a mid-range physical device via DevTools, never from a simulator on an M-series Mac; crash-free rate from Crashlytics, Sentry, Play Console Vitals, or Xcode Organizer — and if the app has never shipped, the honest answer is that there is no crash-free rate yet, and the finding is whether the reporting is wired up to produce one.

**Never** point a probe at production billing keys, never invoke the release signing key for an audit build, never publish a Shorebird patch during an audit, and delete any sandbox purchases and test accounts the audit created.
