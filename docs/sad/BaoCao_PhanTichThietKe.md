# Báo cáo phân tích thiết kế hệ thống Tastoria

| Mục | Nội dung |
|---|---|
| Hệ thống | Tastoria — gợi ý một mâm cơm Việt từ ảnh tủ lạnh |
| Phiên bản báo cáo | 1.0, 17/10/2026 |
| Nguồn sự thật | [`model.yaml`](model.yaml): 10 tác nhân, 10 gói, 34 use case, 16 module, 62 bảng, 3 view, 70 endpoint, 13 lệnh CLI, 8 máy trạng thái, 39 BR, 10 NFR |
| Thiết kế gốc | [Thiết kế v2](../superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md) (BR ở §4, NFR ở §11, danh mục sản phẩm ở §12) |
| Chuẩn áp dụng | ISO/IEC/IEEE 29148:2018 (SRS), A. Cockburn (đặc tả use case), OMG UML 2.5.1 (sơ đồ), chuẩn hoá đến BCNF (CSDL), OpenAPI 3.1 và RFC 9457 (API) |

Báo cáo này gom các sản phẩm phân tích thiết kế của Tastoria. Mỗi mục tóm tắt và dẫn tới tài liệu chi tiết; số liệu trong báo cáo lấy từ các tài liệu đó. Mọi mã (A.., PK.., UC.., M.., tên bảng, endpoint) lấy đúng từ `model.yaml`; `docs/sad/tools/check_refs.py` kiểm điều này.

## Mục lục

