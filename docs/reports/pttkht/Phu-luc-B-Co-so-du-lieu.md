# PHỤ LỤC B — CẤU TRÚC BẢNG VÀ RÀNG BUỘC

Nguồn: `Tastoria/db/schema.sql`, SHA-256 `d626650dcfb6c604d4707ea16b8af486e1ef9575cfd6bbe5c6e9b2d219638252`. Có 62 bảng trong tệp nguồn. Các migration bổ sung phải đọc cùng khi mô tả DB đã triển khai; phụ lục này không giả định đã truy vấn schema production.


## idempotency_keys

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `user_id` | `uuid NOT NULL` |
| `key` | `text NOT NULL` |
| `request_sha256` | `bytea NOT NULL` |
| `status_code` | `smallint NOT NULL` |
| `response_body` | `jsonb NOT NULL` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_idempotency_keys PRIMARY KEY (user_id, key)`

## users

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `email` | `citext NOT NULL` |
| `password_hash` | `text NOT NULL` |
| `role` | `user_role_t NOT NULL DEFAULT 'user'` |
| `status` | `user_status_t NOT NULL DEFAULT 'active'` |
| `token_version` | `integer NOT NULL DEFAULT 0` |
| `failed_logins` | `smallint NOT NULL DEFAULT 0` |
| `locked_until` | `timestamptz` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_users PRIMARY KEY (id)`
- `CONSTRAINT uq_users_email UNIQUE (email)`
- `CONSTRAINT ck_users_token_version CHECK (token_version >= 0)`
- `CONSTRAINT ck_users_failed_logins CHECK (failed_logins >= 0)`

## refresh_tokens

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `user_id` | `uuid NOT NULL` |
| `family_id` | `uuid NOT NULL` |
| `token_sha256` | `bytea NOT NULL` |
| `issued_at` | `timestamptz NOT NULL` |
| `expires_at` | `timestamptz NOT NULL` |
| `revoked_at` | `timestamptz` |
| `replaced_by_id` | `uuid` |
| `user_agent` | `text` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_refresh_tokens PRIMARY KEY (id)`
- `CONSTRAINT uq_refresh_tokens_token_sha256 UNIQUE (token_sha256)`
- `CONSTRAINT uq_refresh_tokens_replaced_by_id UNIQUE (replaced_by_id)`
- `CONSTRAINT ck_refresh_tokens_expiry CHECK (expires_at > issued_at)`
- `CONSTRAINT ck_refresh_tokens_not_self CHECK (replaced_by_id <> id)`
- `CONSTRAINT fk_refresh_tokens_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_refresh_tokens_replaced_by_id FOREIGN KEY (replaced_by_id) REFERENCES refresh_tokens (id)`

## password_resets

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `user_id` | `uuid NOT NULL` |
| `token_sha256` | `bytea NOT NULL` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |
| `expires_at` | `timestamptz NOT NULL` |
| `used_at` | `timestamptz` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_password_resets PRIMARY KEY (id)`
- `CONSTRAINT uq_password_resets_token_sha256 UNIQUE (token_sha256)`
- `CONSTRAINT ck_password_resets_expiry CHECK (expires_at > created_at)`
- `CONSTRAINT fk_password_resets_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`

## consent_purposes

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `code` | `text NOT NULL` |
| `name_vi` | `text NOT NULL` |
| `description_vi` | `text NOT NULL` |
| `data_category` | `text NOT NULL` |
| `is_sensitive` | `boolean NOT NULL` |
| `is_required` | `boolean NOT NULL DEFAULT false` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_consent_purposes PRIMARY KEY (code)`

## policy_versions

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `purpose_code` | `text NOT NULL` |
| `version` | `text NOT NULL` |
| `text_sha256` | `bytea NOT NULL` |
| `effective_from` | `timestamptz NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_policy_versions PRIMARY KEY (id)`
- `CONSTRAINT uq_policy_versions_purpose_code_version UNIQUE (purpose_code, version)`
- `CONSTRAINT fk_policy_versions_purpose_code FOREIGN KEY (purpose_code) REFERENCES consent_purposes (code)`

## consent_events

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `user_id` | `uuid NOT NULL` |
| `policy_version_id` | `uuid NOT NULL` |
| `action` | `consent_action_t NOT NULL` |
| `channel` | `consent_channel_t NOT NULL` |
| `app_version` | `text` |
| `created_at` | `timestamptz NOT NULL DEFAULT clock_timestamp()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_consent_events PRIMARY KEY (id)`
- `CONSTRAINT fk_consent_events_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_consent_events_policy_version_id FOREIGN KEY (policy_version_id) REFERENCES policy_versions (id)`

## dsr_requests

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `user_id` | `uuid` |
| `subject_ref` | `bytea NOT NULL` |
| `type` | `dsr_type_t NOT NULL` |
| `status` | `dsr_status_t NOT NULL` |
| `received_at` | `timestamptz NOT NULL` |
| `acknowledged_at` | `timestamptz` |
| `completed_at` | `timestamptz` |
| `result_key` | `text` |
| `note` | `text` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_dsr_requests PRIMARY KEY (id)`
- `CONSTRAINT ck_dsr_requests_completed_at CHECK (completed_at IS NULL OR completed_at >= received_at)`
- `CONSTRAINT fk_dsr_requests_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL`

## audit_log

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `bigint GENERATED ALWAYS AS IDENTITY` |
| `actor_user_id` | `uuid` |
| `actor_role` | `text NOT NULL` |
| `action` | `text NOT NULL` |
| `entity` | `text NOT NULL` |
| `entity_id` | `text` |
| `purpose` | `text` |
| `request_id` | `text` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_audit_log PRIMARY KEY (id)`
- `CONSTRAINT fk_audit_log_actor_user_id FOREIGN KEY (actor_user_id) REFERENCES users (id) ON DELETE SET NULL`

## food_groups

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `code` | `text NOT NULL` |
| `name_vi` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_food_groups PRIMARY KEY (code)`

## nutrient_sources

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `smallint NOT NULL` |
| `code` | `text NOT NULL` |
| `name` | `text NOT NULL` |
| `version` | `text NOT NULL` |
| `license` | `text NOT NULL` |
| `url` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_nutrient_sources PRIMARY KEY (id)`
- `CONSTRAINT uq_nutrient_sources_code UNIQUE (code)`

## food_items

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `source_id` | `smallint NOT NULL` |
| `source_code` | `text NOT NULL` |
| `name` | `text NOT NULL` |
| `name_en` | `text` |
| `refuse_pct` | `numeric` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_food_items PRIMARY KEY (source_id, source_code)`
- `CONSTRAINT ck_food_items_refuse_pct CHECK (refuse_pct BETWEEN 0 AND 100)`
- `CONSTRAINT fk_food_items_source_id FOREIGN KEY (source_id) REFERENCES nutrient_sources (id)`

