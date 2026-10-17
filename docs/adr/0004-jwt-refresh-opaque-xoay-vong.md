# ADR 0004 — Access JWT ngắn hạn + refresh token opaque xoay vòng theo family

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: M02 `identity`; bảng `users`, `refresh_tokens`, `password_resets`; `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-all`, `POST /auth/password-reset/request`, `POST /auth/password-reset/confirm`; UC01–UC04; NFR-SEC-01, NFR-SEC-02
- Thay cho: v1 §6.1 ("JWT: access token ngắn hạn + refresh token", không có chi tiết)

## Bối cảnh

App Android và web (ADR 0010) là public client: không giữ được bí mật client. v1 không nêu thời hạn token, thuật toán ký, cách thu hồi, nơi lưu token trên máy; không có bảng refresh token, không có đăng xuất hay quên mật khẩu; không có kiểm tra quyền theo đối tượng (review:backend_ops#6).

Các yêu cầu khác đòi thu hồi phiên ngay: rút đồng ý có hiệu lực ngay (BR-CONSENT-04), xoá tài khoản (UC07), đổi mật khẩu (UC04).

RFC 9700 §2.2.2: "Refresh tokens for public clients MUST be sender-constrained or use refresh token rotation as described in Section 4.14."

## Các phương án

1. **Phiên server-side (cookie phiên + bảng sessions).** Thu hồi dễ. Mỗi request đọc DB; app Android phải tự quản cookie.
2. **Access JWT dài hạn, không refresh.** Đơn giản. Không thu hồi được trước khi hết hạn.
3. **Access JWT + refresh JWT.** Refresh là JWT tự chứa nên muốn thu hồi vẫn phải có danh sách ở server; không có lợi gì so với chuỗi opaque.
4. **Access JWT ngắn hạn + refresh token opaque lưu băm, xoay vòng theo family, phát hiện dùng lại.** Đáp ứng RFC 9700 bằng xoay vòng.
5. **Ràng buộc người gửi (DPoP).** An toàn hơn xoay vòng. Thư viện phía Expo và FastAPI còn ít; vượt quy mô đồ án.

## Quyết định

Chọn **phương án 4**.

- **Mật khẩu**: Argon2id qua `pwdlib[argon2]` (passlib không chạy trên Python 3.13+).
- **Access token**: JWT 15 phút, có `kid` để xoay khoá ký, kiểm `exp`, `iss`, `aud`, và claim `tv` so với `users.token_version`.
- **Refresh token**: 32 byte ngẫu nhiên, sống 30 ngày, chỉ lưu `token_sha256` (UNIQUE) trong `refresh_tokens`, kèm `family_id`, `issued_at`, `expires_at`, `revoked_at`, `replaced_by_id`, `user_agent`.
  - `POST /auth/refresh` cấp token mới cùng family, ghi `replaced_by_id` và `revoked_at` cho token cũ.
  - Dùng lại một token đã thu hồi → thu hồi cả family (dấu hiệu token bị đánh cắp).
- **Thu hồi diện rộng**: tăng `users.token_version` khi đăng xuất mọi thiết bị (`POST /auth/logout-all`), đổi mật khẩu, rút đồng ý, yêu cầu xoá tài khoản. Access token cũ hết hiệu lực ngay ở request kế tiếp vì `tv` không khớp.
- **Khoá đăng nhập sai** (NFR-SEC-02), hai tầng có vai trò riêng:
  - Valkey đếm theo cặp (email, IP), TTL 15 phút: chặn dò mật khẩu mà không khoá nhầm nhiều người sau NAT nhà mạng (ADR 0003).
  - `users.failed_logins` và `users.locked_until` khoá theo tài khoản sau 5 lần sai liên tiếp, 15 phút; đặt lại khi đăng nhập đúng.
- **Đặt lại mật khẩu** (UC04): `password_resets.token_sha256`, dùng một lần (`used_at`), gửi qua A09 (dev: Mailpit). `POST /auth/password-reset/request` luôn trả cùng một phản hồi, không tiết lộ email có tồn tại hay không.
- **Lưu token trên máy**:
  - Android: `expo-secure-store`.
  - Web: `expo-secure-store` không có bản web. Refresh token đặt trong cookie `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`; access token chỉ giữ trong bộ nhớ. `/auth/refresh` từ web kiểm thêm header `Origin`.
- **Chống BOLA**: một dependency FastAPI dùng chung buộc mọi truy vấn theo `{id}` lọc theo chủ sở hữu; id công khai là UUID. Bảng không có `user_id` (ví dụ `cook_sessions`) lọc qua bảng cha (`meal_plans.user_id`). A truy cập tài nguyên của B nhận 404.

## Hệ quả

Tích cực:
- Thu hồi được từng thiết bị, mọi thiết bị, và ngay khi rút đồng ý.
- Lộ một bản sao CSDL không lộ refresh token dùng được (chỉ có băm).
- Request thường không đọc bảng `refresh_tokens`; chỉ so `token_version` (một dòng `users`, cache được).

Tiêu cực, cần theo dõi:
- Request thường vẫn đọc `users.token_version`. Chấp nhận ở quy mô này.
- App gửi hai request `/auth/refresh` song song (hai tab, hai luồng) có thể bị coi là dùng lại token và mất cả family. Bù bằng: app chỉ có một luồng làm mới; server cho phép một khoảng ân hạn ngắn (vài giây) với token vừa được thay. Ân hạn là đánh đổi an toàn, phải có ca kiểm thử.
- Hai cách lưu refresh token (secure-store và cookie) nghĩa là `POST /auth/refresh` nhận token từ body hoặc cookie. Hợp đồng OpenAPI phải ghi cả hai (đề xuất bổ sung mô hình).
- Khoá ký JWT phải xoay được qua `kid`; khoá nằm ngoài repo (biến môi trường hoặc tệp bí mật của Compose).

## Căn cứ

- review:backend_ops#6 (thiếu xoay vòng, thu hồi, nơi lưu, BOLA), review:sad#11 (rút đồng ý có hiệu lực): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- R3 §3 dòng Argon2/JWT (pwdlib, PyJWT): [03-cong-nghe-vpp-phan-tich-thiet-ke.md §3](../research/raw/03-cong-nghe-vpp-phan-tich-thiet-ke.md#3-infrastructure-licensing-and-current-versions).
- Thiết kế v2 §8 "Xác thực", §11 NFR-SEC-01, NFR-SEC-02; BR-CONSENT-04 ở §4.
- RFC 9700 (OAuth 2.0 Security Best Current Practice) §2.2.2 và §4.14: https://www.rfc-editor.org/rfc/rfc9700.html (đã mở ngày 17/10/2026).
- OWASP API Security Top 10 2023, API1 Broken Object Level Authorization: https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/ (chưa mở lại trong phiên này; dẫn theo review:backend_ops#6).
- pwdlib: https://pypi.org/project/pwdlib/ (R3 mở ngày 17/10/2026).
- `expo-secure-store` chỉ hỗ trợ Android, iOS, tvOS: https://docs.expo.dev/versions/latest/sdk/securestore/ (mở ngày 17/10/2026).
