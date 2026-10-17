# 04 — Mô hình dữ liệu và chuẩn hoá

Tài liệu này phân tích chuẩn hoá cho 62 bảng của lược đồ vật lý `db/schema.sql` (PostgreSQL 18 + pgvector), khớp với `docs/sad/model.yaml`. Với mỗi bảng: khoá ứng viên, phụ thuộc hàm (PTH) không tầm thường, kiểm 1NF, 2NF, 3NF, BCNF và kết luận. Mục 4 giải thích từng chỗ phi chuẩn hoá có kiểm soát và cơ chế trong CSDL giữ nhất quán cho nó; mục 5 trình bày phép tách từ lược đồ v1; mục 6 ghi các thay đổi mô hình còn chờ quyết.

## 1. Sơ đồ đi kèm

| Tệp | Nội dung | Ký pháp |
|---|---|---|
| `docs/erd/ERD00-khai-niem-chen.puml` | Mô hình khái niệm: 29 thực thể, quan hệ đặt tên bằng động từ | Chen |
| `docs/erd/ERD01-dinh-danh-quyen-rieng-tu.puml` | core, identity, privacy (9 bảng) | Chân quạ |
| `docs/erd/ERD02-ho-so.puml` | profile (4 bảng) và danh mục được tham chiếu | Chân quạ |
| `docs/erd/ERD03-danh-muc-thanh-phan.puml` | Thành phần thực phẩm, nguyên liệu, dị ứng, chế độ ăn, đơn vị, mức lượng, lớp thị giác (15 bảng) | Chân quạ |
| `docs/erd/ERD04-mon-an.puml` | Món, bước, thẻ, nguồn, dinh dưỡng món (8 bảng) | Chân quạ |
| `docs/erd/ERD05-kho-quet.puml` | pantry, scan (6 bảng) | Chân quạ |
| `docs/erd/ERD06-mam-nau.puml` | meal, substitute, cooking, events (11 bảng) | Chân quạ |
| `docs/erd/ERD07-khao-sat-mo-hinh.puml` | survey, mlops (9 bảng) | Chân quạ |
| `docs/erd/ERD08-tong-quan.puml` | Cả 62 bảng (chỉ tên) và 97 khoá ngoại, gom theo module | Chân quạ |

Ảnh SVG ở `docs/uml/out/erd/`.

**Quy ước ERD00 (Chen, theo Elmasri–Navathe).** Hình chữ nhật là thực thể, chữ nhật viền đôi là thực thể yếu (Hồ sơ, Bước nấu, Ảnh quét, Phân công khảo sát, Điểm khảo sát); hình thoi là quan hệ, thoi viền đôi là quan hệ định danh; elip gạch chân là thuộc tính khoá. Với thực thể yếu, `<<key>>` là khoá bộ phận (Số bước, Thứ tự ảnh); chuẩn Chen vẽ khoá bộ phận bằng gạch chân nét đứt nhưng PlantUML chỉ vẽ nét liền, nên chú giải trên sơ đồ ghi rõ điều này. Hồ sơ (1:1 với Người dùng), Phân công khảo sát (định danh bởi Người tham gia và Món) và Điểm khảo sát (1:1 với Phân công) không có khoá bộ phận: chúng định danh hoàn toàn qua thực thể chủ. Elip viền đôi là thuộc tính đa trị, elip nét đứt là thuộc tính dẫn xuất (Tổng thời gian, Lượng hiện tại, Độ gấp u), elip có nhánh con là thuộc tính phức hợp. Số 1/N/M trên cạnh là tỉ số lực lượng; cạnh nét đôi là tham gia toàn phần (mọi thể hiện của thực thể phải tham gia quan hệ), nét đơn là tham gia bộ phận. **ERD00 thể hiện ràng buộc nghiệp vụ, ERD01–07 thể hiện đúng những gì DDL ép được.** Vì vậy ở ERD00, Mâm cơm tham gia toàn phần trong "gồm món" (mâm 2–3 món, BR-TRAY-01), Lần quét trong "chụp" (1–2 ảnh), Món trong "gồm bước" và "dùng" (món nào cũng có bước và nguyên liệu, FR-25-08), dù ở chân quạ các đầu bảng con đều có cận dưới 0. Nhật ký đồng ý là thực thể Sự kiện đồng ý (một người có thể đồng ý rồi rút nhiều lần trên cùng một phiên bản điều khoản, nên không vẽ được bằng tập quan hệ M:N giữa Người dùng và Phiên bản điều khoản, vốn chỉ có một thể hiện cho mỗi cặp). Các quan hệ M:N còn lại có thuộc tính (có hàm lượng, dùng, có lớp đầu ra, xếp lịch, ánh xạ tới) đều chỉ có một giá trị cho mỗi cặp, đúng với khoá chính hai cột của bảng tương ứng. Mô hình khái niệm cố ý bỏ các bảng kỹ thuật (token, khoá lũy đẳng, nhật ký kiểm toán, triển khai mô hình, thẻ, nguồn món, danh sách đi chợ…); chúng có đầy đủ ở ERD01–07.

**Quy ước ERD01–08 (chân quạ).** ERD01–08 sinh tự động từ `db/schema.sql`. Mỗi bảng xuất hiện đầy đủ cột ở đúng một sơ đồ trong ERD01–07; bảng của nhóm khác hiện dạng rút gọn nền xám (chỉ khoá chính, ghi sơ đồ chứa chi tiết). `*` là NOT NULL; `<<PK>>`, `<<FK>>`, `<<UQ>>` đánh dấu khoá chính, khoá ngoại, cột duy nhất; ràng buộc duy nhất nhiều cột và chỉ mục duy nhất một phần (`UNIQUE(...) WHERE ...`, không phải khoá của cả bảng) ghi ở cuối thực thể. Bội số hai đầu suy trực tiếp từ DDL:

| Khoá ngoại ở bảng con | Đầu bảng cha | Đầu bảng con | Ví dụ |
|---|---|---|---|
| NOT NULL, không duy nhất | `\|\|` đúng một | `o{` không hoặc nhiều | `users \|\|--o{ scans` |
| Cho phép NULL, không duy nhất | `\|o` không hoặc một | `o{` không hoặc nhiều | `model_versions \|o--o{ scans` |
| NOT NULL và cũng là khoá chính/duy nhất | `\|\|` đúng một | `o\|` không hoặc một | `users \|\|--o\| profiles` |
| Cho phép NULL và duy nhất (NULL không so bằng nhau) | `\|o` không hoặc một | `o\|` không hoặc một | `pantry_transactions \|o--o\| pantry_transactions` (`reverses_id`) |

Tập cột khoá ngoại chứa một khoá (ví dụ `(active_version_id, name)` chứa khoá chính `name` của `model_deployments`) cũng được coi là duy nhất.

Đầu bảng con luôn có cận dưới 0 vì DDL không ép được "bảng cha phải có ít nhất một con" (ví dụ mâm có ít nhất hai món là luật ở service, BR-TRAY-01). Nhãn cạnh là tên cột khoá ngoại, kèm `(cascade)` hoặc `(set_null)` khi có `ON DELETE`. Khoá ngoại ghép cho phép NULL một phần (`interactions (meal_plan_id, user_id)`) theo `MATCH SIMPLE`: khi một cột NULL thì không kiểm, nên đầu cha là `|o`. Hệ quả của `MATCH SIMPLE` là một khoá ngoại ghép có thể lưu "nửa khoá" (một cột có giá trị, cột kia NULL) mà không bị kiểm. Mọi khoá ngoại ghép có cột cho phép NULL vì vậy đi kèm CHECK ghép đôi: `ck_ingredients_comp_pair` (`comp_source_id`, `comp_source_code` cùng NULL hoặc cùng có giá trị), `ck_interactions_item_needs_plan` (có `meal_plan_item_id` thì phải có `meal_plan_id`). Riêng `(previous_version_id, name)` của `model_deployments` không cần, vì `name` là khoá chính, luôn khác NULL.

## 2. Phương pháp và tóm tắt

Các bước cho mỗi bảng:

1. Xác định khoá ứng viên từ khoá chính và ràng buộc `UNIQUE` NOT NULL. Mọi khoá ứng viên nêu trong mục 3 đều đã khai trong DDL. Cột `UNIQUE` cho phép NULL (`refresh_tokens.replaced_by_id`, `pantry_transactions.reverses_id`, `meal_plan_items.replaced_item_id`) không là khoá ứng viên của cả quan hệ nhưng là siêu khoá trên các bộ có cột đó khác NULL (quy ước N1 dưới đây). Chỉ mục duy nhất một phần (`ux_recipes_name_vi_live`...) chỉ là khoá trên tập con thoả điều kiện `WHERE`, không phải khoá ứng viên.
2. Liệt kê PTH không tầm thường: PTH từ khoá chính tới các cột còn lại (vế phải sinh từ DDL), PTH từ khoá thay thế, và mọi PTH có vế trái không phải khoá tìm được khi soát ngữ nghĩa từng cột.
3. Kiểm lần lượt: 1NF (giá trị nguyên tố, không nhóm lặp, có khoá), 2NF (không thuộc tính không khoá nào phụ thuộc vào một phần thực sự của khoá ứng viên), 3NF (với mọi X → A không tầm thường: X là siêu khoá hoặc A là thuộc tính khoá), BCNF (với mọi X → A không tầm thường: X là siêu khoá).

**Quy ước về NULL và ràng buộc trong một bộ (áp cho mọi bảng).**

- **N1. PTH có vế trái chứa cột cho phép NULL** được xét trên các bộ có vế trái khác NULL hoàn toàn, cùng ngữ nghĩa với `UNIQUE` và khoá ngoại `MATCH SIMPLE` của SQL. Ví dụ `dsr_requests.user_id → subject_ref`, `pantry_lots.source_scan_item_id → user_id`. Các PTH này được tính khi xét dạng chuẩn.
- **N2. Ràng buộc mẫu hằng trong một bộ**, dạng "X khác NULL ⇒ A = c", "A = a ⇔ B = b" hay "A = (B IS NULL)", là phụ thuộc hàm có điều kiện với mẫu hằng (conditional functional dependency, Bohannon và cộng sự 2007). Hằng `c` thuộc về lược đồ, không phải dữ liệu, nên ràng buộc không lặp một sự thật nào giữa các bộ và không sinh dị thường thêm, sửa, xoá kiểu mà 2NF–BCNF loại bỏ. Vì vậy chúng **không** được tính khi xét 2NF–BCNF. Điều kiện bù lại: mọi ràng buộc N2 phải được ép bằng `CHECK`; danh sách đầy đủ ở D12. Phân biệt với N1: ở N1, giá trị vế phải thay đổi theo giá trị vế trái (mỗi người dùng một `subject_ref` khác nhau), nên cùng một cặp giá trị lặp lại ở nhiều bộ và là dư thừa thật.

PTH xuyên bảng (giá trị một cột suy ra được qua đường khoá ngoại sang bảng khác, như `recipe_nutrition` suy từ `recipe_ingredients` và `food_nutrients`) không phá dạng chuẩn của từng quan hệ theo định nghĩa, nhưng vẫn là dư thừa; chúng được liệt kê cùng phi chuẩn hoá có kiểm soát ở mục 4.

**Kết quả:** 55 bảng đạt BCNF. 7 bảng cố ý dừng ở 2NF hoặc 1NF, mỗi trường hợp có lý do và cơ chế giữ nhất quán ở mục 4 (D1, D4, D6, D7, D8, D9). Các bản chép theo thời điểm (ảnh chụp) không tạo PTH vì giá trị nguồn thay đổi theo thời gian; chúng vẫn được giải thích ở D2, D3, D10, D11. Ràng buộc mẫu hằng (N2) liệt kê ở D12; tham chiếu đa hình của giao dịch kho ở D13.

**Bất biến được ép trong CSDL.** Lập luận "không có dị thường" ở mục 4 dựa vào một số bất biến: món đã công bố không sửa, bảng nhật ký chỉ ghi thêm, cột chỉ ghi một lần, giá trị dẫn xuất chỉ tính lại ở trạng thái cho phép. Các bất biến này không phải lời hứa của service mà được ép bằng trigger trong `db/schema.sql`, mỗi mục D dẫn đúng tên trigger. Ngoại lệ duy nhất là giao dịch xoá theo quyền chủ thể dữ liệu và thời hạn lưu (UC07, BR-CONSENT-04, job dọn): giao dịch đó chạy `SET LOCAL tastoria.erasure = 'on'`. Trigger là chốt chặn lỗi lập trình. Ranh giới quyền là đặc quyền CSDL: khối cuối `db/schema.sql` thu hồi `UPDATE`, `DELETE`, `TRUNCATE` trên bốn bảng chỉ ghi thêm của vai trò `tastoria_app` và chỉ cấp `DELETE` cho vai trò `tastoria_jobs`.

### Bảng tổng hợp

