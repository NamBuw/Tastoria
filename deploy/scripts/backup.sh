#!/usr/bin/env bash
# Encrypted backup (spec v2 §10, UC33): pg_dump -Fc + the files volume, one tar, gpg AES-256 with
# BACKUP_PASSPHRASE from .env. Kept BACKUP_KEEP_DAYS (default 14) locally and on BACKUP_RCLONE_DEST.
#   ./scripts/backup.sh                    local + Drive
#   ./scripts/backup.sh --local-only       (used by deploy.sh before migrating)
#   ./scripts/backup.sh --label pre-abc    name suffix
# NOT in the backup: deploy/.env (health-column keys, JWT keys, this passphrase). Keep it apart (ADR 0005).
source "$(dirname "$0")/lib.sh"
local_only=0; label=daily
while [ $# -gt 0 ]; do
  case "$1" in
    --local-only) local_only=1 ;;
    --label) label="$2"; shift ;;
    *) die "tham số lạ: $1" ;;
  esac
  shift
done

pass="$(env_get BACKUP_PASSPHRASE)"; [ -n "$pass" ] || die "BACKUP_PASSPHRASE trống trong .env"
keep="$(env_get BACKUP_KEEP_DAYS)"; keep="${keep:-14}"
dest="$(env_get BACKUP_RCLONE_DEST)"
dir="${BACKUP_DIR:-$HOME/backups/tastoria}"
mkdir -p "$dir"; chmod 700 "$dir"

exec 9>"$dir/.lock"
flock -n 9 || die "một bản sao lưu khác đang chạy"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
name="tastoria_${ts}_${label}"
work="$(mktemp -d "$dir/.work.XXXXXX")"
trap 'rm -rf "$work"' EXIT

log "pg_dump"
dc exec -T postgres pg_dump -U tastoria -d tastoria -Fc --no-owner > "$work/db.dump"
[ -s "$work/db.dump" ] || die "pg_dump rỗng"
log "tệp (volume tastoria_files)"
dc exec -T nginx tar czf - -C /var/lib/tastoria/storage . > "$work/files.tar.gz"
{
  echo "created_utc=$ts"
  echo "image_tag=$(env_get TASTORIA_IMAGE_TAG)"
  echo "alembic=$(dc exec -T postgres psql -U tastoria -d tastoria -Atc 'select version_num from alembic_version' 2>/dev/null)"
  echo "published_recipes=$(dc exec -T postgres psql -U tastoria -d tastoria -Atc "select count(*) from recipes where status='published'" 2>/dev/null)"
  echo "users=$(dc exec -T postgres psql -U tastoria -d tastoria -Atc 'select count(*) from users' 2>/dev/null)"
} > "$work/MANIFEST"

out="$dir/$name.tar.gpg"
tar cf - -C "$work" MANIFEST db.dump files.tar.gz \
  | gpg --batch --yes --quiet --symmetric --cipher-algo AES256 --pinentry-mode loopback \
        --passphrase-fd 3 --output "$out.part" 3<<<"$pass"
mv "$out.part" "$out"; chmod 600 "$out"
log "đã ghi $out ($(du -h "$out" | cut -f1))"

find "$dir" -maxdepth 1 -name 'tastoria_*.tar.gpg' -mtime +"$keep" -print -delete

if [ "$local_only" = 0 ] && [ -n "$dest" ]; then
  log "đẩy lên $dest"
  rclone copy "$out" "$dest/" --retries 5
  rclone delete "$dest/" --min-age "${keep}d" --include 'tastoria_*.tar.gpg'
fi
log "xong"
