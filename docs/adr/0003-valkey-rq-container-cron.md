# ADR 0003 — Valkey + RQ cho việc nền, container `scheduler` (cron) cho việc định kỳ

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: M08 `scan` (job suy luận), M03 `privacy` (job xuất dữ liệu, xoá tài khoản), M02 `identity` (đếm đăng nhập sai), M16 `jobs`; actor A08; UC12, UC06, UC07, UC32, UC33, UC34
- Thay cho: v1 §6.1, §7.3 (Redis, "chỉ một loại job")

## Bối cảnh

Ba loại việc không chạy được trong request HTTP:
- Suy luận ảnh (UC12): ONNX trên CPU, mục tiêu p95 ≤ 3 s ở server (NFR-PERF-01). API trả 202, worker xử lý, app long-poll `GET /scans/{id}?wait=10`.
- Xuất dữ liệu cá nhân (UC06) và xoá tài khoản (UC07): chạy lâu, phải hoàn tất ≤ 24 giờ (NFR-PRIV-01).
- Việc định kỳ: xoá ảnh quá hạn (UC32), sao lưu (UC33), dọn job kẹt, token và khoá lũy đẳng hết hạn (UC34).

Ngoài ra cần một kho có TTL để đếm đăng nhập sai theo (email, IP) và khoá 15 phút sau 5 lần (NFR-SEC-02).

Redis từ 8.0 phát hành theo RSALv2, SSPLv1 hoặc AGPLv3; bản 7.2 trở về trước mới là BSD-3 (R3 §3). v1 ghi "Redis chỉ chứa job" nên không có chỗ đếm đăng nhập sai (review:backend_ops#6). v1 cũng không đặc tả vòng đời job: không timeout, không trạng thái lỗi, job mồ côi (review:backend_ops#4).

## Các phương án

1. **Celery + Redis.** Nhiều tính năng (beat, retry, routing). Cấu hình nặng so với 3 loại job; vướng giấy phép Redis 8.
2. **RQ + Valkey.** RQ 2.12.0 (30/08/2026) "requires Redis >= 5 or Valkey >= 7.2"; Valkey 9.1.2 BSD-3-Clause dưới LF Projects (R3 §3). Đơn giản, đủ cho một hàng đợi.
3. **Hàng đợi trên PostgreSQL** (`SELECT … FOR UPDATE SKIP LOCKED`). Không thêm dịch vụ, giao dịch cùng DB. Vẫn cần chỗ có TTL cho đếm đăng nhập sai; tự viết retry và timeout.
4. **Việc định kỳ chạy trong tiến trình API** (APScheduler) hoặc **cron trên máy host**. APScheduler chạy trùng khi API có nhiều worker Uvicorn. Cron host nằm ngoài Compose, khó tái lập.

## Quyết định

- **Valkey 9 + RQ 2** (phương án 2). Valkey giữ hàng đợi RQ và bộ đếm đăng nhập sai có TTL. Valkey không phải nguồn sự thật: trạng thái quét nằm ở `scans.status`.
- **Worker** dùng chung image với API (ADR 0001), nạp phiên ONNX một lần trước khi nhận job, `intra_op_num_threads = 2`, tắt spin. Job quét: timeout 30 s, thử lại tối đa 2 lần (`scans.attempts`).
- **Container `scheduler`** chạy cron, mỗi dòng gọi một lệnh trong `model.yaml`: `python -m tastoria.jobs.purge_images` (UC32), `python -m tastoria.jobs.backup` (UC33), `python -m tastoria.jobs.sweep` (UC34). Sweeper chạy mỗi phút.
- Sweeper (UC34) là lưới an toàn khi mất job trong Valkey: quét `scans` ở `queued` hoặc `processing` quá hạn, xếp lại nếu `attempts` còn, nếu không thì chuyển `failed` hoặc `expired`. Cùng lệnh dọn `refresh_tokens` hết hạn, `password_resets` hết hạn và `idempotency_keys` quá 48 giờ.
- Enqueue job quét **sau khi** giao dịch tạo `scans` đã commit (xem ADR 0007). Nếu tiến trình chết giữa commit và enqueue, `scans.enqueued_at` rỗng và sweeper xếp lại.

## Hệ quả

Tích cực:
- Mọi phần mềm hạ tầng dùng giấy phép BSD/Apache/MIT.
- Valkey mất dữ liệu (khởi động lại không có AOF) không làm sai trạng thái: sweeper đưa các lần quét về trạng thái đúng. Bộ đếm đăng nhập sai bị đặt lại, chấp nhận được.
- Lịch định kỳ nằm trong Compose, tái lập được trên máy khác.

Tiêu cực, cần theo dõi:
- Thêm một dịch vụ (`valkey`) và một container (`scheduler`) phải giám sát.
- RQ không có lập lịch tích hợp tốt bằng Celery beat; đã chuyển phần này sang cron.
- Một worker xử lý tuần tự; NFR-PERF-01 đo với 1 worker và 5 người đồng thời, cần đo thật trước khi khoá ngưỡng.
- Cron trong container chạy theo múi giờ của container; đặt `TZ=Asia/Ho_Chi_Minh` hoặc ghi giờ UTC rõ ràng trong crontab.

## Căn cứ

- review:backend_ops#4 (vòng đời job quét), review:backend_ops#6 (đếm đăng nhập sai không có chỗ), review:sad#14 (thiếu việc định kỳ trong kiến trúc triển khai): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- R3 §3 (Redis, Valkey, RQ): [03-cong-nghe-vpp-phan-tich-thiet-ke.md §3](../research/raw/03-cong-nghe-vpp-phan-tich-thiet-ke.md#3-infrastructure-licensing-and-current-versions).
- Thiết kế v2 §8 "Quét bất đồng bộ", "Worker", "Việc định kỳ"; §10.
- Giấy phép Redis: https://redis.io/legal/licenses/ . Valkey: https://github.com/valkey-io/valkey , https://valkey.io/download/ . RQ: https://pypi.org/project/rq/ (R3 mở ngày 17/10/2026).
