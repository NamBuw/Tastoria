# Từ điển dữ liệu Tastoria

> Tệp sinh tự động bởi `db/gen_dictionary.py` từ catalog PostgreSQL sau khi áp `db/schema.sql`. Không sửa tay: sửa `COMMENT ON` hoặc DDL trong `db/schema.sql`, hoặc phân loại, thời hạn lưu, luật service trong `db/dictionary_meta.py`, rồi chạy lại script.

- Máy chủ: PostgreSQL 18.6 (Debian 18.6-1.pgdg12+2); extension: citext 1.8, pgcrypto 1.4, vector 0.8.7.
- Quy mô: 62 bảng, 393 cột, 3 view, 38 kiểu liệt kê; 62 khoá chính, 97 khoá ngoại, 21 ràng buộc UNIQUE, 79 ràng buộc CHECK, 38 chỉ mục bổ sung (trong đó 7 chỉ mục một phần), 27 trigger.
- Cột **NULL**: `NOT NULL` là bắt buộc; `NULL` là được phép trống. Cột **Ràng buộc** ghi PK, UNIQUE, FK (kèm hành động ON DELETE; không ghi là NO ACTION) và CHECK một cột; ràng buộc nhiều cột ghi dưới bảng.
- Cột **Phân loại** theo NĐ 356/2025: Không phải DLCN; DLCN cơ bản; DLCN nhạy cảm; Bí danh (vẫn là DLCN); Bí mật xác thực; Ẩn danh trong hệ thống. Định nghĩa ở `db/dictionary_meta.py`; thời hạn lưu theo `07-danh-gia-tac-dong-du-lieu-ca-nhan.md` mục 9.
- Cột `numeric` không khai precision/scale: đơn vị và miền ghi ở cột Ý nghĩa và ở CHECK. Quy mô ước lượng là giả định thiết kế cho bản thử 1.000 người dùng trong 1 năm, kho 200 món; dùng để chọn chỉ mục, không phải số đo.
- Nhóm bảng theo module của modular monolith (`docs/sad/model.yaml`). Ghi chú thiết kế lấy từ trường `notes` của mô hình.

## Mục lục

- **M01 core**: `idempotency_keys`
- **M02 identity**: `users`, `refresh_tokens`, `password_resets`
- **M03 privacy**: `consent_purposes`, `policy_versions`, `consent_events`, `dsr_requests`, `audit_log`, `v_current_consents`
- **M04 catalog**: `food_groups`, `nutrient_sources`, `food_items`, `nutrients`, `food_nutrients`, `allergen_groups`, `diets`, `diet_exclusions`, `ingredients`, `ingredient_synonyms`, `ingredient_allergens`, `ingredient_units`, `qty_levels`, `cooking_methods`, `tags`, `recipes`, `recipe_ingredients`, `recipe_steps`, `recipe_tags`, `recipe_sources`, `recipe_nutrition`, `vision_classes`, `vision_class_ingredients`
- **M05 profile**: `profiles`, `user_allergens`, `user_favorite_recipes`, `user_settings`
- **M06 pantry**: `pantry_lots`, `pantry_transactions`, `v_pantry_lot_balance`
- **M07 mlops**: `model_versions`, `model_version_classes`, `model_deployments`
- **M08 scan**: `scans`, `scan_images`, `scan_items`, `detections`
- **M09 events**: `interactions`
- **M10 substitute**: `substitution_pairs`, `ingredient_embeddings`, `shopping_items`
- **M11 meal**: `meal_plans`, `meal_plan_coeater_allergens`, `meal_plan_pins`, `meal_plan_items`, `meal_plan_item_substitutions`
- **M12 cooking**: `cook_sessions`, `cook_schedule_entries`
- **M13 journal**: `v_journal_days`
- **M14 survey**: `survey_forms`, `survey_form_anchors`, `survey_respondents`, `survey_assignments`, `survey_ratings`, `survey_favorites`

## Ánh xạ máy trạng thái sang lược đồ

Máy trạng thái trong `model.yaml` có một số trạng thái không là giá trị của cột enum nào:

| Thực thể | Cách biểu diễn trong CSDL |
|---|---|
| users (tài khoản) | active, deletion_requested: giá trị users.status. locked: suy ra, users.locked_until > now() (khoá tạm 15 phút, NFR-SEC-02), không có giá trị enum riêng. deleted: dòng users bị xoá cứng (UC07); chỉ còn dsr_requests với user_id NULL và subject_ref. |
| model_versions | candidate, validated, rejected, retired: giá trị model_versions.status. active: suy ra, phiên bản đang được model_deployments.active_version_id trỏ tới; không lưu cờ is_active để tránh hai nơi cùng ghi một sự thật. |
| consent (theo mục đích) | none: chưa có consent_events nào cho (người dùng, mục đích). granted / withdrawn: action của sự kiện mới nhất trong v_current_consents. superseded: sự kiện mới nhất là grant nhưng v_current_consents.on_current_policy = false. |
| pantry_lots | in_stock, not_seen, used_up, discarded: giá trị pantry_lots.status; lượng hiện tại ở v_pantry_lot_balance. |

## Kiểu liệt kê

| Kiểu | Giá trị |
|---|---|
| `acquired_basis_t` | purchase_date_entered, first_seen |
| `activity_level_t` | light, moderate, heavy |
| `allergen_basis_t` | codex_2024, tastoria_extra |
| `consent_action_t` | grant, withdraw |
| `consent_channel_t` | onboarding, settings |
| `cook_status_t` | in_progress, completed, reverted, abandoned |
| `dsr_status_t` | received, in_progress, completed, rejected |
| `dsr_type_t` | access, export, correct, delete, withdraw, restrict, object |
| `freshness_t` | tuoi, dung_som, dung_ngay, kiem_tra |
| `goal_t` | maintain, lose, expert |
| `ingredient_role_t` | main, side, seasoning |
| `instance_def_t` | item, group_of, package |
| `interaction_type_t` | served, viewed, swapped, cooked, liked, disliked, undone |
| `kcal_source_t` | suggested, user, expert |
| `lang_t` | vi, en |
| `lot_status_t` | in_stock, used_up, discarded, not_seen |
| `meal_plan_status_t` | proposed, accepted, cooked, abandoned, expired |
| `meal_t` | lunch, dinner |
| `model_name_t` | detector, freshness, ranker, substitution |
| `model_status_t` | candidate, validated, rejected, retired |
| `pantry_ref_type_t` | scan, cook_session, user |
| `pantry_tx_reason_t` | scan_add, cook_deduct, manual_edit, discard, undo |
| `plan_item_status_t` | active, swapped_out |
| `qty_level_t` | it, vua, nhieu |
| `recipe_status_t` | draft, published, retired |
| `scan_item_origin_t` | model, user_added |
| `scan_mode_t` | fridge, haul |
| `scan_status_t` | queued, processing, done, failed, expired, confirmed, discarded |
| `scan_user_action_t` | kept, relabeled, deleted, edited |
| `shopping_status_t` | open, bought, dropped |
| `slot_t` | man, rau, canh |
| `step_kind_t` | active, passive |
| `substitution_origin_t` | lookup, embedding, user |
| `survey_channel_t` | link, qr |
| `swap_reason_t` | khong_hop_gu, moi_an, thieu_thoi_gian, khac |
| `tag_kind_t` | flavor, texture, occasion |
| `user_role_t` | user, admin, curator, ml_operator |
| `user_status_t` | active, deletion_requested |

## M01 — module `core`

DB session, Unit of Work, lỗi RFC 9457, Idempotency-Key, cấu hình, lưu tệp, bảo mật dùng chung.

### `idempotency_keys`

Khoá lũy đẳng của các request POST có header Idempotency-Key (tạo quét, mâm, đổi món, phiên nấu, nấu xong); lưu phản hồi đầu tiên để trả lại nguyên văn khi client gửi lại; job dọn xoá sau 48 giờ (UC34).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE; PK (user_id, key)` | DLCN cơ bản | Người dùng gửi request; khoá lũy đẳng có phạm vi theo từng người dùng. Nguồn: access token. |
| `key` | `text` | NOT NULL |  | `PK (user_id, key)` | DLCN cơ bản | Giá trị header Idempotency-Key do app sinh (UUID). |
| `request_sha256` | `bytea` | NOT NULL |  |  | DLCN cơ bản | SHA-256 của method, path và thân request; dùng để phát hiện cùng key nhưng nội dung khác. |
| `status_code` | `smallint` | NOT NULL |  |  | DLCN cơ bản | Mã trạng thái HTTP của phản hồi đầu tiên. |
| `response_body` | `jsonb` | NOT NULL |  |  | DLCN cơ bản | Thân phản hồi đầu tiên (JSON), chỉ để trả lại nguyên văn, không truy vấn. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm ghi khoá; job dọn (UC34) xoá bản ghi cũ hơn 48 giờ. |

Chỉ mục:

- `ix_idempotency_keys_created_at`: `btree (created_at)` — Job dọn khoá lũy đẳng quá 48 giờ (UC34).

Lưu/Xoá: 48 giờ, job dọn UC34. Quy mô ước lượng: ~10^4 dòng sống.

Ghi chú thiết kế: jsonb chỉ lưu phản hồi để trả lại nguyên văn, không truy vấn; xoá sau 48 giờ (UC34).

## M02 — module `identity`

Tài khoản, mật khẩu, JWT, refresh token, đặt lại mật khẩu, khoá đăng nhập.

### `users`

Tài khoản đăng nhập của người dùng cuối và nhân sự (quản trị viên, biên soạn công thức, vận hành mô hình).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh tài khoản (UUID sinh ở server). |
| `email` | `citext` | NOT NULL |  | `UNIQUE` | DLCN cơ bản | Email đăng nhập, so khớp không phân biệt hoa thường (citext), duy nhất. |
| `password_hash` | `text` | NOT NULL |  |  | Bí mật xác thực | Chuỗi băm Argon2id của mật khẩu (gồm tham số và muối); không lưu mật khẩu gốc. |
| `role` | `user_role_t` | NOT NULL | `'user'::user_role_t` |  | Không phải DLCN | Vai trò: user (người dùng), admin (quản trị viên), curator (biên soạn công thức), ml_operator (vận hành mô hình). |
| `status` | `user_status_t` | NOT NULL | `'active'::user_status_t` |  | DLCN cơ bản | Trạng thái tài khoản: active, hoặc deletion_requested khi người dùng đã yêu cầu xoá (UC07) và đang chờ xoá cứng. |
| `token_version` | `integer` | NOT NULL | `0` | `CHECK ((token_version >= 0))` | DLCN cơ bản | Phiên bản token; tăng khi đăng xuất mọi thiết bị hoặc rút đồng ý để access token cũ hết hiệu lực ngay (BR-CONSENT-04). |
| `failed_logins` | `smallint` | NOT NULL | `0` | `CHECK ((failed_logins >= 0))` | DLCN cơ bản | Số lần đăng nhập sai liên tiếp; đặt về 0 khi đăng nhập đúng (NFR-SEC-02). |
| `locked_until` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm hết khoá tạm; NULL là không bị khoá. Khoá 15 phút sau 5 lần sai (NFR-SEC-02). |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm tạo bản ghi (giờ server, timestamptz). |
| `updated_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz). |

Lưu/Xoá: Đến khi xoá tài khoản (UC07): xoá cứng dòng. Quy mô ước lượng: ~10^3.

Ràng buộc chỉ kiểm ở service: Khoá tạm theo (email, IP) đếm ở Valkey (NFR-SEC-02); users.locked_until chỉ là bản ghi kết quả.

### `refresh_tokens`

Refresh token xoay vòng (hạn 30 ngày, NFR-SEC-01); chỉ lưu băm. Các token cùng family_id thuộc một chuỗi xoay vòng; dùng lại token đã thu hồi thì thu hồi cả họ.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | Bí mật xác thực | Định danh bản ghi token (UUID). |
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE` | DLCN cơ bản | Chủ token. |
| `family_id` | `uuid` | NOT NULL |  |  | Bí mật xác thực | Định danh họ token: mọi token sinh ra từ cùng một lần đăng nhập qua các lần xoay vòng. |
| `token_sha256` | `bytea` | NOT NULL |  | `UNIQUE` | Bí mật xác thực | SHA-256 của refresh token; token gốc chỉ nằm ở app. |
| `issued_at` | `timestamp with time zone` | NOT NULL |  |  | Bí mật xác thực | Thời điểm cấp token. |
| `expires_at` | `timestamp with time zone` | NOT NULL |  |  | Bí mật xác thực | Thời điểm hết hạn (issued_at + 30 ngày). |
| `revoked_at` | `timestamp with time zone` | NULL |  |  | Bí mật xác thực | Thời điểm thu hồi (xoay vòng, đăng xuất, phát hiện dùng lại); NULL là còn hiệu lực. |
| `replaced_by_id` | `uuid` | NULL |  | `FK → refresh_tokens(id); UNIQUE` | Bí mật xác thực | Token mới thay thế token này khi xoay vòng; NULL nếu chưa xoay. |
| `user_agent` | `text` | NULL |  |  | DLCN cơ bản | Chuỗi User-Agent lúc cấp, giúp người dùng nhận ra thiết bị. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_refresh_tokens_expiry`: `CHECK ((expires_at > issued_at))` — Hạn sau thời điểm cấp (NFR-SEC-01).
- `ck_refresh_tokens_not_self`: `CHECK ((replaced_by_id <> id))`
- `uq_refresh_tokens_replaced_by_id`: `UNIQUE (replaced_by_id)` — Mỗi token được thay tối đa một lần (khoá thay thế khi khác NULL; NULL không so bằng nhau).

Chỉ mục:

- `ix_refresh_tokens_expires_at`: `btree (expires_at)` — Job dọn token hết hạn (UC34).
- `ix_refresh_tokens_family_id`: `btree (family_id)`
- `ix_refresh_tokens_user_id`: `btree (user_id)`

Trigger:

- `trg_refresh_tokens_write_once` (before update): `trg_write_once('user_id', 'family_id', 'token_sha256', 'issued_at', 'expires_at')`

Lưu/Xoá: Hết hạn sau 30 ngày, job dọn UC34; xoá dây chuyền khi xoá tài khoản. Quy mô ước lượng: ~10^4.

### `password_resets`

