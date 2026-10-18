# Triển khai Tastoria (Docker Compose)

Bản chạy thật trên máy chủ lab theo thiết kế v2 §10. Toàn bộ stack chỉ mở **một** cổng: `127.0.0.1:6880` (nginx).
Ra Internet qua Cloudflare Tunnel có sẵn trên máy (cấu hình tunnel nằm ngoài thư mục này).

## Thành phần

| Dịch vụ | Image | Việc | Khởi động lại |
|---|---|---|---|
| `nginx` | `tastoria-web:<tag>` (nginx 1.28 + bản web Expo dựng sẵn) | phục vụ app web ở `/`, chuyển `/api/`, `/healthz`, `/readyz` sang api, trả tệp nội bộ `/_protected/` (X-Accel-Redirect, ADR 0002) | `unless-stopped` |
| `api` | `tastoria-backend:<tag>` | uvicorn, 2 tiến trình, healthcheck `/readyz` | `unless-stopped` |
| `migrate` | `tastoria-backend:<tag>` | chạy một lần: `tastoria db upgrade`, `tastoria catalog import data/kb`, `tastoria catalog substitutes import data/kb/substitution_pairs.yaml`, rồi `models-bootstrap.sh` (đăng ký + gate mô hình đã dàn ở `deploy/models/`, deploy nếu tên đó chưa có bản nào); api, worker, scheduler chỉ chạy khi bước này thoát 0 | `no` |
| `worker` | `tastoria-backend:<tag>` | `tastoria worker`: nạp bộ phát hiện đang deploy một lần (kiểm sha256, onnxruntime 2 luồng), chạy RQ SimpleWorker hàng đợi `scan`; giới hạn `cpus: 2`, `mem_limit: 4g`; healthcheck `tastoria worker --check` | `unless-stopped` |
| `scheduler` | `tastoria-backend:<tag>` | mỗi phút `tastoria jobs sweep` (UC34, cả lần quét kẹt), mỗi 10 phút `tastoria jobs process-dsr`, mỗi giờ `tastoria jobs purge-images` (xoá ảnh quét quá 30 ngày) | `unless-stopped` |
| `postgres` | `pgvector/pgvector:pg18` | CSDL, volume `tastoria_pgdata` | `unless-stopped` |
| `valkey` | `valkey/valkey:9` | đếm đăng nhập sai (khoá theo email + IP), hàng đợi RQ `scan`, kênh long-poll `scan:<id>`; volume `tastoria_valkeydata` | `unless-stopped` |

Volume tệp: `tastoria_files` (gắn vào api/scheduler/migrate ở `/var/lib/tastoria/storage`, vào worker và nginx chỉ
đọc): `exports/` (tệp xuất dữ liệu cá nhân), `tmp/scans/<user>/<scan>/` (ảnh quét, xoá sau 30 ngày), `contrib/`
(ảnh đã góp), `models/<tên>/<phiên bản>/` (bản sao mô hình đã đăng ký + `gate.json`).

### Mô hình (ONNX)

Tệp mô hình không nằm trong git (`ml/runs/` bị gitignore) và không chép vào image. `deploy.sh` tìm bộ phát hiện ở
`ml/runs/detect/<phiên bản>/weights/best.onnx` (phiên bản mặc định `yolo26n_640_none`; đổi bằng biến
`TASTORIA_DETECTOR_VERSION`, hoặc trỏ thẳng tệp bằng `TASTORIA_DETECTOR_ONNX`), cùng
`data/processed/cv/detector/<phiên bản>.json` (chỉ số huấn luyện) và `<phiên bản>_serving.json` (ngưỡng conf chọn
trên val), rồi dàn vào `deploy/models/detector/` (gitignore). `migrate` gắn thư mục đó chỉ đọc ở `/import` và chạy
`models-bootstrap.sh`: `tastoria mlops register` (không làm gì nếu đúng các byte đó đã đăng ký) → `gate` →
`deploy --if-none`. Bản đăng ký được chép vào volume tệp, nên khi máy mới không có `ml/runs/` thì bản cũ trong volume
vẫn chạy (deploy.sh chỉ ghi cảnh báo).

`deploy --if-none` chỉ đặt con trỏ khi chưa có bản nào: deploy.sh không bao giờ ghi đè lựa chọn của người vận hành.
Đổi hoặc quay lui bản (UC30):

```bash
docker compose exec api tastoria mlops list detector
docker compose exec api tastoria mlops deploy detector <phiên bản>     # bản đã gate = validated
docker compose exec api tastoria mlops rollback detector
docker compose restart api worker                                     # nạp theo con trỏ mới, kiểm sha256
```

Chưa có mô hình độ tươi (xem backend/README.md, slice 3): chip quét không có xác suất độ tươi, lô dùng u = u_time.

