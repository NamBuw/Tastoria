# Ma trận truy vết

> Tệp sinh tự động bởi `docs/sad/tools/gen_traceability.py` từ `docs/sad/model.yaml`, front-matter `docs/sad/use-cases/UCxx.md` và `docs/sad/06-ke-hoach-kiem-thu.md`. Không sửa tay; sửa nguồn rồi chạy lại script.

## 1. Tóm tắt ô trống

| Nhóm | Số lượng |
|---|---|
| Endpoint không UC nào dùng và không TC nào kiểm | 0 |
| Bảng không UC nào dùng | 0 |
| BR không UC nào và không TC nào tham chiếu | 0 |
| FR chưa có TC | 0 |
| UC chưa có FR | 0 |
| UC chưa có TC | 0 |
| **Tổng** | **0** |

## 2. Ma trận UC × FR × endpoint/CLI × module × bảng × TC

| UC | Tên | FR | Endpoint / CLI | Module | Bảng / view | TC |
|---|---|---|---|---|---|---|
| UC01 | Đăng ký tài khoản | `FR-01-01`<br>`FR-01-02`<br>`FR-01-03`<br>`FR-01-04`<br>`FR-01-05`<br>`FR-01-06`<br>`FR-01-07`<br>`FR-01-08` | `POST /auth/register` | `identity` | `users`<br>`refresh_tokens`<br>`consent_events` | `TC-AUTH-01`<br>`TC-AUTH-02`<br>`TC-AUTH-03`<br>`TC-AUTH-04`<br>`TC-CONT-01`<br>`TC-E2E-01`<br>`TC-E2E-05` |
| UC02 | Đăng nhập | `FR-02-01`<br>`FR-02-02`<br>`FR-02-03`<br>`FR-02-04`<br>`FR-02-05`<br>`FR-02-06`<br>`FR-02-07`<br>`FR-02-08`<br>`FR-02-09`<br>`FR-02-10` | `POST /auth/login`<br>`POST /auth/refresh` | `identity` | `users`<br>`refresh_tokens` | `TC-AUTH-03`<br>`TC-AUTH-05`<br>`TC-AUTH-06`<br>`TC-AUTH-07`<br>`TC-AUTH-08`<br>`TC-AUTH-09`<br>`TC-CONT-01`<br>`TC-SEC-06` |
| UC03 | Đăng xuất (một hoặc mọi thiết bị) | `FR-03-01`<br>`FR-03-02`<br>`FR-03-03`<br>`FR-03-04`<br>`FR-03-05`<br>`FR-03-06` | `POST /auth/logout`<br>`POST /auth/logout-all` | `identity` | `users`<br>`refresh_tokens` | `TC-AUTH-10`<br>`TC-AUTH-11`<br>`TC-AUTH-12`<br>`TC-AUTH-13`<br>`TC-CONT-01` |
| UC04 | Đặt lại mật khẩu | `FR-04-01`<br>`FR-04-02`<br>`FR-04-03`<br>`FR-04-04`<br>`FR-04-05`<br>`FR-04-06`<br>`FR-04-07`<br>`FR-04-08`<br>`FR-04-09`<br>`FR-04-10`<br>`FR-04-11`<br>`FR-04-12` | `POST /auth/password-reset/request`<br>`POST /auth/password-reset/confirm` | `identity` | `users`<br>`password_resets`<br>`refresh_tokens` | `TC-AUTH-14`<br>`TC-AUTH-15`<br>`TC-AUTH-16`<br>`TC-AUTH-17`<br>`TC-AUTH-18`<br>`TC-CONT-01` |
| UC05 | Quản lý đồng ý theo mục đích | `FR-05-01`<br>`FR-05-02`<br>`FR-05-03`<br>`FR-05-04`<br>`FR-05-05`<br>`FR-05-06`<br>`FR-05-07`<br>`FR-05-08`<br>`FR-05-09`<br>`FR-05-10`<br>`FR-05-11`<br>`FR-05-12`<br>`FR-05-13`<br>`FR-05-14`<br>`FR-05-15` | `GET /policies/{purpose}/current`<br>`GET /me/consents`<br>`POST /me/consents`<br>`POST /me/consents/{purpose}/withdraw` | `privacy` | `consent_purposes`<br>`policy_versions`<br>`consent_events`<br>`v_current_consents`<br>`users`<br>`dsr_requests`<br>`profiles`<br>`interactions`<br>`scan_images` | `TC-CONT-01`<br>`TC-E2E-04`<br>`TC-PRIV-01`<br>`TC-PRIV-02`<br>`TC-PRIV-03`<br>`TC-PRIV-04`<br>`TC-PRIV-05`<br>`TC-PRIV-06`<br>`TC-PRIV-07`<br>`TC-PRIV-08`<br>`TC-PRIV-18` |
| UC06 | Tải về dữ liệu cá nhân | `FR-06-01`<br>`FR-06-02`<br>`FR-06-03`<br>`FR-06-04`<br>`FR-06-05`<br>`FR-06-06`<br>`FR-06-07`<br>`FR-06-08`<br>`FR-06-09`<br>`FR-06-10`<br>`FR-06-11`<br>`FR-06-12` | `POST /me/data-requests`<br>`GET /me/data-requests/{id}`<br>`GET /me/data-requests/{id}/download` | `privacy` | `dsr_requests`<br>`audit_log`<br>`users`<br>`refresh_tokens`<br>`consent_events`<br>`v_current_consents`<br>`profiles`<br>`user_allergens`<br>`user_favorite_recipes`<br>`user_settings`<br>`pantry_lots`<br>`pantry_transactions`<br>`scans`<br>`scan_images`<br>`scan_items`<br>`detections`<br>`shopping_items`<br>`meal_plans`<br>`meal_plan_coeater_allergens`<br>`meal_plan_pins`<br>`meal_plan_items`<br>`meal_plan_item_substitutions`<br>`cook_sessions`<br>`cook_schedule_entries`<br>`interactions` | `TC-CONT-01`<br>`TC-E2E-04`<br>`TC-PRIV-09`<br>`TC-PRIV-10`<br>`TC-PRIV-11`<br>`TC-PRIV-12`<br>`TC-PRIV-20`<br>`TC-SEC-01`<br>`TC-SEC-08` |
| UC07 | Xoá tài khoản và toàn bộ dữ liệu | `FR-07-01`<br>`FR-07-02`<br>`FR-07-03`<br>`FR-07-04`<br>`FR-07-05`<br>`FR-07-06`<br>`FR-07-07`<br>`FR-07-08`<br>`FR-07-09`<br>`FR-07-10` | `POST /me/data-requests`<br>`GET /me/data-requests/{id}` | `privacy` | `dsr_requests`<br>`users`<br>`refresh_tokens`<br>`password_resets`<br>`idempotency_keys`<br>`consent_events`<br>`audit_log`<br>`profiles`<br>`user_allergens`<br>`user_favorite_recipes`<br>`user_settings`<br>`pantry_lots`<br>`pantry_transactions`<br>`scans`<br>`scan_images`<br>`scan_items`<br>`detections`<br>`shopping_items`<br>`meal_plans`<br>`meal_plan_coeater_allergens`<br>`meal_plan_pins`<br>`meal_plan_items`<br>`meal_plan_item_substitutions`<br>`cook_sessions`<br>`cook_schedule_entries`<br>`interactions` | `TC-CONT-01`<br>`TC-E2E-04`<br>`TC-PRIV-13`<br>`TC-PRIV-14`<br>`TC-PRIV-15`<br>`TC-PRIV-16`<br>`TC-PRIV-22` |
| UC08 | Yêu cầu sửa, hạn chế hoặc phản đối xử lý | `FR-08-01`<br>`FR-08-02`<br>`FR-08-03`<br>`FR-08-04`<br>`FR-08-05`<br>`FR-08-06`<br>`FR-08-07`<br>`FR-08-08`<br>`FR-08-09`<br>`FR-08-10`<br>`FR-08-11` | `POST /me/data-requests`<br>`GET /me/data-requests/{id}`<br>`POST /admin/data-requests/{id}/resolve` | `privacy`<br>`admin` | `dsr_requests`<br>`audit_log`<br>`users` | `TC-CONT-01`<br>`TC-PRIV-17`<br>`TC-PRIV-18`<br>`TC-PRIV-19`<br>`TC-PRIV-21`<br>`TC-SEC-05` |
| UC09 | Thiết lập hồ sơ 60 giây | `FR-09-01`<br>`FR-09-02`<br>`FR-09-03`<br>`FR-09-04`<br>`FR-09-05`<br>`FR-09-06`<br>`FR-09-07`<br>`FR-09-08`<br>`FR-09-09`<br>`FR-09-10`<br>`FR-09-11`<br>`FR-09-12`<br>`FR-09-13` | `GET /policies/{purpose}/current`<br>`POST /me/consents`<br>`PUT /me/profile`<br>`POST /me/energy-suggestion`<br>`PUT /me/energy-target`<br>`PUT /me/allergens`<br>`PUT /me/diet`<br>`PUT /me/favorites`<br>`GET /reference`<br>`GET /recipes` | `privacy`<br>`profile`<br>`catalog` | `consent_purposes`<br>`policy_versions`<br>`consent_events`<br>`v_current_consents`<br>`profiles`<br>`user_allergens`<br>`user_favorite_recipes`<br>`allergen_groups`<br>`diets`<br>`recipes`<br>`audit_log` | `TC-A11Y-01`<br>`TC-CONT-01`<br>`TC-E2E-01`<br>`TC-PROF-01`<br>`TC-PROF-02`<br>`TC-PROF-03`<br>`TC-PROF-04`<br>`TC-PROF-05`<br>`TC-PROF-06`<br>`TC-UAT-01`<br>`TC-UAT-02`<br>`TC-UAT-03` |
| UC10 | Cập nhật hồ sơ, dị ứng, chế độ ăn, cài đặt bếp | `FR-10-01`<br>`FR-10-02`<br>`FR-10-03`<br>`FR-10-04`<br>`FR-10-05`<br>`FR-10-06`<br>`FR-10-07`<br>`FR-10-08`<br>`FR-10-09`<br>`FR-10-10`<br>`FR-10-11`<br>`FR-10-12` | `GET /me/profile`<br>`PUT /me/profile`<br>`PUT /me/allergens`<br>`PUT /me/diet`<br>`PUT /me/favorites`<br>`GET /me/settings`<br>`PUT /me/settings`<br>`GET /reference` | `profile`<br>`catalog` | `profiles`<br>`user_allergens`<br>`user_favorite_recipes`<br>`user_settings`<br>`allergen_groups`<br>`diets`<br>`diet_exclusions`<br>`recipes`<br>`v_current_consents`<br>`audit_log` | `TC-CONT-01`<br>`TC-E2E-04`<br>`TC-PRIV-18`<br>`TC-PROF-03`<br>`TC-PROF-07`<br>`TC-PROF-08`<br>`TC-PROF-09`<br>`TC-PROF-10`<br>`TC-PROF-11`<br>`TC-PROF-12`<br>`TC-PROF-13` |
| UC11 | Đặt mục tiêu năng lượng (gợi ý / tự nhập / chuyên gia) | `FR-11-01`<br>`FR-11-02`<br>`FR-11-03`<br>`FR-11-04`<br>`FR-11-05`<br>`FR-11-06`<br>`FR-11-07`<br>`FR-11-08`<br>`FR-11-09`<br>`FR-11-10`<br>`FR-11-11`<br>`FR-11-12`<br>`FR-11-13`<br>`FR-11-14`<br>`FR-11-15`<br>`FR-11-16` | `POST /me/energy-suggestion`<br>`PUT /me/energy-target` | `profile` | `profiles`<br>`v_current_consents`<br>`audit_log` | `TC-CONT-01`<br>`TC-NUT-01`<br>`TC-NUT-02`<br>`TC-NUT-03`<br>`TC-NUT-04`<br>`TC-NUT-05`<br>`TC-NUT-06`<br>`TC-NUT-07`<br>`TC-NUT-08`<br>`TC-NUT-09`<br>`TC-NUT-10`<br>`TC-NUT-11`<br>`TC-PROP-08` |
| UC12 | Quét nguyên liệu (toàn tủ hoặc đồ vừa mua) | `FR-12-01`<br>`FR-12-02`<br>`FR-12-03`<br>`FR-12-04`<br>`FR-12-05`<br>`FR-12-06`<br>`FR-12-07`<br>`FR-12-08`<br>`FR-12-09`<br>`FR-12-10`<br>`FR-12-11`<br>`FR-12-12`<br>`FR-12-13`<br>`FR-12-14`<br>`FR-12-15`<br>`FR-12-16`<br>`FR-12-17`<br>`FR-12-18`<br>`FR-12-19` | `POST /scans`<br>`GET /scans/{id}` | `scan` | `scans`<br>`scan_images`<br>`scan_items`<br>`detections`<br>`idempotency_keys`<br>`model_deployments`<br>`model_versions`<br>`model_version_classes`<br>`vision_classes`<br>`vision_class_ingredients`<br>`ingredients`<br>`pantry_lots`<br>`v_current_consents` | `TC-CONT-01`<br>`TC-E2E-01`<br>`TC-E2E-02`<br>`TC-E2E-05`<br>`TC-ONNX-01`<br>`TC-ONNX-02`<br>`TC-PERF-01`<br>`TC-PERF-03`<br>`TC-REL-02`<br>`TC-REL-04`<br>`TC-SCAN-01`<br>`TC-SCAN-02`<br>`TC-SCAN-03`<br>`TC-SCAN-04`<br>`TC-SCAN-05`<br>`TC-SCAN-06`<br>`TC-SCAN-07`<br>`TC-SCAN-08`<br>`TC-SCAN-09`<br>`TC-SCAN-10`<br>`TC-SCAN-11`<br>`TC-SCAN-12`<br>`TC-SCAN-13`<br>`TC-SEC-01`<br>`TC-SEC-02`<br>`TC-SEC-04`<br>`TC-UAT-01`<br>`TC-UAT-02` |
| UC13 | Xác nhận và sửa kết quả quét | `FR-13-01`<br>`FR-13-02`<br>`FR-13-03`<br>`FR-13-04`<br>`FR-13-05`<br>`FR-13-06`<br>`FR-13-07`<br>`FR-13-08`<br>`FR-13-09`<br>`FR-13-10`<br>`FR-13-11`<br>`FR-13-12`<br>`FR-13-13`<br>`FR-13-14`<br>`FR-13-15`<br>`FR-13-16`<br>`FR-13-17`<br>`FR-13-18`<br>`FR-13-19`<br>`FR-13-20` | `GET /ingredients`<br>`GET /scans/{id}`<br>`GET /scans/{id}/images/{ordinal}`<br>`POST /scans/{id}/items`<br>`PATCH /scans/{id}/items/{itemId}`<br>`DELETE /scans/{id}/items/{itemId}`<br>`POST /scans/{id}/confirm`<br>`POST /scans/{id}/discard` | `catalog`<br>`scan` | `scans`<br>`scan_images`<br>`scan_items`<br>`detections`<br>`ingredients`<br>`ingredient_synonyms`<br>`ingredient_units`<br>`qty_levels`<br>`pantry_lots`<br>`v_pantry_lot_balance` | `TC-A11Y-02`<br>`TC-CONT-01`<br>`TC-E2E-01`<br>`TC-SCAN-14`<br>`TC-SCAN-15`<br>`TC-SCAN-16`<br>`TC-SCAN-17`<br>`TC-SCAN-18`<br>`TC-SCAN-19`<br>`TC-SCAN-20`<br>`TC-SCAN-21`<br>`TC-SCAN-22`<br>`TC-SCAN-23`<br>`TC-SCAN-24`<br>`TC-SEC-01`<br>`TC-SEC-08`<br>`TC-UAT-02` |
| UC14 | Quản lý kho (sửa lượng, ngày mua, bỏ đồ, xác nhận đồ cần kiểm tra) | `FR-14-01`<br>`FR-14-02`<br>`FR-14-03`<br>`FR-14-04`<br>`FR-14-05`<br>`FR-14-06`<br>`FR-14-07`<br>`FR-14-08`<br>`FR-14-09`<br>`FR-14-10`<br>`FR-14-11`<br>`FR-14-12`<br>`FR-14-13`<br>`FR-14-14`<br>`FR-14-15`<br>`FR-14-16`<br>`FR-14-17`<br>`FR-14-18`<br>`FR-14-19` | `GET /ingredients`<br>`GET /pantry/lots`<br>`POST /pantry/lots`<br>`PATCH /pantry/lots/{id}`<br>`POST /pantry/lots/{id}/discard` | `catalog`<br>`pantry` | `pantry_lots`<br>`pantry_transactions`<br>`v_pantry_lot_balance`<br>`ingredients`<br>`ingredient_synonyms`<br>`ingredient_units`<br>`qty_levels`<br>`food_groups` | `TC-A11Y-02`<br>`TC-CONT-01`<br>`TC-PANT-01`<br>`TC-PANT-02`<br>`TC-PANT-03`<br>`TC-PANT-04`<br>`TC-PANT-05`<br>`TC-PANT-06`<br>`TC-PANT-07`<br>`TC-PANT-08`<br>`TC-PANT-09`<br>`TC-PANT-10`<br>`TC-PANT-11`<br>`TC-PANT-12`<br>`TC-PANT-13`<br>`TC-PANT-14`<br>`TC-PANT-15`<br>`TC-PERF-04`<br>`TC-PROP-05`<br>`TC-PROP-06`<br>`TC-SEC-01` |
| UC15 | Nhận mâm cơm hôm nay | `FR-15-01`<br>`FR-15-02`<br>`FR-15-03`<br>`FR-15-04`<br>`FR-15-05`<br>`FR-15-06`<br>`FR-15-07`<br>`FR-15-08`<br>`FR-15-09`<br>`FR-15-10`<br>`FR-15-11`<br>`FR-15-12`<br>`FR-15-13`<br>`FR-15-14`<br>`FR-15-15`<br>`FR-15-16`<br>`FR-15-17`<br>`FR-15-18`<br>`FR-15-19`<br>`FR-15-20`<br>`FR-15-21`<br>`FR-15-22`<br>`FR-15-23`<br>`FR-15-24`<br>`FR-15-25`<br>`FR-15-26`<br>`FR-15-27`<br>`FR-15-28`<br>`FR-15-29`<br>`FR-15-30`<br>`FR-15-31`<br>`FR-15-32`<br>`FR-15-33`<br>`FR-15-34`<br>`FR-15-35`<br>`FR-15-36`<br>`FR-15-37`<br>`FR-15-38`<br>`FR-15-39`<br>`FR-15-40`<br>`FR-15-41` | `GET /reference`<br>`GET /recipes`<br>`GET /recipes/{id}`<br>`GET /pantry/lots`<br>`POST /meal-plans`<br>`GET /meal-plans/latest`<br>`GET /meal-plans/{id}`<br>`POST /meal-plans/{id}/accept`<br>`POST /events` | `catalog`<br>`pantry`<br>`meal`<br>`events` | `meal_plans`<br>`meal_plan_items`<br>`meal_plan_coeater_allergens`<br>`meal_plan_pins`<br>`meal_plan_item_substitutions`<br>`idempotency_keys`<br>`profiles`<br>`user_allergens`<br>`user_favorite_recipes`<br>`user_settings`<br>`allergen_groups`<br>`diets`<br>`diet_exclusions`<br>`food_groups`<br>`ingredients`<br>`ingredient_allergens`<br>`ingredient_units`<br>`recipes`<br>`recipe_ingredients`<br>`recipe_steps`<br>`recipe_nutrition`<br>`recipe_tags`<br>`recipe_sources`<br>`tags`<br>`cooking_methods`<br>`food_items`<br>`food_nutrients`<br>`nutrients`<br>`pantry_lots`<br>`v_pantry_lot_balance`<br>`substitution_pairs`<br>`model_deployments`<br>`model_versions`<br>`interactions`<br>`v_current_consents`<br>`audit_log` | `TC-A11Y-01`<br>`TC-CONT-01`<br>`TC-E2E-01`<br>`TC-E2E-02`<br>`TC-E2E-05`<br>`TC-MEAL-01`<br>`TC-MEAL-02`<br>`TC-MEAL-03`<br>`TC-MEAL-04`<br>`TC-MEAL-05`<br>`TC-MEAL-06`<br>`TC-MEAL-07`<br>`TC-MEAL-08`<br>`TC-MEAL-09`<br>`TC-MEAL-10`<br>`TC-MEAL-11`<br>`TC-MEAL-12`<br>`TC-MEAL-13`<br>`TC-MEAL-14`<br>`TC-MEAL-15`<br>`TC-MEAL-16`<br>`TC-MEAL-17`<br>`TC-MEAL-18`<br>`TC-MEAL-19`<br>`TC-MEAL-20`<br>`TC-MEAL-21`<br>`TC-MEAL-22`<br>`TC-MEAL-38`<br>`TC-MEAL-39`<br>`TC-MEAL-40`<br>`TC-PERF-02`<br>`TC-PERF-04`<br>`TC-PROP-01`<br>`TC-PROP-02`<br>`TC-PROP-03`<br>`TC-PROP-04`<br>`TC-SEC-01`<br>`TC-SEC-02`<br>`TC-SEC-03`<br>`TC-UAT-01`<br>`TC-UAT-02` |
| UC16 | Đổi một món | `FR-16-01`<br>`FR-16-02`<br>`FR-16-03`<br>`FR-16-04`<br>`FR-16-05`<br>`FR-16-06`<br>`FR-16-07`<br>`FR-16-08`<br>`FR-16-09`<br>`FR-16-10`<br>`FR-16-11`<br>`FR-16-12`<br>`FR-16-13`<br>`FR-16-14` | `POST /meal-plans/{id}/items/{itemId}/swap`<br>`POST /events` | `meal`<br>`events` | `meal_plans`<br>`meal_plan_items`<br>`meal_plan_coeater_allergens`<br>`meal_plan_pins`<br>`meal_plan_item_substitutions`<br>`idempotency_keys`<br>`profiles`<br>`user_allergens`<br>`user_favorite_recipes`<br>`user_settings`<br>`diet_exclusions`<br>`ingredients`<br>`ingredient_allergens`<br>`ingredient_units`<br>`recipes`<br>`recipe_ingredients`<br>`recipe_steps`<br>`recipe_nutrition`<br>`recipe_tags`<br>`cooking_methods`<br>`pantry_lots`<br>`v_pantry_lot_balance`<br>`substitution_pairs`<br>`model_deployments`<br>`model_versions`<br>`interactions`<br>`v_current_consents`<br>`audit_log` | `TC-CONT-01`<br>`TC-MEAL-23`<br>`TC-MEAL-24`<br>`TC-MEAL-25`<br>`TC-MEAL-26`<br>`TC-MEAL-27`<br>`TC-MEAL-28`<br>`TC-MEAL-29`<br>`TC-PROP-01`<br>`TC-PROP-02`<br>`TC-PROP-03`<br>`TC-PROP-07`<br>`TC-SEC-01`<br>`TC-SEC-02`<br>`TC-SEC-03`<br>`TC-UAT-02` |
| UC17 | Xem và chọn thay thế nguyên liệu thiếu (Thiếu gì?) | `FR-17-01`<br>`FR-17-02`<br>`FR-17-03`<br>`FR-17-04`<br>`FR-17-05`<br>`FR-17-06`<br>`FR-17-07`<br>`FR-17-08`<br>`FR-17-09`<br>`FR-17-10`<br>`FR-17-11`<br>`FR-17-12`<br>`FR-17-13`<br>`FR-17-14` | `GET /meal-plans/{id}/items/{itemId}/substitutes`<br>`POST /meal-plans/{id}/items/{itemId}/substitutions`<br>`POST /shopping-items` | `meal`<br>`substitute` | `meal_plans`<br>`meal_plan_items`<br>`meal_plan_coeater_allergens`<br>`meal_plan_item_substitutions`<br>`profiles`<br>`user_allergens`<br>`diet_exclusions`<br>`food_groups`<br>`ingredients`<br>`ingredient_allergens`<br>`ingredient_units`<br>`recipes`<br>`recipe_ingredients`<br>`food_items`<br>`food_nutrients`<br>`nutrients`<br>`pantry_lots`<br>`v_pantry_lot_balance`<br>`substitution_pairs`<br>`ingredient_embeddings`<br>`model_deployments`<br>`model_versions`<br>`shopping_items` | `TC-CONT-01`<br>`TC-MEAL-30`<br>`TC-MEAL-31`<br>`TC-MEAL-32`<br>`TC-MEAL-33`<br>`TC-MEAL-34`<br>`TC-MEAL-35`<br>`TC-MEAL-36`<br>`TC-MEAL-37`<br>`TC-PROP-01`<br>`TC-PROP-02`<br>`TC-SEC-01` |
| UC18 | Quản lý danh sách đi chợ | `FR-18-01`<br>`FR-18-02`<br>`FR-18-03`<br>`FR-18-04`<br>`FR-18-05`<br>`FR-18-06`<br>`FR-18-07`<br>`FR-18-08`<br>`FR-18-09`<br>`FR-18-10`<br>`FR-18-11`<br>`FR-18-12` | `GET /ingredients`<br>`GET /shopping-items`<br>`POST /shopping-items`<br>`PATCH /shopping-items/{id}` | `catalog`<br>`substitute` | `shopping_items`<br>`ingredients`<br>`ingredient_synonyms`<br>`ingredient_units`<br>`food_groups`<br>`meal_plan_items`<br>`meal_plans` | `TC-CONT-01`<br>`TC-SEC-01`<br>`TC-SHOP-01`<br>`TC-SHOP-02`<br>`TC-SHOP-03`<br>`TC-SHOP-04`<br>`TC-SHOP-05`<br>`TC-SHOP-06`<br>`TC-SHOP-07` |
| UC19 | Nấu cả mâm | `FR-19-01`<br>`FR-19-02`<br>`FR-19-03`<br>`FR-19-04`<br>`FR-19-05`<br>`FR-19-06`<br>`FR-19-07`<br>`FR-19-08`<br>`FR-19-09`<br>`FR-19-10`<br>`FR-19-11`<br>`FR-19-12`<br>`FR-19-13` | `GET /recipes/{id}`<br>`GET /catalog/snapshot`<br>`POST /cook-sessions`<br>`GET /cook-sessions/{id}`<br>`POST /cook-sessions/{id}/abandon`<br>`POST /events` | `catalog`<br>`cooking`<br>`events` | `meal_plans`<br>`meal_plan_items`<br>`meal_plan_item_substitutions`<br>`recipes`<br>`recipe_steps`<br>`recipe_ingredients`<br>`cooking_methods`<br>`user_settings`<br>`cook_sessions`<br>`cook_schedule_entries`<br>`idempotency_keys`<br>`interactions`<br>`v_current_consents` | `TC-CONT-01`<br>`TC-COOK-01`<br>`TC-COOK-02`<br>`TC-COOK-03`<br>`TC-COOK-04`<br>`TC-COOK-05`<br>`TC-COOK-06`<br>`TC-COOK-07`<br>`TC-E2E-01`<br>`TC-PERF-05`<br>`TC-PROP-04`<br>`TC-SEC-01`<br>`TC-SEC-02`<br>`TC-SEC-03`<br>`TC-UAT-01`<br>`TC-UAT-02` |
| UC20 | Hoàn tất bữa nấu (nấu xong một chạm) | `FR-20-01`<br>`FR-20-02`<br>`FR-20-03`<br>`FR-20-04`<br>`FR-20-05`<br>`FR-20-06`<br>`FR-20-07`<br>`FR-20-08`<br>`FR-20-09`<br>`FR-20-10`<br>`FR-20-11`<br>`FR-20-12`<br>`FR-20-13` | `POST /cook-sessions/{id}/complete`<br>`POST /events` | `cooking`<br>`events` | `cook_sessions`<br>`meal_plans`<br>`meal_plan_items`<br>`meal_plan_item_substitutions`<br>`recipe_ingredients`<br>`ingredients`<br>`ingredient_units`<br>`pantry_lots`<br>`pantry_transactions`<br>`v_pantry_lot_balance`<br>`interactions`<br>`v_current_consents`<br>`idempotency_keys` | `TC-CONT-01`<br>`TC-COOK-08`<br>`TC-COOK-09`<br>`TC-COOK-10`<br>`TC-COOK-11`<br>`TC-COOK-12`<br>`TC-COOK-13`<br>`TC-E2E-01`<br>`TC-E2E-02`<br>`TC-PROP-05`<br>`TC-REL-02`<br>`TC-SEC-02`<br>`TC-SEC-03`<br>`TC-UAT-02` |
| UC21 | Hoàn tác trừ kho | `FR-21-01`<br>`FR-21-02`<br>`FR-21-03`<br>`FR-21-04`<br>`FR-21-05`<br>`FR-21-06`<br>`FR-21-07`<br>`FR-21-08`<br>`FR-21-09` | `POST /cook-sessions/{id}/undo` | `cooking` | `cook_sessions`<br>`meal_plans`<br>`pantry_lots`<br>`pantry_transactions`<br>`v_pantry_lot_balance`<br>`interactions`<br>`v_current_consents` | `TC-CONT-01`<br>`TC-COOK-14`<br>`TC-COOK-15`<br>`TC-COOK-16`<br>`TC-COOK-17`<br>`TC-E2E-02`<br>`TC-PROP-05` |
| UC22 | Xem nhật ký tuần | `FR-22-01`<br>`FR-22-02`<br>`FR-22-03`<br>`FR-22-04`<br>`FR-22-05`<br>`FR-22-06`<br>`FR-22-07`<br>`FR-22-08`<br>`FR-22-09`<br>`FR-22-10`<br>`FR-22-11` | `GET /meal-plans`<br>`GET /journal` | `meal`<br>`journal` | `v_journal_days`<br>`cook_sessions`<br>`meal_plans`<br>`meal_plan_items`<br>`recipes`<br>`pantry_transactions`<br>`user_settings` | `TC-A11Y-02`<br>`TC-CONT-01`<br>`TC-E2E-01`<br>`TC-JRNL-01`<br>`TC-JRNL-02`<br>`TC-JRNL-03`<br>`TC-JRNL-04`<br>`TC-JRNL-05`<br>`TC-JRNL-06`<br>`TC-PERF-04`<br>`TC-SEC-01` |
| UC23 | Tham gia khảo sát gu món ăn | `FR-23-01`<br>`FR-23-02`<br>`FR-23-03`<br>`FR-23-04`<br>`FR-23-05`<br>`FR-23-06`<br>`FR-23-07`<br>`FR-23-08`<br>`FR-23-09`<br>`FR-23-10`<br>`FR-23-11`<br>`FR-23-12`<br>`FR-23-13` | `GET /policies/{purpose}/current`<br>`POST /survey/respondents`<br>`GET /survey/respondents/{id}`<br>`PUT /survey/respondents/{id}/ratings/{recipeId}`<br>`PUT /survey/respondents/{id}/favorites`<br>`POST /survey/respondents/{id}/complete` | `privacy`<br>`survey` | `consent_purposes`<br>`policy_versions`<br>`survey_forms`<br>`survey_form_anchors`<br>`recipes`<br>`survey_respondents`<br>`survey_assignments`<br>`survey_ratings`<br>`survey_favorites` | `TC-CONT-01`<br>`TC-E2E-03`<br>`TC-SEC-07`<br>`TC-SURV-01`<br>`TC-SURV-02`<br>`TC-SURV-03`<br>`TC-SURV-04`<br>`TC-SURV-05` |
| UC24 | Quản lý đợt khảo sát (tạo phiếu, xuất kết quả) | `FR-24-01`<br>`FR-24-02`<br>`FR-24-03`<br>`FR-24-04`<br>`FR-24-05`<br>`FR-24-06`<br>`FR-24-07`<br>`FR-24-08`<br>`FR-24-09`<br>`FR-24-10` | `GET /admin/surveys`<br>`CLI tastoria survey create-form --anchors N --random M`<br>`CLI tastoria survey export <form_version>` | `admin` | `recipes`<br>`survey_forms`<br>`survey_form_anchors`<br>`survey_respondents`<br>`survey_assignments`<br>`survey_ratings`<br>`survey_favorites`<br>`policy_versions`<br>`audit_log` | `TC-CONT-01`<br>`TC-SEC-05`<br>`TC-SURV-06`<br>`TC-SURV-07`<br>`TC-SURV-08`<br>`TC-SURV-09` |
| UC25 | Nhập và kiểm tra kho công thức, nguyên liệu | `FR-25-01`<br>`FR-25-02`<br>`FR-25-03`<br>`FR-25-04`<br>`FR-25-05`<br>`FR-25-06`<br>`FR-25-07`<br>`FR-25-08`<br>`FR-25-09`<br>`FR-25-10`<br>`FR-25-11`<br>`FR-25-12`<br>`FR-25-13`<br>`FR-25-14`<br>`FR-25-15` | `CLI tastoria catalog import <bundle_dir>` | `admin` | `recipes`<br>`recipe_ingredients`<br>`recipe_steps`<br>`recipe_tags`<br>`recipe_sources`<br>`recipe_nutrition`<br>`ingredients`<br>`ingredient_synonyms`<br>`ingredient_allergens`<br>`ingredient_units`<br>`food_items`<br>`food_nutrients`<br>`nutrient_sources`<br>`nutrients`<br>`food_groups`<br>`allergen_groups`<br>`diets`<br>`diet_exclusions`<br>`qty_levels`<br>`cooking_methods`<br>`tags`<br>`audit_log` | `TC-CAT-01`<br>`TC-CAT-02`<br>`TC-CAT-03`<br>`TC-CAT-04`<br>`TC-CAT-05`<br>`TC-CAT-06`<br>`TC-PROP-01` |
| UC26 | Quản lý cặp thay thế nguyên liệu | `FR-26-01`<br>`FR-26-02`<br>`FR-26-03`<br>`FR-26-04`<br>`FR-26-05`<br>`FR-26-06`<br>`FR-26-07`<br>`FR-26-08`<br>`FR-26-09`<br>`FR-26-10` | `CLI tastoria catalog substitutes import <file>` | `admin` | `substitution_pairs`<br>`ingredients`<br>`cooking_methods`<br>`food_groups`<br>`audit_log` | `TC-CAT-07`<br>`TC-CAT-08`<br>`TC-CAT-09` |
| UC27 | Xử lý yêu cầu dữ liệu và xem nhật ký kiểm toán | `FR-27-01`<br>`FR-27-02`<br>`FR-27-03`<br>`FR-27-04`<br>`FR-27-05`<br>`FR-27-06`<br>`FR-27-07`<br>`FR-27-08`<br>`FR-27-09`<br>`FR-27-10`<br>`FR-27-11`<br>`FR-27-12` | `GET /admin/data-requests`<br>`POST /admin/data-requests/{id}/resolve`<br>`GET /admin/audit-log` | `admin` | `dsr_requests`<br>`audit_log`<br>`users`<br>`consent_events`<br>`v_current_consents` | `TC-ADM-01`<br>`TC-ADM-02`<br>`TC-ADM-03`<br>`TC-ADM-04`<br>`TC-ADM-05`<br>`TC-ADM-06`<br>`TC-CONT-01`<br>`TC-SEC-05` |
| UC28 | Xuất dữ liệu huấn luyện đã bí danh hoá | `FR-28-01`<br>`FR-28-02`<br>`FR-28-03`<br>`FR-28-04`<br>`FR-28-05`<br>`FR-28-06`<br>`FR-28-07`<br>`FR-28-08`<br>`FR-28-09`<br>`FR-28-10`<br>`FR-28-11`<br>`FR-28-12` | `CLI tastoria mlops export-training-data --since <date>` | `admin` | `interactions`<br>`meal_plans`<br>`meal_plan_items`<br>`scans`<br>`scan_images`<br>`scan_items`<br>`detections`<br>`v_current_consents`<br>`consent_events`<br>`users`<br>`dsr_requests`<br>`recipes`<br>`ingredients`<br>`vision_classes`<br>`model_versions`<br>`audit_log` | `TC-MLOP-01`<br>`TC-MLOP-02`<br>`TC-MLOP-03`<br>`TC-MLOP-04`<br>`TC-PRIV-23` |
| UC29 | Đăng ký và kiểm định phiên bản mô hình | `FR-29-01`<br>`FR-29-02`<br>`FR-29-03`<br>`FR-29-04`<br>`FR-29-05`<br>`FR-29-06`<br>`FR-29-07`<br>`FR-29-08`<br>`FR-29-09`<br>`FR-29-10`<br>`FR-29-11`<br>`FR-29-12` | `GET /admin/models`<br>`CLI tastoria mlops register <name> <artifact> --metrics <json>`<br>`CLI tastoria mlops gate <name> <version>` | `admin` | `model_versions`<br>`model_version_classes`<br>`model_deployments`<br>`vision_classes`<br>`audit_log` | `TC-CONT-01`<br>`TC-MAINT-03`<br>`TC-MLOP-05`<br>`TC-MLOP-06`<br>`TC-MLOP-07`<br>`TC-MLOP-08`<br>`TC-MLOP-09`<br>`TC-ONNX-01`<br>`TC-ONNX-02`<br>`TC-SEC-05` |
| UC30 | Triển khai và quay lui phiên bản mô hình | `FR-30-01`<br>`FR-30-02`<br>`FR-30-03`<br>`FR-30-04`<br>`FR-30-05`<br>`FR-30-06`<br>`FR-30-07`<br>`FR-30-08`<br>`FR-30-09`<br>`FR-30-10`<br>`FR-30-11` | `GET /admin/models`<br>`CLI tastoria mlops deploy <name> <version>`<br>`CLI tastoria mlops rollback <name>` | `admin` | `model_deployments`<br>`model_versions`<br>`model_version_classes`<br>`scans`<br>`meal_plans`<br>`interactions`<br>`audit_log` | `TC-CONT-01`<br>`TC-MLOP-10`<br>`TC-MLOP-11`<br>`TC-MLOP-12`<br>`TC-MLOP-13`<br>`TC-REL-03`<br>`TC-SCAN-07` |
| UC31 | Gán nhãn ảnh góp | `FR-31-01`<br>`FR-31-02`<br>`FR-31-03`<br>`FR-31-04`<br>`FR-31-05`<br>`FR-31-06`<br>`FR-31-07`<br>`FR-31-08`<br>`FR-31-09`<br>`FR-31-10` | `CLI tastoria labeling push|pull` | `admin` | `scan_images`<br>`scans`<br>`scan_items`<br>`detections`<br>`v_current_consents`<br>`vision_classes`<br>`audit_log` | `TC-LBL-01`<br>`TC-LBL-02`<br>`TC-LBL-03` |
| UC32 | Xoá ảnh quét quá hạn | `FR-32-01`<br>`FR-32-02`<br>`FR-32-03`<br>`FR-32-04`<br>`FR-32-05`<br>`FR-32-06`<br>`FR-32-07`<br>`FR-32-08`<br>`FR-32-09` | `CLI python -m tastoria.jobs.purge_images` | `jobs` | `scan_images`<br>`scans`<br>`v_current_consents`<br>`audit_log` | `TC-JOB-01`<br>`TC-JOB-02`<br>`TC-JOB-03`<br>`TC-PRIV-22` |
| UC33 | Sao lưu cơ sở dữ liệu | `FR-33-01`<br>`FR-33-02`<br>`FR-33-03`<br>`FR-33-04`<br>`FR-33-05`<br>`FR-33-06`<br>`FR-33-07`<br>`FR-33-08`<br>`FR-33-09`<br>`FR-33-10` | `CLI python -m tastoria.jobs.backup` | `jobs` | `idempotency_keys`<br>`users`<br>`refresh_tokens`<br>`password_resets`<br>`consent_purposes`<br>`policy_versions`<br>`consent_events`<br>`dsr_requests`<br>`audit_log`<br>`food_groups`<br>`nutrient_sources`<br>`food_items`<br>`nutrients`<br>`food_nutrients`<br>`allergen_groups`<br>`diets`<br>`diet_exclusions`<br>`ingredients`<br>`ingredient_synonyms`<br>`ingredient_allergens`<br>`ingredient_units`<br>`qty_levels`<br>`cooking_methods`<br>`tags`<br>`recipes`<br>`recipe_ingredients`<br>`recipe_steps`<br>`recipe_tags`<br>`recipe_sources`<br>`recipe_nutrition`<br>`vision_classes`<br>`vision_class_ingredients`<br>`profiles`<br>`user_allergens`<br>`user_favorite_recipes`<br>`user_settings`<br>`pantry_lots`<br>`pantry_transactions`<br>`model_versions`<br>`model_version_classes`<br>`model_deployments`<br>`scans`<br>`scan_images`<br>`scan_items`<br>`detections`<br>`substitution_pairs`<br>`ingredient_embeddings`<br>`shopping_items`<br>`meal_plans`<br>`meal_plan_coeater_allergens`<br>`meal_plan_pins`<br>`meal_plan_items`<br>`meal_plan_item_substitutions`<br>`cook_sessions`<br>`cook_schedule_entries`<br>`interactions`<br>`survey_forms`<br>`survey_form_anchors`<br>`survey_respondents`<br>`survey_assignments`<br>`survey_ratings`<br>`survey_favorites`<br>`v_current_consents`<br>`v_pantry_lot_balance`<br>`v_journal_days` | `TC-JOB-04`<br>`TC-JOB-05`<br>`TC-JOB-06`<br>`TC-PRIV-22`<br>`TC-REL-01` |
| UC34 | Dọn job quét kẹt, token và khoá lũy đẳng hết hạn | `FR-34-01`<br>`FR-34-02`<br>`FR-34-03`<br>`FR-34-04`<br>`FR-34-05`<br>`FR-34-06`<br>`FR-34-07`<br>`FR-34-08`<br>`FR-34-09`<br>`FR-34-10`<br>`FR-34-11`<br>`FR-34-12` | `CLI python -m tastoria.jobs.sweep` | `jobs` | `scans`<br>`idempotency_keys`<br>`refresh_tokens`<br>`password_resets`<br>`audit_log` | `TC-JOB-07`<br>`TC-JOB-08`<br>`TC-JOB-09`<br>`TC-JOB-10`<br>`TC-REL-04` |