Yêu cầu đặt lại mật khẩu qua email (UC04); token dùng một lần, chỉ lưu băm.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | Bí mật xác thực | Định danh yêu cầu (UUID). |
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE` | DLCN cơ bản | Tài khoản cần đặt lại mật khẩu. |
| `token_sha256` | `bytea` | NOT NULL |  | `UNIQUE` | Bí mật xác thực | SHA-256 của token gửi trong thư; token gốc chỉ có trong liên kết email. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | Bí mật xác thực | Thời điểm tạo yêu cầu. |
| `expires_at` | `timestamp with time zone` | NOT NULL |  |  | Bí mật xác thực | Thời điểm token hết hạn. |
| `used_at` | `timestamp with time zone` | NULL |  |  | Bí mật xác thực | Thời điểm token đã được dùng; NULL là chưa dùng. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_password_resets_expiry`: `CHECK ((expires_at > created_at))` — Hạn sau thời điểm tạo (UC04).

Chỉ mục:

- `ix_password_resets_expires_at`: `btree (expires_at)` — Job dọn yêu cầu đặt lại mật khẩu hết hạn (UC34).
- `ix_password_resets_user_id`: `btree (user_id)`

Lưu/Xoá: Đến khi dùng hoặc hết hạn, job dọn UC34. Quy mô ước lượng: ~10^3.

Ràng buộc chỉ kiểm ở service: Thời gian sống của liên kết chưa định (07 mục 9).

## M03 — module `privacy`

Mục đích đồng ý, phiên bản điều khoản, nhật ký đồng ý, yêu cầu chủ thể dữ liệu, nhật ký kiểm toán.

### `consent_purposes`

Danh mục mục đích xử lý dữ liệu cần đồng ý riêng (BR-CONSENT-01); dữ liệu tham chiếu.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `code` | `text` | NOT NULL |  | `PK` | Không phải DLCN | Mã mục đích: health_profile, personalization, photo_contribution, survey. |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên mục đích hiển thị cho người dùng. |
| `description_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Mô tả mục đích hiển thị khi xin đồng ý. |
| `data_category` | `text` | NOT NULL |  |  | Không phải DLCN | Loại dữ liệu cá nhân được xử lý cho mục đích này (ví dụ chỉ số cơ thể, dữ liệu hành vi, ảnh). |
| `is_sensitive` | `boolean` | NOT NULL |  |  | Không phải DLCN | true nếu là dữ liệu cá nhân nhạy cảm (health_profile, personalization). |
| `is_required` | `boolean` | NOT NULL | `false` |  | Không phải DLCN | true nếu bắt buộc để dùng dịch vụ; mặc định false, không tích sẵn. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: 4.

### `policy_versions`

Phiên bản văn bản điều khoản của từng mục đích; mỗi sự kiện đồng ý gắn với đúng phiên bản người dùng đã đọc.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | Không phải DLCN | Định danh phiên bản (UUID). |
| `purpose_code` | `text` | NOT NULL |  | `FK → consent_purposes(code)` | Không phải DLCN | Mục đích mà văn bản này áp dụng. |
| `version` | `text` | NOT NULL |  |  | Không phải DLCN | Nhãn phiên bản, duy nhất trong một mục đích. |
| `text_sha256` | `bytea` | NOT NULL |  |  | Không phải DLCN | SHA-256 toàn văn điều khoản đã hiển thị, làm bằng chứng nội dung. |
| `effective_from` | `timestamp with time zone` | NOT NULL |  |  | Không phải DLCN | Thời điểm phiên bản bắt đầu có hiệu lực. |

Ràng buộc nhiều cột hoặc có chú thích:

- `uq_policy_versions_purpose_code_version`: `UNIQUE (purpose_code, version)`

Lưu/Xoá: Dữ liệu tham chiếu, không xoá (bằng chứng phiên bản đã đồng ý). Quy mô ước lượng: ~10.

### `consent_events`

Nhật ký đồng ý và rút đồng ý, chỉ ghi thêm; trạng thái hiện hành = sự kiện mới nhất mỗi (người dùng, mục đích), xem v_current_consents.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh sự kiện (UUID). |
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE` | DLCN cơ bản | Người dùng đưa ra quyết định. |
| `policy_version_id` | `uuid` | NOT NULL |  | `FK → policy_versions(id)` | DLCN cơ bản | Phiên bản điều khoản tại thời điểm quyết định; mục đích suy ra qua policy_versions.purpose_code. |
| `action` | `consent_action_t` | NOT NULL |  |  | DLCN cơ bản | grant (đồng ý) hoặc withdraw (rút đồng ý). |
| `channel` | `consent_channel_t` | NOT NULL |  |  | DLCN cơ bản | Nơi thao tác: onboarding (thiết lập hồ sơ, UC09) hoặc settings (cài đặt, UC05). |
| `app_version` | `text` | NULL |  |  | DLCN cơ bản | Phiên bản app lúc thao tác; NULL nếu không rõ. |
| `created_at` | `timestamp with time zone` | NOT NULL | `clock_timestamp()` |  | DLCN cơ bản | Thời điểm ghi sự kiện (giờ server, clock_timestamp() để hai sự kiện trong một giao dịch vẫn có thứ tự; v_current_consents chọn sự kiện mới nhất theo cột này). |

Chỉ mục:

- `ix_consent_events_user_id_created_at`: `btree (user_id, created_at DESC)`

Trigger:

- `trg_consent_events_append_only` (before delete or update): `trg_append_only()`
- `trg_consent_events_no_truncate` (before truncate): `trg_append_only()`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ); chỉ ghi thêm. Quy mô ước lượng: ~10^4.

Ghi chú thiết kế: chỉ ghi thêm; trạng thái hiện tại = sự kiện mới nhất mỗi mục đích (view v_current_consents).

### `dsr_requests`

Yêu cầu của chủ thể dữ liệu (BR-DSR-01): truy cập, tải về, sửa, xoá, rút đồng ý, hạn chế, phản đối; hoàn tất ≤ 24 giờ (NFR-PRIV-01). Bản ghi giữ lại làm bằng chứng sau khi tài khoản bị xoá.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh yêu cầu (UUID). |
| `user_id` | `uuid` | NULL |  | `FK → users(id) ON DELETE SET NULL` | DLCN cơ bản | Người yêu cầu; thành NULL khi tài khoản bị xoá. |
| `subject_ref` | `bytea` | NOT NULL |  |  | Bí danh (vẫn là DLCN) | HMAC-SHA256 của user_id với khoá bí mật của server; giữ liên kết bằng chứng sau khi xoá tài khoản. |
| `type` | `dsr_type_t` | NOT NULL |  |  | DLCN cơ bản | Loại yêu cầu: access, export, correct, delete, withdraw, restrict, object. |
| `status` | `dsr_status_t` | NOT NULL |  |  | DLCN cơ bản | Trạng thái xử lý: received, in_progress, completed, rejected. |
| `received_at` | `timestamp with time zone` | NOT NULL |  |  | DLCN cơ bản | Thời điểm nhận yêu cầu; mốc tính hạn 24 giờ. |
| `acknowledged_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm xác nhận đã nhận với người yêu cầu; NULL nếu chưa. |
| `completed_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm hoàn tất hoặc từ chối; NULL nếu chưa xong. |
| `result_key` | `text` | NULL |  |  | DLCN cơ bản | Khoá tệp kết quả trong kho lưu trữ (ví dụ gói dữ liệu tải về của UC06); NULL nếu không có tệp. |
| `note` | `text` | NULL |  |  | DLCN cơ bản | Ghi chú xử lý của quản trị viên hoặc lý do từ chối. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_dsr_requests_completed_at`: `CHECK (((completed_at IS NULL) OR (completed_at >= received_at)))`

Chỉ mục:

- `ix_dsr_requests_status_received_at`: `btree (status, received_at)`
- `ix_dsr_requests_user_id`: `btree (user_id)`

Trigger:

- `trg_dsr_requests_guard` (before update): `trg_dsr_requests_guard()`

Lưu/Xoá: Chưa định (07 mục 9; đề xuất 24 tháng sau completed_at). Khi xoá tài khoản user_id thành NULL, giữ subject_ref. Quy mô ước lượng: ~10^2.

Ràng buộc chỉ kiểm ở service: Một yêu cầu mở mỗi loại mỗi người (UC08).

### `audit_log`

Nhật ký kiểm toán, chỉ ghi thêm: mỗi lần giải mã cột sức khoẻ và mỗi thao tác của nhân sự.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `bigint` | NOT NULL | `GENERATED ALWAYS AS IDENTITY` | `PK` | DLCN cơ bản | Số thứ tự bản ghi (identity). |
| `actor_user_id` | `uuid` | NULL |  | `FK → users(id) ON DELETE SET NULL` | DLCN cơ bản | Tài khoản thực hiện; NULL khi tài khoản đã xoá hoặc do tác vụ hệ thống. |
| `actor_role` | `text` | NOT NULL |  |  | DLCN cơ bản | Vai trò của tác nhân tại thời điểm thao tác; giữ lại cả khi tài khoản đã xoá. |
| `action` | `text` | NOT NULL |  |  | DLCN cơ bản | Mã thao tác (ví dụ giải mã hồ sơ sức khoẻ, xử lý yêu cầu dữ liệu, triển khai mô hình). |
| `entity` | `text` | NOT NULL |  |  | DLCN cơ bản | Tên loại đối tượng bị tác động (thường là tên bảng). |
| `entity_id` | `text` | NULL |  |  | DLCN cơ bản | Khoá của đối tượng bị tác động, dạng chuỗi; NULL nếu thao tác không gắn một đối tượng. |
| `purpose` | `text` | NULL |  |  | DLCN cơ bản | Mục đích xử lý dẫn tới thao tác (mã consent_purposes hoặc lý do nghiệp vụ); NULL nếu không áp dụng. |
| `request_id` | `text` | NULL |  |  | DLCN cơ bản | Mã request HTTP hoặc mã lượt chạy CLI để đối chiếu log ứng dụng. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm ghi nhật ký (giờ server). |

Chỉ mục:

- `ix_audit_log_actor_user_id`: `btree (actor_user_id)` — ON DELETE SET NULL khi xoá tài khoản (UC07); lọc nhật ký theo nhân sự (UC27).
- `ix_audit_log_created_at`: `btree (created_at)`

Trigger:

- `trg_audit_log_append_only` (before delete or update): `trg_append_only()`
- `trg_audit_log_no_truncate` (before truncate): `trg_append_only()`

Lưu/Xoá: Chưa định (07 mục 9; đề xuất 24 tháng). Khi xoá tài khoản: actor_user_id thành NULL, entity_id của chủ thể được ghi đè bằng HMAC (04 D8). Quy mô ước lượng: ~10^5.

Ghi chú thiết kế: chỉ ghi thêm; ghi mỗi lần giải mã cột sức khoẻ và mỗi thao tác nhân sự.

### View `v_current_consents`

Đồng ý hiện hành theo (người dùng, mục đích) = consent_event mới nhất; is_granted = true khi sự kiện mới nhất là grant.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `user_id` | `uuid` | Người dùng. |
| `purpose_code` | `text` | Mục đích (qua policy_versions.purpose_code). |
| `action` | `consent_action_t` | Hành động của sự kiện mới nhất: grant hoặc withdraw. |
| `is_granted` | `boolean` | true nếu đang đồng ý. |
| `policy_version_id` | `uuid` | Phiên bản điều khoản của sự kiện mới nhất. |
| `policy_version` | `text` | Nhãn phiên bản điều khoản. |
| `on_current_policy` | `boolean` | true nếu phiên bản đó là phiên bản đang hiệu lực của mục đích; false là đã bị thay (cần xin lại đồng ý). |
| `channel` | `consent_channel_t` | Kênh của sự kiện mới nhất. |
| `decided_at` | `timestamp with time zone` | Thời điểm sự kiện mới nhất. |

## M04 — module `catalog`

Thành phần thực phẩm, nguyên liệu, món, bước, dinh dưỡng món, lớp thị giác, dữ liệu tham chiếu.

### `food_groups`

Nhóm thực phẩm; dùng để loại theo chế độ ăn (diet_exclusions) và quy đổi mức lượng (qty_levels).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `code` | `text` | NOT NULL |  | `PK` | Không phải DLCN | Mã nhóm thực phẩm. |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên nhóm tiếng Việt. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~20.

### `nutrient_sources`

Nguồn bảng thành phần thực phẩm: Bảng TPTP Việt Nam 2007, USDA SR Legacy, USDA Foundation.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `smallint` | NOT NULL |  | `PK` | Không phải DLCN | Định danh nguồn (số nhỏ, cấp thủ công). |
| `code` | `text` | NOT NULL |  | `UNIQUE` | Không phải DLCN | Mã nguồn: fct2007, usda_sr_legacy, usda_foundation. |
| `name` | `text` | NOT NULL |  |  | Không phải DLCN | Tên đầy đủ của nguồn. |
| `version` | `text` | NOT NULL |  |  | Không phải DLCN | Phiên bản hoặc ngày phát hành của bộ dữ liệu đã nạp. |
| `license` | `text` | NOT NULL |  |  | Không phải DLCN | Giấy phép sử dụng (ví dụ CC0 với USDA). |
| `url` | `text` | NOT NULL |  |  | Không phải DLCN | Địa chỉ tải dữ liệu gốc. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: 3.

### `food_items`

Thực phẩm trong bảng thành phần nguồn; khoá tự nhiên là (nguồn, mã trong nguồn).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `source_id` | `smallint` | NOT NULL |  | `FK → nutrient_sources(id); PK (source_id, source_code)` | Không phải DLCN | Nguồn bảng thành phần. |
| `source_code` | `text` | NOT NULL |  | `PK (source_id, source_code)` | Không phải DLCN | Mã thực phẩm trong bảng nguồn (mã TPTP 2007 hoặc FDC ID của USDA). |
| `name` | `text` | NOT NULL |  |  | Không phải DLCN | Tên theo nguồn; tên TPTP 2007 đã chuyển từ mã TCVN3 sang Unicode. |
| `name_en` | `text` | NULL |  |  | Không phải DLCN | Tên tiếng Anh theo nguồn; NULL nếu nguồn không có. |
| `refuse_pct` | `numeric` | NULL |  | `CHECK (((refuse_pct >= (0)::numeric) AND (refuse_pct <= (100)::numeric)))` | Không phải DLCN | Tỷ lệ thải bỏ, % khối lượng lúc mua (0–100); phần ăn được EP = 100 − refuse_pct. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~10^3 (FCT 2007 có 526 mục, thêm USDA khi thiếu).

### `nutrients`

Danh mục chất dinh dưỡng dùng trong tính toán: năng lượng, protein, lipid, glucid, chất xơ, đường, natri.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `code` | `text` | NOT NULL |  | `PK` | Không phải DLCN | Mã chất: energy_kcal, protein_g, lipid_g, glucid_g, fiber_g, sugar_g, sodium_mg. |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên chất tiếng Việt. |
| `unit` | `text` | NOT NULL |  |  | Không phải DLCN | Đơn vị: kcal, g hoặc mg. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: 7.

### `food_nutrients`

Hàm lượng chất dinh dưỡng của thực phẩm theo bảng nguồn.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `source_id` | `smallint` | NOT NULL |  | `FK (source_id, source_code) → food_items(source_id, source_code); PK (source_id, source_code, nutrient_code)` | Không phải DLCN | Nguồn bảng thành phần (cùng source_code tham chiếu food_items). |
| `source_code` | `text` | NOT NULL |  | `FK (source_id, source_code) → food_items(source_id, source_code); PK (source_id, source_code, nutrient_code)` | Không phải DLCN | Mã thực phẩm trong nguồn. |
| `nutrient_code` | `text` | NOT NULL |  | `FK → nutrients(code); PK (source_id, source_code, nutrient_code)` | Không phải DLCN | Chất dinh dưỡng. |
| `per_100g` | `numeric` | NOT NULL |  | `CHECK ((per_100g >= (0)::numeric))` | Không phải DLCN | Hàm lượng trên 100 g phần ăn được, đơn vị theo nutrients.unit. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~7 × 10^3.

### `allergen_groups`

Nhóm dị ứng (BR-ALG-02): 8 nhóm theo Codex CXS 1-1985 sửa 2024 và nhóm bổ sung đậu nành, nhuyễn thể.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `code` | `text` | NOT NULL |  | `PK` | Không phải DLCN | Mã nhóm dị ứng. |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên tiếng Việt. |
| `name_en` | `text` | NOT NULL |  |  | Không phải DLCN | Tên tiếng Anh. |
| `basis` | `allergen_basis_t` | NOT NULL |  |  | Không phải DLCN | Căn cứ: codex_2024 (Codex sửa 2024) hoặc tastoria_extra (bổ sung của Tastoria). |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: 10.

### `diets`

Chế độ ăn người dùng có thể chọn (v2: chay).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `code` | `text` | NOT NULL |  | `PK` | Không phải DLCN | Mã chế độ ăn. |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên tiếng Việt. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: 1–2.

### `diet_exclusions`

Nhóm thực phẩm bị loại theo từng chế độ ăn (BR-DIET-01).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `diet_code` | `text` | NOT NULL |  | `FK → diets(code); PK (diet_code, food_group_code)` | Không phải DLCN | Chế độ ăn. |
| `food_group_code` | `text` | NOT NULL |  | `FK → food_groups(code); PK (diet_code, food_group_code)` | Không phải DLCN | Nhóm thực phẩm bị loại. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~10.

### `ingredients`

Nguyên liệu của kho công thức; không xoá cứng, ngừng dùng bằng is_active = false (BR-CATALOG-01).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | Không phải DLCN | Định danh nguyên liệu (UUID). |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên chuẩn tiếng Việt; duy nhất trong các nguyên liệu đang dùng (ux_ingredients_name_vi_active, is_active = true). |
| `food_group_code` | `text` | NOT NULL |  | `FK → food_groups(code)` | Không phải DLCN | Nhóm thực phẩm, dùng cho chế độ ăn và mức lượng. |
| `comp_source_id` | `smallint` | NULL |  | `FK (comp_source_id, comp_source_code) → food_items(source_id, source_code)` | Không phải DLCN | Nguồn bảng thành phần của thực phẩm tương ứng; NULL khi chưa ánh xạ. |
| `comp_source_code` | `text` | NULL |  | `FK (comp_source_id, comp_source_code) → food_items(source_id, source_code)` | Không phải DLCN | Mã thực phẩm tương ứng trong nguồn; đi cặp với comp_source_id: cả hai cùng NULL hoặc cùng có giá trị (ck_ingredients_comp_pair), vì khoá ngoại ghép MATCH SIMPLE không kiểm khi một cột NULL. |
| `is_staple` | `boolean` | NOT NULL | `false` |  | Không phải DLCN | true nếu là gia vị luôn có: miễn kiểm kho, không miễn kiểm dị ứng (BR-ALG-01). |
| `countable` | `boolean` | NOT NULL | `false` |  | Không phải DLCN | true nếu đếm theo đơn vị (quả, bó...), quy đổi gam qua ingredient_units (BR-QTY-02). |
| `shelf_life_days` | `numeric` | NULL |  | `CHECK ((shelf_life_days > (0)::numeric))` | Không phải DLCN | Thời hạn bảo quản ngăn mát L, đơn vị ngày (BR-FRESH-01); NULL nếu chưa có. |
| `shelf_life_basis` | `text` | NULL |  |  | Không phải DLCN | Căn cứ của L: mã FoodKeeper hoặc hiệu chỉnh của nhóm. |
| `is_active` | `boolean` | NOT NULL | `true` |  | Không phải DLCN | false là ngừng dùng cho món mới; giữ bản ghi để món cũ vẫn tham chiếu được. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | Không phải DLCN | Thời điểm tạo bản ghi (giờ server, timestamptz). |
| `updated_at` | `timestamp with time zone` | NOT NULL | `now()` |  | Không phải DLCN | Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_ingredients_comp_pair`: `CHECK (((comp_source_id IS NULL) = (comp_source_code IS NULL)))` — Khoá ngoại ghép tới food_items theo MATCH SIMPLE: buộc hai cột cùng NULL hoặc cùng có giá trị để không lưu được nửa khoá (BR-NUT-05).

