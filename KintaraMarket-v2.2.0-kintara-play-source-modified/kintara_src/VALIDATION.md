# v2.1.0 validation

The project was compiled against Android Platform 35 with the supplied plain-Java build script:

```text
./build.sh
```

The generated release APK was zip-aligned and verified with APK Signature Schemes v1, v2, and v3. `aapt2 dump badging` reports package `com.tm.kintaramarket`, version `2.1.0`, minSdk 23, and targetSdk 35. The manifest includes the non-exported `KintaraGameActivity` used by the Premium Settings long press.

The source includes wallet-scoped encrypted cache/profile stores, the Premium plan/account-slot model, the item-coloured Market Flow screen, the portrait immersive game shell, and public-mirror item-art aliases. Runtime marketplace, game and Solana behavior still depends on a live authenticated Kintara session, Android WebView with JavaScript/WebGL/WebSocket support, wallet approval where required, and network availability.