## 3. FR → TC

| FR | UC | TC |
|---|---|---|
| FR-01-01 | UC01 | `TC-AUTH-01` |
| FR-01-02 | UC01 | `TC-AUTH-02` |
| FR-01-03 | UC01 | `TC-AUTH-02` |
| FR-01-04 | UC01 | `TC-AUTH-02` |
| FR-01-05 | UC01 | `TC-AUTH-03` |
| FR-01-06 | UC01 | `TC-AUTH-01` |
| FR-01-07 | UC01 | `TC-AUTH-04` |
| FR-01-08 | UC01 | `TC-AUTH-01` |
| FR-02-01 | UC02 | `TC-AUTH-05` |
| FR-02-02 | UC02 | `TC-AUTH-06` |
| FR-02-03 | UC02 | `TC-AUTH-07` |
| FR-02-04 | UC02 | `TC-AUTH-07` |
| FR-02-05 | UC02 | `TC-AUTH-07` |
| FR-02-06 | UC02 | `TC-AUTH-08` |
| FR-02-07 | UC02 | `TC-AUTH-08` |
| FR-02-08 | UC02 | `TC-AUTH-09` |
| FR-02-09 | UC02 | `TC-AUTH-09`<br>`TC-SEC-06` |
| FR-02-10 | UC02 | `TC-AUTH-03` |
| FR-03-01 | UC03 | `TC-AUTH-10` |
| FR-03-02 | UC03 | `TC-AUTH-10` |
| FR-03-03 | UC03 | `TC-AUTH-11` |
| FR-03-04 | UC03 | `TC-AUTH-11` |
| FR-03-05 | UC03 | `TC-AUTH-12` |
| FR-03-06 | UC03 | `TC-AUTH-13` |
| FR-04-01 | UC04 | `TC-AUTH-14` |
| FR-04-02 | UC04 | `TC-AUTH-14` |
| FR-04-03 | UC04 | `TC-AUTH-14` |
| FR-04-04 | UC04 | `TC-AUTH-15` |
| FR-04-05 | UC04 | `TC-AUTH-15` |
| FR-04-06 | UC04 | `TC-AUTH-16` |
| FR-04-07 | UC04 | `TC-AUTH-17` |
| FR-04-08 | UC04 | `TC-AUTH-17` |
| FR-04-09 | UC04 | `TC-AUTH-16` |
| FR-04-10 | UC04 | `TC-AUTH-17` |
| FR-04-11 | UC04 | `TC-AUTH-17` |
| FR-04-12 | UC04 | `TC-AUTH-18` |
| FR-05-01 | UC05 | `TC-PRIV-01` |
| FR-05-02 | UC05 | `TC-PRIV-02` |
| FR-05-03 | UC05 | `TC-PRIV-03` |
| FR-05-04 | UC05 | `TC-PRIV-03` |
| FR-05-05 | UC05 | `TC-PRIV-03` |
| FR-05-06 | UC05 | `TC-PRIV-04` |
| FR-05-07 | UC05 | `TC-PRIV-04` |
| FR-05-08 | UC05 | `TC-PRIV-05` |
| FR-05-09 | UC05 | `TC-PRIV-05` |
| FR-05-10 | UC05 | `TC-PRIV-06` |
| FR-05-11 | UC05 | `TC-PRIV-06` |
| FR-05-12 | UC05 | `TC-PRIV-06` |
| FR-05-13 | UC05 | `TC-PRIV-06` |
| FR-05-14 | UC05 | `TC-PRIV-07` |
| FR-05-15 | UC05 | `TC-PRIV-08` |
| FR-06-01 | UC06 | `TC-PRIV-09` |
| FR-06-02 | UC06 | `TC-PRIV-09` |
| FR-06-03 | UC06 | `TC-PRIV-11` |
| FR-06-04 | UC06 | `TC-PRIV-10` |
| FR-06-05 | UC06 | `TC-PRIV-11` |
| FR-06-06 | UC06 | `TC-PRIV-10` |
| FR-06-07 | UC06 | `TC-PRIV-10` |
| FR-06-08 | UC06 | `TC-PRIV-12`<br>`TC-SEC-01` |
| FR-06-09 | UC06 | `TC-PRIV-12`<br>`TC-SEC-08` |
| FR-06-10 | UC06 | `TC-PRIV-12` |
| FR-06-11 | UC06 | `TC-PRIV-10` |
| FR-06-12 | UC06 | `TC-PRIV-20` |
| FR-07-01 | UC07 | `TC-PRIV-13` |
| FR-07-02 | UC07 | `TC-PRIV-13` |
| FR-07-03 | UC07 | `TC-PRIV-13` |
| FR-07-04 | UC07 | `TC-PRIV-14` |
| FR-07-05 | UC07 | `TC-PRIV-14` |
| FR-07-06 | UC07 | `TC-PRIV-14` |
| FR-07-07 | UC07 | `TC-PRIV-14` |
| FR-07-08 | UC07 | `TC-PRIV-14` |
| FR-07-09 | UC07 | `TC-PRIV-15` |
| FR-07-10 | UC07 | `TC-PRIV-16` |
| FR-08-01 | UC08 | `TC-PRIV-17`<br>`TC-PRIV-21` |
| FR-08-02 | UC08 | `TC-PRIV-17` |
| FR-08-03 | UC08 | `TC-PRIV-17` |
| FR-08-04 | UC08 | `TC-PRIV-18` |
| FR-08-05 | UC08 | `TC-PRIV-19` |
| FR-08-06 | UC08 | `TC-PRIV-19` |
| FR-08-07 | UC08 | `TC-PRIV-19`<br>`TC-SEC-05` |
| FR-08-08 | UC08 | `TC-PRIV-19` |
| FR-08-09 | UC08 | `TC-PRIV-19` |
| FR-08-10 | UC08 | `TC-PRIV-21` |
| FR-08-11 | UC08 | `TC-PRIV-21` |
| FR-09-01 | UC09 | `TC-PROF-01` |
| FR-09-02 | UC09 | `TC-PROF-01` |
| FR-09-03 | UC09 | `TC-PROF-02` |
| FR-09-04 | UC09 | `TC-PROF-03` |
| FR-09-05 | UC09 | `TC-PROF-03` |
| FR-09-06 | UC09 | `TC-PROF-04` |
| FR-09-07 | UC09 | `TC-PROF-05` |
| FR-09-08 | UC09 | `TC-PROF-05` |
| FR-09-09 | UC09 | `TC-PROF-06` |
| FR-09-10 | UC09 | `TC-PROF-06` |
| FR-09-11 | UC09 | `TC-PROF-06` |
| FR-09-12 | UC09 | `TC-PROF-02` |
| FR-09-13 | UC09 | `TC-PROF-03` |
| FR-10-01 | UC10 | `TC-PROF-07` |
| FR-10-02 | UC10 | `TC-PROF-08` |
| FR-10-03 | UC10 | `TC-PROF-03` |
| FR-10-04 | UC10 | `TC-PROF-09` |
| FR-10-05 | UC10 | `TC-PROF-10` |
| FR-10-06 | UC10 | `TC-PROF-10` |
| FR-10-07 | UC10 | `TC-PROF-11` |
| FR-10-08 | UC10 | `TC-PROF-11` |
| FR-10-09 | UC10 | `TC-PROF-12` |
| FR-10-10 | UC10 | `TC-PROF-12` |
| FR-10-11 | UC10 | `TC-PROF-13` |
| FR-10-12 | UC10 | `TC-PROF-13` |
| FR-11-01 | UC11 | `TC-NUT-01` |
| FR-11-02 | UC11 | `TC-NUT-02` |
| FR-11-03 | UC11 | `TC-NUT-03` |
| FR-11-04 | UC11 | `TC-NUT-04` |
| FR-11-05 | UC11 | `TC-NUT-04` |
| FR-11-06 | UC11 | `TC-NUT-05` |
| FR-11-07 | UC11 | `TC-NUT-06` |
| FR-11-08 | UC11 | `TC-NUT-07` |
| FR-11-09 | UC11 | `TC-NUT-08` |
| FR-11-10 | UC11 | `TC-NUT-08` |
| FR-11-11 | UC11 | `TC-NUT-08` |
| FR-11-12 | UC11 | `TC-NUT-09` |
| FR-11-13 | UC11 | `TC-NUT-10` |
| FR-11-14 | UC11 | `TC-NUT-10` |
| FR-11-15 | UC11 | `TC-NUT-06` |
| FR-11-16 | UC11 | `TC-NUT-11` |
| FR-12-01 | UC12 | `TC-SCAN-01` |
| FR-12-02 | UC12 | `TC-SCAN-02`<br>`TC-SEC-04` |
| FR-12-03 | UC12 | `TC-SCAN-02`<br>`TC-SEC-04` |
| FR-12-04 | UC12 | `TC-SCAN-02`<br>`TC-SEC-04` |
| FR-12-05 | UC12 | `TC-SCAN-03`<br>`TC-SEC-04` |
| FR-12-06 | UC12 | `TC-SCAN-04`<br>`TC-SEC-02` |
| FR-12-07 | UC12 | `TC-SCAN-04` |
| FR-12-08 | UC12 | `TC-SCAN-01` |
| FR-12-09 | UC12 | `TC-SCAN-05` |
| FR-12-10 | UC12 | `TC-SCAN-06` |
| FR-12-11 | UC12 | `TC-SCAN-07` |
| FR-12-12 | UC12 | `TC-SCAN-08` |
| FR-12-13 | UC12 | `TC-SCAN-08` |
| FR-12-14 | UC12 | `TC-SCAN-09`<br>`TC-SEC-01` |
| FR-12-15 | UC12 | `TC-SCAN-10` |
| FR-12-16 | UC12 | `TC-SCAN-11` |
| FR-12-17 | UC12 | `TC-SCAN-12` |
| FR-12-18 | UC12 | `TC-SCAN-13` |
| FR-12-19 | UC12 | `TC-SCAN-06` |
| FR-13-01 | UC13 | `TC-SCAN-14` |
| FR-13-02 | UC13 | `TC-SCAN-15` |
| FR-13-03 | UC13 | `TC-SCAN-16` |
| FR-13-04 | UC13 | `TC-SCAN-16` |
| FR-13-05 | UC13 | `TC-SCAN-16` |
| FR-13-06 | UC13 | `TC-SCAN-16` |
| FR-13-07 | UC13 | `TC-SCAN-17` |
| FR-13-08 | UC13 | `TC-SCAN-17` |
| FR-13-09 | UC13 | `TC-SCAN-18` |
| FR-13-10 | UC13 | `TC-SCAN-19` |
| FR-13-11 | UC13 | `TC-SCAN-19` |
| FR-13-12 | UC13 | `TC-SCAN-20` |
| FR-13-13 | UC13 | `TC-SCAN-21` |
| FR-13-14 | UC13 | `TC-SCAN-22` |
| FR-13-15 | UC13 | `TC-SCAN-22` |
| FR-13-16 | UC13 | `TC-SCAN-22` |
| FR-13-17 | UC13 | `TC-SCAN-23` |
| FR-13-18 | UC13 | `TC-SCAN-23` |
| FR-13-19 | UC13 | `TC-SCAN-24` |
| FR-13-20 | UC13 | `TC-SCAN-18` |
| FR-14-01 | UC14 | `TC-PANT-01` |
| FR-14-02 | UC14 | `TC-PANT-02` |
| FR-14-03 | UC14 | `TC-PANT-03` |
| FR-14-04 | UC14 | `TC-PANT-04` |
| FR-14-05 | UC14 | `TC-PANT-04` |
| FR-14-06 | UC14 | `TC-PANT-05` |
| FR-14-07 | UC14 | `TC-PANT-06` |
| FR-14-08 | UC14 | `TC-PANT-07` |
| FR-14-09 | UC14 | `TC-PANT-08` |
| FR-14-10 | UC14 | `TC-PANT-09` |
| FR-14-11 | UC14 | `TC-PANT-10` |
| FR-14-12 | UC14 | `TC-PANT-11` |
| FR-14-13 | UC14 | `TC-PANT-12` |
| FR-14-14 | UC14 | `TC-PANT-13` |
| FR-14-15 | UC14 | `TC-PANT-13` |
| FR-14-16 | UC14 | `TC-PANT-14`<br>`TC-SEC-01` |
| FR-14-17 | UC14 | `TC-PANT-09` |
| FR-14-18 | UC14 | `TC-PANT-15` |
| FR-14-19 | UC14 | `TC-PANT-10` |
| FR-15-01 | UC15 | `TC-MEAL-01` |
| FR-15-02 | UC15 | `TC-MEAL-01` |
| FR-15-03 | UC15 | `TC-MEAL-01` |
| FR-15-04 | UC15 | `TC-MEAL-02`<br>`TC-SEC-02` |
| FR-15-05 | UC15 | `TC-MEAL-02` |
| FR-15-06 | UC15 | `TC-MEAL-03` |
| FR-15-07 | UC15 | `TC-MEAL-04` |
| FR-15-08 | UC15 | `TC-MEAL-04` |
| FR-15-09 | UC15 | `TC-MEAL-05` |
| FR-15-10 | UC15 | `TC-MEAL-06` |
| FR-15-11 | UC15 | `TC-MEAL-07` |
| FR-15-12 | UC15 | `TC-MEAL-08` |
| FR-15-13 | UC15 | `TC-MEAL-09` |
| FR-15-14 | UC15 | `TC-MEAL-10` |
| FR-15-15 | UC15 | `TC-MEAL-10` |
| FR-15-16 | UC15 | `TC-MEAL-11` |
| FR-15-17 | UC15 | `TC-MEAL-12` |
| FR-15-18 | UC15 | `TC-MEAL-12` |
| FR-15-19 | UC15 | `TC-MEAL-13` |
| FR-15-20 | UC15 | `TC-MEAL-13` |
| FR-15-21 | UC15 | `TC-MEAL-14` |
| FR-15-22 | UC15 | `TC-MEAL-15` |
| FR-15-23 | UC15 | `TC-MEAL-16` |
| FR-15-24 | UC15 | `TC-MEAL-17` |
| FR-15-25 | UC15 | `TC-MEAL-18` |
| FR-15-26 | UC15 | `TC-MEAL-19` |
| FR-15-27 | UC15 | `TC-MEAL-20` |
| FR-15-28 | UC15 | `TC-MEAL-21`<br>`TC-SEC-01` |
| FR-15-29 | UC15 | `TC-MEAL-22` |
| FR-15-30 | UC15 | `TC-MEAL-09` |
| FR-15-31 | UC15 | `TC-MEAL-17` |
| FR-15-32 | UC15 | `TC-MEAL-20` |
| FR-15-33 | UC15 | `TC-MEAL-20` |
| FR-15-34 | UC15 | `TC-MEAL-21` |
| FR-15-35 | UC15 | `TC-MEAL-21` |
| FR-15-36 | UC15 | `TC-MEAL-38` |
| FR-15-37 | UC15 | `TC-MEAL-39` |
| FR-15-38 | UC15 | `TC-MEAL-39` |
| FR-15-39 | UC15 | `TC-MEAL-40` |
| FR-15-40 | UC15 | `TC-MEAL-13` |
| FR-15-41 | UC15 | `TC-MEAL-40` |
| FR-16-01 | UC16 | `TC-MEAL-23` |
| FR-16-02 | UC16 | `TC-MEAL-23`<br>`TC-SEC-01` |
| FR-16-03 | UC16 | `TC-MEAL-23` |
| FR-16-04 | UC16 | `TC-MEAL-24`<br>`TC-SEC-02` |
| FR-16-05 | UC16 | `TC-MEAL-25` |
| FR-16-06 | UC16 | `TC-MEAL-25` |
| FR-16-07 | UC16 | `TC-MEAL-26` |
| FR-16-08 | UC16 | `TC-MEAL-26` |
| FR-16-09 | UC16 | `TC-MEAL-26` |
| FR-16-10 | UC16 | `TC-MEAL-27` |
| FR-16-11 | UC16 | `TC-MEAL-27` |
| FR-16-12 | UC16 | `TC-MEAL-28` |
| FR-16-13 | UC16 | `TC-MEAL-28` |
| FR-16-14 | UC16 | `TC-MEAL-29` |
| FR-17-01 | UC17 | `TC-MEAL-30` |
| FR-17-02 | UC17 | `TC-MEAL-30` |
| FR-17-03 | UC17 | `TC-MEAL-31` |
| FR-17-04 | UC17 | `TC-MEAL-31` |
| FR-17-05 | UC17 | `TC-MEAL-31` |
| FR-17-06 | UC17 | `TC-MEAL-32` |
| FR-17-07 | UC17 | `TC-MEAL-33` |
| FR-17-08 | UC17 | `TC-MEAL-34` |
| FR-17-09 | UC17 | `TC-MEAL-34` |
| FR-17-10 | UC17 | `TC-MEAL-32` |
| FR-17-11 | UC17 | `TC-MEAL-35` |
| FR-17-12 | UC17 | `TC-MEAL-35` |
| FR-17-13 | UC17 | `TC-MEAL-36`<br>`TC-SEC-01` |
| FR-17-14 | UC17 | `TC-MEAL-37` |
| FR-18-01 | UC18 | `TC-SHOP-01` |
| FR-18-02 | UC18 | `TC-SHOP-02` |
| FR-18-03 | UC18 | `TC-SHOP-02` |
| FR-18-04 | UC18 | `TC-SHOP-02` |
| FR-18-05 | UC18 | `TC-SHOP-03` |
| FR-18-06 | UC18 | `TC-SHOP-04` |
| FR-18-07 | UC18 | `TC-SHOP-05` |
| FR-18-08 | UC18 | `TC-SHOP-05` |
| FR-18-09 | UC18 | `TC-SEC-01`<br>`TC-SHOP-04` |
| FR-18-10 | UC18 | `TC-SHOP-05` |
| FR-18-11 | UC18 | `TC-SHOP-06` |
| FR-18-12 | UC18 | `TC-SHOP-07` |
| FR-19-01 | UC19 | `TC-COOK-01` |
| FR-19-02 | UC19 | `TC-COOK-01` |
| FR-19-03 | UC19 | `TC-COOK-02`<br>`TC-SEC-02` |
| FR-19-04 | UC19 | `TC-COOK-02` |
| FR-19-05 | UC19 | `TC-COOK-03` |
| FR-19-06 | UC19 | `TC-COOK-03` |
| FR-19-07 | UC19 | `TC-COOK-03` |
| FR-19-08 | UC19 | `TC-COOK-03` |
| FR-19-09 | UC19 | `TC-COOK-03` |
| FR-19-10 | UC19 | `TC-COOK-04` |
| FR-19-11 | UC19 | `TC-COOK-05` |
| FR-19-12 | UC19 | `TC-COOK-06` |
| FR-19-13 | UC19 | `TC-COOK-07` |
| FR-20-01 | UC20 | `TC-COOK-08` |
| FR-20-02 | UC20 | `TC-COOK-08` |
| FR-20-03 | UC20 | `TC-COOK-09`<br>`TC-SEC-02` |
| FR-20-04 | UC20 | `TC-COOK-09`<br>`TC-SEC-02` |
| FR-20-05 | UC20 | `TC-COOK-10` |
| FR-20-06 | UC20 | `TC-COOK-10` |
| FR-20-07 | UC20 | `TC-COOK-11` |
| FR-20-08 | UC20 | `TC-COOK-11` |
| FR-20-09 | UC20 | `TC-COOK-11` |
| FR-20-10 | UC20 | `TC-COOK-12` |
| FR-20-11 | UC20 | `TC-COOK-13` |
| FR-20-12 | UC20 | `TC-COOK-13` |
| FR-20-13 | UC20 | `TC-COOK-13` |
| FR-21-01 | UC21 | `TC-COOK-14` |
| FR-21-02 | UC21 | `TC-COOK-14` |
| FR-21-03 | UC21 | `TC-COOK-15` |
| FR-21-04 | UC21 | `TC-COOK-15` |
| FR-21-05 | UC21 | `TC-COOK-15` |
| FR-21-06 | UC21 | `TC-COOK-16` |
| FR-21-07 | UC21 | `TC-COOK-16` |
| FR-21-08 | UC21 | `TC-COOK-17` |
| FR-21-09 | UC21 | `TC-COOK-17` |
| FR-22-01 | UC22 | `TC-JRNL-01` |
| FR-22-02 | UC22 | `TC-JRNL-01` |
| FR-22-03 | UC22 | `TC-JRNL-02` |
| FR-22-04 | UC22 | `TC-JRNL-02` |
| FR-22-05 | UC22 | `TC-JRNL-02` |
| FR-22-06 | UC22 | `TC-JRNL-03` |
| FR-22-07 | UC22 | `TC-JRNL-04` |
| FR-22-08 | UC22 | `TC-JRNL-01` |
| FR-22-09 | UC22 | `TC-JRNL-05`<br>`TC-SEC-01` |
| FR-22-10 | UC22 | `TC-JRNL-03` |
| FR-22-11 | UC22 | `TC-JRNL-06` |
| FR-23-01 | UC23 | `TC-SURV-01` |
| FR-23-02 | UC23 | `TC-SURV-01` |
| FR-23-03 | UC23 | `TC-SURV-01` |
| FR-23-04 | UC23 | `TC-SURV-01` |
| FR-23-05 | UC23 | `TC-SURV-02` |
| FR-23-06 | UC23 | `TC-SURV-02` |
| FR-23-07 | UC23 | `TC-SURV-02` |
| FR-23-08 | UC23 | `TC-SURV-03` |
| FR-23-09 | UC23 | `TC-SURV-03` |
| FR-23-10 | UC23 | `TC-SURV-03` |
| FR-23-11 | UC23 | `TC-SURV-04` |
| FR-23-12 | UC23 | `TC-SURV-04` |
| FR-23-13 | UC23 | `TC-SURV-05` |
| FR-24-01 | UC24 | `TC-SURV-06` |
| FR-24-02 | UC24 | `TC-SURV-06` |
| FR-24-03 | UC24 | `TC-SURV-06` |
| FR-24-04 | UC24 | `TC-SURV-06` |
| FR-24-05 | UC24 | `TC-SEC-05`<br>`TC-SURV-07` |
| FR-24-06 | UC24 | `TC-SURV-07` |
| FR-24-07 | UC24 | `TC-SURV-08` |
| FR-24-08 | UC24 | `TC-SURV-08` |
| FR-24-09 | UC24 | `TC-SURV-08` |
| FR-24-10 | UC24 | `TC-SURV-09` |
| FR-25-01 | UC25 | `TC-CAT-01` |
| FR-25-02 | UC25 | `TC-CAT-01` |
| FR-25-03 | UC25 | `TC-CAT-01` |
| FR-25-04 | UC25 | `TC-CAT-02` |
| FR-25-05 | UC25 | `TC-CAT-02` |
| FR-25-06 | UC25 | `TC-CAT-03` |
| FR-25-07 | UC25 | `TC-CAT-03` |
| FR-25-08 | UC25 | `TC-CAT-03` |
| FR-25-09 | UC25 | `TC-CAT-04` |
| FR-25-10 | UC25 | `TC-CAT-04` |
| FR-25-11 | UC25 | `TC-CAT-04` |
| FR-25-12 | UC25 | `TC-CAT-05` |
| FR-25-13 | UC25 | `TC-CAT-05` |
| FR-25-14 | UC25 | `TC-CAT-05` |
| FR-25-15 | UC25 | `TC-CAT-06` |
| FR-26-01 | UC26 | `TC-CAT-07` |
| FR-26-02 | UC26 | `TC-CAT-07` |
| FR-26-03 | UC26 | `TC-CAT-08` |
| FR-26-04 | UC26 | `TC-CAT-08` |
| FR-26-05 | UC26 | `TC-CAT-08` |
| FR-26-06 | UC26 | `TC-CAT-08` |
| FR-26-07 | UC26 | `TC-CAT-09` |
| FR-26-08 | UC26 | `TC-CAT-09` |
| FR-26-09 | UC26 | `TC-CAT-09` |
| FR-26-10 | UC26 | `TC-CAT-09` |
| FR-27-01 | UC27 | `TC-ADM-01`<br>`TC-SEC-05` |
| FR-27-02 | UC27 | `TC-ADM-02` |
| FR-27-03 | UC27 | `TC-ADM-02` |
| FR-27-04 | UC27 | `TC-ADM-02` |
| FR-27-05 | UC27 | `TC-ADM-03` |
| FR-27-06 | UC27 | `TC-ADM-03` |
| FR-27-07 | UC27 | `TC-ADM-03` |
| FR-27-08 | UC27 | `TC-ADM-03` |
| FR-27-09 | UC27 | `TC-ADM-04` |
| FR-27-10 | UC27 | `TC-ADM-05` |
| FR-27-11 | UC27 | `TC-ADM-05` |
| FR-27-12 | UC27 | `TC-ADM-06` |
| FR-28-01 | UC28 | `TC-MLOP-01` |
| FR-28-02 | UC28 | `TC-MLOP-01` |
| FR-28-03 | UC28 | `TC-MLOP-01` |
| FR-28-04 | UC28 | `TC-MLOP-02` |
| FR-28-05 | UC28 | `TC-MLOP-02` |
| FR-28-06 | UC28 | `TC-MLOP-02` |
| FR-28-07 | UC28 | `TC-MLOP-03` |
| FR-28-08 | UC28 | `TC-MLOP-03` |
| FR-28-09 | UC28 | `TC-MLOP-03` |
| FR-28-10 | UC28 | `TC-MLOP-04` |
| FR-28-11 | UC28 | `TC-MLOP-04` |
| FR-28-12 | UC28 | `TC-MLOP-04` |
| FR-29-01 | UC29 | `TC-MLOP-05` |
| FR-29-02 | UC29 | `TC-MLOP-05` |
| FR-29-03 | UC29 | `TC-MLOP-05` |
| FR-29-04 | UC29 | `TC-MLOP-06` |
| FR-29-05 | UC29 | `TC-MLOP-06` |
| FR-29-06 | UC29 | `TC-MLOP-07` |
| FR-29-07 | UC29 | `TC-MLOP-07` |
| FR-29-08 | UC29 | `TC-MLOP-08` |
| FR-29-09 | UC29 | `TC-MLOP-08` |
| FR-29-10 | UC29 | `TC-MLOP-08` |
| FR-29-11 | UC29 | `TC-MLOP-08` |
| FR-29-12 | UC29 | `TC-MLOP-09`<br>`TC-SEC-05` |
| FR-30-01 | UC30 | `TC-MLOP-10` |
| FR-30-02 | UC30 | `TC-MLOP-10` |
| FR-30-03 | UC30 | `TC-MLOP-10` |
| FR-30-04 | UC30 | `TC-MLOP-10` |
| FR-30-05 | UC30 | `TC-MLOP-11` |
| FR-30-06 | UC30 | `TC-MLOP-11` |
| FR-30-07 | UC30 | `TC-MLOP-12` |
| FR-30-08 | UC30 | `TC-MLOP-12` |
| FR-30-09 | UC30 | `TC-MLOP-13`<br>`TC-SCAN-07` |
| FR-30-10 | UC30 | `TC-MLOP-13` |
| FR-30-11 | UC30 | `TC-MLOP-11` |
| FR-31-01 | UC31 | `TC-LBL-01` |
| FR-31-02 | UC31 | `TC-LBL-01` |
| FR-31-03 | UC31 | `TC-LBL-01` |
| FR-31-04 | UC31 | `TC-LBL-02` |
| FR-31-05 | UC31 | `TC-LBL-02` |
| FR-31-06 | UC31 | `TC-LBL-02` |
| FR-31-07 | UC31 | `TC-LBL-03` |
| FR-31-08 | UC31 | `TC-LBL-03` |
| FR-31-09 | UC31 | `TC-LBL-03` |
| FR-31-10 | UC31 | `TC-LBL-03` |
| FR-32-01 | UC32 | `TC-JOB-01` |
| FR-32-02 | UC32 | `TC-JOB-01` |
| FR-32-03 | UC32 | `TC-JOB-01` |
| FR-32-04 | UC32 | `TC-JOB-01` |
| FR-32-05 | UC32 | `TC-JOB-02` |
| FR-32-06 | UC32 | `TC-JOB-02` |
| FR-32-07 | UC32 | `TC-JOB-02` |
| FR-32-08 | UC32 | `TC-JOB-03` |
| FR-32-09 | UC32 | `TC-JOB-03` |
| FR-33-01 | UC33 | `TC-JOB-04` |
| FR-33-02 | UC33 | `TC-JOB-04` |
| FR-33-03 | UC33 | `TC-JOB-04` |
| FR-33-04 | UC33 | `TC-JOB-05` |
| FR-33-05 | UC33 | `TC-JOB-05` |
| FR-33-06 | UC33 | `TC-JOB-06` |
| FR-33-07 | UC33 | `TC-JOB-05` |
| FR-33-08 | UC33 | `TC-JOB-06` |
| FR-33-09 | UC33 | `TC-JOB-06` |
| FR-33-10 | UC33 | `TC-JOB-06` |
| FR-34-01 | UC34 | `TC-JOB-07` |
| FR-34-02 | UC34 | `TC-JOB-07` |
| FR-34-03 | UC34 | `TC-JOB-07` |
| FR-34-04 | UC34 | `TC-JOB-08` |
| FR-34-05 | UC34 | `TC-JOB-08` |
| FR-34-06 | UC34 | `TC-JOB-07` |
| FR-34-07 | UC34 | `TC-JOB-09` |
| FR-34-08 | UC34 | `TC-JOB-09` |
| FR-34-09 | UC34 | `TC-JOB-10` |
| FR-34-10 | UC34 | `TC-JOB-10` |
| FR-34-11 | UC34 | `TC-JOB-07`<br>`TC-REL-04` |
| FR-34-12 | UC34 | `TC-JOB-10` |

