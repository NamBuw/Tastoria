#!/usr/bin/env bash
# Build images for the current git commit, back up the database, migrate + import the catalog, start the stack.
#   ./scripts/deploy.sh            deploy HEAD (working tree as it is; tag gets -dirty when uncommitted)
#   ./scripts/deploy.sh --no-backup
source "$(dirname "$0")/lib.sh"
do_backup=1
[ "${1:-}" = "--no-backup" ] && do_backup=0

if [ -f "$ENV_FILE" ]; then
  "$DEPLOY_DIR/scripts/init-env.sh" --ensure-missing
else
  "$DEPLOY_DIR/scripts/init-env.sh"
fi
chmod 600 "$ENV_FILE"

tag="$(git -C "$REPO_DIR" rev-parse --short=12 HEAD)"
git -C "$REPO_DIR" diff --quiet HEAD -- backend ml app data/kb data/processed/fct2007 data/processed/usda deploy \
  || tag="$tag-dirty-$(date +%Y%m%d%H%M%S)"
prev="$(env_get TASTORIA_IMAGE_TAG)"
log "build tastoria-backend:$tag, tastoria-web:$tag (trước đó: ${prev:-chưa có})"
TASTORIA_IMAGE_TAG="$tag" TASTORIA_WEB_TAG="$tag" dc build --pull api nginx
docker tag "tastoria-backend:$tag" tastoria-backend:latest
docker tag "tastoria-web:$tag" tastoria-web:latest

"$DEPLOY_DIR/scripts/check-web-image.sh" "tastoria-web:$tag"

# pg_dump before migrating (spec v2 §10), when a database is already running.
if [ "$do_backup" = 1 ] && [ -n "$(dc ps -q --status running postgres 2>/dev/null)" ]; then
  log "sao lưu trước khi migrate"
  "$DEPLOY_DIR/scripts/backup.sh" --local-only --label "pre-$tag"
fi

# Models (gitignored on the host): stage them for the migrate container, which registers them in the file volume
# (scripts/models-bootstrap.sh). Missing files are not fatal when the volume already holds a deployed version.
stage_model() { # stage_model NAME VERSION PREPROCESS ARTIFACT METRICS SERVING [FILENAME]
  local d="$DEPLOY_DIR/models/$1"
  local fname="${7:-model.onnx}"
  if [ ! -f "$4" ]; then
    log "không thấy nguồn ngoài $4: giữ nguyên bản đã stage trong $d (nếu có)"
    return 0
  fi
  mkdir -p "$d"
  cp "$4" "$d/$fname.tmp" && mv "$d/$fname.tmp" "$d/$fname"
  printf '%s' "$2" > "$d/version"
  printf '%s' "$3" > "$d/preprocess_version"
  [ -f "$5" ] && cp "$5" "$d/metrics.json"
  [ -f "$6" ] && cp "$6" "$d/serving.json"
  log "model $1 $2 (sha256 $(sha256sum "$d/$fname" | cut -c1-12)…)"
}
mkdir -p "$DEPLOY_DIR/models"
if [ -n "${TASTORIA_DETECTOR_VERSION:-}" ] || [ -n "${TASTORIA_DETECTOR_ONNX:-}" ] || [ ! -f "$DEPLOY_DIR/models/detector/model.onnx" ]; then
  det_version="${TASTORIA_DETECTOR_VERSION:-yolo26n_640_none}"
  stage_model detector "$det_version" none \
    "${TASTORIA_DETECTOR_ONNX:-$REPO_DIR/ml/runs/detect/$det_version/weights/best.onnx}" \
    "$REPO_DIR/data/processed/cv/detector/$det_version.json" \
    "$REPO_DIR/data/processed/cv/detector/${det_version}_serving.json"
else
  log "giữ nguyên detector đã stage trong $DEPLOY_DIR/models/detector ($(cat "$DEPLOY_DIR/models/detector/version" 2>/dev/null || echo unknown))"
fi
# Already-staged models (detector, meal_calorie, dish_classifier, mushroom_classifier, ranker, embeddings) are preserved as-is unless explicitly overridden.

env_set TASTORIA_IMAGE_TAG "$tag"
env_set TASTORIA_WEB_TAG "$tag"
log "migrate + import catalog, rồi khởi động"
dc up -d --remove-orphans --wait --wait-timeout 300 postgres valkey

app_pw="$(env_get POSTGRES_APP_PASSWORD)"
jobs_pw="$(env_get POSTGRES_JOBS_PASSWORD)"
[ -n "$app_pw" ] || die "POSTGRES_APP_PASSWORD trống trong .env"
[ -n "$jobs_pw" ] || die "POSTGRES_JOBS_PASSWORD trống trong .env"

log "cấu hình role PostgreSQL least-privilege tastoria_app & tastoria_jobs"
dc exec -T postgres psql -U tastoria -d tastoria -v ON_ERROR_STOP=1 -v app_pw="$app_pw" -v jobs_pw="$jobs_pw" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_app') THEN
        CREATE ROLE tastoria_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_jobs') THEN
        CREATE ROLE tastoria_jobs LOGIN;
    END IF;
END $$;
ALTER ROLE tastoria_app WITH LOGIN PASSWORD :'app_pw';
ALTER ROLE tastoria_jobs WITH LOGIN PASSWORD :'jobs_pw';
SQL

up_ok=1
dc up -d --remove-orphans || up_ok=0
code="$(docker inspect -f '{{.State.ExitCode}}' "$(dc ps -aq migrate)" 2>/dev/null || echo '?')"
dc logs --no-log-prefix migrate | tail -n 40
if [ "$code" != 0 ]; then
  [ -n "$prev" ] && log "migrate lỗi; đang quay về $prev: ./scripts/rollback.sh $prev"
  die "migrate thoát mã $code — api/scheduler không được khởi động"
fi
[ "$up_ok" = 1 ] || die "docker compose up lỗi (xem docker compose ps -a / logs)"
wait_healthy 240 api worker nginx scheduler

curl -fsS http://127.0.0.1:6880/healthz >/dev/null || die "/healthz qua nginx không trả 200"
curl -fsS http://127.0.0.1:6880/readyz >/dev/null || die "/readyz qua nginx không trả 200"
printf '%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$tag" "$(git -C "$REPO_DIR" log -1 --format=%s HEAD)" >> "$DEPLOY_DIR/releases.log"
dc ps
log "xong: tastoria $tag trên http://127.0.0.1:6880"
