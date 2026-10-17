import { ApiError } from './client';
import type { components } from './schema';

type Code = components['schemas']['ProblemCode'];

/** One plain Vietnamese message per problem+json `code` (openapi-v1 ProblemCode). */
const MESSAGES: Record<Code, string> = {
  validation_error: 'Thông tin chưa hợp lệ. Kiểm tra lại các ô được đánh dấu.',
  not_found: 'Không tìm thấy mục này. Có thể nó đã bị xoá.',
  unauthenticated: 'Phiên đăng nhập đã hết. Vui lòng đăng nhập lại.',
  token_revoked: 'Phiên đăng nhập đã bị đóng trên thiết bị khác. Vui lòng đăng nhập lại.',
  forbidden: 'Tài khoản không có quyền làm việc này.',
  app_too_old: 'Phiên bản app đã cũ. Vui lòng cập nhật app.',
  rate_limited: 'Bạn thao tác quá nhanh. Đợi một chút rồi thử lại.',
  conflict_state: 'Trạng thái đã thay đổi. Tải lại rồi thử lại.',
  idempotency_key_required: 'Yêu cầu thiếu khoá chống gửi trùng. Thử lại.',
  idempotency_key_reused: 'Yêu cầu trùng khoá với một yêu cầu khác. Thử lại.',
  idempotency_in_progress: 'Yêu cầu trước vẫn đang xử lý. Đợi vài giây.',
  service_unavailable: 'Máy chủ đang bận. Thử lại sau ít phút.',
  temporarily_unavailable: 'Máy chủ gặp lỗi tạm thời, chưa lưu gì. Thử lại.',
  email_taken: 'Email này đã có tài khoản. Hãy đăng nhập hoặc đặt lại mật khẩu.',
  invalid_email: 'Email chưa đúng định dạng.',
  weak_password: 'Mật khẩu cần ít nhất 10 ký tự.',
  invalid_credentials: 'Email hoặc mật khẩu không đúng.',
  login_locked: 'Đăng nhập sai quá 5 lần. Tài khoản tạm khoá 15 phút.',
  account_deletion_pending: 'Tài khoản đang chờ xoá nên không đăng nhập được.',
  refresh_invalid: 'Phiên đăng nhập đã hết. Vui lòng đăng nhập lại.',
  refresh_reused: 'Phiên đăng nhập bị dùng lại bất thường nên đã đóng. Vui lòng đăng nhập lại.',
  reset_token_invalid: 'Liên kết đặt lại mật khẩu sai, đã dùng hoặc đã hết hạn.',
  purpose_not_found: 'Không có mục đích đồng ý này.',
  purpose_not_allowed: 'Mục đích này không đổi được ở đây.',
  policy_outdated: 'Điều khoản vừa được cập nhật. Đọc lại bản mới rồi chọn lại.',
  consent_required: 'Việc này cần sự đồng ý của bạn. Bật trong Cài đặt › Đồng ý.',
  reauth_failed: 'Mật khẩu xác nhận không đúng.',
  invalid_request: 'Yêu cầu chưa hợp lệ.',
  reason_required: 'Cần ghi lý do.',
  request_not_manual: 'Yêu cầu này được xử lý tự động.',
  request_not_ready: 'Tệp dữ liệu chưa sẵn sàng. Thử lại sau.',
  request_not_downloadable: 'Yêu cầu này không có tệp để tải.',
  export_expired: 'Tệp dữ liệu đã hết hạn. Gửi yêu cầu mới.',
  age_below_minimum: 'Tastoria chỉ tính mục tiêu năng lượng cho người từ 18 tuổi.',
  age_confirmation_required: 'Cần xác nhận bạn đã đủ 18 tuổi.',
  profile_incomplete: 'Thiếu giới, năm sinh, cân nặng hoặc mức vận động để tính gợi ý.',
  unknown_code: 'Danh mục dị ứng hoặc chế độ ăn chưa có mã này.',
  favorites_limit: 'Chỉ chọn tối đa 5 món.',
  recipe_not_published: 'Một món đã chọn không còn trong danh sách. Tải lại rồi chọn lại.',
  below_floor_confirmation_required: 'Mục tiêu thấp hơn mức sàn khuyến nghị. Cần xác nhận.',
  decryption_failed: 'Không đọc được hồ sơ sức khoẻ trên máy chủ.',
  image_too_large: 'Ảnh lớn hơn 3 MB.',
  unsupported_media_type: 'Tệp không phải ảnh.',
  image_too_many_pixels: 'Ảnh lớn hơn 4096 × 4096 điểm ảnh.',
  model_unavailable: 'Mô hình nhận diện chưa chạy. Thử lại sau hoặc thêm đồ bằng tay.',
  queue_full: 'Đang có nhiều ảnh chờ xử lý. Thử lại sau ít phút.',
  scan_not_editable: 'Lần quét này không còn sửa được.',
  invalid_scan_state: 'Lần quét không ở trạng thái cho phép thao tác này.',
  duplicate_item: 'Nguyên liệu này đã có trong danh sách.',
  unknown_ingredient: 'Không có nguyên liệu này trong danh mục.',
  qty_kind_mismatch: 'Nguyên liệu này đo theo cách khác (đếm hoặc ít/vừa/nhiều).',
  qty_level_required: 'Còn nguyên liệu chưa chọn ít / vừa / nhiều.',
  unit_conversion_missing: 'Nguyên liệu này chưa có quy đổi đơn vị sang gam. Nhập theo gam.',
  freshness_check_required: 'Còn nguyên liệu ở mức "kiểm tra trước khi dùng" chưa xác nhận.',
  image_purged: 'Ảnh gốc đã được xoá sau 30 ngày.',
  acquired_at_in_future: 'Ngày mua không thể ở tương lai.',
  invalid_lot_transition: 'Không đổi được trạng thái lô này.',
  lot_closed: 'Lô này đã dùng hết hoặc đã bỏ.',
  lot_not_check_level: 'Lô này không ở mức "kiểm tra trước khi dùng".',
  no_feasible_tray: 'Chưa ghép được mâm từ đồ đang có.',
  pin_unsatisfiable: 'Không mâm nào dùng đủ đồ bạn đã ghim. Bỏ bớt ghim rồi thử lại.',
  no_alternative: 'Không còn món khác phù hợp với đồ đang có.',
  meal_plan_not_accepted: 'Cần nhận mâm trước khi nấu.',
  meal_plan_not_cookable: 'Mâm này đã nấu, đã bỏ hoặc đã hết hạn.',
  cook_session_in_progress: 'Mâm này đang được nấu.',
  cook_session_not_in_progress: 'Phiên nấu không còn đang chạy.',
  cook_session_not_completed: 'Phiên nấu chưa hoàn tất nên không hoàn tác được.',
  undo_window_expired: 'Đã quá 10 phút nên không hoàn tác được. Sửa từng lô trong Kho.',
  recipe_without_steps: 'Một món trong mâm chưa có bước nấu.',
  invalid_iso_week: 'Tuần không hợp lệ.',
  respondent_token_invalid: 'Phiếu khảo sát không còn hiệu lực. Bắt đầu lại.',
  survey_closed: 'Khảo sát hiện chưa mở hoặc đã đóng.',
  survey_already_completed: 'Bạn đã nộp phiếu này.',
  survey_incomplete: 'Còn món chưa trả lời.',
  invalid_rating: 'Điểm phải từ 1 đến 5, hoặc chọn "chưa ăn bao giờ".',
  invalid_favorites: 'Chọn tối đa 5 món khác nhau.',
  survey_form_misconfigured: 'Phiếu khảo sát đang được cấu hình lại.',
  internal_error: 'Máy chủ gặp lỗi. Thử lại.',
};

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 0) return 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.';
    const msg = MESSAGES[e.code as Code];
    if (msg) {
      const ref = e.code === 'internal_error' && e.problem?.request_id ? ` (mã: ${e.problem.request_id})` : '';
      return msg + ref;
    }
    return e.problem?.detail ?? `Có lỗi (${e.status}). Thử lại.`;
  }
  return 'Có lỗi không lường trước. Thử lại.';
}

/** Field errors of a validation problem, keyed by the last pointer segment (`/weight_kg` → `weight_kg`). */
export function fieldErrors(e: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (e instanceof ApiError && e.problem?.errors) {
    for (const fe of e.problem.errors) {
      const key = fe.pointer.split('/').filter(Boolean).pop() ?? '';
      out[key] = fe.message;
    }
  }
  return out;
}

/** Message for a bare problem code (e.g. `scans.error_code`). */
export function codeText(code: string): string {
  return MESSAGES[code as Code] ?? 'Chưa xử lý được.';
}
