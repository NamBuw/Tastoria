# Tastoria app

Expo SDK 58 (React Native 0.88), TypeScript, expo-router; one codebase for Android and web (`web.output: "single"`).
Spec: `docs/superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md` §9. Contract: `docs/api/openapi-v1.yaml`.

## Run

```bash
npm install
npm run gen:api                     # src/api/schema.d.ts from openapi-v1.yaml (openapi-typescript)
npm run typecheck
npm run export:web                  # → dist/
API_TARGET=http://127.0.0.1:8000 PORT=8080 npm run serve:web   # dist + /api proxy, same origin as nginx
```

`EXPO_PUBLIC_API_URL` sets the API base (default `/api/v1` on web, same origin). Android needs an absolute URL,
e.g. `EXPO_PUBLIC_API_URL=http://192.168.1.10:8000/api/v1 npx expo run:android`. The backend sends no CORS headers,
so `expo start --web` on another port cannot call it; use the export + `serve:web` (or nginx).

Backend and catalog: see `backend/README.md` (`tastoria db upgrade`, `tastoria catalog import data/kb`).

## Android release APK (local, no EAS)

`plugins/with-android-release.js` wires release signing from `TASTORIA_UPLOAD_*` (Gradle property or env; falls back
to the debug keystore when unset), limits ABIs to arm64-v8a + armeabi-v7a and sets Gradle to `-Xmx6g`, 8 workers.
The keystore and its password live outside the repo in `~/.config/tastoria/` (release.keystore, keystore.env).
`EXPO_PUBLIC_API_URL` is inlined into the JS bundle at build time, so it must be set when Gradle runs.

```bash
export ANDROID_HOME=$HOME/Android/Sdk JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export EXPO_PUBLIC_API_URL=https://tastoria.ctslab.net/api/v1
set -a; . ~/.config/tastoria/keystore.env; set +a
npx expo prebuild --platform android --clean --no-install
(cd android && ./gradlew assembleRelease)    # → android/app/build/outputs/apk/release/app-release.apk
```

## Layout

```
src/api/        client.ts (openapi-fetch, auth + refresh, X-App-Version), errors.ts (problem code → Vietnamese)
src/auth/       session provider; refresh token in expo-secure-store (Android) / sessionStorage (web)
src/lib/        outbox (complete + events, same Idempotency-Key / event_id on replay), catalog snapshot cache,
                cooking (session cache, absolute-time timers, keep-awake), image (1280 px JPEG), idempotency keys
src/theme/      tokens.ts: light + dark palettes (contrast ratios in the header comment), type scale, 48 dp targets
src/components/ ui primitives, tray, kcal bar, freshness badge (colour + text), profile and pantry forms
src/app/        routes: (auth) đăng nhập / đăng ký / quên mật khẩu, dat-lai-mat-khau, onboarding (đồng ý + 4 bước),
                (tabs) trang chủ / kho / mâm / đi chợ / nhật ký, quet, quet/[id], nau/[id], nau-xong/[id], mon/[id],
                cai-dat, khao-sat (public)
```

## E2E

`scripts/e2e_flow.py` (python playwright) drives register → onboarding → 10 pantry lots by hand → tray → swap →
recipe → cook → finish → undo → cook again → journal, and saves a light and a dark 390×844 screenshot of each screen
to `docs/screenshots/`. Run it against `serve:web` with a fresh backend that has the catalog imported:

```bash
WEB_URL=http://127.0.0.1:8080 python scripts/e2e_flow.py docs/screenshots
```

Scan (`/scans`) and survey (`/survey/*`) endpoints are in the contract but not in the backend yet; the app shows
"Quét ảnh chưa mở" / "Khảo sát chưa mở" when the POST answers 404.

## Public website and releases

The website root `/` serves the public landing; `/bep` opens the authenticated app. CI/CD and signed Android releases are documented in [deploy/FRONTEND-CD.md](../deploy/FRONTEND-CD.md).
