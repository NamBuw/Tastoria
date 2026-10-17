# Hồ sơ đánh giá tác động xử lý dữ liệu cá nhân — Tastoria v2

> **Bản nháp cho đồ án, cần rà soát pháp lý trước khi phát hành.** Tài liệu này do nhóm đồ án soạn theo Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15 và Nghị định 356/2025/NĐ-CP. Nhóm không phải luật sư. Điều khoản dẫn ở đây đã được đối chiếu với bản đăng lại trên các trang văn bản pháp luật (bảng ở §15), **chưa đối chiếu với bản Công báo**. Mọi chỗ ghi **[chưa xác minh]** hoặc **[cần rà soát pháp lý]** phải được người có chuyên môn kiểm trước khi đưa hệ thống ra người dùng ngoài nhóm.

| Mục | Giá trị |
|---|---|
| Hệ thống | Tastoria v2: app Android + web, backend, worker, máy chủ lab |
| Phiên bản hồ sơ | 0.1 (nháp), 17/10/2026 |
| Nguồn mô hình | `docs/sad/model.yaml` (bảng, cột, endpoint, mục đích đồng ý) và thiết kế v2 §4, §8, §10 |
| Quyết định kiến trúc liên quan | ADR 0002, 0004, 0005, 0006, 0007, 0011, 0012 trong `docs/adr/` |

Cấu trúc hồ sơ theo các nội dung của báo cáo đánh giá tác động tại NĐ 356/2025 Điều 19 khoản 3 (thông tin các bên; bộ phận bảo vệ dữ liệu; mục đích, loại dữ liệu, hoạt động xử lý, sơ đồ luồng; cách lấy đồng ý, chính sách lưu và xoá; biện pháp bảo vệ; kết quả đánh giá tuân thủ; mức độ ảnh hưởng, rủi ro và biện pháp giảm thiểu). Thành phần hồ sơ và mẫu biểu chính thức kèm Nghị định **[chưa xác minh]**: nhóm chưa mở phụ lục mẫu.

---

## 1. Có phải lập hồ sơ không

- Luật 91/2025 Điều 21 khoản 1: bên kiểm soát dữ liệu cá nhân, bên kiểm soát và xử lý dữ liệu cá nhân lập, lưu trữ hồ sơ đánh giá tác động và gửi 01 bản chính cho cơ quan chuyên trách bảo vệ dữ liệu cá nhân trong 60 ngày kể từ ngày đầu tiên xử lý dữ liệu cá nhân. Khoản 2: đánh giá một lần cho suốt thời gian hoạt động, cập nhật theo Điều 22.
- Luật 91/2025 Điều 38 khoản 2–3: doanh nghiệp nhỏ, khởi nghiệp được chọn không thực hiện Điều 21, 22 trong 5 năm; hộ kinh doanh, doanh nghiệp siêu nhỏ không phải thực hiện. Ngoại lệ không áp dụng cho bên **trực tiếp xử lý dữ liệu cá nhân nhạy cảm** hoặc xử lý dữ liệu của số lượng lớn chủ thể.
- Tastoria trực tiếp xử lý dữ liệu nhạy cảm (§4). Vì vậy, nếu hệ thống mở cho người dùng ngoài nhóm, nghĩa vụ Điều 21 được coi là áp dụng, kể cả khi bên vận hành là nhóm sinh viên chứ không phải doanh nghiệp.
- **[cần rà soát pháp lý]**: (a) giai đoạn thử nghiệm chỉ với thành viên nhóm và người thử có đồng ý có tính là "ngày đầu tiên xử lý" hay không; (b) tư cách pháp lý của bên kiểm soát khi hệ thống là đồ án (cá nhân sinh viên, nhóm, hay cơ sở đào tạo).

## 2. Các bên

| Vai trò | Bên | Ghi chú |
|---|---|---|
| Bên kiểm soát và xử lý dữ liệu cá nhân (Luật 91 Điều 2 khoản 9) | Nhóm đồ án Tastoria. Tên, địa chỉ liên hệ: **[cần điền]** | Quyết định mục đích, phương tiện và trực tiếp xử lý |
| Bộ phận/nhân sự bảo vệ dữ liệu | **[cần điền]**: đề xuất một thành viên nhóm đầu mối, email liên hệ riêng | NĐ 356 Điều 19 khoản 3 điểm b |
| Bên xử lý (Điều 2 khoản 8) — vận hành hạ tầng | Lab sở hữu máy chủ (nếu nhân sự lab có quyền quản trị máy) | Cần thoả thuận xử lý dữ liệu bằng văn bản **[cần rà soát pháp lý]** |
| Bên xử lý / bên thứ ba — truyền tải | Cloudflare (Cloudflare Tunnel, thiết kế v2 §10) | TLS kết thúc tại hạ tầng Cloudflare, xem §8 |
| Bên xử lý — gửi email (A09) | Nhà cung cấp SMTP: **chưa chọn** (dev dùng Mailpit tự host) | Chỉ nhận email và liên kết đặt lại mật khẩu |
| Bên xử lý — lưu bản sao lưu | Google Drive qua rclone (thiết kế v2 §10), bản sao lưu đã mã hoá | Xem §8 |
| Bên xử lý — nghiên cứu | Google (Gemini API, gói trả phí), chỉ cho baseline môn Xử lý ảnh | Không nhận dữ liệu người dùng app; xem §8 và ADR 0012 |
| Công cụ gán nhãn (A10) | Label Studio tự host trên hạ tầng của nhóm | Không phải bên thứ ba |

Không bán, không cho thuê, không chia sẻ dữ liệu cá nhân cho quảng cáo.

## 3. Mục đích xử lý

### 3.1. Mục đích cần đồng ý riêng (bảng `consent_purposes`, BR-CONSENT-01)