Chỉ mục:

- `ux_ingredients_name_vi_active`: `UNIQUE btree (name_vi) WHERE is_active` — Tên nguyên liệu duy nhất trong các nguyên liệu đang dùng (BR-CATALOG-01).

Lưu/Xoá: Không xoá cứng (is_active = false, BR-CATALOG-01). Quy mô ước lượng: ~300.

Ghi chú thiết kế: EP lấy qua FK tới food_items.refuse_pct, không chép vào đây (tránh phụ thuộc bắc cầu).

### `ingredient_synonyms`

Tên gọi khác của nguyên liệu (tiếng Việt và tiếng Anh); dùng tìm kiếm và nối với Word2Vec trên Food.com.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id); PK (ingredient_id, synonym, lang)` | Không phải DLCN | Nguyên liệu. |
| `synonym` | `text` | NOT NULL |  | `PK (ingredient_id, synonym, lang)` | Không phải DLCN | Tên gọi khác. |
| `lang` | `lang_t` | NOT NULL |  | `PK (ingredient_id, synonym, lang)` | Không phải DLCN | Ngôn ngữ của tên: vi hoặc en. |
| `source` | `text` | NULL |  |  | Không phải DLCN | Nguồn của tên gọi (ví dụ từ điển, biên soạn); NULL nếu do nhóm tự thêm. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~10^3.

### `ingredient_allergens`

Nguyên liệu thuộc nhóm dị ứng nào (quan hệ nhiều–nhiều).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id); PK (ingredient_id, allergen_code)` | Không phải DLCN | Nguyên liệu. |
| `allergen_code` | `text` | NOT NULL |  | `FK → allergen_groups(code); PK (ingredient_id, allergen_code)` | Không phải DLCN | Nhóm dị ứng. |

Chỉ mục:

- `ix_ingredient_allergens_allergen_code`: `btree (allergen_code)`

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~10^2.

### `ingredient_units`

Quy đổi đơn vị đếm sang gam lúc mua cho nguyên liệu đếm được (BR-QTY-02).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id); PK (ingredient_id, unit_code)` | Không phải DLCN | Nguyên liệu. |
| `unit_code` | `text` | NOT NULL |  | `PK (ingredient_id, unit_code)` | Không phải DLCN | Đơn vị đếm: qua, bo, cu, nhanh, mieng, goi, hop. |
| `grams_per_unit` | `numeric` | NOT NULL |  | `CHECK ((grams_per_unit > (0)::numeric))` | Không phải DLCN | Số gam lúc mua của một đơn vị (> 0), ví dụ 1 quả trứng gà = 50 g. |
| `source` | `text` | NOT NULL |  |  | Không phải DLCN | Nguồn số liệu quy đổi. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~10^2.

### `qty_levels`

Quy đổi mức lượng ít/vừa/nhiều sang khoảng gam theo nhóm thực phẩm (BR-QTY-02).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `food_group_code` | `text` | NOT NULL |  | `FK → food_groups(code); PK (food_group_code, level)` | Không phải DLCN | Nhóm thực phẩm. |
| `level` | `qty_level_t` | NOT NULL |  | `PK (food_group_code, level)` | Không phải DLCN | Mức lượng: it, vua, nhieu. |
| `g_min` | `numeric` | NOT NULL |  | `CHECK ((g_min >= (0)::numeric))` | Không phải DLCN | Cận dưới khoảng gam lúc mua. |
| `g_max` | `numeric` | NOT NULL |  |  | Không phải DLCN | Cận trên khoảng gam lúc mua (≥ g_min). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_qty_levels_1`: `CHECK ((g_min <= g_max))`

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~60.

### `cooking_methods`

Cách nấu (luộc, xào, kho...); dùng cho món và ngữ cảnh cặp thay thế.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `code` | `text` | NOT NULL |  | `PK` | Không phải DLCN | Mã cách nấu. |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên tiếng Việt. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~10.

### `tags`

Nhãn mô tả món theo vị, kết cấu, dịp ăn; dùng cho xếp hạng nội dung.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `code` | `text` | NOT NULL |  | `PK` | Không phải DLCN | Mã nhãn. |
| `kind` | `tag_kind_t` | NOT NULL |  |  | Không phải DLCN | Loại nhãn: flavor (vị), texture (kết cấu), occasion (dịp). |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên tiếng Việt. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~50.

### `recipes`

Món ăn trong kho công thức. Món published là bất biến: sửa thì tạo bản mới, bản cũ chuyển retired (BR-CATALOG-01). Tổng thời gian và nguyên liệu chính là giá trị dẫn xuất, không lưu.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | Không phải DLCN | Định danh món (UUID); mỗi bản sửa là một id mới. |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên món tiếng Việt; duy nhất trong các bản chưa retired (ux_recipes_name_vi_live), nên bản mới của món đã sửa (BR-CATALOG-01) giữ được tên cũ. |
| `slot` | `slot_t` | NOT NULL |  |  | Không phải DLCN | Vị trí trong mâm: man (mặn), rau, canh (BR-TRAY-01). |
| `servings` | `smallint` | NOT NULL |  | `CHECK ((servings > 0))` | Không phải DLCN | Số khẩu phần mà lượng gam trong recipe_ingredients áp dụng (> 0). |
| `method_code` | `text` | NOT NULL |  | `FK → cooking_methods(code)` | Không phải DLCN | Cách nấu chính. |
| `status` | `recipe_status_t` | NOT NULL | `'draft'::recipe_status_t` |  | Không phải DLCN | Trạng thái: draft, published, retired. |
| `notes` | `text` | NULL |  |  | Không phải DLCN | Ghi chú biên soạn. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | Không phải DLCN | Thời điểm tạo bản ghi (giờ server, timestamptz). |
| `updated_at` | `timestamp with time zone` | NOT NULL | `now()` |  | Không phải DLCN | Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz). |

Ràng buộc nhiều cột hoặc có chú thích:

- `uq_recipes_id_slot`: `UNIQUE (id, slot)`

Chỉ mục:

- `ux_recipes_name_vi_live`: `UNIQUE btree (name_vi) WHERE (status <> 'retired'::recipe_status_t)` — Tên món duy nhất trong các bản draft/published; bản retired giữ tên cũ để bản mới dùng lại (BR-CATALOG-01).

Trigger:

- `trg_recipes_guard` (before delete or update): `trg_recipes_guard()` — BR-CATALOG-01: published chỉ chuyển retired, retired bất biến, không xoá món đã công bố.

Lưu/Xoá: Không xoá cứng (retired, BR-CATALOG-01). Quy mô ước lượng: 150–200 món mỗi bản, cộng các bản retired.

Ràng buộc chỉ kiểm ở service: Chuyển published khi có ≥ 2 nguồn, mọi nguyên liệu có ánh xạ bảng thành phần, bước liên tục từ 1 (FR-25-08).

Ghi chú thiết kế: món đã published là bất biến (BR-CATALOG-01): sửa = tạo bản mới, retire bản cũ; tổng thời gian và nguyên liệu chính là giá trị dẫn xuất, không lưu.

### `recipe_ingredients`

Nguyên liệu của món và lượng dùng.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `recipe_id` | `uuid` | NOT NULL |  | `FK → recipes(id); PK (recipe_id, ingredient_id)` | Không phải DLCN | Món. |
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id); PK (recipe_id, ingredient_id)` | Không phải DLCN | Nguyên liệu. |
| `grams` | `numeric` | NOT NULL |  | `CHECK ((grams > (0)::numeric))` | Không phải DLCN | Khối lượng lúc mua cho servings khẩu phần, gam (> 0); lượng cần cho n người = grams × n / servings (BR-TRAY-02). |
| `role` | `ingredient_role_t` | NOT NULL |  |  | Không phải DLCN | Vai trò trong món: main (chính), side (phụ), seasoning (gia vị). |
| `is_optional` | `boolean` | NOT NULL | `false` |  | Không phải DLCN | true nếu có thể bỏ mà món vẫn nấu được. |

Chỉ mục:

- `ix_recipe_ingredients_ingredient_id`: `btree (ingredient_id)`

Trigger:

- `trg_recipe_ingredients_guard` (before insert or delete or update): `trg_recipe_children_guard()`

Lưu/Xoá: Theo món. Quy mô ước lượng: ~2 × 10^3.

### `recipe_steps`

Các bước nấu của món, dùng cho lịch nấu CP-SAT (BR-COOK-01).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `recipe_id` | `uuid` | NOT NULL |  | `FK → recipes(id); PK (recipe_id, step_no)` | Không phải DLCN | Món. |
| `step_no` | `smallint` | NOT NULL |  | `CHECK ((step_no > 0)); PK (recipe_id, step_no)` | Không phải DLCN | Số thứ tự bước trong món; các bước làm theo thứ tự này. |
| `text_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Nội dung bước, tiếng Việt. |
| `kind` | `step_kind_t` | NOT NULL |  |  | Không phải DLCN | active (người nấu phải làm) hoặc passive (chờ, người nấu rảnh tay). |
| `minutes` | `smallint` | NOT NULL |  | `CHECK ((minutes > 0))` | Không phải DLCN | Thời lượng bước, phút (> 0). |
| `uses_burner` | `boolean` | NOT NULL | `false` |  | Không phải DLCN | true nếu bước chiếm một họng bếp. |