## nutrients

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `code` | `text NOT NULL` |
| `name_vi` | `text NOT NULL` |
| `unit` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_nutrients PRIMARY KEY (code)`

## food_nutrients

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `source_id` | `smallint NOT NULL` |
| `source_code` | `text NOT NULL` |
| `nutrient_code` | `text NOT NULL` |
| `per_100g` | `numeric NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_food_nutrients PRIMARY KEY (source_id, source_code, nutrient_code)`
- `CONSTRAINT ck_food_nutrients_per_100g CHECK (per_100g >= 0)`
- `CONSTRAINT fk_food_nutrients_nutrient_code FOREIGN KEY (nutrient_code) REFERENCES nutrients (code)`
- `CONSTRAINT fk_food_nutrients_source_id_source_code FOREIGN KEY (source_id, source_code) REFERENCES food_items (source_id, source_code)`

## allergen_groups

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `code` | `text NOT NULL` |
| `name_vi` | `text NOT NULL` |
| `name_en` | `text NOT NULL` |
| `basis` | `allergen_basis_t NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_allergen_groups PRIMARY KEY (code)`

## diets

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `code` | `text NOT NULL` |
| `name_vi` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_diets PRIMARY KEY (code)`

## diet_exclusions

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `diet_code` | `text NOT NULL` |
| `food_group_code` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_diet_exclusions PRIMARY KEY (diet_code, food_group_code)`
- `CONSTRAINT fk_diet_exclusions_diet_code FOREIGN KEY (diet_code) REFERENCES diets (code)`
- `CONSTRAINT fk_diet_exclusions_food_group_code FOREIGN KEY (food_group_code) REFERENCES food_groups (code)`

## ingredients

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `name_vi` | `text NOT NULL` |
| `food_group_code` | `text NOT NULL` |
| `comp_source_id` | `smallint` |
| `comp_source_code` | `text` |
| `is_staple` | `boolean NOT NULL DEFAULT false` |
| `countable` | `boolean NOT NULL DEFAULT false` |
| `shelf_life_days` | `numeric` |
| `shelf_life_basis` | `text` |
| `is_active` | `boolean NOT NULL DEFAULT true` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_ingredients PRIMARY KEY (id)`
- `CONSTRAINT ck_ingredients_comp_pair CHECK ((comp_source_id IS NULL) = (comp_source_code IS NULL))`
- `CONSTRAINT ck_ingredients_shelf_life_days CHECK (shelf_life_days > 0)`
- `CONSTRAINT fk_ingredients_food_group_code FOREIGN KEY (food_group_code) REFERENCES food_groups (code)`
- `CONSTRAINT fk_ingredients_comp_source_id_comp_source_code FOREIGN KEY (comp_source_id, comp_source_code) REFERENCES food_items (source_id, source_code)`

## ingredient_synonyms

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `ingredient_id` | `uuid NOT NULL` |
| `synonym` | `text NOT NULL` |
| `lang` | `lang_t NOT NULL` |
| `source` | `text` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_ingredient_synonyms PRIMARY KEY (ingredient_id, synonym, lang)`
- `CONSTRAINT fk_ingredient_synonyms_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`

## ingredient_allergens

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `ingredient_id` | `uuid NOT NULL` |
| `allergen_code` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_ingredient_allergens PRIMARY KEY (ingredient_id, allergen_code)`
- `CONSTRAINT fk_ingredient_allergens_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`
- `CONSTRAINT fk_ingredient_allergens_allergen_code FOREIGN KEY (allergen_code) REFERENCES allergen_groups (code)`

## ingredient_units

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `ingredient_id` | `uuid NOT NULL` |
| `unit_code` | `text NOT NULL` |
| `grams_per_unit` | `numeric NOT NULL` |
| `source` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_ingredient_units PRIMARY KEY (ingredient_id, unit_code)`
- `CONSTRAINT ck_ingredient_units_grams_per_unit CHECK (grams_per_unit > 0)`
- `CONSTRAINT fk_ingredient_units_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`

## qty_levels

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `food_group_code` | `text NOT NULL` |
| `level` | `qty_level_t NOT NULL` |
| `g_min` | `numeric NOT NULL` |
| `g_max` | `numeric NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_qty_levels PRIMARY KEY (food_group_code, level)`
- `CONSTRAINT ck_qty_levels_1 CHECK (g_min <= g_max)`
- `CONSTRAINT ck_qty_levels_g_min CHECK (g_min >= 0)`
- `CONSTRAINT fk_qty_levels_food_group_code FOREIGN KEY (food_group_code) REFERENCES food_groups (code)`

## cooking_methods

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `code` | `text NOT NULL` |
| `name_vi` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_cooking_methods PRIMARY KEY (code)`

## tags

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `code` | `text NOT NULL` |
| `kind` | `tag_kind_t NOT NULL` |
| `name_vi` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_tags PRIMARY KEY (code)`

## recipes

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `name_vi` | `text NOT NULL` |
| `slot` | `slot_t NOT NULL` |
| `servings` | `smallint NOT NULL` |
| `method_code` | `text NOT NULL` |
| `status` | `recipe_status_t NOT NULL DEFAULT 'draft'` |
| `notes` | `text` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_recipes PRIMARY KEY (id)`
- `CONSTRAINT uq_recipes_id_slot UNIQUE (id, slot)`
- `CONSTRAINT ck_recipes_servings CHECK (servings > 0)`
- `CONSTRAINT fk_recipes_method_code FOREIGN KEY (method_code) REFERENCES cooking_methods (code)`

## recipe_ingredients

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `recipe_id` | `uuid NOT NULL` |
| `ingredient_id` | `uuid NOT NULL` |
| `grams` | `numeric NOT NULL` |
| `role` | `ingredient_role_t NOT NULL` |
| `is_optional` | `boolean NOT NULL DEFAULT false` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_recipe_ingredients PRIMARY KEY (recipe_id, ingredient_id)`
- `CONSTRAINT ck_recipe_ingredients_grams CHECK (grams > 0)`
- `CONSTRAINT fk_recipe_ingredients_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`
- `CONSTRAINT fk_recipe_ingredients_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`

## recipe_steps

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `recipe_id` | `uuid NOT NULL` |
| `step_no` | `smallint NOT NULL` |
| `text_vi` | `text NOT NULL` |
| `kind` | `step_kind_t NOT NULL` |
| `minutes` | `smallint NOT NULL` |
| `uses_burner` | `boolean NOT NULL DEFAULT false` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_recipe_steps PRIMARY KEY (recipe_id, step_no)`
- `CONSTRAINT ck_recipe_steps_minutes CHECK (minutes > 0)`
- `CONSTRAINT ck_recipe_steps_step_no CHECK (step_no > 0)`
- `CONSTRAINT fk_recipe_steps_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`