| `code` | Mục đích | Dữ liệu chính | Nhạy cảm | Bắt buộc | Hệ quả khi không đồng ý |
|---|---|---|---|---|---|
| `health_profile` | Tính mục tiêu năng lượng (BMR, TEE, E_mâm) để ghép mâm vừa nhu cầu | `profiles.*_enc`, `activity_level`, `goal`, `kcal_target` | Có | Không | Không lưu chỉ số cơ thể; β = 0; app hiện "chưa có mục tiêu" (BR-CONSENT-02) |
| `personalization` | Ghi tương tác để xếp hạng món theo gu | `interactions` | Có | Không | Không ghi `interactions`; xếp hạng dùng trung bình món + content-based từ 5 món hay ăn (BR-CONSENT-03) |
| `photo_contribution` | Giữ ảnh quét quá 30 ngày để gán nhãn và huấn luyện lại mô hình | `scan_images` có `contributed = true`, tệp ở `contrib/` | Tuỳ nội dung ảnh | Không, mặc định tắt | Ảnh gốc xoá sau 30 ngày (BR-RETAIN-01) |
| `survey` | Thu điểm gu món ăn cho nghiên cứu xếp hạng (UC23) | `survey_respondents`, `survey_assignments`, `survey_ratings`, `survey_favorites` | Không (bí danh, xem §4) | Có, cho người tham gia khảo sát | Không tham gia được khảo sát |

### 3.2. Mục đích của dịch vụ cốt lõi

| Mục đích | Dữ liệu | Ghi chú |
|---|---|---|
| Tài khoản, đăng nhập, bảo mật phiên (UC01–UC04) | `users`, `refresh_tokens`, `password_resets`, bộ đếm đăng nhập sai trong Valkey | |
| Quét tủ lạnh, quản lý kho (UC12–UC14) | `scans`, `scan_images`, `scan_items`, `detections`, `pantry_lots`, `pantry_transactions` | |
| Ghép mâm, đổi món, thay thế, đi chợ (UC15–UC18) | `meal_plans`, `meal_plan_items`, `meal_plan_pins`, `meal_plan_coeater_allergens`, `meal_plan_item_substitutions`, `shopping_items` | |
| Nấu và nhật ký (UC19–UC22) | `cook_sessions`, `cook_schedule_entries`, view `v_journal_days` | |
| Lọc cứng dị ứng, chế độ ăn (BR-ALG-01, BR-DIET-01) | `user_allergens`, `profiles.diet_code`, `meal_plan_coeater_allergens` | Xem §6 |
| Chứng minh tuân thủ, kiểm toán (UC27) | `consent_events`, `dsr_requests`, `audit_log` | |
| Lũy đẳng và chống gửi trùng | `idempotency_keys` (giữ 48 giờ) | |

`consent_purposes` không có mục đích cho nhóm dữ liệu cốt lõi. Căn cứ xử lý của nhóm này ghi ở §6 và là điểm **[cần rà soát pháp lý]**.

## 4. Loại dữ liệu cá nhân

Phân loại theo Luật 91 Điều 2 khoản 2–3 và danh mục tại NĐ 356 Điều 3 (dữ liệu cơ bản) và Điều 4 khoản 1 (dữ liệu nhạy cảm). Các điểm của Điều 4 khoản 1 nhóm đã đối chiếu: điểm d "Tình trạng sức khỏe", điểm đ "Dữ liệu sinh trắc học, đặc điểm di truyền", điểm h "Vị trí của cá nhân được xác định qua dịch vụ định vị", điểm l "Dữ liệu theo dõi hành vi, hoạt động sử dụng dịch vụ viễn thông, mạng xã hội, dịch vụ truyền thông trực tuyến". Danh mục Điều 3 chưa được nhóm đọc đầy đủ **[chưa xác minh]**.

### 4.1. Dữ liệu nhạy cảm

| Bảng / nơi lưu | Cột | Lý do xếp nhạy cảm | Bảo vệ riêng |
|---|---|---|---|
| `profiles` | `sex_enc`, `birth_year_enc`, `height_cm_enc`, `weight_kg_enc`, `enc_key_id` | Chỉ số cơ thể → tình trạng sức khoẻ (Điều 4 khoản 1 điểm d) | AES-GCM tầng ứng dụng, chỉ M05 giải mã, mỗi lần giải mã ghi `audit_log` (ADR 0005) |
| `profiles` | `activity_level`, `goal`, `kcal_target`, `kcal_source` | Dẫn xuất từ dữ liệu sức khoẻ; `goal = lose` cho biết mục tiêu giảm cân | Phân quyền, mã hoá bản sao lưu |
| `profiles` | `diet_code` | Chế độ ăn chay có thể cho thấy niềm tin tôn giáo. Việc niềm tin tôn giáo có nằm trong Điều 4 khoản 1 hay không **[chưa xác minh]**; xếp nhạy cảm để thận trọng | Như trên |
| `user_allergens` | `allergen_code` | Dị ứng thực phẩm → tình trạng sức khoẻ | Không mã hoá (lọc cứng bằng SQL, ADR 0005); phân quyền |
| `meal_plan_coeater_allergens` | `allergen_code` | Dị ứng của **người ăn cùng** (người thứ ba, không có tài khoản). Chỉ là mã nhóm dị ứng gắn với một mâm, không có tên hay định danh người ăn cùng | Xoá theo mâm (`ON DELETE CASCADE`) |
| `meal_plans` | `e_target_kcal`, `kcal_low`, `kcal_high` | Ảnh chụp mục tiêu năng lượng → dẫn xuất từ sức khoẻ | Phân quyền |
| `interactions` | toàn bảng | Theo dõi hành vi sử dụng dịch vụ trực tuyến (điểm l); thiết kế v2 BR-CONSENT-01 xếp nhạy cảm | Chỉ ghi khi có đồng ý `personalization` |
| `idempotency_keys` | `response_body` | Có thể chứa bản sao phản hồi mâm cơm (kcal) | Giữ 48 giờ |
| Ảnh quét gốc (`scan_images`, tệp ở `tmp/`, `contrib/`) | nội dung ảnh | Ảnh tủ lạnh có thể lọt khuôn mặt, người trong nhà, giấy tờ, nhãn thuốc (gợi ý tình trạng sức khoẻ). Khuôn mặt có phải dữ liệu sinh trắc học (điểm đ) khi không được xử lý để nhận dạng hay không **[chưa xác minh]** | EXIF bị xoá khi mã hoá lại JPEG; xoá sau 30 ngày; đọc qua kiểm quyền (ADR 0002) |
| Bản xuất huấn luyện (UC28) | tương tác, ảnh góp, điểm | Dữ liệu bí danh hoá (HMAC-SHA256), vẫn là dữ liệu cá nhân (Luật 91 Điều 2 khoản 1, 11) | Khoá HMAC tách riêng; chỉ trên máy lab (ADR 0012) |