Trigger:

- `trg_recipe_steps_guard` (before insert or delete or update): `trg_recipe_children_guard()`

Lưu/Xoá: Theo món. Quy mô ước lượng: ~2 × 10^3.

Ràng buộc chỉ kiểm ở service: Bước đánh số liên tục từ 1 (FR-25-08).

### `recipe_tags`

Nhãn gắn cho món (quan hệ nhiều–nhiều).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `recipe_id` | `uuid` | NOT NULL |  | `FK → recipes(id); PK (recipe_id, tag_code)` | Không phải DLCN | Món. |
| `tag_code` | `text` | NOT NULL |  | `FK → tags(code); PK (recipe_id, tag_code)` | Không phải DLCN | Nhãn. |

Trigger:

- `trg_recipe_tags_guard` (before insert or delete or update): `trg_recipe_children_guard()`

Lưu/Xoá: Theo món. Quy mô ước lượng: ~10^3.

### `recipe_sources`

Nguồn tham khảo của món (mỗi món ≥ 2 nguồn, nội dung viết lại bằng lời của nhóm).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `recipe_id` | `uuid` | NOT NULL |  | `FK → recipes(id); PK (recipe_id, url)` | Không phải DLCN | Món. |
| `url` | `text` | NOT NULL |  | `PK (recipe_id, url)` | Không phải DLCN | Địa chỉ nguồn. |
| `title` | `text` | NOT NULL |  |  | Không phải DLCN | Tiêu đề trang nguồn. |
| `accessed_on` | `date` | NOT NULL |  |  | Không phải DLCN | Ngày truy cập nguồn. |

Lưu/Xoá: Theo món. Quy mô ước lượng: ~500.

Ràng buộc chỉ kiểm ở service: Mỗi món published có ≥ 2 nguồn (FR-25-08).

### `recipe_nutrition`

Dinh dưỡng mỗi khẩu phần của món. Phi chuẩn hoá có kiểm soát: dẫn xuất từ recipe_ingredients × food_nutrients × EP (BR-NUT-05), job tính lại khi kho món hoặc bảng thành phần đổi.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `recipe_id` | `uuid` | NOT NULL |  | `FK → recipes(id); PK (recipe_id, nutrient_code)` | Không phải DLCN | Món. |
| `nutrient_code` | `text` | NOT NULL |  | `FK → nutrients(code); PK (recipe_id, nutrient_code)` | Không phải DLCN | Chất dinh dưỡng. |
| `per_serving` | `numeric` | NOT NULL |  | `CHECK ((per_serving >= (0)::numeric))` | Không phải DLCN | Hàm lượng mỗi khẩu phần, đơn vị theo nutrients.unit. |
| `computed_at` | `timestamp with time zone` | NOT NULL |  |  | Không phải DLCN | Thời điểm tính. |
| `data_version` | `text` | NOT NULL |  |  | Không phải DLCN | Phiên bản dữ liệu nguồn dùng khi tính (kho món, bảng thành phần). |

Lưu/Xoá: Tính lại bởi UC25. Quy mô ước lượng: ~1.400.

Ghi chú thiết kế: PHI CHUẨN HOÁ CÓ KIỂM SOÁT: giá trị dẫn xuất từ recipe_ingredients × food_nutrients × EP; tính lại bằng job khi kho món hoặc bảng thành phần đổi; data_version ghi phiên bản dữ liệu nguồn.

### `vision_classes`

Lớp nhận dạng của mô hình phát hiện nguyên liệu trong ảnh.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `smallint` | NOT NULL |  | `PK` | Không phải DLCN | Định danh lớp (số nhỏ). |
| `code` | `text` | NOT NULL |  | `UNIQUE` | Không phải DLCN | Mã lớp, duy nhất. |
| `name_vi` | `text` | NOT NULL |  |  | Không phải DLCN | Tên tiếng Việt. |
| `name_en` | `text` | NOT NULL |  |  | Không phải DLCN | Tên tiếng Anh. |
| `countable` | `boolean` | NOT NULL |  |  | Không phải DLCN | true nếu đếm theo từng vật; false thì người dùng chọn mức ít/vừa/nhiều. |
| `instance_def` | `instance_def_t` | NOT NULL |  |  | Không phải DLCN | Cách định nghĩa một thể hiện khi gán khung: item (một vật), group_of (một cụm), package (một gói). |
| `has_freshness_model` | `boolean` | NOT NULL | `false` |  | Không phải DLCN | true nếu lớp có bộ phân loại độ tươi. |

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~60.

### `vision_class_ingredients`

Ánh xạ lớp thị giác sang nguyên liệu (một lớp có thể ứng với nhiều nguyên liệu).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `vision_class_id` | `smallint` | NOT NULL |  | `FK → vision_classes(id); PK (vision_class_id, ingredient_id)` | Không phải DLCN | Lớp thị giác. |
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id); PK (vision_class_id, ingredient_id)` | Không phải DLCN | Nguyên liệu. |
| `is_default` | `boolean` | NOT NULL | `false` |  | Không phải DLCN | true nếu là nguyên liệu gán sẵn cho chip khi mô hình phát hiện lớp này. |

Chỉ mục:

- `ux_vision_class_ingredients_default`: `UNIQUE btree (vision_class_id) WHERE is_default` — Mỗi lớp thị giác tối đa một nguyên liệu mặc định.

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~100.

## M05 — module `profile`

Hồ sơ (cột sức khỏe mã hoá), dị ứng, chế độ ăn, món hay ăn, cài đặt; công thức BMR/TEE/E_mâm; get_meal_constraints().

### `profiles`

Hồ sơ dinh dưỡng của người dùng (users 1 — 0..1 profiles). Cột *_enc mã hoá AES-GCM ở tầng ứng dụng, chỉ module profile giải mã và mỗi lần giải mã ghi audit_log.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE; PK` | DLCN nhạy cảm | Người dùng sở hữu hồ sơ (khoá chính đồng thời là khoá ngoại). |
| `sex_enc` | `bytea` | NULL |  |  | DLCN nhạy cảm | Giới tính, mã hoá AES-GCM; NULL khi chưa đồng ý health_profile (BR-CONSENT-02). |
| `birth_year_enc` | `bytea` | NULL |  |  | DLCN nhạy cảm | Năm sinh, mã hoá AES-GCM; dùng kiểm ≥ 18 tuổi và chọn khoảng tuổi BMR (BR-NUT-01). |
| `height_cm_enc` | `bytea` | NULL |  |  | DLCN nhạy cảm | Chiều cao (cm), mã hoá AES-GCM. |
| `weight_kg_enc` | `bytea` | NULL |  |  | DLCN nhạy cảm | Cân nặng (kg), mã hoá AES-GCM; đầu vào BMR (BR-NUT-01). |
| `enc_key_id` | `text` | NULL |  |  | Không phải DLCN | Định danh khoá đã mã hoá các cột *_enc (phục vụ xoay khoá). |
| `activity_level` | `activity_level_t` | NULL |  |  | DLCN nhạy cảm | Mức vận động: light, moderate, heavy; PAL 1,50 / 1,75 / 2,00 (BR-NUT-02). |
| `goal` | `goal_t` | NULL |  |  | DLCN nhạy cảm | Mục tiêu: maintain (giữ cân), lose (giảm cân), expert (theo chuyên gia). |
| `kcal_target` | `integer` | NULL |  | `CHECK (((kcal_target >= 800) AND (kcal_target <= 5000)))` | DLCN nhạy cảm | Năng lượng mục tiêu E, kcal/ngày (800–5000); NULL là chưa có mục tiêu. |
| `kcal_source` | `kcal_source_t` | NULL |  |  | DLCN nhạy cảm | Nguồn của kcal_target: suggested (công thức gợi ý), user (tự nhập), expert (chuyên gia đặt). |
| `diet_code` | `text` | NULL |  | `FK → diets(code)` | DLCN cơ bản | Chế độ ăn; NULL là không theo chế độ nào. |
| `updated_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_profiles_enc_key`: `CHECK (((num_nonnulls(sex_enc, birth_year_enc, height_cm_enc, weight_kg_enc) = 0) OR (enc_key_id IS NOT NULL)))` — Có cột *_enc thì phải biết khoá đã mã hoá (NFR-PRIV-01).
- `ck_profiles_expert`: `CHECK (((kcal_source IS NULL) OR ((NOT (goal IS DISTINCT FROM 'expert'::goal_t)) = (kcal_source = 'expert'::kcal_source_t))))` — goal = expert khi và chỉ khi kcal_source = expert, xét khi đã có kcal_source (BR-NUT-03: mục tiêu chuyên gia ghi đè công thức).
- `ck_profiles_kcal_pair`: `CHECK (((kcal_target IS NULL) = (kcal_source IS NULL)))` — Mục tiêu và nguồn mục tiêu cùng có hoặc cùng trống (BR-NUT-01..04).

Lưu/Xoá: Chỉ số cơ thể: đến khi rút health_profile (đặt NULL ≤ 24 giờ, BR-CONSENT-04) hoặc xoá tài khoản. Quy mô ước lượng: ~10^3.

Ràng buộc chỉ kiểm ở service: Tuổi ≥ 18 kiểm sau giải mã (BR-NUT-01).

Ghi chú thiết kế: users 1 — 0..1 profiles; cột *_enc mã hoá AES-GCM tầng ứng dụng, chỉ module profile giải mã (ghi audit_log).

### `user_allergens`

Nhóm dị ứng người dùng đã khai (BR-ALG-01).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE; PK (user_id, allergen_code)` | DLCN nhạy cảm | Người dùng. |
| `allergen_code` | `text` | NOT NULL |  | `FK → allergen_groups(code); PK (user_id, allergen_code)` | DLCN nhạy cảm | Nhóm dị ứng. |

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~2 × 10^3.

### `user_favorite_recipes`

Món hay ăn người dùng chọn khi thiết lập (tối đa 5, kiểm ở service); dùng xếp hạng nội dung khi không có đồng ý personalization (BR-CONSENT-03).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE; PK (user_id, recipe_id)` | DLCN cơ bản | Người dùng. |
| `recipe_id` | `uuid` | NOT NULL |  | `FK → recipes(id); PK (user_id, recipe_id)` | DLCN cơ bản | Món. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm chọn. |

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~5 × 10^3.

Ràng buộc chỉ kiểm ở service: Tối đa 5 món, chỉ món published (FR-10-11).

Ghi chú thiết kế: tối đa 5 món (kiểm ở service).

### `user_settings`

Cài đặt bếp và mặc định của người dùng.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE; PK` | DLCN cơ bản | Người dùng (khoá chính đồng thời là khoá ngoại). |
| `burners` | `smallint` | NOT NULL | `2` | `CHECK (((burners >= 1) AND (burners <= 4)))` | DLCN cơ bản | Số họng bếp (1–4), mặc định 2; ràng buộc lịch nấu (BR-COOK-01). |
| `default_persons` | `smallint` | NOT NULL | `2` | `CHECK (((default_persons >= 1) AND (default_persons <= 6)))` | DLCN cơ bản | Số người ăn mặc định (1–6), mặc định 2. |
| `timezone` | `text` | NOT NULL | `'Asia/Ho_Chi_Minh'::text` |  | DLCN cơ bản | Múi giờ IANA dùng hiển thị và tính ngày (v_journal_days); mặc định Asia/Ho_Chi_Minh; trigger trg_user_settings_timezone chỉ nhận tên có trong pg_timezone_names. |
| `updated_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz). |

Trigger:

- `trg_user_settings_timezone` (before insert or update of timezone): `trg_user_settings_timezone()`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~10^3.

## M06 — module `pantry`

Lô, giao dịch kho, quy đổi lượng, độ gấp u (tính lúc đọc).

### `pantry_lots`

Lô nguyên liệu trong kho của người dùng; mỗi lần thêm đồ tạo một lô (BR-PANTRY-01). Lượng hiện tại = initial + Σ giao dịch (v_pantry_lot_balance); độ gấp u tính lúc đọc, không lưu (BR-FRESH-05).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh lô (UUID). |
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE` | DLCN cơ bản | Chủ kho. |
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id)` | DLCN cơ bản | Nguyên liệu. |
| `initial_g_min` | `numeric` | NOT NULL |  | `CHECK ((initial_g_min >= (0)::numeric))` | DLCN cơ bản | Cận dưới lượng ban đầu, gam lúc mua (≥ 0, BR-QTY-01). |
| `initial_g_max` | `numeric` | NOT NULL |  |  | DLCN cơ bản | Cận trên lượng ban đầu, gam lúc mua (≥ initial_g_min). |
| `acquired_at` | `timestamp with time zone` | NOT NULL |  |  | DLCN cơ bản | Ngày mua người dùng nhập, nếu không thì lần đầu thấy trong ảnh quét; mốc tính u_time (BR-FRESH-01). |
| `acquired_basis` | `acquired_basis_t` | NOT NULL |  |  | DLCN cơ bản | Căn cứ của acquired_at: purchase_date_entered (người dùng nhập) hoặc first_seen (lần đầu thấy) (BR-FRESH-03). |
| `status` | `lot_status_t` | NOT NULL | `'in_stock'::lot_status_t` |  | DLCN cơ bản | Trạng thái lô: in_stock, used_up, discarded, not_seen (quét toàn tủ không thấy, BR-PANTRY-03). |
| `p_tuoi` | `real` | NULL |  |  | DLCN cơ bản | Xác suất lớp tươi ở lần quan sát mới nhất của lô (bộ phân loại độ tươi đã hiệu chỉnh nhiệt độ, BR-FRESH-02). |
| `p_dung_som` | `real` | NULL |  |  | DLCN cơ bản | Xác suất lớp nên dùng sớm ở lần quan sát mới nhất. |
| `p_dung_ngay` | `real` | NULL |  |  | DLCN cơ bản | Xác suất lớp dùng ngay ở lần quan sát mới nhất. |
| `p_kiem_tra` | `real` | NULL |  |  | DLCN cơ bản | Xác suất lớp kiểm tra trước khi dùng ở lần quan sát mới nhất. |
| `freshness_observed_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm quan sát độ tươi mới nhất; NULL nếu lô chưa có ảnh độ tươi (khi đó u = u_time). |
| `freshness_model_version_id` | `uuid` | NULL |  | `FK → model_versions(id)` | DLCN cơ bản | Phiên bản bộ phân loại độ tươi đã cho các xác suất p_*. |
| `user_checked_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm người dùng xác nhận đồ ở mức kiểm tra vẫn dùng được (BR-FRESH-04). |
| `source_scan_item_id` | `uuid` | NULL |  | `FK → scan_items(id) ON DELETE SET NULL` | DLCN cơ bản | Chip quét đã tạo ra lô; NULL nếu nhập tay hoặc chip đã bị xoá. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm tạo bản ghi (giờ server, timestamptz). |
| `updated_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_pantry_lots_1`: `CHECK ((initial_g_min <= initial_g_max))`
- `ck_pantry_lots_p_group`: `CHECK ((num_nulls(p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra) = ANY (ARRAY[0, 4])))` — Bốn xác suất độ tươi cùng NULL hoặc cùng có giá trị (BR-FRESH-02).
- `ck_pantry_lots_p_observed`: `CHECK (((p_tuoi IS NULL) OR (freshness_observed_at IS NOT NULL)))`
- `ck_pantry_lots_p_range`: `CHECK ((((p_tuoi >= (0)::double precision) AND (p_tuoi <= (1)::double precision)) AND ((p_dung_som >= (0)::double precision) AND (p_dung_som <= (1)::double precision)) AND ((p_dung_ngay >= (0)::double precision) AND (p_dung_ngay <= (1)::double precision)) AND ((p_kiem_tra >= (0)::double precision) AND (p_kiem_tra <= (1)::double precision))))`
- `ck_pantry_lots_p_sum`: `CHECK (((p_tuoi IS NULL) OR (abs(((((p_tuoi + p_dung_som) + p_dung_ngay) + p_kiem_tra) - (1)::double precision)) <= (0.01)::double precision)))` — Phân phối bốn lớp có tổng 1 (sai số làm tròn 0,01) (BR-FRESH-02).

