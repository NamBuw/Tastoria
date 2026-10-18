# Shared helpers for deploy/scripts/*.sh (sourced, not run).
set -euo pipefail
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
ENV_FILE="$DEPLOY_DIR/.env"
cd "$DEPLOY_DIR"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
die() { log "LỖI: $*" >&2; exit 1; }
dc() { docker compose --project-directory "$DEPLOY_DIR" -f "$DEPLOY_DIR/docker-compose.yml" "$@"; }

env_get() { # env_get NAME -> value from .env (empty if absent)
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true
}

env_set() { # env_set NAME VALUE -> replace or append the line in .env
  local tmp
  tmp="$(mktemp "$DEPLOY_DIR/.env.XXXXXX")"
  grep -vE "^$1=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

wait_healthy() { # wait_healthy SECONDS service...
  local deadline=$(( $(date +%s) + $1 )); shift
  local svc state
  for svc in "$@"; do
    while :; do
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$(dc ps -q "$svc")" 2>/dev/null || echo missing)"
      [ "$state" = healthy ] && break
      [ "$(date +%s)" -lt "$deadline" ] || die "$svc chưa healthy (trạng thái: $state). Xem: docker compose logs $svc"
      sleep 3
    done
    log "$svc: healthy"
  done
}