### 4.2. Dữ liệu cơ bản và dữ liệu dịch vụ

| Bảng / nơi lưu | Cột chứa dữ liệu cá nhân |
|---|---|
| `users` | `email`, `password_hash` (Argon2id), `role`, `status`, `token_version`, `failed_logins`, `locked_until`, `created_at`, `updated_at` |
| `refresh_tokens` | `user_id`, `family_id`, `token_sha256`, `issued_at`, `expires_at`, `revoked_at`, `user_agent` |
| `password_resets` | `user_id`, `token_sha256`, `created_at`, `expires_at`, `used_at` |
| Valkey (ADR 0003) | khoá đếm đăng nhập sai theo (email, địa chỉ IP), TTL 15 phút |
| `user_settings` | `burners`, `default_persons`, `timezone` |
| `user_favorite_recipes` | 5 món hay ăn (sở thích ăn uống) |
| `pantry_lots`, `pantry_transactions` | nguyên liệu trong kho, ngày mua, lượng, lịch sử thay đổi (thói quen mua sắm, ăn uống) |
| `scans`, `scan_items`, `detections` | thời điểm quét, chế độ quét, chip nguyên liệu, khung phát hiện |
| `meal_plans`, `meal_plan_items`, `meal_plan_pins`, `meal_plan_item_substitutions` | bữa, số người, thời gian tối đa, món, lý do đổi món |
| `shopping_items` | danh sách đi chợ |
| `cook_sessions`, `cook_schedule_entries` | giờ dọn mâm, thời điểm nấu |
| `consent_events` | lịch sử đồng ý, `app_version` |
| `dsr_requests` | `subject_ref` (HMAC-SHA256 của `user_id`), loại yêu cầu, thời điểm, `note` |
| `audit_log` | `actor_user_id`, `actor_role`, hành động, `request_id` |
| `survey_respondents`, `survey_assignments`, `survey_ratings`, `survey_favorites` | điểm món, món hay ăn, `consented_at`, `channel`. Không lưu tên, email hay IP. Coi là dữ liệu cá nhân bí danh hoá vì người tham gia giữ token và có thể bị nhận ra qua tổ hợp câu trả lời khi mẫu nhỏ (80–100 người) |
| Log ứng dụng và log truy cập nginx | `request_id`, địa chỉ IP, user agent, đường dẫn (có UUID) |
| Bản sao lưu `pg_dump` | bản sao toàn bộ các bảng trên (đã mã hoá) |

Không thu: số điện thoại, họ tên thật, địa chỉ nhà, vị trí GPS, danh bạ. Thời tiết đã bỏ khỏi v2 nên không gửi thành phố cho bên ngoài.

## 5. Nguồn dữ liệu và hoạt động xử lý

| Nguồn | Dữ liệu | Hoạt động |
|---|---|---|
| Chủ thể nhập trực tiếp trong app (A02) | email, mật khẩu, hồ sơ, dị ứng, chế độ ăn, món hay ăn, cài đặt, ngày mua, sửa chip | thu thập, lưu, mã hoá, chỉnh sửa, xoá |
| Thiết bị của chủ thể | ảnh tủ lạnh (camera/thư viện ảnh), user agent | thu thập, mã hoá lại ảnh, suy luận, lưu tạm |
| Chủ thể cung cấp về người thứ ba | nhóm dị ứng của người ăn cùng | thu thập theo từng mâm |
| Hệ thống suy ra | độ gấp u (tính lúc đọc, không lưu, BR-FRESH-05), gợi ý năng lượng, điểm gu, mâm, lịch nấu | phân tích, tổng hợp |
| Hành vi trong app | `interactions` (served, viewed, swapped, cooked, liked, disliked, undone) | thu thập có cổng đồng ý |
| Người tham gia khảo sát (A03) | điểm món, 5 món hay ăn | thu thập qua link/QR, không tài khoản |
| Nhân sự (A04–A07) | thao tác quản trị | ghi `audit_log` |
| Ngoài app — dữ liệu huấn luyện của nhóm | ảnh tủ lạnh của 12–15 hộ, ảnh lô rau | nhóm chụp với đồng ý của chủ bếp; quản lý ngoài cơ sở dữ liệu app |

Sơ đồ luồng dữ liệu (NĐ 356 Điều 19 khoản 3 điểm c), dạng văn bản; sơ đồ triển khai UML vẽ ở `docs/uml/deployment/`:

1. App → Cloudflare (TLS) → tunnel → nginx (127.0.0.1) → `api` → PostgreSQL / Valkey / volume tệp.
2. `api` → hàng đợi Valkey → `worker` → `scan.service` → PostgreSQL.
3. `scheduler` → `python -m tastoria.jobs.purge_images` (xoá ảnh tạm), `python -m tastoria.jobs.backup` (`pg_dump` mã hoá → rclone → Google Drive), `python -m tastoria.jobs.sweep`.
4. `api` → SMTP (A09) → hộp thư người dùng (chỉ thư đặt lại mật khẩu).
5. A06 chạy `tastoria mlops export-training-data` → bản xuất bí danh hoá → máy lab (huấn luyện, MLflow) → `tastoria mlops register` → `model_versions`.
6. A07 dùng `tastoria labeling push|pull` → Label Studio tự host (A10) → nhãn quay về máy lab.

## 6. Căn cứ xử lý và cách lấy đồng ý

