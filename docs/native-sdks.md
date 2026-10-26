# Native application reporting

These libraries report errors explicitly from your existing application error handling. They do not install a global crash handler, capture stack traces, replay sessions, identify users or infer that every crash was observed. Reports are untrusted telemetry and cannot trigger gateway blocks or repairs.

Set the monitor's `native_apps` list to your app's identifier. Use an HTTPS `/ingest/native` endpoint and the public installation key. Private operator/gateway/model credentials never belong in an app binary.

## iOS

The package at `sdk/ios` uses Swift 5.9 and supports iOS 15/macOS 12 or later. Add that local package directory in Xcode and link its `CharismaMonitor` product. The package is in a subdirectory, so adding the repository root as a remote Swift package is not supported. Vendor the package at a reviewed commit or publish a dedicated package repository if your distribution workflow needs a root-level remote package.

```swift
import CharismaMonitor
import Foundation

let monitor = try CharismaMonitor(
    endpoint: URL(string: "https://monitor.example.com/ingest/native")!,
    appID: "com.example.yourapp",
    siteKey: "your-public-installation-key"
)

// Call from an existing error-handling path using a fixed screen label.
Task {
    await monitor.record(screen: "checkout", category: .error)
}

// When reporting should stop:
Task {
    await monitor.stop()
}
```

`record` returns true when the configured transport accepts the report. Categories are `.error` and `.unknown`. Labels accept 1–40 letters, digits, underscores or hyphens. Duplicate screen/category pairs are suppressed and a monitor instance sends at most 30 distinct reports. There is no persistence/retry queue.

The default transport uses an ephemeral URLSession, disables its cookie handling/cache, refuses redirects and has an eight-second request timeout. Do not use permissive App Transport Security exceptions to work around an invalid TLS setup. Monitoring failures return false and do not replace the application's normal error handling. `stop()` prevents future reports; an already-started request may finish.

Local checks on a Mac:

```sh
cd sdk/ios
swift test
xcodebuild -scheme CharismaMonitor \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /tmp/charisma-derived CODE_SIGNING_ALLOWED=NO build
```

This compiles the SDK without signing. Your actual app still needs its own integration tests, simulator/device runs, privacy review and store release process.

## Android and Kotlin

The source at `sdk/android/src/main/java/io/charisma/CharismaMonitor.java` is Java 8 compatible and supports Android API 21 or later. Copy it into your app/module's matching `io/charisma` package, or build a reviewed JAR and add it to your Gradle module. CI supplies a JAR artifact; no Maven publication is configured.

Your application needs its normal `android.permission.INTERNET` permission. Use HTTPS without disabling certificate validation.

Kotlin integration:

```kotlin
import io.charisma.CharismaMonitor

val monitor = CharismaMonitor(
    "https://monitor.example.com/ingest/native",
    "com.example.yourapp",
    "your-public-installation-key"
)

// From an existing error-handling path:
monitor.record("checkout")

// At the lifecycle boundary where this monitor should stop:
monitor.close()
```

`record` returns whether the report was queued, not whether the server received it. A bounded background executor sends it. Labels use the same 1–40 character rules as iOS, duplicates are suppressed by screen, and the session is capped at 30 distinct reports. The payload category is `Unknown`; exception messages and stack traces are not passed to this API.

The default transport uses HttpURLConnection with five-second connect/read timeouts, no redirects, no automatic retry and an explicitly empty Cookie header. The SDK does not read application cookies. Review any app-wide CookieHandler, Authenticator or network instrumentation because the embedding application controls those global facilities. Use the injectable transport when your app needs stricter networking integration.

`close()` stops future reports and cancels queued work. A network request already running may take its timeout to end. `awaitIdle()` is a test/controlled-shutdown helper; never wait on it from the UI thread.

CI runs Java behaviour tests, compiles against Android API 35 and generates DEX for minimum API 21. This is library compatibility evidence, not an emulator/device test of your app.

## Integration checks

1. Trigger a controlled handled error in a non-production build and verify one event appears.
2. Inspect the request and confirm no account details, error messages, stack traces or personal labels are present.
3. Confirm invalid app identifiers are rejected and monitoring failure does not disrupt the app.
4. Confirm duplicates, session limits and stop/close behaviour fit your lifecycle.
5. Retain the application's own crash/error reporting and test release behaviour on devices.