| # | Bảng | Module | ERD | Dạng chuẩn đạt |
|---|---|---|---|---|
| 1 | `idempotency_keys` | core | ERD01 | BCNF |
| 2 | `users` | identity | ERD01 | BCNF |
| 3 | `refresh_tokens` | identity | ERD01 | 2NF |
| 4 | `password_resets` | identity | ERD01 | BCNF |
| 5 | `consent_purposes` | privacy | ERD01 | BCNF |
| 6 | `policy_versions` | privacy | ERD01 | BCNF |
| 7 | `consent_events` | privacy | ERD01 | BCNF |
| 8 | `dsr_requests` | privacy | ERD01 | 2NF |
| 9 | `audit_log` | privacy | ERD01 | BCNF |
| 10 | `food_groups` | catalog | ERD03 | BCNF |
| 11 | `nutrient_sources` | catalog | ERD03 | BCNF |
| 12 | `food_items` | catalog | ERD03 | BCNF |
| 13 | `nutrients` | catalog | ERD03 | BCNF |
| 14 | `food_nutrients` | catalog | ERD03 | BCNF |
| 15 | `allergen_groups` | catalog | ERD03 | BCNF |
| 16 | `diets` | catalog | ERD03 | BCNF |
| 17 | `diet_exclusions` | catalog | ERD03 | BCNF |
| 18 | `ingredients` | catalog | ERD03 | BCNF |
| 19 | `ingredient_synonyms` | catalog | ERD03 | BCNF |
| 20 | `ingredient_allergens` | catalog | ERD03 | BCNF |
| 21 | `ingredient_units` | catalog | ERD03 | BCNF |
| 22 | `qty_levels` | catalog | ERD03 | BCNF |
| 23 | `vision_classes` | catalog | ERD03 | BCNF |
| 24 | `vision_class_ingredients` | catalog | ERD03 | BCNF |
| 25 | `cooking_methods` | catalog | ERD04 | BCNF |
| 26 | `tags` | catalog | ERD04 | BCNF |
| 27 | `recipes` | catalog | ERD04 | BCNF |
| 28 | `recipe_ingredients` | catalog | ERD04 | BCNF |
| 29 | `recipe_steps` | catalog | ERD04 | BCNF |
| 30 | `recipe_tags` | catalog | ERD04 | BCNF |
| 31 | `recipe_sources` | catalog | ERD04 | BCNF |
| 32 | `recipe_nutrition` | catalog | ERD04 | 1NF |
| 33 | `profiles` | profile | ERD02 | BCNF |
| 34 | `user_allergens` | profile | ERD02 | BCNF |
| 35 | `user_favorite_recipes` | profile | ERD02 | BCNF |
| 36 | `user_settings` | profile | ERD02 | BCNF |
| 37 | `pantry_lots` | pantry | ERD05 | 2NF |
| 38 | `pantry_transactions` | pantry | ERD05 | BCNF |
| 39 | `scans` | scan | ERD05 | BCNF |
| 40 | `scan_images` | scan | ERD05 | BCNF |
| 41 | `scan_items` | scan | ERD05 | BCNF |
| 42 | `detections` | scan | ERD05 | BCNF |
| 43 | `model_versions` | mlops | ERD07 | BCNF |
| 44 | `model_version_classes` | mlops | ERD07 | BCNF |
| 45 | `model_deployments` | mlops | ERD07 | BCNF |
| 46 | `substitution_pairs` | substitute | ERD06 | BCNF |
| 47 | `ingredient_embeddings` | substitute | ERD06 | BCNF |
| 48 | `shopping_items` | substitute | ERD06 | 2NF |
| 49 | `meal_plans` | meal | ERD06 | BCNF |
| 50 | `meal_plan_coeater_allergens` | meal | ERD06 | BCNF |
| 51 | `meal_plan_pins` | meal | ERD06 | BCNF |
| 52 | `meal_plan_items` | meal | ERD06 | 2NF |
| 53 | `meal_plan_item_substitutions` | meal | ERD06 | BCNF |
| 54 | `cook_sessions` | cooking | ERD06 | BCNF |
| 55 | `cook_schedule_entries` | cooking | ERD06 | BCNF |
| 56 | `interactions` | events | ERD06 | 2NF |
| 57 | `survey_forms` | survey | ERD07 | BCNF |
| 58 | `survey_form_anchors` | survey | ERD07 | BCNF |
| 59 | `survey_respondents` | survey | ERD07 | BCNF |
| 60 | `survey_assignments` | survey | ERD07 | BCNF |
| 61 | `survey_ratings` | survey | ERD07 | BCNF |
| 62 | `survey_favorites` | survey | ERD07 | BCNF |

## 3. Phân tích từng bảng

### Nhóm core (ERD01)

#### `idempotency_keys`

- **Khoá ứng viên:** {`user_id`, `key`}.
- **PTH không tầm thường:** `user_id`, `key` → `request_sha256`, `status_code`, `response_body`, `created_at`
- **1NF:** Đạt. `response_body` là jsonb nhưng được coi là một giá trị nguyên tố của miền "tài liệu phản hồi": CSDL chỉ lưu và trả lại nguyên văn, không truy vấn hay ràng buộc theo thành phần bên trong (xem D5).
- **2NF:** Đạt. Cùng một `key` có thể do hai người dùng sinh ra, và một người dùng có nhiều khoá, nên không cột nào phụ thuộc chỉ vào `user_id` hay chỉ vào `key`; mọi cột không khoá phụ thuộc vào cả cặp.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

### Nhóm identity (ERD01)

#### `users`

