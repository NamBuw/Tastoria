"""Sinh docs/api/openapi-v1.yaml từ định nghĩa trong tệp này, danh mục mã lỗi docs/api/problem_catalog.py và model.yaml.

Chạy: uv run --with pyyaml python gen_openapi.py <model.yaml> <out.yaml>
"""
import re
import sys
import yaml

MODEL = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
OUT = sys.argv[2]


def R(name):
    return {"$ref": f"#/components/schemas/{name}"}


def nullable(t, **kw):
    d = {"type": [t, "null"]}
    d.update(kw)
    return d


UUID = {"type": "string", "format": "uuid"}
UUIDN = {"type": ["string", "null"], "format": "uuid"}
TS = {"type": "string", "format": "date-time"}
TSN = {"type": ["string", "null"], "format": "date-time"}
DATE = {"type": "string", "format": "date"}
HEX = {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "SHA-256 dạng hex chữ thường"}
SLOT = {"type": "string", "enum": ["man", "rau", "canh"]}
QTY_LEVEL = {"type": "string", "enum": ["it", "vua", "nhieu"]}
FRESH = {"type": "string", "enum": ["tuoi", "dung_som", "dung_ngay", "kiem_tra"]}
SWAP_REASON = {"type": "string", "enum": ["khong_hop_gu", "moi_an", "thieu_thoi_gian", "khac"]}
PURPOSE = {"type": "string", "enum": ["health_profile", "personalization", "photo_contribution", "survey"]}
PROB01 = {"type": ["number", "null"], "minimum": 0, "maximum": 1}


def obj(props, required=None, desc=None, addl=None):
    d = {"type": "object"}
    if desc:
        d["description"] = desc
    d["properties"] = props
    if required:
        d["required"] = required
    if addl is False:
        d["additionalProperties"] = False
    return d


def page(item):
    return obj({
        "items": {"type": "array", "items": R(item)},
        "next_cursor": {"type": ["string", "null"], "description": "Con trỏ keyset cho trang sau; null khi hết dữ liệu"},
    }, ["items", "next_cursor"], f"Một trang {item} theo phân trang keyset (created_at, id)")


# ------------------------------------------------------------------ schemas
import pathlib as _pl, sys as _sys
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
from problem_catalog import CATALOG, RENAMED  # noqa: E402

PROBLEM_CODES = [c for c, *_ in CATALOG]
assert len(PROBLEM_CODES) == len(set(PROBLEM_CODES))

S = {}
S["ProblemCode"] = {
    "type": "string",
    "description": (
        "Danh mục mã lỗi duy nhất của API: mỗi mã có một (hoặc hai, ghi rõ trường hợp) mã HTTP và một điều kiện. "
        "Tiêu chí chấp nhận FR/BR trong `docs/sad/use-cases`, SRS và kế hoạch kiểm thử dùng đúng các mã này. "
        "Client rẽ nhánh theo `code`, không theo `title`. Không đổi nghĩa hay xoá mã đã phát hành; chỉ thêm mã mới.\n\n"
        "| code | HTTP | Khi nào | Nguồn |\n|---|---|---|---|\n"
        + "".join(f"| {c} | {h} | {w} | {src} |\n" for c, h, w, src in CATALOG)
    ),
    "enum": PROBLEM_CODES,
    "x-catalog": [{"code": c, "status": h, "when": w, "source": src} for c, h, w, src in CATALOG],
}
S["FieldError"] = obj({
    "pointer": {"type": "string", "description": "JSON Pointer (RFC 6901) tới trường lỗi trong thân, hoặc `#/query/<tên>` cho tham số", "examples": ["/persons"]},
    "code": {"type": "string", "description": "Mã lỗi cấp trường, ví dụ `out_of_range`, `required`, `max_items`", "examples": ["out_of_range"]},
    "message": {"type": "string", "description": "Mô tả tiếng Việt cho người đọc"},
}, ["pointer", "code", "message"])
S["Problem"] = {
    "type": "object",
    "description": "Chi tiết lỗi theo RFC 9457 (`application/problem+json`). Cho phép thêm trường mở rộng theo từng `code`.",
    "properties": {
        "type": {"type": "string", "format": "uri-reference", "default": "about:blank",
                 "description": "URI định danh loại lỗi, dạng `https://tastoria.ctslab.net/problems/<code>`"},
        "title": {"type": "string", "description": "Tóm tắt ngắn, tiếng Việt, không đổi theo lần xảy ra"},
        "status": {"type": "integer", "minimum": 400, "maximum": 599},
        "detail": {"type": "string", "description": "Giải thích riêng cho lần xảy ra này"},
        "instance": {"type": "string", "format": "uri-reference", "description": "Đường dẫn yêu cầu gây lỗi"},
        "code": R("ProblemCode"),
        "request_id": {"type": "string", "description": "Trùng `request_id` trong log JSON và `audit_log.request_id`"},
        "errors": {"type": "array", "items": R("FieldError"), "description": "Danh sách lỗi cấp trường (khi code = validation_error)"},
    },
    "required": ["type", "title", "status", "code"],
}
S["TrayShortfall"] = obj({
    "rank": {"type": "integer", "minimum": 1, "maximum": 3},
    "recipe_ids": {"type": "array", "items": UUID},
    "missing": {"type": "array", "items": obj({
        "ingredient_id": UUID,
        "name_vi": {"type": "string"},
        "need_g": {"type": "number", "minimum": 0},
        "available_g_min": {"type": "number", "minimum": 0},
    }, ["ingredient_id", "name_vi", "need_g", "available_g_min"])},
}, ["rank", "recipe_ids", "missing"], "Một trong 3 mâm tốt nhất và nguyên liệu còn thiếu (BR-TRAY-06)")
S["InfeasibleTrayProblem"] = {
    "allOf": [R("Problem"), {
        "type": "object",
        "properties": {
            "shortfalls": {"type": "array", "maxItems": 3, "items": R("TrayShortfall")},
            "unmet_pinned_lot_ids": {"type": "array", "items": UUID,
                                     "description": "Lô ghim không mâm nào dùng được ≥ 50% g_min (BR-TRAY-08); gợi ý bỏ ghim"},
        },
    }],
    "description": "Problem với code = no_feasible_tray (kèm 3 mâm tốt nhất và đồ thiếu), pin_unsatisfiable (kèm id lô ghim) hoặc no_alternative",
}
S["PageCursor"] = {"type": "string", "description": "Con trỏ keyset mờ (base64url của (created_at, id)); lấy từ next_cursor"}

# ---- identity
S["UserRole"] = {"type": "string", "enum": ["user", "admin", "curator", "ml_operator"]}
S["UserSummary"] = obj({
    "id": UUID, "email": {"type": "string", "format": "email"}, "role": R("UserRole"),
    "status": {"type": "string", "enum": ["active", "deletion_requested"]}, "created_at": TS,
}, ["id", "email", "role", "status", "created_at"], "Tài khoản (bảng users), không gồm password_hash/token_version")
S["AuthSession"] = obj({
    "access_token": {"type": "string", "description": "JWT, hạn 15 phút, header có `kid` (NFR-SEC-01)"},
    "token_type": {"type": "string", "const": "Bearer"},
    "expires_in": {"type": "integer", "const": 900},
    "refresh_token": {"type": "string", "description": "Chuỗi ngẫu nhiên; server chỉ lưu SHA-256 (refresh_tokens.token_sha256); hạn 30 ngày, xoay vòng mỗi lần dùng"},
    "refresh_expires_at": TS,
    "user": R("UserSummary"),
}, ["access_token", "token_type", "expires_in", "refresh_token", "refresh_expires_at", "user"])
S["RegisterRequest"] = obj({
    "email": {"type": "string", "format": "email", "maxLength": 254},
    "password": {"type": "string", "minLength": 10, "maxLength": 128, "writeOnly": True},
}, ["email", "password"])
S["LoginRequest"] = obj({
    "email": {"type": "string", "format": "email"},
    "password": {"type": "string", "writeOnly": True},
}, ["email", "password"])
S["RefreshRequest"] = obj({"refresh_token": {"type": "string"}}, ["refresh_token"])
S["LogoutRequest"] = obj({"refresh_token": {"type": "string", "description": "Token của thiết bị cần đăng xuất; family của nó bị thu hồi"}}, ["refresh_token"])
S["PasswordResetRequest"] = obj({"email": {"type": "string", "format": "email"}}, ["email"])
S["PasswordResetConfirm"] = obj({
    "token": {"type": "string", "description": "Token trong thư; server so với password_resets.token_sha256"},
    "new_password": {"type": "string", "minLength": 10, "maxLength": 128, "writeOnly": True},
}, ["token", "new_password"])

# ---- privacy
S["ConsentPurposeCode"] = PURPOSE
S["ConsentPurpose"] = obj({
    "code": R("ConsentPurposeCode"), "name_vi": {"type": "string"}, "description_vi": {"type": "string"},
    "data_category": {"type": "string"}, "is_sensitive": {"type": "boolean"}, "is_required": {"type": "boolean"},
}, ["code", "name_vi", "description_vi", "data_category", "is_sensitive", "is_required"], "Bảng consent_purposes")
S["PolicyVersion"] = obj({
    "id": UUID, "purpose_code": R("ConsentPurposeCode"), "version": {"type": "string"},
    "text_sha256": HEX, "effective_from": TS, "purpose": R("ConsentPurpose"),
    "text_vi": {"type": "string", "description": "Nội dung điều khoản; server kiểm SHA-256 khớp text_sha256 trước khi trả"},
}, ["id", "purpose_code", "version", "text_sha256", "effective_from", "purpose", "text_vi"], "Bảng policy_versions (phiên bản hiện hành của một mục đích)")
S["ConsentState"] = obj({
    "purpose_code": R("ConsentPurposeCode"),
    "state": {"type": "string", "enum": ["none", "granted", "withdrawn", "superseded"],
              "description": "superseded = đã đồng ý một phiên bản điều khoản cũ hơn phiên bản hiện hành"},
    "policy_version_id": UUIDN, "version": {"type": ["string", "null"]},
    "current_policy_version_id": UUID,
    "decided_at": TSN,
}, ["purpose_code", "state", "policy_version_id", "version", "current_policy_version_id", "decided_at"],
    "Một dòng của view v_current_consents, kèm phiên bản hiện hành để client biết cần hỏi lại")
S["ConsentList"] = obj({"items": {"type": "array", "items": R("ConsentState")}}, ["items"])
S["ConsentDecision"] = obj({
    "policy_version_id": UUID, "action": {"type": "string", "enum": ["grant", "withdraw"]},
}, ["policy_version_id", "action"])
S["ConsentDecisionBatch"] = obj({
    "channel": {"type": "string", "enum": ["onboarding", "settings"]},
    "decisions": {"type": "array", "minItems": 1, "maxItems": 4, "items": R("ConsentDecision")},
}, ["channel", "decisions"], "Ghi thêm consent_events; không có ô tích sẵn (BR-CONSENT-01)")
S["ConsentWithdrawRequest"] = obj({"channel": {"type": "string", "enum": ["onboarding", "settings"], "default": "settings"}})
S["DataRequestType"] = {"type": "string", "enum": ["access", "export", "correct", "delete", "withdraw", "restrict", "object"]}
S["DataRequestStatus"] = {"type": "string", "enum": ["received", "in_progress", "completed", "rejected"]}
S["DataRequestCreate"] = obj({
    "type": R("DataRequestType"),
    "note": {"type": ["string", "null"], "maxLength": 2000, "description": "Bắt buộc với correct/restrict/object (mô tả nội dung yêu cầu)"},
}, ["type"])
S["DataRequest"] = obj({
    "id": UUID, "type": R("DataRequestType"), "status": R("DataRequestStatus"),
    "received_at": TS, "acknowledged_at": TSN, "completed_at": TSN,
    "due_at": {**TS, "description": "received_at + 24 giờ (NFR-PRIV-01)"},
    "download_available": {"type": "boolean", "description": "true khi type ∈ {access, export}, status = completed và tệp còn hạn"},
    "note": {"type": ["string", "null"]},
}, ["id", "type", "status", "received_at", "acknowledged_at", "completed_at", "due_at", "download_available", "note"],
    "Bảng dsr_requests nhìn từ chủ thể dữ liệu (không lộ subject_ref, result_key)")

# ---- profile
S["Profile"] = obj({
    "sex": {"type": ["string", "null"], "enum": ["male", "female", None], "description": "Giải mã từ profiles.sex_enc"},
    "birth_year": {"type": ["integer", "null"], "description": "Giải mã từ profiles.birth_year_enc"},
    "height_cm": {"type": ["number", "null"], "description": "Giải mã từ profiles.height_cm_enc"},
    "weight_kg": {"type": ["number", "null"], "description": "Giải mã từ profiles.weight_kg_enc"},
    "activity_level": {"type": ["string", "null"], "enum": ["light", "moderate", "heavy", None]},
    "goal": {"type": ["string", "null"], "enum": ["maintain", "lose", "expert", None]},
    "kcal_target": {"type": ["integer", "null"], "minimum": 800, "maximum": 5000},
    "kcal_source": {"type": ["string", "null"], "enum": ["suggested", "user", "expert", None]},
    "diet_code": {"type": ["string", "null"]},
    "allergen_codes": {"type": "array", "items": {"type": "string"}, "description": "user_allergens.allergen_code"},
    "favorite_recipe_ids": {"type": "array", "maxItems": 5, "items": UUID, "description": "user_favorite_recipes.recipe_id"},
    "health_profile_consented": {"type": "boolean", "description": "false → mọi chỉ số cơ thể là null, app hiện 'chưa có mục tiêu' (BR-CONSENT-02)"},
    "updated_at": TSN,
}, ["sex", "birth_year", "height_cm", "weight_kg", "activity_level", "goal", "kcal_target", "kcal_source",
    "diet_code", "allergen_codes", "favorite_recipe_ids", "health_profile_consented", "updated_at"],
    "Hồ sơ (profiles + user_allergens + user_favorite_recipes). Mỗi lần giải mã cột *_enc ghi audit_log")
S["ProfileUpdate"] = obj({
    "sex": {"type": ["string", "null"], "enum": ["male", "female", None]},
    "birth_year": {"type": ["integer", "null"], "minimum": 1900, "description": "Tuổi ≥ 18 (BR-NUT-01), nếu không → 422 age_below_minimum"},
    "height_cm": {"type": ["number", "null"], "minimum": 100, "maximum": 250},
    "weight_kg": {"type": ["number", "null"], "minimum": 25, "maximum": 300},
    "activity_level": {"type": ["string", "null"], "enum": ["light", "moderate", "heavy", None]},
    "goal": {"type": ["string", "null"], "enum": ["maintain", "lose", "expert", None]},
    "adult_confirmed": {"type": "boolean", "default": False,
                        "description": "Xác nhận \"tôi đã đủ 18 tuổi\"; bắt buộc true khi năm hiện tại − birth_year = 18, nếu không → 422 age_confirmation_required (FR-09-13)"},
}, ["sex", "birth_year", "height_cm", "weight_kg", "activity_level", "goal"],
    "Ghi đè toàn bộ phần chỉ số của hồ sơ (PUT). Có chỉ số khác null mà chưa đồng ý health_profile → 403 consent_required")
