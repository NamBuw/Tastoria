# ADR 0005 — Mã hoá cột sức khoẻ ở tầng ứng dụng và giao diện `profile.get_meal_constraints()`

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: M05 `profile`; bảng `profiles`, `user_allergens`, `audit_log`; module gọi: M10 `substitute`, M11 `meal`, M13 `journal`; UC09, UC10, UC11, UC15; BR-CONSENT-02, BR-NUT-01..04
- Thay cho: v1 §7.4 ("Chỉ module profile đọc cột sức khỏe", tự mâu thuẫn)

## Bối cảnh

Hồ sơ năng lượng cần giới tính, năm sinh, chiều cao, cân nặng để tính BMR, TEE và E_mâm (BR-NUT-01..04). Đây là dữ liệu về tình trạng sức khoẻ, thuộc danh mục dữ liệu cá nhân nhạy cảm (NĐ 356/2025 Điều 4 khoản 1 điểm d, xem [07-danh-gia-tac-dong-du-lieu-ca-nhan.md](../sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md)).

v1 viết "chỉ module profile đọc cột sức khoẻ", nhưng ghép mâm cần E_mâm và dị ứng, nhật ký cần mục tiêu calo. Cả hệ thống dùng chung một user DB nên câu đó không cưỡng chế được. Nếu dị ứng nằm trong cột mã hoá thì SQL không lọc cứng được (review:backend_ops#9).

Yếu tố quyết định:
- Rò bảng hoặc bản sao lưu không được lộ chỉ số cơ thể.
- Lọc cứng dị ứng và chế độ ăn phải chạy bằng SQL để kiểm thử toàn kho món (BR-ALG-01).
- Module ngoài `profile` không cần và không được thấy chỉ số cơ thể thô.

## Các phương án

1. **Không mã hoá, chỉ dựa vào quyền DB.** Đơn giản. Một bản `pg_dump` lộ toàn bộ chỉ số.
2. **Mã hoá toàn ổ / TDE.** Bảo vệ khi mất ổ. Không bảo vệ trước người có quyền đọc DB hay bản dump; PostgreSQL bản cộng đồng không có TDE.
3. **`pgcrypto` trong SQL.** Khoá phải đi qua câu SQL, dễ lọt vào log truy vấn; giải mã được ở bất kỳ module nào có kết nối DB.
4. **Mã hoá tầng ứng dụng AES-GCM, chỉ `profile` giữ khoá, module khác nhận giá trị dẫn xuất qua service.**

## Quyết định

Chọn **phương án 4**.

- Cột mã hoá: `profiles.sex_enc`, `birth_year_enc`, `height_cm_enc`, `weight_kg_enc` (bytea), kèm `profiles.enc_key_id`.
  - AES-256-GCM, nonce 96 bit ngẫu nhiên mỗi lần ghi.
  - Dữ liệu liên kết (AAD) = `user_id` + tên cột, để không chép được bản mã từ hàng này sang hàng khác hay từ cột này sang cột khác.
  - Khoá dữ liệu nạp từ tệp bí mật của Compose, không nằm trong repo, image hay bản sao lưu DB. `enc_key_id` cho phép xoay khoá: bản ghi mới dùng khoá mới, job mã hoá lại bản ghi cũ.
- Chỉ M05 `profile` import mã giải mã (import-linter `protected`, ADR 0001). Mỗi lần giải mã ghi một dòng `audit_log` (`action`, `entity = profiles`, `purpose`, `request_id`).
- Không có đồng ý `health_profile` thì các cột `*_enc` để NULL (BR-CONSENT-02). Rút đồng ý thì xoá giá trị trong ≤ 24 giờ (BR-CONSENT-04).
- Giao diện công khai: `profile.service.get_meal_constraints(user_id) -> MealConstraints`, gồm:
  - `e_meal_kcal` theo bữa (hoặc rỗng nếu không có mục tiêu → β = 0),
  - `allergen_codes` (từ `user_allergens`),
  - `diet_code`,
  - `favorite_recipe_ids` (từ `user_favorite_recipes`),
  - `burners`, `default_persons` (từ `user_settings`).

  Không trả chỉ số cơ thể thô. M11 `meal` và M10 `substitute` truyền các giá trị này làm tham số vào truy vấn lọc cứng của `catalog`.
- Các giá trị không mã hoá, vì cần truy vấn và tự chúng không phải chỉ số cơ thể: `activity_level`, `goal`, `kcal_target`, `kcal_source`, `diet_code`, và `user_allergens` (lọc cứng bằng SQL). Đánh giá tác động xếp chúng là dữ liệu nhạy cảm hoặc dẫn xuất từ dữ liệu sức khoẻ, bảo vệ bằng phân quyền và mã hoá bản sao lưu.

## Hệ quả

Tích cực:
- Rò bảng `profiles` hoặc bản `pg_dump` không lộ chỉ số cơ thể nếu khoá không rò cùng.
- Truy vết được mỗi lần giải mã.
- Ranh giới khớp ADR 0001: meal và substitute chỉ thấy ràng buộc, không thấy cân nặng.

Tiêu cực, cần theo dõi:
- Không lọc hay thống kê được theo cân nặng bằng SQL. Phân tích nhóm phải đi qua `profile`.
- Mất khoá là mất dữ liệu hồ sơ; khoá phải được sao lưu tách khỏi bản sao lưu DB, và quy trình khôi phục (NFR-REL-01) phải gồm bước nạp khoá.
- `user_allergens`, `kcal_target` và ảnh chụp `meal_plans.e_target_kcal` không mã hoá nhưng vẫn là dữ liệu liên quan sức khoẻ. Mục đích đồng ý nào bao trùm `user_allergens` chưa được ghi trong `consent_purposes` (đề xuất bổ sung mô hình).
- `get_meal_constraints()` giải mã mỗi lần ghép mâm: mỗi `POST /meal-plans` sinh một dòng `audit_log`. Có thể cache E_mâm đã tính trong phạm vi request, không cache giá trị thô.

## Căn cứ

- review:backend_ops#9 (câu "chỉ profile đọc cột sức khoẻ" tự mâu thuẫn), review:backend_ops#13 (chưa thiết kế quản lý khoá mã hoá cột), review:sad#11: [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- Thiết kế v2 §8 "Mã hoá cột"; BR-CONSENT-02, BR-CONSENT-04, BR-ALG-01 ở §4.
- NĐ 356/2025/NĐ-CP Điều 4 khoản 1 điểm d ("Tình trạng sức khỏe"), đối chiếu qua bản đăng trên LuatVietnam: https://luatvietnam.vn/dan-su/nghi-dinh-356-2025-nd-cp-quy-dinh-chi-tiet-luat-bao-ve-du-lieu-ca-nhan-422896-d1.html (mở ngày 17/10/2026; chưa đối chiếu bản Công báo).
- AES-GCM trong thư viện `cryptography` (`AESGCM`): https://cryptography.io/en/latest/hazmat/primitives/aead/ (chưa mở lại trong phiên này).
