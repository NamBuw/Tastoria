#!/usr/bin/env bash
# Run from a clean, CI-approved checkout; deploy frontend only, without migrations.
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
live_dir="${TASTORIA_LIVE_DEPLOY:?Set the live deploy directory}"
apk_dir="$(cd "$live_dir/.." && pwd)/dist"
sha="$(git -C "$repo_dir" rev-parse HEAD)"
tag="ui-${sha:0:12}"
cd "$repo_dir"
npm --prefix app ci --no-audit --no-fund
npm --prefix app run typecheck
npm --prefix app run lint
python3 app/scripts/contrast.py > /dev/null
echo "Publishing web before the Android build"
docker build -f deploy/web.Dockerfile -t "tastoria-web:$tag" .
docker run --rm --network tastoria_backend "tastoria-web:$tag" nginx -t
# Persist only a frontend override; keep backend/catalog/model version untouched.
previous="$(docker inspect tastoria-nginx-1 --format '{{.Config.Image}}')"
previous_tag="${previous#tastoria-web:}"
set_tag() {
  local temp
  temp="$(mktemp "$live_dir/.env.XXXXXX")"
  grep -v '^TASTORIA_WEB_TAG=' "$live_dir/.env" > "$temp" || true
  printf 'TASTORIA_WEB_TAG=%s\n' "$1" >> "$temp"
  chmod 600 "$temp"
  mv "$temp" "$live_dir/.env"
}
compose() { docker compose --project-directory "$live_dir" -f "$live_dir/docker-compose.yml" "$@"; }
set_tag "$tag"
if ! compose up -d --no-deps --no-build nginx; then
  set_tag "$previous_tag"; compose up -d --no-deps --no-build nginx; exit 1
fi
ok=0
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:6880/ | grep -q 'id="hero-title"' && curl -fsS http://127.0.0.1:6880/healthz > /dev/null && curl -fsS http://127.0.0.1:6880/gioi-thieu/story.js > /dev/null; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != 1 ]; then
  set_tag "$previous_tag"; compose up -d --no-deps --no-build nginx
  echo 'Frontend health check failed; previous image restored.' >&2; exit 1
fi
# Existing signing key stays on the server and is never uploaded to GitHub.
set -a
source "${TASTORIA_KEYSTORE_ENV:-$HOME/.config/tastoria/keystore.env}"
set +a
: "${TASTORIA_UPLOAD_STORE_FILE:?Release signing is required}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"
export EXPO_PUBLIC_API_URL="${TASTORIA_PUBLIC_API:-https://tastoria.ctslab.net/api/v1}"
export CI=1 EXPO_NO_TELEMETRY=1
(cd app && npx expo prebuild --platform android --clean --no-install && cd android && ./gradlew assembleRelease --no-daemon)
version="$(node -p "require('./app/app.json').expo.version")"
mkdir -p "$apk_dir"
cp app/android/app/build/outputs/apk/release/app-release.apk "$apk_dir/tastoria-$version.apk.tmp"
mv "$apk_dir/tastoria-$version.apk.tmp" "$apk_dir/tastoria-$version.apk"

printf '%s\t%s\tfrontend + APK %s\n' "$(date -u +%FT%TZ)" "$sha" "$version" >> "$live_dir/releases.log"
echo "Deployed $sha, APK $version"