S["EnergySuggestionRequest"] = obj({
    "goal": {"type": "string", "enum": ["maintain", "lose"], "description": "Mặc định lấy profiles.goal"},
    "formula": {"type": "string", "enum": ["fao_who_unu_1985", "mifflin_st_jeor"], "default": "fao_who_unu_1985"},
})
S["EnergySuggestion"] = obj({
    "formula": {"type": "string", "enum": ["fao_who_unu_1985", "mifflin_st_jeor"]},
    "bmr_kcal": {"type": "number"}, "pal": {"type": "number", "enum": [1.5, 1.75, 2.0]},
    "tee_kcal": {"type": "number"}, "suggested_kcal": {"type": "integer"},
    "floor_applied": {"type": "boolean", "description": "true khi bị nâng lên mức sàn 1.200 (nữ) / 1.500 (nam) kcal (BR-NUT-03)"},
    "e_lunch_kcal": {"type": "number", "description": "E × 0,35 (BR-NUT-04)"},
    "e_dinner_kcal": {"type": "number", "description": "E × 0,30 (BR-NUT-04)"},
}, ["formula", "bmr_kcal", "pal", "tee_kcal", "suggested_kcal", "floor_applied", "e_lunch_kcal", "e_dinner_kcal"],
    "Kết quả tính, không lưu (BR-NUT-01..04)")
S["EnergyTarget"] = obj({
    "kcal_target": {"type": "integer", "minimum": 800, "maximum": 5000},
    "kcal_source": {"type": "string", "enum": ["suggested", "user", "expert"], "description": "expert ghi đè mọi công thức (BR-NUT-03)"},
    "goal": {"type": "string", "enum": ["maintain", "lose", "expert"],
             "description": "Ghi vào profiles.goal; kcal_source = expert đi với goal = expert (ck_profiles_expert)"},
    "confirm_below_floor": {"type": "boolean", "default": False,
                            "description": "Bắt buộc true để lưu mục tiêu tự nhập dưới sàn 1.200 (nữ) / 1.500 (nam) kcal; thiếu → 409 below_floor_confirmation_required (FR-11-12)"},
}, ["kcal_target", "kcal_source"], "profiles.kcal_target, profiles.kcal_source, profiles.goal")
S["AllergenSet"] = obj({"allergen_codes": {"type": "array", "uniqueItems": True, "items": {"type": "string"}}}, ["allergen_codes"])
S["DietSelection"] = obj({"diet_code": {"type": ["string", "null"], "description": "Mã trong diets (v2: chay); null = không theo chế độ"}}, ["diet_code"])
S["FavoriteSet"] = obj({"recipe_ids": {"type": "array", "items": UUID}}, ["recipe_ids"],
                       "Tối đa 5 món hay ăn khác nhau, món phải published. Giới hạn kiểm ở service để trả đúng mã: "
                       "PUT /me/favorites → 422 favorites_limit / recipe_not_published (FR-10-11); "
                       "PUT /survey/respondents/{id}/favorites → 422 invalid_favorites (FR-23-11)")
S["UserSettings"] = obj({
    "burners": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2},
    "default_persons": {"type": "integer", "minimum": 1, "maximum": 6, "default": 2},
    "timezone": {"type": "string", "default": "Asia/Ho_Chi_Minh", "description": "Tên múi giờ IANA"},
    "updated_at": {**TS, "readOnly": True},
}, ["burners", "default_persons", "timezone"], "Bảng user_settings")

# ---- catalog
S["CodeName"] = obj({"code": {"type": "string"}, "name_vi": {"type": "string"}}, ["code", "name_vi"])
S["AllergenGroup"] = obj({"code": {"type": "string"}, "name_vi": {"type": "string"}, "name_en": {"type": "string"},
                          "basis": {"type": "string", "enum": ["codex_2024", "tastoria_extra"]}}, ["code", "name_vi", "name_en", "basis"])
S["Diet"] = obj({"code": {"type": "string"}, "name_vi": {"type": "string"},
                 "excluded_food_group_codes": {"type": "array", "items": {"type": "string"}, "description": "diet_exclusions.food_group_code"}},
                ["code", "name_vi", "excluded_food_group_codes"])
S["Tag"] = obj({"code": {"type": "string"}, "kind": {"type": "string", "enum": ["flavor", "texture", "occasion"]}, "name_vi": {"type": "string"}},
               ["code", "kind", "name_vi"])
S["Nutrient"] = obj({"code": {"type": "string", "enum": ["energy_kcal", "protein_g", "lipid_g", "glucid_g", "fiber_g", "sugar_g", "sodium_mg"]},
                     "name_vi": {"type": "string"}, "unit": {"type": "string"}}, ["code", "name_vi", "unit"])
S["QtyLevel"] = obj({"food_group_code": {"type": "string"}, "level": QTY_LEVEL, "g_min": {"type": "number"}, "g_max": {"type": "number"}},
                    ["food_group_code", "level", "g_min", "g_max"])
S["ReferenceData"] = obj({
    "data_version": {"type": "string"},
    "allergen_groups": {"type": "array", "items": R("AllergenGroup")},
    "diets": {"type": "array", "items": R("Diet")},
    "food_groups": {"type": "array", "items": R("CodeName")},
    "cooking_methods": {"type": "array", "items": R("CodeName")},
    "tags": {"type": "array", "items": R("Tag")},
    "nutrients": {"type": "array", "items": R("Nutrient")},
    "qty_levels": {"type": "array", "items": R("QtyLevel")},
    "consent_purposes": {"type": "array", "items": R("ConsentPurpose")},
}, ["data_version", "allergen_groups", "diets", "food_groups", "cooking_methods", "tags", "nutrients", "qty_levels", "consent_purposes"])
S["IngredientUnit"] = obj({"unit_code": {"type": "string", "enum": ["qua", "bo", "cu", "nhanh", "mieng", "goi", "hop"]},
                           "grams_per_unit": {"type": "number", "exclusiveMinimum": 0}, "source": {"type": "string"}},
                          ["unit_code", "grams_per_unit", "source"])
S["Ingredient"] = obj({
    "id": UUID, "name_vi": {"type": "string"}, "food_group_code": {"type": "string"},
    "is_staple": {"type": "boolean"}, "countable": {"type": "boolean"},
    "shelf_life_days": {"type": ["number", "null"]},
    "allergen_codes": {"type": "array", "items": {"type": "string"}},
    "units": {"type": "array", "items": R("IngredientUnit")},
    "synonyms": {"type": "array", "items": {"type": "string"}},
}, ["id", "name_vi", "food_group_code", "is_staple", "countable", "shelf_life_days", "allergen_codes", "units", "synonyms"],
    "Bảng ingredients (chỉ is_active = true) + ingredient_allergens, ingredient_units, ingredient_synonyms")
S["RecipeSummary"] = obj({
    "id": UUID, "name_vi": {"type": "string"}, "slot": SLOT, "servings": {"type": "integer", "minimum": 1},
    "method_code": {"type": "string"},
    "total_minutes": {"type": "integer", "description": "Dẫn xuất từ recipe_steps, không lưu"},
    "kcal_per_serving": {"type": ["number", "null"], "description": "recipe_nutrition (energy_kcal)"},
    "tag_codes": {"type": "array", "items": {"type": "string"}},
}, ["id", "name_vi", "slot", "servings", "method_code", "total_minutes", "kcal_per_serving", "tag_codes"])
S["RecipeIngredient"] = obj({
    "ingredient_id": UUID, "name_vi": {"type": "string"}, "grams": {"type": "number", "exclusiveMinimum": 0},
    "role": {"type": "string", "enum": ["main", "side", "seasoning"]}, "is_optional": {"type": "boolean"},
    "is_staple": {"type": "boolean"}, "allergen_codes": {"type": "array", "items": {"type": "string"}},
}, ["ingredient_id", "name_vi", "grams", "role", "is_optional", "is_staple", "allergen_codes"])
S["RecipeStep"] = obj({
    "step_no": {"type": "integer", "minimum": 1}, "text_vi": {"type": "string"},
    "kind": {"type": "string", "enum": ["active", "passive"]}, "minutes": {"type": "integer", "minimum": 1},
    "uses_burner": {"type": "boolean"},
}, ["step_no", "text_vi", "kind", "minutes", "uses_burner"])
S["RecipeSource"] = obj({"url": {"type": "string", "format": "uri"}, "title": {"type": "string"}, "accessed_on": DATE},
                        ["url", "title", "accessed_on"])
S["RecipeNutrient"] = obj({"nutrient_code": {"type": "string"}, "per_serving": {"type": "number"}}, ["nutrient_code", "per_serving"])
S["Recipe"] = {"allOf": [R("RecipeSummary"), obj({
    "status": {"type": "string", "enum": ["draft", "published", "retired"]},
    "notes": {"type": ["string", "null"]},
    "ingredients": {"type": "array", "items": R("RecipeIngredient")},
    "steps": {"type": "array", "items": R("RecipeStep")},
    "sources": {"type": "array", "items": R("RecipeSource")},
    "nutrition": {"type": "array", "items": R("RecipeNutrient")},
    "nutrition_data_version": {"type": ["string", "null"], "description": "recipe_nutrition.data_version"},
}, ["status", "notes", "ingredients", "steps", "sources", "nutrition", "nutrition_data_version"], addl=None)],
    "description": "Chi tiết món (recipes + recipe_ingredients + recipe_steps + recipe_tags + recipe_sources + recipe_nutrition). Món retired vẫn đọc được theo id (BR-CATALOG-01)"}
S["CatalogSnapshot"] = obj({
    "data_version": {"type": "string"}, "generated_at": TS,
    "recipes": {"type": "array", "items": R("Recipe")},
    "ingredients": {"type": "array", "items": R("Ingredient")},
}, ["data_version", "generated_at", "recipes", "ingredients"], "Toàn bộ kho món published để app lưu SQLite, nấu offline")

# ---- pantry
S["LotStatus"] = {"type": "string", "enum": ["in_stock", "used_up", "discarded", "not_seen"]}
S["PantryLot"] = obj({
    "id": UUID, "ingredient_id": UUID, "ingredient_name_vi": {"type": "string"},
    "initial_g_min": {"type": "number", "minimum": 0}, "initial_g_max": {"type": "number", "minimum": 0},
    "balance_g_min": {"type": "number", "minimum": 0, "description": "v_pantry_lot_balance"},
    "balance_g_max": {"type": "number", "minimum": 0, "description": "v_pantry_lot_balance"},
    "acquired_at": TS, "acquired_basis": {"type": "string", "enum": ["purchase_date_entered", "first_seen"]},
    "status": R("LotStatus"),
    "p_tuoi": PROB01, "p_dung_som": PROB01, "p_dung_ngay": PROB01, "p_kiem_tra": PROB01,
    "freshness_observed_at": TSN, "user_checked_at": TSN,
    "urgency": {"type": "number", "minimum": 0, "description": "u tính lúc đọc, không lưu (BR-FRESH-01..05)"},
    "freshness_label": {**FRESH, "description": "Nhãn suy từ u (BR-FRESH-04); app luôn hiện chữ kèm chấm màu"},
    "available": {"type": "boolean", "description": "false khi nhãn kiem_tra chưa được người dùng xác nhận — không tính vào lượng khả dụng"},
    "created_at": TS, "updated_at": TS,
}, ["id", "ingredient_id", "ingredient_name_vi", "initial_g_min", "initial_g_max", "balance_g_min", "balance_g_max",
    "acquired_at", "acquired_basis", "status", "p_tuoi", "p_dung_som", "p_dung_ngay", "p_kiem_tra",
    "freshness_observed_at", "user_checked_at", "urgency", "freshness_label", "available", "created_at", "updated_at"],
    "Lô kho (pantry_lots + v_pantry_lot_balance)")
S["QuantityInput"] = {
    "description": "Một trong ba cách nhập lượng; server quy đổi ra [g_min, g_max] (BR-QTY-01, BR-QTY-02)",
    "oneOf": [
        obj({"g_min": {"type": "number", "minimum": 0}, "g_max": {"type": "number", "minimum": 0}}, ["g_min", "g_max"], addl=False),
        obj({"count": {"type": "integer", "minimum": 1}, "unit_code": {"type": "string"}}, ["count", "unit_code"], addl=False),
        obj({"qty_level": QTY_LEVEL}, ["qty_level"], addl=False),
    ],
}
S["PantryLotCreate"] = obj({
    "ingredient_id": UUID, "quantity": R("QuantityInput"),
    "acquired_at": {**TS, "description": "Ngày mua người dùng nhập; bỏ trống = lúc tạo, acquired_basis = first_seen (BR-PANTRY-01)"},
}, ["ingredient_id", "quantity"])
S["PantryLotPatch"] = obj({
    "balance": {**R("QuantityInput"), "description": "Lượng hiện tại mới; server ghi pantry_transactions reason = manual_edit bằng phần chênh"},
    "acquired_at": TS,
    "acquired_basis": {"type": "string", "enum": ["purchase_date_entered"]},
    "status": {"type": "string", "enum": ["in_stock"], "description": "Chỉ dùng để trả lô not_seen về in_stock (BR-PANTRY-03)"},
    "user_checked": {"type": "boolean", "const": True, "description": "Xác nhận đồ 'kiểm tra' vẫn dùng được → user_checked_at = now"},
}, desc="JSON Merge Patch (RFC 7396); trường bỏ trống giữ nguyên")

