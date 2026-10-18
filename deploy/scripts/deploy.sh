#!/usr/bin/env bash
# Build images for the current git commit, back up the database, migrate + import the catalog, start the stack.
#   ./scripts/deploy.sh            deploy HEAD (working tree as it is; tag gets -dirty when uncommitted)
#   ./scripts/deploy.sh --no-backup
source "$(dirname "$0")/lib.sh"
do_backup=1
[ "${1:-}" = "--no-backup" ] && do_backup=0

[ -f "$ENV_FILE" ] || "$DEPLOY_DIR/scripts/init-env.sh"
chmod 600 "$ENV_FILE"

tag="$(git -C "$REPO_DIR" rev-parse --short=12 HEAD)"
git -C "$REPO_DIR" diff --quiet HEAD -- backend ml app data/kb data/processed/fct2007 data/processed/usda deploy \
  || tag="$tag-dirty-$(date +%Y%m%d%H%M%S)"
prev="$(env_get TASTORIA_IMAGE_TAG)"
log "build tastoria-backend:$tag, tastoria-web:$tag (trước đó: ${prev:-chưa có})"
TASTORIA_IMAGE_TAG="$tag" dc build --pull api nginx
docker tag "tastoria-backend:$tag" tastoria-backend:latest

# pg_dump before migrating (spec v2 §10), when a database is already running.
if [ "$do_backup" = 1 ] && [ -n "$(dc ps -q --status running postgres 2>/dev/null)" ]; then
  log "sao lưu trước khi migrate"
  "$DEPLOY_DIR/scripts/backup.sh" --local-only --label "pre-$tag"
fi

# Models (gitignored on the host): stage them for the migrate container, which registers them in the file volume
# (scripts/models-bootstrap.sh). Missing files are not fatal when the volume already holds a deployed version.
stage_model() { # stage_model NAME VERSION PREPROCESS ONNX METRICS SERVING
  local d="$DEPLOY_DIR/models/$1"
  if [ ! -f "$4" ]; then
    log "không thấy $4: bỏ qua đăng ký $1 (bản đã đăng ký trong volume vẫn dùng được)"
    rm -rf "$d"
    return 0
  fi
  mkdir -p "$d"
  cp "$4" "$d/model.onnx.tmp" && mv "$d/model.onnx.tmp" "$d/model.onnx"
  printf '%s' "$2" > "$d/version"
  printf '%s' "$3" > "$d/preprocess_version"
  cp "$5" "$d/metrics.json"
  cp "$6" "$d/serving.json"
  log "model $1 $2 (sha256 $(sha256sum "$d/model.onnx" | cut -c1-12)…)"
}
mkdir -p "$DEPLOY_DIR/models"
det_version="${TASTORIA_DETECTOR_VERSION:-yolo26n_640_none}"
stage_model detector "$det_version" none \
  "${TASTORIA_DETECTOR_ONNX:-$REPO_DIR/ml/runs/detect/$det_version/weights/best.onnx}" \
  "$REPO_DIR/data/processed/cv/detector/$det_version.json" \
  "$REPO_DIR/data/processed/cv/detector/${det_version}_serving.json"
# No freshness model is exported yet (backend/README.md, slice 3): nothing to stage.

env_set TASTORIA_IMAGE_TAG "$tag"
log "migrate + import catalog, rồi khởi động"
dc up -d --remove-orphans --wait --wait-timeout 300 postgres valkey
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
