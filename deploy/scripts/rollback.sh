#!/usr/bin/env bash
# Run an earlier image tag again (images stay on the host: `docker images tastoria-backend`).
#   ./scripts/rollback.sh <tag>
# Code-only rollback. If the newer release ran a migration, the older image cannot start on the newer schema
# (alembic does not know the revision): restore the pre-deploy backup first (./scripts/restore.sh), see README.
source "$(dirname "$0")/lib.sh"
tag="${1:?dùng: rollback.sh <tag> (xem deploy/releases.log)}"
docker image inspect "tastoria-backend:$tag" "tastoria-web:$tag" >/dev/null || die "không có image tag $tag"
env_set TASTORIA_IMAGE_TAG "$tag"
dc up -d --remove-orphans --no-build
wait_healthy 240 api nginx scheduler
printf '%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$tag" "rollback" >> "$DEPLOY_DIR/releases.log"
log "đang chạy $tag"