Chỉ mục:

- `ix_pantry_lots_source_scan_item_id`: `btree (source_scan_item_id)`
- `ix_pantry_lots_user_id_status`: `btree (user_id, status)`

Trigger:

- `trg_pantry_lots_write_once` (before update): `trg_write_once('user_id')`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~10^5.

Ràng buộc chỉ kiểm ở service: Lô sinh từ quét phải cùng chủ với lần quét (04 D9).

Ghi chú thiết kế: lượng hiện tại = initial + Σ giao dịch (view v_pantry_lot_balance); u tính lúc đọc (BR-FRESH-05); p_* là quan sát mới nhất của chính lô.

### `pantry_transactions`

Giao dịch kho, chỉ ghi thêm; hoàn tác bằng giao dịch đảo trỏ reverses_id (BR-PANTRY-02).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `bigint` | NOT NULL | `GENERATED ALWAYS AS IDENTITY` | `PK` | DLCN cơ bản | Số thứ tự giao dịch (identity). |
| `lot_id` | `uuid` | NOT NULL |  | `FK → pantry_lots(id) ON DELETE CASCADE` | DLCN cơ bản | Lô bị thay đổi. |
| `delta_g_min` | `numeric` | NOT NULL |  |  | DLCN cơ bản | Thay đổi cận dưới, gam lúc mua; âm là trừ. |
| `delta_g_max` | `numeric` | NOT NULL |  |  | DLCN cơ bản | Thay đổi cận trên, gam lúc mua; âm là trừ. |
| `reason` | `pantry_tx_reason_t` | NOT NULL |  |  | DLCN cơ bản | Lý do: scan_add, cook_deduct, manual_edit, discard, undo. |
| `ref_type` | `pantry_ref_type_t` | NULL |  |  | DLCN cơ bản | Loại đối tượng gây ra giao dịch: scan, cook_session, user; NULL nếu không có. |
| `ref_id` | `uuid` | NULL |  |  | DLCN cơ bản | Id của đối tượng theo ref_type (scans.id, cook_sessions.id hoặc users.id = chủ lô); tham chiếu đa hình: không có khoá ngoại, trigger trg_pantry_transactions_ref kiểm tồn tại và cùng chủ lúc ghi; đi cặp với ref_type (ck_pantry_transactions_ref_pair). |
| `reverses_id` | `bigint` | NULL |  | `FK → pantry_transactions(id); UNIQUE` | DLCN cơ bản | Giao dịch bị đảo bởi giao dịch này; khác NULL đúng khi reason = undo (ck_pantry_transactions_undo); duy nhất: mỗi giao dịch bị đảo tối đa một lần. |
| `urgency_at_event` | `real` | NULL |  | `CHECK ((urgency_at_event >= (0)::double precision))` | DLCN cơ bản | Độ gấp u của lô tại thời điểm giao dịch (ảnh chụp, BR-FRESH-05); dùng đếm lô gấp được dùng kịp trong nhật ký. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm ghi giao dịch. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_pantry_transactions_not_self`: `CHECK ((reverses_id <> id))`
- `ck_pantry_transactions_ref_pair`: `CHECK (((ref_type IS NULL) = (ref_id IS NULL)))`
- `ck_pantry_transactions_undo`: `CHECK (((reason = 'undo'::pantry_tx_reason_t) = (reverses_id IS NOT NULL)))` — reason = undo khi và chỉ khi có reverses_id (BR-PANTRY-02).
- `uq_pantry_transactions_reverses_id`: `UNIQUE (reverses_id)` — Mỗi giao dịch bị đảo tối đa một lần (BR-PANTRY-02).

Chỉ mục:

- `ix_pantry_transactions_lot_id`: `btree (lot_id)`
- `ix_pantry_transactions_ref`: `btree (ref_type, ref_id)` — Tìm giao dịch theo đối tượng gây ra (hoàn tác UC21, nhật ký v_journal_days).

Trigger:

- `trg_pantry_transactions_append_only` (before delete or update): `trg_append_only()`
- `trg_pantry_transactions_no_truncate` (before truncate): `trg_append_only()`
- `trg_pantry_transactions_ref` (before insert): `trg_pantry_transactions_ref()` — Thay cho khoá ngoại của tham chiếu đa hình (ref_type, ref_id): kiểm tồn tại và cùng chủ lô (D13).

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ) (qua lô); chỉ ghi thêm. Quy mô ước lượng: ~5 × 10^5.

Ràng buộc chỉ kiểm ở service: Trừ kho theo lô gấp nhất trước (BR-PANTRY-02).

Ghi chú thiết kế: chỉ ghi thêm; hoàn tác = ghi giao dịch đảo trỏ reverses_id.

### View `v_pantry_lot_balance`

Lượng hiện tại của lô [g_min, g_max] = initial + Σ delta, chặn dưới 0; kèm trạng thái lô.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `lot_id` | `uuid` | Lô. |
| `user_id` | `uuid` | Chủ kho. |
| `ingredient_id` | `uuid` | Nguyên liệu. |
| `status` | `lot_status_t` | Trạng thái lô. |
| `acquired_at` | `timestamp with time zone` | Ngày mua hoặc lần đầu thấy. |
| `g_min` | `numeric` | Cận dưới lượng hiện tại, gam (≥ 0). |
| `g_max` | `numeric` | Cận trên lượng hiện tại, gam (≥ 0). |
| `n_transactions` | `bigint` | Số giao dịch đã ghi cho lô. |

## M07 — module `mlops`

Phiên bản mô hình, bản đồ lớp, con trỏ triển khai, nạp mô hình.

### `model_versions`

Phiên bản mô hình học máy đã đăng ký (UC29). Bản đang chạy xác định duy nhất qua model_deployments.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | Không phải DLCN | Định danh phiên bản (UUID). |
| `name` | `model_name_t` | NOT NULL |  |  | Không phải DLCN | Loại mô hình: detector, freshness, ranker, substitution. |
| `version` | `text` | NOT NULL |  |  | Không phải DLCN | Nhãn phiên bản, duy nhất trong mỗi loại. |
| `artifact_key` | `text` | NOT NULL |  |  | Không phải DLCN | Khoá tệp trọng số trong kho lưu trữ. |
| `sha256` | `bytea` | NOT NULL |  |  | Không phải DLCN | SHA-256 của tệp trọng số, kiểm khi nạp. |
| `preprocess_version` | `text` | NULL |  |  | Không phải DLCN | Phiên bản bước tiền xử lý ảnh đi kèm; NULL với mô hình không dùng ảnh. |
| `metrics` | `jsonb` | NOT NULL |  |  | Không phải DLCN | Chỉ số đánh giá (JSON), là báo cáo, không truy vấn. |
| `gate_report_key` | `text` | NULL |  |  | Không phải DLCN | Khoá tệp báo cáo kiểm định; NULL nếu chưa kiểm định. |
| `mlflow_run_id` | `text` | NULL |  |  | Không phải DLCN | Mã lượt chạy MLflow sinh ra mô hình. |
| `status` | `model_status_t` | NOT NULL | `'candidate'::model_status_t` |  | Không phải DLCN | Trạng thái: candidate, validated, rejected, retired. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | Không phải DLCN | Thời điểm đăng ký. |

Ràng buộc nhiều cột hoặc có chú thích:

- `uq_model_versions_id_name`: `UNIQUE (id, name)` — Siêu khoá làm đích khoá ngoại ghép từ model_deployments.
- `uq_model_versions_name_version`: `UNIQUE (name, version)`

Lưu/Xoá: Không xoá (retired). Quy mô ước lượng: ~50.

Ràng buộc chỉ kiểm ở service: Chỉ phiên bản validated được triển khai (UC30).

Ghi chú thiết kế: metrics là báo cáo không truy vấn (jsonb hợp lý); bản đang chạy xác định DUY NHẤT qua model_deployments.

### `model_version_classes`

Bản đồ chỉ số đầu ra của mô hình sang lớp thị giác, theo từng phiên bản.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `model_version_id` | `uuid` | NOT NULL |  | `FK → model_versions(id); PK (model_version_id, class_index)` | Không phải DLCN | Phiên bản mô hình. |
| `class_index` | `smallint` | NOT NULL |  | `CHECK ((class_index >= 0)); PK (model_version_id, class_index)` | Không phải DLCN | Chỉ số lớp ở đầu ra mô hình. |
| `vision_class_id` | `smallint` | NOT NULL |  | `FK → vision_classes(id)` | Không phải DLCN | Lớp thị giác tương ứng. |

Ràng buộc nhiều cột hoặc có chú thích:

- `uq_model_version_classes_model_version_id_vision_class_id`: `UNIQUE (model_version_id, vision_class_id)` — Mỗi lớp thị giác xuất hiện một lần trong đầu ra của một phiên bản mô hình (khoá ứng viên thứ hai).

Lưu/Xoá: Theo phiên bản mô hình. Quy mô ước lượng: ~10^3.

### `model_deployments`

Con trỏ triển khai: mỗi loại mô hình có đúng một phiên bản đang chạy (UC30).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `name` | `model_name_t` | NOT NULL |  | `FK (active_version_id, name) → model_versions(id, name); FK (previous_version_id, name) → model_versions(id, name); PK` | Không phải DLCN | Loại mô hình (khoá chính). |
| `active_version_id` | `uuid` | NOT NULL |  | `FK (active_version_id, name) → model_versions(id, name); UNIQUE` | Không phải DLCN | Phiên bản đang chạy. |
| `previous_version_id` | `uuid` | NULL |  | `FK (previous_version_id, name) → model_versions(id, name)` | Không phải DLCN | Phiên bản chạy trước đó, dùng khi quay lui; NULL nếu chưa có. |
| `switched_at` | `timestamp with time zone` | NOT NULL |  |  | Không phải DLCN | Thời điểm chuyển phiên bản gần nhất. |
| `switched_by` | `uuid` | NULL |  | `FK → users(id) ON DELETE SET NULL` | Không phải DLCN | Nhân sự đã chuyển phiên bản; NULL nếu tài khoản đã xoá. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_model_deployments_previous`: `CHECK ((previous_version_id <> active_version_id))`
- `fk_model_deployments_active_version_id_name`: `FOREIGN KEY (active_version_id, name) REFERENCES model_versions(id, name)` — Con trỏ chỉ trỏ phiên bản cùng loại mô hình (UC30).
- `uq_model_deployments_active_version_id`: `UNIQUE (active_version_id)` — Một phiên bản là bản đang chạy của tối đa một con trỏ (khoá ứng viên).

Lưu/Xoá: Một dòng mỗi loại mô hình. Quy mô ước lượng: 4.

## M08 — module `scan`

Nhận ảnh, job suy luận (worker), chip, xác nhận vào kho.

### `scans`

Một lượt quét nguyên liệu (UC12): 1–2 ảnh, job suy luận chạy ở worker.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh lượt quét (UUID). |
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE` | DLCN cơ bản | Người quét. |
| `mode` | `scan_mode_t` | NOT NULL |  |  | DLCN cơ bản | Chế độ: fridge (toàn tủ) hoặc haul (đồ vừa mua) (BR-PANTRY-03). |
| `status` | `scan_status_t` | NOT NULL |  |  | DLCN cơ bản | Trạng thái: queued, processing, done, failed, expired, confirmed, discarded. |
| `error_code` | `text` | NULL |  |  | DLCN cơ bản | Mã lỗi khi status = failed; NULL nếu không lỗi. |
| `attempts` | `smallint` | NOT NULL | `0` | `CHECK ((attempts >= 0))` | DLCN cơ bản | Số lần worker đã thử xử lý. |
| `detector_version_id` | `uuid` | NULL |  | `FK → model_versions(id)` | DLCN cơ bản | Phiên bản mô hình phát hiện đã dùng. |
| `classifier_version_id` | `uuid` | NULL |  | `FK → model_versions(id)` | DLCN cơ bản | Phiên bản bộ phân loại độ tươi đã dùng. |
| `preprocess_version` | `text` | NULL |  |  | DLCN cơ bản | Phiên bản tiền xử lý ảnh đã dùng. |
| `enqueued_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm đưa job vào hàng đợi. |
| `started_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm worker bắt đầu xử lý. |
| `finished_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm worker xử lý xong (done hoặc failed). |
| `confirmed_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm người dùng xác nhận ghi kho (BR-SCAN-02). |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm tạo lượt quét. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_scans_confirmed`: `CHECK (((status = 'confirmed'::scan_status_t) = (confirmed_at IS NOT NULL)))` — confirmed_at có giá trị đúng khi status = confirmed (BR-SCAN-02).

Chỉ mục:

- `ix_scans_stuck`: `btree (started_at) WHERE (status = ANY (ARRAY['queued'::scan_status_t, 'processing'::scan_status_t]))` — Sweeper tìm job quét kẹt (UC34).
- `ix_scans_user_id_created_at`: `btree (user_id, created_at DESC)`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~5 × 10^4.