- **Khoá ứng viên:** {`id`}; {`email`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `email`, `password_hash`, `role`, `status`, `token_version`, `failed_logins`, `locked_until`, `created_at`, `updated_at`
  - `email` → `id`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `failed_logins`, `locked_until`, `token_version` là trạng thái hiện hành của chính tài khoản, không suy ra từ bảng khác.
- **Kết luận:** BCNF.

#### `refresh_tokens`

- **Khoá ứng viên:** {`id`}; {`token_sha256`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `user_id`, `family_id`, `token_sha256`, `issued_at`, `expires_at`, `revoked_at`, `replaced_by_id`, `user_agent`
  - `token_sha256` → `id`
  - `family_id` → `user_id` (mọi token trong một họ xoay vòng sinh từ cùng một lần đăng nhập của một người)
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** **Không đạt.** `id → family_id → user_id` là phụ thuộc bắc cầu: `family_id` không phải siêu khoá (một họ có nhiều token) nhưng xác định `user_id`.
- **BCNF:** Không đạt (hệ quả của 3NF).
- **Ghi chú:** `replaced_by_id` chỉ khác NULL ở token đã bị xoay và mỗi token chỉ được thay một lần; DDL khai `UNIQUE (replaced_by_id)` nên nó là siêu khoá trên các bộ khác NULL (N1), quan hệ tự thân là 0..1 — 0..1. `user_id`, `family_id`, `token_sha256`, `issued_at`, `expires_at` chỉ ghi một lần (`trg_refresh_tokens_write_once`).
- **Kết luận:** 2NF; vi phạm 3NF có chủ đích, kiểm soát ở D7.

#### `password_resets`

- **Khoá ứng viên:** {`id`}; {`token_sha256`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `user_id`, `token_sha256`, `created_at`, `expires_at`, `used_at`
  - `token_sha256` → `id`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

### Nhóm privacy (ERD01)

#### `consent_purposes`

- **Khoá ứng viên:** {`code`}.
- **PTH không tầm thường:** `code` → `name_vi`, `description_vi`, `data_category`, `is_sensitive`, `is_required`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `policy_versions`

- **Khoá ứng viên:** {`id`}; {`purpose_code`, `version`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `purpose_code`, `version`, `text_sha256`, `effective_from`
  - `purpose_code`, `version` → `id`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Khoá ghép `(purpose_code, version)`: `text_sha256` và `effective_from` thuộc về một phiên bản cụ thể của một mục đích, không phụ thuộc riêng `purpose_code` (một mục đích có nhiều phiên bản) hay riêng `version` (cùng số "1.0" dùng cho nhiều mục đích).
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `consent_events`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `user_id`, `policy_version_id`, `action`, `channel`, `app_version`, `created_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Bảng chỉ ghi thêm (`trg_consent_events_append_only`). Trạng thái đồng ý hiện hành không lưu mà suy ra bằng view `v_current_consents` (sự kiện mới nhất mỗi `(user_id, purpose_code)`), nên không có cột dẫn xuất. `purpose_code` không chép vào đây mà lấy qua `policy_version_id`, tránh PTH bắc cầu `policy_version_id → purpose_code`. `created_at` mặc định `clock_timestamp()` để hai sự kiện trong cùng một giao dịch vẫn có thứ tự xác định trong view.
- **Kết luận:** BCNF.

#### `dsr_requests`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:**
  - `id` → `user_id`, `subject_ref`, `type`, `status`, `received_at`, `acknowledged_at`, `completed_at`, `result_key`, `note`
  - `user_id` → `subject_ref` (với user_id khác NULL; subject_ref = HMAC-SHA256(khoá bí mật, user_id))
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** **Không đạt** khi `user_id` khác NULL: `id → user_id → subject_ref` là bắc cầu (`user_id` không phải siêu khoá, một người có nhiều yêu cầu).
- **BCNF:** Không đạt (hệ quả của 3NF).
- **Ghi chú:** Theo N1, PTH xét trên các bộ có `user_id` khác NULL; sau khi tài khoản bị xoá, `user_id` thành NULL và chỉ còn `subject_ref`.
- **Kết luận:** 2NF; vi phạm 3NF có chủ đích, kiểm soát ở D8.

#### `audit_log`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `actor_user_id`, `actor_role`, `action`, `entity`, `entity_id`, `purpose`, `request_id`, `created_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `actor_role` là vai trò tại thời điểm thao tác. Vai trò của một người có thể đổi, nên không có PTH `actor_user_id → actor_role` trên toàn bảng; đây là thuộc tính của sự kiện, không phải bản chép của `users.role`. Bảng chỉ ghi thêm (`trg_audit_log_append_only`); việc bí danh hoá `entity_id` khi xoá tài khoản ở D8.
- **Kết luận:** BCNF.

### Nhóm catalog — thành phần, nguyên liệu, lớp thị giác (ERD03)

#### `food_groups`

- **Khoá ứng viên:** {`code`}.
- **PTH không tầm thường:** `code` → `name_vi`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `nutrient_sources`

- **Khoá ứng viên:** {`id`}; {`code`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `code`, `name`, `version`, `license`, `url`
  - `code` → `id`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `food_items`

- **Khoá ứng viên:** {`source_id`, `source_code`}.
- **PTH không tầm thường:** `source_id`, `source_code` → `name`, `name_en`, `refuse_pct`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. `source_code` chỉ duy nhất trong một nguồn (mã FCT 2007 và mã USDA có thể trùng chữ), nên `name`, `name_en`, `refuse_pct` phụ thuộc vào cả cặp, không vào riêng thành phần nào.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `refuse_pct` (tỉ lệ thải bỏ, từ đó EP = 100 − refuse_pct) để ở đây chứ không ở `ingredients`: nó là thuộc tính của mục thực phẩm trong bảng thành phần. Nếu chép sang `ingredients` sẽ có `ingredients.id → (comp_source_id, comp_source_code) → refuse_pct`, một phụ thuộc bắc cầu.
- **Kết luận:** BCNF.

#### `nutrients`

- **Khoá ứng viên:** {`code`}.
- **PTH không tầm thường:** `code` → `name_vi`, `unit`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `food_nutrients`

- **Khoá ứng viên:** {`source_id`, `source_code`, `nutrient_code`}.
- **PTH không tầm thường:** `source_id`, `source_code`, `nutrient_code` → `per_100g`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. `per_100g` là hàm lượng của một chất trong một mục thực phẩm: phụ thuộc cả ba cột khoá; không phụ thuộc riêng mục thực phẩm (mỗi chất một giá trị) hay riêng chất.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `allergen_groups`

- **Khoá ứng viên:** {`code`}.
- **PTH không tầm thường:** `code` → `name_vi`, `name_en`, `basis`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `diets`

- **Khoá ứng viên:** {`code`}.
- **PTH không tầm thường:** `code` → `name_vi`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `diet_exclusions`

- **Khoá ứng viên:** {`diet_code`, `food_group_code`}.
- **PTH không tầm thường:** Không có (bảng toàn khoá: mọi cột thuộc khoá chính, chỉ có PTH tầm thường).
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Không có thuộc tính không khoá nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá.
- **BCNF:** Đạt. Chỉ có PTH tầm thường.
- **Kết luận:** BCNF.

#### `ingredients`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `name_vi`, `food_group_code`, `comp_source_id`, `comp_source_code`, `is_staple`, `countable`, `shelf_life_days`, `shelf_life_basis`, `is_active`, `created_at`, `updated_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `name_vi` không phải khoá ứng viên của cả quan hệ: nguyên liệu không xoá cứng mà chuyển `is_active = false` (BR-CATALOG-01), và tên của nguyên liệu đã ngừng được dùng lại cho nguyên liệu mới. Tên chỉ duy nhất trong các dòng đang dùng (`ux_ingredients_name_vi_active ... WHERE is_active`), tức là khoá trên tập con chứ không trên quan hệ. Cặp `(comp_source_id, comp_source_code)` không phải khoá (nhiều nguyên liệu có thể dùng chung một mục thành phần, ví dụ hai loại rau cùng nhóm khi bảng thành phần thiếu). `shelf_life_basis` ghi xuất xứ của `shelf_life_days` (mã FoodKeeper hoặc ghi chú hiệu chỉnh); cùng một mã FoodKeeper có thể cho số ngày khác nhau sau hiệu chỉnh theo nhóm, nên không có PTH `shelf_life_basis → shelf_life_days`. `ck_ingredients_comp_pair` buộc cặp khoá ngoại ghép tới `food_items` cùng NULL hoặc cùng có giá trị (D12).
- **Kết luận:** BCNF.

#### `ingredient_synonyms`

- **Khoá ứng viên:** {`ingredient_id`, `synonym`, `lang`}.
- **PTH không tầm thường:** `ingredient_id`, `synonym`, `lang` → `source`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Thuộc tính không khoá duy nhất `source` (nơi lấy tên gọi) gắn với từng cách gọi của từng nguyên liệu trong từng ngôn ngữ; không phụ thuộc riêng `synonym` vì một tên gọi có thể dùng cho nhiều nguyên liệu ("rau thơm").
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Không có PTH `synonym → ingredient_id` vì tên gọi dân gian có thể nhập nhằng; vì vậy `synonym` không đứng một mình làm khoá.
- **Kết luận:** BCNF.

#### `ingredient_allergens`

- **Khoá ứng viên:** {`ingredient_id`, `allergen_code`}.
- **PTH không tầm thường:** Không có (bảng toàn khoá: mọi cột thuộc khoá chính, chỉ có PTH tầm thường).
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Không có thuộc tính không khoá nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá.
- **BCNF:** Đạt. Chỉ có PTH tầm thường.
- **Kết luận:** BCNF.

#### `ingredient_units`

- **Khoá ứng viên:** {`ingredient_id`, `unit_code`}.
- **PTH không tầm thường:** `ingredient_id`, `unit_code` → `grams_per_unit`, `source`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. `grams_per_unit` và `source` là khối lượng của một đơn vị đếm cho một nguyên liệu cụ thể (1 quả trứng gà = 50 g, 1 quả chanh khác): phụ thuộc cả cặp, không phụ thuộc riêng `unit_code`.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `qty_levels`

- **Khoá ứng viên:** {`food_group_code`, `level`}.
- **PTH không tầm thường:** `food_group_code`, `level` → `g_min`, `g_max`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. `g_min`, `g_max` của mức "vừa" khác nhau giữa nhóm rau và nhóm thịt, nên phụ thuộc cả cặp `(food_group_code, level)`.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `vision_classes`

- **Khoá ứng viên:** {`id`}; {`code`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `code`, `name_vi`, `name_en`, `countable`, `instance_def`, `has_freshness_model`
  - `code` → `id`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `vision_class_ingredients`

- **Khoá ứng viên:** {`vision_class_id`, `ingredient_id`}.
- **PTH không tầm thường:** `vision_class_id`, `ingredient_id` → `is_default`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. `is_default` cho biết nguyên liệu nào được chọn mặc định khi mô hình trả lớp này: thuộc về cặp (lớp, nguyên liệu).
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Ràng buộc "mỗi lớp tối đa một nguyên liệu mặc định" không phải PTH mà là ràng buộc duy nhất trên tập con, ép bằng `ux_vision_class_ingredients_default ... WHERE is_default`.
- **Kết luận:** BCNF.

### Nhóm catalog — món ăn (ERD04)

#### `cooking_methods`

- **Khoá ứng viên:** {`code`}.
- **PTH không tầm thường:** `code` → `name_vi`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `tags`

- **Khoá ứng viên:** {`code`}.
- **PTH không tầm thường:** `code` → `kind`, `name_vi`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `recipes`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `name_vi`, `slot`, `servings`, `method_code`, `status`, `notes`, `created_at`, `updated_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `name_vi` không phải khoá ứng viên của cả quan hệ: theo BR-CATALOG-01, sửa món đã công bố là tạo bản mới cùng tên và chuyển bản cũ sang `retired`, nên hai dòng có thể trùng tên. Tên chỉ duy nhất trong các bản chưa `retired` (`ux_recipes_name_vi_live ... WHERE status <> 'retired'`). Thứ tự ghi của lệnh nhập kho món trong một giao dịch: chuyển bản cũ sang `retired`, thêm bản mới ở `draft`, ghi nguyên liệu, bước, thẻ, rồi chuyển `published`. Món `published` bất biến, `retired` không sửa được và món đã công bố không xoá cứng (`trg_recipes_guard`); nguyên liệu, bước, thẻ chỉ ghi khi món còn `draft` (`trg_recipe_children_guard`). Hiện chưa có cột nối các phiên bản của cùng một món (đề xuất ở mục 6). `UNIQUE (id, slot)` là siêu khoá chứ không phải khoá ứng viên (không tối tiểu, vì `id` đã là khoá); nó tồn tại chỉ để làm đích cho khoá ngoại ghép từ `meal_plan_items` (xem D6). Tổng thời gian và nguyên liệu chính là giá trị dẫn xuất từ `recipe_steps`, `recipe_ingredients` nên không lưu.
- **Kết luận:** BCNF.

#### `recipe_ingredients`

- **Khoá ứng viên:** {`recipe_id`, `ingredient_id`}.
- **PTH không tầm thường:** `recipe_id`, `ingredient_id` → `grams`, `role`, `is_optional`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. `grams`, `role`, `is_optional` mô tả vai trò của một nguyên liệu trong một món cụ thể; không phụ thuộc riêng món hay riêng nguyên liệu.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `recipe_steps`

- **Khoá ứng viên:** {`recipe_id`, `step_no`}.
- **PTH không tầm thường:** `recipe_id`, `step_no` → `text_vi`, `kind`, `minutes`, `uses_burner`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Nội dung, loại, số phút, cờ chiếm bếp thuộc về bước thứ `step_no` của một món; `step_no` riêng lẻ không xác định gì.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Thực thể yếu của `recipes` (khoá bộ phận `step_no`).
- **Kết luận:** BCNF.

#### `recipe_tags`

- **Khoá ứng viên:** {`recipe_id`, `tag_code`}.
- **PTH không tầm thường:** Không có (bảng toàn khoá: mọi cột thuộc khoá chính, chỉ có PTH tầm thường).
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Không có thuộc tính không khoá nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá.
- **BCNF:** Đạt. Chỉ có PTH tầm thường.
- **Ghi chú:** Thay cho cột danh sách `flavor_tags` của v1 (xem mục 5.1). `kind` của thẻ nằm ở `tags`, không chép vào đây (tránh `tag_code → kind`).
- **Kết luận:** BCNF.

#### `recipe_sources`

- **Khoá ứng viên:** {`recipe_id`, `url`}.
- **PTH không tầm thường:** `recipe_id`, `url` → `title`, `accessed_on`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt, với giả định ngữ nghĩa: `title` là tiêu đề trang **như ghi nhận khi trích dẫn** vào ngày `accessed_on`. Tiêu đề trang web đổi theo thời gian và hai lần trích cùng URL (hai phiên bản của một món theo BR-CATALOG-01) có thể ghi hai tiêu đề, nên không có PTH `url → title`. Nếu muốn coi tiêu đề là thuộc tính cố định của URL thì phải tách bảng nguồn riêng (đề xuất cuối tệp).
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `recipe_nutrition`

- **Khoá ứng viên:** {`recipe_id`, `nutrient_code`}.
- **PTH không tầm thường:**
  - `recipe_id`, `nutrient_code` → `per_serving`, `computed_at`, `data_version`
  - `recipe_id` → `computed_at`, `data_version` (job tính lại ghi đủ mọi chất của một món trong một giao dịch)
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** **Không đạt** theo quy ước vận hành: `computed_at` và `data_version` chỉ phụ thuộc `recipe_id`, là một phần của khoá.
- **3NF:** Không xét được (chưa đạt 2NF).
- **BCNF:** Không đạt.
- **Ghi chú:** Ngoài PTH nội bộ trên, toàn bộ `per_serving` là dư thừa liên quan hệ: suy ra được từ `recipe_ingredients × food_items.refuse_pct × food_nutrients`.
- **Kết luận:** 1NF; là bảng đệm dẫn xuất có kiểm soát (D1). Bản thân `per_serving` phụ thuộc đầy đủ vào khoá.

### Nhóm profile (ERD02)

#### `profiles`

- **Khoá ứng viên:** {`user_id`}.
- **PTH không tầm thường:** `user_id` → `sex_enc`, `birth_year_enc`, `height_cm_enc`, `weight_kg_enc`, `enc_key_id`, `activity_level`, `goal`, `kcal_target`, `kcal_source`, `diet_code`, `updated_at`
- **1NF:** Đạt. Các cột `*_enc` là bản mã AES-GCM của một giá trị vô hướng (giới tính, năm sinh, chiều cao, cân nặng); mỗi ô chứa đúng một giá trị đã mã hoá, không phải tập hợp.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Khi `kcal_source = 'suggested'`, `kcal_target` bằng giá trị tính từ BMR × PAL (BR-NUT-01..03). Nó vẫn được lưu vì người dùng xác nhận hoặc ghi đè (`user`, `expert`); giá trị lưu là mục tiêu đã chọn, không phải kết quả công thức, nên không có PTH từ các cột cơ thể sang `kcal_target`. `diet_code` để ở đây (mỗi người một chế độ ăn), danh sách nhóm loại trừ nằm ở `diet_exclusions`. Giá trị `expert` có ở cả `goal` lẫn `kcal_source`; quan hệ giữa chúng là ràng buộc mẫu hằng (N2): `kcal_source = expert` khi và chỉ khi `goal = expert`, xét khi đã có `kcal_source` (`ck_profiles_expert`). Đây không phải PTH: `goal = maintain` có thể đi với `suggested` hoặc `user`, và `kcal_source = suggested` có thể đi với `maintain` hoặc `lose`. Các ràng buộc bộ khác: `ck_profiles_kcal_pair`, `ck_profiles_enc_key` (D12).
- **Kết luận:** BCNF.

#### `user_allergens`

- **Khoá ứng viên:** {`user_id`, `allergen_code`}.
- **PTH không tầm thường:** Không có (bảng toàn khoá: mọi cột thuộc khoá chính, chỉ có PTH tầm thường).
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Không có thuộc tính không khoá nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá.
- **BCNF:** Đạt. Chỉ có PTH tầm thường.
- **Kết luận:** BCNF.

#### `user_favorite_recipes`

- **Khoá ứng viên:** {`user_id`, `recipe_id`}.
- **PTH không tầm thường:** `user_id`, `recipe_id` → `created_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. `created_at` là thời điểm người dùng chọn món đó; phụ thuộc cả cặp.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `user_settings`

- **Khoá ứng viên:** {`user_id`}.
- **PTH không tầm thường:** `user_id` → `burners`, `default_persons`, `timezone`, `updated_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

### Nhóm pantry (ERD05)

#### `pantry_lots`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:**
  - `id` → `user_id`, `ingredient_id`, `initial_g_min`, `initial_g_max`, `acquired_at`, `acquired_basis`, `status`, `p_tuoi`, `p_dung_som`, `p_dung_ngay`, `p_kiem_tra`, `freshness_observed_at`, `freshness_model_version_id`, `user_checked_at`, `source_scan_item_id`, `created_at`, `updated_at`
  - `source_scan_item_id` → `user_id` (với source_scan_item_id khác NULL: chip thuộc một lần quét của đúng người đó)
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** **Không đạt** với các lô sinh từ quét: `id → source_scan_item_id → user_id` là bắc cầu (một chip có thể sinh nhiều lô nên `source_scan_item_id` không phải siêu khoá). Các cột `p_*`, `freshness_*` là bản chép quan sát mới nhất (D3); `ingredient_id` không thuộc PTH này vì người dùng được sửa nguyên liệu của lô ở UC14.
- **BCNF:** Không đạt (hệ quả của 3NF).
- **Ghi chú:** Lượng hiện tại không lưu: `v_pantry_lot_balance` tính `initial + Σ delta`. Độ gấp u không lưu (BR-FRESH-05). `status` không dẫn xuất được từ số dư: `discarded`, `not_seen` là quyết định của người dùng hoặc của lần quét.
- **Kết luận:** 2NF; `user_id` và nhóm `p_*` là dư thừa có kiểm soát (D3, D9).

#### `pantry_transactions`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `lot_id`, `delta_g_min`, `delta_g_max`, `reason`, `ref_type`, `ref_id`, `reverses_id`, `urgency_at_event`, `created_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Chỉ ghi thêm (`trg_pantry_transactions_append_only`); hoàn tác là một bản ghi đảo trỏ `reverses_id`. Theo BR-PANTRY-02 mỗi giao dịch bị đảo tối đa một lần, và DDL khai `UNIQUE (reverses_id)`, nên `reverses_id` là siêu khoá trên các bộ khác NULL (N1). Nhờ đó các PTH `reverses_id → lot_id` và `reverses_id → delta_*` (bản đảo cùng lô, đổi dấu) có vế trái là siêu khoá và không phá BCNF; trigger `trg_pantry_transactions_ref` kiểm bản đảo cùng lô. `reason = undo` khi và chỉ khi có `reverses_id` là ràng buộc mẫu hằng (N2, `ck_pantry_transactions_undo`). Ở v2 mỗi `reason` thường đi với một `ref_type`, nhưng thiết kế không ép cặp này (`manual_edit` và `discard` có thể do người dùng hoặc job), nên không ghi PTH `reason → ref_type`. `urgency_at_event` là ảnh chụp độ gấp lúc trừ kho (D2). `(ref_type, ref_id)` là tham chiếu đa hình, kiểm bằng trigger thay cho khoá ngoại (D13).
- **Kết luận:** BCNF.

### Nhóm scan (ERD05)

#### `scans`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `user_id`, `mode`, `status`, `error_code`, `attempts`, `detector_version_id`, `classifier_version_id`, `preprocess_version`, `enqueued_at`, `started_at`, `finished_at`, `confirmed_at`, `created_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `preprocess_version` là phiên bản tiền xử lý **đã áp dụng** cho lần quét, không phải bản chép `model_versions.preprocess_version` (phiên bản mô hình yêu cầu). Hai giá trị lẽ ra bằng nhau; lưu riêng để phát hiện lệch, nên không coi là PTH `detector_version_id → preprocess_version`.
- **Kết luận:** BCNF.

#### `scan_images`

- **Khoá ứng viên:** {`id`}; {`storage_key`}; {`scan_id`, `ordinal`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `scan_id`, `ordinal`, `shelf_group`, `storage_key`, `width`, `height`, `contributed`, `purged_at`
  - `storage_key` → `id`
  - `scan_id`, `ordinal` → `id`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Với khoá ghép `(scan_id, ordinal)`: `shelf_group`, `storage_key`, kích thước, cờ góp ảnh, thời điểm xoá là của từng ảnh, không phụ thuộc riêng `scan_id` (một lần quét có 1–2 ảnh khác nhau) hay riêng `ordinal`.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `scan_items`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `scan_id`, `ingredient_id`, `origin`, `model_count`, `final_count`, `qty_level`, `user_action`, `original_ingredient_id`, `user_freshness`, `created_at`, `updated_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `model_count` là số đếm của mô hình sau khi gộp các khung (BR-SCAN-01: cùng ngăn lấy max, khác ngăn cộng), suy ra được từ `detections` (D10). `final_count` là con số người dùng xác nhận, độc lập. Các ràng buộc giữa `origin`, `user_action`, `original_ingredient_id`, `model_count` là ràng buộc mẫu hằng (N2), ép bằng CHECK: đổi nhãn thì phải có nhãn gốc (`ck_scan_items_relabeled`), nhãn gốc chỉ có ở chip của mô hình và khác nhãn hiện tại (`ck_scan_items_original`), chip người dùng thêm không có `model_count` (`ck_scan_items_user_added`). Không có PTH `original_ingredient_id → user_action`: chip đã đổi nhãn rồi sửa số đếm có `user_action = edited` mà vẫn giữ nhãn gốc. `scan_id`, `origin`, `model_count` chỉ ghi một lần (`trg_scan_items_write_once`).
- **Kết luận:** BCNF.

#### `detections`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `scan_image_id`, `scan_item_id`, `vision_class_id`, `x1`, `y1`, `x2`, `y2`, `confidence`, `p_tuoi`, `p_dung_som`, `p_dung_ngay`, `p_kiem_tra`
- **1NF:** Đạt. Khung giữ bốn cột `x1, y1, x2, y2` thay cho một cột `bbox` ghép như v1.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `confidence` và bốn xác suất độ tươi trong [0, 1]; bốn xác suất cùng NULL hoặc cùng có giá trị và có tổng 1 (`ck_detections_p_*`, BR-FRESH-02).
- **Kết luận:** BCNF.

### Nhóm mlops (ERD07)

#### `model_versions`

- **Khoá ứng viên:** {`id`}; {`name`, `version`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `name`, `version`, `artifact_key`, `sha256`, `preprocess_version`, `metrics`, `gate_report_key`, `mlflow_run_id`, `status`, `created_at`
  - `name`, `version` → `id`
- **1NF:** Đạt. `metrics` (jsonb) là báo cáo đánh giá đọc nguyên khối, không truy vấn theo thành phần (D5).
- **2NF:** Đạt. Với khoá ghép `(name, version)`: tệp mô hình, băm, chỉ số, trạng thái là của một phiên bản cụ thể của một loại mô hình; số phiên bản lặp lại giữa các loại, và một loại có nhiều phiên bản.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Phiên bản đang chạy không lưu ở đây (không có cờ `is_active`) mà duy nhất qua `model_deployments`, tránh hai nơi cùng ghi một sự thật.
- **Kết luận:** BCNF.

#### `model_version_classes`

- **Khoá ứng viên:** {`model_version_id`, `class_index`}; {`model_version_id`, `vision_class_id`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `model_version_id`, `class_index` → `vision_class_id`
  - `model_version_id`, `vision_class_id` → `class_index` (mỗi lớp xuất hiện một lần trong đầu ra của một mô hình)
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Cả hai khoá ứng viên đều ghép và bảng chỉ có ba cột; cột không thuộc khoá này thì thuộc khoá kia, nên mọi thuộc tính đều là thuộc tính khoá.
- **3NF:** Đạt. Không có thuộc tính không khoá.
- **BCNF:** Đạt. Hai PTH không tầm thường `(model_version_id, class_index) → vision_class_id` và `(model_version_id, vision_class_id) → class_index` đều có vế trái là khoá ứng viên.
- **Ghi chú:** Bảng không toàn khoá: khoá chính hai cột, cột thứ ba phụ thuộc vào nó. Khoá ứng viên thứ hai khai bằng `UNIQUE (model_version_id, vision_class_id)`.
- **Kết luận:** BCNF.

#### `model_deployments`

- **Khoá ứng viên:** {`name`}; {`active_version_id`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `name` → `active_version_id`, `previous_version_id`, `switched_at`, `switched_by`
  - `active_version_id` → `name` (một phiên bản thuộc đúng một tên mô hình, và mỗi tên chỉ có một con trỏ)
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Hai khoá ứng viên đều khai trong DDL: khoá chính `name` và `UNIQUE (active_version_id)`. PTH `active_version_id → name` vốn là PTH liên quan hệ (tên lấy từ `model_versions.name`); nó được ép bằng khoá ngoại ghép `(active_version_id, name) → model_versions (id, name)` (đích là siêu khoá `UNIQUE (id, name)`), và `(previous_version_id, name)` cũng vậy, nên con trỏ không thể trỏ phiên bản của loại mô hình khác. Ở ERD07 hai cạnh tới `model_versions` là 0..1 phía con.
- **Kết luận:** BCNF.

### Nhóm substitute (ERD06)

#### `substitution_pairs`

- **Khoá ứng viên:** {`id`}; {`ingredient_id`, `substitute_id`, `context_slot`, `context_method_code`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `ingredient_id`, `substitute_id`, `context_slot`, `context_method_code`, `ratio`, `score`, `source`, `curated`
  - `ingredient_id`, `substitute_id`, `context_slot`, `context_method_code` → `id`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Với khoá ghép bốn cột: `ratio`, `score`, `source`, `curated` thay đổi theo ngữ cảnh (cùng cặp nguyên liệu có thể thay được trong canh nhưng không trong món rán), nên không phụ thuộc riêng cặp `(ingredient_id, substitute_id)` hay bất kỳ tập con nào.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Khoá thay thế có hai cột cho phép NULL (`NULL` = mọi slot / mọi cách nấu); `UNIQUE NULLS NOT DISTINCT` làm NULL so sánh bằng nhau, nên tổ hợp vẫn hoạt động như khoá. `ratio`, `score`, `source`, `curated` thuộc về cặp trong ngữ cảnh.
- **Kết luận:** BCNF.

#### `ingredient_embeddings`

- **Khoá ứng viên:** {`ingredient_id`, `model_version_id`}.
- **PTH không tầm thường:** `ingredient_id`, `model_version_id` → `vector`
- **1NF:** Đạt. `vector(100)` là một giá trị của miền vector pgvector; CSDL chỉ dùng nó nguyên khối (khoảng cách cosine), không truy cập từng chiều.
- **2NF:** Đạt. Vector của một nguyên liệu khác nhau giữa các phiên bản mô hình nên phụ thuộc cả cặp.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `shopping_items`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:**
  - `id` → `user_id`, `ingredient_id`, `qty_g`, `note`, `status`, `source_meal_plan_item_id`, `created_at`, `updated_at`
  - `source_meal_plan_item_id` → `user_id` (với giá trị khác NULL, qua mâm của người dùng)
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** **Không đạt** với dòng sinh từ mâm: `id → source_meal_plan_item_id → user_id` là bắc cầu (một món trong mâm sinh nhiều dòng đi chợ).
- **BCNF:** Không đạt (hệ quả của 3NF).
- **Kết luận:** 2NF; dư thừa có kiểm soát (D9).

### Nhóm meal (ERD06)

#### `meal_plans`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `user_id`, `meal`, `persons`, `max_minutes`, `status`, `e_target_kcal`, `kcal_low`, `kcal_high`, `rice_bowls_per_person`, `reason_vi`, `ranker_version_id`, `params_version`, `created_at`, `updated_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `UNIQUE (id, user_id)` là siêu khoá dùng làm đích của khoá ngoại ghép từ `interactions` (D4). `e_target_kcal` là ảnh chụp lúc tạo mâm; `kcal_low`, `kcal_high`, `rice_bowls_per_person` là giá trị dẫn xuất, chỉ tính lại khi mâm còn `proposed`/`accepted` (D2). Không có PTH với `profiles` vì hồ sơ đổi sau đó. `params_version` chưa có bảng đích (mục 6).
- **Kết luận:** BCNF.

#### `meal_plan_coeater_allergens`

- **Khoá ứng viên:** {`meal_plan_id`, `allergen_code`}.
- **PTH không tầm thường:** Không có (bảng toàn khoá: mọi cột thuộc khoá chính, chỉ có PTH tầm thường).
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Không có thuộc tính không khoá nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá.
- **BCNF:** Đạt. Chỉ có PTH tầm thường.
- **Kết luận:** BCNF.

#### `meal_plan_pins`

- **Khoá ứng viên:** {`meal_plan_id`, `lot_id`}.
- **PTH không tầm thường:** Không có (bảng toàn khoá: mọi cột thuộc khoá chính, chỉ có PTH tầm thường).
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Không có thuộc tính không khoá nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá.
- **BCNF:** Đạt. Chỉ có PTH tầm thường.
- **Ghi chú:** Ràng buộc "lô ghim phải thuộc chủ mâm" và "tối đa 2 lô" (BR-TRAY-08) không phải PTH; kiểm ở service (đề xuất khoá ngoại ghép cuối tệp).
- **Kết luận:** BCNF.

#### `meal_plan_items`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:**
  - `id` → `meal_plan_id`, `slot`, `recipe_id`, `status`, `replaced_item_id`, `swap_reason`, `rank_score`, `servings_scale`, `kcal_per_person`, `created_at`
  - `recipe_id` → `slot` (slot là thuộc tính của món)
  - `replaced_item_id` → `meal_plan_id`, `slot` (với giá trị khác NULL; món thay vào cùng mâm, cùng slot với món bị đổi)
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** **Không đạt**: `id → recipe_id → slot` là bắc cầu (`recipe_id` không là siêu khoá: cùng một món xuất hiện trong nhiều mâm). PTH thứ hai không phá dạng chuẩn vì mỗi món chỉ bị đổi một lần và DDL khai `UNIQUE (replaced_item_id)`, nên `replaced_item_id` là siêu khoá trên các bộ khác NULL (N1).
- **BCNF:** Không đạt (hệ quả của 3NF).
- **Ghi chú:** `UNIQUE (meal_plan_id, slot) WHERE status = 'active'` là ràng buộc một phần, không phải khoá ứng viên của cả quan hệ (một mâm có nhiều món `swapped_out` cùng slot). `UNIQUE (id, meal_plan_id, recipe_id)` là siêu khoá làm đích khoá ngoại ghép từ `interactions` (D4). `rank_score`, `servings_scale` là ảnh chụp ghi một lần; `kcal_per_person` là giá trị dẫn xuất tính lại khi thay nguyên liệu (D2).
- **Kết luận:** 2NF; `slot` chép có chủ đích và được khoá ngoại ghép giữ nhất quán (D6).

#### `meal_plan_item_substitutions`

- **Khoá ứng viên:** {`item_id`, `original_ingredient_id`}.
- **PTH không tầm thường:** `item_id`, `original_ingredient_id` → `substitute_ingredient_id`, `grams`, `origin`, `created_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Nguyên liệu thay, lượng gam, nguồn gợi ý và thời điểm thuộc về việc thay một nguyên liệu cụ thể trong một món của mâm; không phụ thuộc riêng `item_id` (một món có thể thay nhiều nguyên liệu) hay riêng nguyên liệu gốc.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

### Nhóm cooking (ERD06)

#### `cook_sessions`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `meal_plan_id`, `status`, `serve_at`, `burners`, `started_at`, `completed_at`, `reverted_at`, `created_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Không lưu `user_id`; chủ sở hữu truy qua `meal_plan_id`, tránh PTH `meal_plan_id → user_id`. `burners` là ảnh chụp số họng bếp lúc lập lịch (D2). Một mâm có tối đa một phiên `in_progress` hoặc `completed` (`ux_cook_sessions_one_live`), nên hai thiết bị gửi "nấu xong" song song với khoá lũy đẳng khác nhau không tạo được hai phiên hoàn tất. Quan hệ giữa `status` và `completed_at`, `reverted_at` là ràng buộc mẫu hằng (N2, `ck_cook_sessions_completed`, `ck_cook_sessions_reverted`).
- **Kết luận:** BCNF.

#### `cook_schedule_entries`

- **Khoá ứng viên:** {`cook_session_id`, `recipe_id`, `step_no`}.
- **PTH không tầm thường:** `cook_session_id`, `recipe_id`, `step_no` → `start_offset_s`, `end_offset_s`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Thời điểm bắt đầu/kết thúc là lịch của một bước trong một phiên; bước của món đã có nội dung riêng ở `recipe_steps`, không chép vào đây.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `(cook_session_id, start_offset_s)` không phải khoá vì các bước thụ động chạy song song có thể bắt đầu cùng lúc.
- **Kết luận:** BCNF.

### Nhóm events (ERD06)

#### `interactions`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:**
  - `id` → `user_id`, `recipe_id`, `meal_plan_id`, `meal_plan_item_id`, `type`, `position`, `swap_reason`, `ranker_version_id`, `propensity`, `occurred_at`, `received_at`
  - `meal_plan_id` → `user_id` (với meal_plan_id khác NULL)
  - `meal_plan_item_id` → `meal_plan_id`, `recipe_id` (với meal_plan_item_id khác NULL)
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** **Không đạt**: `id → meal_plan_id → user_id` và `id → meal_plan_item_id → recipe_id` là bắc cầu (một mâm, một món trong mâm sinh nhiều sự kiện).
- **BCNF:** Không đạt (hệ quả của 3NF).
- **Ghi chú:** `id` là `event_id` do app sinh để chống ghi trùng. Cả hai PTH bắc cầu đều được CSDL ép bằng khoá ngoại ghép (D4). Bảng chỉ ghi thêm (`trg_interactions_append_only`).
- **Kết luận:** 2NF; dư thừa có kiểm soát (D4). `ranker_version_id`, `propensity` là ảnh chụp ghi log chính sách (D2).

### Nhóm survey (ERD07)

#### `survey_forms`

- **Khoá ứng viên:** {`id`}; {`version`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `id` → `version`, `n_anchor`, `n_random`, `is_open`, `created_at`
  - `version` → `id`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Kết luận:** BCNF.

#### `survey_form_anchors`

- **Khoá ứng viên:** {`form_id`, `recipe_id`}.
- **PTH không tầm thường:** Không có (bảng toàn khoá: mọi cột thuộc khoá chính, chỉ có PTH tầm thường).
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Không có thuộc tính không khoá nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá.
- **BCNF:** Đạt. Chỉ có PTH tầm thường.
- **Ghi chú:** Không đổi được khi phiếu đã mở hoặc đã có người tham gia (`trg_survey_form_anchors_guard`), để `survey_assignments.is_anchor` không lệch nguồn (D11).
- **Kết luận:** BCNF.

#### `survey_respondents`

- **Khoá ứng viên:** {`id`}.
- **PTH không tầm thường:** `id` → `form_id`, `policy_version_id`, `consented_at`, `completed_at`, `channel`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Mọi khoá ứng viên chỉ có một cột nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** Không có cột định danh người thật; `policy_version_id` là bằng chứng đồng ý mục đích `survey`.
- **Kết luận:** BCNF.

#### `survey_assignments`

- **Khoá ứng viên:** {`respondent_id`, `recipe_id`}; {`respondent_id`, `display_order`} (khoá chính là khoá đầu).
- **PTH không tầm thường:**
  - `respondent_id`, `recipe_id` → `display_order`, `is_anchor`
  - `respondent_id`, `display_order` → `recipe_id`, `is_anchor` (mỗi vị trí hiển thị một món)
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. `display_order` và `is_anchor` thuộc về việc giao một món cho một người tham gia; không phụ thuộc riêng thành phần nào của khoá.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `is_anchor` suy ra được: bằng `true` khi `recipe_id` có trong `survey_form_anchors` của phiếu mà người tham gia điền (D11). Khoá ứng viên thứ hai khai bằng `UNIQUE (respondent_id, display_order)`.
- **Kết luận:** BCNF.

#### `survey_ratings`

- **Khoá ứng viên:** {`respondent_id`, `recipe_id`}.
- **PTH không tầm thường:** `respondent_id`, `recipe_id` → `rating`, `never_eaten`, `answered_at`
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Điểm, cờ chưa ăn và thời điểm trả lời thuộc về câu trả lời của một người cho một món.
- **3NF:** Đạt. Không có thuộc tính không khoá nào phụ thuộc vào một tập cột không phải siêu khoá.
- **BCNF:** Đạt. Vế trái của mọi PTH không tầm thường là siêu khoá.
- **Ghi chú:** `never_eaten = (rating IS NULL)` là ràng buộc mẫu hằng (N2), không phải PTH `rating → never_eaten`: với mọi `rating` khác NULL, `never_eaten` là hằng `false`, nên không có cặp giá trị nào lặp giữa các bộ. Cột này vẫn là một bit dư thừa, được ép bằng `CHECK ((rating IS NULL) = never_eaten)` (D12).
- **Kết luận:** BCNF.

#### `survey_favorites`

- **Khoá ứng viên:** {`respondent_id`, `recipe_id`}.
- **PTH không tầm thường:** Không có (bảng toàn khoá: mọi cột thuộc khoá chính, chỉ có PTH tầm thường).
- **1NF:** Đạt. Mỗi cột chứa một giá trị nguyên tố của miền (vô hướng hoặc enum), không có nhóm lặp; có khoá chính.
- **2NF:** Đạt. Không có thuộc tính không khoá nên không thể có phụ thuộc bộ phận.
- **3NF:** Đạt. Không có thuộc tính không khoá.
- **BCNF:** Đạt. Chỉ có PTH tầm thường.
- **Kết luận:** BCNF.

## 4. Phi chuẩn hoá có kiểm soát

Mỗi mục ghi: dư thừa nằm ở đâu, vì sao cần, và cơ chế nào trong CSDL giữ nhất quán (tên trigger, ràng buộc trong `db/schema.sql`). D1–D6 là các trường hợp đã định sẵn trong thiết kế v2. D7–D11 là các trường hợp tìm thêm khi soát PTH từng cột ở mục 3. D12 gom các ràng buộc mẫu hằng (quy ước N2), D13 là tham chiếu đa hình.

### D1. `recipe_nutrition` — bảng đệm dẫn xuất

- **Dư thừa.** `per_serving` của mỗi chất suy ra được theo BR-NUT-05: Σ `recipe_ingredients.grams` × EP (= 100 − `food_items.refuse_pct`) / 100 × `food_nutrients.per_100g` (RF = 1 ở v2), chia `recipes.servings`. Ngoài ra `computed_at`, `data_version` chỉ phụ thuộc `recipe_id` (job ghi đủ các chất của một món trong một giao dịch), nên bảng chỉ đạt 1NF.
- **Vì sao cần.** Ghép mâm (`POST /meal-plans`, NFR-PERF-02: p95 ≤ 1 s với kho 200 món) cần kcal của mọi món ứng viên ở mỗi lần gọi. Tính lại từ ba bảng mỗi lần là phép nối và gộp trên toàn kho món; bảng đệm biến nó thành một lần đọc theo khoá. `data_version` ghi phiên bản dữ liệu nguồn để báo cáo calo (BR-NUT-06) truy được về đúng bảng thành phần đã dùng.
- **Giữ nhất quán.** Bảng chỉ do một nơi ghi: lệnh `tastoria catalog import` (UC25) tính lại sau mỗi lần nhập kho món hoặc bảng thành phần, xoá và ghi lại toàn bộ dòng của món trong cùng giao dịch, nên không có trạng thái "một chất mới, một chất cũ". Đầu vào phía món không đổi sau khi công bố, và điều này do CSDL ép: `trg_recipe_children_guard` từ chối mọi INSERT, UPDATE, DELETE trên `recipe_ingredients` (cùng `recipe_steps`, `recipe_tags`) khi món không còn `draft`, và `trg_recipes_guard` chỉ cho món `published` chuyển sang `retired`. Một lệnh UPDATE gõ tay vì vậy không làm lệch được bảng đệm. Giá trị đệm chỉ lỗi thời khi bảng thành phần đổi, đúng lúc job chạy. Kiểm thử: so `recipe_nutrition` với phép tính trực tiếp trên toàn kho món sau mỗi lần nhập.
- **Phương án chuẩn hoá đầy đủ (không chọn).** Một view thường thay bảng (chậm như trên), hoặc tách `computed_at`, `data_version` sang bảng `(recipe_id → computed_at, data_version)` để đạt BCNF; lợi ích nhỏ vì cả bảng là đệm.

### D2. Cột ảnh chụp và cột dẫn xuất của mâm, phiên nấu, sự kiện

Có hai loại cột cần tách bạch.

**(a) Ảnh chụp ghi một lần.** Giá trị "tại thời điểm t", không đổi sau khi ghi:

| Cột | Giá trị nguồn (hiện hành) | Vì sao chụp lại | Cơ chế ghi một lần |
|---|---|---|---|
| `meal_plans.e_target_kcal` | E_mâm = E × s từ `profiles.kcal_target` và bữa (BR-NUT-04) | Nhật ký tuần (UC22, `v_journal_days`) so kcal đã ăn với mục tiêu **của ngày đó**; người dùng đổi mục tiêu sau thì lịch sử không được đổi theo | `trg_meal_plans_write_once` |
| `meal_plans.ranker_version_id`, `params_version` | Con trỏ triển khai, bộ tham số hiện hành | Truy được mô hình và tham số đã sinh mâm | `trg_meal_plans_write_once` |
| `meal_plan_items.rank_score`, `servings_scale` | Điểm của mô hình xếp hạng đang triển khai; tỉ lệ số người / khẩu phần | Mô hình đổi phiên bản (UC30); điểm là dữ liệu huấn luyện và đánh giá ngoại tuyến, phải là điểm đã dùng để chọn món | `trg_meal_plan_items_write_once` |
| `cook_sessions.burners` | `user_settings.burners` | Lịch nấu đã lập (`cook_schedule_entries`) chỉ đúng với số họng bếp lúc lập | `trg_cook_sessions_write_once` |
| `pantry_transactions.urgency_at_event` | Độ gấp u tính lúc đọc (BR-FRESH-05) | u thay đổi theo thời gian; nhật ký cần biết lô có gấp **khi được dùng** để đếm "lô gấp dùng kịp" | bảng chỉ ghi thêm, `trg_pantry_transactions_append_only` |
| `interactions.ranker_version_id`, `propensity` | `meal_plans.ranker_version_id`, xác suất hiển thị | Học từ log (off-policy) cần chính sách đã sinh ra lần hiển thị | bảng chỉ ghi thêm, `trg_interactions_append_only` |
| `audit_log.actor_role` | `users.role` | Bằng chứng kiểm toán phải ghi quyền tại thời điểm thao tác | bảng chỉ ghi thêm, `trg_audit_log_append_only` |

Ảnh chụp ghi một sự thật khác với cột nguồn ("giá trị tại t" chứ không phải "giá trị hiện tại"). Hai sự thật này được phép khác nhau, nên giữa chúng không có PTH; ví dụ cùng một người dùng có nhiều mâm với `e_target_kcal` khác nhau. Vì trigger từ chối mọi UPDATE đổi các cột này, không có đường làm lệch ảnh chụp với chính nó.

**(b) Giá trị dẫn xuất, tính lại có kiểm soát.** Các cột sau không phải ảnh chụp ghi một lần. UC17 (FR-17-12) và SD05 cập nhật chúng sau khi tạo mâm, khi người dùng chọn thay nguyên liệu:

| Cột | Dẫn xuất từ | Khi nào được tính lại |
|---|---|---|
| `meal_plan_items.kcal_per_person` | `recipe_nutrition.per_serving` × `servings_scale`, điều chỉnh theo `meal_plan_item_substitutions` của món | Trong cùng giao dịch ghi `meal_plan_item_substitutions` của món đó |
| `meal_plans.kcal_low`, `kcal_high` | Σ `kcal_per_person` của món `active` và nửa độ rộng hiệu chỉnh (BR-NUT-06) | Cùng giao dịch trên |
| `meal_plans.rice_bowls_per_person` | BR-TRAY-03 từ `e_target_kcal`, Σ `kcal_per_person`, E_bát | Cùng giao dịch trên |

Đây là dư thừa liên quan hệ (giá trị suy được từ bảng khác), được giữ vì mâm phải hiện đúng con số đã cho người dùng xem, kể cả khi `recipe_nutrition` được tính lại sau đó. Cơ chế giữ nhất quán:

1. **Một nơi ghi duy nhất.** Chỉ service `meal` (UC15 tạo mâm, UC16 đổi món, UC17 nhận thay thế) ghi các cột này. Nó tính lại cả ba nhóm trong cùng giao dịch với dòng `meal_plan_item_substitutions`.
2. **Chỉ ở trạng thái cho phép.** `trg_meal_plan_items_guard` từ chối đổi `kcal_per_person` khi món không `active` hoặc mâm không ở `proposed`/`accepted`. `trg_meal_plans_guard` làm tương tự cho `kcal_low`, `kcal_high`, `rice_bowls_per_person`. `trg_meal_plan_item_substitutions_guard` từ chối ghi thay thế khi mâm đã `cooked`, `abandoned` hoặc `expired`. Sau khi mâm được nấu, cả bộ giá trị đông cứng; đó là con số nhật ký dùng.
3. **Ràng buộc miền.** `ck_meal_plans_rice_bowls` (bát cơm trong [0,5; 3], bước 0,5), `ck_meal_plans_kcal_range`, `ck_meal_plan_items_kcal_per_person`.
4. **Kiểm thử.** Sau mỗi giao dịch của UC15–UC17, tính lại `kcal_per_person` từ `recipe_nutrition` và `meal_plan_item_substitutions` rồi so với giá trị lưu; tính lại `rice_bowls_per_person` theo BR-TRAY-03 rồi so.

**Phần cơm trong nhật ký.** E_mâm gồm cả cơm (BR-TRAY-03: số bát = (E_mâm − E_món) / E_bát), còn Σ `kcal_per_person` chỉ gồm món. `v_journal_days` vì vậy trả `kcal_dishes_per_person`, `rice_bowls_per_person` và `kcal_per_person` = món + bát × E_bát, để so với `e_target_kcal` mà không lệch hệ thống. E_bát hiện đọc từ tham số `tastoria.rice_bowl_kcal` (giá trị hiện hành). Muốn nhật ký đúng tuyệt đối khi E_bát đổi thì cần ảnh chụp E_bát theo mâm (`meal_plans.rice_kcal_per_bowl`, đề xuất ở mục 6).

### D3. `pantry_lots.p_*` — quan sát độ tươi mới nhất của lô

- **Dư thừa.** `p_tuoi`, `p_dung_som`, `p_dung_ngay`, `p_kiem_tra`, `freshness_observed_at`, `freshness_model_version_id` chép xác suất từ `detections` của lần quét gần nhất nhìn thấy lô.
- **Vì sao cần.** Không có đường khoá ngoại ổn định từ lô tới khung phát hiện mới nhất: `source_scan_item_id` chỉ trỏ lần quét **tạo** lô; các lần quét toàn tủ sau (BR-PANTRY-03) cập nhật lô có sẵn chứ không tạo lô mới. Lần quét cũ còn bị xoá theo vòng đời (UC32 xoá ảnh, UC07 xoá tài khoản, `ON DELETE SET NULL`). Độ gấp u (BR-FRESH-02, 03) phải tính được ở mỗi lần đọc kho mà không phụ thuộc lịch sử quét còn hay mất.
- **Giữ nhất quán.** Một dòng mỗi lô, nên không có bản chép thứ hai trong cùng bảng để lệch nhau. Các cột được ghi cùng nhau trong giao dịch xác nhận quét (`POST /scans/{id}/confirm`, BR-SCAN-02). CSDL ép tính nguyên khối của nhóm: `ck_pantry_lots_p_group` (bốn xác suất cùng NULL hoặc cùng có giá trị), `ck_pantry_lots_p_range`, `ck_pantry_lots_p_sum` (tổng 1, sai số 0,01), `ck_pantry_lots_p_observed` (có xác suất thì phải có thời điểm quan sát). u không lưu (BR-FRESH-05), nên không có cột thứ ba phải cập nhật theo.

### D4. `interactions` — `user_id` cùng khoá ngoại ghép tới `meal_plans` và `meal_plan_items`

- **Dư thừa.** `meal_plan_id → user_id` (chủ mâm), và `meal_plan_item_id → meal_plan_id, recipe_id`; bảng đạt 2NF.
- **Vì sao cần.** `meal_plan_id` cho phép NULL: sự kiện xem chi tiết món ngoài mâm (`viewed`, `liked`) không có mâm nhưng vẫn phải thuộc một người, để (a) ghi đồng ý `personalization` theo người (BR-CONSENT-03), (b) xoá theo người khi rút đồng ý hoặc xoá tài khoản (`ON DELETE CASCADE` từ `users`), (c) truy vấn huấn luyện theo người dùng có chỉ mục `(user_id, occurred_at)`. `recipe_id` cũng NOT NULL vì cùng lý do và vì nhãn học là (người, món).
- **Giữ nhất quán.** Cả hai PTH bắc cầu đều do CSDL ép. (1) Khoá ngoại ghép `(meal_plan_id, user_id) → meal_plans (id, user_id)` từ chối mọi dòng có `user_id` khác chủ mâm. (2) Khoá ngoại ghép `(meal_plan_item_id, meal_plan_id, recipe_id) → meal_plan_items (id, meal_plan_id, recipe_id)` (đích là siêu khoá `uq_meal_plan_items_id_meal_plan_id_recipe_id`) buộc mâm và món của sự kiện khớp dòng món; khi dòng món bị xoá, chỉ `meal_plan_item_id` được đặt NULL (`ON DELETE SET NULL (meal_plan_item_id)`). `ck_interactions_item_needs_plan` chặn trường hợp có dòng món mà không có mâm, để `MATCH SIMPLE` không bỏ qua kiểm tra. Bảng chỉ ghi thêm (`trg_interactions_append_only`; chống trùng theo `id` = `event_id`).

### D5. Cột jsonb: `idempotency_keys.response_body`, `model_versions.metrics`

- **Vấn đề 1NF.** jsonb có thể chứa cấu trúc lồng; nếu CSDL truy vấn hay ràng buộc theo thành phần bên trong thì cột không còn nguyên tố.
- **Vì sao chấp nhận.** Cả hai được dùng nguyên khối. `response_body` là phản hồi HTTP đã gửi, chỉ để trả lại nguyên văn khi client gửi lại cùng `Idempotency-Key` (so `request_sha256` trước); không truy vấn, không chỉ mục, xoá sau 48 giờ (UC34). `metrics` là báo cáo đánh giá của một phiên bản mô hình (mAP, độ chính xác theo lớp, kết quả kiểm định thống kê), khác cấu trúc giữa bốn loại mô hình; cổng kiểm định đọc cả tài liệu trong mã, CSDL không lọc theo trường. Với cách dùng đó, mỗi giá trị là một phần tử nguyên tố của miền "tài liệu", và 1NF giữ được.
- **Ranh giới.** Mọi thứ cần lọc, nối hoặc ràng buộc đều có cột riêng: `status_code`, `request_sha256`; `model_versions.status`, `name`, `version`, `sha256`. Khi một chỉ số trong `metrics` cần dùng để lọc (ví dụ chọn mô hình theo mAP) thì phải tách thành cột, không truy vấn vào jsonb.

### D6. `recipes UNIQUE (id, slot)` và khoá ngoại ghép từ `meal_plan_items`

- **Dư thừa.** `meal_plan_items.slot` chép `recipes.slot`: `recipe_id → slot` với `recipe_id` không phải khoá của `meal_plan_items`, nên bảng đạt 2NF.
- **Vì sao cần.** Luật "mỗi slot của mâm có đúng một món đang dùng" (BR-TRAY-01, BR-SWAP-01) là chỉ mục duy nhất một phần `UNIQUE (meal_plan_id, slot) WHERE status = 'active'`. PostgreSQL không cho chỉ mục trải trên hai bảng, nên `slot` phải có mặt ở `meal_plan_items`.
- **Giữ nhất quán.** Khoá ngoại ghép `(recipe_id, slot) → recipes(id, slot)` buộc `slot` của dòng mâm bằng `slot` của món. `UNIQUE (id, slot)` trên `recipes` là siêu khoá thêm vào chỉ để làm đích khoá ngoại. Hai phía đều không đổi được: `trg_recipes_guard` từ chối sửa mọi cột của món đã `published` hoặc `retired` (món `draft` chưa thể có trong mâm vì service chỉ chọn món `published`), và `trg_meal_plan_items_write_once` từ chối đổi `slot`, `recipe_id` của dòng mâm. Không có `ON UPDATE CASCADE`. Vì vậy không thể đổi slot ở một nơi mà quên nơi kia.

### D7. `refresh_tokens.user_id` cùng `family_id`

- **Dư thừa.** `family_id → user_id`; bảng đạt 2NF.
- **Vì sao cần.** Đăng xuất mọi thiết bị (UC03) và xoá tài khoản (UC07) thu hồi token theo `user_id` bằng một câu lệnh có chỉ mục; phát hiện tái sử dụng token (NFR-SEC-01) thu hồi theo `family_id`. Dạng chuẩn đầy đủ cần bảng họ token `(family_id → user_id)`, không có trong `model.yaml` (đề xuất ở mục 6).
- **Giữ nhất quán.** `family_id` sinh mới ở lần đăng nhập; token xoay vòng chép `family_id` và `user_id` từ token trước trong cùng giao dịch `POST /auth/refresh`. Sau khi ghi, `trg_refresh_tokens_write_once` từ chối đổi `user_id`, `family_id`, `token_sha256`, `issued_at`, `expires_at`; chỉ `revoked_at`, `replaced_by_id`, `user_agent` đổi được. Mỗi token được thay tối đa một lần (`uq_refresh_tokens_replaced_by_id`). Kiểm thử: truy vấn `family_id` có hơn một `user_id` phải trả 0 dòng.

### D8. `dsr_requests.subject_ref` và dữ liệu còn lại sau khi xoá tài khoản

- **Dư thừa.** `subject_ref = HMAC-SHA256(khoá, user_id)`, nên `user_id → subject_ref` khi `user_id` khác NULL (N1); bảng đạt 2NF.
- **Vì sao cần.** Sau khi xoá tài khoản (UC07), `user_id` bị đặt NULL (`ON DELETE SET NULL`) nhưng bằng chứng đã xử lý yêu cầu phải còn (BR-DSR-01, NĐ 356/2025). `subject_ref` cho phép trả lời "yêu cầu của người có định danh X đã được xử lý chưa" khi người đó (hoặc cơ quan quản lý) đưa ra định danh.
- **Bản chất dữ liệu.** `subject_ref` là **dữ liệu cá nhân đã bí danh hoá**, không phải dữ liệu ẩn danh. Người giữ khoá HMAC tính lại được nó từ `user_id`, nên nó vẫn là dữ liệu cá nhân (spec v2, bảng thay đổi mục 22). Căn cứ giữ lại là nghĩa vụ chứng minh tuân thủ, không phải đồng ý. Vì vậy nó phải có thời hạn lưu xác định và job xoá. Đề xuất: giữ `dsr_requests` và `audit_log` 24 tháng kể từ `completed_at` / `created_at`, sau đó job định kỳ xoá dòng (chạy với `tastoria.erasure`). Thời hạn chính thức chưa được chốt ở `07-danh-gia-tac-dong-du-lieu-ca-nhan.md` mục 9 (mục 6, đề xuất 5).
- **Dữ liệu sót trong `audit_log`.** Khi xoá cứng, chỉ `audit_log.actor_user_id` được đặt NULL. `entity_id` (text) của các dòng ghi thao tác trên chính tài khoản đó (ví dụ giải mã `profiles` có `entity_id` = `user_id`) vẫn giữ định danh gốc. Giao dịch xoá của UC07 (AD05) vì vậy phải, trước khi `DELETE FROM users`, chạy `UPDATE audit_log SET entity_id = 'hmac:' || <HMAC(user_id)> WHERE entity_id = <user_id>::text OR entity_id IN (<id các bản ghi của người đó>)`, trong cùng giao dịch có `SET LOCAL tastoria.erasure = 'on'` (trigger chỉ ghi thêm cho phép bước này khi cờ bật). Phương án sạch hơn là cột `audit_log.subject_ref` riêng (mục 6, đề xuất 5). Việc bổ sung bước này vào UC07, AD05 và 07 mục 9 thuộc các tệp đó.
- **Giữ nhất quán.** Giá trị tính một lần khi tạo yêu cầu từ `user_id` của phiên đăng nhập. `trg_dsr_requests_guard` từ chối đổi `subject_ref`, `type`, `received_at`, và chỉ cho `user_id` đổi thành NULL. Hàm HMAC tất định nên cùng người luôn cho cùng giá trị. Nếu xoay khoá HMAC, các yêu cầu cũ giữ giá trị cũ (bằng chứng lịch sử) và tài liệu vận hành ghi phiên bản khoá.

### D9. `user_id` ở bảng có khoá ngoại tới thực thể đã thuộc người dùng: `pantry_lots`, `shopping_items`

- **Dư thừa.** `pantry_lots.source_scan_item_id → user_id` (chip thuộc lần quét của chủ lô); `shopping_items.source_meal_plan_item_id → user_id` (qua mâm). Hai bảng đạt 2NF.
- **Vì sao cần.** Cả hai khoá ngoại nguồn đều cho phép NULL và `ON DELETE SET NULL`: lô nhập tay, dòng đi chợ thêm tay không có nguồn; lô và dòng đi chợ sống lâu hơn lần quét hay mâm sinh ra chúng. Chủ sở hữu vì vậy phải là thuộc tính riêng của dòng, dùng cho lọc chống BOLA ở mọi truy vấn theo `{id}`, cho chỉ mục `(user_id, status)` và cho xoá theo người (`ON DELETE CASCADE`).
- **Giữ nhất quán.** `user_id` lấy từ phiên đăng nhập và ghi một lần khi tạo dòng; `trg_pantry_lots_write_once`, `trg_shopping_items_write_once` từ chối đổi nó. Service kiểm nguồn thuộc cùng người trước khi ghi (`scans.user_id`, `meal_plans.user_id`). CSDL chưa ép điểm này bằng khoá ngoại ghép vì `scan_items` và `meal_plan_items` không mang `user_id` (mục 6, đề xuất 7).

### D10. `scan_items.model_count`

- **Dư thừa.** Số đếm của mô hình suy ra từ các `detections` gắn chip, gộp theo BR-SCAN-01 (cùng `shelf_group` lấy max giữa các ảnh, khác ngăn thì cộng).
- **Vì sao cần.** Người dùng sửa chip (gán lại nhãn, xoá, thêm) thì `detections.scan_item_id` bị đổi hoặc đặt NULL, và ảnh bị xoá sau 30 ngày (BR-RETAIN-01). So sánh "mô hình đếm bao nhiêu, người dùng sửa thành bao nhiêu" (`model_count` với `final_count`) là dữ liệu đánh giá mô hình, phải giữ đúng con số lúc suy luận.
- **Giữ nhất quán.** Worker ghi một lần khi tạo chip từ kết quả suy luận. `trg_scan_items_write_once` từ chối đổi `scan_id`, `origin`, `model_count`; API sửa chip chỉ ghi `final_count`, `qty_level`, `user_action`, `ingredient_id`, `original_ingredient_id`, `user_freshness`. Đây là ảnh chụp đầu ra mô hình, không phải giá trị phải bám theo `detections` sau khi người dùng sửa.

### D11. `survey_assignments.is_anchor`

- **Dư thừa.** `is_anchor` = có `(form_id của người tham gia, recipe_id)` trong `survey_form_anchors`.
- **Vì sao cần.** Xuất kết quả khảo sát (UC24) và mô hình khối không đầy đủ dùng cờ này trên từng dòng phân công; tránh nối ba bảng ở mỗi lần xuất.
- **Giữ nhất quán.** Phân công sinh một lần khi người tham gia bắt đầu, từ phiếu đang mở; `trg_survey_assignments_write_once` từ chối đổi `is_anchor`, `recipe_id`, `display_order`. Nguồn cũng không đổi: `trg_survey_form_anchors_guard` từ chối thêm, sửa, xoá món neo khi phiếu đã mở hoặc đã có người tham gia. Đổi bộ neo là tạo phiếu phiên bản mới (`survey_forms.version` duy nhất).

### D12. Ràng buộc mẫu hằng trong một bộ (quy ước N2)

Các ràng buộc dưới đây chỉ liên quan tới cột của cùng một dòng và có vế phải là hằng hoặc trạng thái NULL. Theo N2 (mục 2) chúng không được tính khi xét 2NF–BCNF, với điều kiện mỗi ràng buộc được ép bằng `CHECK`. Bảng liệt kê đủ để người đọc thấy quy ước được áp như nhau ở mọi bảng.

| Bảng | Ràng buộc | CHECK | Căn cứ |
|---|---|---|---|
| `survey_ratings` | `never_eaten = (rating IS NULL)`: "chưa từng ăn" là lựa chọn tường minh, khác "chưa trả lời" (không có dòng) | `ck_survey_ratings_1` | UC23 |
| `profiles` | `kcal_source = expert` ⇔ `goal = expert` (khi đã có `kcal_source`) | `ck_profiles_expert` | BR-NUT-03 |
| `profiles` | `kcal_target`, `kcal_source` cùng có hoặc cùng trống | `ck_profiles_kcal_pair` | BR-NUT-01..04 |
| `profiles` | có cột `*_enc` ⇒ có `enc_key_id` | `ck_profiles_enc_key` | NFR-PRIV-01 |
| `scan_items` | `user_action = relabeled` ⇒ có `original_ingredient_id`; có `original_ingredient_id` ⇒ `origin = model` và khác `ingredient_id`; `origin = user_added` ⇒ `model_count` NULL và không `deleted` | `ck_scan_items_relabeled`, `ck_scan_items_original`, `ck_scan_items_user_added` | FR-13-03, FR-13-06 |
| `scans` | `status = confirmed` ⇔ có `confirmed_at` | `ck_scans_confirmed` | BR-SCAN-02 |
| `cook_sessions` | `status = completed` ⇔ có `completed_at` và chưa có `reverted_at`; `status = reverted` ⇔ có `reverted_at` | `ck_cook_sessions_completed`, `ck_cook_sessions_reverted` | BR-COOK-02, BR-PANTRY-02 |
| `pantry_transactions` | `reason = undo` ⇔ có `reverses_id`; `ref_type`, `ref_id` cùng có hoặc cùng trống | `ck_pantry_transactions_undo`, `ck_pantry_transactions_ref_pair` | BR-PANTRY-02 |
| `pantry_lots`, `detections` | bốn xác suất độ tươi cùng NULL hoặc cùng có giá trị, tổng 1 | `ck_pantry_lots_p_group`, `ck_pantry_lots_p_sum`, `ck_detections_p_group`, `ck_detections_p_sum` | BR-FRESH-02 |
| `ingredients` | `comp_source_id`, `comp_source_code` cùng có hoặc cùng trống | `ck_ingredients_comp_pair` | BR-NUT-05 |
| `meal_plans` | `kcal_low`, `kcal_high` cùng có hoặc cùng trống | `ck_meal_plans_kcal_pair` | BR-NUT-06 |
| `interactions` | có `meal_plan_item_id` ⇒ có `meal_plan_id`; có `swap_reason` ⇒ `type = swapped` | `ck_interactions_item_needs_plan`, `ck_interactions_swap_reason` | BR-SWAP-01 |

`survey_ratings.never_eaten` vẫn là một bit dư thừa (suy được từ `rating`). Nó được giữ vì làm ý nghĩa "chưa từng ăn" hiển nhiên khi xuất dữ liệu và khi tính tỉ lệ món lạ; `CHECK` làm CSDL từ chối mọi dòng hai cột mâu thuẫn.

### D13. `pantry_transactions (ref_type, ref_id)` — tham chiếu đa hình

- **Phi chuẩn hoá.** `ref_id` trỏ tới `scans.id`, `cook_sessions.id` hoặc `users.id` tuỳ `ref_type`, nên không khai được khoá ngoại. CSDL vì vậy không tự bảo đảm `ref_id` trỏ bản ghi có thật hay đúng chủ, dù nghiệp vụ dựa trực tiếp vào cặp này: hoàn tác (UC21, SD06) tìm giao dịch theo `(ref_type = 'cook_session', ref_id)`, và `v_journal_days` nối `ref_id` với phiên nấu.
- **Vì sao chưa tách.** Dạng chuẩn là các cột khoá ngoại tường minh (`cook_session_id`, `scan_id`, có thể NULL) kèm `CHECK (num_nonnulls(...) <= 1)`. `model.yaml` chưa có các cột đó (mục 6, đề xuất 4); `ref_type = user` cũng không cần cột riêng vì `users.id` chính là chủ lô.
- **Giữ nhất quán (đến khi tách).** `ck_pantry_transactions_ref_pair` buộc hai cột cùng có hoặc cùng trống. `trg_pantry_transactions_ref` (BEFORE INSERT) kiểm `ref_id` tồn tại trong bảng đúng loại và thuộc chủ lô: `scans.user_id`, `meal_plans.user_id` qua phiên nấu, hoặc chính `pantry_lots.user_id` với `ref_type = user`. Trigger này cũng kiểm giao dịch đảo cùng lô với giao dịch bị đảo. Vì bảng chỉ ghi thêm, kiểm lúc INSERT là đủ. Đối tượng được trỏ chỉ bị xoá khi xoá tài khoản (dây chuyền từ `users`), lúc đó các giao dịch của lô cũng bị xoá theo, nên không còn tham chiếu treo trong dữ liệu đang dùng. Chỉ mục `ix_pantry_transactions_ref (ref_type, ref_id)` phục vụ hoàn tác và nhật ký (không quét toàn bảng).

### Hiệu năng của view trên đường nóng

- `v_pantry_lot_balance` gộp giao dịch bằng `CROSS JOIN LATERAL` theo từng lô. Điều kiện `l.user_id = $1` vì vậy được áp trước, và mỗi lô chỉ đọc giao dịch của nó qua `ix_pantry_transactions_lot_id`. Bản trước gộp toàn bộ `pantry_transactions` trong một subquery `GROUP BY` mà điều kiện người dùng không đẩy xuống được.
- `v_journal_days` không dùng CTE. Hai nhánh gộp theo `(user_id, local_date)` là subquery thường, nên điều kiện `user_id = $1` đẩy xuống cả hai nhánh (truy theo `ix_meal_plans_user_id_created_at`, `ux_cook_sessions_one_live`, `ix_pantry_transactions_ref`). Bản trước tham chiếu CTE hai lần nên CTE bị vật chất hoá, quét mọi phiên của mọi người trước khi lọc.
- Kế hoạch kiểm thử hiệu năng (NFR-PERF-02) cần chạy `EXPLAIN (ANALYZE, BUFFERS)` cho `SELECT * FROM v_pantry_lot_balance WHERE user_id = $1` và `SELECT * FROM v_journal_days WHERE user_id = $1 AND local_date BETWEEN $2 AND $3` trên dữ liệu cỡ đích, và chặn mọi `Seq Scan` trên `pantry_transactions`, `cook_sessions`. Kế hoạch đã kiểm trên CSDL trống ở mục 7.

### Chỉ mục phục vụ xoá dây chuyền và tác vụ định kỳ

| Chỉ mục | Phục vụ |
|---|---|
| `ix_audit_log_actor_user_id`, `ix_dsr_requests_user_id`, `ix_password_resets_user_id`, `ix_interactions_meal_plan_id_user_id`, `ix_interactions_meal_plan_item_id` | `ON DELETE SET NULL` / `CASCADE` khi xoá cứng tài khoản (UC07); lọc nhật ký theo nhân sự (UC27) |
| `ix_detections_scan_item_id`, `ix_pantry_lots_source_scan_item_id` | `ON DELETE SET NULL` khi xoá chip (UC13) hoặc lần quét |
| `ix_meal_plan_pins_lot_id`, `ix_shopping_items_source_meal_plan_item_id` | `ON DELETE CASCADE` / `SET NULL` từ lô và món trong mâm |
| `ix_idempotency_keys_created_at`, `ix_refresh_tokens_expires_at`, `ix_password_resets_expires_at`, `ix_scans_stuck` (một phần, `status IN ('queued','processing')`) | Job dọn (UC34) |
| `ix_scan_images_purge` (một phần, `purged_at IS NULL AND NOT contributed`) | Job xoá ảnh quá hạn (UC32, BR-RETAIN-01) |
| `ix_pantry_transactions_ref` | Hoàn tác (UC21), nhật ký (UC22) |

`ix_scan_images_scan_id` đã bỏ: chỉ mục của `uq_scan_images_scan_id_ordinal (scan_id, ordinal)` có `scan_id` là cột dẫn đầu.

## 5. Phép tách từ lược đồ v1

Lược đồ v1 (tài liệu thiết kế 14/10/2026, mục 6.4) có ba quan hệ không đạt dạng chuẩn. Dưới đây là PTH đã buộc tách và kết quả ở v2.

### 5.1. v1 `recipes`

v1: `recipes(id, name, slot, servings, total_min, method, flavor_tags, kcal, protein, glucid, lipid, fiber, steps)`.

| Vấn đề | PTH / vi phạm | Tách thành (v2) |
|---|---|---|
| `flavor_tags` chứa danh sách thẻ | Thuộc tính đa trị: vi phạm 1NF | `recipe_tags(recipe_id, tag_code)` + `tags(code → kind, name_vi)`. Nếu giữ tên thẻ và loại thẻ trong món sẽ có `tag → kind` lặp ở mọi món |
| `steps` chứa danh sách bước | Nhóm lặp (mỗi bước có nội dung, số phút, chủ động/thụ động, chiếm bếp): vi phạm 1NF | Thực thể yếu `recipe_steps(recipe_id, step_no → text_vi, kind, minutes, uses_burner)`; lịch nấu CP-SAT (BR-COOK-01) và `cook_schedule_entries` trỏ được tới từng bước bằng khoá ngoại ghép `(recipe_id, step_no)` |
| `total_min` | Dẫn xuất từ các bước (`steps → total_min`, và thực chất phụ thuộc số họng bếp khi nấu song song) | Bỏ, không lưu; tính lúc đọc |
| `kcal, protein, glucid, lipid, fiber` | `{nguyên liệu và lượng của món} × {bảng thành phần} → dinh dưỡng`: dư thừa liên quan hệ; năm cột cố định là nhóm lặp theo chất | `recipe_nutrition(recipe_id, nutrient_code → per_serving, …)` với `nutrients(code → name_vi, unit)`; giữ có kiểm soát ở D1, thêm chất mới không đổi lược đồ |
| `method` là chuỗi tự do | `method → tên hiển thị` lặp ở mọi món | `cooking_methods(code → name_vi)`, khoá ngoại `recipes.method_code` (cũng là ngữ cảnh của `substitution_pairs`) |

Kết quả: `recipes(id → name_vi, slot, servings, method_code, status, notes, created_at, updated_at)` đạt BCNF.

### 5.2. v1 `detections`

v1: `detections(scan_id, ingredient_id, bbox, confidence, count, p_wilted, corrected_ingredient_id)`; mỗi dòng là một khung phát hiện.

| Vấn đề | PTH / vi phạm | Tách thành (v2) |
|---|---|---|
| `count` | `(scan_id, ingredient_id) → count`: số đếm là của **nhóm** nguyên liệu trong lần quét, không của từng khung. Khoá của quan hệ là khung, nên đây là PTH có vế trái không phải siêu khoá (vi phạm 3NF; số đếm lặp ở mọi khung cùng loại, sửa một khung thì lệch) | Chip `scan_items(id → scan_id, ingredient_id, model_count, final_count, qty_level, …)`; khung trỏ chip qua `detections.scan_item_id` |
| `corrected_ingredient_id` | `(scan_id, ingredient_id) → corrected_ingredient_id`: người dùng sửa chip, không sửa từng khung; cùng vi phạm như trên | `scan_items.original_ingredient_id`, `user_action`, `ingredient_id` (nhãn cuối) |
| `ingredient_id` trên khung | Mô hình dự đoán **lớp thị giác**, không dự đoán nguyên liệu; một lớp ứng nhiều nguyên liệu (`vision_class → {ingredient}`), lớp của khung là đầu ra cố định của mô hình | `detections.vision_class_id` + `vision_class_ingredients`; bản đồ chỉ số lớp theo phiên bản ở `model_version_classes` |
| `bbox` | Giá trị ghép bốn số: vi phạm 1NF nếu lưu một chuỗi/mảng | `x1, y1, x2, y2` với CHECK miền [0, 1] |
| `scans.image_key` (liên quan) | Một lần quét có 1–2 ảnh: nhóm lặp | `scan_images(id; scan_id, ordinal → storage_key, shelf_group, …)`, khung trỏ ảnh qua `scan_image_id` |
| `p_wilted` | Một xác suất thay cho phân phối bốn lớp độ tươi | `p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra` (BR-FRESH-02) |

Kết quả: `detections(id → scan_image_id, scan_item_id, vision_class_id, x1, y1, x2, y2, confidence, p_*)` và `scan_items` đều đạt BCNF.

### 5.3. v1 `pantry_items`

v1: `pantry_items(user_id, ingredient_id, qty, unit, first_seen_at, urgency, source_scan_id)`, một dòng cho mỗi (người dùng, nguyên liệu).

| Vấn đề | PTH / vi phạm | Tách thành (v2) |
|---|---|---|
| `urgency` | `urgency` = f(`first_seen_at`, `ingredients.shelf_life_days`, xác suất độ tươi, **thời điểm hiện tại**): dẫn xuất, và phụ thuộc thời gian nên lưu lại là sai ngay hôm sau | Bỏ; u tính lúc đọc (BR-FRESH-01..05) từ `acquired_at`, `shelf_life_days`, `p_*` |
| Khoá `(user_id, ingredient_id)` với `first_seen_at`, `source_scan_id` | Hai lần mua cùng một nguyên liệu ở hai ngày có hai ngày mua khác nhau, nhưng khoá chỉ cho một dòng: `(user_id, ingredient_id) → first_seen_at` là PTH sai về nghiệp vụ, buộc gộp và làm mất thông tin độ gấp của lô cũ | `pantry_lots(id → user_id, ingredient_id, acquired_at, acquired_basis, initial_g_min, initial_g_max, status, …)`: mỗi lần thêm một lô (BR-PANTRY-01) |
| `qty` | Lượng hiện tại là trạng thái tích luỹ từ các lần thêm, trừ khi nấu, sửa tay; ghi đè `qty` làm mất lịch sử và không hoàn tác được (BR-PANTRY-02) | `pantry_transactions(id → lot_id, delta_g_min, delta_g_max, reason, …)` chỉ ghi thêm; lượng hiện tại = view `v_pantry_lot_balance` |
| `qty, unit` đơn vị tự do | `(ingredient_id, unit) → gam/đơn vị` lặp ở mọi dòng kho; hai đơn vị khác nhau cho cùng nguyên liệu không cộng được | Đơn vị chuẩn là gam dạng khoảng `[g_min, g_max]` (BR-QTY-01); quy đổi qua `ingredient_units(ingredient_id, unit_code → grams_per_unit)` và `qty_levels(food_group_code, level → g_min, g_max)` (BR-QTY-02) |

Kết quả: `pantry_transactions` đạt BCNF; `pantry_lots` đạt 2NF chỉ vì `user_id` và quan sát độ tươi mới nhất, cả hai có kiểm soát (D3, D9).

## 6. Đề xuất bổ sung mô hình

Các thay đổi dưới đây cần sửa `model.yaml` (thêm cột hoặc bảng), nên chưa đưa vào `db/schema.sql`. Ghi lại để quyết định; những ràng buộc không cần cột mới (UNIQUE, CHECK, khoá ngoại ghép, chỉ mục một phần, trigger) đã có trong DDL.

1. **Dòng dõi phiên bản món** (BR-CATALOG-01): `recipes.supersedes_id uuid NULL` khoá ngoại tới `recipes(id)`, `UNIQUE`. Thiếu cột này thì `user_favorite_recipes`, `survey_ratings`, `interactions` không nối được bản cũ với bản mới của cùng một món, nên gu học được bị đứt khi món đổi bản. Phương án khác: `family_id uuid NOT NULL` + `version smallint`, `UNIQUE (family_id, version)`.
2. **Ảnh chụp E_bát theo mâm** (BR-TRAY-03, D2): `meal_plans.rice_kcal_per_bowl numeric NULL`. Khi có cột này, `v_journal_days.kcal_per_person` dùng nó thay cho tham số hiện hành `tastoria.rice_bowl_kcal`.
3. **Bảng tham số có phiên bản** (SRS và spec v2 §4: "tham số in đậm nằm trong bảng cấu hình"): `param_sets(version text PK, params jsonb NOT NULL, created_at timestamptz NOT NULL, is_active bool NOT NULL)`, chỉ mục duy nhất một phần trên `is_active`, và khoá ngoại `meal_plans.params_version → param_sets(version)`. Hiện `params_version` là tham chiếu treo; view đọc tham số qua `app_param()` (GUC cấp CSDL). Nếu nhóm chọn giữ tham số trong tệp cấu hình thì phải sửa câu tương ứng trong SRS và spec, và mô tả cách lưu phiên bản của tệp.
4. **Khoá ngoại tường minh cho giao dịch kho** (D13): `pantry_transactions.cook_session_id uuid NULL` khoá ngoại tới `cook_sessions(id)` `ON DELETE CASCADE`, `scan_id uuid NULL` khoá ngoại tới `scans(id)` `ON DELETE SET NULL`, `CHECK (num_nonnulls(cook_session_id, scan_id) <= 1)`; bỏ `ref_type`, `ref_id`.
5. **Bí danh hoá trong nhật ký kiểm toán và thời hạn lưu** (D8): `audit_log.subject_ref bytea NULL` (HMAC của chủ thể), để không phải ghi đè `entity_id` khi xoá tài khoản. Chốt thời hạn lưu `dsr_requests`, `audit_log` ở 07 mục 9 (đề xuất 24 tháng) và thêm job xoá vào UC34 hoặc một tác vụ mới.
6. **Bảng họ token** `refresh_token_families(id, user_id, created_at)` nếu muốn `refresh_tokens` đạt BCNF (D7).
7. **Chủ sở hữu ở D9**: ép bằng khoá ngoại ghép cần thêm `user_id` vào `scan_items` và `meal_plan_items` (chính là thêm dư thừa ở chỗ khác). Khuyến nghị giữ kiểm ở service và thêm kiểm thử.
8. **`meal_plan_pins`**: khoá ngoại ghép tới `pantry_lots (id, user_id)` cần `meal_plan_pins.user_id`; tương tự, khuyến nghị kiểm ở service ("tối đa 2 lô", "lô ghim thuộc chủ mâm", BR-TRAY-08).
9. Nếu coi tiêu đề trang là thuộc tính cố định của URL: tách `sources(url → title)` khỏi `recipe_sources`.
10. **Đồng bộ ký hiệu trong `model.yaml`**: `recipes.name_vi` và `ingredients.name_vi` đang ghi `UQ`; DDL dùng chỉ mục duy nhất một phần (`WHERE status <> 'retired'`, `WHERE is_active`). Các CHECK, UNIQUE và trigger mới ở mục 4 nên được ghi vào `model.yaml` (`columns` CK, `unique`, `unique_partial`, `notes`) để mô hình và DDL cùng một nguồn.

## 7. Kiểm tra đã chạy

- `docs/sad/tools/test_ddl.sh`: áp `db/schema.sql` trên PostgreSQL 18 + pgvector, 62 bảng, 3 view, 393 cột khớp `model.yaml`, 0 chỗ lệch.
- Kiểm hành vi trên CSDL tạm (kịch bản SQL, không nằm trong repo): mỗi ràng buộc và trigger ở mục 4 được thử một lần vi phạm (bị từ chối) và một lần hợp lệ (chạy được). Gồm: sửa nguyên liệu/bước của món `published`, xoá món đã công bố, tạo bản mới cùng tên sau khi chuyển `retired`; nửa khoá thành phần; `kcal_source = expert` với `goal = lose`; múi giờ không hợp lệ; nhóm `p_*` thiếu hoặc tổng khác 1; đổi chủ lô; `ref_id` sai chủ hoặc không tồn tại; giao dịch đảo hai lần; phiên nấu thứ hai khi đã có phiên đang nấu; tính lại kcal khi mâm đã `cooked`; sửa/xoá bảng chỉ ghi thêm; xoá tài khoản khi chưa bật `tastoria.erasure` (bị chặn) và khi đã bật (xoá dây chuyền, `audit_log.actor_user_id` thành NULL). Hai sự kiện đồng ý trong cùng giao dịch cho `v_current_consents` đúng sự kiện sau. `v_journal_days` gán phiên hoàn tất lúc 2026-10-12T17:30Z vào ngày 2026-10-13 theo `Asia/Ho_Chi_Minh` (FR-22-02).
- `EXPLAIN` của `v_journal_days WHERE user_id = $1` và `v_pantry_lot_balance WHERE user_id = $1`: mọi bảng truy qua chỉ mục, không có `Seq Scan` trên `pantry_transactions` hay `cook_sessions`.
- Mọi tệp `docs/erd/*.puml` render bằng `docs/sad/tools/render.sh` (mã thoát 0, SVG không chứa "Syntax Error").
- ERD01–08 sinh từ `db/schema.sql` bằng script: 62/62 bảng xuất hiện đầy đủ cột đúng một lần; tên cột, kiểu, NOT NULL, PK, UNIQUE, chỉ mục duy nhất một phần khớp DDL; 97/97 khoá ngoại có mặt ở ERD01–07 và ở ERD08.
- Khoá chính trong mục 3 được đối chiếu tự động với `PRIMARY KEY` của DDL; vế phải của PTH "khoá → các cột còn lại" sinh từ danh sách cột của DDL. `db/schema_vp.sql` sinh lại từ `db/schema.sql` và áp được trên PostgreSQL thuần.
