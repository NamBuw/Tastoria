"""Danh mục mã lỗi duy nhất của API Tastoria: (code, HTTP, khi nào, nguồn).

Nguồn sự thật là tiêu chí chấp nhận FR/BR trong docs/sad/use-cases và SRS; OpenAPI theo đúng danh mục này.
Mã chung (không gắn một UC) đứng đầu.
"""

CATALOG = [
    # ---- chung
    ("validation_error", "400, 422", "Thân/tham số sai cú pháp hoặc kiểu (400), hoặc vi phạm ràng buộc miền không có mã riêng (422); chi tiết trong `errors[]`", "UC09–UC14"),
    ("not_found", "404", "Không có tài nguyên, hoặc tài nguyên không thuộc người gọi (chống BOLA: không phân biệt hai trường hợp)", "FR-12-14"),
    ("unauthenticated", "401", "Thiếu access token, chữ ký sai hoặc token hết hạn", "NFR-SEC-01"),
    ("token_revoked", "401", "Access token mang `token_version` nhỏ hơn `users.token_version` (đăng xuất mọi nơi, rút đồng ý, yêu cầu xoá)", "FR-02-09, FR-03-04"),
    ("forbidden", "403", "Vai trò không đủ quyền (endpoint nhân sự)", "UC08"),
    ("app_too_old", "412", "`X-App-Version` thấp hơn phiên bản tối thiểu server còn hỗ trợ", "NFR-MAINT-01"),
    ("rate_limited", "429", "Vượt giới hạn tần suất; xem `Retry-After`", "NFR-SEC-02"),
    ("conflict_state", "409", "Chuyển trạng thái không hợp lệ theo máy trạng thái khi UC không định mã riêng (nhận mâm đã `cooked`, đổi món đã `swapped_out`, sửa dòng đi chợ không `open`...)", "FR-15-33, FR-16-03, FR-17-13, FR-18-07"),
    ("idempotency_key_required", "400", "Thiếu header `Idempotency-Key` ở thao tác bắt buộc có khoá", "UC12"),
    ("idempotency_key_reused", "422", "Cùng `Idempotency-Key` nhưng thân yêu cầu khác (request_sha256 lệch)", "FR-12-06"),
    ("idempotency_in_progress", "409", "Yêu cầu đầu tiên mang cùng `Idempotency-Key` vẫn đang chạy; xem `Retry-After`", "UC15"),
    ("service_unavailable", "503", "Phụ thuộc (CSDL, Valkey, mô hình) chưa sẵn sàng; xem `Retry-After`", "UC02"),
    ("temporarily_unavailable", "503", "Lỗi CSDL tạm thời trong giao dịch, đã rollback, chưa lưu khoá lũy đẳng; gửi lại cùng `Idempotency-Key`", "UC19, UC20, UC21"),
    # ---- identity
    ("email_taken", "409", "Email đã có tài khoản", "UC01"),
    ("invalid_email", "422", "Email sai cú pháp", "FR-01-04"),
    ("weak_password", "422", "Mật khẩu ngắn hơn `password_min_length`", "FR-01-03, FR-04-09"),
    ("invalid_credentials", "401", "Sai email hoặc mật khẩu (không tiết lộ cái nào sai)", "UC02"),
    ("login_locked", "429", "Cặp (email, IP) bị khoá 15 phút sau 5 lần sai (NFR-SEC-02); xem `Retry-After`", "FR-02-03"),
    ("account_deletion_pending", "403", "Tài khoản `status = deletion_requested`: không đăng nhập, không làm mới phiên", "FR-02-08"),
    ("refresh_invalid", "401", "Refresh token không tồn tại hoặc hết hạn", "UC02"),
    ("refresh_reused", "401", "Refresh token đã thu hồi bị dùng lại; cả family bị thu hồi (NFR-SEC-01)", "FR-02-07"),
    ("reset_token_invalid", "400", "Token đặt lại mật khẩu sai, đã dùng hoặc hết hạn", "UC04"),
    # ---- privacy
    ("purpose_not_found", "404", "Mục đích không có trong `consent_purposes`", "UC05"),
    ("purpose_not_allowed", "422", "Mục đích không ghi được qua endpoint này (`survey`) hoặc mã lạ trong lô quyết định", "UC05"),
    ("policy_outdated", "409", "`policy_version_id` gửi lên không phải bản điều khoản hiện hành", "FR-05-04, FR-23-04"),
    ("consent_required", "403, 422", "403: thao tác của người dùng cần một mục đích chưa được đồng ý (BR-CONSENT-01..03). 422: `POST /survey/respondents` có cờ đồng ý false (FR-23-02)", "UC09, UC12, FR-23-02"),
    ("reauth_failed", "403", "Mật khẩu xác nhận lại sai khi gửi yêu cầu xoá tài khoản", "FR-07-01"),
    ("invalid_request", "422", "Yêu cầu dữ liệu sai loại hoặc thiếu ghi chú bắt buộc", "FR-08-02"),
    ("reason_required", "422", "Từ chối yêu cầu dữ liệu mà không có ghi chú lý do", "FR-08-06"),
    ("request_not_manual", "409", "Yêu cầu loại tự xử lý (`export`, `delete`, `withdraw`) không được đóng tay", "FR-08-09"),
    ("request_not_ready", "409", "Tải tệp xuất khi yêu cầu chưa `completed`", "FR-06-09"),
    ("request_not_downloadable", "409", "Tải tệp cho yêu cầu không phải `export`", "UC06"),
    ("export_expired", "410", "Tệp xuất đã bị dọn khỏi volume", "UC06"),
    # ---- profile
    ("age_below_minimum", "422", "Năm sinh cho tuổi < 18 (BR-NUT-01)", "FR-09-05, FR-10-03"),
    ("age_confirmation_required", "422", "Năm hiện tại − năm sinh = 18 mà thiếu `adult_confirmed = true` (BR-NUT-01)", "FR-09-13"),
    ("profile_incomplete", "422", "Thiếu giới, năm sinh, cân nặng hoặc mức vận động để tính gợi ý; kèm danh sách trường", "FR-11-14"),
    ("unknown_code", "422", "Mã dị ứng hoặc chế độ ăn không có trong danh mục", "UC09, UC10"),
    ("favorites_limit", "422", "Quá 5 món hay ăn", "FR-10-11"),
    ("recipe_not_published", "422", "Món hay ăn không ở trạng thái `published`", "FR-10-11"),
    ("below_floor_confirmation_required", "409", "Mục tiêu tự nhập dưới sàn 1.200/1.500 kcal mà chưa có `confirm_below_floor = true`", "FR-11-12"),
    ("decryption_failed", "500", "Không giải mã được cột sức khoẻ (khoá `enc_key_id` không còn)", "UC10, UC11"),
    # ---- scan
    ("image_too_large", "413", "Ảnh lớn hơn 3 MB", "FR-12-02"),
    ("unsupported_media_type", "415", "Magic bytes cho thấy tệp không phải ảnh", "FR-12-03"),
    ("image_too_many_pixels", "422", "Ảnh lớn hơn 4096 × 4096 điểm ảnh", "FR-12-04"),
    ("model_unavailable", "503", "Không có bản `detector` đang chạy; xem `Retry-After`", "UC12"),
    ("queue_full", "503", "Hàng đợi suy luận quá dài; xem `Retry-After`", "UC12"),
    ("scan_not_editable", "409", "Thêm, sửa, xoá chip khi scan không ở `done`", "FR-13-07"),
    ("invalid_scan_state", "409", "Xác nhận hoặc bỏ scan ở trạng thái không cho phép (`queued`, `processing`, `failed`, `expired`, `discarded`)", "FR-13-18"),
    ("duplicate_item", "409", "Thêm nguyên liệu đã có chip trong cùng scan", "FR-13-05"),
    ("unknown_ingredient", "422", "`ingredient_id` không tồn tại hoặc `is_active = false`", "UC13"),
    ("qty_kind_mismatch", "422", "Số đếm cho nguyên liệu không đếm được, hoặc mức lượng cho đồ đếm được", "UC13"),
    ("qty_level_required", "422", "Còn chip không đếm được chưa chọn mức; kèm danh sách chip", "FR-13-11"),
    ("unit_conversion_missing", "422", "Đồ đếm được chưa có dòng `ingredient_units`", "UC13"),
    ("freshness_check_required", "409", "Còn chip nhãn \"kiểm tra trước khi dùng\" chưa xác nhận (BR-FRESH-04); kèm danh sách chip", "FR-13-09"),
    ("image_purged", "410", "Ảnh gốc đã xoá theo hạn 30 ngày (BR-RETAIN-01)", "UC13"),
    # ---- pantry
    ("acquired_at_in_future", "422", "Ngày mua ở tương lai", "UC14"),
    ("invalid_lot_transition", "409", "Chuyển trạng thái lô bằng tay không nằm trong FR-14-13", "FR-14-13"),
    ("lot_closed", "409", "Sửa lô đã `discarded` hoặc `used_up`", "UC14"),
    ("lot_not_check_level", "409", "Xác nhận \"vẫn dùng được\" cho lô không ở mức \"kiểm tra\"", "FR-14-14"),
    # ---- meal
    ("no_feasible_tray", "422", "Không có mâm khả thi (BR-TRAY-06); kèm nguyên liệu thiếu của 3 mâm tốt nhất", "UC15"),
    ("pin_unsatisfiable", "422", "Không mâm nào dùng đủ lô ghim (BR-TRAY-08); kèm id lô", "UC15"),
    ("no_alternative", "422", "Không còn món thay khả thi cho slot (BR-SWAP-01)", "UC16"),
    # ---- cooking
    ("meal_plan_not_accepted", "409", "Tạo phiên nấu cho mâm còn `proposed`", "FR-19-01"),
    ("meal_plan_not_cookable", "409", "Tạo phiên nấu cho mâm `cooked`, `abandoned` hoặc `expired`", "UC19"),
    ("cook_session_in_progress", "409", "Mâm đã có phiên `in_progress`; kèm `cook_session_id`", "FR-19-02"),
    ("cook_session_not_in_progress", "409", "Nấu xong hoặc bỏ phiên không ở `in_progress`", "UC19, UC20"),
    ("cook_session_not_completed", "409", "Hoàn tác phiên không ở `completed`", "UC21"),
    ("undo_window_expired", "409", "Quá 10 phút kể từ khi nấu xong (BR-PANTRY-02)", "UC21"),
    ("recipe_without_steps", "422", "Món trong mâm không có bước nấu để lập lịch", "UC19"),
    # ---- journal
    ("invalid_iso_week", "422", "Tham số `week` không phải tuần ISO 8601 hợp lệ", "FR-22-08"),
    # ---- survey
    ("respondent_token_invalid", "401", "`X-Respondent-Token` thiếu, sai, hết hạn hoặc thuộc người tham gia khác", "UC23"),
    ("survey_closed", "409", "Không có phiếu đang mở, hoặc phiếu đã đóng khi đang làm", "UC23, UC24"),
    ("survey_already_completed", "409", "Ghi sau khi phiếu đã hoàn tất", "UC23"),
    ("survey_incomplete", "422", "Nộp phiếu khi còn món chưa trả lời; kèm danh sách `recipeId`", "FR-23-12"),
    ("invalid_rating", "422", "Điểm ngoài 1–5 hoặc có điểm đồng thời `never_eaten = true`", "FR-23-08"),
    ("invalid_favorites", "422", "Quá 5 món, món trùng hoặc món không `published`", "FR-23-11"),
    ("survey_form_misconfigured", "503", "Kho món `published` ít hơn số món ngẫu nhiên của phiếu", "UC23"),
]

# Mã cũ của bản OpenAPI trước → mã trong danh mục (đổi tên trong mô tả còn sót).
RENAMED = {
    "validation_failed": "validation_error",
    "account_locked": "login_locked",
    "token_reused": "refresh_reused",
    "undo_window_closed": "undo_window_expired",
    "infeasible_tray": "no_feasible_tray",
    "scan_not_ready": "invalid_scan_state",
    "image_invalid": "unsupported_media_type",
}