## recipe_tags

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `recipe_id` | `uuid NOT NULL` |
| `tag_code` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_recipe_tags PRIMARY KEY (recipe_id, tag_code)`
- `CONSTRAINT fk_recipe_tags_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`
- `CONSTRAINT fk_recipe_tags_tag_code FOREIGN KEY (tag_code) REFERENCES tags (code)`

## recipe_sources

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `recipe_id` | `uuid NOT NULL` |
| `url` | `text NOT NULL` |
| `title` | `text NOT NULL` |
| `accessed_on` | `date NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_recipe_sources PRIMARY KEY (recipe_id, url)`
- `CONSTRAINT fk_recipe_sources_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`

## recipe_nutrition

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `recipe_id` | `uuid NOT NULL` |
| `nutrient_code` | `text NOT NULL` |
| `per_serving` | `numeric NOT NULL` |
| `computed_at` | `timestamptz NOT NULL` |
| `data_version` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_recipe_nutrition PRIMARY KEY (recipe_id, nutrient_code)`
- `CONSTRAINT ck_recipe_nutrition_per_serving CHECK (per_serving >= 0)`
- `CONSTRAINT fk_recipe_nutrition_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`
- `CONSTRAINT fk_recipe_nutrition_nutrient_code FOREIGN KEY (nutrient_code) REFERENCES nutrients (code)`

## vision_classes

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `smallint NOT NULL` |
| `code` | `text NOT NULL` |
| `name_vi` | `text NOT NULL` |
| `name_en` | `text NOT NULL` |
| `countable` | `boolean NOT NULL` |
| `instance_def` | `instance_def_t NOT NULL` |
| `has_freshness_model` | `boolean NOT NULL DEFAULT false` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_vision_classes PRIMARY KEY (id)`
- `CONSTRAINT uq_vision_classes_code UNIQUE (code)`

## vision_class_ingredients

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `vision_class_id` | `smallint NOT NULL` |
| `ingredient_id` | `uuid NOT NULL` |
| `is_default` | `boolean NOT NULL DEFAULT false` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_vision_class_ingredients PRIMARY KEY (vision_class_id, ingredient_id)`
- `CONSTRAINT fk_vision_class_ingredients_vision_class_id FOREIGN KEY (vision_class_id) REFERENCES vision_classes (id)`
- `CONSTRAINT fk_vision_class_ingredients_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`

## profiles

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `user_id` | `uuid NOT NULL` |
| `sex_enc` | `bytea` |
| `birth_year_enc` | `bytea` |
| `height_cm_enc` | `bytea` |
| `weight_kg_enc` | `bytea` |
| `enc_key_id` | `text` |
| `activity_level` | `activity_level_t` |
| `goal` | `goal_t` |
| `kcal_target` | `integer` |
| `kcal_source` | `kcal_source_t` |
| `diet_code` | `text` |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_profiles PRIMARY KEY (user_id)`
- `CONSTRAINT ck_profiles_kcal_target CHECK (kcal_target BETWEEN 800 AND 5000)`
- `CONSTRAINT ck_profiles_kcal_pair CHECK ((kcal_target IS NULL) = (kcal_source IS NULL))`
- `CONSTRAINT ck_profiles_expert CHECK (kcal_source IS NULL OR (goal IS NOT DISTINCT FROM 'expert') = (kcal_source = 'expert'))`
- `CONSTRAINT ck_profiles_enc_key CHECK (num_nonnulls(sex_enc, birth_year_enc, height_cm_enc, weight_kg_enc) = 0 OR enc_key_id IS NOT NULL)`
- `CONSTRAINT fk_profiles_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_profiles_diet_code FOREIGN KEY (diet_code) REFERENCES diets (code)`

## user_allergens

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `user_id` | `uuid NOT NULL` |
| `allergen_code` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_user_allergens PRIMARY KEY (user_id, allergen_code)`
- `CONSTRAINT fk_user_allergens_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_user_allergens_allergen_code FOREIGN KEY (allergen_code) REFERENCES allergen_groups (code)`

## user_favorite_recipes

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `user_id` | `uuid NOT NULL` |
| `recipe_id` | `uuid NOT NULL` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_user_favorite_recipes PRIMARY KEY (user_id, recipe_id)`
- `CONSTRAINT fk_user_favorite_recipes_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_user_favorite_recipes_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`

## user_settings

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `user_id` | `uuid NOT NULL` |
| `burners` | `smallint NOT NULL DEFAULT 2` |
| `default_persons` | `smallint NOT NULL DEFAULT 2` |
| `timezone` | `text NOT NULL DEFAULT 'Asia/Ho_Chi_Minh'` |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_user_settings PRIMARY KEY (user_id)`
- `CONSTRAINT ck_user_settings_burners CHECK (burners BETWEEN 1 AND 4)`
- `CONSTRAINT ck_user_settings_default_persons CHECK (default_persons BETWEEN 1 AND 6)`
- `CONSTRAINT fk_user_settings_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`

## pantry_lots

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `user_id` | `uuid NOT NULL` |
| `ingredient_id` | `uuid NOT NULL` |
| `initial_g_min` | `numeric NOT NULL` |
| `initial_g_max` | `numeric NOT NULL` |
| `acquired_at` | `timestamptz NOT NULL` |
| `acquired_basis` | `acquired_basis_t NOT NULL` |
| `status` | `lot_status_t NOT NULL DEFAULT 'in_stock'` |
| `p_tuoi` | `real` |
| `p_dung_som` | `real` |
| `p_dung_ngay` | `real` |
| `p_kiem_tra` | `real` |
| `freshness_observed_at` | `timestamptz` |
| `freshness_model_version_id` | `uuid` |
| `user_checked_at` | `timestamptz` |
| `source_scan_item_id` | `uuid` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_pantry_lots PRIMARY KEY (id)`
- `CONSTRAINT ck_pantry_lots_initial_g_min CHECK (initial_g_min >= 0)`
- `CONSTRAINT ck_pantry_lots_1 CHECK (initial_g_min <= initial_g_max)`
- `CONSTRAINT ck_pantry_lots_p_range CHECK (p_tuoi BETWEEN 0 AND 1 AND p_dung_som BETWEEN 0 AND 1 AND p_dung_ngay BETWEEN 0 AND 1 AND p_kiem_tra BETWEEN 0 AND 1)`
- `CONSTRAINT ck_pantry_lots_p_group CHECK (num_nulls(p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra) IN (0, 4))`
- `CONSTRAINT ck_pantry_lots_p_sum CHECK (p_tuoi IS NULL OR abs(p_tuoi + p_dung_som + p_dung_ngay + p_kiem_tra - 1) <= 0.01)`
- `CONSTRAINT ck_pantry_lots_p_observed CHECK (p_tuoi IS NULL OR freshness_observed_at IS NOT NULL)`
- `CONSTRAINT fk_pantry_lots_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_pantry_lots_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`

## pantry_transactions

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `bigint GENERATED ALWAYS AS IDENTITY` |
| `lot_id` | `uuid NOT NULL` |
| `delta_g_min` | `numeric NOT NULL` |
| `delta_g_max` | `numeric NOT NULL` |
| `reason` | `pantry_tx_reason_t NOT NULL` |
| `ref_type` | `pantry_ref_type_t` |
| `ref_id` | `uuid` |
| `reverses_id` | `bigint` |
| `urgency_at_event` | `real` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_pantry_transactions PRIMARY KEY (id)`
- `CONSTRAINT uq_pantry_transactions_reverses_id UNIQUE (reverses_id)`
- `CONSTRAINT ck_pantry_transactions_ref_pair CHECK ((ref_type IS NULL) = (ref_id IS NULL))`
- `CONSTRAINT ck_pantry_transactions_undo CHECK ((reason = 'undo') = (reverses_id IS NOT NULL))`
- `CONSTRAINT ck_pantry_transactions_not_self CHECK (reverses_id <> id)`
- `CONSTRAINT ck_pantry_transactions_urgency CHECK (urgency_at_event >= 0)`
- `CONSTRAINT fk_pantry_transactions_lot_id FOREIGN KEY (lot_id) REFERENCES pantry_lots (id) ON DELETE CASCADE`
- `CONSTRAINT fk_pantry_transactions_reverses_id FOREIGN KEY (reverses_id) REFERENCES pantry_transactions (id)`