- Đồng ý theo **từng mục đích** (Luật 91 Điều 9 khoản 4 điểm a), dựa trên tự nguyện và biết rõ loại dữ liệu, mục đích, bên kiểm soát, quyền và nghĩa vụ của chủ thể (khoản 2), ở dạng kiểm chứng được (khoản 3). Màn đồng ý trong Hồ sơ 60 giây (UC09) không tích sẵn; im lặng hay bỏ qua không phải đồng ý (khoản 4 điểm d).
- Không đặt điều kiện bắt buộc đồng ý mục đích khác (Điều 9 khoản 4 điểm b): người dùng từ chối `health_profile` và `personalization` vẫn dùng được quét, kho, mâm cơm.
- Lưu bằng chứng (NĐ 356 Điều 6 khoản 2): `consent_events` chỉ ghi thêm, trỏ `policy_versions` có `text_sha256` (ADR 0006). Người tham gia khảo sát: `survey_respondents.policy_version_id` + `consented_at`.
- Endpoint: `GET /policies/{purpose}/current`, `GET /me/consents`, `POST /me/consents`, `POST /me/consents/{purpose}/withdraw`.
- Dữ liệu cốt lõi (§3.2) hiện được xử lý vì người dùng tự đăng ký và dùng dịch vụ; thiết kế v2 chưa có mục đích đồng ý riêng cho nhóm này. **[cần rà soát pháp lý]**: xác định Luật 91 có trường hợp xử lý không cần đồng ý áp dụng được (ví dụ thực hiện hợp đồng với chủ thể) hay phải thêm một mục đích đồng ý bắt buộc khi đăng ký. Nhóm chưa đọc các điều về xử lý không cần đồng ý **[chưa xác minh]**.
- `user_allergens` là dữ liệu sức khoẻ nhưng cần cho an toàn của chính người dùng (BR-ALG-01). Chưa định mục đích đồng ý nào bao trùm; đề xuất đưa vào `health_profile` hoặc một mục đích riêng, và nói rõ hệ quả: không khai dị ứng thì không lọc được.
- Dị ứng của người ăn cùng: người dùng khai thay người thứ ba. App nhắc người dùng chỉ khai khi người ăn cùng biết và đồng ý; hệ thống chỉ lưu mã nhóm dị ứng theo mâm. **[cần rà soát pháp lý]**.
- Ảnh do nhóm tự chụp ở 12–15 hộ cho bộ dữ liệu: đồng ý bằng văn bản của chủ bếp, ghi phạm vi (huấn luyện, baseline Gemini, công bố hay không), nằm ngoài cơ sở dữ liệu app.

## 7. Bên nhận và quyền truy cập nội bộ

| Người nhận | Dữ liệu được truy cập | Cách truy cập |
|---|---|---|
| Chủ thể (A02) | toàn bộ dữ liệu của mình | app (`GET /me/profile`, `GET /me/settings`, `GET /me/consents`, `GET /pantry/lots`), bản tải về qua `GET /me/data-requests/{id}/download` |
| Quản trị viên (A04, role `admin`) | `dsr_requests`, `audit_log` | `GET /admin/data-requests`, `POST /admin/data-requests/{id}/resolve`, `GET /admin/audit-log`; mọi thao tác ghi `audit_log` |
| Người biên soạn (A05, role `curator`) | không có dữ liệu cá nhân (chỉ kho món) | CLI `tastoria catalog import` |
| Người vận hành mô hình (A06, role `ml_operator`) | bản xuất bí danh hoá, số liệu khảo sát | CLI `tastoria mlops export-training-data`, `tastoria survey export`; `GET /admin/models`, `GET /admin/surveys` |
| Người gán nhãn (A07) | ảnh đã đồng ý góp (`contrib/`) | Label Studio (A10) |
| Bên xử lý ở §2 | theo §2 | theo thoả thuận |

Không có bên nhận nào ngoài danh sách. Cơ quan nhà nước có thẩm quyền nhận dữ liệu khi có yêu cầu theo luật.

## 8. Chuyển dữ liệu cá nhân xuyên biên giới

Luật 91 Điều 20 khoản 1: chuyển xuyên biên giới gồm (a) chuyển dữ liệu đang lưu tại Việt Nam sang hệ thống lưu trữ ngoài lãnh thổ; (b) tổ chức, cá nhân tại Việt Nam chuyển dữ liệu cho tổ chức, cá nhân ở nước ngoài; (c) dùng nền tảng ngoài lãnh thổ để xử lý dữ liệu cá nhân thu thập tại Việt Nam. Khoản 2: lập hồ sơ đánh giá tác động chuyển xuyên biên giới, gửi trong 60 ngày kể từ lần chuyển đầu tiên. Các trường hợp miễn: Luật Điều 20 khoản 6 và NĐ 356 Điều 17 khoản 3.

**Thiết kế mục tiêu: không chuyển dữ liệu người dùng ra nước ngoài.** Cơ sở dữ liệu, tệp, worker, huấn luyện và gán nhãn đều chạy trên máy chủ lab đặt tại Việt Nam (ADR 0012; vị trí vật lý cần xác nhận). Colab/Kaggle chỉ dùng dữ liệu công khai.

Các điểm còn chạm ra nước ngoài, phải xử lý hoặc rà soát trước khi phát hành:

| # | Luồng | Có phải chuyển xuyên biên giới | Hướng xử lý |
|---|---|---|---|
| X1 | Baseline Gemini (môn Xử lý ảnh) | Có nếu ảnh chứa dữ liệu cá nhân (điểm c). Điều khoản Gemini API gói trả phí: không dùng để cải thiện sản phẩm, log giới hạn để chống lạm dụng, dữ liệu "may be stored transiently or cached in any country" | Chỉ ảnh của nhóm có đồng ý chủ bếp, gói trả phí, không dùng ảnh người dùng app. Kiểm từng ảnh không có người, giấy tờ, nhãn thuốc. **[cần rà soát pháp lý]**: còn phải lập hồ sơ Điều 20 khoản 2 không |
| X2 | Sao lưu `pg_dump` mã hoá lên Google Drive | Có thể thuộc điểm a (lưu trữ ngoài lãnh thổ), dù dữ liệu đã mã hoá và khoá ở Việt Nam | **[cần rà soát pháp lý]**. Phương án thay: sao lưu sang ổ/máy thứ hai trong nước |
| X3 | Cloudflare Tunnel | TLS kết thúc tại hạ tầng Cloudflare nên request (kể cả ảnh, hồ sơ) đi qua máy chủ của Cloudflare ở dạng giải mã | **[cần rà soát pháp lý]**. Phương án thay: tên miền trỏ thẳng về máy chủ với chứng chỉ riêng |
| X4 | Nhà cung cấp SMTP (A09) | Có nếu chọn dịch vụ đặt ở nước ngoài (chỉ email + liên kết) | Chọn nhà cung cấp trong nước, hoặc lập hồ sơ |
| X5 | Dịch vụ build (EAS), GitHub | Không chứa dữ liệu người dùng | Không cần, giữ bí mật và dữ liệu ngoài repo |

