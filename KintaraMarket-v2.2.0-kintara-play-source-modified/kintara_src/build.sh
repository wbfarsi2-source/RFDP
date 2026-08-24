#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION_NAME="2.2.0"
VERSION_TAG="v2.2.0"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [[ -z "$SDK" ]]; then
  echo "Set ANDROID_HOME or ANDROID_SDK_ROOT." >&2
  exit 1
fi
ANDROID_JAR="$SDK/platforms/android-35/android.jar"
if [[ ! -f "$ANDROID_JAR" ]]; then
  echo "Android Platform 35 is required." >&2
  exit 1
fi

if [[ -n "${ANDROID_BUILD_TOOLS:-}" ]]; then
  BT="$ANDROID_BUILD_TOOLS"
else
  BT="$(find "$SDK/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)"
fi
for t in aapt2 d8 zipalign apksigner; do
  [[ -x "$BT/$t" ]] || { echo "Missing $BT/$t" >&2; exit 1; }
done

OUT="$ROOT/out"
CLS="$OUT/classes"
DEX="$OUT/dex"
rm -rf "$OUT"
mkdir -p "$CLS" "$DEX"
find "$ROOT/src" -name '*.java' | sort > "$OUT/sources.txt"

if command -v javac >/dev/null 2>&1; then
  JAVAC=(javac)
else
  JAVAC=(java -m jdk.compiler/com.sun.tools.javac.Main)
fi
"${JAVAC[@]}" -source 8 -target 8 -Xlint:-options -classpath "$ANDROID_JAR" -d "$CLS" @"$OUT/sources.txt"
if command -v jar >/dev/null 2>&1; then
  JAR=(jar)
else
  JAR=(java -m jdk.jartool/sun.tools.jar.Main)
fi
(cd "$CLS" && "${JAR[@]}" cf "$OUT/classes.jar" .)
"$BT/d8" --min-api 23 --lib "$ANDROID_JAR" --output "$DEX" "$OUT/classes.jar"
"$BT/aapt2" compile --dir "$ROOT/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/base-unsigned.apk" -I "$ANDROID_JAR" --manifest "$ROOT/AndroidManifest.xml" -A "$ROOT/assets" "$OUT/res.zip"
cp "$DEX/classes.dex" "$OUT/classes.dex"
(cd "$OUT" && zip -q -u base-unsigned.apk classes.dex)
"$BT/zipalign" -f -p 4 "$OUT/base-unsigned.apk" "$OUT/KintaraMarket-${VERSION_TAG}-aligned-unsigned.apk"

if [[ -n "${KINTARA_KEYSTORE:-}" ]]; then
  : "${KINTARA_KEY_ALIAS:?Set KINTARA_KEY_ALIAS}"
  : "${KINTARA_STORE_PASS:?Set KINTARA_STORE_PASS}"
  : "${KINTARA_KEY_PASS:?Set KINTARA_KEY_PASS}"
  "$BT/apksigner" sign \
    --ks "$KINTARA_KEYSTORE" \
    --ks-key-alias "$KINTARA_KEY_ALIAS" \
    --ks-pass "pass:$KINTARA_STORE_PASS" \
    --key-pass "pass:$KINTARA_KEY_PASS" \
    --v1-signing-enabled true \
    --v2-signing-enabled true \
    --v3-signing-enabled true \
    --out "$OUT/KintaraMarket-${VERSION_TAG}.apk" \
    "$OUT/KintaraMarket-${VERSION_TAG}-aligned-unsigned.apk"
  "$BT/apksigner" verify --verbose "$OUT/KintaraMarket-${VERSION_TAG}.apk"
  echo "Built: $OUT/KintaraMarket-${VERSION_TAG}.apk"
else
  echo "Built unsigned: $OUT/KintaraMarket-${VERSION_TAG}-aligned-unsigned.apk"
fi