## model_versions

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `name` | `model_name_t NOT NULL` |
| `version` | `text NOT NULL` |
| `artifact_key` | `text NOT NULL` |
| `sha256` | `bytea NOT NULL` |
| `preprocess_version` | `text` |
| `metrics` | `jsonb NOT NULL` |
| `gate_report_key` | `text` |
| `mlflow_run_id` | `text` |
| `status` | `model_status_t NOT NULL DEFAULT 'candidate'` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_model_versions PRIMARY KEY (id)`
- `CONSTRAINT uq_model_versions_name_version UNIQUE (name, version)`
- `CONSTRAINT uq_model_versions_id_name UNIQUE (id, name)`

## model_version_classes

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `model_version_id` | `uuid NOT NULL` |
| `class_index` | `smallint NOT NULL` |
| `vision_class_id` | `smallint NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_model_version_classes PRIMARY KEY (model_version_id, class_index)`
- `CONSTRAINT uq_model_version_classes_model_version_id_vision_class_id UNIQUE (model_version_id, vision_class_id)`
- `CONSTRAINT ck_model_version_classes_class_index CHECK (class_index >= 0)`
- `CONSTRAINT fk_model_version_classes_model_version_id FOREIGN KEY (model_version_id) REFERENCES model_versions (id)`
- `CONSTRAINT fk_model_version_classes_vision_class_id FOREIGN KEY (vision_class_id) REFERENCES vision_classes (id)`

## model_deployments

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `name` | `model_name_t NOT NULL` |
| `active_version_id` | `uuid NOT NULL` |
| `previous_version_id` | `uuid` |
| `switched_at` | `timestamptz NOT NULL` |
| `switched_by` | `uuid` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_model_deployments PRIMARY KEY (name)`
- `CONSTRAINT uq_model_deployments_active_version_id UNIQUE (active_version_id)`
- `CONSTRAINT ck_model_deployments_previous CHECK (previous_version_id <> active_version_id)`
- `CONSTRAINT fk_model_deployments_active_version_id_name FOREIGN KEY (active_version_id, name) REFERENCES model_versions (id, name)`
- `CONSTRAINT fk_model_deployments_previous_version_id_name FOREIGN KEY (previous_version_id, name) REFERENCES model_versions (id, name)`
- `CONSTRAINT fk_model_deployments_switched_by FOREIGN KEY (switched_by) REFERENCES users (id) ON DELETE SET NULL`

## scans

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `user_id` | `uuid NOT NULL` |
| `mode` | `scan_mode_t NOT NULL` |
| `status` | `scan_status_t NOT NULL` |
| `error_code` | `text` |
| `attempts` | `smallint NOT NULL DEFAULT 0` |
| `detector_version_id` | `uuid` |
| `classifier_version_id` | `uuid` |
| `preprocess_version` | `text` |
| `enqueued_at` | `timestamptz` |
| `started_at` | `timestamptz` |
| `finished_at` | `timestamptz` |
| `confirmed_at` | `timestamptz` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_scans PRIMARY KEY (id)`
- `CONSTRAINT ck_scans_attempts CHECK (attempts >= 0)`
- `CONSTRAINT ck_scans_confirmed CHECK ((status = 'confirmed') = (confirmed_at IS NOT NULL))`
- `CONSTRAINT fk_scans_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_scans_detector_version_id FOREIGN KEY (detector_version_id) REFERENCES model_versions (id)`
- `CONSTRAINT fk_scans_classifier_version_id FOREIGN KEY (classifier_version_id) REFERENCES model_versions (id)`

## scan_images

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `scan_id` | `uuid NOT NULL` |
| `ordinal` | `smallint NOT NULL` |
| `shelf_group` | `smallint NOT NULL DEFAULT 1` |
| `storage_key` | `text NOT NULL` |
| `width` | `integer NOT NULL` |
| `height` | `integer NOT NULL` |
| `contributed` | `boolean NOT NULL DEFAULT false` |
| `purged_at` | `timestamptz` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_scan_images PRIMARY KEY (id)`
- `CONSTRAINT uq_scan_images_storage_key UNIQUE (storage_key)`
- `CONSTRAINT uq_scan_images_scan_id_ordinal UNIQUE (scan_id, ordinal)`
- `CONSTRAINT ck_scan_images_ordinal CHECK (ordinal BETWEEN 1 AND 2)`
- `CONSTRAINT ck_scan_images_size CHECK (width > 0 AND height > 0)`
- `CONSTRAINT ck_scan_images_shelf_group CHECK (shelf_group >= 1)`
- `CONSTRAINT fk_scan_images_scan_id FOREIGN KEY (scan_id) REFERENCES scans (id) ON DELETE CASCADE`