Image backend cài cả gói `tastoria-ml` để lệnh nhập catalog tính dinh dưỡng bằng bộ tính tham chiếu
(`nutrition_engine: tastoria_ml`), và chép `data/kb` + `data/processed/{fct2007,usda}` vào image.

## Cấu hình: `deploy/.env`

- Tạo lần đầu: `./scripts/init-env.sh` (deploy.sh tự gọi nếu chưa có). Sinh mật khẩu PostgreSQL, khoá JWT, khoá
  AES cột sức khoẻ, khoá HMAC, mật khẩu mã hoá bản sao lưu. Quyền 600, đã nằm trong `.gitignore`.
- **Chép `.env` ra chỗ an toàn ngoài máy chủ** (trình quản lý mật khẩu). Mất `TASTORIA_HEALTH_ENC_KEYS` là mất chỉ
  số cơ thể của mọi người dùng (ADR 0005); mất `BACKUP_PASSPHRASE` là không mở được bản sao lưu. Bản sao lưu không
  chứa `.env`.
- `TASTORIA_ENV=production` đặt cứng trong `docker-compose.yml`; backend từ chối khởi động nếu còn khoá mặc định
  của môi trường dev.
- Mẫu đầy đủ: `.env.example`.

### Thư (SMTP)

Chưa có tài khoản SMTP nên `TASTORIA_MAILER=log`: thư đặt lại mật khẩu không được gửi, log api chỉ ghi tiêu đề.
Muốn gửi thật: đặt `TASTORIA_MAILER=smtp`, điền `TASTORIA_SMTP_HOST/PORT/USER/PASSWORD`, `TASTORIA_SMTP_STARTTLS=true`
(cổng 587), sửa `TASTORIA_MAIL_FROM` cho khớp tên miền gửi, rồi `docker compose up -d api`.
Link trong thư lấy từ `TASTORIA_RESET_URL_BASE` (đang là `https://safework.ctslab.net/dat-lai-mat-khau`).

## Triển khai / cập nhật

```bash
cd ~/NamBuw/Tastoria
git pull                      # hoặc commit thay đổi của mình
cd deploy
./scripts/deploy.sh
```

`deploy.sh` làm theo thứ tự:
1. dựng `tastoria-backend:<tag>` và `tastoria-web:<tag>`, `<tag>` = 12 ký tự đầu của commit (thêm `-dirty-<giờ>`
   nếu cây làm việc còn thay đổi chưa commit trong backend/ml/app/data/deploy), và dàn mô hình vào `deploy/models/`;
2. nếu CSDL đang chạy: sao lưu (chỉ lưu tại máy, nhãn `pre-<tag>`) trước khi migrate;
3. ghi `TASTORIA_IMAGE_TAG=<tag>` vào `.env`, `docker compose up -d`: postgres, valkey → migrate → api, worker,
   scheduler → nginx;
4. dừng lại báo lỗi nếu migrate thoát khác 0 (api cũ vẫn chạy nếu chưa bị thay); chờ api, worker, nginx, scheduler
   healthy; gọi `/healthz`, `/readyz` qua cổng 6880; ghi một dòng vào `releases.log`.

Lệnh nhập catalog chạy lại mỗi lần migrate. Bộ dữ liệu không đổi thì báo `"changes": 0`; đổi `data/kb` thì món đã
xuất bản bị đổi nội dung sẽ thành phiên bản mới (BR-CATALOG-01).

Chạy tay (luôn từ thư mục `deploy/` để compose đọc `.env`):

```bash
docker compose ps
docker compose logs -f api            # log JSON có request_id
docker compose exec postgres psql -U tastoria
docker compose exec api tastoria db current
```

## Kiểm tra sau khi triển khai

```bash
curl -s 127.0.0.1:6880/healthz        # {"status":"ok"}
curl -s 127.0.0.1:6880/readyz         # {"status":"ready","checks":{...}}
~/miniconda3/bin/python scripts/smoke.py http://127.0.0.1:6880 smoke.png
```

`smoke.py` mở trình duyệt: đăng ký → đồng ý + hồ sơ 60 giây → nhập 10 lô vào kho → ghép mâm hôm nay, chụp
`smoke.png`. Mỗi lần chạy tạo một tài khoản `smoke+<giờ>@example.com`.

## Quay lui

```bash
cat releases.log                              # các tag đã chạy
docker images tastoria-backend                # image cũ còn trên máy
./scripts/rollback.sh <tag-cũ>
```

Quay lui chỉ đổi code. Nếu bản mới đã chạy migration mới thì image cũ không khởi động được (alembic không biết
revision mới, migrate thoát lỗi). Khi đó khôi phục bản sao lưu `pre-<tag-mới>` rồi mới quay lui:

```bash
./scripts/restore.sh ~/backups/tastoria/tastoria_<giờ>_pre-<tag-mới>.tar.gpg
./scripts/rollback.sh <tag-cũ>
```

