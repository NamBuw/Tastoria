"""Thông tin quản trị dữ liệu cho từ điển dữ liệu (db/gen_dictionary.py).

Catalog PostgreSQL không chứa phân loại dữ liệu cá nhân, thời hạn lưu hay luật chỉ kiểm ở service, nên
chúng được khai ở đây. Nguồn: docs/sad/07-danh-gia-tac-dong-du-lieu-ca-nhan.md mục 4 và 9 (thời hạn),
docs/sad/04-chuan-hoa.md (ràng buộc), các UC. Khi 07 mục 9 chốt thời hạn còn "chưa định" thì sửa ở đây.

Phân loại (theo NĐ 356/2025):
  KCN   không phải dữ liệu cá nhân (danh mục, tham chiếu, mô hình)
  CB    dữ liệu cá nhân cơ bản (gắn với một người dùng qua user_id hoặc định danh trực tiếp)
  NC    dữ liệu cá nhân nhạy cảm (sức khoẻ: mục đích health_profile; hành vi: personalization)
  BD    bí danh hoá (HMAC): vẫn là dữ liệu cá nhân, chỉ người giữ khoá tính lại được
  BMXT  bí mật xác thực (băm mật khẩu/token): không trả ra ngoài, không xuất trong tải về dữ liệu
  AD    ẩn danh trong hệ thống (người tham gia khảo sát không có định danh người thật)
"""

CLASS_LABEL = {
    "KCN": "Không phải DLCN",
    "CB": "DLCN cơ bản",
    "NC": "DLCN nhạy cảm",
    "BD": "Bí danh (vẫn là DLCN)",
    "BMXT": "Bí mật xác thực",
    "AD": "Ẩn danh trong hệ thống",
}

_CASCADE = "Đến khi xoá tài khoản: xoá dây chuyền từ users (UC07, ≤ 24 giờ)"

