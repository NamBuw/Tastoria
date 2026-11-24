#!/usr/bin/env bash
# Writes deploy/.env with fresh random secrets (or appends missing keys when called with --ensure-missing).
# chmod 600, gitignored. Never prints secret values.
source "$(dirname "$0")/lib.sh"

umask 077
rand_hex() { python3 -c "import secrets;print(secrets.token_hex($1))"; }
rand_b64() { python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"; }

ensure_key() { # ensure_key NAME VALUE -> appends only if key absent
  local k="$1" v="$2"
  if ! grep -qE "^${k}=" "$ENV_FILE"; then
    printf '%s=%s\n' "$k" "$v" >> "$ENV_FILE"
  fi
}

if [ "${1:-}" = "--ensure-missing" ] && [ -f "$ENV_FILE" ]; then
  chmod 600 "$ENV_FILE"
  ensure_key POSTGRES_APP_PASSWORD "$(rand_hex 24)"
  ensure_key POSTGRES_JOBS_PASSWORD "$(rand_hex 24)"
  ensure_key VALKEY_PASSWORD "$(rand_hex 24)"
  survey_kid="prod-survey-$(date +%Y%m%d)"
  ensure_key TASTORIA_SURVEY_JWT_KEYS "{\"$survey_kid\":\"$(rand_hex 32)\"}"
  ensure_key TASTORIA_SURVEY_JWT_ACTIVE_KID "$survey_kid"
  ensure_key TASTORIA_TRAINING_EXPORT_HMAC_KEY "$(rand_hex 32)"
  ensure_key BACKUP_PASSPHRASE "$(rand_hex 32)"
  if grep -qE '^TASTORIA_MAIL_FROM=Tastoria <' "$ENV_FILE"; then
    tmp="$(mktemp "$DEPLOY_DIR/.env.XXXXXX")"
    sed 's|^TASTORIA_MAIL_FROM=Tastoria <\(.*\)>|TASTORIA_MAIL_FROM=Mỹ Vị <\1>|' "$ENV_FILE" > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
  fi
  chmod 600 "$ENV_FILE"
  log "đã kiểm tra và bổ sung các khoá còn thiếu trong .env (không ghi đè khoá hiện có)"
  exit 0
fi

[ -f "$ENV_FILE" ] && die ".env đã có, không ghi đè (xoá tay nếu thật sự muốn tạo lại — mất khoá là mất dữ liệu sức khoẻ)"
kid="prod-$(date +%Y%m%d)"
survey_kid="prod-survey-$(date +%Y%m%d)"
sed \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand_hex 24)|" \
  -e "s|^POSTGRES_APP_PASSWORD=.*|POSTGRES_APP_PASSWORD=$(rand_hex 24)|" \
  -e "s|^POSTGRES_JOBS_PASSWORD=.*|POSTGRES_JOBS_PASSWORD=$(rand_hex 24)|" \
  -e "s|^VALKEY_PASSWORD=.*|VALKEY_PASSWORD=$(rand_hex 24)|" \
  -e "s|^TASTORIA_JWT_KEYS=.*|TASTORIA_JWT_KEYS={\"$kid\":\"$(rand_hex 32)\"}|" \
  -e "s|^TASTORIA_JWT_ACTIVE_KID=.*|TASTORIA_JWT_ACTIVE_KID=$kid|" \
  -e "s|^TASTORIA_SURVEY_JWT_KEYS=.*|TASTORIA_SURVEY_JWT_KEYS={\"$survey_kid\":\"$(rand_hex 32)\"}|" \
  -e "s|^TASTORIA_SURVEY_JWT_ACTIVE_KID=.*|TASTORIA_SURVEY_JWT_ACTIVE_KID=$survey_kid|" \
  -e "s|^TASTORIA_HEALTH_ENC_KEYS=.*|TASTORIA_HEALTH_ENC_KEYS={\"$kid\":\"$(rand_b64)\"}|" \
  -e "s|^TASTORIA_HEALTH_ENC_ACTIVE_KEY_ID=.*|TASTORIA_HEALTH_ENC_ACTIVE_KEY_ID=$kid|" \
  -e "s|^TASTORIA_DSR_HMAC_KEY=.*|TASTORIA_DSR_HMAC_KEY=$(rand_hex 32)|" \
  -e "s|^TASTORIA_TRAINING_EXPORT_HMAC_KEY=.*|TASTORIA_TRAINING_EXPORT_HMAC_KEY=$(rand_hex 32)|" \
  -e "s|^BACKUP_RCLONE_DEST=.*|BACKUP_RCLONE_DEST=${BACKUP_RCLONE_DEST:-gdrive-cts:Backups/tastoria}|" \
  "$DEPLOY_DIR/.env.example" > "$ENV_FILE"
printf 'BACKUP_PASSPHRASE=%s\n' "$(rand_hex 32)" >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
log "đã tạo $ENV_FILE (600). Chép tệp này ra chỗ an toàn NGOÀI máy chủ: nó giữ khoá giải mã cột sức khoẻ và khoá giải mã bản sao lưu."