### `scan_images`

Ảnh của lượt quét; ảnh gốc xoá sau 30 ngày trừ khi đã đồng ý góp ảnh (BR-RETAIN-01).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh ảnh (UUID). |
| `scan_id` | `uuid` | NOT NULL |  | `FK → scans(id) ON DELETE CASCADE` | DLCN cơ bản | Lượt quét. |
| `ordinal` | `smallint` | NOT NULL |  | `CHECK (((ordinal >= 1) AND (ordinal <= 2)))` | DLCN cơ bản | Thứ tự ảnh trong lượt quét (1–2). |
| `shelf_group` | `smallint` | NOT NULL | `1` | `CHECK ((shelf_group >= 1))` | DLCN cơ bản | Nhóm ngăn: cùng số là cùng ngăn (số đếm lấy max), khác số thì cộng (BR-SCAN-01). |
| `storage_key` | `text` | NOT NULL |  | `UNIQUE` | DLCN cơ bản | Khoá tệp ảnh trong kho lưu trữ, duy nhất. |
| `width` | `integer` | NOT NULL |  |  | DLCN cơ bản | Chiều rộng ảnh, pixel. |
| `height` | `integer` | NOT NULL |  |  | DLCN cơ bản | Chiều cao ảnh, pixel. |
| `contributed` | `boolean` | NOT NULL | `false` |  | DLCN cơ bản | true nếu người dùng góp ảnh (đồng ý photo_contribution); ảnh không bị xoá sau 30 ngày. |
| `purged_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm tệp ảnh đã bị xoá (UC32); NULL nếu còn. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_scan_images_size`: `CHECK (((width > 0) AND (height > 0)))`
- `uq_scan_images_scan_id_ordinal`: `UNIQUE (scan_id, ordinal)`

Chỉ mục:

- `ix_scan_images_purge`: `btree (scan_id) WHERE ((purged_at IS NULL) AND (NOT contributed))` — Job xoá ảnh quá hạn tìm ảnh chưa xoá và chưa góp (UC32, BR-RETAIN-01).

Lưu/Xoá: Ảnh gốc xoá sau 30 ngày (UC32) trừ khi đã góp; ảnh góp đến khi rút photo_contribution (BR-RETAIN-01, BR-CONSENT-04). Quy mô ước lượng: ~10^5.

### `scan_items`

Chip kết quả quét: một nguyên liệu và số lượng chờ người dùng xác nhận; chỉ ghi vào kho khi xác nhận (BR-SCAN-02).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh chip (UUID). |
| `scan_id` | `uuid` | NOT NULL |  | `FK → scans(id) ON DELETE CASCADE` | DLCN cơ bản | Lượt quét. |
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id)` | DLCN cơ bản | Nguyên liệu hiện tại của chip (sau khi người dùng sửa nếu có). |
| `origin` | `scan_item_origin_t` | NOT NULL |  |  | DLCN cơ bản | Nguồn chip: model (mô hình phát hiện) hoặc user_added (người dùng thêm). |
| `model_count` | `smallint` | NULL |  | `CHECK ((model_count >= 0))` | DLCN cơ bản | Số đếm do mô hình đưa ra; NULL với chip người dùng thêm hoặc lớp không đếm. |
| `final_count` | `smallint` | NULL |  | `CHECK (((final_count >= 0) AND (final_count <= 99)))` | DLCN cơ bản | Số đếm sau khi người dùng xác nhận hoặc sửa. |
| `qty_level` | `qty_level_t` | NULL |  |  | DLCN cơ bản | Mức lượng it/vua/nhieu với nguyên liệu không đếm được (BR-QTY-02). |
| `user_action` | `scan_user_action_t` | NOT NULL | `'kept'::scan_user_action_t` |  | DLCN cơ bản | Thao tác người dùng: kept, relabeled, deleted, edited. |
| `original_ingredient_id` | `uuid` | NULL |  | `FK → ingredients(id)` | DLCN cơ bản | Nguyên liệu mô hình đề xuất ban đầu khi người dùng đổi nhãn; NULL nếu không đổi. |
| `user_freshness` | `freshness_t` | NULL |  |  | DLCN cơ bản | Nhãn độ tươi người dùng chọn: tuoi, dung_som, dung_ngay, kiem_tra; NULL nếu không chọn. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm tạo bản ghi (giờ server, timestamptz). |
| `updated_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_scan_items_final_count`: `CHECK (((final_count >= 0) AND (final_count <= 99)))` — Số đếm người dùng nhập 0..99 (UC13 5a).
- `ck_scan_items_original`: `CHECK (((original_ingredient_id IS NULL) OR ((origin = 'model'::scan_item_origin_t) AND (original_ingredient_id <> ingredient_id))))` — Nhãn gốc chỉ có ở chip của mô hình và khác nhãn hiện tại.
- `ck_scan_items_relabeled`: `CHECK (((user_action <> 'relabeled'::scan_user_action_t) OR (original_ingredient_id IS NOT NULL)))` — Chip đã đổi nhãn phải giữ nhãn gốc (FR-13-03).
- `ck_scan_items_user_added`: `CHECK (((origin = 'model'::scan_item_origin_t) OR ((model_count IS NULL) AND (user_action <> 'deleted'::scan_user_action_t))))` — Chip người dùng thêm không có số đếm mô hình và bị xoá hẳn chứ không đánh dấu deleted (FR-13-06).

Chỉ mục:

- `ix_scan_items_scan_id`: `btree (scan_id)`

Trigger:

- `trg_scan_items_write_once` (before update): `trg_write_once('scan_id', 'origin', 'model_count')`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~5 × 10^5.

Ràng buộc chỉ kiểm ở service: Một chip mỗi nguyên liệu trong một lần quét (FR-13-05).

Ghi chú thiết kế: chip; ghi vào kho chỉ khi xác nhận (BR-SCAN-02).

### `detections`

Khung phát hiện của mô hình trên từng ảnh, kèm xác suất độ tươi.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `bigint` | NOT NULL | `GENERATED ALWAYS AS IDENTITY` | `PK` | DLCN cơ bản | Số thứ tự khung (identity). |
| `scan_image_id` | `uuid` | NOT NULL |  | `FK → scan_images(id) ON DELETE CASCADE` | DLCN cơ bản | Ảnh chứa khung. |
| `scan_item_id` | `uuid` | NULL |  | `FK → scan_items(id) ON DELETE SET NULL` | DLCN cơ bản | Chip mà khung được gộp vào; NULL nếu chưa gộp hoặc chip đã xoá. |
| `vision_class_id` | `smallint` | NOT NULL |  | `FK → vision_classes(id)` | DLCN cơ bản | Lớp thị giác dự đoán. |
| `x1` | `real` | NOT NULL |  |  | DLCN cơ bản | Toạ độ trái, chuẩn hoá theo chiều rộng ảnh [0, 1]. |
| `y1` | `real` | NOT NULL |  |  | DLCN cơ bản | Toạ độ trên, chuẩn hoá theo chiều cao ảnh [0, 1]. |
| `x2` | `real` | NOT NULL |  |  | DLCN cơ bản | Toạ độ phải, chuẩn hoá [0, 1], lớn hơn x1. |
| `y2` | `real` | NOT NULL |  |  | DLCN cơ bản | Toạ độ dưới, chuẩn hoá [0, 1], lớn hơn y1. |
| `confidence` | `real` | NOT NULL |  | `CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))` | DLCN cơ bản | Độ tin cậy của khung do mô hình phát hiện đưa ra. |
| `p_tuoi` | `real` | NULL |  |  | DLCN cơ bản | Xác suất lớp tươi của khung; NULL nếu lớp không có bộ phân loại độ tươi. |
| `p_dung_som` | `real` | NULL |  |  | DLCN cơ bản | Xác suất lớp nên dùng sớm của khung. |
| `p_dung_ngay` | `real` | NULL |  |  | DLCN cơ bản | Xác suất lớp dùng ngay của khung. |
| `p_kiem_tra` | `real` | NULL |  |  | DLCN cơ bản | Xác suất lớp kiểm tra trước khi dùng của khung. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_detections_1`: `CHECK ((((0)::double precision <= x1) AND (x1 < x2) AND (x2 <= (1)::double precision) AND ((0)::double precision <= y1) AND (y1 < y2) AND (y2 <= (1)::double precision)))`
- `ck_detections_p_group`: `CHECK ((num_nulls(p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra) = ANY (ARRAY[0, 4])))` — Bốn xác suất độ tươi cùng NULL hoặc cùng có giá trị (BR-FRESH-02).
- `ck_detections_p_range`: `CHECK ((((p_tuoi >= (0)::double precision) AND (p_tuoi <= (1)::double precision)) AND ((p_dung_som >= (0)::double precision) AND (p_dung_som <= (1)::double precision)) AND ((p_dung_ngay >= (0)::double precision) AND (p_dung_ngay <= (1)::double precision)) AND ((p_kiem_tra >= (0)::double precision) AND (p_kiem_tra <= (1)::double precision))))`
- `ck_detections_p_sum`: `CHECK (((p_tuoi IS NULL) OR (abs(((((p_tuoi + p_dung_som) + p_dung_ngay) + p_kiem_tra) - (1)::double precision)) <= (0.01)::double precision)))`

Chỉ mục:

- `ix_detections_scan_image_id`: `btree (scan_image_id)`
- `ix_detections_scan_item_id`: `btree (scan_item_id)`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~10^6.

## M09 — module `events`

Ghi tương tác có cổng đồng ý, chống trùng theo event_id.

### `interactions`

Tương tác của người dùng với món, chỉ ghi khi có đồng ý personalization (BR-CONSENT-03); chống trùng theo event_id. Khoá ngoại ghép (meal_plan_id, user_id) bảo đảm user_id khớp chủ mâm.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL |  | `PK` | DLCN nhạy cảm | event_id do app sinh (UUID); gửi lại cùng id không tạo bản ghi mới. |
| `user_id` | `uuid` | NOT NULL |  | `FK (meal_plan_id, user_id) → meal_plans(id, user_id) ON DELETE CASCADE; FK → users(id) ON DELETE CASCADE` | DLCN nhạy cảm | Người dùng. |
| `recipe_id` | `uuid` | NOT NULL |  | `FK (meal_plan_item_id, meal_plan_id, recipe_id) → meal_plan_items(id, meal_plan_id, recipe_id) ON DELETE SET NULL; FK → recipes(id)` | DLCN nhạy cảm | Món. |
| `meal_plan_id` | `uuid` | NULL |  | `FK (meal_plan_id, user_id) → meal_plans(id, user_id) ON DELETE CASCADE; FK (meal_plan_item_id, meal_plan_id, recipe_id) → meal_plan_items(id, meal_plan_id, recipe_id) ON DELETE SET NULL` | DLCN nhạy cảm | Mâm chứa món; NULL nếu tương tác ngoài mâm. |
| `meal_plan_item_id` | `uuid` | NULL |  | `FK (meal_plan_item_id, meal_plan_id, recipe_id) → meal_plan_items(id, meal_plan_id, recipe_id) ON DELETE SET NULL` | DLCN nhạy cảm | Dòng món trong mâm; NULL nếu không gắn dòng nào. Khoá ngoại ghép (meal_plan_item_id, meal_plan_id, recipe_id) buộc mâm và món khớp dòng đó. |
| `type` | `interaction_type_t` | NOT NULL |  |  | DLCN nhạy cảm | Loại: served, viewed, swapped, cooked, liked, disliked, undone. |
| `position` | `smallint` | NULL |  | `CHECK (("position" >= 0))` | DLCN nhạy cảm | Vị trí món trong danh sách hiển thị; NULL nếu không áp dụng. |
| `swap_reason` | `swap_reason_t` | NULL |  |  | DLCN nhạy cảm | Lý do đổi khi type = swapped (BR-SWAP-01). |
| `ranker_version_id` | `uuid` | NULL |  | `FK → model_versions(id)` | DLCN nhạy cảm | Phiên bản mô hình xếp hạng lúc hiển thị. |
| `propensity` | `real` | NULL |  | `CHECK (((propensity > (0)::double precision) AND (propensity <= (1)::double precision)))` | DLCN nhạy cảm | Xác suất món được hiển thị theo chính sách xếp hạng lúc đó; dùng đánh giá ngoại tuyến. |
| `occurred_at` | `timestamp with time zone` | NOT NULL |  |  | DLCN nhạy cảm | Thời điểm xảy ra theo đồng hồ app. |
| `received_at` | `timestamp with time zone` | NOT NULL |  |  | DLCN nhạy cảm | Thời điểm server nhận. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_interactions_item_needs_plan`: `CHECK (((meal_plan_item_id IS NULL) OR (meal_plan_id IS NOT NULL)))` — Có dòng món thì phải có mâm, để khoá ngoại ghép không bị MATCH SIMPLE bỏ qua.
- `ck_interactions_swap_reason`: `CHECK (((swap_reason IS NULL) OR (type = 'swapped'::interaction_type_t)))`
- `fk_interactions_meal_plan_item_id_meal_plan_id_recipe_id`: `FOREIGN KEY (meal_plan_item_id, meal_plan_id, recipe_id) REFERENCES meal_plan_items(id, meal_plan_id, recipe_id) ON DELETE SET NULL (meal_plan_item_id)` — Sự kiện gắn dòng món thì mâm và món phải khớp dòng đó (D4); xoá dòng món chỉ đặt NULL meal_plan_item_id.

Chỉ mục:

- `ix_interactions_meal_plan_id_user_id`: `btree (meal_plan_id, user_id)`
- `ix_interactions_meal_plan_item_id`: `btree (meal_plan_item_id)`
- `ix_interactions_user_id_occurred_at`: `btree (user_id, occurred_at DESC)`

Trigger:

- `trg_interactions_append_only` (before delete or update): `trg_append_only()`
- `trg_interactions_no_truncate` (before truncate): `trg_append_only()`

Lưu/Xoá: Đến khi rút personalization hoặc xoá tài khoản (≤ 24 giờ, BR-CONSENT-04); chỉ ghi thêm. Quy mô ước lượng: ~10^6.

Ràng buộc chỉ kiểm ở service: Chỉ ghi khi có đồng ý personalization (BR-CONSENT-03).

Ghi chú thiết kế: FK ghép bảo đảm user_id khớp chủ mâm (không có phụ thuộc bắc cầu tự do); chỉ ghi khi có đồng ý personalization (BR-CONSENT-03).

## M10 — module `substitute`

Cặp thay thế, embedding nguyên liệu, gợi ý thay thế có lọc cứng, danh sách đi chợ.

### `substitution_pairs`

Cặp thay thế nguyên liệu có ngữ cảnh (slot, cách nấu), do nhóm biên soạn hoặc mô hình đề xuất (UC26).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | Không phải DLCN | Định danh cặp (UUID). |
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id)` | Không phải DLCN | Nguyên liệu gốc bị thiếu. |
| `substitute_id` | `uuid` | NOT NULL |  | `FK → ingredients(id)` | Không phải DLCN | Nguyên liệu thay thế, khác nguyên liệu gốc. |
| `context_slot` | `slot_t` | NULL |  |  | Không phải DLCN | Slot áp dụng; NULL là mọi slot. |
| `context_method_code` | `text` | NULL |  | `FK → cooking_methods(code)` | Không phải DLCN | Cách nấu áp dụng; NULL là mọi cách nấu. |
| `ratio` | `numeric` | NOT NULL | `1` | `CHECK ((ratio > (0)::numeric))` | Không phải DLCN | Tỷ lệ gam thay thế trên gam gốc, mặc định 1. |
| `score` | `real` | NOT NULL |  |  | Không phải DLCN | Điểm phù hợp của cặp, dùng xếp hạng gợi ý. |
| `source` | `text` | NOT NULL |  |  | Không phải DLCN | Nguồn của cặp (tài liệu, biên soạn, mô hình). |
| `curated` | `boolean` | NOT NULL |  |  | Không phải DLCN | true nếu do nhóm biên soạn và duyệt. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_substitution_pairs_1`: `CHECK ((ingredient_id <> substitute_id))`
- `uq_substitution_pairs_ctx`: `UNIQUE NULLS NOT DISTINCT (ingredient_id, substitute_id, context_slot, context_method_code)`

Lưu/Xoá: Dữ liệu tham chiếu. Quy mô ước lượng: ~10^3.

### `ingredient_embeddings`

Vector biểu diễn nguyên liệu (Word2Vec skip-gram trên danh sách nguyên liệu), theo phiên bản mô hình substitution.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id); PK (ingredient_id, model_version_id)` | Không phải DLCN | Nguyên liệu. |
| `model_version_id` | `uuid` | NOT NULL |  | `FK → model_versions(id); PK (ingredient_id, model_version_id)` | Không phải DLCN | Phiên bản mô hình sinh vector. |
| `vector` | `vector(100)` | NOT NULL |  |  | Không phải DLCN | Vector 100 chiều (pgvector); so sánh bằng cosine, không dùng chỉ mục ANN. |