## 9. Thời hạn lưu và xoá

| Dữ liệu | Thời hạn | Cơ chế | Căn cứ |
|---|---|---|---|
| Ảnh quét gốc (`tmp/`) | 30 ngày | UC32 `python -m tastoria.jobs.purge_images`, ghi `scan_images.purged_at` | BR-RETAIN-01 |
| Ảnh đã góp (`contrib/`) | đến khi rút `photo_contribution` hoặc xoá tài khoản | xoá trong ≤ 24 giờ | BR-CONSENT-04 |
| Bản sao lưu | ≤ 14 ngày (7 bản ngày + 1 bản tuần) | UC33; quay vòng | BR-RETAIN-01; nằm trong hạn xoá 20 ngày của NĐ 356 Điều 5 khoản 4 |
| `idempotency_keys` | 48 giờ | UC34 | thiết kế v2 §8 |
| `refresh_tokens` | hết hạn sau 30 ngày; dòng hết hạn bị dọn | UC34 | NFR-SEC-01 |
| `password_resets` | đến khi dùng hoặc hết hạn; dòng hết hạn bị dọn | UC34 | thời gian sống của liên kết chưa định (đề xuất 30 phút) |
| Bộ đếm đăng nhập sai (Valkey) | 15 phút | TTL | NFR-SEC-02 |
| `interactions` | đến khi rút `personalization` hoặc xoá tài khoản | xoá trong ≤ 24 giờ | BR-CONSENT-04 |
| Chỉ số cơ thể (`profiles.*_enc`) | đến khi rút `health_profile` hoặc xoá tài khoản | đặt NULL / xoá trong ≤ 24 giờ | BR-CONSENT-04 |
| Dữ liệu tài khoản, kho, mâm, nấu | đến khi xoá tài khoản | `ON DELETE CASCADE` từ `users`, xoá tệp | UC07, BR-DSR-01 |
| `consent_events` | đến khi xoá tài khoản | cascade | ADR 0006 |
| `dsr_requests` | **chưa định** | `user_id` → NULL khi xoá tài khoản, giữ `subject_ref` làm bằng chứng | đề xuất định thời hạn có lý do |
| `audit_log` | **chưa định** | `actor_user_id` → NULL khi xoá tài khoản | đề xuất định thời hạn |
| Dữ liệu khảo sát | **chưa định** | không có endpoint cho người tham gia tự xoá | đề xuất: giữ đến hết đồ án, có đường xoá theo token |
| Bản xuất huấn luyện, run MLflow | **chưa định** | áp danh sách xoá vào lần xuất kế tiếp; bản cũ trên máy lab chưa có quy tắc xoá | đề xuất giữ ≤ 1 bản gần nhất, xoá bản cũ |
| Log ứng dụng, log nginx | **chưa định** | | đề xuất ≤ 14 ngày, cùng hạn bản sao lưu |

Các dòng **chưa định** là việc phải làm trước khi phát hành.

## 10. Biện pháp bảo vệ

Kỹ thuật:
- Mật khẩu Argon2id; access JWT 15 phút; refresh token opaque lưu băm, xoay vòng, phát hiện dùng lại; `token_version` để thu hồi ngay (ADR 0004, NFR-SEC-01).
- Khoá đăng nhập 15 phút sau 5 lần sai (NFR-SEC-02).
- Chống BOLA: mọi truy vấn `{id}` lọc theo chủ sở hữu, id công khai là UUID (ADR 0004).
- Mã hoá cột chỉ số cơ thể AES-GCM, khoá ngoài repo và ngoài bản sao lưu, chỉ M05 giải mã, ghi `audit_log` (ADR 0005).
- Ranh giới module cưỡng chế bằng import-linter (ADR 0001).
- Ảnh: kiểm magic bytes, giới hạn kích thước và số điểm ảnh, xoá EXIF, phục vụ qua kiểm quyền + `X-Accel-Redirect`, không có URL công khai (ADR 0002).
- Cổng đồng ý trong mã; `interactions` chỉ ghi khi có `personalization` (ADR 0006).
- Bản xuất huấn luyện bí danh hoá bằng HMAC-SHA256, khoá tách riêng, chỉ trên máy lab (ADR 0012).
- Bản sao lưu mã hoá; diễn tập khôi phục ≥ 1 lần (NFR-REL-01).
- nginx chỉ bind 127.0.0.1, ra Internet qua tunnel; PostgreSQL và Valkey không mở cổng ra ngoài.
- TLS trên mọi kết nối từ app.

Tổ chức:
- Phân vai trò `user`, `admin`, `curator`, `ml_operator`; mỗi thao tác nhân sự ghi `audit_log`.
- Một đầu mối bảo vệ dữ liệu trong nhóm (§2).
- Quy trình xử lý yêu cầu thủ công (UC08, UC27) có hạn xử lý (§11).
- Quy trình phản ứng sự cố (§12, R15).
- Thoả thuận bằng văn bản với lab và các bên xử lý ở §2.

## 11. Quyền của chủ thể dữ liệu và thời hạn đáp ứng

Quyền theo Luật 91 Điều 4 khoản 1. Thời hạn theo NĐ 356 Điều 5. Mục tiêu của Tastoria: tự hoàn tất ≤ 24 giờ với yêu cầu tự động (BR-DSR-01, NFR-PRIV-01), luôn trong hạn luật định.

