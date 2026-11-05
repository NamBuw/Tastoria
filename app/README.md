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

## Size (slimming pass, 2026-11-05)

| | before | after |
|---|---|---|
| `src/` lines (without generated `api/schema.d.ts`) | 6155 | 6113 |
| npm dependencies | 31 | 27 (dropped expo-device, react-native-reanimated, react-native-worklets, react-native-gesture-handler: nothing imports them; expo-router treats them as optional) |
| web export JS (`expo export -p web`) | 1 646 951 B (449 kB gzip) | 1 641 852 B (448 kB gzip) |
| web export assets | 925 kB | 803 kB |
| web export total | 2.61 MB | 2.48 MB |
| Android Hermes bundle | 3 637 919 B | 3 631 161 B |
| `assets/` (food photo + icons) | 424 kB | 272 kB (photo JPEG → WebP q78, icons re-encoded losslessly) |

All four Be Vietnam Pro weights are in use (500 only for the freshness badge). `api/schema.d.ts` stays generated
from the contract (types only, no bundle cost). Visual check: `scripts/e2e_flow.py` screenshots before/after differ
only in data (dish order, times, e-mail).