1. [Giới thiệu](#1-giới-thiệu)
2. [Tóm tắt đặc tả yêu cầu](#2-tóm-tắt-đặc-tả-yêu-cầu)
3. [Mô hình use case](#3-mô-hình-use-case)
4. [Trích đặc tả use case](#4-trích-đặc-tả-use-case)
5. [Mô hình hành vi](#5-mô-hình-hành-vi)
6. [Mô hình cấu trúc](#6-mô-hình-cấu-trúc)
7. [Thiết kế cơ sở dữ liệu](#7-thiết-kế-cơ-sở-dữ-liệu)
8. [Hợp đồng API](#8-hợp-đồng-api)
9. [Kiểm thử](#9-kiểm-thử)
10. [Quyết định kiến trúc (ADR)](#10-quyết-định-kiến-trúc-adr)
11. [Đánh giá tác động xử lý dữ liệu cá nhân](#11-đánh-giá-tác-động-xử-lý-dữ-liệu-cá-nhân)
12. [Ma trận truy vết](#12-ma-trận-truy-vết)
13. [Phụ lục: danh mục tệp](#13-phụ-lục-danh-mục-tệp)

---

## 1. Giới thiệu

### 1.1. Bài toán

Người nấu ở hộ gia đình Việt thường mở tủ lạnh mà không biết nấu gì, đồ mua dư bị bỏ phí, và việc cân đối calo hay tránh dị ứng phải làm bằng tay. Tastoria nhận 1–2 ảnh tủ lạnh hoặc túi đồ vừa mua, nhận diện và đếm nguyên liệu, ước độ tươi, lưu kho theo lô, rồi đề xuất **một** mâm cơm (mặn + rau + canh, hoặc 2 món khi ăn một mình) từ đồ đang có. Mâm ưu tiên lô sắp hỏng, bám mục tiêu năng lượng và loại chắc chắn món có chất gây dị ứng đã khai. Hệ thống lập lịch nấu song song cả mâm, trừ kho khi nấu xong và ghi nhật ký tuần.

Ngoài luồng chính, hệ thống có trang khảo sát gu món cho người ngoài (không cần tài khoản), luồng quyền dữ liệu cá nhân theo Luật 91/2025/QH15, công cụ dòng lệnh cho nhân sự nhập kho món và vận hành mô hình, và tác vụ định kỳ.

### 1.2. Phạm vi hệ thống

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| App | Expo (React Native), một mã nguồn cho Android và web | Giao diện người dùng; SQLite cho catalog và phiên nấu khi mất mạng; outbox gửi lại |
| API | FastAPI, modular monolith 16 module M01–M16, tiền tố `/api/v1` | 70 endpoint |
| Worker | Valkey + RQ, ONNX Runtime trên CPU | Suy luận ảnh, xuất dữ liệu cá nhân, xoá tài khoản |
| Scheduler | Container cron | UC32–UC34 |
| CSDL | PostgreSQL 18 + pgvector 0.8 | 62 bảng, 3 view |
| Lưu tệp | Ổ đĩa, nginx `X-Accel-Redirect` | Ảnh quét, bản xuất, tệp mô hình |
| CLI | `tastoria …` trong container api | Thao tác của A05, A06 |

Ngoài phạm vi v2: tính calo từ ảnh món đã nấu, mã vạch, thực đơn tuần, thông báo đẩy, đặt hàng, nhiều hồ sơ trong một hộ, bản iOS. Huấn luyện mô hình chạy ngoài hệ thống trên GPU của lab; hệ thống chỉ nhận mô hình đã huấn luyện qua UC29–UC30.

### 1.3. Phương pháp

1. Chốt mô hình chung trong `model.yaml` (mã tác nhân, gói, UC, module, bảng, cột, endpoint, máy trạng thái).
2. Viết đặc tả 34 use case theo mẫu Cockburn, mỗi UC có FR nguyên tử kèm tiêu chí chấp nhận Given/When/Then.
3. Tổng hợp SRS theo ISO/IEC/IEEE 29148:2018 từ các UC (bảng FR sinh bằng script).
4. Vẽ sơ đồ UML và ERD bằng PlantUML; viết DDL PostgreSQL và kiểm bằng container thật; phân tích phụ thuộc hàm và dạng chuẩn từng bảng.
5. Viết hợp đồng OpenAPI 3.1, kế hoạch kiểm thử, ADR, hồ sơ đánh giá tác động dữ liệu cá nhân.
6. Sinh ma trận truy vết và kiểm chéo bằng script; soi phản biện theo ba góc (ký pháp UML, thiết kế CSDL, chất lượng yêu cầu) rồi sửa.

Sơ đồ ngữ cảnh (mức 0) cho thấy ranh giới hệ thống và các tác nhân:

![CTX01 — Sơ đồ ngữ cảnh](../uml/out/context/CTX01-ngu-canh.svg)

*Hình 1. CTX01 — Tastoria là hộp đen; tác nhân người tương tác qua app/web, `/admin/*` hoặc CLI; hệ thống ngoài là dịch vụ email A09 và công cụ gán nhãn A10.*

---

## 2. Tóm tắt đặc tả yêu cầu

Chi tiết: [01-SRS.md](01-SRS.md) (SRS 1.1). Thuật ngữ: [00-thuat-ngu.md](00-thuat-ngu.md).

### 2.1. Số lượng yêu cầu

| Loại | Số lượng | Ghi chú |
|---|---|---|
| Use case | 34 (M 24 · S 8 · C 2) | 10 gói PK1–PK10 |
| Yêu cầu chức năng (FR) | 446 (M 339 · S 91 · C 16) | Mã `FR-<UC>-<số>`, nằm trong tệp UC, SRS §3.2 sinh tự động |
| Quy tắc nghiệp vụ (BR) | 39 | SRS §3.3, mỗi BR có tiêu chí chấp nhận |
| Yêu cầu phi chức năng (NFR) | 10 mã, 31 điều khoản | 10 điều khoản gốc + 21 điều khoản con `.b`–`.e`, phân loại theo ISO/IEC 25010:2023 |
| Ràng buộc | RB-01 … RB-08 | Pháp lý, GPU dùng chung, máy 2 vCPU/4 GB, AGPL, nền tảng, công cụ nộp sơ đồ |
| Giả định, phụ thuộc | GD-01 … GD-07, PT-01 … PT-06 | SRS §2.5 |

### 2.2. Tác nhân

| Mã | Tác nhân | Loại |
|---|---|---|
| A01 | Khách | Người |
| A02 | Người dùng (tổng quát hoá từ A01) | Người |
| A03 | Người tham gia khảo sát | Người |
| A04 | Quản trị viên | Người |
| A05 | Người biên soạn công thức | Người |
| A06 | Người vận hành mô hình | Người |
| A07 | Người gán nhãn | Người |
| A08 | Bộ lập lịch | Thời gian |
| A09 | Dịch vụ email | Hệ thống ngoài |
| A10 | Công cụ gán nhãn | Hệ thống ngoài |

Người ăn cùng không phải tác nhân vì không tương tác với hệ thống; A02 khai nhóm dị ứng của họ cho từng bữa (`meal_plan_coeater_allergens`). Đây là độ lệch có chủ đích so với thiết kế v2 §12, ghi ở SRS §2.6.

### 2.3. NFR chính

| Mã | Nội dung (ngưỡng chấp nhận SRS 1.1) |
|---|---|
| NFR-PERF-01 | Xử lý quét ở server (`enqueued_at` → `finished_at`) p95 ≤ 3 s trên máy `--cpus=2 --memory=4g`, 1 worker, 5 người dùng đồng thời, ≥ 300 mẫu |
| NFR-PERF-02 | Tạo mâm (`POST /meal-plans`) p95 ≤ 1 s với kho 200 món, 10 người dùng đồng thời, ≥ 300 yêu cầu |
| NFR-PERF-03 | Quét đầu–cuối trên điện thoại p95 ≤ 8 s (Wi-Fi), ≤ 12 s (4G) |
| NFR-REL-01 | Khôi phục từ sao lưu: RPO ≤ 24 h, RTO ≤ 2 h, diễn tập ≥ 1 lần trước khi nộp |
| NFR-SEC-01 | Access JWT 15 phút; refresh token 30 ngày, xoay vòng theo family; dùng lại refresh đã thu hồi thì thu hồi cả family |
| NFR-SEC-02 | Khoá đăng nhập 15 phút sau 5 lần sai liên tiếp theo (email, IP), trả 429 |
| NFR-PRIV-01 | Yêu cầu chủ thể dữ liệu loại tự động (`export`, `delete`, `withdraw`) hoàn tất ≤ 24 h; loại thủ công (`correct`, `restrict`, `object`) xác nhận ≤ 24 h |
| NFR-A11Y-01 | WCAG 2.2 mức AA cho app và trang khảo sát; vùng chạm ≥ 44 × 44 dp |
| NFR-USE-01 | SUS ≥ 68; ≥ 80% người thử hoàn thành mỗi nhiệm vụ (8–10 người thử) |
| NFR-MAINT-01 | Độ phủ dòng và nhánh ≥ 80% từng module `meal`, `pantry`, `profile`, `cooking`; ranh giới module kiểm bằng import-linter |

Ngưỡng đầy đủ, điều kiện đo và quy trình đổi ngưỡng ở SRS §3.4. Các điểm còn mở được theo dõi bằng mã TBD ở SRS Phụ lục C.

---

## 3. Mô hình use case

### 3.1. Sơ đồ tổng quan

![UCD00 — Tổng quan use case](../uml/out/usecase/UCD00-tong-quan.svg)

*Hình 2. UCD00 — 34 use case trong 10 gói, 10 tác nhân; quan hệ include/extend theo `model.yaml`.*

Sơ đồ theo gói: [UCD01](../uml/out/usecase/UCD01-tai-khoan-bao-mat.svg), [UCD02](../uml/out/usecase/UCD02-quyen-rieng-tu.svg), [UCD03](../uml/out/usecase/UCD03-ho-so-muc-tieu.svg), [UCD04](../uml/out/usecase/UCD04-kho-quet.svg), [UCD05](../uml/out/usecase/UCD05-mam-com.svg), [UCD06](../uml/out/usecase/UCD06-nau-nhat-ky.svg), [UCD07](../uml/out/usecase/UCD07-khao-sat-gu.svg), [UCD08](../uml/out/usecase/UCD08-quan-tri-noi-dung-du-lieu.svg), [UCD09](../uml/out/usecase/UCD09-van-hanh-mo-hinh.svg), [UCD10](../uml/out/usecase/UCD10-tac-vu-dinh-ky.svg).

Hai gói của luồng chính:

![UCD04 — Gói PK4 Kho & quét](../uml/out/usecase/UCD04-kho-quet.svg)

*Hình 3. UCD04 — UC12 include UC13; UC14 quản lý lô kho.*

![UCD05 — Gói PK5 Mâm cơm](../uml/out/usecase/UCD05-mam-com.svg)

*Hình 4. UCD05 — UC16, UC17 extend UC15; UC18 extend UC17 và extend UC15 khi không có mâm khả thi (BR-TRAY-06).*

### 3.2. Danh sách use case

| UC | Tên | Gói | Tác nhân chính | Tác nhân phụ | Quan hệ | MoSCoW |
|---|---|---|---|---|---|---|
| UC01 | Đăng ký tài khoản | PK1 | A01 | | | M |
| UC02 | Đăng nhập | PK1 | A01 | | | M |
| UC03 | Đăng xuất (một hoặc mọi thiết bị) | PK1 | A02 | | | M |
| UC04 | Đặt lại mật khẩu | PK1 | A01 | A09 | | S |
| UC05 | Quản lý đồng ý theo mục đích | PK2 | A02 | | | M |
| UC06 | Tải về dữ liệu cá nhân | PK2 | A02 | | | M |
| UC07 | Xoá tài khoản và toàn bộ dữ liệu | PK2 | A02 | | | M |
| UC08 | Yêu cầu sửa, hạn chế hoặc phản đối xử lý | PK2 | A02 | A04 | | C |
| UC09 | Thiết lập hồ sơ 60 giây | PK3 | A02 | | include UC05 | M |
| UC10 | Cập nhật hồ sơ, dị ứng, chế độ ăn, cài đặt bếp | PK3 | A02 | | | M |
| UC11 | Đặt mục tiêu năng lượng (gợi ý / tự nhập / chuyên gia) | PK3 | A02 | | | M |
| UC12 | Quét nguyên liệu (toàn tủ hoặc đồ vừa mua) | PK4 | A02 | | include UC13 | M |
| UC13 | Xác nhận và sửa kết quả quét | PK4 | A02 | | | M |
| UC14 | Quản lý kho (sửa lượng, ngày mua, bỏ đồ, xác nhận đồ cần kiểm tra) | PK4 | A02 | | | M |
| UC15 | Nhận mâm cơm hôm nay | PK5 | A02 | | | M |
| UC16 | Đổi một món | PK5 | A02 | | extend UC15 | M |
| UC17 | Xem và chọn thay thế nguyên liệu thiếu (Thiếu gì?) | PK5 | A02 | | extend UC15 | M |
| UC18 | Quản lý danh sách đi chợ | PK5 | A02 | | extend UC17; extend UC15 (không có mâm khả thi) | S |
| UC19 | Nấu cả mâm | PK6 | A02 | | | M |
| UC20 | Hoàn tất bữa nấu (nấu xong một chạm) | PK6 | A02 | | | M |
| UC21 | Hoàn tác trừ kho | PK6 | A02 | | extend UC20 | S |
| UC22 | Xem nhật ký tuần | PK6 | A02 | | | S |
| UC23 | Tham gia khảo sát gu món ăn | PK7 | A03 | | | M |
| UC24 | Quản lý đợt khảo sát (tạo phiếu, xuất kết quả) | PK7 | A06 | | | S |
| UC25 | Nhập và kiểm tra kho công thức, nguyên liệu | PK8 | A05 | | | M |
| UC26 | Quản lý cặp thay thế nguyên liệu | PK8 | A05 | | | S |
| UC27 | Xử lý yêu cầu dữ liệu và xem nhật ký kiểm toán | PK8 | A04 | | | S |
| UC28 | Xuất dữ liệu huấn luyện đã bí danh hoá | PK9 | A06 | | | S |
| UC29 | Đăng ký và kiểm định phiên bản mô hình | PK9 | A06 | | | M |
| UC30 | Triển khai và quay lui phiên bản mô hình | PK9 | A06 | | | M |
| UC31 | Gán nhãn ảnh góp | PK9 | A07 | A10 | | C |
| UC32 | Xoá ảnh quét quá hạn | PK10 | A08 | | | M |
| UC33 | Sao lưu cơ sở dữ liệu | PK10 | A08 | | | M |
| UC34 | Dọn job quét kẹt, token và khoá lũy đẳng hết hạn | PK10 | A08 | | | M |

Tổng: M 24, S 8, C 2. Số FR theo UC và theo MoSCoW ở SRS Phụ lục A. Đặc tả đầy đủ từng UC ở [`use-cases/`](use-cases/).

Mức mục tiêu theo Cockburn: UC02, UC13, UC16, UC17, UC21 ở mức mục tiêu con; các UC còn lại ở mức mục tiêu người dùng (UC32–UC34 là mục tiêu của tác nhân thời gian A08). Quy tắc viết đặc tả ở SRS §2.2.

---

## 4. Trích đặc tả use case

Bốn UC của luồng lõi quét → kho → mâm → nấu xong. Phần trích gồm mục tiêu, tiền điều kiện, đảm bảo, kịch bản chính và các mở rộng chính; bảng FR, dữ liệu, giao diện và câu hỏi mở nằm trong tệp gốc.

### 4.1. UC12 — Quét nguyên liệu (toàn tủ hoặc đồ vừa mua)

Đặc tả đầy đủ: [use-cases/UC12.md](use-cases/UC12.md) (19 FR, FR-12-01 … FR-12-19).

| Mục | Nội dung |
|---|---|
| Mục tiêu | A02 chụp 1–2 ảnh tủ lạnh (`fridge`) hoặc túi đồ vừa mua (`haul`); hệ thống nhận diện, đếm, ước độ tươi và trả danh sách chip. Kho chưa bị ghi ở UC12. |
| Mức, gói | Mục tiêu người dùng; PK4 |
| Tác nhân chính | A02 |
| Tiền điều kiện | A02 đã đăng nhập; có bản `detector` đang chạy trong `model_deployments`; app có quyền camera hoặc thư viện ảnh |
| Đảm bảo tối thiểu | Không ghi giao dịch kho; một `Idempotency-Key` sinh nhiều nhất một `scans`; ảnh lưu không có EXIF; mọi scan kết thúc ở `done`, `failed` hoặc `expired` |
| Đảm bảo khi thành công | `scans.status = done` có phiên bản mô hình và tiền xử lý; có `scan_images`, `detections`, `scan_items` (`origin = model`); app ở màn Xác nhận (UC13) |
| Kích hoạt | A02 bấm "Chụp tủ lạnh" hoặc "Đồ vừa mua" |
| Quy tắc | BR-SCAN-01, BR-PANTRY-03, BR-FRESH-02, BR-RETAIN-01, BR-CONSENT-01 |
| Endpoint | `POST /scans`, `GET /scans/{id}` |

**Kịch bản chính**

| # | Bước |
|---|---|
| 1 | A02 chọn chế độ, chụp ảnh thứ nhất; tuỳ chọn chụp ảnh thứ hai và đánh dấu "ngăn khác". |
| 2 | App nén ảnh về cạnh dài 1.280 px, sinh `Idempotency-Key`, gửi `POST /scans`. |
| 3 | Hệ thống kiểm khoá lũy đẳng, số ảnh, dung lượng, loại tệp, số điểm ảnh; xoay theo EXIF và lưu JPEG không metadata. |
| 4 | Hệ thống ghi lần quét `queued`, đánh dấu ảnh góp nếu có đồng ý `photo_contribution`, đưa việc nhận diện vào hàng đợi. |
| 5 | Hệ thống trả 202 kèm `Location` và `Retry-After`. |
| 6 | App hỏi trạng thái theo long-poll (tối đa 10 s mỗi lần). |
| 7 | Hệ thống chạy bộ phát hiện trên từng ảnh, ghi các khung. |
| 8 | Hệ thống ước xác suất độ tươi cho khung thuộc lớp có mô hình độ tươi (BR-FRESH-02). |
| 9 | Hệ thống quy lớp thị giác về nguyên liệu, gộp khung thành chip và đếm theo BR-SCAN-01. |
| 10 | Hệ thống ghi phiên bản mô hình và tiền xử lý, chuyển lần quét sang `done`. |
| 11 | Hệ thống trả danh sách chip; với `fridge` kèm các lô `in_stock` không thấy. |
| 12 | App mở màn Xác nhận nguyên liệu. **[include UC13]** |

**Mở rộng chính**

- 2a. Mất mạng khi tải lên: app gửi lại với cùng `Idempotency-Key`; server trả lại nguyên văn phản hồi lần đầu.
- 3b. Cùng key, thân khác: 422 `idempotency_key_reused`.
- 3d. Ảnh > 3 MB: 413 `image_too_large`; không phải ảnh: 415 `unsupported_media_type`; > 4096²: 422 `image_too_many_pixels`.
- 4a. Không có bản `detector` đang chạy: 503 `model_unavailable` kèm `Retry-After`.
- 6a. Quá 20 s tổng: app hiện "Thử lại / Nhập tay" (FR-12-15).
- 7a. Lỗi suy luận: đưa lại hàng đợi khi `attempts` < 3; lần thứ 3 vẫn lỗi thì `failed` (FR-12-19).
- 7b. Job quá 30 s hoặc worker chết: sweeper UC34 đưa lại hàng đợi hoặc đặt `expired`.
- 9a. Không phát hiện khung nào: `done` với danh sách rỗng.
- 11a. Chế độ `haul`: không trả danh sách lô không thấy (BR-PANTRY-03).

### 4.2. UC13 — Xác nhận và sửa kết quả quét

Đặc tả đầy đủ: [use-cases/UC13.md](use-cases/UC13.md) (20 FR, FR-13-01 … FR-13-20).

| Mục | Nội dung |
|---|---|
| Mục tiêu | A02 sửa chip (đổi tên, sửa số, chọn mức ít/vừa/nhiều, thêm, xoá), xác nhận chip ở mức "kiểm tra trước khi dùng", rồi đưa vào kho. Chỉ bước xác nhận mới ghi kho. |
| Mức, gói | Mục tiêu con (UC12 include; cũng mở trực tiếp từ một scan `done`); PK4 |
| Tiền điều kiện | A02 đã đăng nhập; scan thuộc A02 và ở `done` |
| Đảm bảo tối thiểu | Không tạo hay đổi `pantry_lots`/`pantry_transactions` trước khi xác nhận (BR-SCAN-02); xác nhận ghi toàn bộ hoặc không ghi gì; gửi lại chỉ ghi kho một lần |
| Đảm bảo khi thành công | `scans.status = confirmed`; mỗi chip còn lại tạo lô mới hoặc ghi quan sát vào lô có sẵn; với `fridge`, lô không thấy chuyển `not_seen` |
| Quy tắc | BR-SCAN-02, BR-PANTRY-01, BR-PANTRY-03, BR-QTY-01, BR-QTY-02, BR-FRESH-04, BR-FRESH-05 |
| Endpoint | `GET /scans/{id}`, `GET /scans/{id}/images/{ordinal}`, `POST /scans/{id}/items`, `PATCH`/`DELETE /scans/{id}/items/{itemId}`, `POST /scans/{id}/confirm`, `POST /scans/{id}/discard`, `GET /ingredients` |

**Kịch bản chính**

| # | Bước |
|---|---|
| 1 | App hiện chip theo nhóm thực phẩm, có tên, số đếm hoặc mức lượng, nhãn độ tươi; nhóm "Cần kiểm tra" ở trên cùng. |
| 2–4 | A02 đổi tên một chip nhận sai: app tìm `GET /ingredients?q=`, gửi `PATCH`; hệ thống lưu `original_ingredient_id`, `user_action = relabeled`. |
| 5 | A02 sửa số đếm hoặc chọn mức lượng; hệ thống ghi `final_count`/`qty_level`, `user_action = edited`. |
| 6 | A02 thêm đồ bị sót: `POST /scans/{id}/items`, chip `origin = user_added`. |
| 7 | A02 xoá chip thừa: `DELETE`, chip của mô hình được đánh dấu `deleted`. |
| 8 | A02 xác nhận chip "kiểm tra" vẫn dùng được (`user_freshness`) hoặc xoá chip đó. |
| 9 | Với `fridge`, app hiện danh sách "Lần này không thấy". |
| 10–11 | A02 bấm "Đưa vào kho"; app gửi `POST /scans/{id}/confirm`. |
| 12 | Hệ thống kiểm scan `done` và mọi chip đủ điều kiện; quy lượng về khoảng gam [g_min, g_max] (BR-QTY-02). |
| 13 | Hệ thống ghi kho trong một giao dịch, đánh dấu `not_seen` (với `fridge`), chuyển scan sang `confirmed`. |
| 14 | App hiện "Đã thêm n món vào kho" và nút "Ra mâm cơm" (UC15). |

**Mở rộng chính**

- 4a. Sửa chip khi scan đã `confirmed`/`discarded`: 409 `scan_not_editable`.
- 5b. Đặt số đếm cho nguyên liệu không đếm được: 422 `qty_kind_mismatch`.
- 6b. Thêm chip trùng nguyên liệu: 409 `duplicate_item`.
- 10a. Còn chip "kiểm tra" chưa xử lý: 409 `freshness_check_required`.
- 10b. Còn chip không đếm được chưa chọn mức: 422 `qty_level_required`.
- 11a. Gửi lại xác nhận sau khi đã commit: 200 với cùng kết quả, kho không bị ghi lần hai.
- 11b. Hai thiết bị cùng xác nhận: khoá dòng `scans`, chỉ một giao dịch ghi kho.
- 12a. Thiếu quy đổi đơn vị: 422 `unit_conversion_missing`.
- 14a. A02 bỏ kết quả: `POST /scans/{id}/discard`, `discarded`, không ghi kho.

### 4.3. UC15 — Nhận mâm cơm hôm nay

Đặc tả đầy đủ: [use-cases/UC15.md](use-cases/UC15.md) (41 FR, FR-15-01 … FR-15-41).

| Mục | Nội dung |
|---|---|
| Mục tiêu | Hệ thống ghép một mâm cơm từ kho của A02, ưu tiên lô sắp hỏng, hợp gu, vừa năng lượng mục tiêu, nấu xong trong thời gian đã chọn, không chứa thứ gì thuộc nhóm dị ứng hoặc trái chế độ ăn của A02 và người ăn cùng |
| Mức, gói | Mục tiêu người dùng; PK5 |
| Tiền điều kiện | A02 đã đăng nhập; kho món có ít nhất một món `published` cho mỗi slot `man`, `rau`, `canh` |
| Đảm bảo tối thiểu | Không lưu hoặc trả mâm vi phạm BR-ALG-01, BR-DIET-01; không ghi `interactions` khi thiếu đồng ý `personalization`; kho không đổi; cùng `Idempotency-Key` không tạo mâm thứ hai |
| Đảm bảo khi thành công | Một `meal_plans` `proposed` (sau chấp nhận là `accepted`) với 2–3 `meal_plan_items` `active`, dị ứng người ăn cùng, lô ghim, ảnh chụp mục tiêu năng lượng, số bát cơm, dòng lý do, phiên bản bộ xếp hạng và tham số |
| Quy tắc | BR-TRAY-01 … BR-TRAY-08, BR-ALG-01, BR-DIET-01, BR-NUT-04, BR-NUT-06, BR-CONSENT-02, BR-CONSENT-03, BR-FRESH-04, BR-FRESH-05, BR-QTY-01, BR-QTY-02, BR-COOK-01, BR-CATALOG-01 |
| Endpoint | `POST /meal-plans`, `GET /meal-plans/latest`, `GET /meal-plans/{id}`, `POST /meal-plans/{id}/accept`, `GET /pantry/lots`, `GET /reference`, `GET /recipes`, `GET /recipes/{id}`, `POST /events` |

**Kịch bản chính**

| # | Bước |
|---|---|
| 1 | A02 mở màn Mâm cơm hôm nay; app hiện nhóm dị ứng, lô trong kho, số người mặc định. |
| 2 | A02 chọn bữa, số người n, thời gian nấu tối đa, (tuỳ chọn) dị ứng người ăn cùng và tối đa 2 lô "phải dùng", bấm "Ra mâm". |
| 3 | App gửi `POST /meal-plans` với `Idempotency-Key` mới. |
| 4 | Hệ thống kiểm khoá lũy đẳng và dữ liệu vào. |
| 5 | Hệ thống lấy ràng buộc bữa ăn: dị ứng, chế độ ăn, số họng bếp, 5 món hay ăn, E_mâm (BR-NUT-04); mỗi lần đọc chỉ số sức khoẻ ghi nhật ký kiểm toán. |
| 6 | Hệ thống kiểm đồng ý `personalization` hiện hành. |
| 7 | Hệ thống tính lượng khả dụng và độ gấp u của từng lô; bỏ lô ở mức "kiểm tra trước khi dùng" (BR-FRESH-04). |
| 8 | Hệ thống lọc cứng món `published` theo dị ứng và chế độ ăn (BR-ALG-01, BR-DIET-01). |
| 9 | Hệ thống chấm điểm gu từng món. |
| 10 | Hệ thống ghép mâm: chọn tổ hợp thoả BR-TRAY-01, 04, 05, 08 có hàm mục tiêu cao nhất. |
| 11 | Hệ thống tính số bát cơm (BR-TRAY-03), khoảng calo (BR-NUT-06), dòng lý do. |
| 12 | Hệ thống lưu mâm `proposed`, ghi `served` nếu có đồng ý, trả 201. |
| 13 | App hiện mâm tròn, dòng lý do, thanh calo dạng khoảng, "gợi ý x bát cơm". |
| 14 | A02 xem chi tiết món; app gửi sự kiện `viewed`. |
| 15 | A02 bấm "Nấu mâm này"; `POST /meal-plans/{id}/accept`, mâm sang `accepted`; app chuyển sang UC19. |

**Mở rộng chính**

- 1a. Chưa hoàn tất UC09: app nhắc; nếu vẫn ra mâm thì ghép như người chưa khai dị ứng, không có mục tiêu năng lượng, dùng cài đặt bếp mặc định.
- 4c. Gửi lại cùng khoá, cùng nội dung: trả nguyên văn phản hồi đã lưu.
- 4e. Bản gửi lại tới khi yêu cầu đầu còn xử lý: 409 kèm `Retry-After`.
- 5a. Chưa đồng ý `health_profile` hoặc chưa có mục tiêu: không có E_mâm, β = 0 (BR-CONSENT-02).
- 6a. Chưa đồng ý `personalization`: xếp hạng bằng trung bình món + content-based, không ghi `served` (BR-CONSENT-03).
- 10a. Không có mâm 3 món khả thi khi n ≥ 2: thử mâm 2 món (BR-TRAY-06).
- 10b. Vẫn không có mâm khả thi: 422 `no_feasible_tray` kèm danh sách nguyên liệu thiếu; điểm mở rộng tới UC18.
- 10c. Lô ghim không dùng được: 422 `pin_unsatisfiable`.
- 13a. Không ưng một món: UC16. 13b. Xem thiếu gì: UC17.
- 15a. Mâm không còn `proposed`: 409. 15c. Mâm hết hiệu lực theo ST02.
- \*a. Truy cập mâm người khác: 404 (chống BOLA).

### 4.4. UC20 — Hoàn tất bữa nấu (nấu xong một chạm)

Đặc tả đầy đủ: [use-cases/UC20.md](use-cases/UC20.md) (13 FR, FR-20-01 … FR-20-13).

| Mục | Nội dung |
|---|---|
| Mục tiêu | A02 chạm "Nấu xong"; trong một giao dịch, hệ thống trừ kho theo lô gấp nhất trước, ghi tương tác (nếu có đồng ý), chuyển phiên nấu và mâm sang trạng thái đã xong; A02 có 10 phút để hoàn tác (UC21) |
| Mức, gói | Mục tiêu người dùng; PK6 |
| Tiền điều kiện | A02 đã đăng nhập; có `cook_sessions` `in_progress` của một mâm thuộc A02 |
| Đảm bảo tối thiểu | Mọi thay đổi cùng ghi hoặc không ghi gì; một phiên bị trừ kho nhiều nhất một lần; không ghi `interactions` khi thiếu đồng ý; lượng lô không âm |
| Đảm bảo khi thành công | `cook_sessions.status = completed`, `meal_plans.status = cooked`; mỗi lô bị dùng có một `pantry_transactions` `reason = cook_deduct`; lô hết chuyển `used_up`; có tương tác `cooked` và `liked`/`disliked` khi có đồng ý; phản hồi có `undo_deadline` |
| Quy tắc | BR-COOK-02, BR-PANTRY-02, BR-CONSENT-03, BR-TRAY-02, BR-QTY-01, BR-QTY-02, BR-FRESH-04, BR-FRESH-05 |
| Endpoint | `POST /cook-sessions/{id}/complete`, `POST /events` |

**Kịch bản chính**

| # | Bước |
|---|---|
| 1 | App hiện màn Nấu xong với danh sách món, mỗi món có nút thích / không thích. |
| 2 | A02 chấm (tuỳ chọn) rồi chạm "Nấu xong". |
| 3 | App sinh `Idempotency-Key` và `event_id` cho mỗi sự kiện, đưa vào outbox, gửi `POST /cook-sessions/{id}/complete`. |
| 4 | Hệ thống kiểm khoá lũy đẳng; chưa gặp thì thực hiện bước 5–11 trong một giao dịch (BR-COOK-02). |
| 5 | Hệ thống chuyển phiên sang `completed` chỉ khi đang `in_progress` và mâm thuộc A02. |
| 6 | Hệ thống tính lượng đã dùng theo món `active`, đồ thay thế, số người (BR-TRAY-02, BR-QTY-02). |
| 7 | Hệ thống trừ kho theo lô có độ gấp cao nhất trước (BR-PANTRY-02). |
| 8 | Hệ thống bỏ qua lô "kiểm tra trước khi dùng", ghi giao dịch âm theo khoảng gam, chuyển lô hết sang `used_up`. |
| 9 | Hệ thống chuyển mâm sang `cooked`. |
| 10 | Hệ thống ghi tương tác `cooked`, `liked`/`disliked` khi có đồng ý `personalization`; `event_id` chống trùng. |
| 11 | Hệ thống ghi nhớ phản hồi theo khoá lũy đẳng, kết thúc giao dịch. |
| 12 | Hệ thống trả 200 kèm tóm tắt trừ kho và `undo_deadline`. |
| 13 | App xoá yêu cầu khỏi outbox, hiện tóm tắt và nút "Hoàn tác" đếm ngược (điểm mở rộng UC21). |

**Mở rộng chính**

- 3a. Mất mạng: yêu cầu nằm trong outbox, gửi lại tự động; kho chỉ bị trừ khi yêu cầu tới server.
- 4a. Gửi lại cùng khoá trong 48 giờ: trả nguyên văn phản hồi, không trừ kho lần hai.
- 5a. Phiên đã `completed` (gửi lại với khoá khác): 200 với tóm tắt lần đầu.
- 5b. Phiên `abandoned` hoặc `reverted`: 409 `cook_session_not_in_progress`.
- 8a. Kho không đủ: trừ tới hết, phần thiếu ghi trong tóm tắt.
- 10a. Thiếu đồng ý `personalization`: không ghi `interactions`, vẫn trừ kho.
- 11a. Lỗi CSDL: rollback toàn bộ, 503 `temporarily_unavailable`, outbox gửi lại cùng khoá.
- 13a. Trừ sai: hoàn tác trong 10 phút (UC21), sau đó sửa lô ở UC14.

---

## 5. Mô hình hành vi

### 5.1. Sơ đồ hoạt động

![AD01 — Từ quét đến nấu xong](../uml/out/activity/AD01-quet-den-nau.svg)

*Hình 5. AD01 — Luồng nối các gói từ quét tủ lạnh tới nấu xong, ba làn Người dùng, App, api; gồm các nhánh đổi món, thay nguyên liệu và hoàn tác.*

![AD02 — Ghép mâm](../uml/out/activity/AD02-ghep-mam.svg)

*Hình 6. AD02 — Ghép mâm bên trong `POST /meal-plans`: làn `profile` cấp ràng buộc bữa ăn, `pantry` cấp lượng và độ gấp, `meal` lọc cứng, xếp hạng và chọn tổ hợp.*

![AD03 — Xác nhận quét](../uml/out/activity/AD03-xac-nhan-quet.svg)

*Hình 7. AD03 — Xác nhận kết quả quét vào kho trong một Unit of Work, làn App, `scan`, `pantry`.*

![AD04 — Vòng dữ liệu và mô hình](../uml/out/activity/AD04-vong-du-lieu-mo-hinh.svg)

*Hình 8. AD04 — Ảnh góp có đồng ý đi qua gán nhãn, xuất dữ liệu bí danh hoá, huấn luyện trên GPU lab, đăng ký, kiểm định và triển khai mô hình.*

![AD05 — Xoá tài khoản](../uml/out/activity/AD05-xoa-tai-khoan.svg)

*Hình 9. AD05 — Yêu cầu xoá tài khoản được worker xử lý trong hạn BR-DSR-01; ảnh và dữ liệu xoá theo BR-RETAIN-01.*

![AD06 — Khảo sát](../uml/out/activity/AD06-khao-sat.svg)

*Hình 10. AD06 — Người vận hành tạo phiếu, người tham gia đồng ý rồi chấm món ẩn danh; kết quả xuất bằng `tastoria survey export`.*

### 5.2. Sơ đồ tuần tự

![SD01 — Quét ảnh bất đồng bộ](../uml/out/sequence/SD01-quet-anh-bat-dong-bo.svg)

*Hình 11. SD01 — `POST /scans` trả 202, worker suy luận bất đồng bộ, app chờ bằng long-poll; sweeper UC34 xử lý job kẹt.*

![SD02 — Xác nhận quét](../uml/out/sequence/SD02-xac-nhan-quet.svg)

*Hình 12. SD02 — Sửa chip rồi xác nhận; module `scan` gọi `pantry` trong cùng Unit of Work để ghi lô và giao dịch.*

![SD03 — Tạo mâm](../uml/out/sequence/SD03-tao-mam.svg)

*Hình 13. SD03 — `meal` gọi `profile.get_meal_constraints()`, `pantry`, `privacy` và bộ xếp hạng; ghi mâm, sự kiện `served` và khoá lũy đẳng.*

![SD04 — Đổi món](../uml/out/sequence/SD04-doi-mon.svg)

*Hình 14. SD04 — Đổi một món trong mâm (UC16) có lọc dị ứng lại cho món thay (BR-ALG-01).*

![SD05 — Chọn thay thế](../uml/out/sequence/SD05-chon-thay-the.svg)

*Hình 15. SD05 — "Thiếu gì?": `substitute` tra cặp thay thế và embedding, lọc cứng, rồi ghi lựa chọn hoặc thêm vào danh sách đi chợ.*

![SD06 — Nấu xong và hoàn tác](../uml/out/sequence/SD06-nau-xong-va-hoan-tac.svg)

*Hình 16. SD06 — Tạo phiên nấu với lịch CP-SAT, nấu xong trong một Unit of Work, hoàn tác trong 10 phút bằng giao dịch đảo.*

![SD07 — Rút đồng ý](../uml/out/sequence/SD07-rut-dong-y.svg)

*Hình 17. SD07 — Rút đồng ý ghi `consent_events`, tăng `token_version` và tạo yêu cầu xoá dữ liệu của mục đích đó.*

![SD08 — Làm mới token](../uml/out/sequence/SD08-lam-moi-token.svg)

*Hình 18. SD08 — Refresh token opaque xoay vòng theo family; dùng lại token cũ thì thu hồi cả family.*

![SD09 — Tải dữ liệu](../uml/out/sequence/SD09-tai-du-lieu.svg)

*Hình 19. SD09 — Yêu cầu xuất dữ liệu được worker xử lý, tệp tải về qua `X-Accel-Redirect` sau khi kiểm chủ sở hữu.*

![SD10 — Triển khai mô hình](../uml/out/sequence/SD10-trien-khai-mo-hinh.svg)

*Hình 20. SD10 — CLI `tastoria mlops` đăng ký, kiểm định, triển khai và quay lui; quay lui đổi chỗ `active_version_id` và `previous_version_id` trong `model_deployments`.*

### 5.3. Sơ đồ máy trạng thái

![ST01 — Scan](../uml/out/state/ST01-scan.svg)

*Hình 21. ST01 — `scans`: `queued` → `processing` → `done` → `confirmed`/`discarded`; lỗi lặp tới 3 lần thì `failed`, kẹt thì sweeper đặt `expired`.*

![ST02 — MealPlan](../uml/out/state/ST02-meal-plan.svg)

*Hình 22. ST02 — `meal_plans`: `proposed` → `accepted` → `cooked`; mâm cũ `expired` hoặc `abandoned` khi có mâm mới cùng bữa hoặc qua giờ bữa; hoàn tác đưa `cooked` về `accepted`.*

![ST03 — CookSession](../uml/out/state/ST03-cook-session.svg)

*Hình 23. ST03 — `cook_sessions`: `completed` có trạng thái con "còn hoàn tác được" trong 10 phút, sau đó khoá lại.*

![ST04 — Consent](../uml/out/state/ST04-consent.svg)

*Hình 24. ST04 — Đồng ý theo (người dùng, mục đích): `none`, `granted`, `withdrawn`, `superseded` khi có phiên bản điều khoản mới.*

![ST05 — PantryLot](../uml/out/state/ST05-pantry-lot.svg)

*Hình 25. ST05 — `pantry_lots`: `in_stock`, `not_seen` (quét toàn tủ không thấy), `used_up`, `discarded`; hoàn tác trả `used_up` về `in_stock`.*

![ST06 — Account](../uml/out/state/ST06-account.svg)

*Hình 26. ST06 — Tài khoản: `locked` sau 5 lần sai mật khẩu, tự mở sau 15 phút; `deletion_requested` → `deleted` trong 24 giờ.*

![ST07 — ModelVersion](../uml/out/state/ST07-model-version.svg)

*Hình 27. ST07 — `model_versions`: `candidate` qua cổng kiểm định thành `validated` hoặc `rejected`; `active` là vị trí trong `model_deployments`, không phải giá trị cột `status`.*

![ST08 — DsrRequest](../uml/out/state/ST08-dsr-request.svg)

*Hình 28. ST08 — `dsr_requests`: loại tự động do worker hoàn tất; loại `correct`, `restrict`, `object` do A04 xử lý qua `/admin/data-requests/{id}/resolve`.*

---

## 6. Mô hình cấu trúc

### 6.1. Sơ đồ lớp

![CL01 — Lớp miền](../uml/out/class/CL01-mien-phan-tich.svg)

*Hình 29. CL01 — Lớp miền mức phân tích: người dùng, hồ sơ, lô kho, lần quét, món, mâm, phiên nấu và quan hệ bội số giữa chúng.*

Lớp phân tích BCE (boundary–control–entity) cho các UC lõi:

![CL02 — BCE quét](../uml/out/class/CL02-bce-quet.svg)

*Hình 30. CL02 — BCE cho UC12 và UC13.*

![CL03 — BCE mâm](../uml/out/class/CL03-bce-mam.svg)

*Hình 31. CL03 — BCE cho UC15.*

![CL04 — BCE nấu xong](../uml/out/class/CL04-bce-nau-xong.svg)

*Hình 32. CL04 — BCE cho UC20.*

Lớp thiết kế cho bốn module có logic nặng nhất:

![CL05 — Thiết kế meal](../uml/out/class/CL05-thiet-ke-meal.svg)

*Hình 33. CL05 — Module `meal` (M11): router, service, lọc cứng, xếp hạng, ghép mâm, repository.*

![CL06 — Thiết kế pantry](../uml/out/class/CL06-thiet-ke-pantry.svg)

*Hình 34. CL06 — Module `pantry` (M06): lô, giao dịch chỉ ghi thêm, quy đổi lượng, tính độ gấp lúc đọc.*

![CL07 — Thiết kế scan](../uml/out/class/CL07-thiet-ke-scan.svg)

*Hình 35. CL07 — Module `scan` (M08): nhận ảnh, job worker, gộp chip, xác nhận vào kho.*

![CL08 — Thiết kế cooking](../uml/out/class/CL08-thiet-ke-cooking.svg)

*Hình 36. CL08 — Module `cooking` (M12): lịch CP-SAT, phiên nấu, nấu xong và hoàn tác.*

### 6.2. Sơ đồ thành phần

![CP01 — Thành phần](../uml/out/component/CP01-thanh-phan.svg)

*Hình 37. CP01 — 16 module backend, giao diện mỗi module công bố qua `service.py` và các phụ thuộc được phép theo `model.yaml`; đồ thị phụ thuộc không có vòng, kiểm bằng import-linter (ADR 0001).*

### 6.3. Sơ đồ gói

![PG01 — Gói](../uml/out/package/PG01-goi.svg)

*Hình 38. PG01 — Bố cục mã nguồn backend theo module và app Expo.*

### 6.4. Sơ đồ triển khai

![DP01 — Triển khai](../uml/out/deployment/DP01-trien-khai.svg)

*Hình 39. DP01 — Docker Compose trên máy chủ lab: nginx, api, worker, scheduler, postgres, valkey; ra Internet qua Cloudflare Tunnel; sao lưu ra kho ngoài.*

---

## 7. Thiết kế cơ sở dữ liệu

Chi tiết: [04-chuan-hoa.md](04-chuan-hoa.md) (chuẩn hoá), [05-tu-dien-du-lieu.md](05-tu-dien-du-lieu.md) (từ điển dữ liệu sinh từ catalog PostgreSQL), [`db/schema.sql`](../../db/schema.sql) (DDL đầy đủ), [`db/schema_vp.sql`](../../db/schema_vp.sql) (bản cho Visual Paradigm).

### 7.1. Mô hình khái niệm (Chen)

![ERD00 — Mô hình khái niệm Chen](../uml/out/erd/ERD00-khai-niem-chen.svg)

*Hình 40. ERD00 — 29 thực thể, quan hệ đặt tên bằng động từ; 1/N/M là tỉ số lực lượng, nét đôi là tham gia toàn phần.*

### 7.2. Mô hình logic/vật lý (chân quạ)

![ERD08 — Tổng quan 62 bảng](../uml/out/erd/ERD08-tong-quan.svg)

*Hình 41. ERD08 — Tổng quan 62 bảng và mọi khoá ngoại; cột chi tiết ở ERD01–ERD07.*

| ERD | Nhóm | Số bảng |
|---|---|---|
| [ERD01](../uml/out/erd/ERD01-dinh-danh-quyen-rieng-tu.svg) | core, identity, privacy | 9 |
| [ERD02](../uml/out/erd/ERD02-ho-so.svg) | profile | 4 |
| [ERD03](../uml/out/erd/ERD03-danh-muc-thanh-phan.svg) | catalog: thành phần thực phẩm, nguyên liệu, dị ứng, chế độ ăn, đơn vị, mức lượng, lớp thị giác | 15 |
| [ERD04](../uml/out/erd/ERD04-mon-an.svg) | catalog: món, bước, thẻ, nguồn, dinh dưỡng món | 8 |
| [ERD05](../uml/out/erd/ERD05-kho-quet.svg) | pantry, scan | 6 |
| [ERD06](../uml/out/erd/ERD06-mam-nau.svg) | meal, substitute, cooking, events | 11 |
| [ERD07](../uml/out/erd/ERD07-khao-sat-mo-hinh.svg) | survey, mlops | 9 |
| | **Tổng** | **62** |

Ba view: `v_current_consents` (đồng ý hiện hành = sự kiện mới nhất mỗi mục đích), `v_pantry_lot_balance` (lượng hiện tại của lô = lượng đầu + Σ giao dịch, chặn dưới 0), `v_journal_days` (nhật ký theo ngày địa phương).

DDL được kiểm bằng `docs/sad/tools/test_ddl.sh`: dựng container `pgvector/pgvector:pg18` tạm, áp `db/schema.sql`, so tên bảng và cột với `model.yaml`.

### 7.3. Chuẩn hoá

Với mỗi bảng: xác định khoá ứng viên, liệt kê phụ thuộc hàm không tầm thường, kiểm lần lượt 1NF, 2NF, 3NF, BCNF. Hai quy ước áp chung: N1 (phụ thuộc hàm có vế trái chứa cột cho phép NULL xét trên các bộ có vế trái khác NULL) và N2 (ràng buộc mẫu hằng trong một bộ, ép bằng `CHECK`, không tính khi xét dạng chuẩn).

Kết quả: **55 bảng đạt BCNF; 7 bảng cố ý dừng ở 2NF hoặc 1NF**, mỗi trường hợp có lý do và cơ chế giữ nhất quán. Các bất biến (món đã công bố không sửa, bảng nhật ký chỉ ghi thêm, cột chỉ ghi một lần) được ép bằng trigger trong `db/schema.sql`, không chỉ dựa vào service; vai trò `tastoria_app` bị thu hồi `UPDATE`, `DELETE`, `TRUNCATE` trên bốn bảng chỉ ghi thêm.

### 7.4. Phi chuẩn hoá có kiểm soát

| Mục | Dư thừa | Lý do |
|---|---|---|
| D1 | `recipe_nutrition.per_serving` dẫn xuất từ `recipe_ingredients` × tỉ lệ ăn được × `food_nutrients` (bảng chỉ đạt 1NF) | Ghép mâm cần kcal mọi món ứng viên ở mỗi lần gọi (NFR-PERF-02); job tính lại khi kho món hoặc bảng thành phần đổi, `data_version` ghi phiên bản nguồn |
| D2 | Cột ảnh chụp của mâm, phiên nấu, sự kiện (`e_target_kcal`, `kcal_per_person`, `burners`, …) | Giữ giá trị tại thời điểm lập mâm; tách ảnh chụp ghi một lần và giá trị dẫn xuất tính lại có kiểm soát |
| D3 | `pantry_lots.p_*` chép xác suất độ tươi từ lần quét gần nhất thấy lô | Không có đường khoá ngoại ổn định từ lô tới khung phát hiện mới nhất; lần quét cũ bị xoá theo vòng đời |
| D4 | `interactions.user_id` cùng khoá ngoại ghép tới `meal_plans (id, user_id)` (2NF) | Sự kiện ngoài mâm vẫn phải thuộc một người (cổng đồng ý, xoá theo người); FK ghép bảo đảm `user_id` khớp chủ mâm khi có mâm |
| D5 | Cột `jsonb`: `idempotency_keys.response_body`, `model_versions.metrics` | Lưu để trả lại nguyên văn hoặc làm báo cáo, không truy vấn |
| D6 | `meal_plan_items.slot` chép `recipes.slot`, FK ghép tới `recipes (id, slot)` (2NF) | Chỉ mục duy nhất một phần `UNIQUE (meal_plan_id, slot) WHERE status = 'active'` cần `slot` ở cùng bảng |
| D7 | `refresh_tokens`: `family_id → user_id` (2NF) | Đăng xuất mọi thiết bị và xoá tài khoản thu hồi token theo `user_id` bằng một câu lệnh; `trg_refresh_tokens_write_once` giữ nhất quán |
| D8 | `dsr_requests`: `user_id → subject_ref` (HMAC, 2NF) | Giữ bằng chứng xử lý yêu cầu sau khi xoá tài khoản (`user_id` thành NULL); `subject_ref` vẫn là dữ liệu cá nhân đã bí danh hoá |
| D9 | `user_id` ở `pantry_lots`, `shopping_items` suy được qua khoá ngoại nguồn (2NF) | Khoá ngoại nguồn cho phép NULL và sống ngắn hơn dòng; `user_id` dùng cho lọc chống BOLA và xoá theo người; trigger ghi một lần |
| D10 | `scan_items.model_count` suy được từ `detections` | Giữ đúng số đếm lúc suy luận để so với `final_count` khi đánh giá mô hình; `detections` đổi khi người dùng sửa chip |
| D11 | `survey_assignments.is_anchor` suy được từ `survey_form_anchors` | Xuất kết quả khảo sát không phải nối ba bảng; món neo bị khoá khi phiếu đã mở |
| D12 | Ràng buộc mẫu hằng trong một bộ (N2), ví dụ `survey_ratings.never_eaten = (rating IS NULL)` | Không tính khi xét dạng chuẩn; mỗi ràng buộc ép bằng `CHECK` |
| D13 | `pantry_transactions (ref_type, ref_id)` tham chiếu đa hình, không khai được khoá ngoại | Chưa tách thành cột khoá ngoại tường minh vì `model.yaml` chưa có; đến khi tách, `trg_pantry_transactions_ref` kiểm `ref_id` tồn tại và đúng chủ |

Chi tiết cơ chế (tên trigger, ràng buộc) và phép tách từ lược đồ v1 ở `04-chuan-hoa.md` mục 4 và 5.

---

## 8. Hợp đồng API

Chi tiết: [`docs/api/openapi-v1.yaml`](../api/openapi-v1.yaml) (OpenAPI 3.1, 70 operation, kiểm bằng `openapi-spec-validator`).

| Quy ước | Nội dung |
|---|---|
| Tiền tố | `/api/v1` cho mọi endpoint trừ `/healthz`, `/readyz` |
| Định danh | Id công khai là UUID; mọi truy vấn theo `{id}` lọc theo chủ sở hữu, tài nguyên người khác trả 404 (chống BOLA) |
| Lỗi | RFC 9457 `application/problem+json` với `code` ổn định; danh mục `ProblemCode` có 77 mã; client rẽ nhánh theo `code` |
| Xác thực | Bearer JWT ngắn hạn + refresh token opaque xoay vòng (ADR 0004); endpoint nhân sự ghi vai trò ở `x-required-role` |
| Lũy đẳng | `Idempotency-Key` bắt buộc ở 5 thao tác (`POST /scans`, `POST /meal-plans`, swap, `POST /cook-sessions`, `/complete`), lưu 48 giờ; `POST /events` chống trùng theo `event_id`; 56 endpoint lũy đẳng tự nhiên; 8 endpoint tạo tài nguyên mới mỗi lần gọi |
| Bất đồng bộ | 202 + `Location` + `Retry-After`; long-poll `?wait=` |
| Phân trang | Keyset: `cursor` + `limit` (≤ 100) → `next_cursor` |
| Phiên bản app | Header `X-App-Version`; quá cũ trả 412 `app_too_old` |
| Mở rộng | `x-use-cases`, `x-module`, `x-idempotency`, `x-required-role` để truy vết tới `model.yaml` |

Phân bố 70 endpoint theo quyền: 51 `user`, 10 `public`, 4 `public+respondent_token` (khảo sát), 3 `staff:admin`, 2 `staff:ml_operator`. Thao tác nhân sự còn lại chạy bằng 13 lệnh CLI `tastoria …` và `python -m tastoria.jobs.*`.

---

## 9. Kiểm thử

Chi tiết: [06-ke-hoach-kiem-thu.md](06-ke-hoach-kiem-thu.md).

| Tầng | Công cụ | Chặn hợp nhất khi |
|---|---|---|
| Đơn vị | pytest, freezegun | Một ca đỏ hoặc độ phủ dưới ngưỡng NFR-MAINT-01 |
| Tính chất | Hypothesis | Một phản ví dụ |
| Tích hợp API | pytest + httpx, PostgreSQL và Valkey thật | Một ca đỏ |
| Hợp đồng | Schemathesis, openapi-spec-validator | Một 5xx hoặc lệch schema |
| Bảo mật | pytest (BOLA, lũy đẳng, tải lên), pip-audit, npm audit | Một ca đỏ; lỗ hổng mức cao |
| Vận hành | pytest gọi CLI và job | Một ca đỏ |
| Mô hình | pytest trên bộ ảnh vàng, cổng UC29 | Lệch vượt dung sai |
| E2E | Playwright (web), Maestro (Android) | Một luồng đỏ |
| Tải | k6, Locust | p95 vượt ngưỡng NFR-PERF |
| UAT | Phiên thử có điều phối, bảng SUS | NFR-USE-01 không đạt |

Danh mục có **271 ca kiểm thử** trong 26 nhóm. Nhóm lớn nhất: `MEAL` 40, `SCAN` 24, `PRIV` 23, `AUTH` 18, `COOK` 17, `PANT` 15. Ca bắt buộc không có ngoại lệ: TC-PROP-01 kiểm BR-ALG-01 (không mâm nào chứa nhóm dị ứng đã khai) trên toàn bộ kho món thật × mọi nhóm dị ứng.

Độ phủ yêu cầu: 446/446 FR, 39/39 BR, 10/10 mã NFR (31/31 điều khoản), 34/34 UC có ít nhất một ca.

---

## 10. Quyết định kiến trúc (ADR)

Các ADR ở [`docs/adr/`](../adr/), định dạng MADR, ngày 17/10/2026.

| ADR | Quyết định | Trạng thái |
|---|---|---|
| [0001](../adr/0001-modular-monolith-ranh-gioi-module.md) | Modular monolith, ranh giới module cưỡng chế bằng import-linter | Chấp nhận |
| [0002](../adr/0002-luu-tep-tren-o-dia-x-accel-redirect.md) | Lưu tệp trên ổ đĩa, phục vụ qua `X-Accel-Redirect` | Chấp nhận |
| [0003](../adr/0003-valkey-rq-container-cron.md) | Valkey + RQ cho việc nền, container `scheduler` (cron) cho việc định kỳ | Chấp nhận |
| [0004](../adr/0004-jwt-refresh-opaque-xoay-vong.md) | Access JWT ngắn hạn + refresh token opaque xoay vòng theo family | Chấp nhận |
| [0005](../adr/0005-ma-hoa-cot-suc-khoe-get-meal-constraints.md) | Mã hoá cột sức khoẻ ở tầng ứng dụng; giao diện `profile.get_meal_constraints()` | Chấp nhận |
| [0006](../adr/0006-dong-y-theo-muc-dich-nhat-ky-chi-ghi-them.md) | Đồng ý theo mục đích, nhật ký đồng ý chỉ ghi thêm | Chấp nhận |
| [0007](../adr/0007-luy-dang-va-unit-of-work.md) | Lũy đẳng (`Idempotency-Key`, `event_id`) và Unit of Work cho thao tác nhiều module | Chấp nhận |
| [0008](../adr/0008-phuc-vu-xep-hang-bang-numpy.md) | Phục vụ xếp hạng gu bằng mảng NumPy đã xuất, không cài LightFM trong API | Chấp nhận |
| [0009](../adr/0009-lich-nau-cp-sat.md) | Lịch nấu cả mâm bằng CP-SAT (OR-Tools) | Chấp nhận |
| [0010](../adr/0010-expo-mot-ma-nguon-android-web.md) | Expo: một mã nguồn cho Android và web | Chấp nhận |
| [0011](../adr/0011-yolo26n-giay-phep-agpl.md) | Bộ phát hiện YOLO26n và nghĩa vụ giấy phép AGPL-3.0 | Chấp nhận; phần giấy phép cần rà soát pháp lý |
| [0012](../adr/0012-huan-luyen-gpu-lab-trong-nuoc.md) | Huấn luyện trên GPU của lab trong nước; Colab/Kaggle chỉ cho dữ liệu công khai | Chấp nhận; vị trí máy chủ lab cần xác nhận |
| [0013](../adr/0013-giao-so-do-visual-paradigm-plantuml-vp.md) | Giao sơ đồ cho Visual Paradigm qua plugin PlantUML-VP và Reverse DDL | Chấp nhận |

---

## 11. Đánh giá tác động xử lý dữ liệu cá nhân

Chi tiết: [07-danh-gia-tac-dong-du-lieu-ca-nhan.md](07-danh-gia-tac-dong-du-lieu-ca-nhan.md) (bản nháp 0.1, cần rà soát pháp lý trước khi phát hành).

- **Căn cứ**: Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 và Nghị định 356/2025/NĐ-CP. Điều khoản đã đối chiếu với bản đăng lại, chưa đối chiếu Công báo.
- **Có phải lập hồ sơ**: có, khi mở cho người dùng ngoài nhóm, vì hệ thống trực tiếp xử lý dữ liệu nhạy cảm (chỉ số cơ thể, dị ứng, hành vi sử dụng); ngoại lệ cho doanh nghiệp nhỏ ở Luật 91 Điều 38 không áp dụng.
- **Mục đích cần đồng ý riêng** (bảng `consent_purposes`): `health_profile`, `personalization`, `photo_contribution`, `survey`; mặc định tắt, ghi nhật ký chỉ ghi thêm.
- **Biện pháp chính**: mã hoá cột sức khoẻ AES-GCM, giải mã chỉ trong module `profile` và ghi `audit_log`; cổng đồng ý kiểm ở server; chống BOLA; ảnh quét xoá sau 30 ngày trừ ảnh góp có đồng ý; bản sao lưu mã hoá giữ ≤ 14 ngày; huấn luyện trên máy trong nước; yêu cầu chủ thể loại tự động hoàn tất ≤ 24 giờ.
- **Rủi ro**: 18 rủi ro R01–R18. Sau biện pháp, phần lớn ở mức Thấp; còn mức Trung bình: R02 (dị ứng, kcal không mã hoá), R05 (nội dung ảnh), R07 (dữ liệu còn sau khi xoá ở bản sao lưu, bản xuất, Label Studio, MLflow), R09 (luồng ra nước ngoài).
- **Chưa đạt**: căn cứ xử lý dữ liệu dịch vụ cốt lõi chưa xác định; luồng xuyên biên giới X1–X4 (Gemini, sao lưu Drive, Cloudflare, SMTP) cần quyết định; một số thời hạn lưu chưa định; chưa có thoả thuận với bên xử lý.

---

## 12. Ma trận truy vết

Chi tiết: [08-ma-tran-truy-vet.md](08-ma-tran-truy-vet.md), sinh bằng `docs/sad/tools/gen_traceability.py` từ `model.yaml`, front-matter tệp UC và kế hoạch kiểm thử. Ma trận nối UC → FR → endpoint/CLI → module → bảng/view → TC, kèm BR → UC, TC.

| Đối tượng | Đã truy vết | Ô trống |
|---|---|---|
| Use case có FR | 34/34 | 0 |
| Use case có TC | 34/34 | 0 |
| FR có TC | 446/446 | 0 |
| BR được UC hoặc TC tham chiếu | 39/39 | 0 |
| Endpoint được UC dùng hoặc TC kiểm | 70/70 | 0 |
| Bảng được UC dùng | 62/62 | 0 |
| **Tổng ô trống** | | **0** |

Kiểm chéo đi kèm: `check_refs.py` (mã lạ trong tài liệu và sơ đồ), `render.sh` (56 sơ đồ render được, SVG không có lỗi cú pháp), `test_ddl.sh` (DDL áp được, cột khớp `model.yaml`).

---

## 13. Phụ lục: danh mục tệp

### 13.1. Tài liệu

| Tệp | Nội dung |
|---|---|
| [`docs/sad/model.yaml`](model.yaml) | Mô hình nguồn sự thật |
| [`docs/sad/00-thuat-ngu.md`](00-thuat-ngu.md) | Thuật ngữ |
| [`docs/sad/01-SRS.md`](01-SRS.md) | Đặc tả yêu cầu phần mềm |
| [`docs/sad/use-cases/UC01.md`](use-cases/UC01.md) … [`UC34.md`](use-cases/UC34.md) | Đặc tả 34 use case |
| [`docs/sad/04-chuan-hoa.md`](04-chuan-hoa.md) | Mô hình dữ liệu và chuẩn hoá |
| [`docs/sad/05-tu-dien-du-lieu.md`](05-tu-dien-du-lieu.md) | Từ điển dữ liệu |
| [`docs/sad/06-ke-hoach-kiem-thu.md`](06-ke-hoach-kiem-thu.md) | Kế hoạch kiểm thử |
| [`docs/sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md`](07-danh-gia-tac-dong-du-lieu-ca-nhan.md) | Đánh giá tác động xử lý dữ liệu cá nhân |
| [`docs/sad/08-ma-tran-truy-vet.md`](08-ma-tran-truy-vet.md) | Ma trận truy vết |
| [`docs/sad/BaoCao_PhanTichThietKe.md`](BaoCao_PhanTichThietKe.md) | Báo cáo này |
| [`docs/adr/`](../adr/) | ADR 0001–0013 |
| [`docs/api/openapi-v1.yaml`](../api/openapi-v1.yaml) | Hợp đồng API |
| [`db/schema.sql`](../../db/schema.sql) | DDL PostgreSQL 18 + pgvector |
| [`db/schema_vp.sql`](../../db/schema_vp.sql) | DDL cho Visual Paradigm Reverse DDL |
| [`docs/vp-import-kit/HUONG-DAN.md`](../vp-import-kit/HUONG-DAN.md) | Hướng dẫn dựng dự án Visual Paradigm |
| `docs/vp-import-kit/make_kit.sh` → `dist/tastoria-vp-kit.zip` | Đóng gói bộ nhập Visual Paradigm |

### 13.2. Sơ đồ (nguồn `.puml` → ảnh trong `docs/uml/out/`)

| Loại | Thư mục nguồn | Sơ đồ | Số tệp |
|---|---|---|---|
| Ngữ cảnh | `docs/uml/context/` | CTX01 | 1 |
| Use case | `docs/uml/usecase/` | UCD00–UCD10 | 11 |
| Hoạt động | `docs/uml/activity/` | AD01–AD06 | 6 |
| Tuần tự | `docs/uml/sequence/` | SD01–SD10 | 10 |
| Máy trạng thái | `docs/uml/state/` | ST01–ST08 | 8 |
| Lớp | `docs/uml/class/` | CL01–CL08 | 8 |
| Thành phần | `docs/uml/component/` | CP01 | 1 |
| Gói | `docs/uml/package/` | PG01 | 1 |
| Triển khai | `docs/uml/deployment/` | DP01 | 1 |
| ERD | `docs/erd/` | ERD00 (Chen), ERD01–ERD08 (chân quạ) | 9 |
| | | **Tổng** | **56** |

### 13.3. Công cụ kiểm tra (`docs/sad/tools/`)

| Tệp | Việc |
|---|---|
| `render.sh` | Render mọi `.puml` ra SVG và PNG, thoát mã khác 0 khi có lỗi |
| `check_refs.py` | Báo mã A/UC/BR/NFR/bảng/endpoint không có trong `model.yaml` |
| `collect_frs.py` | Sinh bảng FR và Phụ lục A của SRS từ tệp UC |
| `test_ddl.sh` | Áp `db/schema.sql` vào container PostgreSQL tạm, so bảng và cột với `model.yaml` |
| `gen_traceability.py` | Sinh ma trận truy vết, in số ô trống |
| `tests/test_tools.py` | Kiểm thử cho các công cụ trên |