## scan_items

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `scan_id` | `uuid NOT NULL` |
| `ingredient_id` | `uuid NOT NULL` |
| `origin` | `scan_item_origin_t NOT NULL` |
| `model_count` | `smallint` |
| `final_count` | `smallint` |
| `qty_level` | `qty_level_t` |
| `user_action` | `scan_user_action_t NOT NULL DEFAULT 'kept'` |
| `original_ingredient_id` | `uuid` |
| `user_freshness` | `freshness_t` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_scan_items PRIMARY KEY (id)`
- `CONSTRAINT ck_scan_items_model_count CHECK (model_count >= 0)`
- `CONSTRAINT ck_scan_items_final_count CHECK (final_count BETWEEN 0 AND 99)`
- `CONSTRAINT ck_scan_items_relabeled CHECK (user_action <> 'relabeled' OR original_ingredient_id IS NOT NULL)`
- `CONSTRAINT ck_scan_items_original CHECK (original_ingredient_id IS NULL OR (origin = 'model' AND original_ingredient_id <> ingredient_id))`
- `CONSTRAINT ck_scan_items_user_added CHECK (origin = 'model' OR (model_count IS NULL AND user_action <> 'deleted'))`
- `CONSTRAINT fk_scan_items_scan_id FOREIGN KEY (scan_id) REFERENCES scans (id) ON DELETE CASCADE`
- `CONSTRAINT fk_scan_items_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`
- `CONSTRAINT fk_scan_items_original_ingredient_id FOREIGN KEY (original_ingredient_id) REFERENCES ingredients (id)`

## detections

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `bigint GENERATED ALWAYS AS IDENTITY` |
| `scan_image_id` | `uuid NOT NULL` |
| `scan_item_id` | `uuid` |
| `vision_class_id` | `smallint NOT NULL` |
| `x1` | `real NOT NULL` |
| `y1` | `real NOT NULL` |
| `x2` | `real NOT NULL` |
| `y2` | `real NOT NULL` |
| `confidence` | `real NOT NULL` |
| `p_tuoi` | `real` |
| `p_dung_som` | `real` |
| `p_dung_ngay` | `real` |
| `p_kiem_tra` | `real` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_detections PRIMARY KEY (id)`
- `CONSTRAINT ck_detections_1 CHECK (0 <= x1 AND x1 < x2 AND x2 <= 1 AND 0 <= y1 AND y1 < y2 AND y2 <= 1)`
- `CONSTRAINT ck_detections_confidence CHECK (confidence BETWEEN 0 AND 1)`
- `CONSTRAINT ck_detections_p_range CHECK (p_tuoi BETWEEN 0 AND 1 AND p_dung_som BETWEEN 0 AND 1 AND p_dung_ngay BETWEEN 0 AND 1 AND p_kiem_tra BETWEEN 0 AND 1)`
- `CONSTRAINT ck_detections_p_group CHECK (num_nulls(p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra) IN (0, 4))`
- `CONSTRAINT ck_detections_p_sum CHECK (p_tuoi IS NULL OR abs(p_tuoi + p_dung_som + p_dung_ngay + p_kiem_tra - 1) <= 0.01)`
- `CONSTRAINT fk_detections_scan_image_id FOREIGN KEY (scan_image_id) REFERENCES scan_images (id) ON DELETE CASCADE`
- `CONSTRAINT fk_detections_scan_item_id FOREIGN KEY (scan_item_id) REFERENCES scan_items (id) ON DELETE SET NULL`
- `CONSTRAINT fk_detections_vision_class_id FOREIGN KEY (vision_class_id) REFERENCES vision_classes (id)`

## substitution_pairs

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `ingredient_id` | `uuid NOT NULL` |
| `substitute_id` | `uuid NOT NULL` |
| `context_slot` | `slot_t` |
| `context_method_code` | `text` |
| `ratio` | `numeric NOT NULL DEFAULT 1` |
| `score` | `real NOT NULL` |
| `source` | `text NOT NULL` |
| `curated` | `boolean NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_substitution_pairs PRIMARY KEY (id)`
- `CONSTRAINT uq_substitution_pairs_ctx UNIQUE NULLS NOT DISTINCT (ingredient_id, substitute_id, context_slot, context_method_code)`
- `CONSTRAINT ck_substitution_pairs_1 CHECK (ingredient_id <> substitute_id)`
- `CONSTRAINT ck_substitution_pairs_ratio CHECK (ratio > 0)`
- `CONSTRAINT fk_substitution_pairs_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`
- `CONSTRAINT fk_substitution_pairs_substitute_id FOREIGN KEY (substitute_id) REFERENCES ingredients (id)`
- `CONSTRAINT fk_substitution_pairs_context_method_code FOREIGN KEY (context_method_code) REFERENCES cooking_methods (code)`

## ingredient_embeddings

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `ingredient_id` | `uuid NOT NULL` |
| `model_version_id` | `uuid NOT NULL` |
| `vector` | `vector(100) NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_ingredient_embeddings PRIMARY KEY (ingredient_id, model_version_id)`
- `CONSTRAINT fk_ingredient_embeddings_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`
- `CONSTRAINT fk_ingredient_embeddings_model_version_id FOREIGN KEY (model_version_id) REFERENCES model_versions (id)`