Lưu/Xoá: Theo phiên bản mô hình. Quy mô ước lượng: ~300 mỗi phiên bản.

### `shopping_items`

Danh sách đi chợ của người dùng (UC18).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh mục (UUID). |
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE` | DLCN cơ bản | Người dùng. |
| `ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id)` | DLCN cơ bản | Nguyên liệu cần mua. |
| `qty_g` | `numeric` | NULL |  | `CHECK ((qty_g > (0)::numeric))` | DLCN cơ bản | Lượng cần mua, gam lúc mua; NULL nếu không ghi. |
| `note` | `text` | NULL |  |  | DLCN cơ bản | Ghi chú tự do của người dùng. |
| `status` | `shopping_status_t` | NOT NULL | `'open'::shopping_status_t` |  | DLCN cơ bản | Trạng thái: open, bought, dropped. |
| `source_meal_plan_item_id` | `uuid` | NULL |  | `FK → meal_plan_items(id) ON DELETE SET NULL` | DLCN cơ bản | Món trong mâm sinh ra mục này (Thiếu gì?, UC17); NULL nếu tự thêm hoặc món đã xoá. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm tạo bản ghi (giờ server, timestamptz). |
| `updated_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz). |

Chỉ mục:

- `ix_shopping_items_source_meal_plan_item_id`: `btree (source_meal_plan_item_id)`
- `ix_shopping_items_user_id_status`: `btree (user_id, status)`

Trigger:

- `trg_shopping_items_write_once` (before update): `trg_write_once('user_id')`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~5 × 10^4.

Ràng buộc chỉ kiểm ở service: Dòng sinh từ mâm phải cùng chủ với mâm (04 D9); chuyển trạng thái theo FR-18-07.

## M11 — module `meal`

Lọc cứng, xếp hạng gu, ghép mâm, đổi món, nhận thay thế, dòng lý do.

### `meal_plans`

Mâm cơm đề xuất cho một bữa (UC15). Các cột kcal là ảnh chụp lịch sử lúc tạo, không phải dẫn xuất lặp.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh mâm (UUID). |
| `user_id` | `uuid` | NOT NULL |  | `FK → users(id) ON DELETE CASCADE` | DLCN cơ bản | Người dùng. |
| `meal` | `meal_t` | NOT NULL |  |  | DLCN cơ bản | Bữa: lunch (trưa) hoặc dinner (tối). |
| `persons` | `smallint` | NOT NULL |  | `CHECK (((persons >= 1) AND (persons <= 6)))` | DLCN cơ bản | Số người ăn n (1–6, BR-TRAY-01). |
| `max_minutes` | `smallint` | NOT NULL |  | `CHECK (((max_minutes >= 10) AND (max_minutes <= 180)))` | DLCN cơ bản | Thời gian nấu tối đa người dùng chọn, phút (10–180, BR-TRAY-05). |
| `status` | `meal_plan_status_t` | NOT NULL | `'proposed'::meal_plan_status_t` |  | DLCN cơ bản | Trạng thái: proposed, accepted, cooked, abandoned, expired. |
| `e_target_kcal` | `numeric` | NULL |  | `CHECK ((e_target_kcal > (0)::numeric))` | DLCN nhạy cảm | Năng lượng mục tiêu của mâm E_mâm, kcal, chụp lúc tạo (BR-NUT-04, BR-TRAY-07); NULL khi chưa có mục tiêu. |
| `kcal_low` | `numeric` | NULL |  |  | DLCN cơ bản | Cận dưới khoảng kcal/người của mâm (BR-NUT-06); NULL khi chưa hiệu chỉnh. |
| `kcal_high` | `numeric` | NULL |  |  | DLCN cơ bản | Cận trên khoảng kcal/người của mâm; NULL khi chưa hiệu chỉnh. |
| `rice_bowls_per_person` | `numeric` | NULL |  | `CHECK ((((rice_bowls_per_person >= 0.5) AND (rice_bowls_per_person <= (3)::numeric)) AND ((rice_bowls_per_person * (2)::numeric) = trunc((rice_bowls_per_person * (2)::numeric)))))` | DLCN cơ bản | Số bát cơm gợi ý mỗi người (0,5–3, bước 0,5; BR-TRAY-03); NULL khi chưa có mục tiêu. |
| `reason_vi` | `text` | NOT NULL |  |  | DLCN cơ bản | Dòng lý do hiển thị cho người dùng. |
| `ranker_version_id` | `uuid` | NULL |  | `FK → model_versions(id)` | DLCN cơ bản | Phiên bản mô hình xếp hạng đã dùng; NULL khi dùng xếp hạng mặc định. |
| `params_version` | `text` | NOT NULL |  |  | DLCN cơ bản | Phiên bản bộ tham số cấu hình (ngưỡng, hệ số) lúc ghép mâm. Chưa có bảng tham số có phiên bản để làm đích khoá ngoại (đề xuất ở 04 mục 6). |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm tạo bản ghi (giờ server, timestamptz). |
| `updated_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_meal_plans_kcal_pair`: `CHECK (((kcal_low IS NULL) = (kcal_high IS NULL)))`
- `ck_meal_plans_kcal_range`: `CHECK (((kcal_low >= (0)::numeric) AND (kcal_low <= kcal_high)))` — Khoảng kcal hợp lệ (BR-NUT-06).
- `ck_meal_plans_rice_bowls`: `CHECK ((((rice_bowls_per_person >= 0.5) AND (rice_bowls_per_person <= (3)::numeric)) AND ((rice_bowls_per_person * (2)::numeric) = trunc((rice_bowls_per_person * (2)::numeric)))))` — Số bát cơm trong [0,5; 3], bước 0,5 (BR-TRAY-03).
- `uq_meal_plans_id_user_id`: `UNIQUE (id, user_id)`

Chỉ mục:

- `ix_meal_plans_user_id_created_at`: `btree (user_id, created_at DESC)`

Trigger:

- `trg_meal_plans_guard` (before update): `trg_meal_plans_guard()`
- `trg_meal_plans_write_once` (before update): `trg_write_once('user_id', 'meal', 'persons', 'e_target_kcal', 'ranker_version_id', 'params_version')`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~10^5.

Ghi chú thiết kế: e_target_kcal, kcal_low/high là ảnh chụp lịch sử, không phải dẫn xuất lặp.

### `meal_plan_coeater_allergens`

Nhóm dị ứng của người ăn cùng trong bữa này (BR-ALG-01); không lưu danh tính người ăn cùng.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `meal_plan_id` | `uuid` | NOT NULL |  | `FK → meal_plans(id) ON DELETE CASCADE; PK (meal_plan_id, allergen_code)` | DLCN nhạy cảm | Mâm. |
| `allergen_code` | `text` | NOT NULL |  | `FK → allergen_groups(code); PK (meal_plan_id, allergen_code)` | DLCN nhạy cảm | Nhóm dị ứng. |

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~10^4.

### `meal_plan_pins`

Lô người dùng ghim phải dùng trong mâm (tối đa 2, mỗi lô dùng ≥ 50% g_min; BR-TRAY-08).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `meal_plan_id` | `uuid` | NOT NULL |  | `FK → meal_plans(id) ON DELETE CASCADE; PK (meal_plan_id, lot_id)` | DLCN cơ bản | Mâm. |
| `lot_id` | `uuid` | NOT NULL |  | `FK → pantry_lots(id) ON DELETE CASCADE; PK (meal_plan_id, lot_id)` | DLCN cơ bản | Lô được ghim. |

Chỉ mục:

- `ix_meal_plan_pins_lot_id`: `btree (lot_id)`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~10^4.

Ràng buộc chỉ kiểm ở service: Tối đa 2 lô mỗi mâm; lô phải thuộc chủ mâm (BR-TRAY-08).

### `meal_plan_items`

Món trong mâm theo slot; đổi món tạo dòng mới và chuyển dòng cũ sang swapped_out; mỗi slot có tối đa một dòng active.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh dòng món (UUID). |
| `meal_plan_id` | `uuid` | NOT NULL |  | `FK → meal_plans(id) ON DELETE CASCADE` | DLCN cơ bản | Mâm. |
| `slot` | `slot_t` | NOT NULL |  | `FK (recipe_id, slot) → recipes(id, slot)` | DLCN cơ bản | Slot: man, rau, canh; khoá ngoại ghép (recipe_id, slot) bảo đảm khớp slot của món. |
| `recipe_id` | `uuid` | NOT NULL |  | `FK (recipe_id, slot) → recipes(id, slot)` | DLCN cơ bản | Món (đúng bản đã dùng, BR-CATALOG-01). |
| `status` | `plan_item_status_t` | NOT NULL | `'active'::plan_item_status_t` |  | DLCN cơ bản | active hoặc swapped_out (đã bị đổi ra). |
| `replaced_item_id` | `uuid` | NULL |  | `FK → meal_plan_items(id); UNIQUE` | DLCN cơ bản | Dòng món bị dòng này thay thế khi đổi món; NULL với món ban đầu. |
| `swap_reason` | `swap_reason_t` | NULL |  |  | DLCN cơ bản | Lý do đổi khi dòng bị đổi ra: khong_hop_gu, moi_an, thieu_thoi_gian, khac (BR-SWAP-01). |
| `rank_score` | `real` | NOT NULL |  |  | DLCN cơ bản | Điểm xếp hạng gu của món lúc ghép. |
| `servings_scale` | `numeric` | NOT NULL |  | `CHECK ((servings_scale > (0)::numeric))` | DLCN cơ bản | Hệ số nhân lượng nguyên liệu = n / servings (BR-TRAY-02). |
| `kcal_per_person` | `numeric` | NULL |  | `CHECK ((kcal_per_person >= (0)::numeric))` | DLCN cơ bản | Năng lượng món mỗi người, kcal, dẫn xuất từ recipe_nutrition × servings_scale và thay thế nguyên liệu; tính lại trong cùng giao dịch ghi meal_plan_item_substitutions, chỉ khi món active và mâm proposed/accepted (trg_meal_plan_items_guard); NULL nếu chưa tính được. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm tạo bản ghi (giờ server, timestamptz). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_meal_plan_items_not_self`: `CHECK ((replaced_item_id <> id))`
- `uq_meal_plan_items_id_meal_plan_id_recipe_id`: `UNIQUE (id, meal_plan_id, recipe_id)` — Siêu khoá làm đích khoá ngoại ghép từ interactions (D4).
- `uq_meal_plan_items_replaced_item_id`: `UNIQUE (replaced_item_id)` — Mỗi món bị đổi ra tối đa một lần (BR-SWAP-01).

Chỉ mục:

- `ix_meal_plan_items_meal_plan_id`: `btree (meal_plan_id)`
- `ux_meal_plan_items_active_slot`: `UNIQUE btree (meal_plan_id, slot) WHERE (status = 'active'::plan_item_status_t)`

Trigger:

- `trg_meal_plan_items_guard` (before update): `trg_meal_plan_items_guard()` — D2: kcal_per_person chỉ tính lại khi món active và mâm proposed/accepted.
- `trg_meal_plan_items_write_once` (before update): `trg_write_once('meal_plan_id', 'slot', 'recipe_id', 'replaced_item_id', 'rank_score', 'servings_scale')`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~3 × 10^5.

Ràng buộc chỉ kiểm ở service: Mâm 2 món khi n = 1, 3 món khi n ≥ 2 (BR-TRAY-01).

### `meal_plan_item_substitutions`

Thay thế nguyên liệu người dùng đã chọn cho một món trong mâm (UC17).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `item_id` | `uuid` | NOT NULL |  | `FK → meal_plan_items(id) ON DELETE CASCADE; PK (item_id, original_ingredient_id)` | DLCN cơ bản | Dòng món trong mâm. |
| `original_ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id); PK (item_id, original_ingredient_id)` | DLCN cơ bản | Nguyên liệu gốc bị thay. |
| `substitute_ingredient_id` | `uuid` | NOT NULL |  | `FK → ingredients(id)` | DLCN cơ bản | Nguyên liệu thay thế. |
| `grams` | `numeric` | NOT NULL |  | `CHECK ((grams > (0)::numeric))` | DLCN cơ bản | Lượng nguyên liệu thay thế, gam lúc mua. |
| `origin` | `substitution_origin_t` | NOT NULL |  |  | DLCN cơ bản | Nguồn gợi ý: lookup (bảng tra), embedding (Word2Vec), user (người dùng tự chọn). |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm chọn thay thế. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_meal_plan_item_substitutions_distinct`: `CHECK ((original_ingredient_id <> substitute_ingredient_id))`