# bảng -> (phân loại mặc định của cột, lưu/xoá, quy mô ước lượng, luật chỉ kiểm ở service)
# Quy mô: ước lượng cho bản thử 1.000 người dùng trong 1 năm, kho 200 món (spec v2 §5); là giả định thiết kế.
TABLES = {
    "idempotency_keys": ("CB", "48 giờ, job dọn UC34", "~10^4 dòng sống", ""),
    "users": ("CB", "Đến khi xoá tài khoản (UC07): xoá cứng dòng", "~10^3", "Khoá tạm theo (email, IP) đếm ở Valkey (NFR-SEC-02); users.locked_until chỉ là bản ghi kết quả."),
    "refresh_tokens": ("BMXT", "Hết hạn sau 30 ngày, job dọn UC34; xoá dây chuyền khi xoá tài khoản", "~10^4", ""),
    "password_resets": ("BMXT", "Đến khi dùng hoặc hết hạn, job dọn UC34", "~10^3", "Thời gian sống của liên kết chưa định (07 mục 9)."),
    "consent_purposes": ("KCN", "Dữ liệu tham chiếu", "4", ""),
    "policy_versions": ("KCN", "Dữ liệu tham chiếu, không xoá (bằng chứng phiên bản đã đồng ý)", "~10", ""),
    "consent_events": ("CB", _CASCADE + "; chỉ ghi thêm", "~10^4", ""),
    "dsr_requests": ("CB", "Chưa định (07 mục 9; đề xuất 24 tháng sau completed_at). Khi xoá tài khoản user_id thành NULL, giữ subject_ref", "~10^2", "Một yêu cầu mở mỗi loại mỗi người (UC08)."),
    "audit_log": ("CB", "Chưa định (07 mục 9; đề xuất 24 tháng). Khi xoá tài khoản: actor_user_id thành NULL, entity_id của chủ thể được ghi đè bằng HMAC (04 D8)", "~10^5", ""),
    "food_groups": ("KCN", "Dữ liệu tham chiếu", "~20", ""),
    "nutrient_sources": ("KCN", "Dữ liệu tham chiếu", "3", ""),
    "food_items": ("KCN", "Dữ liệu tham chiếu", "~10^3 (FCT 2007 có 526 mục, thêm USDA khi thiếu)", ""),
    "nutrients": ("KCN", "Dữ liệu tham chiếu", "7", ""),
    "food_nutrients": ("KCN", "Dữ liệu tham chiếu", "~7 × 10^3", ""),
    "allergen_groups": ("KCN", "Dữ liệu tham chiếu", "10", ""),
    "diets": ("KCN", "Dữ liệu tham chiếu", "1–2", ""),
    "diet_exclusions": ("KCN", "Dữ liệu tham chiếu", "~10", ""),
    "ingredients": ("KCN", "Không xoá cứng (is_active = false, BR-CATALOG-01)", "~300", ""),
    "ingredient_synonyms": ("KCN", "Dữ liệu tham chiếu", "~10^3", ""),
    "ingredient_allergens": ("KCN", "Dữ liệu tham chiếu", "~10^2", ""),
    "ingredient_units": ("KCN", "Dữ liệu tham chiếu", "~10^2", ""),
    "qty_levels": ("KCN", "Dữ liệu tham chiếu", "~60", ""),
    "cooking_methods": ("KCN", "Dữ liệu tham chiếu", "~10", ""),
    "tags": ("KCN", "Dữ liệu tham chiếu", "~50", ""),
    "recipes": ("KCN", "Không xoá cứng (retired, BR-CATALOG-01)", "150–200 món mỗi bản, cộng các bản retired", "Chuyển published khi có ≥ 2 nguồn, mọi nguyên liệu có ánh xạ bảng thành phần, bước liên tục từ 1 (FR-25-08)."),
    "recipe_ingredients": ("KCN", "Theo món", "~2 × 10^3", ""),
    "recipe_steps": ("KCN", "Theo món", "~2 × 10^3", "Bước đánh số liên tục từ 1 (FR-25-08)."),
    "recipe_tags": ("KCN", "Theo món", "~10^3", ""),
    "recipe_sources": ("KCN", "Theo món", "~500", "Mỗi món published có ≥ 2 nguồn (FR-25-08)."),
    "recipe_nutrition": ("KCN", "Tính lại bởi UC25", "~1.400", ""),
    "vision_classes": ("KCN", "Dữ liệu tham chiếu", "~60", ""),
    "vision_class_ingredients": ("KCN", "Dữ liệu tham chiếu", "~100", ""),
    "profiles": ("NC", "Chỉ số cơ thể: đến khi rút health_profile (đặt NULL ≤ 24 giờ, BR-CONSENT-04) hoặc xoá tài khoản", "~10^3", "Tuổi ≥ 18 kiểm sau giải mã (BR-NUT-01)."),
    "user_allergens": ("NC", _CASCADE, "~2 × 10^3", ""),
    "user_favorite_recipes": ("CB", _CASCADE, "~5 × 10^3", "Tối đa 5 món, chỉ món published (FR-10-11)."),
    "user_settings": ("CB", _CASCADE, "~10^3", ""),
    "pantry_lots": ("CB", _CASCADE, "~10^5", "Lô sinh từ quét phải cùng chủ với lần quét (04 D9)."),
    "pantry_transactions": ("CB", _CASCADE + " (qua lô); chỉ ghi thêm", "~5 × 10^5", "Trừ kho theo lô gấp nhất trước (BR-PANTRY-02)."),
    "model_versions": ("KCN", "Không xoá (retired)", "~50", "Chỉ phiên bản validated được triển khai (UC30)."),
    "model_version_classes": ("KCN", "Theo phiên bản mô hình", "~10^3", ""),
    "model_deployments": ("KCN", "Một dòng mỗi loại mô hình", "4", ""),
    "scans": ("CB", _CASCADE, "~5 × 10^4", ""),
    "scan_images": ("CB", "Ảnh gốc xoá sau 30 ngày (UC32) trừ khi đã góp; ảnh góp đến khi rút photo_contribution (BR-RETAIN-01, BR-CONSENT-04)", "~10^5", ""),
    "scan_items": ("CB", _CASCADE, "~5 × 10^5", "Một chip mỗi nguyên liệu trong một lần quét (FR-13-05)."),
    "detections": ("CB", _CASCADE, "~10^6", ""),
    "substitution_pairs": ("KCN", "Dữ liệu tham chiếu", "~10^3", ""),
    "ingredient_embeddings": ("KCN", "Theo phiên bản mô hình", "~300 mỗi phiên bản", ""),
    "shopping_items": ("CB", _CASCADE, "~5 × 10^4", "Dòng sinh từ mâm phải cùng chủ với mâm (04 D9); chuyển trạng thái theo FR-18-07."),
    "meal_plans": ("CB", _CASCADE, "~10^5", ""),
    "meal_plan_coeater_allergens": ("NC", _CASCADE, "~10^4", ""),
    "meal_plan_pins": ("CB", _CASCADE, "~10^4", "Tối đa 2 lô mỗi mâm; lô phải thuộc chủ mâm (BR-TRAY-08)."),
    "meal_plan_items": ("CB", _CASCADE, "~3 × 10^5", "Mâm 2 món khi n = 1, 3 món khi n ≥ 2 (BR-TRAY-01)."),
    "meal_plan_item_substitutions": ("CB", _CASCADE, "~10^4", "Đồ thay không thuộc nhóm dị ứng hay chế độ ăn bị loại (BR-ALG-01, BR-DIET-01)."),
    "cook_sessions": ("CB", _CASCADE, "~10^5", "Hoàn tác trong 10 phút (BR-PANTRY-02)."),
    "cook_schedule_entries": ("CB", _CASCADE, "~10^6", "Lịch thoả BR-COOK-01 (CP-SAT)."),
    "interactions": ("NC", "Đến khi rút personalization hoặc xoá tài khoản (≤ 24 giờ, BR-CONSENT-04); chỉ ghi thêm", "~10^6", "Chỉ ghi khi có đồng ý personalization (BR-CONSENT-03)."),
    "survey_forms": ("KCN", "Đến hết đồ án", "~5", ""),
    "survey_form_anchors": ("KCN", "Đến hết đồ án", "~50", ""),
    "survey_respondents": ("AD", "Chưa định (07 mục 9; đề xuất đến hết đồ án)", "80–100", ""),
    "survey_assignments": ("AD", "Như survey_respondents", "~3 × 10^3", ""),
    "survey_ratings": ("AD", "Như survey_respondents", "~3 × 10^3", ""),
    "survey_favorites": ("AD", "Như survey_respondents", "~500", "Tối đa 5 món (UC23)."),
}

