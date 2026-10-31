# Ma trận truy vết 34 UC

Nguồn: metadata của từng đặc tả UC trong Tastoria. Đây là ánh xạ yêu cầu, không phải kết quả test.

| UC | Phân hệ | Tác nhân | Endpoint / lệnh theo đặc tả | Dữ liệu chính |
|---|---|---|---|---|
| UC01 | PK1 | A01 | POST /auth/register | users, refresh_tokens, consent_events |
| UC02 | PK1 | A01 | POST /auth/login; POST /auth/refresh | users, refresh_tokens |
| UC03 | PK1 | A02 | POST /auth/logout; POST /auth/logout-all | users, refresh_tokens |
| UC04 | PK1 | A01 | POST /auth/password-reset/request; POST /auth/password-reset/confirm | users, password_resets, refresh_tokens |
| UC05 | PK2 | A02 | GET /policies/{purpose}/current; GET /me/consents; POST /me/consents; POST /me/consents/{purpose}/withdraw | consent_purposes, policy_versions, consent_events, v_current_consents, users, dsr_requests, profiles |
| UC06 | PK2 | A02 | POST /me/data-requests; GET /me/data-requests/{id}; GET /me/data-requests/{id}/download | dsr_requests, audit_log, users, refresh_tokens, consent_events, v_current_consents, profiles |
| UC07 | PK2 | A02 | POST /me/data-requests; GET /me/data-requests/{id} | dsr_requests, users, refresh_tokens, password_resets, idempotency_keys, consent_events, audit_log |
| UC08 | PK2 | A02 | POST /me/data-requests; GET /me/data-requests/{id}; POST /admin/data-requests/{id}/resolve | dsr_requests, audit_log, users |
| UC09 | PK3 | A02 | GET /policies/{purpose}/current; POST /me/consents; PUT /me/profile; POST /me/energy-suggestion; PUT /me/energy-target; PUT /me/allergens; PUT /me/diet; PUT /me/favorites; GET /reference; GET /recipes | consent_purposes, policy_versions, consent_events, v_current_consents, profiles, user_allergens, user_favorite_recipes |
| UC10 | PK3 | A02 | GET /me/profile; PUT /me/profile; PUT /me/allergens; PUT /me/diet; PUT /me/favorites; GET /me/settings; PUT /me/settings; GET /reference | profiles, user_allergens, user_favorite_recipes, user_settings, allergen_groups, diets, diet_exclusions |
| UC11 | PK3 | A02 | POST /me/energy-suggestion; PUT /me/energy-target | profiles, v_current_consents, audit_log |
| UC12 | PK4 | A02 | POST /scans; GET /scans/{id} | scans, scan_images, scan_items, detections, idempotency_keys, model_deployments, model_versions |
| UC13 | PK4 | A02 | GET /scans/{id}; GET /scans/{id}/images/{ordinal}; POST /scans/{id}/items; PATCH /scans/{id}/items/{itemId}; DELETE /scans/{id}/items/{itemId}; POST /scans/{id}/confirm; POST /scans/{id}/discard; GET /ingredients | scans, scan_images, scan_items, detections, ingredients, ingredient_synonyms, ingredient_units |
| UC14 | PK4 | A02 | GET /pantry/lots; POST /pantry/lots; PATCH /pantry/lots/{id}; POST /pantry/lots/{id}/discard; GET /ingredients | pantry_lots, pantry_transactions, v_pantry_lot_balance, ingredients, ingredient_synonyms, ingredient_units, qty_levels |
| UC15 | PK5 | A02 | POST /meal-plans; GET /meal-plans/latest; GET /meal-plans/{id}; POST /meal-plans/{id}/accept; GET /pantry/lots; GET /reference; GET /recipes; GET /recipes/{id}; POST /events | meal_plans, meal_plan_items, meal_plan_coeater_allergens, meal_plan_pins, meal_plan_item_substitutions, idempotency_keys, profiles |
| UC16 | PK5 | A02 | POST /meal-plans/{id}/items/{itemId}/swap; POST /events | meal_plans, meal_plan_items, meal_plan_coeater_allergens, meal_plan_pins, meal_plan_item_substitutions, idempotency_keys, profiles |
| UC17 | PK5 | A02 | GET /meal-plans/{id}/items/{itemId}/substitutes; POST /meal-plans/{id}/items/{itemId}/substitutions; POST /shopping-items | meal_plans, meal_plan_items, meal_plan_coeater_allergens, meal_plan_item_substitutions, profiles, user_allergens, diet_exclusions |
| UC18 | PK5 | A02 | GET /shopping-items; POST /shopping-items; PATCH /shopping-items/{id}; GET /ingredients | shopping_items, ingredients, ingredient_synonyms, ingredient_units, food_groups, meal_plan_items, meal_plans |
| UC19 | PK6 | A02 | POST /cook-sessions; GET /cook-sessions/{id}; POST /cook-sessions/{id}/abandon; GET /recipes/{id}; GET /catalog/snapshot; POST /events | meal_plans, meal_plan_items, meal_plan_item_substitutions, recipes, recipe_steps, recipe_ingredients, cooking_methods |
| UC20 | PK6 | A02 | POST /cook-sessions/{id}/complete; POST /events | cook_sessions, meal_plans, meal_plan_items, meal_plan_item_substitutions, recipe_ingredients, ingredients, ingredient_units |
| UC21 | PK6 | A02 | POST /cook-sessions/{id}/undo | cook_sessions, meal_plans, pantry_lots, pantry_transactions, v_pantry_lot_balance, interactions, v_current_consents |
| UC22 | PK6 | A02 | GET /journal; GET /meal-plans | v_journal_days, cook_sessions, meal_plans, meal_plan_items, recipes, pantry_transactions, user_settings |
| UC23 | PK7 | A03 | GET /policies/{purpose}/current; POST /survey/respondents; GET /survey/respondents/{id}; PUT /survey/respondents/{id}/ratings/{recipeId}; PUT /survey/respondents/{id}/favorites; POST /survey/respondents/{id}/complete | consent_purposes, policy_versions, survey_forms, survey_form_anchors, recipes, survey_respondents, survey_assignments |
| UC24 | PK7 | A06 | CLI tastoria survey create-form --anchors N --random M; CLI tastoria survey export <form_version>; GET /admin/surveys | recipes, survey_forms, survey_form_anchors, survey_respondents, survey_assignments, survey_ratings, survey_favorites |
| UC25 | PK8 | A05 | CLI tastoria catalog import <bundle_dir> | recipes, recipe_ingredients, recipe_steps, recipe_tags, recipe_sources, recipe_nutrition, ingredients |
| UC26 | PK8 | A05 | CLI tastoria catalog substitutes import <file> | substitution_pairs, ingredients, cooking_methods, food_groups, audit_log |
| UC27 | PK8 | A04 | GET /admin/data-requests; POST /admin/data-requests/{id}/resolve; GET /admin/audit-log | dsr_requests, audit_log, users, consent_events, v_current_consents |
| UC28 | PK9 | A06 | CLI tastoria mlops export-training-data --since <date> | interactions, meal_plans, meal_plan_items, scans, scan_images, scan_items, detections |
| UC29 | PK9 | A06 | CLI tastoria mlops register <name> <artifact> --metrics <json>; CLI tastoria mlops gate <name> <version>; GET /admin/models | model_versions, model_version_classes, model_deployments, vision_classes, audit_log |
| UC30 | PK9 | A06 | CLI tastoria mlops deploy <name> <version>; CLI tastoria mlops rollback <name>; GET /admin/models | model_deployments, model_versions, model_version_classes, scans, meal_plans, interactions, audit_log |
| UC31 | PK9 | A07 | CLI tastoria labeling push\|pull | scan_images, scans, scan_items, detections, v_current_consents, vision_classes, audit_log |
| UC32 | PK10 | A08 | CLI python -m tastoria.jobs.purge_images | scan_images, scans, v_current_consents, audit_log |
| UC33 | PK10 | A08 | CLI python -m tastoria.jobs.backup | idempotency_keys, users, refresh_tokens, password_resets, consent_purposes, policy_versions, consent_events |
| UC34 | PK10 | A08 | CLI python -m tastoria.jobs.sweep | scans, idempotency_keys, refresh_tokens, password_resets, audit_log |