# ---- scan
S["ScanMode"] = {"type": "string", "enum": ["fridge", "haul"]}
S["ScanStatus"] = {"type": "string", "enum": ["queued", "processing", "done", "failed", "expired", "confirmed", "discarded"]}
S["ScanCreate"] = obj({
    "mode": R("ScanMode"),
    "images": {"type": "array", "minItems": 1, "maxItems": 2,
               "items": {"type": "string", "contentMediaType": "image/jpeg", "description": "≤ 3 MB, ≤ 4096² điểm ảnh; server kiểm magic bytes, exif_transpose, mã hoá lại JPEG bỏ metadata"}},
    "shelf_groups": {"type": "array", "maxItems": 2, "items": {"type": "integer", "minimum": 1, "maximum": 2},
                     "description": "Theo thứ tự ảnh; cùng số = cùng ngăn (lấy max), khác số = cộng (BR-SCAN-01). Mặc định [1, 1]"},
    "contribute": {"type": "boolean", "default": False, "description": "Góp ảnh cho huấn luyện; cần đồng ý photo_contribution"},
}, ["mode", "images"])
S["ScanAccepted"] = obj({"id": UUID, "status": {"type": "string", "const": "queued"}, "created_at": TS}, ["id", "status", "created_at"])
S["ScanImage"] = obj({
    "ordinal": {"type": "integer", "minimum": 1, "maximum": 2}, "shelf_group": {"type": "integer", "minimum": 1},
    "width": {"type": "integer"}, "height": {"type": "integer"}, "contributed": {"type": "boolean"},
    "purged": {"type": "boolean", "description": "true khi purged_at khác null (đã xoá theo BR-RETAIN-01)"},
}, ["ordinal", "shelf_group", "width", "height", "contributed", "purged"])
S["Detection"] = obj({
    "id": {"type": "integer", "format": "int64"}, "image_ordinal": {"type": "integer", "minimum": 1, "maximum": 2},
    "vision_class_code": {"type": "string"},
    "x1": {"type": "number", "minimum": 0, "maximum": 1}, "y1": {"type": "number", "minimum": 0, "maximum": 1},
    "x2": {"type": "number", "minimum": 0, "maximum": 1}, "y2": {"type": "number", "minimum": 0, "maximum": 1},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "p_tuoi": PROB01, "p_dung_som": PROB01, "p_dung_ngay": PROB01, "p_kiem_tra": PROB01,
}, ["id", "image_ordinal", "vision_class_code", "x1", "y1", "x2", "y2", "confidence", "p_tuoi", "p_dung_som", "p_dung_ngay", "p_kiem_tra"],
    "Khung phát hiện (detections), toạ độ chuẩn hoá [0, 1]")
S["ScanItem"] = obj({
    "id": UUID, "ingredient_id": UUID, "ingredient_name_vi": {"type": "string"},
    "origin": {"type": "string", "enum": ["model", "user_added"]},
    "model_count": {"type": ["integer", "null"]}, "final_count": {"type": ["integer", "null"]},
    "qty_level": {"type": ["string", "null"], "enum": ["it", "vua", "nhieu", None]},
    "user_action": {"type": "string", "enum": ["kept", "relabeled", "deleted", "edited"]},
    "original_ingredient_id": UUIDN,
    "predicted_freshness": {"type": ["string", "null"], "enum": ["tuoi", "dung_som", "dung_ngay", "kiem_tra", None]},
    "user_freshness": {"type": ["string", "null"], "enum": ["tuoi", "dung_som", "dung_ngay", "kiem_tra", None]},
    "needs_check": {"type": "boolean", "description": "true khi nhãn dự đoán là kiem_tra và người dùng chưa chọn user_freshness (BR-FRESH-04)"},
    "detections": {"type": "array", "items": R("Detection")},
    "created_at": TS, "updated_at": TS,
}, ["id", "ingredient_id", "ingredient_name_vi", "origin", "model_count", "final_count", "qty_level", "user_action",
    "original_ingredient_id", "predicted_freshness", "user_freshness", "needs_check", "detections", "created_at", "updated_at"],
    "Chip kết quả quét (scan_items)")
S["Scan"] = obj({
    "id": UUID, "mode": R("ScanMode"), "status": R("ScanStatus"),
    "error_code": {"type": ["string", "null"]}, "attempts": {"type": "integer", "minimum": 0, "maximum": 3},
    "created_at": TS, "enqueued_at": TSN, "started_at": TSN, "finished_at": TSN, "confirmed_at": TSN,
    "detector_version_id": UUIDN, "classifier_version_id": UUIDN, "preprocess_version": {"type": ["string", "null"]},
    "images": {"type": "array", "items": R("ScanImage")},
    "items": {"type": "array", "items": R("ScanItem"), "description": "Rỗng khi status ∈ {queued, processing, failed, expired}; không gồm chip user_action = deleted"},
}, ["id", "mode", "status", "error_code", "attempts", "created_at", "enqueued_at", "started_at", "finished_at",
    "confirmed_at", "detector_version_id", "classifier_version_id", "preprocess_version", "images", "items"], "Lần quét (scans)")
S["ScanItemCreate"] = obj({
    "ingredient_id": UUID,
    "final_count": {"type": ["integer", "null"], "minimum": 0},
    "qty_level": {"type": ["string", "null"], "enum": ["it", "vua", "nhieu", None]},
    "user_freshness": {"type": ["string", "null"], "enum": ["tuoi", "dung_som", "dung_ngay", "kiem_tra", None]},
}, ["ingredient_id"], "Thêm chip người dùng tự nhập (origin = user_added)")
S["ScanItemPatch"] = obj({
    "ingredient_id": {**UUID, "description": "Đổi nhãn: server lưu nhãn cũ vào original_ingredient_id, user_action = relabeled"},
    "final_count": {"type": ["integer", "null"], "minimum": 0},
    "qty_level": {"type": ["string", "null"], "enum": ["it", "vua", "nhieu", None]},
    "user_freshness": {"type": ["string", "null"], "enum": ["tuoi", "dung_som", "dung_ngay", "kiem_tra", None]},
}, desc="JSON Merge Patch; sửa chip không ghi kho (BR-SCAN-02)")
S["ScanConfirmRequest"] = obj({
    "purchase_date": {**DATE, "description": "Chế độ haul: mặc định hôm nay (BR-PANTRY-03). Chế độ fridge: có thì acquired_basis = purchase_date_entered"},
}, desc="Thân có thể rỗng")
S["ScanConfirmResult"] = obj({
    "scan_id": UUID, "status": {"type": "string", "const": "confirmed"}, "confirmed_at": TS,
    "created_lot_ids": {"type": "array", "items": UUID},
    "not_seen_lot_ids": {"type": "array", "items": UUID, "description": "Chế độ fridge: lô in_stock không thấy trong lần quét → not_seen, chờ người dùng xử lý (BR-PANTRY-03)"},
}, ["scan_id", "status", "confirmed_at", "created_lot_ids", "not_seen_lot_ids"])

# ---- meal
S["MealType"] = {"type": "string", "enum": ["lunch", "dinner"]}
S["MealPlanStatus"] = {"type": "string", "enum": ["proposed", "accepted", "cooked", "abandoned", "expired"]}
S["MealPlanCreate"] = obj({
    "meal": R("MealType"),
    "persons": {"type": "integer", "minimum": 1, "maximum": 6, "description": "Mặc định user_settings.default_persons (BR-TRAY-01)"},
    "max_minutes": {"type": "integer", "minimum": 10, "maximum": 180, "description": "Makespan lịch nấu tối đa (BR-TRAY-05)"},
    "coeater_allergen_codes": {"type": "array", "uniqueItems": True, "items": {"type": "string"},
                               "description": "Dị ứng của người ăn cùng bữa này (BR-ALG-01) → meal_plan_coeater_allergens"},
    "pinned_lot_ids": {"type": "array", "uniqueItems": True, "maxItems": 2, "items": UUID,
                       "description": "Lô 'phải dùng' (BR-TRAY-08) → meal_plan_pins"},
}, ["meal", "max_minutes"])
S["Substitution"] = obj({
    "original_ingredient_id": UUID, "substitute_ingredient_id": UUID,
    "grams": {"type": "number", "exclusiveMinimum": 0},
    "origin": {"type": "string", "enum": ["lookup", "embedding", "user"]}, "created_at": TS,
}, ["original_ingredient_id", "substitute_ingredient_id", "grams", "origin", "created_at"], "meal_plan_item_substitutions")
S["MealPlanItem"] = obj({
    "id": UUID, "slot": SLOT, "recipe_id": UUID, "recipe_name_vi": {"type": "string"},
    "status": {"type": "string", "enum": ["active", "swapped_out"]},
    "replaced_item_id": UUIDN, "swap_reason": {"type": ["string", "null"], "enum": ["khong_hop_gu", "moi_an", "thieu_thoi_gian", "khac", None]},
    "rank_score": {"type": "number"}, "servings_scale": {"type": "number", "exclusiveMinimum": 0},
    "kcal_per_person": {"type": ["number", "null"]},
    "substitutions": {"type": "array", "items": R("Substitution")},
    "created_at": TS,
}, ["id", "slot", "recipe_id", "recipe_name_vi", "status", "replaced_item_id", "swap_reason", "rank_score",
    "servings_scale", "kcal_per_person", "substitutions", "created_at"], "meal_plan_items")
S["MealPlanSummary"] = obj({
    "id": UUID, "meal": R("MealType"), "persons": {"type": "integer"}, "status": R("MealPlanStatus"),
    "recipe_names_vi": {"type": "array", "items": {"type": "string"}, "description": "Tên các món active"},
    "created_at": TS,
}, ["id", "meal", "persons", "status", "recipe_names_vi", "created_at"])
S["MealPlan"] = obj({
    "id": UUID, "meal": R("MealType"), "persons": {"type": "integer", "minimum": 1, "maximum": 6},
    "max_minutes": {"type": "integer"}, "status": R("MealPlanStatus"),
    "e_target_kcal": {"type": ["number", "null"], "description": "Ảnh chụp E_mâm × n lúc tạo (BR-TRAY-07); null khi chưa có mục tiêu (BR-CONSENT-02)"},
    "kcal_low": {"type": ["number", "null"], "description": "null khi khoảng calo đang hiệu chỉnh (BR-NUT-06)"},
    "kcal_high": {"type": ["number", "null"]},
    "rice_bowls_per_person": {"type": ["number", "null"], "multipleOf": 0.5, "minimum": 0.5, "maximum": 3, "description": "BR-TRAY-03"},
    "reason_vi": {"type": "string", "description": "Dòng lý do"},
    "ranker_version_id": UUIDN, "params_version": {"type": "string"},
    "coeater_allergen_codes": {"type": "array", "items": {"type": "string"}},
    "pinned_lot_ids": {"type": "array", "items": UUID},
    "items": {"type": "array", "items": R("MealPlanItem"), "description": "Gồm cả món swapped_out để hiện lịch sử đổi"},
    "created_at": TS, "updated_at": TS,
}, ["id", "meal", "persons", "max_minutes", "status", "e_target_kcal", "kcal_low", "kcal_high", "rice_bowls_per_person",
    "reason_vi", "ranker_version_id", "params_version", "coeater_allergen_codes", "pinned_lot_ids", "items", "created_at", "updated_at"],
    "Mâm cơm (meal_plans + meal_plan_items + meal_plan_coeater_allergens + meal_plan_pins)")
S["SwapRequest"] = obj({"swap_reason": SWAP_REASON}, ["swap_reason"], "Chỉ khong_hop_gu là nhãn âm về gu (BR-SWAP-01)")
S["SubstituteCandidate"] = obj({
    "substitute_ingredient_id": UUID, "name_vi": {"type": "string"},
    "ratio": {"type": "number", "exclusiveMinimum": 0}, "grams": {"type": "number", "exclusiveMinimum": 0},
    "score": {"type": "number"}, "origin": {"type": "string", "enum": ["lookup", "embedding"]},
    "in_pantry": {"type": "boolean"},
}, ["substitute_ingredient_id", "name_vi", "ratio", "grams", "score", "origin", "in_pantry"])
S["MissingIngredient"] = obj({
    "original_ingredient_id": UUID, "name_vi": {"type": "string"},
    "need_g": {"type": "number"}, "available_g_min": {"type": "number"},
    "candidates": {"type": "array", "maxItems": 3, "items": R("SubstituteCandidate"),
                   "description": "Đã qua lọc cứng dị ứng/chế độ ăn của người dùng và người ăn cùng (BR-ALG-01, BR-DIET-01)"},
}, ["original_ingredient_id", "name_vi", "need_g", "available_g_min", "candidates"])
S["SubstituteList"] = obj({"items": {"type": "array", "items": R("MissingIngredient")}}, ["items"])
S["SubstitutionCreate"] = obj({
    "original_ingredient_id": UUID, "substitute_ingredient_id": UUID,
    "origin": {"type": "string", "enum": ["lookup", "embedding", "user"]},
}, ["original_ingredient_id", "substitute_ingredient_id", "origin"])

# ---- substitute (shopping)
S["ShoppingItem"] = obj({
    "id": UUID, "ingredient_id": UUID, "ingredient_name_vi": {"type": "string"},
    "qty_g": {"type": ["number", "null"], "minimum": 0}, "note": {"type": ["string", "null"]},
    "status": {"type": "string", "enum": ["open", "bought", "dropped"]},
    "source_meal_plan_item_id": UUIDN, "created_at": TS, "updated_at": TS,
}, ["id", "ingredient_id", "ingredient_name_vi", "qty_g", "note", "status", "source_meal_plan_item_id", "created_at", "updated_at"])
S["ShoppingItemCreate"] = obj({
    "ingredient_id": UUID, "qty_g": {"type": ["number", "null"], "minimum": 0},
    "note": {"type": ["string", "null"], "maxLength": 500}, "source_meal_plan_item_id": UUIDN,
}, ["ingredient_id"])
S["ShoppingItemPatch"] = obj({
    "qty_g": {"type": ["number", "null"], "minimum": 0}, "note": {"type": ["string", "null"], "maxLength": 500},
    "status": {"type": "string", "enum": ["open", "bought", "dropped"]},
}, desc="JSON Merge Patch")

# ---- cooking
S["CookSessionStatus"] = {"type": "string", "enum": ["in_progress", "completed", "reverted", "abandoned"]}
S["CookSessionCreate"] = obj({
    "meal_plan_id": UUID,
    "serve_at": {**TS, "description": "Giờ dọn mâm; lịch CP-SAT xếp để mọi món xong trong 5 phút trước giờ này (BR-COOK-01)"},
}, ["meal_plan_id", "serve_at"])
S["ScheduleEntry"] = obj({
    "recipe_id": UUID, "step_no": {"type": "integer"},
    "start_offset_s": {"type": "integer", "minimum": 0}, "end_offset_s": {"type": "integer", "minimum": 1},
    "text_vi": {"type": "string"}, "kind": {"type": "string", "enum": ["active", "passive"]}, "uses_burner": {"type": "boolean"},
}, ["recipe_id", "step_no", "start_offset_s", "end_offset_s", "text_vi", "kind", "uses_burner"], "cook_schedule_entries kèm nội dung bước")
S["CookSession"] = obj({
    "id": UUID, "meal_plan_id": UUID, "status": R("CookSessionStatus"),
    "serve_at": TS, "burners": {"type": "integer", "minimum": 1, "maximum": 4},
    "started_at": TS, "completed_at": TSN, "reverted_at": TSN, "created_at": TS,
    "makespan_s": {"type": "integer", "description": "max(end_offset_s), dẫn xuất"},
    "undo_deadline": {**TSN, "description": "completed_at + 10 phút (BR-PANTRY-02); null khi chưa hoàn tất"},
    "schedule": {"type": "array", "items": R("ScheduleEntry")},
}, ["id", "meal_plan_id", "status", "serve_at", "burners", "started_at", "completed_at", "reverted_at",
    "created_at", "makespan_s", "undo_deadline", "schedule"], "cook_sessions")