# Phân loại riêng của cột (ghi đè mặc định của bảng).
COLUMNS = {
    ("users", "email"): "CB",
    ("users", "password_hash"): "BMXT",
    ("users", "role"): "KCN",
    ("refresh_tokens", "user_agent"): "CB",
    ("refresh_tokens", "user_id"): "CB",
    ("password_resets", "user_id"): "CB",
    ("dsr_requests", "subject_ref"): "BD",
    ("dsr_requests", "note"): "CB",
    ("audit_log", "entity_id"): "CB",
    ("profiles", "sex_enc"): "NC",
    ("profiles", "birth_year_enc"): "NC",
    ("profiles", "height_cm_enc"): "NC",
    ("profiles", "weight_kg_enc"): "NC",
    ("profiles", "activity_level"): "NC",
    ("profiles", "goal"): "NC",
    ("profiles", "kcal_target"): "NC",
    ("profiles", "kcal_source"): "NC",
    ("profiles", "enc_key_id"): "KCN",
    ("profiles", "diet_code"): "CB",
    ("profiles", "updated_at"): "CB",
    ("scan_images", "storage_key"): "CB",
    ("meal_plans", "e_target_kcal"): "NC",
}

# Ánh xạ máy trạng thái của model.yaml sang lược đồ khi trạng thái không là giá trị của một cột enum.
STATE_MAPPING = [
    ("users (tài khoản)",
     "active, deletion_requested: giá trị users.status. locked: suy ra, users.locked_until > now() (khoá tạm 15 phút, NFR-SEC-02), "
     "không có giá trị enum riêng. deleted: dòng users bị xoá cứng (UC07); chỉ còn dsr_requests với user_id NULL và subject_ref."),
    ("model_versions",
     "candidate, validated, rejected, retired: giá trị model_versions.status. active: suy ra, phiên bản đang được "
     "model_deployments.active_version_id trỏ tới; không lưu cờ is_active để tránh hai nơi cùng ghi một sự thật."),
    ("consent (theo mục đích)",
     "none: chưa có consent_events nào cho (người dùng, mục đích). granted / withdrawn: action của sự kiện mới nhất trong "
     "v_current_consents. superseded: sự kiện mới nhất là grant nhưng v_current_consents.on_current_policy = false."),
    ("pantry_lots",
     "in_stock, not_seen, used_up, discarded: giá trị pantry_lots.status; lượng hiện tại ở v_pantry_lot_balance."),
]
