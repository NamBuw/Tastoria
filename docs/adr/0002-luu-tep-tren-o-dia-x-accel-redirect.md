# ADR 0002 — Lưu tệp trên ổ đĩa, phục vụ qua `X-Accel-Redirect`

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: M01 `core` (giao diện `Storage`), M08 `scan`, M07 `mlops`, M16 `jobs`; bảng `scan_images`, `model_versions`; UC12, UC13, UC31, UC32
- Thay cho: v1 §6.1, §7.3 (MinIO, URL ký có hạn)

## Bối cảnh

Hệ thống lưu ba loại tệp: ảnh quét gốc (1–2 ảnh mỗi lần quét, ≤ 3 MB mỗi ảnh, xoá sau 30 ngày theo BR-RETAIN-01), ảnh người dùng đồng ý góp (mục đích `photo_contribution`) và tệp mô hình ONNX/NumPy. Tổng dung lượng ước tính vài GB, một máy chủ.

Bản v1 chọn MinIO với URL ký có hạn. Hai vấn đề (review:backend_ops#8):
1. Kho mã MinIO bản cộng đồng bị archived ngày 25/04/2026 với dòng "THIS REPOSITORY IS NO LONGER MAINTAINED"; bản cộng đồng chỉ còn phát hành mã nguồn, không còn binary mới (R3 §3). Dùng image cũ nghĩa là không có bản vá bảo mật.
2. MinIO không mở ra ngoài, còn app chỉ nói chuyện với nginx, nên URL ký sinh từ endpoint nội bộ không truy cập được từ điện thoại. Đi qua nginx thì phải giữ nguyên Host để chữ ký khớp.

Yếu tố quyết định: bản vá bảo mật còn được phát hành; ít dịch vụ; kiểm quyền theo chủ sở hữu (chống BOLA) trước khi trả ảnh; job xoá 30 ngày chỉ đụng ảnh tạm.

## Các phương án

1. **Ghim một image MinIO cũ.** Không đổi mã. Không còn bản vá; vẫn vướng vấn đề URL ký.
2. **SeaweedFS (`weed mini`, Apache-2.0)**, có API S3 và presigned URL; tài liệu ghi "fine for single-node production". Thêm một dịch vụ để vận hành và sao lưu.
3. **Garage, RustFS.** Garage `--single-node` "should not be used in production"; giấy phép Garage chưa xác minh. RustFS còn nhiều tính năng ở mức Preview (R3 §3).
4. **Volume Docker riêng + `X-Accel-Redirect`.** API kiểm quyền, trả header `X-Accel-Redirect` trỏ tới một `location` `internal` của nginx; nginx đọc tệp từ volume. Chỉ dùng tính năng lõi của nginx, không cần module `secure_link` (không build sẵn).

## Quyết định

Chọn **phương án 4**, đặt sau một giao diện `Storage` trong M01 `core` để thay được bằng SeaweedFS (phương án 2) nếu báo cáo cần "tương thích S3".

- Một volume riêng, ba thư mục: `tmp/` (ảnh quét gốc, xoá sau 30 ngày), `contrib/` (ảnh đã đồng ý góp), `models/` (tệp mô hình). Tên tệp là UUID, chia thư mục theo người dùng và lần quét; đường dẫn tương đối lưu ở `scan_images.storage_key` (UNIQUE) và `model_versions.artifact_key`.
- Ảnh tải lên qua `POST /scans`: kiểm magic bytes, Pillow `MAX_IMAGE_PIXELS` = 4096², `exif_transpose`, mã hoá lại JPEG không metadata trước khi ghi (thiết kế v2 §8).
- Đọc ảnh qua `GET /scans/{id}/images/{ordinal}`: API lọc `scans.user_id` = người gọi, rồi trả `X-Accel-Redirect: /_files/tmp/...`. Không lộ đường dẫn thật, không có URL ký.
- Khi người dùng bật `photo_contribution`, ảnh được chép sang `contrib/` và `scan_images.contributed = true`. Rút đồng ý thì xoá bản ở `contrib/` theo BR-CONSENT-04.
- UC32 (`python -m tastoria.jobs.purge_images`, chạy bởi A08) chỉ quét `tmp/`, xoá tệp quá 30 ngày và ghi `scan_images.purged_at`.
- Tệp mô hình kiểm `sha256` (cột `model_versions.sha256`) trước khi nạp.

## Hệ quả

Tích cực:
- Bớt một dịch vụ so với v1. Không phụ thuộc dự án đã ngừng bảo trì.
- Quyền đọc ảnh đi qua cùng một dependency kiểm chủ sở hữu như mọi endpoint `{id}`.
- Ảnh tạm và ảnh góp tách thư mục, job xoá không thể xoá nhầm ảnh góp.

Tiêu cực, cần theo dõi:
- Một nút, không dư thừa. Hỏng ổ là mất ảnh. Ảnh tạm chấp nhận mất. `contrib/` và `models/` phải được đưa vào kế hoạch sao lưu (UC33 hiện mới nói cơ sở dữ liệu); ghi ở đề xuất bổ sung.
- Nếu sau này chạy nhiều máy, phải chuyển sang kho đối tượng; giao diện `Storage` giữ chi phí đổi ở mức một lớp cài đặt.
- Tệp và dòng DB có thể lệch (xoá tệp nhưng giao dịch DB lỗi). Job xoá ghi `purged_at` sau khi xoá tệp thành công và chạy lại được nhiều lần.

## Căn cứ

- review:backend_ops#8 (MinIO archived, URL ký mâu thuẫn): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- R3 §3, bảng giấy phép và khuyến nghị "Replace MinIO": [03-cong-nghe-vpp-phan-tich-thiet-ke.md §3](../research/raw/03-cong-nghe-vpp-phan-tich-thiet-ke.md#3-infrastructure-licensing-and-current-versions).
- Thiết kế v2 §3 dòng 19, §8 "Lưu tệp", "Ảnh tải lên"; BR-RETAIN-01 ở §4.
- MinIO archived: https://github.com/minio/minio . SeaweedFS: https://github.com/seaweedfs/seaweedfs . Garage quick start: https://garagehq.deuxfleurs.fr/documentation/quick-start/ . nginx `internal`: https://nginx.org/en/docs/http/ngx_http_core_module.html ; `secure_link` không build mặc định: https://nginx.org/en/docs/http/ngx_http_secure_link_module.html (các nguồn này do R3 mở ngày 17/10/2026).