S["DishFeedback"] = obj({
    "meal_plan_item_id": UUID,
    "liked": {"type": ["boolean", "null"], "description": "true = thích, false = không thích, null = không đánh giá (BR-COOK-02)"},
}, ["meal_plan_item_id", "liked"])
S["CookCompleteRequest"] = obj({
    "completed_at": {**TS, "description": "Mốc thời gian phía app (outbox có thể gửi muộn); mặc định giờ server"},
    "feedback": {"type": "array", "maxItems": 3, "items": R("DishFeedback")},
})
S["PantryDeduction"] = obj({
    "transaction_id": {"type": "integer", "format": "int64"}, "lot_id": UUID, "ingredient_id": UUID,
    "delta_g_min": {"type": "number", "maximum": 0}, "delta_g_max": {"type": "number", "maximum": 0},
    "urgency_at_event": {"type": ["number", "null"]},
}, ["transaction_id", "lot_id", "ingredient_id", "delta_g_min", "delta_g_max", "urgency_at_event"],
    "pantry_transactions reason = cook_deduct, trừ lô gấp nhất trước (BR-PANTRY-02)")
S["CookCompletion"] = obj({
    "cook_session": R("CookSession"),
    "deductions": {"type": "array", "items": R("PantryDeduction")},
    "interactions_recorded": {"type": "boolean", "description": "false khi chưa đồng ý personalization (BR-CONSENT-03)"},
}, ["cook_session", "deductions", "interactions_recorded"])

# ---- journal
S["JournalDay"] = obj({
    "date": DATE, "cooked_trays": {"type": "integer", "minimum": 0},
    "kcal_per_person": {"type": ["number", "null"]}, "e_target_kcal": {"type": ["number", "null"]},
    "urgent_lots_used": {"type": "integer", "minimum": 0, "description": "Số lô gấp được dùng kịp"},
}, ["date", "cooked_trays", "kcal_per_person", "e_target_kcal", "urgent_lots_used"], "Một dòng v_journal_days")
S["JournalWeek"] = obj({
    "week": {"type": "string", "pattern": "^[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$"},
    "timezone": {"type": "string"},
    "days": {"type": "array", "minItems": 7, "maxItems": 7, "items": R("JournalDay")},
    "kcal_range_status": {"type": "string", "enum": ["calibrated", "calibrating"], "description": "calibrating → app hiện 'đang hiệu chỉnh' (BR-NUT-06)"},
}, ["week", "timezone", "days", "kcal_range_status"])

# ---- events
S["InteractionType"] = {"type": "string", "enum": ["served", "viewed", "swapped", "cooked", "liked", "disliked", "undone"]}
S["InteractionEvent"] = obj({
    "event_id": {**UUID, "description": "Do app sinh (UUIDv7); thành interactions.id → chống trùng"},
    "type": R("InteractionType"), "recipe_id": UUID, "meal_plan_id": UUIDN, "meal_plan_item_id": UUIDN,
    "position": {"type": ["integer", "null"], "minimum": 0},
    "swap_reason": {"type": ["string", "null"], "enum": ["khong_hop_gu", "moi_an", "thieu_thoi_gian", "khac", None]},
    "occurred_at": TS,
}, ["event_id", "type", "recipe_id", "occurred_at"])
S["EventBatch"] = obj({"events": {"type": "array", "minItems": 1, "maxItems": 100, "items": R("InteractionEvent")}}, ["events"])
S["EventBatchResult"] = obj({
    "accepted": {"type": "integer", "minimum": 0},
    "duplicates": {"type": "integer", "minimum": 0, "description": "event_id đã có, bỏ qua"},
    "skipped_no_consent": {"type": "integer", "minimum": 0, "description": "Không ghi vì chưa đồng ý personalization (BR-CONSENT-03)"},
}, ["accepted", "duplicates", "skipped_no_consent"])

# ---- survey
S["SurveyRespondentCreate"] = obj({
    "form_version": {"type": "string", "description": "survey_forms.version; bỏ trống = phiếu đang mở"},
    "policy_version_id": {**UUID, "description": "Phiên bản điều khoản survey hiện hành người tham gia vừa đọc"},
    "consent": {"type": "boolean", "description": "Phải true; false → 422 consent_required (BR-CONSENT-01, FR-23-02)"},
    "channel": {"type": "string", "enum": ["link", "qr"]},
}, ["policy_version_id", "consent", "channel"])
S["SurveyAssignment"] = obj({
    "recipe_id": UUID, "name_vi": {"type": "string"}, "slot": SLOT,
    "display_order": {"type": "integer"}, "is_anchor": {"type": "boolean"},
    "rating": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
    "never_eaten": {"type": ["boolean", "null"], "description": "null = chưa trả lời"},
}, ["recipe_id", "name_vi", "slot", "display_order", "is_anchor", "rating", "never_eaten"],
    "survey_assignments + survey_ratings")
S["SurveyRespondent"] = obj({
    "id": UUID, "form_version": {"type": "string"}, "consented_at": TS, "completed_at": TSN,
    "channel": {"type": "string", "enum": ["link", "qr"]},
    "assignments": {"type": "array", "items": R("SurveyAssignment")},
    "favorite_recipe_ids": {"type": "array", "maxItems": 5, "items": UUID},
}, ["id", "form_version", "consented_at", "completed_at", "channel", "assignments", "favorite_recipe_ids"])
S["SurveyRespondentCreated"] = obj({
    "respondent": R("SurveyRespondent"),
    "respondent_token": {"type": "string", "description": "Gửi lại trong header X-Respondent-Token cho các lời gọi sau; không gắn với tài khoản"},
}, ["respondent", "respondent_token"])
S["SurveyRatingPut"] = obj({
    "rating": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
    "never_eaten": {"type": "boolean"},
}, ["rating", "never_eaten"], "Ràng buộc (rating IS NULL) = never_eaten")
S["SurveyRating"] = obj({
    "recipe_id": UUID, "rating": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
    "never_eaten": {"type": "boolean"}, "answered_at": TS,
}, ["recipe_id", "rating", "never_eaten", "answered_at"])

# ---- admin
S["AdminDataRequest"] = obj({
    "id": UUID, "user_id": UUIDN,
    "subject_ref": {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "HMAC-SHA256 của user_id (hex); còn lại sau khi xoá tài khoản"},
    "type": R("DataRequestType"), "status": R("DataRequestStatus"),
    "received_at": TS, "acknowledged_at": TSN, "completed_at": TSN, "due_at": TS, "note": {"type": ["string", "null"]},
}, ["id", "user_id", "subject_ref", "type", "status", "received_at", "acknowledged_at", "completed_at", "due_at", "note"])
S["DataRequestResolve"] = obj({
    "status": {"type": "string", "enum": ["in_progress", "completed", "rejected"]},
    "note": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "Bắt buộc; nêu việc đã làm hoặc lý do từ chối"},
}, ["status", "note"])
S["AuditLogEntry"] = obj({
    "id": {"type": "integer", "format": "int64"}, "actor_user_id": UUIDN, "actor_role": {"type": "string"},
    "action": {"type": "string"}, "entity": {"type": "string"}, "entity_id": {"type": ["string", "null"]},
    "purpose": {"type": ["string", "null"]}, "request_id": {"type": ["string", "null"]}, "created_at": TS,
}, ["id", "actor_user_id", "actor_role", "action", "entity", "entity_id", "purpose", "request_id", "created_at"], "audit_log (chỉ đọc)")
S["ModelName"] = {"type": "string", "enum": ["detector", "freshness", "ranker", "substitution"]}
S["ModelVersion"] = obj({
    "id": UUID, "name": R("ModelName"), "version": {"type": "string"}, "artifact_key": {"type": "string"},
    "sha256": HEX, "preprocess_version": {"type": ["string", "null"]},
    "metrics": {"type": "object", "additionalProperties": True, "description": "Báo cáo chỉ số, không truy vấn"},
    "gate_report_key": {"type": ["string", "null"]}, "mlflow_run_id": {"type": ["string", "null"]},
    "status": {"type": "string", "enum": ["candidate", "validated", "rejected", "retired"]},
    "is_active": {"type": "boolean", "description": "Dẫn xuất: model_deployments.active_version_id = id"},
    "created_at": TS,
}, ["id", "name", "version", "artifact_key", "sha256", "preprocess_version", "metrics", "gate_report_key",
    "mlflow_run_id", "status", "is_active", "created_at"], "model_versions")
S["ModelDeployment"] = obj({
    "name": R("ModelName"), "active_version_id": UUID, "previous_version_id": UUIDN,
    "switched_at": TS, "switched_by": UUIDN,
}, ["name", "active_version_id", "previous_version_id", "switched_at", "switched_by"], "model_deployments")
S["ModelVersionPage"] = obj({
    "items": {"type": "array", "items": R("ModelVersion")},
    "next_cursor": {"type": ["string", "null"]},
    "deployments": {"type": "array", "items": R("ModelDeployment")},
}, ["items", "next_cursor", "deployments"])
S["SurveyFormSummary"] = obj({
    "id": UUID, "version": {"type": "string"}, "n_anchor": {"type": "integer"}, "n_random": {"type": "integer"},
    "is_open": {"type": "boolean"}, "created_at": TS,
    "respondents_total": {"type": "integer", "minimum": 0}, "respondents_completed": {"type": "integer", "minimum": 0},
}, ["id", "version", "n_anchor", "n_random", "is_open", "created_at", "respondents_total", "respondents_completed"], "survey_forms + đếm survey_respondents")

# ---- core
S["Health"] = obj({"status": {"type": "string", "const": "ok"}}, ["status"])
S["Readiness"] = obj({
    "status": {"type": "string", "enum": ["ready", "not_ready"]},
    "checks": obj({
        "database": {"type": "string", "enum": ["ok", "fail"]},
        "valkey": {"type": "string", "enum": ["ok", "fail"]},
        "models": {"type": "string", "enum": ["ok", "fail"], "description": "Mọi model_deployments đã nạp được artifact khớp sha256"},
    }, ["database", "valkey", "models"]),
}, ["status", "checks"])

for name in ["PantryLot", "Ingredient", "RecipeSummary", "MealPlanSummary", "ShoppingItem", "AdminDataRequest", "AuditLogEntry", "SurveyFormSummary"]:
    S[f"{name}Page"] = page(name)

