# CARA Android — WebView wrapper APK

A minimal Android project that wraps the CARA PWA in a WebView for users
who prefer a "real app" icon over the Chrome PWA install. Builds locally
on the NanoPC (aarch64) using the Android SDK + QEMU x86_64 emulation
since Google ships build-tools host binaries only as x86_64.

## Prerequisites (one-off)

```bash
sudo apt-get install -y openjdk-17-jdk-headless qemu-user-static binfmt-support unzip
sudo dpkg --add-architecture amd64
sudo apt-get update && sudo apt-get install -y libc6:amd64 libstdc++6:amd64 zlib1g:amd64
```

Android SDK at `/opt/android-sdk` with:
- cmdline-tools `latest`
- platform-tools
- platforms;android-34
- build-tools;36.1.0

(Installed via `sdkmanager`. See the timestamps in `/opt/android-sdk/`.)

## Signing key

`cara-signing.keystore` (excluded from git). Generate once with:

```bash
keytool -genkeypair -v -keystore cara-signing.keystore -alias cara \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass cara-signing-2026 -keypass cara-signing-2026 \
  -dname "CN=CARA, OU=Famiglia Pedoto, O=CARA Home, L=Italia, ST=Italia, C=IT"
```

Lose the keystore and you can't ship updates that the OS recognises as
the same app — keep it backed up off-server.

## Build

```bash
cd /opt/cara/build/twa
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64
export ANDROID_HOME=/opt/android-sdk
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
./gradlew --no-daemon assembleRelease
```

Output: `app/build/outputs/apk/release/app-release.apk` (~2.5 MB).

## Deploy

```bash
cp app/build/outputs/apk/release/app-release.apk \
   /opt/cara/frontend/public/cara.apk
docker cp /opt/cara/frontend/public/cara.apk \
          cara-frontend:/usr/share/nginx/html/cara.apk
```

Family downloads from `https://192.168.1.23:8455/cara.apk`.

## Behaviour

- Loads `https://192.168.1.23:8455/` in a single fullscreen WebView.
- Trusts the LAN self-signed cert via `network_security_config.xml`
  (only for the host `192.168.1.23`).
- Asks for `RECORD_AUDIO` at first launch and forwards it to the page
  so STT and the wake word work.
- `setMediaPlaybackRequiresUserGesture(false)` so Piper TTS can start
  speaking after the discovery roundtrip without an extra tap.
- Back button navigates the WebView's history stack first; falls back
  to the system back when the WebView has no more history.

## What this is NOT

- Not a TWA. There's no Digital Asset Links file, no Custom Tabs, no
  Chrome integration. It's a WebView. Pros: works fully offline-against-
  service-worker, simpler, no online verification step. Cons: can't share
  cookies / auth state with Chrome on the same device.
- Not on Play Store. Sideload only — `Settings → Security → Install
  unknown apps` on Android.
