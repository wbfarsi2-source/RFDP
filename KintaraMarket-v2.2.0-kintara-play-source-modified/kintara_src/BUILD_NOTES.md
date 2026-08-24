# Build notes — v2.1.0

Requirements: JDK, Android Platform 35, `aapt2`, `d8`, `zipalign`, and `apksigner`.

The release APK is compiled against API 35 with minSdk 23, zip-aligned, signed, and verified with Android APK signature schemes.

Set `ANDROID_HOME` or `ANDROID_SDK_ROOT`, then run `./build.sh`. To sign, also set `KINTARA_KEYSTORE`, `KINTARA_KEY_ALIAS`, `KINTARA_STORE_PASS`, and `KINTARA_KEY_PASS`.

Live marketplace Buy and Sell require:

- an authenticated Kintara account;
- Android System WebView with JavaScript and WebSocket support;
- successful automatic Queue/Presence entry to a public Kintara server;
- Phantom or Solflare for $KINS approval;
- sufficient $KINS and a small SOL balance for network fees; and
- network access to Kintara and Solana through the authenticated Kintara relay.

The Premium game entry is a native Android Activity shell around the official
Kintara client. It requires Android System WebView with JavaScript, WebGL and
WebSocket support. Holding Settings in the app launches the Activity and asks
Android for portrait orientation; returning to the market restores the normal
sensor policy.

Installing as an update requires the private signing key used by the already-installed APK. A differently signed APK requires uninstalling the existing app first.