# ------------------------------------------------------------------ params / responses / headers
P = {
    "IdempotencyKey": {"name": "Idempotency-Key", "in": "header", "required": True,
                       "description": "Khoá do client sinh (UUIDv4/v7) cho mỗi thao tác logic. Server lưu (user_id, key, request_sha256, status_code, response_body) trong idempotency_keys 48 giờ. Gửi lại cùng khoá + cùng thân → trả lại nguyên văn phản hồi đã lưu kèm `Idempotent-Replayed: true`; cùng khoá + thân khác → 422 idempotency_key_reused; yêu cầu đầu còn đang chạy → 409 idempotency_in_progress.",
                       "schema": {"type": "string", "minLength": 16, "maxLength": 64, "pattern": "^[A-Za-z0-9_-]+$"}},
    "AppVersion": {"name": "X-App-Version", "in": "header", "required": False,
                   "description": "Phiên bản app (semver). Thấp hơn bản tối thiểu server còn hỗ trợ → 412 app_too_old. Trình duyệt trang khảo sát không gửi thì bỏ qua kiểm tra.",
                   "schema": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$", "examples": ["1.4.0"]}},
    "Cursor": {"name": "cursor", "in": "query", "required": False, "description": "Con trỏ keyset lấy từ next_cursor của trang trước", "schema": R("PageCursor")},
    "Limit": {"name": "limit", "in": "query", "required": False, "description": "Số phần tử mỗi trang", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
    "Id": {"name": "id", "in": "path", "required": True, "schema": UUID},
    "ItemId": {"name": "itemId", "in": "path", "required": True, "schema": UUID},
    "RecipeId": {"name": "recipeId", "in": "path", "required": True, "schema": UUID},
    "Purpose": {"name": "purpose", "in": "path", "required": True, "schema": R("ConsentPurposeCode")},
    "Ordinal": {"name": "ordinal", "in": "path", "required": True, "schema": {"type": "integer", "minimum": 1, "maximum": 2}},
    "Wait": {"name": "wait", "in": "query", "required": False,
             "description": "Long-poll: giữ kết nối tối đa `wait` giây cho tới khi status rời {queued, processing}; 0 = trả ngay",
             "schema": {"type": "integer", "minimum": 0, "maximum": 10, "default": 0}},
}

H = {
    "Location": {"description": "URL tài nguyên vừa tạo hoặc nơi theo dõi tiến độ", "schema": {"type": "string", "format": "uri-reference"}},
    "RetryAfter": {"description": "Số giây nên chờ trước khi gọi lại", "schema": {"type": "integer", "minimum": 0}},
    "IdempotentReplayed": {"description": "true khi phản hồi là bản lưu của lần gọi trước cùng Idempotency-Key", "schema": {"type": "boolean"}},
    "XAccelRedirect": {"description": "Do nginx xử lý (location internal); client nhận thân tệp, không thấy header này", "schema": {"type": "string"}},
}


RESP_DEF = {
    "BadRequest": ("400: thân hoặc tham số sai cú pháp/kiểu", ["validation_error"], 400, None, "Problem"),
    "Unauthorized": ("401: chưa xác thực, token hết hạn hoặc đã bị thu hồi theo token_version", ["unauthenticated", "token_revoked"], 401, None, "Problem"),
    "Forbidden": ("403: không đủ quyền hoặc thiếu đồng ý", ["forbidden", "consent_required"], 403, None, "Problem"),
    "NotFound": ("404: không có hoặc không thuộc người gọi", ["not_found"], 404, None, "Problem"),
    "Conflict": ("409: xung đột trạng thái", ["conflict_state"], 409, None, "Problem"),
    "AppTooOld": ("412: phiên bản app quá cũ, cần cập nhật", ["app_too_old"], 412, None, "Problem"),
    "PayloadTooLarge": ("413: ảnh quá lớn hoặc quá số lượng", ["image_too_large"], 413, None, "Problem"),
    "Unprocessable": ("422: vi phạm ràng buộc miền không có mã riêng", ["validation_error"], 422, None, "Problem"),
    "TooManyRequests": ("429: vượt giới hạn tần suất", ["rate_limited"], 429, {"Retry-After": {"$ref": "#/components/headers/RetryAfter"}}, "Problem"),
    "ServiceUnavailable": ("503: phụ thuộc chưa sẵn sàng", ["service_unavailable"], 503, {"Retry-After": {"$ref": "#/components/headers/RetryAfter"}}, "Problem"),
}
TITLES = {
    "validation_error": "Dữ liệu không hợp lệ", "unauthenticated": "Chưa đăng nhập hoặc phiên đã hết hạn",
    "token_revoked": "Phiên đã bị thu hồi, cần làm mới", "forbidden": "Không đủ quyền",
    "consent_required": "Cần đồng ý mục đích xử lý dữ liệu", "not_found": "Không tìm thấy",
    "conflict_state": "Trạng thái hiện tại không cho phép thao tác này", "app_too_old": "Phiên bản app quá cũ",
    "image_too_large": "Ảnh quá lớn", "rate_limited": "Gửi quá nhiều yêu cầu",
    "service_unavailable": "Dịch vụ tạm thời chưa sẵn sàng",
}
RESP = {}
for k, (desc, codes, st, hdr, sch) in RESP_DEF.items():
    exs = {c: {"value": {"type": f"https://tastoria.ctslab.net/problems/{c}", "title": TITLES[c], "status": st, "code": c}} for c in codes}
    r = {"description": desc, "content": {"application/problem+json": {"schema": R(sch), "examples": exs}}}
    if hdr:
        r["headers"] = hdr
    RESP[k] = r


def problem_inline(status, desc, codes, schema="Problem", headers=None, details=None):
    """Phản hồi lỗi riêng cho một operation (liệt kê code cụ thể)."""
    r = {"description": desc + " — code: " + ", ".join(f"`{c}`" for c in codes),
         "content": {"application/problem+json": {"schema": R(schema)}}}
    if headers:
        r["headers"] = headers
    return r


def ok(schema=None, desc="Thành công", status=200, headers=None, media="application/json"):
    r = {"description": desc}
    if schema is not None:
        r["content"] = {media: {"schema": R(schema) if isinstance(schema, str) else schema}}
    if headers:
        r["headers"] = headers
    return (str(status), r)


def body(schema, media="application/json", required=True, desc=None):
    b = {"required": required, "content": {media: {"schema": R(schema) if isinstance(schema, str) else schema}}}
    if desc:
        b["description"] = desc
    return b


def qp(name, schema, desc=None, required=False):
    d = {"name": name, "in": "query", "required": required, "schema": schema}
    if desc:
        d["description"] = desc
    return d


PREF = lambda n: {"$ref": f"#/components/parameters/{n}"}
HREF = lambda n: {"$ref": f"#/components/headers/{n}"}
RREF = lambda n: {"$ref": f"#/components/responses/{n}"}

# ------------------------------------------------------------------ operations
# key: (METHOD, path) -> dict(opid, summary, description, params, body, ok: [(status, resp)], errors: {status: resp|refname})
OPS = {}


def op(method, path, opid, summary, desc, params=(), req=None, oks=(), errs=None, paginated=False):
    OPS[(method, path)] = dict(opid=opid, summary=summary, desc=desc, params=list(params), req=req,
                               oks=list(oks), errs=errs or {}, paginated=paginated)


SESSION_OK = ok("AuthSession")
# identity
op("POST", "/auth/register", "identity_register_user", "Đăng ký tài khoản",
   "Tạo users (role = user) và trả phiên đăng nhập ngay. Mật khẩu băm Argon2id. Đồng ý theo mục đích được hỏi ở bước sau (POST /me/consents), không tích sẵn.",
   req=body("RegisterRequest"), oks=[ok("AuthSession", "Đã tạo tài khoản", 201)],
   errs={"409": problem_inline(409, "Email đã có tài khoản", ["email_taken"]), "422": "Unprocessable", "429": "TooManyRequests"})
op("POST", "/auth/login", "identity_login_user", "Đăng nhập",
   "Kiểm mật khẩu, tạo refresh token family mới. Sai 5 lần theo (email, IP) → khoá 15 phút (NFR-SEC-02); trong thời gian khoá trả 429 account_locked kể cả khi mật khẩu đúng.",
   req=body("LoginRequest"), oks=[SESSION_OK],
   errs={"401": problem_inline(401, "Sai thông tin đăng nhập", ["invalid_credentials"]),
         "429": problem_inline(429, "Tài khoản bị khoá tạm hoặc vượt tần suất", ["account_locked", "rate_limited"], headers={"Retry-After": HREF("RetryAfter")})})
op("POST", "/auth/refresh", "identity_refresh_token", "Làm mới phiên",
   "Xoay vòng refresh token: thu hồi token cũ (revoked_at, replaced_by_id), cấp token mới cùng family_id. Dùng lại token đã thu hồi → thu hồi cả family, trả 401 refresh_reused (NFR-SEC-01).",
   req=body("RefreshRequest"), oks=[SESSION_OK],
   errs={"401": problem_inline(401, "Refresh token không dùng được", ["token_reused", "token_invalid"]), "429": "TooManyRequests"})
op("POST", "/auth/logout", "identity_logout_session", "Đăng xuất thiết bị hiện tại",
   "Thu hồi family của refresh token gửi lên. Lũy đẳng: token đã thu hồi vẫn trả 204.",
   req=body("LogoutRequest"), oks=[ok(None, "Đã đăng xuất", 204)])
op("POST", "/auth/logout-all", "identity_logout_all_sessions", "Đăng xuất mọi thiết bị",
   "Thu hồi mọi refresh token của người dùng và tăng users.token_version để vô hiệu mọi access token đang lưu hành. Lũy đẳng.",
   oks=[ok(None, "Đã đăng xuất mọi thiết bị", 204)])
op("POST", "/auth/password-reset/request", "identity_request_password_reset", "Yêu cầu đặt lại mật khẩu",
   "Luôn trả 204 dù email có tồn tại hay không (không lộ tài khoản). Nếu có, tạo password_resets (hạn 30 phút) và gửi thư qua dịch vụ email (A09). Gửi lại trong thời gian token cũ còn hạn không tạo thư mới.",
   req=body("PasswordResetRequest"), oks=[ok(None, "Đã nhận yêu cầu", 204)], errs={"429": "TooManyRequests"})
op("POST", "/auth/password-reset/confirm", "identity_confirm_password_reset", "Đặt mật khẩu mới bằng token trong thư",
   "Đặt password_hash mới, ghi used_at, thu hồi mọi refresh token và tăng token_version. Token sai, đã dùng hoặc hết hạn → 400 reset_token_invalid; mật khẩu mới không đạt chính sách → 422 weak_password (token chưa bị tiêu).",
   req=body("PasswordResetConfirm"), oks=[ok(None, "Đã đổi mật khẩu", 204)],
   errs={"400": problem_inline(400, "Token sai, đã dùng hoặc hết hạn; hoặc thân sai", ["token_invalid", "validation_failed"]), "422": "Unprocessable", "429": "TooManyRequests"})
# privacy
op("GET", "/policies/{purpose}/current", "privacy_get_current_policy", "Lấy điều khoản hiện hành của một mục đích",
   "Trả phiên bản policy_versions có effective_from mới nhất ≤ hiện tại. Dùng ở màn đồng ý khi thiết lập hồ sơ (UC09), cài đặt (UC05) và trang khảo sát (UC23).",
   params=[PREF("Purpose")], oks=[ok("PolicyVersion")])
op("GET", "/me/consents", "privacy_list_consents", "Xem trạng thái đồng ý theo từng mục đích",
   "Một dòng cho mỗi mục đích trong consent_purposes, kể cả mục đích chưa từng quyết định (state = none).",
   oks=[ok("ConsentList")])
op("POST", "/me/consents", "privacy_record_consents", "Ghi quyết định đồng ý / không đồng ý",
   "Ghi thêm consent_events cho từng quyết định. Lũy đẳng: quyết định trùng trạng thái hiện hành không tạo sự kiện mới. policy_version_id phải là bản hiện hành của mục đích. Rút đồng ý qua đây có cùng hiệu lực như /withdraw (BR-CONSENT-04).",
   req=body("ConsentDecisionBatch"), oks=[ok("ConsentList", "Trạng thái đồng ý sau khi ghi")],
   errs={"409": problem_inline(409, "policy_version_id không còn là bản hiện hành", ["conflict_state"]), "422": "Unprocessable"})
op("POST", "/me/consents/{purpose}/withdraw", "privacy_withdraw_consent", "Rút đồng ý một mục đích",
   "Ghi consent_events action = withdraw, tăng users.token_version (access token cũ hết hiệu lực ngay, app gọi /auth/refresh), xếp lịch xoá dữ liệu của mục đích trong ≤ 24 giờ (BR-CONSENT-04). Lũy đẳng.",
   params=[PREF("Purpose")], req=body("ConsentWithdrawRequest", required=False), oks=[ok("ConsentState")])
op("POST", "/me/data-requests", "privacy_create_data_request", "Gửi yêu cầu của chủ thể dữ liệu",
   "Ghi dsr_requests (status = received) và đẩy job xử lý. access/export/delete/withdraw tự hoàn tất ≤ 24 giờ; correct/restrict/object chờ quản trị viên (UC08, UC27). type = delete chuyển users.status = deletion_requested. Lũy đẳng: còn yêu cầu cùng type chưa xong thì trả lại yêu cầu đó với 200.",
   req=body("DataRequestCreate"),
   oks=[ok("DataRequest", "Đã nhận, đang xử lý bất đồng bộ", 202, {"Location": HREF("Location"), "Retry-After": HREF("RetryAfter")}),
        ok("DataRequest", "Đã có yêu cầu cùng loại đang mở; trả lại yêu cầu đó", 200, {"Location": HREF("Location")})],
   errs={"422": "Unprocessable", "429": "TooManyRequests"})
op("GET", "/me/data-requests/{id}", "privacy_get_data_request", "Theo dõi yêu cầu dữ liệu",
   "Chỉ trả yêu cầu của chính người gọi (lọc user_id).", params=[PREF("Id")],
   oks=[ok("DataRequest", headers={"Retry-After": {**HREF("RetryAfter")}})])
op("GET", "/me/data-requests/{id}/download", "privacy_download_data_export", "Tải tệp dữ liệu cá nhân",
   "API kiểm quyền rồi trả X-Accel-Redirect tới tệp ZIP (JSON + ảnh còn lưu). Chỉ khi type = export và status = completed. Chưa completed → 409 request_not_ready; không phải export → 409 request_not_downloadable; tệp đã dọn → 410 export_expired.",
   params=[PREF("Id")],
   oks=[ok({"type": "string", "contentMediaType": "application/zip"}, "Tệp ZIP", 200, {"X-Accel-Redirect": HREF("XAccelRedirect")}, media="application/zip")],
   errs={"409": "Conflict"})
# profile
op("GET", "/me/profile", "profile_get_profile", "Xem hồ sơ", "Giải mã cột *_enc (ghi audit_log). Chưa đồng ý health_profile thì các chỉ số là null.",
   oks=[ok("Profile")])
op("PUT", "/me/profile", "profile_update_profile", "Lưu chỉ số cơ thể và mục tiêu",
   "Mã hoá AES-GCM ở tầng ứng dụng rồi lưu profiles (enc_key_id). Chỉ số khác null khi chưa đồng ý health_profile → 403 consent_required (BR-CONSENT-02). Tuổi < 18 → 422 age_below_minimum (BR-NUT-01).",
   req=body("ProfileUpdate"), oks=[ok("Profile")],
   errs={"403": problem_inline(403, "Chưa đồng ý health_profile", ["consent_required"]), "422": "Unprocessable"})
op("POST", "/me/energy-suggestion", "profile_suggest_energy", "Tính gợi ý năng lượng",
   "Tính BMR (FAO/WHO/UNU 1985 mặc định), TEE = BMR × PAL, áp giảm 500 kcal và mức sàn nếu goal = lose; không lưu. Lũy đẳng (thuần tính toán).",
   req=body("EnergySuggestionRequest", required=False), oks=[ok("EnergySuggestion")],
   errs={"403": problem_inline(403, "Chưa đồng ý health_profile", ["consent_required"]),
         "422": problem_inline(422, "Hồ sơ thiếu chỉ số cần cho công thức", ["validation_failed"])})
op("PUT", "/me/energy-target", "profile_set_energy_target", "Đặt mục tiêu năng lượng",
   "Lưu profiles.kcal_target và kcal_source (gợi ý / tự nhập / chuyên gia). Cần đồng ý health_profile.",
   req=body("EnergyTarget"), oks=[ok("EnergyTarget")],
   errs={"403": problem_inline(403, "Chưa đồng ý health_profile", ["consent_required"]), "422": "Unprocessable"})
op("PUT", "/me/allergens", "profile_set_allergens", "Đặt nhóm dị ứng",
   "Thay toàn bộ user_allergens. Mã phải có trong allergen_groups (BR-ALG-02).",
   req=body("AllergenSet"), oks=[ok("AllergenSet")], errs={"422": "Unprocessable"})
op("PUT", "/me/diet", "profile_set_diet", "Đặt chế độ ăn", "Lưu profiles.diet_code (BR-DIET-01).",
   req=body("DietSelection"), oks=[ok("DietSelection")], errs={"422": "Unprocessable"})
op("PUT", "/me/favorites", "profile_set_favorites", "Đặt 5 món hay ăn",
   "Thay toàn bộ user_favorite_recipes; tối đa 5 món published. Dùng cho xếp hạng content-based khi chưa đồng ý personalization (BR-CONSENT-03).",
   req=body("FavoriteSet"), oks=[ok("FavoriteSet")], errs={"422": "Unprocessable"})
op("GET", "/me/settings", "profile_get_settings", "Xem cài đặt bếp", "Bảng user_settings; chưa có thì trả giá trị mặc định.",
   oks=[ok("UserSettings")])
op("PUT", "/me/settings", "profile_update_settings", "Lưu cài đặt bếp", "Số họng bếp, số người mặc định, múi giờ.",
   req=body("UserSettings"), oks=[ok("UserSettings")], errs={"422": "Unprocessable"})
# catalog
op("GET", "/reference", "catalog_get_reference", "Lấy dữ liệu tham chiếu",
   "Danh mục dị ứng, chế độ ăn, nhóm thực phẩm, cách nấu, thẻ, chất dinh dưỡng, mức lượng, mục đích đồng ý. Công khai; có ETag, gửi If-None-Match nhận 304.",
   params=[{"name": "If-None-Match", "in": "header", "required": False, "schema": {"type": "string"}}],
   oks=[ok("ReferenceData", headers={"ETag": {"schema": {"type": "string"}}}), ("304", {"description": "Không đổi so với ETag client giữ"})])
op("GET", "/recipes", "catalog_list_recipes", "Tìm món",
   "Chỉ món published. Dùng khi chọn 5 món hay ăn (UC09) và duyệt món (UC15).",
   params=[qp("q", {"type": "string", "maxLength": 100}, "Tìm theo tên (không dấu cũng khớp)"), qp("slot", SLOT),
           qp("tag", {"type": "string"}, "Mã thẻ")],
   oks=[ok("RecipeSummaryPage")], paginated=True)
op("GET", "/recipes/{id}", "catalog_get_recipe", "Xem chi tiết món",
   "Gồm nguyên liệu (gam lúc mua cho servings khẩu phần), bước, nguồn, dinh dưỡng. Món retired vẫn đọc được để mâm/phiên nấu cũ hiển thị đúng (BR-CATALOG-01).",
   params=[PREF("Id")], oks=[ok("Recipe")])
op("GET", "/ingredients", "catalog_list_ingredients", "Tìm nguyên liệu",
   "Tìm theo tên hoặc từ đồng nghĩa; chỉ is_active = true. Dùng khi sửa chip quét, thêm lô, thêm đồ đi chợ.",
   params=[qp("q", {"type": "string", "maxLength": 100}), qp("food_group_code", {"type": "string"})],
   oks=[ok("IngredientPage")], paginated=True)
op("GET", "/catalog/snapshot", "catalog_get_snapshot", "Tải ảnh chụp kho món cho chế độ offline",
   "Toàn bộ món published + nguyên liệu; app lưu SQLite để nấu khi mất mạng. ETag theo data_version.",
   params=[{"name": "If-None-Match", "in": "header", "required": False, "schema": {"type": "string"}}],
   oks=[ok("CatalogSnapshot", headers={"ETag": {"schema": {"type": "string"}}}), ("304", {"description": "Không đổi"})])
# pantry
op("GET", "/pantry/lots", "pantry_list_lots", "Xem kho theo lô",
   "Lượng hiện tại lấy từ v_pantry_lot_balance; độ gấp u và nhãn tính lúc đọc (BR-FRESH-05). Sắp theo u giảm dần khi sort = urgency.",
   params=[qp("status", {"type": "array", "items": R("LotStatus"), "default": ["in_stock", "not_seen"]}, "Lọc trạng thái (lặp tham số)"),
           qp("sort", {"type": "string", "enum": ["urgency", "created_at"], "default": "urgency"})],
   oks=[ok("PantryLotPage")], paginated=True)
op("POST", "/pantry/lots", "pantry_create_lot", "Thêm lô bằng tay",
   "Tạo pantry_lots mới và giao dịch reason = manual_edit. Không lũy đẳng: mỗi lần gọi là một lô mới (BR-PANTRY-01).",
   req=body("PantryLotCreate"), oks=[ok("PantryLot", "Đã tạo lô", 201, {"Location": HREF("Location")})], errs={"422": "Unprocessable"})
op("PATCH", "/pantry/lots/{id}", "pantry_update_lot", "Sửa lượng, ngày mua hoặc xác nhận lô",
   "Sửa lượng ghi giao dịch manual_edit theo phần chênh (kho chỉ ghi thêm); đặt lại ngày mua; xác nhận đồ 'kiểm tra' vẫn dùng được; đưa lô not_seen về in_stock.",
   params=[PREF("Id")], req=body("PantryLotPatch", media="application/merge-patch+json"), oks=[ok("PantryLot")],
   errs={"409": "Conflict", "422": "Unprocessable"})
op("POST", "/pantry/lots/{id}/discard", "pantry_discard_lot", "Bỏ lô",
   "Chuyển status = discarded và ghi giao dịch discard đưa lượng về 0. Lũy đẳng: lô đã discarded trả 200 nguyên trạng.",
   params=[PREF("Id")], oks=[ok("PantryLot")], errs={"409": "Conflict"})
# scan
op("POST", "/scans", "scan_create_scan", "Gửi ảnh để quét nguyên liệu",
   "Nhận 1–2 ảnh, lưu tmp/, tạo scans (queued) và đẩy job suy luận. Trả 202 ngay; theo dõi bằng GET /scans/{id}?wait=10. Ảnh gốc xoá sau 30 ngày trừ khi contribute = true và đã đồng ý photo_contribution (BR-RETAIN-01).",
   req={**body("ScanCreate", media="multipart/form-data"),
        "content": {"multipart/form-data": {"schema": R("ScanCreate"), "encoding": {"images": {"contentType": "image/jpeg"}}}}},
   oks=[ok("ScanAccepted", "Đã xếp hàng", 202, {"Location": HREF("Location"), "Retry-After": HREF("RetryAfter")})],
   errs={"403": problem_inline(403, "contribute = true nhưng chưa đồng ý photo_contribution", ["consent_required"]),
         "413": "PayloadTooLarge",
         "422": problem_inline(422, "Ảnh không đọc được, sai ràng buộc, hoặc Idempotency-Key bị dùng lại với thân khác", ["image_invalid", "validation_failed", "idempotency_key_reused"]),
         "429": "TooManyRequests", "503": "ServiceUnavailable"})
op("GET", "/scans/{id}", "scan_get_scan", "Xem trạng thái và kết quả quét",
   "Long-poll với ?wait (tối đa 10 s). Khi status ∈ {queued, processing} phản hồi có Retry-After: 1. status = failed kèm error_code; job quá 30 s được thử lại tối đa 2 lần rồi expired.",
   params=[PREF("Id"), PREF("Wait")], oks=[ok("Scan", headers={"Retry-After": HREF("RetryAfter")})])
op("GET", "/scans/{id}/images/{ordinal}", "scan_get_image", "Tải ảnh của lần quét",
   "Kiểm quyền rồi trả X-Accel-Redirect. Ảnh đã xoá theo hạn giữ (purged_at khác null) → 404 not_found.",
   params=[PREF("Id"), PREF("Ordinal")],
   oks=[ok({"type": "string", "contentMediaType": "image/jpeg"}, "Ảnh JPEG đã bỏ metadata", 200, {"X-Accel-Redirect": HREF("XAccelRedirect")}, media="image/jpeg")])
SCAN409 = problem_inline(409, "Lần quét chưa xong hoặc đã chốt", ["scan_not_ready", "conflict_state"])
op("POST", "/scans/{id}/items", "scan_add_item", "Thêm chip nguyên liệu bị sót",
   "Tạo scan_items origin = user_added. Chỉ khi status = done. Không ghi kho.",
   params=[PREF("Id")], req=body("ScanItemCreate"), oks=[ok("ScanItem", "Đã thêm chip", 201, {"Location": HREF("Location")})],
   errs={"409": SCAN409, "422": "Unprocessable"})
op("PATCH", "/scans/{id}/items/{itemId}", "scan_update_item", "Sửa chip (đổi nhãn, số lượng, độ tươi)",
   "Đổi ingredient_id → user_action = relabeled và lưu original_ingredient_id; sửa số/lượng/độ tươi → edited. Chỉ khi status = done.",
   params=[PREF("Id"), PREF("ItemId")], req=body("ScanItemPatch", media="application/merge-patch+json"), oks=[ok("ScanItem")],
   errs={"409": SCAN409, "422": "Unprocessable"})
op("DELETE", "/scans/{id}/items/{itemId}", "scan_delete_item", "Xoá chip nhận nhầm",
   "Đặt user_action = deleted (giữ lại làm tín hiệu chọn ảnh cho học chủ động). Lũy đẳng.",
   params=[PREF("Id"), PREF("ItemId")], oks=[ok(None, "Đã xoá chip", 204)], errs={"409": SCAN409})
op("POST", "/scans/{id}/confirm", "scan_confirm_scan", "Xác nhận kết quả quét vào kho",
   "Một Unit of Work: tạo pantry_lots + giao dịch scan_add cho mỗi chip còn lại, đánh dấu lô not_seen (fridge), status = confirmed (BR-SCAN-02, BR-PANTRY-01, BR-PANTRY-03). Còn chip needs_check = true chưa xác nhận → 409 freshness_check_required (BR-FRESH-04); chip không đếm được chưa có mức → 422 qty_level_required. Lũy đẳng: gọi lại khi đã confirmed trả kết quả cũ.",
   params=[PREF("Id")], req=body("ScanConfirmRequest", required=False), oks=[ok("ScanConfirmResult")],
   errs={"409": problem_inline(409, "status khác done/confirmed", ["scan_not_ready", "conflict_state"]),
         "422": problem_inline(422, "Còn chip 'kiểm tra' chưa xác nhận", ["validation_failed"])})
op("POST", "/scans/{id}/discard", "scan_discard_scan", "Bỏ lần quét",
   "status = discarded, không ghi kho. Không áp dụng cho lần quét đã confirmed. Lũy đẳng.",
   params=[PREF("Id")], oks=[ok("Scan")], errs={"409": "Conflict"})
# meal
op("POST", "/meal-plans", "meal_create_plan", "Ghép mâm cơm",
   "Lọc cứng dị ứng/chế độ ăn (BR-ALG-01, BR-DIET-01), xếp hạng gu, ghép mâm theo khả thi kho và thời gian (BR-TRAY-01..08). Không có mâm khả thi → 422 no_feasible_tray kèm 3 mâm tốt nhất và đồ còn thiếu (BR-TRAY-06); không mâm nào dùng đủ lô ghim → 422 pin_unsatisfiable (BR-TRAY-08). Ghi interactions served nếu đã đồng ý personalization.",
   req=body("MealPlanCreate"), oks=[ok("MealPlan", "Đã tạo mâm", 201, {"Location": HREF("Location")})],
   errs={"422": problem_inline(422, "Không ghép được mâm, thân sai, hoặc Idempotency-Key bị dùng lại với thân khác",
                               ["infeasible_tray", "validation_failed", "idempotency_key_reused"], schema="InfeasibleTrayProblem"),
         "429": "TooManyRequests", "503": "ServiceUnavailable"})
op("GET", "/meal-plans", "meal_list_plans", "Liệt kê mâm đã tạo",
   "Lọc theo trạng thái và khoảng ngày (múi giờ người dùng). Dùng cho nhật ký tuần.",
   params=[qp("status", {"type": "array", "items": R("MealPlanStatus")}), qp("from", DATE), qp("to", DATE)],
   oks=[ok("MealPlanSummaryPage")], paginated=True)
op("GET", "/meal-plans/latest", "meal_get_latest_plan", "Lấy mâm gần nhất còn dùng được",
   "Mâm mới nhất có status ∈ {proposed, accepted} của bữa chỉ định trong ngày hiện tại; không có → 404.",
   params=[qp("meal", R("MealType"))], oks=[ok("MealPlan")], errs={"404": "NotFound"})
op("GET", "/meal-plans/{id}", "meal_get_plan", "Xem mâm", "Gồm món active và món đã đổi ra.",
   params=[PREF("Id")], oks=[ok("MealPlan")])
op("POST", "/meal-plans/{id}/accept", "meal_accept_plan", "Nhận mâm",
   "proposed → accepted. Lũy đẳng: đã accepted trả 200. Từ trạng thái khác → 409 conflict_state.",
   params=[PREF("Id")], oks=[ok("MealPlan")], errs={"409": "Conflict"})
op("POST", "/meal-plans/{id}/items/{itemId}/swap", "meal_swap_item", "Đổi một món",
   "Giải lại với các slot còn lại cố định, loại các món đã đổi ra khỏi mâm này (BR-SWAP-01). Món cũ → swapped_out kèm swap_reason; món mới trỏ replaced_item_id. Ghi interactions swapped nếu có đồng ý.",
   params=[PREF("Id"), PREF("ItemId")], req=body("SwapRequest"), oks=[ok("MealPlan", "Mâm sau khi đổi")],
   errs={"409": problem_inline(409, "Mâm không ở proposed/accepted hoặc món đã bị đổi", ["conflict_state", "idempotency_in_progress"]),
         "422": problem_inline(422, "Không còn món thay khả thi hoặc Idempotency-Key bị dùng lại", ["infeasible_tray", "validation_failed", "idempotency_key_reused"], schema="InfeasibleTrayProblem")})
op("GET", "/meal-plans/{id}/items/{itemId}/substitutes", "meal_list_substitutes", "Xem nguyên liệu thiếu và gợi ý thay thế",
   "Màn 'Thiếu gì?': với mỗi nguyên liệu thiếu, tối đa 3 gợi ý đã qua lọc cứng (cùng nhóm thực phẩm, dị ứng, chế độ ăn của người dùng và người ăn cùng).",
   params=[PREF("Id"), PREF("ItemId")], oks=[ok("SubstituteList")])
op("POST", "/meal-plans/{id}/items/{itemId}/substitutions", "meal_apply_substitution", "Chọn đồ thay thế",
   "Ghi (hoặc ghi đè) meal_plan_item_substitutions theo khoá (item_id, original_ingredient_id) rồi tính lại kcal_per_person. Đồ thay thế vi phạm dị ứng/chế độ ăn → 422 validation_failed. Lũy đẳng.",
   params=[PREF("Id"), PREF("ItemId")], req=body("SubstitutionCreate"), oks=[ok("MealPlanItem")],
   errs={"409": "Conflict", "422": "Unprocessable"})
# shopping
op("GET", "/shopping-items", "substitute_list_shopping_items", "Xem danh sách đi chợ", "Mặc định chỉ status = open.",
   params=[qp("status", {"type": "array", "items": {"type": "string", "enum": ["open", "bought", "dropped"]}, "default": ["open"]})],
   oks=[ok("ShoppingItemPage")], paginated=True)
op("POST", "/shopping-items", "substitute_create_shopping_item", "Thêm đồ cần mua",
   "Từ 'Thiếu gì?' (UC17), từ danh sách đồ thiếu khi không có mâm khả thi (BR-TRAY-06) hoặc nhập tay. Không lũy đẳng.",
   req=body("ShoppingItemCreate"), oks=[ok("ShoppingItem", "Đã thêm", 201, {"Location": HREF("Location")})], errs={"422": "Unprocessable"})
op("PATCH", "/shopping-items/{id}", "substitute_update_shopping_item", "Sửa hoặc đánh dấu đồ đi chợ",
   "Đổi lượng, ghi chú, trạng thái (đã mua / bỏ). Đánh dấu bought không tự thêm vào kho; app gợi ý quét 'đồ vừa mua'.",
   params=[PREF("Id")], req=body("ShoppingItemPatch", media="application/merge-patch+json"), oks=[ok("ShoppingItem")],
   errs={"422": "Unprocessable"})
# cooking
op("POST", "/cook-sessions", "cooking_create_session", "Bắt đầu nấu cả mâm",
   "Mâm phải ở accepted. Lập lịch CP-SAT (BR-COOK-01) với user_settings.burners, lưu cook_schedule_entries. Ghi interactions cooked khi hoàn tất, không phải lúc này.",
   req=body("CookSessionCreate"), oks=[ok("CookSession", "Đã tạo phiên nấu", 201, {"Location": HREF("Location")})],
   errs={"409": problem_inline(409, "Mâm không ở accepted, đã có phiên đang nấu, hoặc yêu cầu cùng khoá đang chạy", ["conflict_state", "idempotency_in_progress"]),
         "422": problem_inline(422, "Thân sai hoặc Idempotency-Key bị dùng lại", ["validation_failed", "idempotency_key_reused"])})
op("GET", "/cook-sessions/{id}", "cooking_get_session", "Xem phiên nấu và lịch bước", "", params=[PREF("Id")], oks=[ok("CookSession")])
op("POST", "/cook-sessions/{id}/complete", "cooking_complete_session", "Nấu xong một chạm",
   "Một Unit of Work: trừ kho theo lô gấp nhất trước (BR-PANTRY-02), ghi interactions cooked/liked/disliked nếu đã đồng ý personalization (BR-CONSENT-03), cook_sessions → completed, meal_plans → cooked (BR-COOK-02). Lũy đẳng theo Idempotency-Key; outbox của app gửi lại an toàn.",
   params=[PREF("Id")], req=body("CookCompleteRequest", required=False), oks=[ok("CookCompletion")],
   errs={"409": problem_inline(409, "Phiên không ở in_progress hoặc yêu cầu cùng khoá đang chạy", ["conflict_state", "idempotency_in_progress"]),
         "422": problem_inline(422, "Thân sai hoặc Idempotency-Key bị dùng lại", ["validation_failed", "idempotency_key_reused"])})
op("POST", "/cook-sessions/{id}/undo", "cooking_undo_session", "Hoàn tác trừ kho",
   "Trong 10 phút sau completed_at: ghi giao dịch đảo (reason = undo, reverses_id), interactions undone, cook_sessions → reverted, meal_plans → accepted. Quá hạn → 409 undo_window_closed. Lũy đẳng: đã reverted trả 200.",
   params=[PREF("Id")], oks=[ok("CookSession")],
   errs={"409": problem_inline(409, "Hết cửa sổ hoàn tác hoặc trạng thái không cho phép", ["undo_window_closed", "conflict_state"])})
op("POST", "/cook-sessions/{id}/abandon", "cooking_abandon_session", "Bỏ phiên nấu",
   "in_progress → abandoned, không trừ kho; mâm giữ accepted để nấu lại. Lũy đẳng.",
   params=[PREF("Id")], oks=[ok("CookSession")], errs={"409": "Conflict"})
# journal
op("GET", "/journal", "journal_get_week", "Xem nhật ký tuần",
   "Đọc v_journal_days theo tuần ISO 8601 và múi giờ trong user_settings. Calo hiện dạng khoảng hoặc 'đang hiệu chỉnh' (BR-NUT-06).",
   params=[qp("week", {"type": "string", "pattern": "^[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$"}, "Tuần ISO, ví dụ 2026-W42; mặc định tuần hiện tại")],
   oks=[ok("JournalWeek")], errs={"422": "Unprocessable"})
# events
op("POST", "/events", "events_record_events", "Gửi lô sự kiện tương tác",
   "Chống trùng theo event_id (interactions.id): gửi lại cùng event_id không tạo bản ghi mới. Chưa đồng ý personalization thì không ghi, chỉ đếm skipped_no_consent (BR-CONSENT-03). meal_plan_id phải thuộc người gọi (FK ghép).",
   req=body("EventBatch"), oks=[ok("EventBatchResult")], errs={"422": "Unprocessable", "429": "TooManyRequests"})
# survey
op("POST", "/survey/respondents", "survey_create_respondent", "Bắt đầu tham gia khảo sát",
   "Tạo survey_respondents gắn policy_version_id đã đồng ý, sinh phiếu khối không đầy đủ (món neo + món ngẫu nhiên phân tầng) vào survey_assignments, cấp respondent_token. Không cần tài khoản. Không lũy đẳng: mỗi lần là một người tham gia mới.",
   req=body("SurveyRespondentCreate"),
   oks=[ok("SurveyRespondentCreated", "Đã tạo người tham gia", 201, {"Location": HREF("Location")})],
   errs={"403": problem_inline(403, "consent = false", ["consent_required"]),
         "409": problem_inline(409, "Không có phiếu đang mở hoặc policy_version_id không còn hiện hành", ["conflict_state"]),
         "422": "Unprocessable", "429": "TooManyRequests"})
op("GET", "/survey/respondents/{id}", "survey_get_respondent", "Xem phiếu khảo sát của mình",
   "Token trong X-Respondent-Token phải khớp id.", params=[PREF("Id")], oks=[ok("SurveyRespondent")])
op("PUT", "/survey/respondents/{id}/ratings/{recipeId}", "survey_put_rating", "Chấm điểm một món",
   "Ghi đè survey_ratings của (respondent, recipe). recipeId phải nằm trong survey_assignments. Phiếu đã hoàn tất → 409.",
   params=[PREF("Id"), PREF("RecipeId")], req=body("SurveyRatingPut"), oks=[ok("SurveyRating")],
   errs={"409": "Conflict", "422": "Unprocessable"})
op("PUT", "/survey/respondents/{id}/favorites", "survey_set_favorites", "Chọn 5 món hay ăn",
   "Thay toàn bộ survey_favorites; tối đa 5 món.",
   params=[PREF("Id")], req=body("FavoriteSet"), oks=[ok("FavoriteSet")], errs={"409": "Conflict", "422": "Unprocessable"})
op("POST", "/survey/respondents/{id}/complete", "survey_complete_respondent", "Nộp phiếu khảo sát",
   "Đặt completed_at. Còn món chưa trả lời → 422 survey_incomplete kèm danh sách recipeId. Lũy đẳng.",
   params=[PREF("Id")], oks=[ok("SurveyRespondent")], errs={"422": "Unprocessable"})
# admin
op("GET", "/admin/data-requests", "admin_list_data_requests", "Liệt kê yêu cầu dữ liệu",
   "Mỗi lần đọc ghi audit_log. Sắp received_at tăng dần để xử lý theo hạn.",
   params=[qp("status", {"type": "array", "items": R("DataRequestStatus")}), qp("type", {"type": "array", "items": R("DataRequestType")})],
   oks=[ok("AdminDataRequestPage")], paginated=True)
op("POST", "/admin/data-requests/{id}/resolve", "admin_resolve_data_request", "Xử lý yêu cầu dữ liệu thủ công",
   "Dùng cho correct/restrict/object (UC08). Đặt status, acknowledged_at/completed_at, note; ghi audit_log. Lũy đẳng: cùng status đã đặt trả 200. Yêu cầu đã completed/rejected không đổi được → 409.",
   params=[PREF("Id")], req=body("DataRequestResolve"), oks=[ok("AdminDataRequest")],
   errs={"409": "Conflict", "422": "Unprocessable"})
op("GET", "/admin/audit-log", "admin_list_audit_log", "Xem nhật ký kiểm toán",
   "Chỉ đọc; keyset theo (created_at, id) giảm dần.",
   params=[qp("actor_user_id", UUID), qp("entity", {"type": "string"}), qp("action", {"type": "string"}),
           qp("from", TS), qp("to", TS)],
   oks=[ok("AuditLogEntryPage")], paginated=True)
op("GET", "/admin/models", "admin_list_models", "Xem phiên bản mô hình và bản đang chạy",
   "Đăng ký, kiểm định, triển khai, quay lui thực hiện qua CLI `tastoria mlops ...`; endpoint này chỉ đọc.",
   params=[qp("name", R("ModelName")), qp("status", {"type": "string", "enum": ["candidate", "validated", "rejected", "retired"]})],
   oks=[ok("ModelVersionPage")], paginated=True)
op("GET", "/admin/surveys", "admin_list_surveys", "Xem các đợt khảo sát",
   "Tạo phiếu và xuất kết quả qua CLI `tastoria survey ...`; endpoint này chỉ đọc số liệu tiến độ.",
   oks=[ok("SurveyFormSummaryPage")], paginated=True)
# core
op("GET", "/healthz", "core_get_health", "Kiểm tra tiến trình còn sống", "Không chạm CSDL. Nằm ở gốc, không có tiền tố /api/v1.",
   oks=[ok("Health")])
op("GET", "/readyz", "core_get_readiness", "Kiểm tra sẵn sàng nhận tải", "Kiểm CSDL, Valkey và mô hình đã nạp. Nằm ở gốc, không có tiền tố /api/v1.",
   oks=[ok("Readiness")], errs={"503": {"description": "Chưa sẵn sàng", "headers": {"Retry-After": HREF("RetryAfter")},
                                        "content": {"application/json": {"schema": R("Readiness")}}}})

# ------------------------------------------------------------------ strict request bodies
for d in OPS.values():
    if d["req"]:
        for media in d["req"]["content"].values():
            ref = media["schema"].get("$ref", "")
            name = ref.rsplit("/", 1)[-1]
            if name in S and S[name].get("type") == "object":
                S[name]["additionalProperties"] = False


RA = {"Retry-After": HREF("RetryAfter")}
IDEM409 = ["idempotency_in_progress"]
IDEM422 = ["idempotency_key_reused"]


def pi(st, desc, codes, **kw):
    return problem_inline(st, desc, codes, **kw)


ERR_OVERRIDES = {
    ("POST", "/auth/register"): {
        "409": pi(409, "Email đã có tài khoản", ["email_taken"]),
        "422": pi(422, "Email sai cú pháp, mật khẩu yếu hoặc thân sai", ["invalid_email", "weak_password", "validation_error"])},
    ("POST", "/auth/login"): {
        "401": pi(401, "Sai thông tin đăng nhập", ["invalid_credentials"]),
        "403": pi(403, "Tài khoản đang chờ xoá", ["account_deletion_pending"]),
        "429": pi(429, "Cặp (email, IP) bị khoá tạm hoặc vượt tần suất", ["login_locked", "rate_limited"], headers=RA),
        "503": pi(503, "Valkey hoặc CSDL chưa sẵn sàng", ["service_unavailable"], headers=RA)},
    ("POST", "/auth/refresh"): {
        "401": pi(401, "Refresh token không dùng được", ["refresh_invalid", "refresh_reused"]),
        "403": pi(403, "Tài khoản đang chờ xoá", ["account_deletion_pending"])},
    ("POST", "/auth/password-reset/confirm"): {
        "400": pi(400, "Token sai, đã dùng hoặc hết hạn; hoặc thân sai", ["reset_token_invalid", "validation_error"]),
        "422": pi(422, "Mật khẩu mới không đạt chính sách (token chưa bị tiêu)", ["weak_password"])},
    ("GET", "/policies/{purpose}/current"): {
        "404": pi(404, "Mục đích không tồn tại", ["purpose_not_found"])},
    ("POST", "/me/consents"): {
        "409": pi(409, "policy_version_id không còn là bản hiện hành", ["policy_outdated"]),
        "422": pi(422, "Mục đích không ghi được ở đây (survey) hoặc mã lạ; thân sai", ["purpose_not_allowed", "validation_error"])},
    ("POST", "/me/consents/{purpose}/withdraw"): {
        "404": pi(404, "Mục đích không tồn tại", ["purpose_not_found"])},
    ("POST", "/me/data-requests"): {
        "403": pi(403, "Mật khẩu xác nhận sai khi yêu cầu xoá", ["reauth_failed"]),
        "422": pi(422, "Loại yêu cầu sai hoặc thiếu ghi chú", ["invalid_request", "validation_error"])},
    ("GET", "/me/data-requests/{id}/download"): {
        "409": pi(409, "Yêu cầu chưa completed hoặc không phải export", ["request_not_ready", "request_not_downloadable"]),
        "410": pi(410, "Tệp xuất đã bị dọn", ["export_expired"])},
    ("GET", "/me/profile"): {
        "500": pi(500, "Không giải mã được cột sức khoẻ", ["decryption_failed"])},
    ("PUT", "/me/profile"): {
        "403": pi(403, "Chưa đồng ý health_profile", ["consent_required"]),
        "422": pi(422, "Tuổi < 18, tuổi 18 theo năm sinh chưa xác nhận, hoặc giá trị ngoài miền", ["age_below_minimum", "age_confirmation_required", "validation_error"])},
    ("POST", "/me/energy-suggestion"): {
        "403": pi(403, "Chưa đồng ý health_profile", ["consent_required"]),
        "422": pi(422, "Hồ sơ thiếu chỉ số cần cho công thức hoặc tuổi < 18", ["profile_incomplete", "age_below_minimum"]),
        "500": pi(500, "Không giải mã được cột sức khoẻ", ["decryption_failed"])},
    ("PUT", "/me/energy-target"): {
        "403": pi(403, "Chưa đồng ý health_profile", ["consent_required"]),
        "409": pi(409, "Mục tiêu tự nhập dưới sàn chưa được xác nhận", ["below_floor_confirmation_required"]),
        "422": pi(422, "kcal_target ngoài [800, 5000], goal lạ hoặc hồ sơ thiếu chỉ số", ["validation_error", "profile_incomplete", "age_below_minimum"]),
        "500": pi(500, "Không giải mã được cột sức khoẻ", ["decryption_failed"])},
    ("PUT", "/me/allergens"): {
        "422": pi(422, "Mã dị ứng không có trong danh mục", ["unknown_code"])},
    ("PUT", "/me/diet"): {
        "422": pi(422, "Mã chế độ ăn không có trong danh mục", ["unknown_code"])},
    ("PUT", "/me/favorites"): {
        "422": pi(422, "Quá 5 món hoặc món không published", ["favorites_limit", "recipe_not_published"])},
    ("POST", "/pantry/lots"): {
        "422": pi(422, "Ngày mua ở tương lai, nguyên liệu không dùng được hoặc thân sai", ["acquired_at_in_future", "unknown_ingredient", "validation_error"])},
    ("PATCH", "/pantry/lots/{id}"): {
        "409": pi(409, "Chuyển trạng thái không hợp lệ, lô đã đóng hoặc lô không ở mức kiểm tra", ["invalid_lot_transition", "lot_closed", "lot_not_check_level"]),
        "422": pi(422, "Ngày mua ở tương lai hoặc thân sai", ["acquired_at_in_future", "validation_error"])},
    ("POST", "/pantry/lots/{id}/discard"): {
        "409": pi(409, "Lô đã used_up", ["invalid_lot_transition"])},
    ("POST", "/scans"): {
        "403": pi(403, "contribute = true nhưng chưa đồng ý photo_contribution", ["consent_required"]),
        "413": pi(413, "Ảnh lớn hơn 3 MB", ["image_too_large"]),
        "415": pi(415, "Tệp không phải ảnh (magic bytes)", ["unsupported_media_type"]),
        "422": pi(422, "Ảnh quá 4096², 0 hoặc > 2 ảnh, mode sai, hoặc Idempotency-Key bị dùng lại với thân khác",
                  ["image_too_many_pixels", "validation_error", "idempotency_key_reused"]),
        "503": pi(503, "Không có detector đang chạy, hàng đợi đầy, hoặc lỗi tạm thời", ["model_unavailable", "queue_full", "temporarily_unavailable"], headers=RA)},
    ("GET", "/scans/{id}/images/{ordinal}"): {
        "410": pi(410, "Ảnh gốc đã xoá theo hạn 30 ngày", ["image_purged"])},
    ("POST", "/scans/{id}/items"): {
        "409": pi(409, "Scan không ở done hoặc nguyên liệu đã có chip", ["scan_not_editable", "duplicate_item"]),
        "422": pi(422, "Nguyên liệu không dùng được, sai loại lượng, hoặc thân sai", ["unknown_ingredient", "qty_kind_mismatch", "validation_error"])},
    ("PATCH", "/scans/{id}/items/{itemId}"): {
        "409": pi(409, "Scan không ở done", ["scan_not_editable"]),
        "422": pi(422, "Nguyên liệu không dùng được, sai loại lượng, hoặc số đếm ngoài 0–99", ["unknown_ingredient", "qty_kind_mismatch", "validation_error"])},
    ("DELETE", "/scans/{id}/items/{itemId}"): {
        "409": pi(409, "Scan không ở done", ["scan_not_editable"])},
    ("POST", "/scans/{id}/confirm"): {
        "409": pi(409, "Scan ở trạng thái không cho xác nhận, hoặc còn chip 'kiểm tra' chưa xác nhận", ["invalid_scan_state", "freshness_check_required"]),
        "422": pi(422, "Chip không đếm được chưa có mức, hoặc đồ đếm được chưa có quy đổi đơn vị", ["qty_level_required", "unit_conversion_missing"])},
    ("POST", "/scans/{id}/discard"): {
        "409": pi(409, "Scan ở trạng thái không cho bỏ (đã confirmed, đang xử lý)", ["invalid_scan_state"])},
    ("POST", "/meal-plans"): {
        "422": pi(422, "Không có mâm khả thi, không dùng đủ lô ghim, thân sai, hoặc Idempotency-Key bị dùng lại",
                  ["no_feasible_tray", "pin_unsatisfiable", "validation_error", "idempotency_key_reused"], schema="InfeasibleTrayProblem")},
    ("POST", "/meal-plans/{id}/accept"): {
        "409": pi(409, "Mâm ở cooked, abandoned hoặc expired", ["conflict_state"])},
    ("POST", "/meal-plans/{id}/items/{itemId}/swap"): {
        "409": pi(409, "Mâm không ở proposed/accepted, món đã bị đổi, hoặc yêu cầu cùng khoá đang chạy", ["conflict_state"] + IDEM409, headers=RA),
        "422": pi(422, "Không còn món thay khả thi, thân sai, hoặc Idempotency-Key bị dùng lại", ["no_alternative", "validation_error"] + IDEM422, schema="InfeasibleTrayProblem")},
    ("GET", "/meal-plans/{id}/items/{itemId}/substitutes"): {
        "409": pi(409, "Mâm không ở proposed/accepted hoặc món không active", ["conflict_state"])},
    ("POST", "/meal-plans/{id}/items/{itemId}/substitutions"): {
        "409": pi(409, "Mâm không ở proposed/accepted hoặc món không active", ["conflict_state"]),
        "422": pi(422, "Đồ thay vi phạm dị ứng/chế độ ăn hoặc thân sai", ["validation_error"])},
    ("PATCH", "/shopping-items/{id}"): {
        "409": pi(409, "Chuyển trạng thái không hợp lệ hoặc sửa dòng không open", ["conflict_state"]),
        "422": pi(422, "Thân sai", ["validation_error"])},
    ("POST", "/cook-sessions"): {
        "409": pi(409, "Mâm chưa accepted, không nấu được, đã có phiên đang nấu, hoặc yêu cầu cùng khoá đang chạy",
                  ["meal_plan_not_accepted", "meal_plan_not_cookable", "cook_session_in_progress"] + IDEM409, headers=RA),
        "422": pi(422, "Món không có bước nấu, thân sai, hoặc Idempotency-Key bị dùng lại", ["recipe_without_steps", "validation_error"] + IDEM422),
        "503": pi(503, "Lỗi CSDL tạm thời; gửi lại cùng Idempotency-Key", ["temporarily_unavailable"], headers=RA)},
    ("POST", "/cook-sessions/{id}/complete"): {
        "409": pi(409, "Phiên không ở in_progress hoặc yêu cầu cùng khoá đang chạy", ["cook_session_not_in_progress"] + IDEM409, headers=RA),
        "422": pi(422, "Thân sai hoặc Idempotency-Key bị dùng lại", ["validation_error"] + IDEM422),
        "503": pi(503, "Lỗi CSDL tạm thời; gửi lại cùng Idempotency-Key", ["temporarily_unavailable"], headers=RA)},
    ("POST", "/cook-sessions/{id}/undo"): {
        "409": pi(409, "Quá 10 phút hoặc phiên không ở completed", ["undo_window_expired", "cook_session_not_completed"]),
        "503": pi(503, "Lỗi CSDL tạm thời", ["temporarily_unavailable"], headers=RA)},
    ("POST", "/cook-sessions/{id}/abandon"): {
        "409": pi(409, "Phiên không ở in_progress", ["cook_session_not_in_progress"])},
    ("GET", "/journal"): {
        "422": pi(422, "week không phải tuần ISO 8601 hợp lệ", ["invalid_iso_week"])},
    ("POST", "/survey/respondents"): {
        "403": None,
        "409": pi(409, "Không có phiếu đang mở hoặc policy_version_id không còn hiện hành", ["survey_closed", "policy_outdated"]),
        "422": pi(422, "Cờ đồng ý false hoặc thân sai", ["consent_required", "validation_error"]),
        "503": pi(503, "Phiếu cấu hình sai (thiếu món published)", ["survey_form_misconfigured"])},
    ("PUT", "/survey/respondents/{id}/ratings/{recipeId}"): {
        "409": pi(409, "Phiếu đã đóng hoặc đã hoàn tất", ["survey_closed", "survey_already_completed"]),
        "422": pi(422, "Điểm ngoài 1–5 hoặc mâu thuẫn với never_eaten", ["invalid_rating"])},
    ("PUT", "/survey/respondents/{id}/favorites"): {
        "409": pi(409, "Phiếu đã đóng hoặc đã hoàn tất", ["survey_closed", "survey_already_completed"]),
        "422": pi(422, "Quá 5 món, món trùng hoặc món không published", ["invalid_favorites"])},
    ("POST", "/survey/respondents/{id}/complete"): {
        "409": pi(409, "Phiếu đã đóng", ["survey_closed"]),
        "422": pi(422, "Còn món chưa trả lời", ["survey_incomplete"])},
    ("POST", "/admin/data-requests/{id}/resolve"): {
        "409": pi(409, "Yêu cầu loại tự xử lý hoặc không ở trạng thái mở", ["request_not_manual", "conflict_state"]),
        "422": pi(422, "Từ chối không có lý do hoặc thân sai", ["reason_required", "validation_error"])},
}

# ------------------------------------------------------------------ assemble
MODULE_IDS = {m["name"]: m["id"] for m in MODEL["modules"]}
paths = {}
missing = []
for ep in MODEL["endpoints"]:
    method, path, module, ucs, idem, auth = ep
    key = (method, path)
    if key not in OPS:
        missing.append(key)
        continue
    d = OPS[key]
    assert d["opid"].startswith(module + "_"), d["opid"]
    root = path in ("/healthz", "/readyz")
    o = {"operationId": d["opid"], "tags": [module], "summary": d["summary"]}
    desc = d["desc"]
    for _old, _new in RENAMED.items():
        desc = re.sub(rf"\b{_old}\b", _new, desc)
    o["description"] = desc if desc else d["summary"] + "."
    o["x-use-cases"] = ucs
    o["x-module"] = MODULE_IDS[module]
    if idem == "Idempotency-Key":
        o["x-idempotency"] = "idempotency-key"
    elif idem == "event_id":
        o["x-idempotency"] = "event-id"
    else:
        o["x-idempotency"] = "idempotent" if idem else "none"
    # security
    if auth == "public":
        o["security"] = []
    elif auth == "user":
        o["security"] = [{"bearerAuth": []}]
    elif auth.startswith("staff:"):
        role = auth.split(":", 1)[1]
        o["security"] = [{"bearerAuth": []}]
        o["x-required-role"] = role
        o["description"] += f" Chỉ vai trò `{role}` (claim `role` trong JWT); vai trò khác → 403 forbidden. Mọi lời gọi ghi audit_log."
    elif auth == "public+respondent_token":
        o["security"] = [{"respondentToken": []}]
    else:
        raise SystemExit(f"auth lạ {auth}")
    params = list(d["params"])
    if d["paginated"]:
        params += [PREF("Cursor"), PREF("Limit")]
    if idem == "Idempotency-Key":
        params.append(PREF("IdempotencyKey"))
    if not root:
        params.append(PREF("AppVersion"))
    if params:
        o["parameters"] = params
    if d["req"]:
        o["requestBody"] = d["req"]
    resp = {}
    for st, r in d["oks"]:
        r = dict(r)
        if idem == "Idempotency-Key" and st.startswith("2"):
            r["headers"] = dict(r.get("headers", {}))
            r["headers"]["Idempotent-Replayed"] = HREF("IdempotentReplayed")
        resp[st] = r
    errs = {}
    if not root:
        if params or d["req"]:
            errs["400"] = "BadRequest"
        if auth != "public":
            errs["401"] = "Unauthorized"
        if auth.startswith("staff:"):
            errs["403"] = "Forbidden"
        if "{" in path:
            errs["404"] = "NotFound"
        errs["412"] = "AppTooOld"
        if idem == "Idempotency-Key":
            errs["400"] = problem_inline(400, "Thân sai cú pháp hoặc thiếu Idempotency-Key", ["validation_error", "idempotency_key_required"])
            errs["409"] = problem_inline(409, "Yêu cầu đầu tiên cùng Idempotency-Key còn đang chạy", ["idempotency_in_progress"],
                                         headers={"Retry-After": HREF("RetryAfter")})
            errs["422"] = problem_inline(422, "Idempotency-Key bị dùng lại với thân khác", ["idempotency_key_reused"])
        if auth == "public+respondent_token":
            errs["401"] = problem_inline(401, "Thiếu, sai hoặc hết hạn X-Respondent-Token", ["respondent_token_invalid"])
    errs.update(d["errs"])
    errs.update(ERR_OVERRIDES.get(key, {}))
    for st in sorted(errs):
        v = errs[st]
        if v is None:
            continue
        resp[st] = RREF(v) if isinstance(v, str) else v
    o["responses"] = dict(sorted(resp.items()))
    item = paths.setdefault(path, {})
    if root:
        item["servers"] = [{"url": "/", "description": "Gốc máy chủ, ngoài tiền tố /api/v1"}]
    item[method.lower()] = o

if missing:
    raise SystemExit(f"thiếu định nghĩa cho {missing}")
extra = set(OPS) - {(e[0], e[1]) for e in MODEL["endpoints"]}
if extra:
    raise SystemExit(f"định nghĩa thừa {extra}")

tags = []
for m in MODEL["modules"]:
    if any(e[2] == m["name"] for e in MODEL["endpoints"]):
        tags.append({"name": m["name"], "description": f"{m['id']} — {m['desc']}"})

doc = {
    "openapi": "3.1.0",
    "info": {
        "title": "Tastoria API",
        "version": "1.0.0",
        "summary": "Hợp đồng HTTP của backend Tastoria (modular monolith FastAPI)",
        "description": (
            "Nguồn mã định danh: `docs/sad/model.yaml` (70 endpoint, module M01–M16, use case UC01–UC34). "
            "Thiết kế: `docs/superpowers/specs/2026-10-17-tastoria-thiet-ke-v2.md` §8.\n\n"
            "**Quy ước chung**\n"
            "- Tiền tố `/api/v1` cho mọi endpoint trừ `/healthz`, `/readyz` (ở gốc).\n"
            "- Id công khai là UUID. Mọi truy vấn theo `{id}` lọc theo chủ sở hữu; tài nguyên của người khác trả 404 (chống BOLA).\n"
            "- Lỗi theo RFC 9457 `application/problem+json`, có `code` ổn định (schema `ProblemCode`).\n"
            "- `Idempotency-Key` bắt buộc ở các thao tác `x-idempotency: idempotency-key` (POST /scans, /meal-plans, swap, /cook-sessions, /complete); lưu 48 giờ.\n"
            "- `x-idempotency: idempotent` nghĩa là gọi lại cùng thân cho cùng kết quả mà không cần khoá; `event-id` là chống trùng theo event_id trong thân; `none` là mỗi lần gọi tạo tài nguyên mới.\n"
            "- Phân trang keyset: `cursor` + `limit` (≤ 100) → `next_cursor` (null khi hết).\n"
            "- Thời gian ISO 8601 có múi giờ; tuần theo ISO 8601; múi giờ mặc định Asia/Ho_Chi_Minh.\n"
            "- Header `X-App-Version` từ app; quá cũ → 412 `app_too_old`.\n"
            "- Tác vụ bất đồng bộ trả 202 + `Location` + `Retry-After`.\n"
            "- Endpoint nhân sự (`/admin/*`) yêu cầu vai trò ghi ở `x-required-role`; các thao tác nhân sự còn lại chạy bằng CLI `tastoria ...` (xem model.yaml mục cli).\n"
            "- Mở rộng: `x-use-cases` (UC trong model.yaml), `x-module` (M01–M16), `x-idempotency`, `x-required-role`."
        ),
        "license": {"name": "Nội bộ — đồ án học phần", "identifier": "LicenseRef-Tastoria-Internal"},
    },
    "servers": [{"url": "/api/v1", "description": "Tương đối theo máy chủ triển khai (nginx → api)"}],
    "tags": tags,
    "paths": paths,
    "components": {
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                           "description": "Access JWT 15 phút (header có `kid`; claim `sub` = users.id, `role`, `tv` = users.token_version). token_version tăng (đăng xuất mọi nơi, rút đồng ý, đổi mật khẩu) thì token cũ bị từ chối với 401 token_revoked."},
            "respondentToken": {"type": "apiKey", "in": "header", "name": "X-Respondent-Token",
                                "description": "Token người tham gia khảo sát (A03) nhận từ POST /survey/respondents; chỉ mở được phiếu của chính người đó."},
        },
        "parameters": P,
        "headers": H,
        "responses": RESP,
        "schemas": S,
    },
}


class Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def str_presenter(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


Dumper.add_representer(str, str_presenter)

_used = set()
for _item in paths.values():
    for _m, _o in _item.items():
        if not isinstance(_o, dict) or "responses" not in _o:
            continue
        for _st, _r in _o["responses"].items():
            for _c in re.findall(r"`([a-z_]+)`", _r.get("description", "")):
                if _c not in PROBLEM_CODES:
                    raise SystemExit(f"{_m.upper()} {_st}: mã {_c} không có trong danh mục")
                _used.add(_c)
for _r in RESP.values():
    for _c in _r["content"]["application/problem+json"].get("examples", {}):
        _used.add(_c)
_dump = yaml.dump(doc, Dumper=Dumper, sort_keys=False, allow_unicode=True)
for _old in list(RENAMED) + ["token_invalid"]:
    if re.search(rf"\b{_old}\b", _dump):
        raise SystemExit(f"còn mã cũ {_old} trong tài liệu")
_unused = [c for c in PROBLEM_CODES if c not in _used and c not in ("idempotency_key_required",)]
if _unused:
    raise SystemExit(f"mã trong danh mục chưa endpoint nào dùng: {_unused}")
with open(OUT, "w", encoding="utf-8") as f:
    f.write("# Tastoria — OpenAPI 3.1 cho 70 endpoint trong docs/sad/model.yaml.\n")
    f.write("# Định danh (module, UC, bảng, cột) lấy đúng từ model.yaml; không sửa tay mã ngoài model.\n")
    yaml.dump(doc, f, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)
print("ok", len(MODEL["endpoints"]), "endpoints")