## 4. BR → UC, TC

| BR | UC | TC |
|---|---|---|
| BR-TRAY-01 | `UC10`<br>`UC15`<br>`UC16`<br>`UC25`<br>`UC26` | `TC-MEAL-01`<br>`TC-MEAL-07`<br>`TC-PROP-03` |
| BR-TRAY-02 | `UC15`<br>`UC17`<br>`UC18`<br>`UC20` | `TC-COOK-10`<br>`TC-MEAL-05`<br>`TC-PROP-03` |
| BR-TRAY-03 | `UC15`<br>`UC16` | `TC-MEAL-14` |
| BR-TRAY-04 | `UC15`<br>`UC16`<br>`UC17` | `TC-MEAL-06`<br>`TC-MEAL-26`<br>`TC-MEAL-30`<br>`TC-PANT-06`<br>`TC-PROP-03` |
| BR-TRAY-05 | `UC15`<br>`UC16`<br>`UC19` | `TC-COOK-04`<br>`TC-MEAL-08`<br>`TC-MEAL-26`<br>`TC-PROP-04` |
| BR-TRAY-06 | `UC15`<br>`UC18` | `TC-MEAL-17` |
| BR-TRAY-07 | `UC15`<br>`UC22` | `TC-JRNL-03`<br>`TC-JRNL-06`<br>`TC-MEAL-13` |
| BR-TRAY-08 | `UC15`<br>`UC16` | `TC-MEAL-01`<br>`TC-MEAL-09`<br>`TC-MEAL-26`<br>`TC-PROP-03` |
| BR-SWAP-01 | `UC16`<br>`UC28` | `TC-MEAL-23`<br>`TC-MEAL-25`<br>`TC-MEAL-28`<br>`TC-PROP-07` |
| BR-ALG-01 | `UC15`<br>`UC16`<br>`UC17`<br>`UC25`<br>`UC26` | `TC-CAT-06`<br>`TC-MEAL-03`<br>`TC-MEAL-22`<br>`TC-MEAL-26`<br>`TC-MEAL-32`<br>`TC-PROP-01` |
| BR-ALG-02 | `UC09`<br>`UC10`<br>`UC25` | `TC-CAT-02`<br>`TC-PROF-06`<br>`TC-PROF-10`<br>`TC-PROP-01` |
| BR-DIET-01 | `UC09`<br>`UC10`<br>`UC15`<br>`UC16`<br>`UC17`<br>`UC25` | `TC-MEAL-04`<br>`TC-MEAL-22`<br>`TC-MEAL-32`<br>`TC-PROF-11`<br>`TC-PROP-02` |
| BR-QTY-01 | `UC13`<br>`UC14`<br>`UC15`<br>`UC17`<br>`UC18`<br>`UC20` | `TC-PANT-08`<br>`TC-PANT-09`<br>`TC-PROP-03`<br>`TC-PROP-05`<br>`TC-SCAN-19` |
| BR-QTY-02 | `UC13`<br>`UC14`<br>`UC15`<br>`UC17`<br>`UC18`<br>`UC20`<br>`UC25` | `TC-CAT-03`<br>`TC-COOK-10`<br>`TC-MEAL-05`<br>`TC-MEAL-34`<br>`TC-SCAN-19` |
| BR-PANTRY-01 | `UC13`<br>`UC14` | `TC-PANT-08`<br>`TC-PROP-05`<br>`TC-SCAN-21`<br>`TC-SCAN-22` |
| BR-PANTRY-02 | `UC20`<br>`UC21` | `TC-COOK-11`<br>`TC-COOK-14`<br>`TC-PROP-05` |
| BR-PANTRY-03 | `UC12`<br>`UC13`<br>`UC14` | `TC-SCAN-13`<br>`TC-SCAN-21`<br>`TC-SCAN-22` |
| BR-SCAN-01 | `UC12` | `TC-SCAN-08` |
| BR-SCAN-02 | `UC13`<br>`UC34` | `TC-REL-02`<br>`TC-SCAN-17`<br>`TC-SCAN-23` |
| BR-FRESH-01 | `UC14`<br>`UC25` | `TC-PANT-02`<br>`TC-PROP-06` |
| BR-FRESH-02 | `UC12`<br>`UC14`<br>`UC29` | `TC-PANT-04`<br>`TC-PROP-06`<br>`TC-SCAN-11` |
| BR-FRESH-03 | `UC14` | `TC-PANT-03`<br>`TC-PROP-06` |
| BR-FRESH-04 | `UC13`<br>`UC14`<br>`UC15`<br>`UC16`<br>`UC17`<br>`UC20`<br>`UC22`<br>`UC29` | `TC-MEAL-11`<br>`TC-MEAL-34`<br>`TC-PANT-04`<br>`TC-PANT-06`<br>`TC-PROP-06`<br>`TC-SCAN-14`<br>`TC-SCAN-18` |
| BR-FRESH-05 | `UC13`<br>`UC14`<br>`UC15`<br>`UC20` | `TC-A11Y-02`<br>`TC-PANT-05`<br>`TC-PANT-07`<br>`TC-PROP-06`<br>`TC-SCAN-15` |
| BR-NUT-01 | `UC09`<br>`UC10`<br>`UC11` | `TC-NUT-01`<br>`TC-NUT-02`<br>`TC-PROF-03`<br>`TC-PROP-08` |
| BR-NUT-02 | `UC09`<br>`UC11` | `TC-NUT-03`<br>`TC-PROP-08` |
| BR-NUT-03 | `UC09`<br>`UC11` | `TC-NUT-04`<br>`TC-NUT-05`<br>`TC-NUT-08`<br>`TC-NUT-09`<br>`TC-PROP-08` |
| BR-NUT-04 | `UC09`<br>`UC11`<br>`UC15` | `TC-JRNL-06`<br>`TC-MEAL-13`<br>`TC-NUT-07`<br>`TC-PROP-08` |
| BR-NUT-05 | `UC17`<br>`UC25` | `TC-CAT-05`<br>`TC-MEAL-35` |
| BR-NUT-06 | `UC15`<br>`UC16`<br>`UC17`<br>`UC22` | `TC-JRNL-03`<br>`TC-MEAL-15` |
| BR-CONSENT-01 | `UC01`<br>`UC05`<br>`UC09`<br>`UC12`<br>`UC23`<br>`UC24`<br>`UC28`<br>`UC31`<br>`UC32` | `TC-PRIV-02`<br>`TC-PRIV-03`<br>`TC-PROF-01`<br>`TC-SCAN-12`<br>`TC-SURV-01` |
| BR-CONSENT-02 | `UC05`<br>`UC09`<br>`UC10`<br>`UC11`<br>`UC15`<br>`UC22` | `TC-MEAL-13`<br>`TC-MEAL-38`<br>`TC-NUT-10`<br>`TC-PROF-03` |
| BR-CONSENT-03 | `UC05`<br>`UC15`<br>`UC16`<br>`UC19`<br>`UC20`<br>`UC21`<br>`UC28` | `TC-COOK-07`<br>`TC-COOK-13`<br>`TC-MEAL-12`<br>`TC-MEAL-19`<br>`TC-MEAL-28`<br>`TC-MLOP-01`<br>`TC-PRIV-23`<br>`TC-SEC-03` |
| BR-CONSENT-04 | `UC05`<br>`UC27`<br>`UC28`<br>`UC31`<br>`UC32` | `TC-ADM-04`<br>`TC-PRIV-05`<br>`TC-PRIV-06` |
| BR-DSR-01 | `UC05`<br>`UC06`<br>`UC07`<br>`UC08`<br>`UC27`<br>`UC28`<br>`UC33` | `TC-ADM-02`<br>`TC-ADM-06`<br>`TC-PRIV-09`<br>`TC-PRIV-14`<br>`TC-PRIV-17`<br>`TC-PRIV-20`<br>`TC-PRIV-21` |
| BR-RETAIN-01 | `UC07`<br>`UC12`<br>`UC28`<br>`UC31`<br>`UC32`<br>`UC33` | `TC-JOB-01`<br>`TC-JOB-05`<br>`TC-PRIV-16`<br>`TC-PRIV-22` |
| BR-COOK-01 | `UC10`<br>`UC15`<br>`UC19`<br>`UC25` | `TC-COOK-03`<br>`TC-PERF-05`<br>`TC-PROP-04` |
| BR-COOK-02 | `UC20`<br>`UC21` | `TC-COOK-08`<br>`TC-COOK-09`<br>`TC-COOK-13`<br>`TC-E2E-02`<br>`TC-REL-02`<br>`TC-SEC-02` |
| BR-CATALOG-01 | `UC07`<br>`UC15`<br>`UC16`<br>`UC19`<br>`UC23`<br>`UC24`<br>`UC25`<br>`UC26` | `TC-CAT-04`<br>`TC-COOK-05`<br>`TC-MEAL-04`<br>`TC-PRIV-14` |

## 5. Độ phủ ngược

### 5.1. Endpoint không UC nào dùng

| Endpoint | Module | TC kiểm |
|---|---|---|
| `GET /healthz` | core | `TC-CONT-01`<br>`TC-MAINT-04`<br>`TC-MLOP-12` |
| `GET /readyz` | core | `TC-CONT-01`<br>`TC-MAINT-04`<br>`TC-MLOP-11`<br>`TC-MLOP-12`<br>`TC-REL-03` |

Endpoint có TC kiểm (ví dụ endpoint vận hành) không tính là ô trống.

### 5.2. Bảng không UC nào dùng

Không có.

### 5.3. BR không UC nào và không TC nào tham chiếu

Không có.

### 5.4. FR chưa có TC

Không có.

### 5.5. UC chưa có FR

Không có.

### 5.6. UC chưa có TC

Không có.
