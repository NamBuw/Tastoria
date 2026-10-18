# Báo cáo môn Phát triển ứng dụng thông minh — Tastoria: gợi ý một mâm cơm Việt từ ảnh tủ lạnh

Tác giả: Nguyễn Xuân Nam. Ngày viết: 18/10/2026. Mã nguồn: repo `Tastoria` (backend `backend/`, app `app/`, học máy
`ml/`, triển khai `deploy/`, trang giới thiệu `landing/`). Hệ thống chạy thật tại `https://safework.ctslab.net`.

> **Quy ước về số liệu.** Mọi con số trong báo cáo lấy từ một tệp trong repo hoặc từ một lần chạy ghi rõ ngày, đường
> dẫn tệp nguồn ghi cạnh số. Số kiểm thử ở mục 6 là lần chạy ngày 18/10/2026 trong lúc viết báo cáo. Những gì chưa
> đo (đánh giá khả dụng với người thật, đo trên điện thoại, kiểm thử tải theo đúng điều kiện SRS) được liệt kê riêng
> ở mục 8.3, không ước lượng thay.

## Mục lục

1. [Giới thiệu](#1-giới-thiệu)
2. [Khảo sát và yêu cầu](#2-khảo-sát-và-yêu-cầu)
3. [Phân tích](#3-phân-tích)
4. [Thiết kế](#4-thiết-kế)
5. [Cài đặt](#5-cài-đặt)
6. [Kiểm thử](#6-kiểm-thử)
7. [Triển khai và vận hành](#7-triển-khai-và-vận-hành)
8. [Đánh giá](#8-đánh-giá)
9. [Hạn chế và hướng phát triển](#9-hạn-chế-và-hướng-phát-triển)
10. [Tài liệu tham khảo](#10-tài-liệu-tham-khảo)
11. [Phụ lục](#11-phụ-lục)

---

## 1. Giới thiệu

### 1.1. Bài toán

Người nấu ăn ở hộ gia đình Việt thường gặp ba việc lặp lại mỗi ngày: chọn món từ đồ đang có, dùng đồ mua trước khi
hỏng, và (với một số người) giữ lượng năng lượng bữa ăn quanh một mục tiêu hoặc tránh chất gây dị ứng. Các việc này
hiện làm bằng tay.

Tastoria nhận 1–2 ảnh tủ lạnh hoặc túi đồ vừa mua, nhận diện và đếm nguyên liệu, đưa vào kho theo lô, rồi đề xuất
**một** mâm cơm (mặn + rau + canh, hoặc 2 món khi ăn một mình) từ đồ đang có. Mâm ưu tiên lô sắp hỏng, bám mục tiêu
năng lượng của bữa, và loại mọi món chứa nhóm dị ứng đã khai của người dùng và người ăn cùng. Hệ thống lập lịch nấu
song song cả mâm, trừ kho khi nấu xong và ghi nhật ký tuần (thiết kế v2 §1,
[`docs/superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md`](../../superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md)).

### 1.2. Mục tiêu

1. Một hệ thống chạy thật: app Android và web từ một mã nguồn, backend, mô hình nhận diện, trang giới thiệu, triển
   khai trên máy chủ và ra Internet.
2. Bộ phân tích thiết kế đầy đủ: SRS, đặc tả use case, UML, ERD chuẩn hoá từng quan hệ, hợp đồng API, kế hoạch kiểm
   thử, ma trận truy vết.
3. Mọi con số trên app truy được về công thức có nguồn và dữ liệu có nguồn (ví dụ `recipe_nutrition.data_version`).

### 1.3. Phạm vi

Trong phạm vi: 34 use case ở 10 gói (tài khoản, quyền riêng tư, hồ sơ, kho và quét, mâm cơm, nấu và nhật ký, khảo
sát gu, quản trị nội dung, vận hành mô hình, tác vụ định kỳ).

Ngoài phạm vi (thiết kế v2 §1): tính calo từ ảnh món đã nấu, mã vạch và hoá đơn, thực đơn tuần, thông báo đẩy, đặt
hàng, nhiều hồ sơ trong một hộ, bản iOS. Huấn luyện mô hình chạy ngoài hệ thống trên GPU của lab; hệ thống chỉ nhận
mô hình đã huấn luyện qua UC29–UC30. Phần huấn luyện và đánh giá mô hình được trình bày ở hai báo cáo môn Xử lý ảnh
và Học máy; báo cáo này chỉ dùng kết quả của chúng ở chỗ hệ thống phục vụ mô hình.

### 1.4. Đóng góp

| Hạng mục | Nội dung | Nguồn |
|---|---|---|
| Phân tích thiết kế | 34 UC, 446 FR, 39 BR, 10 NFR (31 điều khoản), 62 bảng, 70 endpoint, 56 sơ đồ PlantUML; ma trận truy vết 0 ô trống | [`docs/sad/BaoCao_PhanTichThietKe.md`](../../sad/BaoCao_PhanTichThietKe.md) |
| Backend | FastAPI modular monolith, 14 module nghiệp vụ + `core`, `jobs`; ranh giới module kiểm bằng import-linter | `backend/` |
| Worker quét ảnh | RQ + ONNX Runtime trên CPU, YOLO26n tự huấn luyện, hậu xử lý đối chiếu với ultralytics | `backend/src/tastoria/modules/scan/` |
| Ghép mâm | Tìm tổ hợp có ràng buộc kho gộp, thời gian và dị ứng; lịch nấu bằng CP-SAT | `modules/meal/composer.py`, `modules/meal/schedule.py` |
| App | Expo SDK 58, một mã nguồn Android + web, 33 màn hình chụp ở chế độ sáng và tối | `app/`, `app/docs/screenshots/` |
| Dữ liệu | 180 công thức, 223 nguyên liệu, dinh dưỡng theo EuroFIR, so 45 món với Viện Dinh dưỡng | `data/kb/`, `data/processed/kb/` |
| Triển khai | Docker Compose 7 dịch vụ, Cloudflare Tunnel, sao lưu mã hoá, quay lui theo tag, APK ký riêng | `deploy/` |

Repo có 52 commit trong hai ngày 17/10/2026 (31) và 18/10/2026 (21) (`git log`, đếm lúc viết báo cáo; không tính
commit của báo cáo này).

---

## 2. Khảo sát và yêu cầu

### 2.1. Đối thủ và khoảng trống

Khảo sát bàn giấy ngày 17/10/2026 ([`docs/research/raw/04-doi-thu-va-bang-chung.md`](../../research/raw/04-doi-thu-va-bang-chung.md)
§2–§3) so 15 sản phẩm quốc tế và 8 sản phẩm Việt Nam theo năm tiêu chí:

| Sản phẩm | Ảnh → nguyên liệu | Ưu tiên đồ sắp hết hạn | Cả bộ món | Calo |
|---|---|---|---|---|
| Samsung Food / Food+ | Có | Có ("prioritizing those nearing use-by-date") | Không (kế hoạch tuần, từng món) | Có |
| DELISH KITCHEN (Nhật) | Không (gõ tay) | Không | **Có** (主菜・副菜・汁物) | Ghi calo |
| me:new (Nhật) | Không | Không | **Có**, từ đồ thừa trong tủ | Hiện kcal |
| Frish (Nhật) | Ảnh hoá đơn | **Có** | Có | Có |
| Eat This Much | Không (mã vạch) | Ưu tiên đồ trong kho | Cả ngày | Có |
| Cookpad VN | Không (gõ tay) | Không | Không | Không |
| Thực đơn nấu ăn 365 | Không | Không | Mâm soạn sẵn, không theo kho | Không |

Kết luận của khảo sát: từng thành phần đã có tiền lệ (cả bộ món từ đồ thừa ở DELISH KITCHEN, me:new; ưu tiên đồ sắp
hết hạn ở Samsung Food+, Frish). Không tìm thấy sản phẩm nào làm trọn chuỗi một ảnh → mâm cơm Việt có định lượng
chia giữa các món theo kho → ưu tiên đồ sắp hỏng → bám mục tiêu calo, và không có sản phẩm tương tự bằng tiếng Việt.
Khoảng trống này hẹp: chia lượng nguyên liệu giữa các món là một ràng buộc trong bộ giải, không phải lợi thế khó sao
chép. Phần khó sao chép hơn là mô hình nhận diện nguyên liệu Việt, và phần này chỉ có giá trị nếu đo được tốt hơn
Gemini trên cùng tập test (đã nêu ở báo cáo Xử lý ảnh, chưa đo vì chưa có ảnh tủ lạnh của nhóm).

### 2.2. Người dùng

Bằng chứng từ cùng tài liệu, §5 (các nguồn được ghi số thứ tự trong tệp gốc):

- 78% bà mẹ đi làm ở Hà Nội và TP.HCM nấu bữa tối mỗi ngày (n = 1.032, 2017). Nghiên cứu Q&Me trên hơn 6.000 ảnh bữa
  tối (n = 300, 4/2023): trung bình 3,0 món mỗi bữa, 62 phút nấu, 97% món Việt. Hộ trung bình 3,5–3,6 người; 80,5%
  hộ có tủ lạnh năm 2019. Cấu trúc mặn + rau + canh vì vậy khớp bữa ăn thường ngày.
- 41% bà mẹ đi chợ mỗi ngày; đồ mua ở chợ không có hoá đơn hay mã vạch. Vì lý do này hệ thống có chế độ quét "đồ vừa
  mua" thay cho quét hoá đơn.
- Ở Hà Nội, hơn 70% rác thực phẩm hộ gia đình sinh ra lúc sơ chế và nấu. Đây là căn cứ cho việc tính lượng nguyên
  liệu theo số người ăn.
- Mức độ "hôm nay ăn gì" gây mệt mỏi chưa được khảo sát định lượng nào ở Việt Nam đo; báo cáo không dựa vào giả định
  này.

Tác nhân của hệ thống (SRS §2): A01 Khách, A02 Người dùng, A03 Người tham gia khảo sát, A04 Quản trị viên, A05 Người
biên soạn công thức, A06 Người vận hành mô hình, A07 Người gán nhãn, A08 Bộ lập lịch, A09 Dịch vụ email, A10 Công cụ
gán nhãn. Người ăn cùng không phải tác nhân: A02 khai nhóm dị ứng của họ cho từng bữa.

### 2.3. Tóm tắt SRS

SRS viết theo ISO/IEC/IEEE 29148:2018 ([`docs/sad/01-SRS.md`](../../sad/01-SRS.md), bản 1.1). Số lượng lấy từ báo cáo
phân tích thiết kế §2.1:

| Loại | Số lượng | MoSCoW |
|---|---|---|
| Use case | 34 | M 24 · S 8 · C 2 |
| Yêu cầu chức năng (FR) | 446, mã `FR-<UC>-<số>`, mỗi FR có tiêu chí chấp nhận Given/When/Then | M 339 · S 91 · C 16 |
| Quy tắc nghiệp vụ (BR) | 39 (mâm, dị ứng, lượng và kho, độ tươi, năng lượng, đồng ý, kho món, nấu) | — |
| Yêu cầu phi chức năng (NFR) | 10 mã, 31 điều khoản (10 gốc + 21 điều khoản con), phân loại theo ISO/IEC 25010:2023 | — |
| Ràng buộc | RB-01 … RB-08 | — |
| Giả định, phụ thuộc | GD-01 … GD-07, PT-01 … PT-06 | — |

Một số BR quyết định thiết kế (thiết kế v2 §4):

- **BR-ALG-01**: không món, gia vị hay đồ thay thế nào trong mâm thuộc nhóm dị ứng hoặc trái chế độ ăn của người dùng
  hoặc người ăn cùng. Gia vị luôn có (`is_staple`) chỉ được miễn kiểm kho, không miễn kiểm dị ứng.
- **BR-TRAY-04**: mâm khả thi khi tổng lượng cần của mọi món (gộp) không vượt cận dưới lượng khả dụng của kho.
- **BR-FRESH-04**: lô ở mức "kiểm tra trước khi dùng" không được tính vào kho khả dụng.
- **BR-COOK-02**: "Nấu xong" lũy đẳng, trừ kho + ghi tương tác + chuyển trạng thái trong một giao dịch.
- **BR-CONSENT-01..04**: đồng ý theo mục đích (`health_profile`, `personalization`, `photo_contribution`, `survey`),
  không tích sẵn, rút có hiệu lực ngay.

NFR chính (ngưỡng chấp nhận của SRS 1.1) được liệt kê cùng số đo ở mục 8.1.

---

## 3. Phân tích

### 3.1. Mô hình use case

![UCD00 — Tổng quan use case](../../uml/out/usecase/UCD00-tong-quan.svg)

*Hình 1. UCD00 — 34 use case trong 10 gói và 10 tác nhân (PlantUML, `docs/uml/usecase/UCD00-tong-quan.puml`).*

![UCD05 — Gói mâm cơm, bản xuất từ Visual Paradigm](fig/vp-UCD05-mam-com.png)

*Hình 2. UCD05 — Gói PK5 Mâm cơm, ảnh do Visual Paradigm CE 18.1 xuất từ `Tastoria-UML.vpp` (dựng tự động, xem mục
4.6). UC16, UC17 extend UC15; UC18 extend UC17 và UC15.*

Bảng 34 use case (báo cáo phân tích thiết kế §3.2):

| UC | Tên | Gói | Tác nhân chính | Quan hệ | MoSCoW |
|---|---|---|---|---|---|
| UC01 | Đăng ký tài khoản | PK1 | A01 | | M |
| UC02 | Đăng nhập | PK1 | A01 | | M |
| UC03 | Đăng xuất (một hoặc mọi thiết bị) | PK1 | A02 | | M |
| UC04 | Đặt lại mật khẩu | PK1 | A01 (phụ: A09) | | S |
| UC05 | Quản lý đồng ý theo mục đích | PK2 | A02 | | M |
| UC06 | Tải về dữ liệu cá nhân | PK2 | A02 | | M |
| UC07 | Xoá tài khoản và toàn bộ dữ liệu | PK2 | A02 | | M |
| UC08 | Yêu cầu sửa, hạn chế hoặc phản đối xử lý | PK2 | A02 (phụ: A04) | | C |
| UC09 | Thiết lập hồ sơ 60 giây | PK3 | A02 | include UC05 | M |
| UC10 | Cập nhật hồ sơ, dị ứng, chế độ ăn, cài đặt bếp | PK3 | A02 | | M |
| UC11 | Đặt mục tiêu năng lượng | PK3 | A02 | | M |
| UC12 | Quét nguyên liệu (toàn tủ hoặc đồ vừa mua) | PK4 | A02 | include UC13 | M |
| UC13 | Xác nhận và sửa kết quả quét | PK4 | A02 | | M |
| UC14 | Quản lý kho | PK4 | A02 | | M |
| UC15 | Nhận mâm cơm hôm nay | PK5 | A02 | | M |
| UC16 | Đổi một món | PK5 | A02 | extend UC15 | M |
| UC17 | Xem và chọn thay thế nguyên liệu thiếu | PK5 | A02 | extend UC15 | M |
| UC18 | Quản lý danh sách đi chợ | PK5 | A02 | extend UC17; extend UC15 | S |
| UC19 | Nấu cả mâm | PK6 | A02 | | M |
| UC20 | Hoàn tất bữa nấu (nấu xong một chạm) | PK6 | A02 | | M |
| UC21 | Hoàn tác trừ kho | PK6 | A02 | extend UC20 | S |
| UC22 | Xem nhật ký tuần | PK6 | A02 | | S |
| UC23 | Tham gia khảo sát gu món ăn | PK7 | A03 | | M |
| UC24 | Quản lý đợt khảo sát | PK7 | A06 | | S |
| UC25 | Nhập và kiểm tra kho công thức, nguyên liệu | PK8 | A05 | | M |
| UC26 | Quản lý cặp thay thế nguyên liệu | PK8 | A05 | | S |
| UC27 | Xử lý yêu cầu dữ liệu và xem nhật ký kiểm toán | PK8 | A04 | | S |
| UC28 | Xuất dữ liệu huấn luyện đã bí danh hoá | PK9 | A06 | | S |
| UC29 | Đăng ký và kiểm định phiên bản mô hình | PK9 | A06 | | M |
| UC30 | Triển khai và quay lui phiên bản mô hình | PK9 | A06 | | M |
| UC31 | Gán nhãn ảnh góp | PK9 | A07 (phụ: A10) | | C |
| UC32 | Xoá ảnh quét quá hạn | PK10 | A08 | | M |
| UC33 | Sao lưu cơ sở dữ liệu | PK10 | A08 | | M |
| UC34 | Dọn job quét kẹt, token và khoá lũy đẳng hết hạn | PK10 | A08 | | M |

Tình trạng cài đặt: UC01–UC25, UC29, UC30, UC32–UC34 có mã và kiểm thử trong backend; UC26 có lệnh nhập bảng tra
(`tastoria catalog substitutes import`, 197 cặp trong `data/kb/substitution_pairs.yaml`); UC27 có endpoint
`/admin/data-requests` nhưng chưa có giao diện quản trị; UC28 và UC31 (gán nhãn ảnh góp, mức C) chưa cài.

### 3.2. Đặc tả mẫu: UC15 — Nhận mâm cơm hôm nay

Trích từ [`docs/sad/use-cases/UC15.md`](../../sad/use-cases/UC15.md) (41 FR, FR-15-01 … FR-15-41), theo mẫu Cockburn.

| Mục | Nội dung |
|---|---|
| Mục tiêu | Hệ thống ghép một mâm từ kho của A02, ưu tiên lô sắp hỏng, hợp gu, vừa năng lượng mục tiêu, nấu xong trong thời gian đã chọn, không chứa thứ gì thuộc nhóm dị ứng hoặc trái chế độ ăn của A02 và người ăn cùng |
| Mức, gói | Mục tiêu người dùng; PK5 |
| Tiền điều kiện | A02 đã đăng nhập; kho món có ít nhất một món `published` cho mỗi slot `man`, `rau`, `canh` |
| Đảm bảo tối thiểu | Không lưu hoặc trả mâm vi phạm BR-ALG-01, BR-DIET-01; không ghi `interactions` khi thiếu đồng ý `personalization`; kho không đổi; cùng `Idempotency-Key` không tạo mâm thứ hai |
| Đảm bảo khi thành công | Một `meal_plans` `proposed` với 2–3 `meal_plan_items` `active`, dị ứng người ăn cùng, lô ghim, ảnh chụp mục tiêu năng lượng, số bát cơm, dòng lý do, phiên bản bộ xếp hạng và tham số |
| Quy tắc | BR-TRAY-01 … 08, BR-ALG-01, BR-DIET-01, BR-NUT-04, BR-NUT-06, BR-CONSENT-02, 03, BR-FRESH-04, 05, BR-QTY-01, 02, BR-COOK-01, BR-CATALOG-01 |
| Endpoint | `POST /meal-plans`, `GET /meal-plans/latest`, `GET /meal-plans/{id}`, `POST /meal-plans/{id}/accept`, `GET /pantry/lots`, `GET /reference`, `GET /recipes`, `GET /recipes/{id}`, `POST /events` |

**Kịch bản chính**

| # | Bước |
|---|---|
| 1 | A02 mở màn Mâm cơm hôm nay; app hiện nhóm dị ứng, lô trong kho, số người mặc định. |
| 2 | A02 chọn bữa, số người n, thời gian nấu tối đa, (tuỳ chọn) dị ứng người ăn cùng và tối đa 2 lô "phải dùng", bấm "Ra mâm". |
| 3 | App gửi `POST /meal-plans` với `Idempotency-Key` mới. |
| 4 | Hệ thống kiểm khoá lũy đẳng và dữ liệu vào. |
| 5 | Hệ thống lấy ràng buộc bữa ăn qua `profile.get_meal_constraints()`: dị ứng, chế độ ăn, số họng bếp, 5 món hay ăn, E_mâm. |
| 6 | Hệ thống kiểm đồng ý `personalization` hiện hành. |
| 7 | Hệ thống tính lượng khả dụng và độ gấp u của từng lô; bỏ lô ở mức "kiểm tra trước khi dùng". |
| 8 | Hệ thống lọc cứng món `published` theo dị ứng và chế độ ăn. |
| 9 | Hệ thống chấm điểm gu từng món. |
| 10 | Hệ thống ghép mâm: chọn tổ hợp thoả BR-TRAY-01, 04, 05, 08 có hàm mục tiêu cao nhất. |
| 11 | Hệ thống tính số bát cơm, khoảng calo, dòng lý do. |
| 12 | Hệ thống lưu mâm `proposed`, ghi sự kiện `served` nếu có đồng ý, trả 201. |
| 13 | App hiện mâm tròn, dòng lý do, thanh calo dạng khoảng, "gợi ý x bát cơm". |
| 14 | A02 xem chi tiết món; app gửi sự kiện `viewed`. |
| 15 | A02 bấm "Nấu mâm này"; mâm sang `accepted`; app chuyển sang UC19. |

**Mở rộng chính**: 4c gửi lại cùng khoá, cùng nội dung → trả nguyên văn phản hồi đã lưu; 4e bản gửi lại tới khi yêu
cầu đầu còn xử lý → 409 kèm `Retry-After`; 5a chưa đồng ý `health_profile` → không có E_mâm, β = 0; 6a chưa đồng ý
`personalization` → xếp hạng bằng trung bình món + content-based, không ghi `served`; 10a không có mâm 3 món khả thi
khi n ≥ 2 → thử mâm 2 món; 10b vẫn không có → 422 `no_feasible_tray` kèm nguyên liệu thiếu, điểm mở rộng tới UC18;
10c lô ghim không dùng được → 422 `pin_unsatisfiable`; \*a truy cập mâm người khác → 404 (chống BOLA).

Màn hình tương ứng trên app (ảnh chụp bởi `app/scripts/e2e_flow.py`, 390 × 844):

| Mâm ghép | Đổi món | Thiếu gì? |
|---|---|---|
| ![Mâm cơm](../../../app/docs/screenshots/13-mam-ghep-light.png) | ![Đổi món](../../../app/docs/screenshots/16-doi-mon-ly-do-light.png) | ![Thiếu gì](../../../app/docs/screenshots/18-thieu-gi-light.png) |

### 3.3. Sơ đồ hoạt động và tuần tự chính

![AD01 — Từ quét đến nấu xong](../../uml/out/activity/AD01-quet-den-nau.svg)

*Hình 3. AD01 — Luồng chính từ quét tủ lạnh tới nấu xong, ba làn Người dùng, App, api; gồm nhánh đổi món, thay
nguyên liệu và hoàn tác.*

![AD02 — Ghép mâm](../../uml/out/activity/AD02-ghep-mam.svg)

*Hình 4. AD02 — Ghép mâm bên trong `POST /meal-plans`: làn `profile` cấp ràng buộc, `pantry` cấp lượng và độ gấp,
`meal` lọc cứng, xếp hạng và chọn tổ hợp.*

![SD01 — Quét ảnh bất đồng bộ](../../uml/out/sequence/SD01-quet-anh-bat-dong-bo.svg)

*Hình 5. SD01 — `POST /scans` trả 202, worker suy luận bất đồng bộ, app chờ bằng long-poll; sweeper (UC34) xử lý job
kẹt.*

![SD03 — Tạo mâm](../../uml/out/sequence/SD03-tao-mam.svg)

*Hình 6. SD03 — `meal` gọi `profile.get_meal_constraints()`, `pantry`, `privacy` và bộ xếp hạng; ghi mâm, sự kiện và
khoá lũy đẳng trong một Unit of Work.*

![SD06 — Nấu xong và hoàn tác](../../uml/out/sequence/SD06-nau-xong-va-hoan-tac.svg)

*Hình 7. SD06 — Tạo phiên nấu với lịch CP-SAT, nấu xong trong một Unit of Work, hoàn tác trong 10 phút bằng giao dịch
đảo.*

Các sơ đồ còn lại (6 hoạt động, 10 tuần tự, 8 máy trạng thái, 8 lớp) ở báo cáo phân tích thiết kế §5–§6.

---

## 4. Thiết kế

### 4.1. Kiến trúc: modular monolith

Quyết định ở [ADR 0001](../../adr/0001-modular-monolith-ranh-gioi-module.md). Bốn phương án được xét: monolith không
chia module, modular monolith có ranh giới cưỡng chế, microservice, modular monolith mỗi module một schema. Chọn
phương án 2 vì hai thao tác lõi (nấu xong, xác nhận quét) ghi vào nhiều module và cần một giao dịch cục bộ;
microservice sẽ phải thêm saga hoặc outbox và nhân số container, không hợp quy mô một người làm.

Cách cưỡng chế:

- Mỗi module là một package `backend/src/tastoria/modules/<tên>/` gồm `router.py`, `service.py` (giao diện công
  khai), `models.py`, `schemas.py`. Module khác chỉ được gọi `service.py` và `schemas.py` của module nó được phép phụ
  thuộc.
- Danh sách phụ thuộc được phép nằm ở `docs/sad/model.yaml`; `backend/scripts/gen_importlinter.py` sinh
  `backend/.importlinter`, và `tests/unit/test_architecture.py` chạy import-linter trong bộ kiểm thử.
- Khi hai module cần nhau ngược chiều phụ thuộc (ví dụ `meal` cần biết mâm có phiên nấu đang chạy, nhưng `cooking`
  phụ thuộc `meal`), `tastoria.app` tiêm hàm gọi (`MealDeps`, `SubstituteDeps`) thay vì import trực tiếp.

Module (thư mục `backend/src/tastoria/modules/`): `identity`, `privacy`, `profile`, `catalog`, `pantry`, `scan`,
`events`, `substitute`, `meal`, `cooking`, `journal`, `survey`, `mlops`, `admin`; cộng `core` (cấu hình, phiên DB,
Unit of Work, lỗi RFC 9457, Idempotency-Key, xác thực) và `jobs` (điểm vào cho việc định kỳ). `model.yaml` đánh số
M01–M16.

![CP01 — Sơ đồ thành phần, bản Visual Paradigm](fig/vp-CP01-thanh-phan.png)

*Hình 8. CP01 — 16 module, giao diện `service` mỗi module và phụ thuộc được phép; bên ngoài là worker, scheduler,
nginx, app, SMTP, Label Studio. Ảnh do Visual Paradigm xuất; bản PlantUML gốc dễ đọc hơn ở
[`docs/uml/out/component/CP01-thanh-phan.svg`](../../uml/out/component/CP01-thanh-phan.svg).*

![DP01 — Sơ đồ triển khai, bản Visual Paradigm](fig/vp-DP01-trien-khai.png)

*Hình 9. DP01 — Docker Compose trên máy chủ lab (nginx, api, migrate, worker, scheduler, postgres, valkey), ra Internet
qua cloudflared; máy GPU lab cho huấn luyện tách riêng.*

### 4.2. Thiết kế cơ sở dữ liệu

PostgreSQL 18 + pgvector 0.8, **62 bảng, 3 view** (`v_current_consents`, `v_pantry_lot_balance`, `v_journal_days`).
DDL ở [`db/schema.sql`](../../../db/schema.sql); migration Alembic 0001 chạy đúng tệp này (bản sao byte-identical,
có kiểm thử), 0002 thêm mục đích đồng ý, 0003 thêm `recipe_make_ahead`. Từ điển dữ liệu sinh từ catalog PostgreSQL:
[`docs/sad/05-tu-dien-du-lieu.md`](../../sad/05-tu-dien-du-lieu.md).

ERD có hai mức: mô hình khái niệm Chen ([ERD00](../../uml/out/erd/ERD00-khai-niem-chen.svg), 29 thực thể) và mô hình
logic/vật lý chân quạ chia 7 nhóm + 1 tổng quan (ERD01–ERD08). Hai nhóm của luồng chính, bản do Visual Paradigm xuất
từ `Tastoria-ERD.vpp` (62 bảng, 393 cột, 97 khoá ngoại; [`docs/vp-import-kit/TU-DONG.md`](../../vp-import-kit/TU-DONG.md)):

![ERD05 — Kho và quét](fig/vp-ERD05-kho-quet.png)

*Hình 10. ERD05 — `scans`, `scan_images`, `detections`, `scan_items`, `pantry_lots`, `pantry_transactions` và các
bảng cha `users`, `ingredients`, `vision_classes`, `model_versions`.*

![ERD06 — Mâm và nấu](fig/vp-ERD06-mam-nau.png)

*Hình 11. ERD06 — `meal_plans`, `meal_plan_items`, phiên nấu, thay thế, đi chợ, tương tác.*

**Chuẩn hoá.** [`docs/sad/04-chuan-hoa.md`](../../sad/04-chuan-hoa.md) xét từng bảng: khoá ứng viên, phụ thuộc hàm
không tầm thường, lần lượt 1NF, 2NF, 3NF, BCNF. Hai quy ước áp chung: N1 (phụ thuộc hàm có vế trái chứa cột cho phép
NULL chỉ xét trên các bộ có vế trái khác NULL) và N2 (ràng buộc mẫu hằng trong một bộ ép bằng `CHECK`, không tính
khi xét dạng chuẩn). Kết quả: **55 bảng đạt BCNF; 7 bảng cố ý dừng ở 2NF hoặc 1NF**.

**Phi chuẩn hoá có kiểm soát.** Mỗi trường hợp có lý do và cơ chế giữ nhất quán (trích báo cáo phân tích thiết kế
§7.4, đủ 13 mục D1–D13 ở tệp gốc):

| Mục | Dư thừa | Lý do | Cơ chế giữ nhất quán |
|---|---|---|---|
| D1 | `recipe_nutrition` dẫn xuất từ nguyên liệu × tỉ lệ ăn được × thành phần (1NF) | Ghép mâm cần kcal mọi món ứng viên mỗi lần gọi | Lệnh nhập catalog tính lại; `data_version` ghi phiên bản nguồn |
| D2 | Cột ảnh chụp ở mâm, phiên nấu (`e_target_kcal`, `kcal_per_person`, `burners`) | Giữ giá trị tại thời điểm lập mâm | Ghi một lần |
| D4 | `interactions.user_id` cùng FK ghép tới `meal_plans (id, user_id)` | Sự kiện ngoài mâm vẫn phải thuộc một người | FK ghép bảo đảm khớp chủ mâm |
| D6 | `meal_plan_items.slot` chép `recipes.slot`, FK ghép `(id, slot)` | Chỉ mục duy nhất một phần `UNIQUE (meal_plan_id, slot) WHERE status = 'active'` | FK ghép |
| D9 | `user_id` ở `pantry_lots`, `shopping_items` | Lọc chống BOLA và xoá theo người bằng một câu lệnh | Trigger ghi một lần |
| D10 | `scan_items.model_count` suy được từ `detections` | Giữ số đếm lúc suy luận để so với `final_count` khi đánh giá mô hình | Ghi một lần |

Các bất biến (món đã công bố không sửa, bảng nhật ký chỉ ghi thêm, cột chỉ ghi một lần) được ép bằng trigger trong
`db/schema.sql`; vai trò `tastoria_app` bị thu hồi `UPDATE`, `DELETE`, `TRUNCATE` trên bốn bảng chỉ ghi thêm.

**Kho theo lô.** Kho không lưu "1 dòng mỗi nguyên liệu" mà lưu `pantry_lots` (mỗi lần thêm đồ một lô, có
`acquired_at`) và `pantry_transactions` chỉ ghi thêm. Lượng là khoảng gam [g_min, g_max] (BR-QTY-01) vì mức "ít /
vừa / nhiều" và số đếm từ ảnh không cho một con số chính xác. Lượng hiện tại = lượng đầu + Σ giao dịch, tính bằng view
`v_pantry_lot_balance`. Độ gấp u tính lúc đọc, không lưu (BR-FRESH-05).

### 4.3. Hợp đồng API

[`docs/api/openapi-v1.yaml`](../../api/openapi-v1.yaml): OpenAPI 3.1, 70 operation, kiểm hợp lệ bằng
`openapi-spec-validator` trong bộ kiểm thử.

| Quy ước | Nội dung |
|---|---|
| Tiền tố | `/api/v1`, trừ `/healthz`, `/readyz` |
| Lỗi | RFC 9457 `application/problem+json` với trường `code` ổn định; enum `ProblemCode` có 77 mã; app ánh xạ mỗi mã sang câu tiếng Việt (`app/src/api/errors.ts`) |
| Định danh, BOLA | Id công khai là UUID; mọi truy vấn theo `{id}` lọc theo chủ sở hữu, tài nguyên của người khác trả 404 chứ không 403 |
| Lũy đẳng | Header `Idempotency-Key` bắt buộc ở 5 thao tác (`POST /scans`, `POST /meal-plans`, đổi món, `POST /cook-sessions`, `/complete`); lưu băm thân yêu cầu + phản hồi 48 giờ; gửi lại cùng khoá cùng thân → trả nguyên văn; cùng khoá khác thân → 422 `idempotency_key_reused`; bản sao đến khi bản đầu còn chạy → 409 `idempotency_in_progress` + `Retry-After: 1`. `POST /events` chống trùng bằng `event_id` do app sinh |
| Bất đồng bộ | `POST /scans` trả 202 + `Location` + `Retry-After`; `GET /scans/{id}?wait=10` long-poll |
| Phân trang | Keyset: `cursor` + `limit` (≤ 100) → `next_cursor`, khoá sắp xếp (created_at, id) |
| Phiên bản app | Header `X-App-Version`; thấp hơn `MIN_APP_VERSION` → 412 `app_too_old` |
| Truy vết | Phần mở rộng `x-use-cases`, `x-module`, `x-idempotency`, `x-required-role` trỏ về `model.yaml` |

Phân bố quyền của 70 endpoint: 51 `user`, 10 `public`, 4 `public + respondent_token` (khảo sát), 3 `staff:admin`,
2 `staff:ml_operator`. Thao tác nhân sự còn lại chạy bằng lệnh CLI `tastoria …` trong container.

Hợp đồng được kiểm hai chiều trong bộ kiểm thử (`tests/integration/test_openapi_contract.py`): mọi operation backend
cài đặt có trong OpenAPI với cùng method, path, operationId; mọi trường backend trả trong thân 2xx có khai báo trong
schema phản hồi tương ứng.

### 4.4. Bảo mật và quyền riêng tư

Căn cứ: Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 và Nghị định 356/2025/NĐ-CP. Hồ sơ đánh giá tác động ở
[`docs/sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md`](../../sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md) (bản nháp 0.1,
chưa được rà soát pháp lý; điều khoản đối chiếu qua bản đăng lại, chưa đối chiếu Công báo). Hệ thống xử lý dữ liệu
nhạy cảm (chỉ số cơ thể, dị ứng, hành vi sử dụng), nên ngoại lệ cho doanh nghiệp nhỏ ở Luật 91 Điều 38 không áp dụng.

| Yêu cầu | Cách làm | ADR / BR |
|---|---|---|
| Xác thực | Mật khẩu Argon2id (`pwdlib`); access JWT HS256 15 phút có `kid`; refresh token ngẫu nhiên 30 ngày lưu SHA-256, xoay vòng theo family, dùng lại token đã thu hồi thì thu hồi cả family; `users.token_version` để vô hiệu mọi access token khi rút đồng ý hoặc đăng xuất mọi nơi | ADR 0004, NFR-SEC-01 |
| Chống dò mật khẩu | Khoá 15 phút sau 5 lần sai theo (email, IP), đếm trong Valkey; Valkey không chạy thì đăng nhập trả 503 (đóng khi lỗi) | NFR-SEC-02 |
| Mã hoá cột sức khoẻ | AES-256-GCM ở tầng ứng dụng, có `key_id` để xoay khoá; chỉ module `profile` giữ khoá; module khác nhận ràng buộc đã dẫn xuất qua `profile.get_meal_constraints()`; mỗi lần giải mã ghi `audit_log` | ADR 0005 |
| Đồng ý theo mục đích | Bốn mục đích, mặc định tắt; `consent_events` chỉ ghi thêm, gắn phiên bản điều khoản (băm SHA-256 văn bản đóng băng trong migration 0002); trạng thái hiện tại là view | ADR 0006, BR-CONSENT-01 |
| Rút đồng ý | Tăng `token_version`, xoá dữ liệu của mục đích đó (rút `personalization` xoá `interactions`) | BR-CONSENT-04 |
| Quyền chủ thể dữ liệu | `dsr_requests`; tải về, xoá, rút đồng ý do job `process-dsr` hoàn tất (lịch mỗi 10 phút), mục tiêu ≤ 24 giờ, trong hạn NĐ 356 Điều 5 | BR-DSR-01, NFR-PRIV-01 |
| Lưu giữ tối thiểu | Ảnh quét không góp xoá sau 30 ngày (job mỗi giờ); sao lưu giữ 14 ngày, nằm trong hạn xoá 20 ngày của NĐ 356 Điều 5 khoản 4 | BR-RETAIN-01 |
| Ảnh tải lên | ≤ 2 ảnh × 3 MB, kiểm magic bytes, số điểm ảnh ≤ 4096² đọc từ header trước khi giải mã, cảnh báo bom giải nén coi là lỗi, `exif_transpose`, mã hoá lại JPEG từ bộ đệm RGB mới (bỏ EXIF/GPS/ICC/XMP) | NFR-SEC-02.b |
| Tệp riêng tư | Ảnh và bản xuất phục vụ qua `X-Accel-Redirect` tới location `internal` của nginx sau khi API kiểm chủ sở hữu | ADR 0002 |
| Bí danh hoá | `dsr_requests.subject_ref` = HMAC-SHA256 với khoá riêng; tài liệu gọi đúng là bí danh hoá, không gọi là ẩn danh | thiết kế v2 #22 |
| Nơi huấn luyện | GPU lab trong nước; Colab/Kaggle chỉ cho dữ liệu công khai | ADR 0012 |

Hồ sơ đánh giá tác động liệt kê 18 rủi ro R01–R18; sau biện pháp còn 4 rủi ro mức Trung bình (R02 dị ứng và kcal
không mã hoá, R05 nội dung ảnh, R07 dữ liệu còn trong bản sao lưu và bản xuất sau khi xoá, R09 luồng ra nước ngoài).
Những việc chưa đạt được ghi ở mục 9.

### 4.5. Các ADR chính

13 ADR định dạng MADR ở [`docs/adr/`](../../adr/), mỗi ADR so 3–6 phương án:

| ADR | Quyết định | Phương án bị loại tiêu biểu và lý do |
|---|---|---|
| 0001 | Modular monolith, import-linter | Microservice: mất giao dịch cục bộ cho nấu xong và xác nhận quét |
| 0002 | Lưu tệp trên ổ đĩa, `X-Accel-Redirect` | Ghim image MinIO cũ: MinIO đã lưu trữ (archived) 25/04/2026, không còn bản vá; SeaweedFS: thêm một dịch vụ phải vận hành và sao lưu |
| 0003 | Valkey 9 + RQ, container cron | Celery + Redis: cấu hình nặng cho 3 loại job; Redis từ 8.0 theo RSALv2/SSPLv1/AGPLv3, Valkey 9 là BSD-3 |
| 0004 | Access JWT ngắn + refresh opaque xoay vòng | JWT dài hạn: không thu hồi được; DPoP: thư viện phía Expo còn ít |
| 0005 | Mã hoá AES-GCM tầng ứng dụng | `pgcrypto`: khoá đi qua câu SQL, dễ lọt vào log truy vấn |
| 0006 | Đồng ý là nhật ký sự kiện chỉ ghi thêm | Cờ boolean: không biết người dùng đã đồng ý phiên bản điều khoản nào |
| 0007 | `Idempotency-Key` + Unit of Work | Mỗi service tự commit: lỗi giữa chừng để lại kho đã trừ, phiên chưa đóng |
| 0008 | Phục vụ xếp hạng bằng mảng NumPy đã xuất | Cài LightFM trong image API: phụ thuộc một bản fork cộng đồng, build có thể vỡ |
| 0009 | Lịch nấu bằng CP-SAT, heuristic tuần tự làm dự phòng | Heuristic tự viết: không chứng minh được tối ưu, dễ sai ở ràng buộc tích luỹ |
| 0010 | Expo, một mã nguồn Android + web | Kotlin + React web: hai mã nguồn; chỉ PWA: không có bản Android cài được |
| 0011 | YOLO26n, nghĩa vụ AGPL-3.0 | Giữ D-FINE-N/RF-DETR-N (Apache-2.0) làm lối thoát giấy phép |
| 0012 | Huấn luyện trên GPU lab trong nước | Colab/Kaggle cho mọi việc: chuyển dữ liệu người dùng ra nước ngoài, phát sinh hồ sơ chuyển dữ liệu xuyên biên giới |
| 0013 | Giao sơ đồ cho Visual Paradigm qua PlantUML-VP | Vẽ tay: tốn công, không kiểm tự động, dễ lệch `model.yaml`; XMI: cần bản Modeler trở lên |

### 4.6. Bộ sơ đồ Visual Paradigm

Nguồn chuẩn của sơ đồ là PlantUML (`docs/uml/**/*.puml`, 56 sơ đồ, ảnh ở `docs/uml/out/`). Ngày 18/10/2026 hai tệp
`.vpp` được dựng tự động trên máy chủ không giao diện ([`docs/vp-import-kit/TU-DONG.md`](../../vp-import-kit/TU-DONG.md)):
Visual Paradigm CE 18.1 chạy dưới Xvfb; plugin PlantUML-VP 1.0.0 được vá 7 lỗi (NPE với actor có stereotype và
fragment lồng, đổi tên phần tử trùng, cạnh không hợp lệ, hộp thoại modal treo tiến trình) để nhập 47 sơ đồ UML; vì
`ReverseDDL.sh` của bản CE báo "Feature not supported", ERD được dựng bằng một plugin viết trên Open API của VP đọc
`db/schema_vp.sql` (62 bảng, 393 cột, 97 khoá ngoại, 8 ERD). Ảnh ở mục 3–4 có tiền tố `vp-` là ảnh do VP xuất từ hai
tệp này. Phần còn phải chỉnh tay trong VP (bố cục sơ đồ tuần tự dồn lifeline về x = 0, làn của sơ đồ hoạt động, 6 lớp
liên kết ở CL01) được liệt kê ở TU-DONG.md §6. Tệp `.vpp` và ảnh xuất nằm trong `dist/` (không commit); năm ảnh dùng
trong báo cáo đã chép vào `docs/reports/ptud/fig/`.

---

## 5. Cài đặt

Kích thước mã lúc viết: backend 16.112 dòng Python trong `backend/src/tastoria` (39 tệp kiểm thử); app 11.521 dòng
TypeScript/TSX trong `app/src` (đếm bằng `wc -l`, gồm cả dòng trống và chú thích).

### 5.1. Backend FastAPI theo module

- FastAPI + SQLAlchemy 2.0 đồng bộ + psycopg 3. Endpoint đồng bộ chạy trong threadpool của FastAPI nên lời gọi DB
  không chặn vòng lặp sự kiện.
- **Một request là một giao dịch.** Dependency `Uow` mở giao dịch và commit trước khi gửi phản hồi
  (`Depends(..., scope="function")`), nên commit lỗi trả 5xx, không bao giờ trả 200 rồi mất dữ liệu. Tác dụng ngoài
  DB (gửi thư, đưa job vào hàng đợi, ghi tệp) đăng ký vào `uow.after_commit`.
- Idempotency-Key dùng `pg_try_advisory_xact_lock` theo (người dùng, khoá); bản sao đồng thời nhận 409 ngay thay vì
  chờ khoá.
- Log JSON có `request_id`; `/healthz` (tiến trình sống) và `/readyz` (kiểm database, valkey, models).
- CLI `tastoria` (Typer): `db upgrade`, `catalog import`, `catalog substitutes import`, `survey …`, `mlops register |
  gate | deploy | rollback | list`, `worker`, `jobs sweep | process-dsr | purge-images`. Mỗi lệnh nhân sự ghi một dòng
  `audit_log`.
- Ba lát cắt cài đặt theo thứ tự (backend/README.md): lát 1 `core`, `identity`, `privacy`, `profile`; lát 2 `catalog`,
  `pantry`, `meal`, `substitute`, `events`, `cooking`, `journal`, `admin`, cộng `survey`; lát 3 `mlops`, `scan` và
  worker.

### 5.2. Worker quét ảnh ONNX

Luồng (UC12, SD01; [`backend/README.md`](../../../backend/README.md) mục "Slice 3"):

1. `POST /scans` kiểm và lưu ảnh, ghi `scans` ở trạng thái `queued`, commit, rồi mới đưa job vào hàng đợi RQ `scan`
   trên Valkey. Mất job (API chết giữa commit và enqueue) thì sweeper đưa lại sau 60 s.
2. Worker là RQ **SimpleWorker** (không fork mỗi job) để phiên ONNX và pool DB được dùng lại và luồng của ONNX Runtime
   không bị fork. Phiên nạp một lần khi khởi động, kiểm sha256 của tệp mô hình trước khi tạo phiên; ONNX Runtime 2
   luồng intra-op, 1 luồng inter-op, tắt spin; container giới hạn `cpus: 2`, `mem_limit: 4g`.
3. Job nhận quyền xử lý bằng `UPDATE … WHERE status = 'queued'`; job trùng không tìm thấy dòng thì không làm gì. Lỗi
   (kể cả hết 30 s) với `attempts` < 3 đưa scan về `queued` và tạo job mới; lần thứ 3 đặt `failed` kèm `error_code`.
4. Hậu xử lý: đầu ra YOLO26n đã xuất là `[1, 17, 8400]` (đầu one-to-many, `end2end: False`), nên backend áp NMS theo
   từng lớp ở IoU 0,7 như ultralytics. Kiểm thử đơn vị so với `predict` của ultralytics 8.4.173 trên 2 ảnh val: cùng
   số khung (5 và 5), cùng lớp, IoU từng cặp > 0,9 ([`docs/reports/xu-ly-anh/ket-qua-so-bo.md`](../xu-ly-anh/ket-qua-so-bo.md) §11.1).
5. Ngưỡng tin cậy 0,18 chọn trên tập val (897 ảnh) theo macro-F1 lớn nhất (0,499), lưu trong
   `model_versions.metrics.serving` của phiên bản mô hình, không nằm trong mã.
6. Khung → chip: lớp thị giác → nguyên liệu mặc định; mỗi nguyên liệu một chip; số đếm của lớp đếm được = Σ theo ngăn
   của max giữa các ảnh cùng ngăn (BR-SCAN-01). Worker PUBLISH lên kênh `scan:<id>`; long-poll của API đăng ký kênh
   đó và đọc lại trạng thái ít nhất mỗi giây.
7. Chỉ `POST /scans/{id}/confirm` ghi kho, trong một Unit of Work có khoá dòng `scans` (BR-SCAN-02).

Mô hình được đưa vào hệ thống qua UC29–UC30: `tastoria mlops register` chép tệp vào volume và ghi sha256,
`gate` kiểm tệp tải được bằng onnxruntime, độ rộng đầu ra = 4 + số lớp, bản đồ lớp đủ 0..n−1, có ngưỡng phục vụ;
`deploy` và `rollback` chỉ đổi con trỏ trong `model_deployments`. `gate` không đặt ngưỡng chất lượng vì chưa có tập
test do nhóm thu. **Chưa có mô hình độ tươi nào được triển khai**: bản MobileNetV3 của báo cáo Xử lý ảnh chỉ lưu dự
đoán out-of-fold, có 3 mức (thiếu mức "kiểm tra") và chưa hiệu chỉnh; chip vì vậy không có xác suất độ tươi và lô dùng
u = u_time (BR-FRESH-02, nhánh không có ảnh độ tươi).

### 5.3. Thuật toán ghép mâm

Hàm mục tiêu (thiết kế v2 §6.2, `backend/src/tastoria/modules/meal/composer.py`):

$$\max_m \;\sum_{r \in m} \hat s'(u, r) \;+\; \alpha\,U(m) \;-\; \beta\,\frac{|E(m) - E_{\text{mâm}}|}{E_{\text{mâm}}} \;-\; \gamma\,D(m)$$

- ŝ'(u, r) ∈ [0, 1]: điểm gu đổi thành phân vị theo người trong từng slot. Bộ xếp hạng đang phục vụ là
  `BaselineRanker`: độ phổ biến có co rút từ tương tác của người đã đồng ý + cosine nội dung với 5 món hay ăn. Chưa có
  mô hình xếp hạng nào được triển khai (lý do ở báo cáo Học máy: chưa có người tham gia khảo sát).
- U(m) = Σ_l u_l · min(1, dùng_l / g_min_l) / Σ_l u_l trên các lô được thưởng (u ∈ [0,5; 1,0], không ở mức kiểm tra).
  Lượng cần của mâm lấy từ lô ghim trước, rồi lô gấp nhất, đúng thứ tự trừ kho khi nấu.
- E(m) mỗi người = Σ kcal các món + số bát cơm × E_bát; số bát = clip(round½((E_mâm − Σ kcal) / E_bát), 0,5, 3).
  Không có mục tiêu năng lượng (chưa đồng ý `health_profile`) thì β = 0 và không gợi ý bát cơm.
- D(m) = (cặp món trùng cách nấu + cặp trùng nguyên liệu chính) / số cặp.
- Trọng số đang dùng là bản tạm `tray-p0-provisional`: α = 1, β = 1, γ = 0,5. Báo cáo Học máy đã chạy lưới α/β/γ trên
  150 kịch bản tủ lạnh tổng hợp; việc chốt trọng số theo quy tắc công bố trước còn chờ dữ liệu khảo sát thật.

Thủ tục tìm kiếm:

1. Lọc cứng dị ứng và chế độ ăn trước (BR-ALG-01, BR-DIET-01): chỉ món được phép mới thành ứng viên.
2. Bỏ món không đủ kho ngay cả khi đứng một mình.
3. Cắt top-K = 20 mỗi slot theo điểm cấp món ŝ' + α·U_r − β·|kcal_r − phần chia| / E_mâm.
4. Duyệt tổ hợp mặn × rau × canh, kiểm kho gộp (BR-TRAY-04), lô ghim dùng ≥ 50% g_min (BR-TRAY-08), và một cận dưới
   của makespan để cắt nhánh. Không tổ hợp nào qua thì K = toàn bộ. Vẫn không có thì thử mâm 2 món, rồi trả
   `no_feasible_tray` kèm nguyên liệu thiếu (BR-TRAY-06).
5. Các mâm tốt nhất được giải lịch nấu chính xác bằng CP-SAT theo thứ tự hàm mục tiêu; mâm đầu tiên có makespan ≤
   thời gian tối đa người dùng chọn được trả về (BR-TRAY-05).

### 5.4. Lịch nấu CP-SAT

`backend/src/tastoria/modules/meal/schedule.py` (ADR 0009, OR-Tools CP-SAT), dùng chung cho `meal` (tính makespan
khi ghép) và `cooking` (lịch của `POST /cook-sessions`). Đơn vị thời gian 1 phút.

- Mỗi bước một biến interval; các bước trong một món theo thứ tự (`end(i) ≤ start(i+1)`).
- Người nấu làm một bước chủ động một lúc: `AddNoOverlap` trên các bước chủ động. Bước thụ động (ninh, ngâm) không
  chiếm người nhưng có thể chiếm họng bếp.
- Bước chiếm bếp: `AddCumulative` với sức chứa = số họng bếp (`user_settings.burners`, mặc định 2).
- Mọi món xong trong cửa sổ [M − 5, M] với M là makespan, để các món cùng nóng khi dọn; món xào xong sau mọi món khác.
- Mục tiêu: cực tiểu M. Giới hạn 2 s, 1 luồng, seed 0.
- Cửa sổ 5 phút có thể bất khả (một họng bếp, món kho 30 phút và một món xào): giải lại không có cửa sổ (trạng thái
  `relaxed`). CP-SAT không tìm được lời giải trong giới hạn thì trả lịch tuần tự (`fallback`), vẫn giữ NoOverlap,
  Cumulative và thứ tự bước.
- Món làm sẵn (dưa muối, măng ngâm; bước thụ động > 120 phút) đánh dấu `lam_san`; các bước làm trước không đưa vào
  lịch và không tính vào makespan.

Kiểm thử tính chất (`tests/integration/test_cooking.py`, Hypothesis 150 ví dụ) kiểm mọi lịch CP-SAT của mâm ngẫu nhiên
từ kho món thật qua bộ kiểm BR-COOK-01 viết độc lập.

### 5.5. App Expo một mã nguồn Android + web

ADR 0010; [`app/README.md`](../../../app/README.md). Expo SDK 58 (React Native 0.88), TypeScript, expo-router;
`web.output: "single"` cho bản web.

- **Client API sinh từ hợp đồng**: `npm run gen:api` chạy openapi-typescript trên `openapi-v1.yaml` ra
  `src/api/schema.d.ts`; `openapi-fetch` gọi có kiểu. Kiểu sai so với hợp đồng là lỗi `tsc`.
- **Phiên**: refresh token trong `expo-secure-store` trên Android, `sessionStorage` trên web; client tự làm mới access
  token và gửi `X-App-Version`.
- **Outbox**: "Nấu xong" và sự kiện được ghi vào hàng đợi cục bộ trước khi gửi; gửi lại dùng cùng `Idempotency-Key`
  / `event_id`, nên mạng chập chờn không làm trừ kho hai lần.
- **Quét**: ảnh nén về cạnh dài 1.280 px JPEG (`expo-image-manipulator`) trước khi tải lên.
- **Nấu**: hẹn giờ theo thời điểm tuyệt đối (không đếm ngược trong bộ nhớ), `keep-awake` trong lúc nấu, lưu phiên
  nấu cục bộ.
- **Giao diện**: bảng màu sáng và tối trong `src/theme/tokens.ts` (tỉ lệ tương phản ghi ở chú thích đầu tệp), vùng
  chạm 48 dp, nhãn độ tươi luôn có chữ kèm chấm màu (NFR-A11Y-01.b), font Be Vietnam Pro.
- **Màn hình**: đăng nhập, đăng ký, quên/đặt lại mật khẩu; đồng ý + hồ sơ 4 bước; 5 tab (trang chủ, kho, mâm, đi chợ,
  nhật ký); quét và xác nhận; chi tiết món; nấu cả mâm; nấu xong; cài đặt; khảo sát (công khai, không cần tài khoản).
- **APK**: dựng tại máy (không dùng EAS), ký bằng khoá upload riêng để ngoài repo (`~/.config/tastoria/`), chỉ ABI
  arm64-v8a + armeabi-v7a. Bản 0.1.1 (versionCode 2) chặn các quyền Android do thư viện kéo vào mà app không dùng
  (RECORD_AUDIO, SYSTEM_ALERT_WINDOW, sinh trắc, đọc/ghi bộ nhớ ngoài); còn INTERNET, CAMERA, VIBRATE,
  ACCESS_NETWORK_STATE (commit `bb9f978`).

| Đăng nhập (live) | Kho | Nấu cả mâm | Nấu xong | Nhật ký |
|---|---|---|---|---|
| ![](fig/live-dang-nhap-390.png) | ![](../../../app/docs/screenshots/12-kho-light.png) | ![](../../../app/docs/screenshots/20-nau-ca-mam-light.png) | ![](../../../app/docs/screenshots/22-da-tru-kho-light.png) | ![](../../../app/docs/screenshots/27-nhat-ky-dark.png) |

*Hình 12. Ảnh đầu chụp từ bản chạy thật ngày 18/10/2026 (390 px); bốn ảnh sau từ `app/docs/screenshots/` do
`app/scripts/e2e_flow.py` chụp trên backend cục bộ có kho món thật.*

### 5.6. Dữ liệu: kho món và dinh dưỡng

- **Kho món**: 180 công thức (`data/kb/recipes/<slot>/*.yaml`; 75 mặn, 55 rau, 50 canh theo
  `data/processed/kb/recipe_nutrition.csv`), gam lúc mua, bước chủ động/thụ động/chiếm bếp, mỗi món ghi ≥ 2 nguồn và
  viết lại bằng lời của nhóm. Lệnh nhập catalog xuất bản món khi có ≥ 2 nguồn và mọi nguyên liệu chính có dữ liệu
  thành phần: **171 món xuất bản, 9 món nháp** (5 món một nguồn, 4 món thiếu thành phần nguyên liệu chính;
  backend/README.md). 223 nguyên liệu: 181 theo Bảng thành phần thực phẩm Việt Nam 2007, 30 theo USDA FoodData
  Central, 12 chưa có nguồn (gia vị có lý do ghi trong `ingredients.yaml`).
- **Kiểm tra khi nhập**: nhập là đồng bộ toàn bộ, chạy trong một giao dịch; sau khi ghi, lệnh kiểm lại bộ lọc dị ứng
  bằng SQL thô trên mọi món xuất bản × mọi nhóm dị ứng và chế độ ăn, có vi phạm thì huỷ toàn bộ. Sửa nội dung một món
  đã xuất bản tạo phiên bản mới và chuyển bản cũ sang `retired` (BR-CATALOG-01). Nhập lại bộ dữ liệu không đổi báo
  `"changes": 0`.
- **Dinh dưỡng** (BR-NUT-05, [`docs/research/kiem-dinh-calo.md`](../../research/kiem-dinh-calo.md)): phương pháp
  nguyên liệu EuroFIR, n_k = Σ_i w_i · EP_i/100 · n_ik · RF_ik chia cho số khẩu phần; RF = 1 cho năng lượng và chất
  sinh năng lượng; món chiên ngập dầu chỉ tính dầu thấm 5 g / 100 g nguyên liệu (Bognár 2002). Mỗi dòng kết quả ghi
  `data_version` (`nut-r1+kb1:b591fa77+fct2007:6dbf6d58+usda:1c93c3cb`), đổi khi một tệp nguồn đổi.
- **E_bát** (150 g cơm, BR-TRAY-03): 173,2 kcal, từ FCT 1004 gạo tẻ, hệ số nở 2,98 (Bognár 2002)
  (`data/processed/kb/rice_bowl.json`).
- **Kiểm định với Viện Dinh dưỡng** (BR-NUT-06): 45 món tra tay ở công cụ của Viện (`data/kb/validation/nin_dishes.yaml`).
  Trung vị |sai số tương đối| 4,7%; **phân vị 80 là 21,4%** (khoảng tin cậy bootstrap 95%: 8,8–33,5%); 31/45 món
  lệch ≤ 10%. App hiện calo dạng khoảng ±21,35% (h = 0,2135 lưu làm tham số CSDL `tastoria.kcal_half_width`, chỉ đặt
  khi ≥ 30 món được so với cùng `data_version`; không đủ thì app hiện "đang hiệu chỉnh").
- 11 món bị cờ ở `data/processed/kb/recipe_nutrition_flags.csv` (kcal ngoài khoảng hợp lý theo slot hoặc > 50% gam
  không có dữ liệu thành phần).

---

## 6. Kiểm thử

### 6.1. Chiến lược

Kế hoạch ở [`docs/sad/06-ke-hoach-kiem-thu.md`](../../sad/06-ke-hoach-kiem-thu.md): 271 ca kiểm thử trong 26 nhóm, phủ
446/446 FR, 39/39 BR, 10/10 mã NFR (31/31 điều khoản), 34/34 UC. Các tầng: đơn vị, tính chất (Hypothesis), tích hợp
API với PostgreSQL và Valkey thật, hợp đồng, bảo mật, vận hành, mô hình, E2E, tải, chấp nhận người dùng.

Kiểm thử tích hợp chạy trên container thật (`pgvector/pgvector:pg18`, `valkey/valkey:9`) do bộ kiểm thử tự dựng với
cổng ngẫu nhiên (`docker run -p 127.0.0.1::<port>`), gắn nhãn `tastoria-test=1` và xoá khi kết thúc. Ca cần kho món
thật chạy trên CSDL thứ hai đã nhập `data/kb`.

### 6.2. Số kiểm thử hiện tại (chạy ngày 18/10/2026)

| Phần | Lệnh | Kết quả | Thời gian |
|---|---|---|---|
| Backend | `TASTORIA_REQUIRE_DOCKER=1 uv run --package tastoria-backend pytest backend/tests -q` | **346 passed**, 0 failed, 0 skipped | 229 s |
| Học máy, dữ liệu | `CUDA_VISIBLE_DEVICES= uv run --package tastoria-ml pytest ml/tests -q` | **252 passed, 1 skipped** (`test_preprocess.py:120` cần `cv2`, không có trong môi trường dự án) | 57 s |
| App | `cd app && npx tsc --noEmit` | 0 lỗi kiểu | — |

`TASTORIA_REQUIRE_DOCKER=1` biến việc thiếu Docker thành lỗi thay vì bỏ qua, nên 346 ca trên gồm cả ca tích hợp. Sau
lần chạy không còn container `tastoria-test=1` nào. Ghi chú: lúc chạy, cây làm việc có thay đổi chưa commit của việc
khác ở `ml/src/tastoria_ml/cv/counting.py`; số của phần học máy tính cả thay đổi đó.

Độ phủ backend (pytest-cov `--cov-branch`, cùng ngày; đo trên toàn bộ bộ kiểm thử):

| Phạm vi | Dòng | Nhánh |
|---|---:|---:|
| `meal` | 1.098/1.147 = 95,7% | 271/318 = 85,2% |
| `pantry` | 541/556 = 97,3% | 146/160 = 91,2% |
| `profile` | 525/539 = 97,4% | 82/94 = 87,2% |
| `cooking` | 241/246 = 98,0% | 31/36 = 86,1% |
| `scan` | 975/1.061 = 91,9% | 181/228 = 79,4% |
| `catalog` | 1.483/1.588 = 93,4% | 350/424 = 82,5% |
| `identity` | 461/522 = 88,3% | 57/74 = 77,0% |
| Toàn bộ `backend/src/tastoria` | 8.060/8.653 = 93,1% | 1.527/1.868 = 81,7% |

Lệnh: `TASTORIA_REQUIRE_DOCKER=1 uv run --package tastoria-backend --with pytest-cov pytest backend/tests -q
--cov=tastoria --cov-branch` (pytest-cov không có trong phụ thuộc của dự án nên được thêm tạm bằng `--with`; cùng 346
ca đều qua). Số theo module là tổng các tệp trong `modules/<tên>/`. Phần thấp nhất là `migrations` (27% dòng, vì
migration chạy qua Alembic trong tiến trình con) và `cli`/`jobs` (66–73% dòng).

### 6.3. Kiểm thử tính chất BR-ALG-01

`tests/integration/test_hard_filter_property.py` là ca bắt buộc của kế hoạch (TC-PROP-01):

- `test_every_recipe_times_every_allergen_group`: duyệt toàn bộ món xuất bản × mọi nhóm dị ứng, so kết quả bộ lọc của
  `meal` với một truy vấn SQL thô viết độc lập (tính cả gia vị luôn có, nguyên liệu tuỳ chọn và đồ làm sẵn).
- `test_any_user_plus_coeater_allergens_and_diet`: Hypothesis 200 ví dụ, sinh tập dị ứng ngẫu nhiên của người dùng và
  người ăn cùng cùng chế độ ăn, đòi hỏi tập món được phép trùng khớp với SQL thô.

Cùng loại: `test_composer_property.py` (60 ví dụ) kiểm mọi mâm trả về cho kho, lô ghim, số người và thời gian ngẫu
nhiên đều vừa kho gộp, thoả ghim, makespan và cấu trúc mâm; `test_cooking.py` kiểm lịch CP-SAT (mục 5.4). Lệnh nhập
catalog cũng chạy lại kiểm tra BR-ALG-01 mỗi lần nhập (mục 5.6).

### 6.4. BOLA, lũy đẳng, Unit of Work

- **BOLA** (NFR-SEC-01.c): các ca tích hợp ở `test_meal.py`, `test_pantry.py`, `test_scan.py`, `test_account_deletion.py`
  dùng hai tài khoản; truy cập tài nguyên của người kia qua `{id}` phải trả 404.
- **Lũy đẳng** (`test_idempotency_and_uow.py`): gửi lại trả nguyên văn phản hồi đã lưu; cùng khoá khác thân bị từ chối;
  khoá có phạm vi theo người dùng; thiếu hoặc sai định dạng khoá; lần thử lỗi không lưu gì; bản sao đồng thời được bảo
  thử lại (409 + `Retry-After`).
- **Unit of Work**: commit, rollback, hook sau commit; commit lỗi không được báo là thành công.
- Nấu xong gửi lại (cùng khoá hoặc khoá mới) chỉ trừ kho một lần; xác nhận quét gửi lại trả cùng kết quả, không tạo
  lô mới.
- Kiến trúc: import-linter xanh; migration 0001 cho cùng `pg_dump --schema-only` như áp thẳng `db/schema.sql`; mọi
  bảng ORM khớp catalog sau migrate; `ProblemCode` khớp enum của hợp đồng theo thứ tự; văn bản điều khoản khớp SHA-256
  đóng băng trong migration 0002.

### 6.5. E2E bằng Playwright

- `app/scripts/e2e_flow.py` (Python Playwright, web 390 × 844) chạy luồng: đăng ký → đồng ý + hồ sơ → nhập tay 10 lô
  → ra mâm → đổi món → xem công thức → nấu cả mâm → nấu xong → hoàn tác → nấu lại → nhật ký; chụp mỗi màn ở chế độ
  sáng và tối vào `app/docs/screenshots/` (33 màn × 2 chế độ = 66 ảnh).
- `deploy/scripts/smoke.py`: sau mỗi lần triển khai, mở trình duyệt vào bản đang chạy: đăng ký → đồng ý + hồ sơ →
  nhập 10 lô → ghép mâm, chụp `deploy/smoke.png`. Mỗi lần chạy tạo một tài khoản thử `smoke+<giờ>@example.com`.
- Chưa có E2E Android (Maestro) và chưa có E2E cho luồng quét có ảnh; luồng quét đầu–cuối được kiểm bằng script
  `backend/scripts/scan_e2e.py` gọi API (mục 6.6).

### 6.6. Độ trễ quét đo thật

Đo ngày 18/10/2026 qua địa chỉ công khai `https://safework.ctslab.net/api/v1` (Cloudflare Tunnel → nginx → api →
Valkey → worker), mỗi lần quét một ảnh thật lấy ngẫu nhiên từ tập test công khai, bằng `backend/scripts/scan_e2e.py`.
Mốc thời gian lấy từ chính dòng `scans` trong CSDL. Nguồn: [`docs/reports/xu-ly-anh/ket-qua-so-bo.md`](../xu-ly-anh/ket-qua-so-bo.md)
§11.2, tệp `data/processed/cv/detector/scan_latency_live_c1.json`, `scan_latency_live_c5.json`.

| Điều kiện | Số lần | hàng đợi → xong p50 / p95 (ms) | tạo → xong p50 / p95 (ms) | chạy job p50 / p95 (ms) | phía client p50 / p95 (ms) |
|---|---:|---:|---:|---:|---:|
| 1 người, tuần tự | 40 | 58,9 / 98,4 | 63,9 / 104,7 | 55,8 / 91,0 | 286,8 / 352,5 |
| 5 người đồng thời | 300 | 65,5 / 170,3 | 72,3 / 178,3 | 53,5 / 66,7 | 312,7 / 413,6 |

Giới hạn của phép đo: máy chủ lab dùng chung (Intel Xeon Gold 6542Y, 32 luồng) với worker giới hạn 2 CPU / 4 GB bằng
Docker, chưa phải VPS 2 vCPU; ảnh test rộng 640–1.024 px (trung bình 717 px), nhỏ hơn ảnh 1.280 px app gửi; ảnh không
phải ảnh tủ lạnh; "phía client" đo từ chính máy chủ, không phải từ điện thoại.

Thời gian chạy mô hình riêng (onnxruntime 1.31.0, 2 luồng, 100 ảnh val, `yolo26n_640_none_latency.json`): p50 23,0 ms,
p95 23,8 ms cho mô hình 640 × 640; 26,5 / 32,0 ms khi tính cả letterbox.

---

## 7. Triển khai và vận hành

### 7.1. Docker Compose

[`deploy/README.md`](../../../deploy/README.md), `deploy/docker-compose.yml` (project `tastoria`). Toàn bộ stack chỉ mở
một cổng `127.0.0.1:6880` (nginx).

| Dịch vụ | Image | Việc |
|---|---|---|
| `nginx` | `tastoria-web:<tag>` (nginx 1.28 + bản web Expo) | Phục vụ app web ở `/`, trang giới thiệu `/gioi-thieu/`, APK `/tai-ve/*.apk`; chuyển `/api/`, `/healthz`, `/readyz` sang api; location `internal` `/_protected/` cho `X-Accel-Redirect` |
| `api` | `tastoria-backend:<tag>` | uvicorn 2 tiến trình, healthcheck `/readyz` |
| `migrate` | `tastoria-backend:<tag>` | Chạy một lần: `db upgrade`, nhập catalog, nhập bảng tra thay thế, đăng ký + gate mô hình đã dàn, `deploy --if-none`; api, worker, scheduler chỉ khởi động khi bước này thoát 0 |
| `worker` | `tastoria-backend:<tag>` | RQ SimpleWorker hàng đợi `scan`; `cpus: 2`, `mem_limit: 4g` |
| `scheduler` | `tastoria-backend:<tag>` | Mỗi phút `jobs sweep`, mỗi 10 phút `jobs process-dsr`, mỗi giờ `jobs purge-images` |
| `postgres` | `pgvector/pgvector:pg18` | CSDL |
| `valkey` | `valkey/valkey:9` | Bộ đếm đăng nhập sai, hàng đợi RQ, kênh long-poll |

`deploy.sh` dựng image với tag = 12 ký tự đầu của commit (thêm `-dirty-<giờ>` nếu cây làm việc còn thay đổi), sao
lưu CSDL đang chạy trước khi migrate (nhãn `pre-<tag>`), chạy `docker compose up -d`, chờ các dịch vụ healthy, gọi
`/healthz`, `/readyz`, ghi một dòng vào `deploy/releases.log`. Image backend chạy bằng người dùng không phải root (uid
10001). Biến `TASTORIA_ENV=production` đặt cứng; backend từ chối khởi động nếu còn khoá mặc định của môi trường dev.
Bí mật sinh bằng `scripts/init-env.sh` vào `deploy/.env` (quyền 600, không commit).

### 7.2. Cloudflare Tunnel

Máy chủ không mở cổng ra Internet; cloudflared có sẵn trên máy chuyển `safework.ctslab.net` tới `127.0.0.1:6880`.
Cloudflare kết thúc TLS; nginx lấy IP thật từ `CF-Connecting-IP` (chỉ tin khi request đến từ loopback hoặc mạng
Docker) để khoá đăng nhập theo (email, IP) đếm đúng từng người. App web và API cùng origin (app gọi `/api/v1`) nên
không cần CORS. Bộ đệm: tệp có hash trong tên `max-age=31536000, immutable`; `index.html` `no-cache`; `/api/*`
`no-store`; sau khi triển khai không cần xoá cache Cloudflare. Thiết kế v2 đề xuất tên `tastoria.ctslab.net`; bản chạy
thật dùng `safework.ctslab.net`.

Kiểm tra lúc viết báo cáo (18/10/2026, `curl` từ máy chủ qua Cloudflare):

| Đường dẫn | Mã | Ghi chú |
|---|---|---|
| `/healthz` | 200 | `{"status":"ok"}` |
| `/readyz` | 200 | `{"status":"ready","checks":{"database":"ok","valkey":"ok","models":"ok"}}` |
| `/gioi-thieu/` | 200 | trang tĩnh 11.391 byte |
| `/tai-ve/tastoria-0.1.1.apk` | 200 | 51.408.936 byte, `application/vnd.android.package-archive`; sha256 tệp gốc `f30664d6…853c665` |
| `/khao-sat` | 200 | app web, màn khảo sát |
| `/api/v1/reference` | 200 | dữ liệu tham chiếu công khai |

| Trang giới thiệu | Khảo sát gu |
|---|---|
| ![](fig/live-gioi-thieu-390.png) | ![](fig/live-khao-sat-390.png) |

*Hình 13. Bản chạy thật, chụp ngày 18/10/2026 ở 390 px (Playwright, không đăng nhập, không gửi biểu mẫu).*

Trang giới thiệu là HTML/CSS tĩnh không JavaScript, font Be Vietnam Pro WOFF2 cắt theo tập ký tự tiếng Việt, số liệu
trên trang là số đo thật kèm giới hạn (commit `d5f1986`).

### 7.3. Sao lưu và khôi phục

- `deploy/scripts/backup.sh`: mỗi bản là `tastoria_<giờ UTC>_<nhãn>.tar.gpg` (gpg AES-256) gồm `pg_dump -Fc`, nén tar
  volume tệp và `MANIFEST` (tag image, revision alembic, số món xuất bản, số người dùng); giữ 14 ngày ở máy và trên
  Google Drive qua rclone (BR-RETAIN-01).
- Lịch: crontab của máy chủ có dòng `15 20 * * *` (03:15 giờ Việt Nam) gọi `backup.sh` (kiểm bằng `crontab -l` lúc
  viết; README triển khai còn ghi "chưa đặt lịch", đã lỗi thời). Thư mục `~/backups/tastoria` có 5 bản ngày 18/10
  (một bản `daily`, một bản `pre-restore`, ba bản `pre-<tag>` do `deploy.sh` tạo).
- `deploy/scripts/restore.sh --verify <tệp>`: diễn tập, khôi phục vào container PostgreSQL tạm, in số món, số người
  dùng, revision, không đụng stack đang chạy. Không có `--verify`: hỏi xác nhận, tự sao lưu trạng thái hiện tại (nhãn
  `pre-restore`), dừng dịch vụ, `pg_restore`, chép lại volume tệp, chạy lại migrate.
- Khôi phục đã được chạy thử khi dựng stack (commit `7f84a5e`; bản `pre-restore` lúc 00:11:50Z là bản `restore.sh` tự
  tạo trước khi khôi phục). Chưa có biên bản bấm giờ trên máy trắng như NFR-REL-01 yêu cầu.
- Quay lui: `rollback.sh <tag-cũ>` đổi image; nếu bản mới đã chạy migration mới thì phải khôi phục bản `pre-<tag>`
  trước. Quay lui mô hình: `tastoria mlops rollback detector` rồi khởi động lại api và worker.
- Khoá mã hoá cột sức khoẻ và mật khẩu sao lưu nằm trong `.env`, không có trong bản sao lưu; README yêu cầu cất `.env`
  ở nơi khác (mất khoá là mất chỉ số cơ thể của mọi người dùng, ADR 0005).

### 7.4. APK ký riêng

APK dựng tại máy bằng `npx expo prebuild` + `./gradlew assembleRelease`, ký bằng khoá upload riêng nằm ngoài repo;
`EXPO_PUBLIC_API_URL=https://safework.ctslab.net/api/v1` được nhúng lúc dựng. Bản 0.1.1 (versionCode 2) phát ở
`/tai-ve/tastoria-0.1.1.apk`; nginx chỉ phục vụ tệp `.apk` trong `dist/` (các tệp khác như bộ nhập Visual Paradigm trả
404). Bản Android chưa có trên cửa hàng ứng dụng; người dùng phải cho phép cài từ nguồn ngoài.

---

## 8. Đánh giá

### 8.1. Đáp ứng NFR: ngưỡng và số đo

| NFR | Ngưỡng (SRS 1.1) | Đo được | Đánh giá |
|---|---|---|---|
| NFR-PERF-01 | Quét ở server (`enqueued_at` → `finished_at`) p95 ≤ 3 s; 2 vCPU / 4 GB, 5 người đồng thời, ≥ 300 mẫu, ảnh 1.280 px | p95 170,3 ms, 300 mẫu, 5 người đồng thời, worker 2 CPU / 4 GB (mục 6.6) | Đạt trong điều kiện đã đo; điều kiện khác SRS ở ảnh (640–1.024 px, ảnh công khai) và máy (Xeon dùng chung) |
| NFR-PERF-02 | `POST /meal-plans` p95 ≤ 1 s; kho 200 món, 30 lô, 10 người đồng thời, ≥ 300 yêu cầu | Kiểm thử khói `test_meal_perf.py`: 171 món, 30+ lô, 1 người, 8 lần, TestClient trong tiến trình: trung vị 0,091 s, lớn nhất 0,252 s (chạy 18/10/2026) | Chưa đo theo điều kiện SRS (chưa có kiểm thử tải 10 người) |
| NFR-PERF-03 | Quét đầu–cuối trên điện thoại p95 ≤ 8 s (Wi-Fi), ≤ 12 s (4G) | Phía client từ máy chủ: p95 413,6 ms (5 người); chưa đo trên điện thoại | Chưa đo |
| NFR-REL-01 | RPO ≤ 24 h, RTO ≤ 2 h, diễn tập ≥ 1 lần | Sao lưu hằng ngày (RPO ≤ 24 h theo lịch); khôi phục đã chạy thử; chưa bấm giờ RTO | Một phần |
| NFR-REL-01.d | Không lần quét nào kẹt quá 6 phút | Sweeper mỗi phút + kiểm thử tích hợp tiêm lỗi | Đạt (kiểm thử) |
| NFR-SEC-01 | Access 15 phút; refresh 30 ngày xoay vòng; dùng lại → thu hồi family | Cấu hình mặc định `ACCESS_TOKEN_TTL_S=900`, `REFRESH_TOKEN_TTL_DAYS=30`; kiểm thử tích hợp `test_identity.py` | Đạt (kiểm thử) |
| NFR-SEC-01.c | 100% endpoint có `{id}` trả 404 khi không thuộc người gọi | Kiểm thử hai tài khoản ở các module có `{id}` | Đạt ở các ca đã viết; chưa có bộ sinh tự động từ danh sách endpoint như SRS mô tả |
| NFR-SEC-02 | Khoá 15 phút sau 5 lần sai theo (email, IP) | Kiểm thử tích hợp với đồng hồ giả | Đạt (kiểm thử) |
| NFR-SEC-02.b | Ảnh tải lên an toàn | `test_scan_images.py`: magic bytes, bom giải nén, EXIF/GPS bị bỏ | Đạt (kiểm thử) |
| NFR-SEC-02.c | Chỉ HTTPS từ Internet, chỉ nginx mở cổng ở 127.0.0.1 | `docker-compose.yml` chỉ có `127.0.0.1:6880`; ra ngoài qua Cloudflare | Đạt theo cấu hình; chưa quét cổng từ máy ngoài |
| NFR-PRIV-01 | Yêu cầu chủ thể dữ liệu tự động ≤ 24 h | Job `process-dsr` mỗi 10 phút; kiểm thử tích hợp tải về, xoá tài khoản, rút đồng ý | Đạt (kiểm thử, theo thiết kế) |
| NFR-A11Y-01 | WCAG 2.2 AA, vùng chạm ≥ 44 × 44 dp | Vùng chạm 48 dp trong theme; nhãn độ tươi có chữ; tương phản ghi trong `tokens.ts` | Chưa kiểm bằng axe và TalkBack |
| NFR-USE-01 | SUS ≥ 68; ≥ 80% người thử hoàn thành mỗi nhiệm vụ (8–10 người) | — | **Chưa đo**, cần người thật (mục 8.3) |
| NFR-MAINT-01 | Độ phủ dòng và nhánh ≥ 80% từng module `meal`, `pantry`, `profile`, `cooking`; import-linter xanh | `meal` 95,7% / 85,2%, `pantry` 97,3% / 91,2%, `profile` 97,4% / 87,2%, `cooking` 98,0% / 86,1% (dòng / nhánh, mục 6.2); import-linter xanh | Đạt (đo một lần, chưa có CI chạy tự động) |
| NFR-MAINT-01.e | OpenAPI hợp lệ, đủ 70 endpoint | `openapi-spec-validator` + so operation trong bộ kiểm thử | Đạt (kiểm thử) |

### 8.2. Đánh giá chức năng

Luồng chính quét → xác nhận → kho → mâm → đổi món → thiếu gì → nấu cả mâm → nấu xong → hoàn tác → nhật ký chạy được
đầu–cuối trên web (E2E mục 6.5) và trên bản triển khai thật (smoke test sau mỗi lần triển khai; một lần quét `haul` thật
qua Cloudflare cho chip "tôm" từ 8 khung, xác nhận tạo lô 250–500 g, xác nhận lần hai trả cùng kết quả,
ket-qua-so-bo.md §11.2). Chất lượng của các thành phần thông minh không được đánh giá trong báo cáo này:

- Bộ phát hiện: mAP50 0,424 / mAP50-95 0,278 trên tập test **công khai** (Open Images + rau Bangladesh, 13 trong 22 lớp
  có dữ liệu); chưa có ảnh tủ lạnh của nhóm nên chưa biết chất lượng trên tủ lạnh Việt Nam (báo cáo Xử lý ảnh).
- Xếp hạng gu và trọng số ghép mâm: mới đo trên Food.com và kịch bản tổng hợp (báo cáo Học máy); bản phục vụ dùng bộ
  xếp hạng baseline và trọng số tạm.
- Calo: sai số so với Viện Dinh dưỡng đã đo (mục 5.6) và được hiển thị dưới dạng khoảng.

### 8.3. Những gì chưa đo

1. **Khả dụng (NFR-USE-01)**: cần 8–10 người thật không thuộc nhóm, mỗi người một phiên 30–40 phút có người điều phối
   đọc kịch bản cố định (kế hoạch kiểm thử §3, TC-UAT-01..03). Chưa có người thử nào; báo cáo không đưa ra điểm SUS.
   Phiếu SUS tiếng Việt và kịch bản phiên thử ở Phụ lục C, D để dùng khi có người.
2. **Quét trên điện thoại (NFR-PERF-03)**: cần điện thoại Android tầm trung thật, ≥ 30 lần mỗi loại mạng, mốc thời
   gian phía app.
3. **Tải theo điều kiện SRS (NFR-PERF-02, 02.b, 02.c)**: chưa có kịch bản Locust/k6.
4. **RTO**: diễn tập khôi phục trên máy trắng có bấm giờ.
5. **Truy cập (NFR-A11Y-01)**: axe trên web, TalkBack trên Android.

---

## 9. Hạn chế và hướng phát triển

**Hạn chế**

- Chưa có dữ liệu người thật: ảnh tủ lạnh, lô rau cho độ tươi, người khảo sát gu, đáp án thay thế, người thử app. Mọi
  số về chất lượng mô hình là trên dữ liệu công khai hoặc mô phỏng; hệ thống đã có công cụ thu (trang khảo sát
  `/khao-sat`, chế độ góp ảnh có đồng ý) nhưng chưa thu.
- Không có mô hình độ tươi nào đang chạy; độ gấp của lô chỉ dựa vào số ngày từ lúc mua và thời hạn bảo quản.
- 9/22 lớp thị giác chưa có dữ liệu huấn luyện, trong đó có thịt lợn (47 món), đậu phụ (16) và thịt bò (10), những
  nguyên liệu chính của kho món. Người dùng phải thêm tay qua chip.
- Thư đặt lại mật khẩu chưa gửi được: chưa có tài khoản SMTP, bản chạy thật đặt `TASTORIA_MAILER=log`.
- Hồ sơ đánh giá tác động là bản nháp chưa rà soát pháp lý; căn cứ xử lý cho dịch vụ cốt lõi chưa xác định; các luồng
  dữ liệu ra nước ngoài (Gemini, Google Drive, Cloudflare, SMTP) cần quyết định; chưa có thoả thuận với bên xử lý.
- YOLO26n theo AGPL-3.0: khi mở cho người ngoài phải công bố mã nguồn phần dịch vụ (ADR 0011), hoặc đổi sang mô hình
  Apache-2.0.
- Máy chủ lab dùng chung, không có cam kết sẵn sàng (SRS GD-06).
- Một số tài liệu chưa cập nhật theo mã: `app/README.md` còn ghi endpoint quét và khảo sát "chưa có trong backend";
  mục "Next steps" của `backend/README.md` còn ghi chưa có lệnh nhập bảng tra thay thế; `deploy/README.md` còn ghi
  sao lưu chưa đặt lịch.

**Hướng phát triển**

1. Thu dữ liệu thật theo thiết kế v2 §5: ≥ 12–15 hộ chụp tủ lạnh, 80–100 người khảo sát, rồi đo lại bộ phát hiện và so
   với Gemini trên cùng tập test.
2. Chạy phiên thử người dùng theo Phụ lục C, D; đo NFR-PERF-03 trên điện thoại trong cùng phiên.
3. Huấn luyện bộ phân loại độ tươi 4 mức có hiệu chỉnh nhiệt độ, xuất ONNX và chạy trên khung cắt trong worker.
4. Phục vụ mô hình xếp hạng đã huấn luyện qua `Ranker` protocol và `mlops`, ghi `ranker_version_id`; chốt α, β, γ bằng
   quy tắc công bố trước.
5. Viết kịch bản tải Locust/k6 cho NFR-PERF-02; E2E Android bằng Maestro.
6. Cấu hình SMTP; rà soát pháp lý hồ sơ đánh giá tác động trước khi mở cho người ngoài nhóm.

---

## 10. Tài liệu tham khảo

1. ISO/IEC/IEEE 29148:2018. *Systems and software engineering — Life cycle processes — Requirements engineering*.
2. ISO/IEC 25010:2023. *Systems and software engineering — Product quality model*.
3. A. Cockburn (2001). *Writing Effective Use Cases*. Addison-Wesley.
4. Object Management Group. *Unified Modeling Language 2.5.1* (2017).
5. M. Nottingham, E. Wilde, S. Dalal. RFC 9457, *Problem Details for HTTP APIs* (2023).
6. OpenAPI Initiative. *OpenAPI Specification 3.1.0* (2021).
7. IETF. RFC 9700, *Best Current Practice for OAuth 2.0 Security* (2025) (xoay vòng refresh token).
8. Quốc hội. Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15.
9. Chính phủ. Nghị định 356/2025/NĐ-CP quy định chi tiết Luật Bảo vệ dữ liệu cá nhân.
10. W3C. *Web Content Accessibility Guidelines (WCAG) 2.2* (2023).
11. J. Brooke (1996). SUS: a "quick and dirty" usability scale. In *Usability Evaluation in Industry*, 189–194.
12. A. Bangor, P. Kortum, J. Miller (2008). An empirical evaluation of the System Usability Scale. *International
    Journal of Human–Computer Interaction* 24(6), 574–594.
13. Google OR-Tools, CP-SAT solver (phiên bản cài: 9.15.6755). https://developers.google.com/optimization
14. Ultralytics YOLO, `ultralytics==8.4.173` (YOLO26n). AGPL-3.0.
15. ONNX Runtime 1.31.0.
16. Viện Dinh dưỡng (2007). *Bảng thành phần thực phẩm Việt Nam*. NXB Y học.
17. U.S. Department of Agriculture. FoodData Central (Foundation, SR Legacy), CC0.
18. EuroFIR. Phương pháp tính dinh dưỡng món theo nguyên liệu (recipe calculation, ingredient method).
19. Á. Bognár (2002). *Tables on weight yield of food and retention factors of food constituents for the calculation of
    nutrient composition of cooked foods (dishes)*. BFE-R--02-03, Karlsruhe.
20. Codex Alimentarius. CXS 1-1985, *General Standard for the Labelling of Prepackaged Foods* (sửa đổi 2024).
21. Tài liệu nội bộ: thiết kế v2, SRS, báo cáo phân tích thiết kế, ADR 0001–0013, khảo sát đối thủ (danh sách ở Phụ lục A).

---

## 11. Phụ lục

### A. Danh mục tệp

| Tệp / thư mục | Nội dung |
|---|---|
| [`docs/superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md`](../../superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md) | Thiết kế v2 (BR, NFR, kiến trúc) |
| [`docs/sad/BaoCao_PhanTichThietKe.md`](../../sad/BaoCao_PhanTichThietKe.md) | Báo cáo phân tích thiết kế |
| [`docs/sad/01-SRS.md`](../../sad/01-SRS.md), [`use-cases/`](../../sad/use-cases/) | SRS, đặc tả 34 UC |
| [`docs/sad/04-chuan-hoa.md`](../../sad/04-chuan-hoa.md), [`05-tu-dien-du-lieu.md`](../../sad/05-tu-dien-du-lieu.md) | Chuẩn hoá, từ điển dữ liệu |
| [`docs/sad/06-ke-hoach-kiem-thu.md`](../../sad/06-ke-hoach-kiem-thu.md) | Kế hoạch kiểm thử (271 ca) |
| [`docs/sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md`](../../sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md) | Đánh giá tác động xử lý dữ liệu cá nhân |
| [`docs/sad/08-ma-tran-truy-vet.md`](../../sad/08-ma-tran-truy-vet.md) | Ma trận truy vết |
| [`docs/adr/`](../../adr/) | ADR 0001–0013 |
| [`docs/api/openapi-v1.yaml`](../../api/openapi-v1.yaml) | Hợp đồng API |
| [`db/schema.sql`](../../../db/schema.sql), `db/schema_vp.sql` | DDL, bản cho Visual Paradigm |
| `docs/uml/`, `docs/erd/`, `docs/uml/out/` | Nguồn PlantUML và ảnh |
| [`docs/vp-import-kit/`](../../vp-import-kit/) | Hướng dẫn và công cụ dựng `.vpp` |
| [`docs/research/raw/04-doi-thu-va-bang-chung.md`](../../research/raw/04-doi-thu-va-bang-chung.md) | Khảo sát đối thủ, bằng chứng người dùng |
| [`docs/research/kiem-dinh-calo.md`](../../research/kiem-dinh-calo.md) | Dinh dưỡng món, kiểm định calo |
| [`docs/reports/xu-ly-anh/ket-qua-so-bo.md`](../xu-ly-anh/ket-qua-so-bo.md) | Kết quả xử lý ảnh, độ trễ quét thật |
| [`docs/reports/hoc-may/bao-cao-hoc-may.md`](../hoc-may/bao-cao-hoc-may.md) | Báo cáo Học máy |
| `backend/`, [`backend/README.md`](../../../backend/README.md) | Backend, quyết định từng lát cắt |
| `app/`, [`app/README.md`](../../../app/README.md), `app/docs/screenshots/` | App, ảnh màn hình |
| `deploy/`, [`deploy/README.md`](../../../deploy/README.md) | Triển khai, sao lưu, khôi phục |
| `landing/` | Trang giới thiệu tĩnh |
| `data/kb/`, `data/processed/kb/` | Kho món, nguyên liệu, kết quả dinh dưỡng |
| `docs/reports/ptud/fig/` | Ảnh của báo cáo này: `vp-*.png` (Visual Paradigm), `live-*.png` (bản chạy thật) |

### B. Hướng dẫn chạy

Kiểm thử (từ thư mục gốc repo, cần Python 3.12, `uv`, Docker, Node 22):

```bash
TASTORIA_REQUIRE_DOCKER=1 uv run --package tastoria-backend pytest backend/tests -q
CUDA_VISIBLE_DEVICES= uv run --package tastoria-ml pytest ml/tests -q
(cd app && npm install && npx tsc --noEmit)
# dọn container nếu bộ kiểm thử bị ngắt giữa chừng
docker rm -f $(docker ps -aq --filter label=tastoria-test=1)
```

Chạy cục bộ (backend/README.md, app/README.md):

```bash
export TASTORIA_DATABASE_URL=postgresql+psycopg://tastoria:tastoria@127.0.0.1:5432/tastoria
export TASTORIA_VALKEY_URL=redis://127.0.0.1:6379/0
uv run --package tastoria-backend tastoria db upgrade
uv run --package tastoria-backend tastoria catalog import data/kb
uv run --package tastoria-backend uvicorn tastoria.app:create_app --factory --host 127.0.0.1 --port 8000
cd app && npm run gen:api && npm run export:web
API_TARGET=http://127.0.0.1:8000 PORT=8080 npm run serve:web
```

Triển khai (deploy/README.md):

```bash
cd deploy && ./scripts/deploy.sh          # dựng image theo commit, sao lưu, migrate, khởi động, kiểm sức khoẻ
curl -s 127.0.0.1:6880/readyz
./scripts/backup.sh                       # sao lưu thủ công
./scripts/restore.sh --verify <tệp>       # diễn tập khôi phục
./scripts/rollback.sh <tag-cũ>
```

### C. Phiếu SUS tiếng Việt (TC-UAT-01)

Dùng sau khi người thử làm xong 5 nhiệm vụ ở Phụ lục D. Mỗi câu chọn một mức: 1 = Hoàn toàn không đồng ý, 2, 3, 4,
5 = Hoàn toàn đồng ý. Bản dịch từ thang gốc của Brooke (1996); "hệ thống" được thay bằng "ứng dụng Tastoria".

| # | Câu hỏi | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 1 | Tôi nghĩ tôi sẽ muốn dùng ứng dụng này thường xuyên. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 2 | Tôi thấy ứng dụng phức tạp không cần thiết. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 3 | Tôi thấy ứng dụng dễ dùng. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 4 | Tôi nghĩ tôi sẽ cần người có chuyên môn kỹ thuật hỗ trợ mới dùng được ứng dụng này. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 5 | Tôi thấy các chức năng của ứng dụng gắn kết tốt với nhau. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 6 | Tôi thấy ứng dụng có quá nhiều chỗ không nhất quán. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 7 | Tôi nghĩ phần lớn mọi người sẽ học dùng ứng dụng này rất nhanh. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 8 | Tôi thấy ứng dụng rất rườm rà, khó thao tác. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 9 | Tôi thấy tự tin khi dùng ứng dụng. | ☐ | ☐ | ☐ | ☐ | ☐ |
| 10 | Tôi đã phải học nhiều thứ trước khi dùng được ứng dụng này. | ☐ | ☐ | ☐ | ☐ | ☐ |

Cách tính (Brooke 1996): câu lẻ lấy (điểm − 1), câu chẵn lấy (5 − điểm); cộng 10 câu rồi nhân 2,5, được thang 0–100.
Báo cáo: trung bình, độ lệch chuẩn, khoảng tin cậy 95% (t, n − 1 bậc tự do), số người. Ngưỡng NFR-USE-01: trung bình
≥ 68. Với 8–10 người, khoảng tin cậy sẽ rộng; ghi kèm để người đọc thấy độ chắc của con số.

Thông tin ghi thêm cho mỗi người thử (không ghi họ tên, chỉ mã P01, P02, …): nhóm tuổi; số lần nấu cơm mỗi tuần; có
dùng điện thoại Android không; đã dùng app nấu ăn nào chưa.

### D. Kịch bản phiên kiểm thử người dùng (TC-UAT-02, TC-UAT-03)

**Chuẩn bị**

- 8–10 người không thuộc nhóm, đã đồng ý tham gia bằng văn bản (mục đích, dữ liệu ghi, thời gian lưu). Không quay mặt;
  chỉ ghi màn hình nếu người thử đồng ý riêng.
- Điện thoại Android tầm trung có cài APK 0.1.1, Wi-Fi; một tủ lạnh thật hoặc một túi đồ chợ gồm ít nhất 5 loại thuộc
  13 lớp có dữ liệu (ví dụ trứng, cà chua, cà rốt, khoai tây, bắp cải) và một loại thịt (lớp chưa có dữ liệu, để quan
  sát việc thêm tay).
- Tài khoản do người thử tự tạo trên máy thử; xoá tài khoản (UC07) sau phiên.
- Người điều phối đọc nguyên văn lời dẫn, không gợi ý thao tác. Người thử nói to suy nghĩ khi làm.
- Ghi cho mỗi nhiệm vụ: hoàn thành không trợ giúp (có/không), thời gian (bấm từ lúc đọc xong lời dẫn), số lỗi (thao tác
  sai phải quay lại), trích lời nguyên văn. Mốc thời gian phía app dùng cho TC-UAT-03 và NFR-PERF-03.

**Lời dẫn chung**: "Chúng tôi đang thử ứng dụng, không thử anh/chị. Không có câu trả lời sai. Anh/chị cứ làm như ở nhà;
nếu bí quá thì nói 'tôi dừng', chúng ta chuyển sang việc sau."

| # | Nhiệm vụ (đọc cho người thử) | Hoàn thành khi | Liên quan |
|---|---|---|---|
| 1 | "Anh/chị vừa cài ứng dụng. Hãy tạo tài khoản và khai hồ sơ để ứng dụng biết anh/chị ăn khoảng bao nhiêu và dị ứng gì (nếu có)." | Tới Trang chủ sau màn đồng ý và 4 bước hồ sơ | UC01, UC09; TC-UAT-03 đo thời gian từ màn đồng ý tới Trang chủ (trung vị ≤ 60 s) |
| 2 | "Hãy chụp tủ lạnh (hoặc túi đồ này) để đưa đồ vào kho. Nếu ứng dụng nhận sai hoặc thiếu món nào, hãy sửa cho đúng." | Bấm "Đưa vào kho", màn Kho có các lô vừa thêm, gồm món phải thêm tay | UC12, UC13; NFR-PERF-03 (mốc chụp xong → hiện chip) |
| 3 | "Tối nay nhà anh/chị có 3 người ăn, có khoảng 45 phút để nấu. Hãy xem ứng dụng gợi ý mâm gì, và đổi một món anh/chị không muốn ăn." | Mâm mới hiện sau khi đổi, có lý do đã chọn | UC15, UC16 |
| 4 | "Hãy bắt đầu nấu mâm này theo hướng dẫn của ứng dụng." (Không cần nấu thật; người thử đi qua các bước hẹn giờ.) | Tới màn Nấu xong | UC19 |
| 5 | "Giả sử anh/chị đã nấu xong. Hãy báo cho ứng dụng và cho biết anh/chị thích món nào." | Màn tóm tắt trừ kho hiện, có nút Hoàn tác | UC20 |

Sau 5 nhiệm vụ: phiếu SUS (Phụ lục C), rồi ba câu hỏi mở: "Chỗ nào làm anh/chị lúng túng nhất?", "Anh/chị có tin con
số calo trên mâm không, vì sao?", "Anh/chị có dùng tiếp không, trong trường hợp nào?".

Tiêu chí (NFR-USE-01, TC-UAT-02): ≥ 80% người thử hoàn thành mỗi nhiệm vụ không cần trợ giúp. Tạm dừng phiên khi một
nhiệm vụ không làm được vì lỗi phần mềm; lỗi đó được ghi riêng và không tính vào tỉ lệ hoàn thành. Thiếu người thì báo
đúng số người thực có, không bổ sung bằng dữ liệu giả.