| Quyền (Luật 91 Điều 4 khoản 1) | Cách thực hiện trong Tastoria | Hạn theo NĐ 356 Điều 5 | Mục tiêu Tastoria |
|---|---|---|---|
| Được biết về hoạt động xử lý (điểm a) | Văn bản điều khoản theo mục đích: `GET /policies/{purpose}/current`; trang quyền riêng tư trên landing | — | luôn có |
| Đồng ý, không đồng ý, rút lại đồng ý (điểm b) | UC05: `POST /me/consents`, `POST /me/consents/{purpose}/withdraw` | Khoản 2: phản hồi trong 02 ngày làm việc, thực hiện trong 15 ngày | hiệu lực ngay, xoá dữ liệu của mục đích ≤ 24 giờ (BR-CONSENT-04) |
| Xem, chỉnh sửa (điểm c) | UC10, UC11, UC14: `GET /me/profile`, `PUT /me/profile`, `PUT /me/allergens`, `PUT /me/diet`, `PATCH /pantry/lots/{id}`; yêu cầu sửa thủ công qua UC08 | Khoản 3: phản hồi 02 ngày làm việc, thực hiện 10 ngày | tự phục vụ ngay; thủ công ≤ 24 giờ |
| Yêu cầu cung cấp dữ liệu (điểm d) | UC06: `POST /me/data-requests` (`type = export`), `GET /me/data-requests/{id}`, `GET /me/data-requests/{id}/download` | Khoản 3: 10 ngày | ≤ 24 giờ |
| Yêu cầu xoá (điểm d) | UC07: `POST /me/data-requests` (`type = delete`); `users.status = deletion_requested`, tăng `token_version`, job xoá | Khoản 4: 20 ngày | ≤ 24 giờ; bản sao lưu tự hết hạn ≤ 14 ngày |
| Hạn chế xử lý, phản đối xử lý (điểm d) | UC08: `POST /me/data-requests` (`type = restrict` hoặc `object`), A04 xử lý qua `POST /admin/data-requests/{id}/resolve` (UC27) | Khoản 2: phản hồi 02 ngày làm việc, thực hiện 15 ngày | ≤ 24 giờ phản hồi |
| Khiếu nại, tố cáo, khởi kiện, yêu cầu bồi thường (điểm đ) | Email đầu mối bảo vệ dữ liệu (§2) | theo pháp luật liên quan | — |
| Yêu cầu áp dụng biện pháp bảo vệ dữ liệu của mình (điểm e) | Chưa có loại yêu cầu riêng trong `dsr_requests.type`; tạm nhận qua email đầu mối | Khoản 5: 15 ngày | đề xuất bổ sung mô hình |

Gia hạn: NĐ 356 Điều 5 cho phép kéo dài tối đa 01 lần, không quá 15 ngày (nhóm đọc thấy ở khoản 2; khoản này có áp cho mọi loại yêu cầu hay không **[chưa xác minh]**). Tastoria không dự kiến dùng gia hạn.

Người tham gia khảo sát (A03): hiện chỉ có endpoint chấm điểm theo token (`PUT /survey/respondents/{id}/ratings/{recipeId}` và các endpoint cùng nhóm); chưa có đường tự xem hay xoá câu trả lời. Đề xuất bổ sung mô hình.

## 12. Rủi ro, mức độ và biện pháp giảm thiểu

Thang đo. Khả năng: Thấp (khó xảy ra trong vòng đời đồ án), Trung bình (có thể xảy ra), Cao (dễ xảy ra nếu không có biện pháp). Mức độ ảnh hưởng: Thấp (bất tiện, không lộ dữ liệu nhạy cảm), Trung bình (lộ dữ liệu cơ bản hoặc thói quen), Cao (lộ dữ liệu nhạy cảm hoặc gây hại sức khoẻ). Cột khả năng và mức độ là **trước** biện pháp; cột cuối là rủi ro còn lại **sau** biện pháp.