Dữ liệu người dùng ghi sau lúc sao lưu đó sẽ mất.

## Sao lưu

```bash
./scripts/backup.sh                 # lưu ~/backups/tastoria + đẩy lên BACKUP_RCLONE_DEST
./scripts/backup.sh --local-only
```

Mỗi bản là một tệp `tastoria_<giờ UTC>_<nhãn>.tar.gpg` (gpg AES-256, mật khẩu `BACKUP_PASSPHRASE`) gồm
`pg_dump -Fc`, nén tar của volume tệp, và `MANIFEST` (tag image, revision alembic, số món đã xuất bản, số người dùng).
Giữ `BACKUP_KEEP_DAYS` ngày (mặc định 14) ở cả máy và Drive. Đích Drive mặc định: `gdrive-cts:Backups/tastoria`
(Drive của xuannamservice@gmail.com).

Chưa đặt lịch tự động. Muốn chạy hằng ngày lúc 03:15 giờ VN (máy chủ chạy giờ UTC), thêm vào `crontab -e`:

```
15 20 * * * /home/namnx/NamBuw/Tastoria/deploy/scripts/backup.sh >> /home/namnx/backups/tastoria/backup.log 2>&1
```

## Khôi phục

```bash
# lấy bản trên Drive về nếu cần
rclone copy gdrive-cts:Backups/tastoria/<tên>.tar.gpg ~/backups/tastoria/

# diễn tập: khôi phục vào container PostgreSQL tạm, in số món / người dùng / revision, không đụng stack đang chạy
./scripts/restore.sh --verify ~/backups/tastoria/<tên>.tar.gpg

# khôi phục thật: hỏi xác nhận (gõ "khoi phuc"), tự sao lưu trạng thái hiện tại (nhãn pre-restore),
# dừng nginx/api/scheduler, tạo lại CSDL, pg_restore, chép lại volume tệp, chạy lại migrate rồi bật stack
./scripts/restore.sh ~/backups/tastoria/<tên>.tar.gpg
```

Tham số cấp CSDL (`tastoria.rice_bowl_kcal`, `tastoria.kcal_half_width`) không nằm trong `pg_dump`; bước
`migrate` chạy lại lệnh nhập catalog và đặt lại chúng.

Khôi phục sang máy khác: chép repo + `.env` đã cất riêng, `./scripts/deploy.sh --no-backup`, rồi
`./scripts/restore.sh <tệp>`.

## Đứng sau Cloudflare

- App web và API cùng một origin (app gọi `/api/v1`), nên không cần CORS, không có cookie. Refresh token trên web
  nằm trong `sessionStorage`.
- Cloudflare kết thúc TLS. nginx gửi `X-Forwarded-Proto: https` cho api và lấy IP thật từ `CF-Connecting-IP`
  (chỉ tin khi request đến từ mạng Docker / loopback), nên khoá đăng nhập theo (email, IP) đếm đúng từng người.
- Bộ đệm: `/_expo/*` và `/assets/*` có hash trong tên tệp → `max-age=31536000, immutable`; `index.html` và mọi đường
  dẫn của app (SPA) → `no-cache`; `/api/*` → `no-store`. Sau khi deploy không cần purge cache Cloudflare.
- Ảnh quét tối đa 2 × 3 MB: `client_max_body_size 8m` (Cloudflare gói Free cho tới 100 MB). Ảnh quét trả qua
  `X-Accel-Redirect` tới `/_protected/` sau khi API kiểm chủ sở hữu.
- Trang giới thiệu tĩnh ở `/gioi-thieu/` (thư mục `landing/`, nướng vào image nginx; đoạn cấu hình lấy từ
  `landing/nginx-snippet.conf`), tệp APK ở `/tai-ve/tastoria-*.apk` (thư mục `dist/` của repo gắn chỉ đọc; chỉ tệp
  `.apk` được phục vụ, `tastoria-vp-kit.zip` → 404).

## Tệp trong thư mục này

```
docker-compose.yml         stack (project name: tastoria)
backend.Dockerfile         python 3.12-slim + uv, người dùng không phải root (uid 10001)
web.Dockerfile             node 22 dựng bản web Expo (EXPO_PUBLIC_API_URL=/api/v1) → nginx 1.28-alpine
*.Dockerfile.dockerignore  danh sách tệp được đưa vào từng image
nginx/                     nginx.conf, tastoria.conf
.env.example               mẫu cấu hình (.env thật không commit)
scripts/                   init-env, deploy, rollback, backup, restore, smoke.py, scheduler.sh + models-bootstrap.sh
                           (chạy trong container)
models/                    mô hình deploy.sh dàn cho migrate (gitignore)
smoke.png                  ảnh mâm cơm từ lần smoke test gần nhất
```
