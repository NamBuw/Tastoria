#!/usr/bin/env bash
# Exercise nginx HTTP routing in a disposable container before touching production.
set -euo pipefail
image="${1:?Pass an image tag}"
container="tastoria-web-check-$$"
cleanup() { docker rm -f "$container" > /dev/null 2>&1 || true; }
trap cleanup EXIT
# No production volumes, credentials or published external interfaces.
docker run -d --name "$container" -p 127.0.0.1::80 "$image" > /dev/null
port="$(docker port "$container" 80/tcp | head -n1 | sed 's/.*://')"
base="http://127.0.0.1:$port"
for i in $(seq 1 15); do
  if curl -fsS "$base/" 2>/dev/null | grep -q 'id="hero-title"'; then break; fi
  [ "$i" != 15 ] || { docker logs "$container"; exit 1; }
  sleep 1
done
curl -fsS "$base/gioi-thieu/" | grep -q 'id="hero-title"'
curl -fsS "$base/gioi-thieu/style.css" | grep -q -- '--paper'
curl -fsS "$base/gioi-thieu/story.js" | grep -q 'data-ingredient'
curl -fsS "$base/bep" | grep -q '_expo/static/js'
curl -fsS "$base/dang-nhap" | grep -q '_expo/static/js'
echo 'nginx HTTP preflight passed: public root, legacy landing, assets, app routes.'