| # | Rủi ro | Khả năng | Mức độ | Biện pháp | Rủi ro còn lại |
|---|---|---|---|---|---|
| R01 | Rò cơ sở dữ liệu hoặc bản sao lưu làm lộ chỉ số cơ thể | Trung bình | Cao | Mã hoá cột AES-GCM, khoá tách khỏi DB và bản sao lưu; bản sao lưu mã hoá; DB không mở cổng | Thấp |
| R02 | Rò DB làm lộ dị ứng, mục tiêu kcal, chế độ ăn (không mã hoá) | Trung bình | Trung bình | Phân quyền; DB không mở cổng; bản sao lưu mã hoá; giữ ≤ 14 ngày | Trung bình |
| R03 | Người dùng A đọc dữ liệu của B qua `{id}` (BOLA) | Cao | Cao | Dependency lọc theo chủ sở hữu cho mọi `{id}`; UUID; ca kiểm thử A→B trả 404 cho mọi endpoint `{id}` | Thấp |
| R04 | Chiếm phiên do lộ refresh token | Trung bình | Trung bình | Xoay vòng, thu hồi cả family khi dùng lại; secure-store trên Android, cookie `HttpOnly` trên web; `logout-all` | Thấp |
| R05 | Ảnh tủ lạnh lọt khuôn mặt, giấy tờ, nhãn thuốc | Cao | Trung bình | Hướng dẫn chụp; xoá EXIF; xoá sau 30 ngày; chỉ chủ ảnh xem được; ảnh góp chỉ khi đồng ý; người gán nhãn được dặn bỏ ảnh có người | Trung bình |
| R06 | Tái nhận dạng từ bản xuất bí danh hoá | Trung bình | Trung bình | HMAC khoá tách riêng; làm thô thời gian; chỉ trên máy lab; chỉ người có đồng ý | Thấp |
| R07 | Dữ liệu còn sau khi xoá tài khoản (bản sao lưu, bản xuất, Label Studio, MLflow) | Cao | Trung bình | Bản sao lưu ≤ 14 ngày; áp danh sách xoá vào lần xuất kế tiếp; xoá ảnh trong Label Studio theo danh sách xoá. Thời hạn bản xuất cũ và MLflow chưa định (§9) | Trung bình |
| R08 | Tiếp tục xử lý sau khi rút đồng ý (job đang chạy, outbox của app gửi muộn) | Trung bình | Trung bình | Cổng đồng ý kiểm ở server lúc ghi, không ở app; `token_version` tăng; job xoá ≤ 24 giờ | Thấp |
| R09 | Dữ liệu ra nước ngoài ngoài kế hoạch (X1–X4 ở §8) | Cao | Trung bình | Bảng §8; thay sao lưu Drive và Cloudflare bằng phương án trong nước nếu rà soát yêu cầu | Trung bình đến khi rà soát xong |
| R10 | Lọc dị ứng sai → mâm có món gây dị ứng (hại sức khoẻ) | Trung bình | Cao | BR-ALG-01: lọc cứng cả gia vị và đồ thay thế, dị ứng người ăn cùng; kiểm thử toàn kho món × mọi nhóm dị ứng trong CI; app ghi rõ là gợi ý, người dùng tự kiểm | Thấp |
| R11 | Xử lý dữ liệu người thứ ba không có đồng ý (dị ứng người ăn cùng, người trong ảnh) | Trung bình | Thấp | Chỉ lưu mã nhóm dị ứng theo mâm; nhắc người dùng; xoá theo mâm | Thấp |
| R12 | Nhân sự lạm quyền (đọc yêu cầu, bản xuất) | Thấp | Trung bình | Vai trò tách bạch; `audit_log` chỉ ghi thêm; không có endpoint nhân sự đọc hồ sơ sức khoẻ | Thấp |
| R13 | Mất hoặc lộ khoá mã hoá cột / khoá HMAC / khoá ký JWT | Thấp | Cao | Khoá ngoài repo và image; sao lưu khoá tách bản sao lưu DB; `enc_key_id` và `kid` cho xoay khoá | Thấp |
| R14 | Không đáp ứng kịp yêu cầu thủ công (UC08) | Trung bình | Thấp | `dsr_requests` có `received_at`, `acknowledged_at`; danh sách chờ ở `GET /admin/data-requests`; cảnh báo yêu cầu quá 24 giờ | Thấp |
| R15 | Sự cố vi phạm (rò dữ liệu) không được báo đúng hạn | Thấp | Cao | Quy trình: đầu mối đánh giá; nếu thuộc Luật 91 Điều 23 khoản 1 thì báo cơ quan chuyên trách chậm nhất 72 giờ từ khi phát hiện; lập biên bản (khoản 2); nội dung thông báo theo NĐ 356 Điều 28 | Thấp |
| R16 | Trọng số mô hình công bố theo AGPL học từ ảnh người dùng | Thấp | Thấp | Chỉ công bố trọng số học từ dữ liệu công khai và ảnh nhóm có đồng ý (ADR 0011) | Thấp |
| R17 | Log chứa dữ liệu cá nhân, không hạn lưu | Cao | Thấp | Không log thân request; log chỉ `request_id` và UUID; đặt hạn lưu (§9) | Thấp sau khi đặt hạn |
| R18 | Người tham gia khảo sát bị nhận ra qua tổ hợp câu trả lời | Thấp | Thấp | Không thu tên, email, IP; xuất kết quả theo tổng hợp; mẫu xuất cho phân tích dùng id bí danh | Thấp |

## 13. Kết quả đánh giá tuân thủ (NĐ 356 Điều 19 khoản 3 điểm e)

| Yêu cầu | Trạng thái theo thiết kế v2 |
|---|---|
| Đồng ý theo từng mục đích, không tích sẵn, kiểm chứng được (Luật 91 Điều 9) | Đạt theo thiết kế (ADR 0006) |
| Lưu và chứng minh được sự đồng ý (NĐ 356 Điều 6 khoản 2) | Đạt khi tài khoản còn; sau khi xoá tài khoản **[cần rà soát pháp lý]** |
| Rút đồng ý (Luật 91 Điều 10) | Đạt theo thiết kế |
| Thực hiện quyền trong hạn (NĐ 356 Điều 5) | Đạt theo thiết kế cho yêu cầu tự động; thủ công phụ thuộc quy trình |
| Phân loại và bảo vệ dữ liệu nhạy cảm | Đạt một phần: chỉ số cơ thể mã hoá; dị ứng và kcal chỉ được bảo vệ bằng phân quyền |
| Căn cứ xử lý dữ liệu dịch vụ cốt lõi | Chưa xác định (§6) |
| Chuyển xuyên biên giới | Chưa đạt: X1–X4 ở §8 cần quyết định |
| Thời hạn lưu cho mọi loại dữ liệu | Chưa đạt: các dòng "chưa định" ở §9 |
| Hồ sơ đánh giá tác động (Luật 91 Điều 21) | Bản nháp này; chưa gửi cơ quan chuyên trách |
| Thông báo vi phạm (Luật 91 Điều 23) | Có quy trình (R15), chưa diễn tập |
| Bên xử lý có thoả thuận | Chưa có |

## 14. Kết luận

- Tastoria xử lý dữ liệu cá nhân nhạy cảm (chỉ số cơ thể, dị ứng, hành vi sử dụng), nên nghĩa vụ đánh giá tác động theo Luật 91 Điều 21 được coi là áp dụng khi mở cho người dùng ngoài nhóm. Ngoại lệ cho doanh nghiệp nhỏ ở Điều 38 không áp dụng vì có xử lý dữ liệu nhạy cảm.
- Thiết kế v2 đã đặt các biện pháp chính: đồng ý theo mục đích có nhật ký, cổng đồng ý trong mã, mã hoá cột sức khoẻ, chống BOLA, xoá ảnh 30 ngày, bản sao lưu ≤ 14 ngày, huấn luyện trong nước, yêu cầu của chủ thể hoàn tất ≤ 24 giờ. Với các biện pháp này, phần lớn rủi ro còn lại ở mức Thấp.
- Rủi ro còn lại ở mức Trung bình: R02 (dị ứng, kcal không mã hoá), R05 (nội dung ảnh), R07 (dữ liệu còn sau khi xoá), R09 (luồng ra nước ngoài).
- Việc phải làm trước khi phát hành cho người dùng ngoài nhóm:
  1. Rà soát pháp lý toàn bộ hồ sơ, đặc biệt các mục **[cần rà soát pháp lý]** và **[chưa xác minh]**; đối chiếu điều khoản với bản Công báo.
  2. Quyết định X1–X4 ở §8 (Gemini, sao lưu Drive, Cloudflare, SMTP).
  3. Xác định căn cứ xử lý dữ liệu cốt lõi và mục đích đồng ý cho `user_allergens`.
  4. Đặt thời hạn lưu cho các dòng "chưa định" ở §9.
  5. Điền thông tin bên kiểm soát và đầu mối bảo vệ dữ liệu; ký thoả thuận với lab và các bên xử lý.
  6. Thêm đường cho người tham gia khảo sát xem và xoá câu trả lời.
  7. Gửi hồ sơ cho cơ quan chuyên trách trong 60 ngày kể từ ngày đầu xử lý, nếu rà soát xác nhận nghĩa vụ.
