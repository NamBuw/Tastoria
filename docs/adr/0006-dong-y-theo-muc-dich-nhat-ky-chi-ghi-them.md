# ADR 0006 — Đồng ý theo mục đích, nhật ký đồng ý chỉ ghi thêm

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: M03 `privacy`; bảng `consent_purposes`, `policy_versions`, `consent_events`, `dsr_requests`, `audit_log`, view `v_current_consents`; `survey_respondents.policy_version_id`; `GET /policies/{purpose}/current`, `GET /me/consents`, `POST /me/consents`, `POST /me/consents/{purpose}/withdraw`; UC05, UC09, UC23; BR-CONSENT-01..04
- Thay cho: v1 §6.4 bảng `consents(user_id, data_type, policy_version, granted_at, revoked_at)`

## Bối cảnh

Tastoria xử lý dữ liệu nhạy cảm: chỉ số cơ thể (sức khoẻ) và lịch sử tương tác dùng để cá nhân hoá (dữ liệu theo dõi hành vi sử dụng dịch vụ trực tuyến). Luật 91/2025/QH15 Điều 9 khoản 4 điểm a yêu cầu đồng ý "đối với từng mục đích", điểm d: "Sự im lặng hoặc không phản hồi không được coi là sự đồng ý". NĐ 356/2025 Điều 6 khoản 2 yêu cầu bên kiểm soát lưu trữ sự đồng ý và chịu trách nhiệm chứng minh khi có tranh chấp.

Bảng v1 ghi đồng ý theo **loại dữ liệu**, không theo mục đích; không có bảng phiên bản điều khoản để chứng minh người dùng đồng ý với văn bản nào; ghi đè `revoked_at` nên mất lịch sử; hệ quả khi bỏ qua hay rút đồng ý chưa được định nghĩa (review:sad#11). `POST /events` ghi tương tác bất kể đồng ý (review:backend_ops#7).

## Các phương án

1. **Cờ boolean trên `users`** (một cột mỗi mục đích). Không có lịch sử, không biết người dùng đồng ý với phiên bản điều khoản nào.
2. **Một dòng mỗi (người dùng, mục đích), cập nhật tại chỗ** (`granted_at`, `revoked_at`). Có trạng thái hiện tại, mất lịch sử khi đồng ý lại.
3. **Nhật ký sự kiện chỉ ghi thêm** (grant/withdraw) gắn phiên bản điều khoản; trạng thái hiện tại là view của sự kiện mới nhất.

## Quyết định

Chọn **phương án 3**.

- `consent_purposes` (danh mục, khoá `code`): `health_profile` (nhạy cảm), `personalization` (nhạy cảm), `photo_contribution` (tuỳ chọn, mặc định tắt), `survey` (người tham gia khảo sát). Mỗi mục có `data_category`, `is_sensitive`, `is_required` (BR-CONSENT-01).
- `policy_versions`: mỗi văn bản điều khoản theo mục đích có `version`, `text_sha256` và `effective_from`; UNIQUE (`purpose_code`, `version`). Văn bản gốc lưu trong repo theo phiên bản; băm chứng minh nội dung không đổi.
- `consent_events`: mỗi lần cấp hoặc rút ghi một dòng (`action` ∈ grant/withdraw, `channel` ∈ onboarding/settings, `app_version`, `created_at`) trỏ `policy_version_id`. Không UPDATE, không DELETE, trừ khi xoá cả tài khoản. Cưỡng chế bằng quyền DB: role của ứng dụng chỉ có INSERT và SELECT trên `consent_events` và `audit_log`.
- `v_current_consents`: đồng ý hiện hành theo (người dùng, mục đích) là sự kiện mới nhất. Trạng thái theo máy trạng thái `consent` trong `model.yaml`: `none` → `granted` → `withdrawn`; `granted` → `superseded` khi có `policy_versions` mới hiệu lực cho mục đích đó, phải đồng ý lại.
- Màn đồng ý không tích sẵn; bỏ qua = không có sự kiện = `none`.
- Cổng đồng ý trong mã (mỗi module hỏi `privacy.service.has_consent(user_id, purpose)`):
  - Không có `health_profile`: không lưu chỉ số cơ thể, β = 0, app hiện "chưa có mục tiêu" (BR-CONSENT-02).
  - Không có `personalization`: M09 `events` không ghi `interactions`; xếp hạng dùng trung bình món + content-based từ 5 món hay ăn (BR-CONSENT-03).
  - Rút đồng ý: tăng `users.token_version` (ADR 0004), xoá dữ liệu của mục đích đó trong ≤ 24 giờ qua job, ghi vào `dsr_requests` với `type = withdraw` (BR-CONSENT-04, BR-DSR-01).
- Người tham gia khảo sát (A03) không có tài khoản: bằng chứng đồng ý là `survey_respondents.policy_version_id` + `consented_at`, tạo cùng lúc với người tham gia qua `POST /survey/respondents`.

## Hệ quả

Tích cực:
- Chứng minh được ai đồng ý với văn bản nào, lúc nào, qua kênh nào.
- Đổi điều khoản không cần cập nhật hàng loạt: phiên bản mới làm đồng ý cũ thành `superseded`.
- Hệ quả của từng lựa chọn được định nghĩa, nên kiểm thử tự động được.

Tiêu cực, cần theo dõi:
- Truy vấn trạng thái hiện tại phải lấy sự kiện mới nhất; cần chỉ mục (`user_id`, `policy_version_id`, `created_at DESC`) và có thể cache ngắn theo request.
- Xoá tài khoản (UC07) xoá cứng `consent_events` theo `ON DELETE CASCADE`. Bằng chứng còn lại chỉ là `dsr_requests` (giữ `subject_ref` = HMAC-SHA256 của `user_id`). Việc này có đủ để chứng minh đồng ý sau khi xoá hay không cần rà soát pháp lý; thời hạn lưu `dsr_requests` chưa được định (đề xuất bổ sung mô hình).
- `consent_purposes` chưa có mục đích cho dữ liệu dịch vụ cốt lõi (tài khoản, kho, ảnh quét). Căn cứ xử lý của nhóm dữ liệu này ghi ở đánh giá tác động, cần rà soát pháp lý.

## Căn cứ

- review:sad#11 (quyền theo Luật 91/2025 và NĐ 356 chưa thành luồng), review:backend_ops#7 (đồng ý chưa được cưỡng chế), review:sad#12 (máy trạng thái Consent): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- Thiết kế v2 §3 dòng 23, §4 nhóm "Đồng ý và quyền dữ liệu".
- Luật 91/2025/QH15 Điều 9 khoản 2, 3, 4: https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-9 (mở ngày 17/10/2026; bản đăng lại, chưa đối chiếu Công báo).
- NĐ 356/2025/NĐ-CP Điều 6 khoản 2: https://luatvietnam.vn/dan-su/nghi-dinh-356-2025-nd-cp-quy-dinh-chi-tiet-luat-bao-ve-du-lieu-ca-nhan-422896-d1.html (mở ngày 17/10/2026; bản đăng lại).
- Đánh giá tác động: [07-danh-gia-tac-dong-du-lieu-ca-nhan.md](../sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md).