Trigger:

- `trg_meal_plan_item_substitutions_guard` (before insert or delete or update): `trg_meal_plan_item_substitutions_guard()`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~10^4.

Ràng buộc chỉ kiểm ở service: Đồ thay không thuộc nhóm dị ứng hay chế độ ăn bị loại (BR-ALG-01, BR-DIET-01).

## M12 — module `cooking`

Lịch nấu CP-SAT, phiên nấu, nấu xong (UoW), hoàn tác.

### `cook_sessions`

Phiên nấu cả mâm (UC19); meal_plans 1 — 0..* cook_sessions; không lưu user_id, truy chủ qua meal_plans.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | DLCN cơ bản | Định danh phiên (UUID). |
| `meal_plan_id` | `uuid` | NOT NULL |  | `FK → meal_plans(id) ON DELETE CASCADE` | DLCN cơ bản | Mâm được nấu. |
| `status` | `cook_status_t` | NOT NULL | `'in_progress'::cook_status_t` |  | DLCN cơ bản | Trạng thái: in_progress, completed, reverted, abandoned. |
| `serve_at` | `timestamp with time zone` | NOT NULL |  |  | DLCN cơ bản | Giờ dọn cơm mong muốn; mọi món xong trong cửa sổ 5 phút trước giờ này (BR-COOK-01). |
| `burners` | `smallint` | NOT NULL |  | `CHECK (((burners >= 1) AND (burners <= 4)))` | DLCN cơ bản | Số họng bếp chụp lúc tạo phiên. |
| `started_at` | `timestamp with time zone` | NOT NULL |  |  | DLCN cơ bản | Thời điểm bắt đầu nấu; mốc của các offset trong cook_schedule_entries. |
| `completed_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm bấm nấu xong (BR-COOK-02); NULL nếu chưa xong. |
| `reverted_at` | `timestamp with time zone` | NULL |  |  | DLCN cơ bản | Thời điểm hoàn tác trừ kho (trong 10 phút, BR-PANTRY-02); NULL nếu không hoàn tác. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | DLCN cơ bản | Thời điểm tạo bản ghi (giờ server, timestamptz). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_cook_sessions_burners`: `CHECK (((burners >= 1) AND (burners <= 4)))` — Ảnh chụp số họng bếp trong miền của user_settings.burners (BR-COOK-01).
- `ck_cook_sessions_completed`: `CHECK (((status = 'completed'::cook_status_t) = ((completed_at IS NOT NULL) AND (reverted_at IS NULL))))` — status = completed khi và chỉ khi đã nấu xong và chưa hoàn tác (BR-COOK-02).
- `ck_cook_sessions_order`: `CHECK (((completed_at >= started_at) AND (reverted_at >= completed_at) AND ((reverted_at IS NULL) OR (completed_at IS NOT NULL))))`
- `ck_cook_sessions_reverted`: `CHECK (((status = 'reverted'::cook_status_t) = (reverted_at IS NOT NULL)))` — status = reverted khi và chỉ khi có reverted_at (BR-PANTRY-02).

Chỉ mục:

- `ix_cook_sessions_meal_plan_id`: `btree (meal_plan_id)`
- `ux_cook_sessions_one_live`: `UNIQUE btree (meal_plan_id) WHERE (status = ANY (ARRAY['in_progress'::cook_status_t, 'completed'::cook_status_t]))` — Mỗi mâm tối đa một phiên in_progress hoặc completed; chặn nấu xong hai lần khi hai thiết bị gửi song song (BR-COOK-02).

Trigger:

- `trg_cook_sessions_write_once` (before update): `trg_write_once('meal_plan_id', 'serve_at', 'burners', 'started_at')`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~10^5.

Ràng buộc chỉ kiểm ở service: Hoàn tác trong 10 phút (BR-PANTRY-02).

Ghi chú thiết kế: meal_plans 1 — 0..* cook_sessions; không lưu user_id (truy qua meal_plans để giữ 3NF).

### `cook_schedule_entries`

Lịch nấu của phiên: thời điểm bắt đầu và kết thúc từng bước (CP-SAT, BR-COOK-01).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `cook_session_id` | `uuid` | NOT NULL |  | `FK → cook_sessions(id) ON DELETE CASCADE; PK (cook_session_id, recipe_id, step_no)` | DLCN cơ bản | Phiên nấu. |
| `recipe_id` | `uuid` | NOT NULL |  | `FK (recipe_id, step_no) → recipe_steps(recipe_id, step_no); PK (cook_session_id, recipe_id, step_no)` | DLCN cơ bản | Món chứa bước. |
| `step_no` | `smallint` | NOT NULL |  | `FK (recipe_id, step_no) → recipe_steps(recipe_id, step_no); PK (cook_session_id, recipe_id, step_no)` | DLCN cơ bản | Số thứ tự bước trong món. |
| `start_offset_s` | `integer` | NOT NULL |  | `CHECK ((start_offset_s >= 0))` | DLCN cơ bản | Thời điểm bắt đầu bước, giây tính từ đầu lịch. |
| `end_offset_s` | `integer` | NOT NULL |  |  | DLCN cơ bản | Thời điểm kết thúc bước, giây tính từ đầu lịch (> start_offset_s). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_cook_schedule_entries_1`: `CHECK ((start_offset_s < end_offset_s))`

Lưu/Xoá: Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ). Quy mô ước lượng: ~10^6.

Ràng buộc chỉ kiểm ở service: Lịch thoả BR-COOK-01 (CP-SAT).

## M13 — module `journal`

Nhật ký tuần (view chỉ đọc).

### View `v_journal_days`

Nhật ký theo ngày địa phương (user_settings.timezone) của từng người dùng: số phiên nấu completed, kcal/người gồm món và cơm, mục tiêu ảnh chụp, số lô gấp được dùng kịp (UC22). Lọc theo user_id được đẩy xuống cả hai nhánh gộp.

| Cột | Kiểu | Ý nghĩa |
|---|---|---|
| `user_id` | `uuid` | Người dùng. |
| `local_date` | `date` | Ngày của completed_at theo user_settings.timezone (mặc định Asia/Ho_Chi_Minh khi chưa có dòng cài đặt). |
| `cooked_sessions` | `bigint` | Số phiên nấu completed trong ngày (mỗi mâm tối đa một phiên completed, ux_cook_sessions_one_live). |
| `kcal_dishes_per_person` | `numeric` | Σ kcal_per_person của các món active trong các mâm đã nấu (chưa gồm cơm). |
| `rice_bowls_per_person` | `numeric` | Σ số bát cơm gợi ý mỗi người (meal_plans.rice_bowls_per_person) của các mâm đã nấu. |
| `kcal_per_person` | `numeric` | kcal_dishes_per_person + rice_bowls_per_person × E_bát (app_param rice_bowl_kcal); so được với e_target_kcal vì E_mâm gồm cả cơm (BR-TRAY-03). NULL khi chưa đặt E_bát. E_bát là tham số hiện hành, chưa phải ảnh chụp theo mâm (đề xuất 04 mục 6). |
| `e_target_kcal` | `numeric` | Σ e_target_kcal (ảnh chụp E_mâm) của các mâm đã nấu. |
| `urgent_lots_used` | `bigint` | Số lô khác nhau bị trừ với reason cook_deduct và urgency_at_event trong [fresh_u_soon, fresh_u_check] (mặc định [0,5; 1,0], nhãn "nên dùng sớm"/"dùng ngay" của BR-FRESH-04). |

## M14 — module `survey`

Phiếu khảo sát khối không đầy đủ, người tham gia ẩn danh, điểm, món hay ăn.

### `survey_forms`

Phiếu khảo sát gu theo khối không đầy đủ: mỗi người chấm các món neo chung và một nhóm món ngẫu nhiên (UC24).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | Không phải DLCN | Định danh phiếu (UUID). |
| `version` | `text` | NOT NULL |  | `UNIQUE` | Không phải DLCN | Nhãn phiên bản phiếu, duy nhất. |
| `n_anchor` | `smallint` | NOT NULL |  |  | Không phải DLCN | Số món neo mọi người cùng chấm. |
| `n_random` | `smallint` | NOT NULL |  |  | Không phải DLCN | Số món ngẫu nhiên giao thêm cho mỗi người. |
| `is_open` | `boolean` | NOT NULL | `false` |  | Không phải DLCN | true khi phiếu đang nhận trả lời. |
| `created_at` | `timestamp with time zone` | NOT NULL | `now()` |  | Không phải DLCN | Thời điểm tạo bản ghi (giờ server, timestamptz). |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_survey_forms_sizes`: `CHECK (((n_anchor >= 0) AND (n_random >= 0) AND ((n_anchor + n_random) > 0)))`

Lưu/Xoá: Đến hết đồ án. Quy mô ước lượng: ~5.

### `survey_form_anchors`

Danh sách món neo của phiếu.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `form_id` | `uuid` | NOT NULL |  | `FK → survey_forms(id); PK (form_id, recipe_id)` | Không phải DLCN | Phiếu. |
| `recipe_id` | `uuid` | NOT NULL |  | `FK → recipes(id); PK (form_id, recipe_id)` | Không phải DLCN | Món neo. |

Trigger:

- `trg_survey_form_anchors_guard` (before insert or delete or update): `trg_survey_form_anchors_guard()`

Lưu/Xoá: Đến hết đồ án. Quy mô ước lượng: ~50.

### `survey_respondents`

Người tham gia khảo sát ẩn danh, không cần tài khoản (A03).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `gen_random_uuid()` | `PK` | Ẩn danh trong hệ thống | Định danh ẩn danh của người tham gia (UUID). |
| `form_id` | `uuid` | NOT NULL |  | `FK → survey_forms(id)` | Ẩn danh trong hệ thống | Phiếu đang trả lời. |
| `policy_version_id` | `uuid` | NOT NULL |  | `FK → policy_versions(id)` | Ẩn danh trong hệ thống | Phiên bản điều khoản mục đích survey đã đồng ý. |
| `consented_at` | `timestamp with time zone` | NOT NULL |  |  | Ẩn danh trong hệ thống | Thời điểm đồng ý. |
| `completed_at` | `timestamp with time zone` | NULL |  |  | Ẩn danh trong hệ thống | Thời điểm hoàn thành phiếu; NULL nếu chưa xong. |
| `channel` | `survey_channel_t` | NOT NULL |  |  | Ẩn danh trong hệ thống | Kênh vào khảo sát: link hoặc qr. |

Lưu/Xoá: Chưa định (07 mục 9; đề xuất đến hết đồ án). Quy mô ước lượng: 80–100.

### `survey_assignments`

Món giao cho từng người tham gia và thứ tự hiển thị.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `respondent_id` | `uuid` | NOT NULL |  | `FK → survey_respondents(id) ON DELETE CASCADE; PK (respondent_id, recipe_id)` | Ẩn danh trong hệ thống | Người tham gia. |
| `recipe_id` | `uuid` | NOT NULL |  | `FK → recipes(id); PK (respondent_id, recipe_id)` | Ẩn danh trong hệ thống | Món được giao. |
| `display_order` | `smallint` | NOT NULL |  | `CHECK ((display_order >= 1))` | Ẩn danh trong hệ thống | Thứ tự hiển thị. |
| `is_anchor` | `boolean` | NOT NULL |  |  | Ẩn danh trong hệ thống | true nếu là món neo. |

Ràng buộc nhiều cột hoặc có chú thích:

- `uq_survey_assignments_respondent_id_display_order`: `UNIQUE (respondent_id, display_order)` — Mỗi vị trí hiển thị một món (khoá ứng viên thứ hai).

Trigger:

- `trg_survey_assignments_write_once` (before update): `trg_write_once('respondent_id', 'recipe_id', 'display_order', 'is_anchor')`

Lưu/Xoá: Như survey_respondents. Quy mô ước lượng: ~3 × 10^3.

### `survey_ratings`

Điểm người tham gia chấm cho món được giao; chỉ chấm món đã giao (khoá ngoại ghép tới survey_assignments).

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `respondent_id` | `uuid` | NOT NULL |  | `FK (respondent_id, recipe_id) → survey_assignments(respondent_id, recipe_id) ON DELETE CASCADE; PK (respondent_id, recipe_id)` | Ẩn danh trong hệ thống | Người tham gia. |
| `recipe_id` | `uuid` | NOT NULL |  | `FK (respondent_id, recipe_id) → survey_assignments(respondent_id, recipe_id) ON DELETE CASCADE; PK (respondent_id, recipe_id)` | Ẩn danh trong hệ thống | Món. |
| `rating` | `smallint` | NULL |  | `CHECK (((rating >= 1) AND (rating <= 5)))` | Ẩn danh trong hệ thống | Điểm 1–5; NULL khi chọn chưa ăn bao giờ. |
| `never_eaten` | `boolean` | NOT NULL | `false` |  | Ẩn danh trong hệ thống | true nếu người tham gia chưa ăn món này (khi đó rating là NULL). |
| `answered_at` | `timestamp with time zone` | NOT NULL |  |  | Ẩn danh trong hệ thống | Thời điểm trả lời. |

Ràng buộc nhiều cột hoặc có chú thích:

- `ck_survey_ratings_1`: `CHECK (((rating IS NULL) = never_eaten))`

Chỉ mục:

- `ix_survey_ratings_recipe_id`: `btree (recipe_id)`

Lưu/Xoá: Như survey_respondents. Quy mô ước lượng: ~3 × 10^3.

### `survey_favorites`

Món hay ăn người tham gia khảo sát chọn.

| Cột | Kiểu | NULL | Mặc định | Ràng buộc | Phân loại | Ý nghĩa |
|---|---|---|---|---|---|---|
| `respondent_id` | `uuid` | NOT NULL |  | `FK → survey_respondents(id) ON DELETE CASCADE; PK (respondent_id, recipe_id)` | Ẩn danh trong hệ thống | Người tham gia. |
| `recipe_id` | `uuid` | NOT NULL |  | `FK → recipes(id); PK (respondent_id, recipe_id)` | Ẩn danh trong hệ thống | Món. |

Lưu/Xoá: Như survey_respondents. Quy mô ước lượng: ~500.

Ràng buộc chỉ kiểm ở service: Tối đa 5 món (UC23).