- Giai đoạn thử với thành viên nhóm và người thử đã đồng ý bằng văn bản có thể tiến hành trong khi làm các việc trên, nếu rà soát xác nhận điều đó.

## 15. Bảng xác minh điều khoản

Ngày kiểm: 17/10/2026. Cổng văn bản chính thức vbpl.moj.gov.vn không truy cập được từ máy chủ soạn tài liệu; các điều khoản được đọc qua bản đăng lại dưới đây.

| Điều khoản | Nội dung dùng trong hồ sơ | Nguồn đã mở | Trạng thái |
|---|---|---|---|
| Luật 91/2025/QH15: số hiệu, ngày thông qua 26/06/2025, hiệu lực 01/01/2026 | thông tin văn bản | https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025.html/dieu-1 ; https://gvlawyers.com.vn/wp-content/uploads/2025/09/VN_Legal-alert-_Law-on-PDP-2025.pdf (qua kết quả tìm kiếm) | Đã đối chiếu qua bản đăng lại |
| Luật 91 Điều 2 khoản 1–3, 5–12 | định nghĩa dữ liệu cá nhân, cơ bản, nhạy cảm, các bên, khử nhận dạng, đánh giá tác động | https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-2 | Đã đối chiếu qua bản đăng lại |
| Luật 91 Điều 4 khoản 1 điểm a–e | quyền của chủ thể | https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-4 | Đã đối chiếu qua bản đăng lại |
| Luật 91 Điều 9 khoản 2, 3, 4 | điều kiện của sự đồng ý | https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-9 | Đã đối chiếu qua bản đăng lại |
| Luật 91 Điều 10 | tiêu đề "Yêu cầu rút lại sự đồng ý, yêu cầu hạn chế xử lý dữ liệu cá nhân" | nêu trong trang Điều 9 ở trên | Chỉ đối chiếu tiêu đề **[chưa xác minh nội dung]** |
| Luật 91 Điều 20 khoản 1, 2, 6 | chuyển xuyên biên giới, hồ sơ 60 ngày, miễn trừ | https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-20 | Đã đối chiếu qua bản đăng lại |
| Luật 91 Điều 21 khoản 1–7 | hồ sơ đánh giá tác động, 60 ngày, 01 bản chính | https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-21 | Đã đối chiếu qua bản đăng lại |
| Luật 91 Điều 22 | cập nhật hồ sơ | chỉ thấy tiêu đề trong mục lục | **[chưa xác minh nội dung]** |
| Luật 91 Điều 23 khoản 1, 2, 5 | thông báo vi phạm, 72 giờ | https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-23 | Đã đối chiếu qua bản đăng lại |
| Luật 91 Điều 38 khoản 2–4 | miễn trừ doanh nghiệp nhỏ, siêu nhỏ, hộ kinh doanh | https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-38 | Đã đối chiếu qua bản đăng lại |
| Luật 91: các trường hợp xử lý không cần đồng ý | căn cứ cho dữ liệu cốt lõi | chưa mở | **[chưa xác minh]** |
| NĐ 356/2025/NĐ-CP: ban hành 31/12/2025, hiệu lực 01/01/2026, thay NĐ 13/2023 | thông tin văn bản | https://luatvietnam.vn/dan-su/nghi-dinh-356-2025-nd-cp-quy-dinh-chi-tiet-luat-bao-ve-du-lieu-ca-nhan-422896-d1.html | Đã đối chiếu qua bản đăng lại |
| NĐ 356 Điều 3, Điều 4 khoản 1 điểm d, đ, h, l | danh mục dữ liệu cơ bản, nhạy cảm | như trên | Điều 4 khoản 1 các điểm nêu: đã đối chiếu; danh mục đầy đủ và điểm về tôn giáo **[chưa xác minh]** |
| NĐ 356 Điều 5 khoản 2–5 | thời hạn thực hiện quyền (02 ngày làm việc; 15; 10; 20; 15 ngày; gia hạn 01 lần ≤ 15 ngày) | như trên | Đã đối chiếu qua bản đăng lại; phạm vi của gia hạn **[chưa xác minh]** |
| NĐ 356 Điều 6 khoản 2 | lưu và chứng minh sự đồng ý | như trên | Đã đối chiếu qua bản đăng lại |
| NĐ 356 Điều 17 khoản 3 | miễn đánh giá tác động chuyển xuyên biên giới | như trên | Đã đối chiếu qua bản đăng lại |
| NĐ 356 Điều 19 khoản 3 | nội dung báo cáo đánh giá tác động | như trên | Đã đối chiếu qua bản đăng lại; mẫu biểu phụ lục **[chưa xác minh]** |
| NĐ 356 Điều 28 | nội dung thông báo vi phạm (Mẫu số 08) | như trên | Đã đối chiếu qua bản đăng lại |
| Điều khoản Gemini API, mục Paid Services | không dùng để cải thiện sản phẩm; log giới hạn; lưu tạm ở bất kỳ quốc gia nào | https://ai.google.dev/gemini-api/terms | Đã mở trực tiếp |

Căn cứ thiết kế: thiết kế v2 §3 dòng 21–23, §4 nhóm "Đồng ý và quyền dữ liệu", §8, §10; phát hiện review:sad#11 và review:backend_ops#7 trong [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