## shopping_items

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `user_id` | `uuid NOT NULL` |
| `ingredient_id` | `uuid NOT NULL` |
| `qty_g` | `numeric` |
| `note` | `text` |
| `status` | `shopping_status_t NOT NULL DEFAULT 'open'` |
| `source_meal_plan_item_id` | `uuid` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_shopping_items PRIMARY KEY (id)`
- `CONSTRAINT ck_shopping_items_qty_g CHECK (qty_g > 0)`
- `CONSTRAINT fk_shopping_items_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_shopping_items_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)`

## meal_plans

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `user_id` | `uuid NOT NULL` |
| `meal` | `meal_t NOT NULL` |
| `persons` | `smallint NOT NULL` |
| `max_minutes` | `smallint NOT NULL` |
| `status` | `meal_plan_status_t NOT NULL DEFAULT 'proposed'` |
| `e_target_kcal` | `numeric` |
| `kcal_low` | `numeric` |
| `kcal_high` | `numeric` |
| `rice_bowls_per_person` | `numeric` |
| `reason_vi` | `text NOT NULL` |
| `ranker_version_id` | `uuid` |
| `params_version` | `text NOT NULL` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |
| `updated_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_meal_plans PRIMARY KEY (id)`
- `CONSTRAINT uq_meal_plans_id_user_id UNIQUE (id, user_id)`
- `CONSTRAINT ck_meal_plans_persons CHECK (persons BETWEEN 1 AND 6)`
- `CONSTRAINT ck_meal_plans_max_minutes CHECK (max_minutes BETWEEN 10 AND 180)`
- `CONSTRAINT ck_meal_plans_e_target_kcal CHECK (e_target_kcal > 0)`
- `CONSTRAINT ck_meal_plans_kcal_pair CHECK ((kcal_low IS NULL) = (kcal_high IS NULL))`
- `CONSTRAINT ck_meal_plans_kcal_range CHECK (kcal_low >= 0 AND kcal_low <= kcal_high)`
- `CONSTRAINT ck_meal_plans_rice_bowls CHECK (rice_bowls_per_person BETWEEN 0.5 AND 3 AND rice_bowls_per_person * 2 = trunc(rice_bowls_per_person * 2))`
- `CONSTRAINT fk_meal_plans_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_meal_plans_ranker_version_id FOREIGN KEY (ranker_version_id) REFERENCES model_versions (id)`

## meal_plan_coeater_allergens

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `meal_plan_id` | `uuid NOT NULL` |
| `allergen_code` | `text NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_meal_plan_coeater_allergens PRIMARY KEY (meal_plan_id, allergen_code)`
- `CONSTRAINT fk_meal_plan_coeater_allergens_meal_plan_id FOREIGN KEY (meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE`
- `CONSTRAINT fk_meal_plan_coeater_allergens_allergen_code FOREIGN KEY (allergen_code) REFERENCES allergen_groups (code)`

## meal_plan_pins

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `meal_plan_id` | `uuid NOT NULL` |
| `lot_id` | `uuid NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_meal_plan_pins PRIMARY KEY (meal_plan_id, lot_id)`
- `CONSTRAINT fk_meal_plan_pins_meal_plan_id FOREIGN KEY (meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE`
- `CONSTRAINT fk_meal_plan_pins_lot_id FOREIGN KEY (lot_id) REFERENCES pantry_lots (id) ON DELETE CASCADE`

## meal_plan_items

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `meal_plan_id` | `uuid NOT NULL` |
| `slot` | `slot_t NOT NULL` |
| `recipe_id` | `uuid NOT NULL` |
| `status` | `plan_item_status_t NOT NULL DEFAULT 'active'` |
| `replaced_item_id` | `uuid` |
| `swap_reason` | `swap_reason_t` |
| `rank_score` | `real NOT NULL` |
| `servings_scale` | `numeric NOT NULL` |
| `kcal_per_person` | `numeric` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_meal_plan_items PRIMARY KEY (id)`
- `CONSTRAINT uq_meal_plan_items_replaced_item_id UNIQUE (replaced_item_id)`
- `CONSTRAINT uq_meal_plan_items_id_meal_plan_id_recipe_id UNIQUE (id, meal_plan_id, recipe_id)`
- `CONSTRAINT ck_meal_plan_items_servings_scale CHECK (servings_scale > 0)`
- `CONSTRAINT ck_meal_plan_items_kcal_per_person CHECK (kcal_per_person >= 0)`
- `CONSTRAINT ck_meal_plan_items_not_self CHECK (replaced_item_id <> id)`
- `CONSTRAINT fk_meal_plan_items_meal_plan_id FOREIGN KEY (meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE`
- `CONSTRAINT fk_meal_plan_items_replaced_item_id FOREIGN KEY (replaced_item_id) REFERENCES meal_plan_items (id)`
- `CONSTRAINT fk_meal_plan_items_recipe_id_slot FOREIGN KEY (recipe_id, slot) REFERENCES recipes (id, slot)`

## meal_plan_item_substitutions

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `item_id` | `uuid NOT NULL` |
| `original_ingredient_id` | `uuid NOT NULL` |
| `substitute_ingredient_id` | `uuid NOT NULL` |
| `grams` | `numeric NOT NULL` |
| `origin` | `substitution_origin_t NOT NULL` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_meal_plan_item_substitutions PRIMARY KEY (item_id, original_ingredient_id)`
- `CONSTRAINT ck_meal_plan_item_substitutions_grams CHECK (grams > 0)`
- `CONSTRAINT ck_meal_plan_item_substitutions_distinct CHECK (original_ingredient_id <> substitute_ingredient_id)`
- `CONSTRAINT fk_meal_plan_item_substitutions_item_id FOREIGN KEY (item_id) REFERENCES meal_plan_items (id) ON DELETE CASCADE`
- `CONSTRAINT fk_meal_plan_item_substitutions_original_ingredient_id FOREIGN KEY (original_ingredient_id) REFERENCES ingredients (id)`
- `CONSTRAINT fk_meal_plan_item_substitutions_substitute_ingredient_id FOREIGN KEY (substitute_ingredient_id) REFERENCES ingredients (id)`

## cook_sessions

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `meal_plan_id` | `uuid NOT NULL` |
| `status` | `cook_status_t NOT NULL DEFAULT 'in_progress'` |
| `serve_at` | `timestamptz NOT NULL` |
| `burners` | `smallint NOT NULL` |
| `started_at` | `timestamptz NOT NULL` |
| `completed_at` | `timestamptz` |
| `reverted_at` | `timestamptz` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_cook_sessions PRIMARY KEY (id)`
- `CONSTRAINT ck_cook_sessions_burners CHECK (burners BETWEEN 1 AND 4)`
- `CONSTRAINT ck_cook_sessions_completed CHECK ((status = 'completed') = (completed_at IS NOT NULL AND reverted_at IS NULL))`
- `CONSTRAINT ck_cook_sessions_reverted CHECK ((status = 'reverted') = (reverted_at IS NOT NULL))`
- `CONSTRAINT ck_cook_sessions_order CHECK (completed_at >= started_at AND reverted_at >= completed_at AND (reverted_at IS NULL OR completed_at IS NOT NULL))`
- `CONSTRAINT fk_cook_sessions_meal_plan_id FOREIGN KEY (meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE`

## cook_schedule_entries

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `cook_session_id` | `uuid NOT NULL` |
| `recipe_id` | `uuid NOT NULL` |
| `step_no` | `smallint NOT NULL` |
| `start_offset_s` | `integer NOT NULL` |
| `end_offset_s` | `integer NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_cook_schedule_entries PRIMARY KEY (cook_session_id, recipe_id, step_no)`
- `CONSTRAINT ck_cook_schedule_entries_1 CHECK (start_offset_s < end_offset_s)`
- `CONSTRAINT ck_cook_schedule_entries_start CHECK (start_offset_s >= 0)`
- `CONSTRAINT fk_cook_schedule_entries_cook_session_id FOREIGN KEY (cook_session_id) REFERENCES cook_sessions (id) ON DELETE CASCADE`
- `CONSTRAINT fk_cook_schedule_entries_recipe_id_step_no FOREIGN KEY (recipe_id, step_no) REFERENCES recipe_steps (recipe_id, step_no)`

## interactions

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL` |
| `user_id` | `uuid NOT NULL` |
| `recipe_id` | `uuid NOT NULL` |
| `meal_plan_id` | `uuid` |
| `meal_plan_item_id` | `uuid` |
| `type` | `interaction_type_t NOT NULL` |
| `position` | `smallint` |
| `swap_reason` | `swap_reason_t` |
| `ranker_version_id` | `uuid` |
| `propensity` | `real` |
| `occurred_at` | `timestamptz NOT NULL` |
| `received_at` | `timestamptz NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_interactions PRIMARY KEY (id)`
- `CONSTRAINT ck_interactions_item_needs_plan CHECK (meal_plan_item_id IS NULL OR meal_plan_id IS NOT NULL)`
- `CONSTRAINT ck_interactions_position CHECK (position >= 0)`
- `CONSTRAINT ck_interactions_propensity CHECK (propensity > 0 AND propensity <= 1)`
- `CONSTRAINT ck_interactions_swap_reason CHECK (swap_reason IS NULL OR type = 'swapped')`
- `CONSTRAINT fk_interactions_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE`
- `CONSTRAINT fk_interactions_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`
- `CONSTRAINT fk_interactions_meal_plan_item_id_meal_plan_id_recipe_id FOREIGN KEY (meal_plan_item_id, meal_plan_id, recipe_id) REFERENCES meal_plan_items (id, meal_plan_id, recipe_id) ON DELETE SET NULL (meal_plan_item_id)`
- `CONSTRAINT fk_interactions_ranker_version_id FOREIGN KEY (ranker_version_id) REFERENCES model_versions (id)`
- `CONSTRAINT fk_interactions_meal_plan_id_user_id FOREIGN KEY (meal_plan_id, user_id) REFERENCES meal_plans (id, user_id) ON DELETE CASCADE`

## survey_forms

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `version` | `text NOT NULL` |
| `n_anchor` | `smallint NOT NULL` |
| `n_random` | `smallint NOT NULL` |
| `is_open` | `boolean NOT NULL DEFAULT false` |
| `created_at` | `timestamptz NOT NULL DEFAULT now()` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_survey_forms PRIMARY KEY (id)`
- `CONSTRAINT uq_survey_forms_version UNIQUE (version)`
- `CONSTRAINT ck_survey_forms_sizes CHECK (n_anchor >= 0 AND n_random >= 0 AND n_anchor + n_random > 0)`

## survey_form_anchors

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `form_id` | `uuid NOT NULL` |
| `recipe_id` | `uuid NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_survey_form_anchors PRIMARY KEY (form_id, recipe_id)`
- `CONSTRAINT fk_survey_form_anchors_form_id FOREIGN KEY (form_id) REFERENCES survey_forms (id)`
- `CONSTRAINT fk_survey_form_anchors_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`

## survey_respondents

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `id` | `uuid NOT NULL DEFAULT gen_random_uuid()` |
| `form_id` | `uuid NOT NULL` |
| `policy_version_id` | `uuid NOT NULL` |
| `consented_at` | `timestamptz NOT NULL` |
| `completed_at` | `timestamptz` |
| `channel` | `survey_channel_t NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_survey_respondents PRIMARY KEY (id)`
- `CONSTRAINT fk_survey_respondents_form_id FOREIGN KEY (form_id) REFERENCES survey_forms (id)`
- `CONSTRAINT fk_survey_respondents_policy_version_id FOREIGN KEY (policy_version_id) REFERENCES policy_versions (id)`

## survey_assignments

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `respondent_id` | `uuid NOT NULL` |
| `recipe_id` | `uuid NOT NULL` |
| `display_order` | `smallint NOT NULL` |
| `is_anchor` | `boolean NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_survey_assignments PRIMARY KEY (respondent_id, recipe_id)`
- `CONSTRAINT uq_survey_assignments_respondent_id_display_order UNIQUE (respondent_id, display_order)`
- `CONSTRAINT ck_survey_assignments_display_order CHECK (display_order >= 1)`
- `CONSTRAINT fk_survey_assignments_respondent_id FOREIGN KEY (respondent_id) REFERENCES survey_respondents (id) ON DELETE CASCADE`
- `CONSTRAINT fk_survey_assignments_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`

## survey_ratings

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `respondent_id` | `uuid NOT NULL` |
| `recipe_id` | `uuid NOT NULL` |
| `rating` | `smallint` |
| `never_eaten` | `boolean NOT NULL DEFAULT false` |
| `answered_at` | `timestamptz NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_survey_ratings PRIMARY KEY (respondent_id, recipe_id)`
- `CONSTRAINT ck_survey_ratings_rating CHECK (rating BETWEEN 1 AND 5)`
- `CONSTRAINT ck_survey_ratings_1 CHECK ((rating IS NULL) = never_eaten)`
- `CONSTRAINT fk_survey_ratings_respondent_id_recipe_id FOREIGN KEY (respondent_id, recipe_id) REFERENCES survey_assignments (respondent_id, recipe_id) ON DELETE CASCADE`

## survey_favorites

| Cột | Kiểu và ràng buộc khai báo |
|---|---|
| `respondent_id` | `uuid NOT NULL` |
| `recipe_id` | `uuid NOT NULL` |

**Ràng buộc đặt tên trong CREATE TABLE:**

- `CONSTRAINT pk_survey_favorites PRIMARY KEY (respondent_id, recipe_id)`
- `CONSTRAINT fk_survey_favorites_respondent_id FOREIGN KEY (respondent_id) REFERENCES survey_respondents (id) ON DELETE CASCADE`
- `CONSTRAINT fk_survey_favorites_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)`

## Ràng buộc bổ sung, index và view

Cạnh FK phát sinh từ ALTER TABLE và index không được bỏ qua khi nghiệm thu mô hình. DDL đầy đủ đi kèm trong evidence/schema-source.sql; một số ràng buộc chỉ có ở migration mới.

```sql
ALTER TABLE ở cuối tệp.
-- Bất biến mà chuẩn hoá dựa vào (docs/sad/04-chuan-hoa.md mục 4) được ép trong CSDL, không chỉ ở service:
--   * trigger trg_append_only: consent_events, audit_log, pantry_transactions, interactions chỉ ghi thêm;
```

```sql
ALTER TABLE idempotency_keys ADD CONSTRAINT fk_idempotency_keys_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;
```

```sql
ALTER TABLE pantry_lots ADD CONSTRAINT fk_pantry_lots_freshness_model_version_id FOREIGN KEY (freshness_model_version_id) REFERENCES model_versions (id);
```

```sql
ALTER TABLE pantry_lots ADD CONSTRAINT fk_pantry_lots_source_scan_item_id FOREIGN KEY (source_scan_item_id) REFERENCES scan_items (id) ON DELETE SET NULL;
```

```sql
ALTER TABLE shopping_items ADD CONSTRAINT fk_shopping_items_source_meal_plan_item_id FOREIGN KEY (source_meal_plan_item_id) REFERENCES meal_plan_items (id) ON DELETE SET NULL;
```

```sql
CREATE UNIQUE INDEX ux_meal_plan_items_active_slot ON meal_plan_items (meal_plan_id, slot) WHERE status = 'active';
```

```sql
CREATE UNIQUE INDEX ux_recipes_name_vi_live ON recipes (name_vi) WHERE status <> 'retired';
```

```sql
CREATE UNIQUE INDEX ux_ingredients_name_vi_active ON ingredients (name_vi) WHERE is_active;
```

```sql
CREATE UNIQUE INDEX ux_vision_class_ingredients_default ON vision_class_ingredients (vision_class_id) WHERE is_default;
```

```sql
CREATE UNIQUE INDEX ux_cook_sessions_one_live ON cook_sessions (meal_plan_id) WHERE status IN ('in_progress', 'completed');
```

```sql
CREATE INDEX ix_recipe_ingredients_ingredient_id ON recipe_ingredients (ingredient_id);
```

```sql
CREATE INDEX ix_ingredient_allergens_allergen_code ON ingredient_allergens (allergen_code);
```

```sql
CREATE INDEX ix_pantry_lots_user_id_status ON pantry_lots (user_id, status);
```

```sql
CREATE INDEX ix_pantry_transactions_lot_id ON pantry_transactions (lot_id);
```

```sql
CREATE INDEX ix_interactions_user_id_occurred_at ON interactions (user_id, occurred_at DESC);
```

```sql
CREATE INDEX ix_meal_plans_user_id_created_at ON meal_plans (user_id, created_at DESC);
```

```sql
CREATE INDEX ix_meal_plan_items_meal_plan_id ON meal_plan_items (meal_plan_id);
```

```sql
CREATE INDEX ix_scans_user_id_created_at ON scans (user_id, created_at DESC);
```

```sql
CREATE INDEX ix_scan_items_scan_id ON scan_items (scan_id);
```

```sql
CREATE INDEX ix_detections_scan_image_id ON detections (scan_image_id);
```

```sql
CREATE INDEX ix_consent_events_user_id_created_at ON consent_events (user_id, created_at DESC);
```

```sql
CREATE INDEX ix_dsr_requests_status_received_at ON dsr_requests (status, received_at);
```

```sql
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
```

```sql
CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);
```

```sql
CREATE INDEX ix_shopping_items_user_id_status ON shopping_items (user_id, status);
```

```sql
CREATE INDEX ix_audit_log_created_at ON audit_log (created_at);
```

```sql
CREATE INDEX ix_cook_sessions_meal_plan_id ON cook_sessions (meal_plan_id);
```

```sql
CREATE INDEX ix_survey_ratings_recipe_id ON survey_ratings (recipe_id);
```

```sql
CREATE INDEX ix_pantry_transactions_ref ON pantry_transactions (ref_type, ref_id);
```

```sql
CREATE INDEX ix_audit_log_actor_user_id ON audit_log (actor_user_id);
```

```sql
CREATE INDEX ix_dsr_requests_user_id ON dsr_requests (user_id);
```

```sql
CREATE INDEX ix_password_resets_user_id ON password_resets (user_id);
```

```sql
CREATE INDEX ix_detections_scan_item_id ON detections (scan_item_id);
```

```sql
CREATE INDEX ix_pantry_lots_source_scan_item_id ON pantry_lots (source_scan_item_id);
```

```sql
CREATE INDEX ix_meal_plan_pins_lot_id ON meal_plan_pins (lot_id);
```

```sql
CREATE INDEX ix_shopping_items_source_meal_plan_item_id ON shopping_items (source_meal_plan_item_id);
```

```sql
CREATE INDEX ix_interactions_meal_plan_item_id ON interactions (meal_plan_item_id);
```

```sql
CREATE INDEX ix_interactions_meal_plan_id_user_id ON interactions (meal_plan_id, user_id);
```

```sql
CREATE INDEX ix_idempotency_keys_created_at ON idempotency_keys (created_at);
```

```sql
CREATE INDEX ix_refresh_tokens_expires_at ON refresh_tokens (expires_at);
```

```sql
CREATE INDEX ix_password_resets_expires_at ON password_resets (expires_at);
```

```sql
CREATE INDEX ix_scans_stuck ON scans (started_at) WHERE status IN ('queued', 'processing');
```

```sql
CREATE INDEX ix_scan_images_purge ON scan_images (scan_id) WHERE purged_at IS NULL AND NOT contributed;
```

```sql
CREATE VIEW v_current_consents AS
SELECT DISTINCT ON (ce.user_id, pv.purpose_code)
       ce.user_id,
       pv.purpose_code,
       ce.action,
       (ce.action = 'grant') AS is_granted,
       ce.policy_version_id,
       pv.version AS policy_version,
       (pv.id = (SELECT p2.id
                   FROM policy_versions p2
                  WHERE p2.purpose_code = pv.purpose_code
                    AND p2.effective_from <= now()
                  ORDER BY p2.effective_from DESC
                  LIMIT 1)) AS on_current_policy,
       ce.channel,
       ce.created_at AS decided_at
  FROM consent_events ce
  JOIN policy_versions pv ON pv.id = ce.policy_version_id
 ORDER BY ce.user_id, pv.purpose_code, ce.created_at DESC, ce.id DESC;
```

```sql
CREATE VIEW v_pantry_lot_balance AS
SELECT l.id AS lot_id,
       l.user_id,
       l.ingredient_id,
       l.status,
       l.acquired_at,
       GREATEST(0, l.initial_g_min + t.sum_min) AS g_min,
       GREATEST(0, l.initial_g_max + t.sum_max) AS g_max,
       t.n AS n_transactions
  FROM pantry_lots l
 CROSS JOIN LATERAL (SELECT COALESCE(sum(x.delta_g_min), 0) AS sum_min,
                            COALESCE(sum(x.delta_g_max), 0) AS sum_max,
                            count(*) AS n
                       FROM pantry_transactions x
                      WHERE x.lot_id = l.id) t;
```

```sql
CREATE VIEW v_journal_days AS
SELECT d.user_id,
       d.local_date,
       d.cooked_sessions,
       d.kcal_dishes_per_person,
       d.rice_bowls_per_person,
       d.kcal_dishes_per_person + COALESCE(d.rice_bowls_per_person, 0) * app_param('rice_bowl_kcal') AS kcal_per_person,
       d.e_target_kcal,
       COALESCE(u.urgent_lots_used, 0) AS urgent_lots_used
  FROM (SELECT mp.user_id,
               (cs.completed_at AT TIME ZONE COALESCE(us.timezone, 'Asia/Ho_Chi_Minh'))::date AS local_date,
               count(*) AS cooked_sessions,
               sum(k.kcal) AS kcal_dishes_per_person,
               sum(mp.rice_bowls_per_person) AS rice_bowls_per_person,
               sum(mp.e_target_kcal) AS e_target_kcal
          FROM cook_sessions cs
          JOIN meal_plans mp ON mp.id = cs.meal_plan_id
          LEFT JOIN user_settings us ON us.user_id = mp.user_id
          LEFT JOIN LATERAL (SELECT sum(i.kcal_per_person) AS kcal
                               FROM meal_plan_items i
                              WHERE i.meal_plan_id = mp.id
                                AND i.status = 'active') k ON true
         WHERE cs.status = 'completed'
         GROUP BY 1, 2) d
  LEFT JOIN (SELECT mp.user_id,
                    (cs.completed_at AT TIME ZONE COALESCE(us.timezone, 'Asia/Ho_Chi_Minh'))::date AS local_date,
                    count(DISTINCT t.lot_id) AS urgent_lots_used
               FROM cook_sessions cs
               JOIN meal_plans mp ON mp.id = cs.meal_plan_id
               LEFT JOIN user_settings us ON us.user_id = mp.user_id
               JOIN pantry_transactions t
                 ON t.ref_type = 'cook_session'
                AND t.ref_id = cs.id
                AND t.reason = 'cook_deduct'
                AND t.urgency_at_event BETWEEN app_param('fresh_u_soon') AND app_param('fresh_u_check')
              WHERE cs.status = 'completed'
              GROUP BY 1, 2) u
    ON u.user_id = d.user_id AND u.local_date = d.local_date;
```
