#!/usr/bin/env bash
# Restore a backup made by backup.sh.
#   ./scripts/restore.sh --verify FILE.tar.gpg   decrypt + pg_restore into a throwaway container, print counts
#                                               (rehearsal: touches nothing of the running stack)
#   ./scripts/restore.sh FILE.tar.gpg            REPLACE the live database and files with the backup
# A remote copy: rclone copy gdrive-cts:Backups/tastoria/<name> ~/backups/tastoria/
source "$(dirname "$0")/lib.sh"
verify=0
[ "${1:-}" = "--verify" ] && { verify=1; shift; }
file="$(realpath "${1:?dùng: restore.sh [--verify] FILE.tar.gpg}")"
[ -f "$file" ] || die "không thấy $file"
pass="$(env_get BACKUP_PASSPHRASE)"; [ -n "$pass" ] || die "BACKUP_PASSPHRASE trống trong .env"

work="$(mktemp -d)"
cleanup() { rm -rf "$work"; [ -n "${tmpc:-}" ] && docker rm -f "$tmpc" >/dev/null 2>&1 || true; }
trap cleanup EXIT
gpg --batch --quiet --decrypt --pinentry-mode loopback --passphrase-fd 3 "$file" 3<<<"$pass" | tar xf - -C "$work"
cat "$work/MANIFEST"

role_sql="DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_app') THEN
        CREATE ROLE tastoria_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_jobs') THEN
        CREATE ROLE tastoria_jobs LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_migrator') THEN
        CREATE ROLE tastoria_migrator NOLOGIN;
    END IF;
END \$\$;"

count_sql="select 'published_recipes='||count(*) from recipes where status='published'
  union all select 'users='||count(*) from users
  union all select 'alembic='||version_num from alembic_version"

if [ "$verify" = 1 ]; then
  tmpc="tastoria-restore-verify-$$"
  docker run -d --name "$tmpc" --label tastoria-restore-verify=1 -e POSTGRES_USER=tastoria -e POSTGRES_DB=tastoria \
    -e POSTGRES_PASSWORD=verify pgvector/pgvector:pg18 >/dev/null
  for _ in $(seq 60); do docker exec "$tmpc" pg_isready -U tastoria -d tastoria -q 2>/dev/null && break; sleep 1; done
  sleep 2
  docker exec "$tmpc" psql -U tastoria -d postgres -v ON_ERROR_STOP=1 -c "$role_sql"
  docker exec -i "$tmpc" pg_restore -U tastoria -d tastoria --no-owner --exit-on-error < "$work/db.dump"
  docker exec "$tmpc" psql -U tastoria -d tastoria -Atc "$count_sql"
  log "tệp trong bản sao lưu: $(tar tzf "$work/files.tar.gz" | grep -vc '/$') tệp"
  log "diễn tập khôi phục OK (container tạm đã xoá)"
  exit 0
fi

read -r -p "Ghi đè CSDL và tệp đang chạy bằng $(basename "$file")? Gõ 'khoi phuc' để tiếp tục: " ans
[ "$ans" = "khoi phuc" ] || die "đã huỷ"
log "sao lưu trạng thái hiện tại trước khi ghi đè"
"$DEPLOY_DIR/scripts/backup.sh" --local-only --label pre-restore
dc stop nginx api worker scheduler
dc exec -T valkey valkey-cli FLUSHDB
dc exec -T postgres psql -U tastoria -d postgres -v ON_ERROR_STOP=1 -c "$role_sql" \
  -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='tastoria' and pid<>pg_backend_pid()" \
  -c "drop database tastoria" -c "create database tastoria owner tastoria"
dc exec -T postgres pg_restore -U tastoria -d tastoria --no-owner --exit-on-error < "$work/db.dump"
dc exec -T postgres psql -U tastoria -d tastoria -Atc "$count_sql"
docker run --rm -i -u 0 -v tastoria_files:/f "tastoria-backend:$(env_get TASTORIA_IMAGE_TAG)" \
  sh -ec 'find /f -mindepth 1 -delete; tar xzf - -C /f; chown -R 10001:10001 /f' < "$work/files.tar.gz"
app_pw="$(env_get POSTGRES_APP_PASSWORD)"
jobs_pw="$(env_get POSTGRES_JOBS_PASSWORD)"
if [ -n "$app_pw" ] || [ -n "$jobs_pw" ]; then
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
fi
dc run --rm migrate
dc up -d
wait_healthy 240 api worker nginx scheduler
log "đã khôi phục từ $(basename "$file")"
