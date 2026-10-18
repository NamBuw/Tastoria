#!/usr/bin/env bash
# Writes deploy/.env with fresh random secrets (only when it does not exist yet). chmod 600, gitignored.
source "$(dirname "$0")/lib.sh"
[ -f "$ENV_FILE" ] && die ".env đã có, không ghi đè (xoá tay nếu thật sự muốn tạo lại — mất khoá là mất dữ liệu sức khoẻ)"
umask 077
rand_hex() { python3 -c "import secrets;print(secrets.token_hex($1))"; }
rand_b64() { python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"; }
kid="prod-$(date +%Y%m%d)"
sed \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand_hex 24)|" \
  -e "s|^TASTORIA_JWT_KEYS=.*|TASTORIA_JWT_KEYS={\"$kid\":\"$(rand_hex 32)\"}|" \
  -e "s|^TASTORIA_JWT_ACTIVE_KID=.*|TASTORIA_JWT_ACTIVE_KID=$kid|" \
  -e "s|^TASTORIA_HEALTH_ENC_KEYS=.*|TASTORIA_HEALTH_ENC_KEYS={\"$kid\":\"$(rand_b64)\"}|" \
  -e "s|^TASTORIA_HEALTH_ENC_ACTIVE_KEY_ID=.*|TASTORIA_HEALTH_ENC_ACTIVE_KEY_ID=$kid|" \
  -e "s|^TASTORIA_DSR_HMAC_KEY=.*|TASTORIA_DSR_HMAC_KEY=$(rand_hex 32)|" \
  -e "s|^BACKUP_RCLONE_DEST=.*|BACKUP_RCLONE_DEST=${BACKUP_RCLONE_DEST:-gdrive-cts:Backups/tastoria}|" \
  "$DEPLOY_DIR/.env.example" > "$ENV_FILE"
printf 'BACKUP_PASSPHRASE=%s\n' "$(rand_hex 32)" >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
log "đã tạo $ENV_FILE (600). Chép tệp này ra chỗ an toàn NGOÀI máy chủ: nó giữ khoá giải mã cột sức khoẻ và khoá giải mã bản sao lưu."
