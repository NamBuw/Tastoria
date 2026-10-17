-- Tastoria — lược đồ CSDL bản cho Visual Paradigm (Tools > DB > Reverse DDL).
-- Sinh từ db/schema.sql bằng script (không sửa tay). Khác bản chuẩn:
--   không extension, không CREATE TYPE (enum -> text + CHECK IN), vector -> bytea, citext -> text,
--   identity -> bigserial, không view, không hàm/trigger, không chỉ mục một phần, UNIQUE không có NULLS NOT DISTINCT,
--   chú thích cắt còn <= 250 ký tự, bỏ chú thích ràng buộc/chỉ mục/trigger. Áp được trên PostgreSQL thuần.
-- Ràng buộc bị lược hoặc yếu đi so với bản chuẩn (vẫn có đủ trong db/schema.sql):
--   uq_substitution_pairs_ctx: UNIQUE NULLS NOT DISTINCT (ingredient_id, substitute_id, context_slot, context_method_code) — bản VP là UNIQUE thường, nên hai dòng cùng cặp nguyên liệu với context NULL không còn bị chặn trùng.
--   fk_interactions_meal_plan_item_id_meal_plan_id_recipe_id: ON DELETE SET NULL (meal_plan_item_id) — bản VP ghi ON DELETE SET NULL cho mọi cột của khoá ghép.
--   ux_meal_plan_items_active_slot: UNIQUE meal_plan_items (meal_plan_id, slot) WHERE status = 'active'
--   ux_recipes_name_vi_live: UNIQUE recipes (name_vi) WHERE status <> 'retired'
--   ux_ingredients_name_vi_active: UNIQUE ingredients (name_vi) WHERE is_active
--   ux_vision_class_ingredients_default: UNIQUE vision_class_ingredients (vision_class_id) WHERE is_default
--   ux_cook_sessions_one_live: UNIQUE cook_sessions (meal_plan_id) WHERE status IN ('in_progress', 'completed')
--   ix_scans_stuck: chỉ mục một phần scans (started_at) WHERE status IN ('queued', 'processing')
--   ix_scan_images_purge: chỉ mục một phần scan_images (scan_id) WHERE purged_at IS NULL AND NOT contributed
--   Mọi trigger bảo vệ bất biến (trg_append_only, trg_write_once, trg_recipes_guard, trg_recipe_children_guard,
--   trg_survey_form_anchors_guard, trg_meal_plans_guard, trg_meal_plan_items_guard,
--   trg_meal_plan_item_substitutions_guard, trg_pantry_transactions_ref, trg_dsr_requests_guard,
--   trg_user_settings_timezone): xem docs/sad/04-chuan-hoa.md mục 4.

BEGIN;

-- ===================== Module core =====================

CREATE TABLE idempotency_keys (
    user_id uuid NOT NULL,
    key text NOT NULL,
    request_sha256 bytea NOT NULL,
    status_code smallint NOT NULL,
    response_body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_idempotency_keys PRIMARY KEY (user_id, key)
);

-- ===================== Module identity =====================

CREATE TABLE users (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    email text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL DEFAULT 'user',
    status text NOT NULL DEFAULT 'active',
    token_version integer NOT NULL DEFAULT 0,
    failed_logins smallint NOT NULL DEFAULT 0,
    locked_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT ck_users_token_version CHECK (token_version >= 0),
    CONSTRAINT ck_users_failed_logins CHECK (failed_logins >= 0),
    CONSTRAINT ck_users_role_enum CHECK (role IN ('user', 'admin', 'curator', 'ml_operator')),
    CONSTRAINT ck_users_status_enum CHECK (status IN ('active', 'deletion_requested'))
);

CREATE TABLE refresh_tokens (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    family_id uuid NOT NULL,
    token_sha256 bytea NOT NULL,
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    replaced_by_id uuid,
    user_agent text,
    CONSTRAINT pk_refresh_tokens PRIMARY KEY (id),
    CONSTRAINT uq_refresh_tokens_token_sha256 UNIQUE (token_sha256),
    CONSTRAINT uq_refresh_tokens_replaced_by_id UNIQUE (replaced_by_id),
    CONSTRAINT ck_refresh_tokens_expiry CHECK (expires_at > issued_at),
    CONSTRAINT ck_refresh_tokens_not_self CHECK (replaced_by_id <> id),
    CONSTRAINT fk_refresh_tokens_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_refresh_tokens_replaced_by_id FOREIGN KEY (replaced_by_id) REFERENCES refresh_tokens (id)
);

CREATE TABLE password_resets (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    token_sha256 bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    CONSTRAINT pk_password_resets PRIMARY KEY (id),
    CONSTRAINT uq_password_resets_token_sha256 UNIQUE (token_sha256),
    CONSTRAINT ck_password_resets_expiry CHECK (expires_at > created_at),
    CONSTRAINT fk_password_resets_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- ===================== Module privacy =====================

CREATE TABLE consent_purposes (
    code text NOT NULL,
    name_vi text NOT NULL,
    description_vi text NOT NULL,
    data_category text NOT NULL,
    is_sensitive boolean NOT NULL,
    is_required boolean NOT NULL DEFAULT false,
    CONSTRAINT pk_consent_purposes PRIMARY KEY (code)
);

CREATE TABLE policy_versions (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    purpose_code text NOT NULL,
    version text NOT NULL,
    text_sha256 bytea NOT NULL,
    effective_from timestamptz NOT NULL,
    CONSTRAINT pk_policy_versions PRIMARY KEY (id),
    CONSTRAINT uq_policy_versions_purpose_code_version UNIQUE (purpose_code, version),
    CONSTRAINT fk_policy_versions_purpose_code FOREIGN KEY (purpose_code) REFERENCES consent_purposes (code)
);

CREATE TABLE consent_events (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    policy_version_id uuid NOT NULL,
    action text NOT NULL,
    channel text NOT NULL,
    app_version text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_consent_events PRIMARY KEY (id),
    CONSTRAINT ck_consent_events_action_enum CHECK (action IN ('grant', 'withdraw')),
    CONSTRAINT ck_consent_events_channel_enum CHECK (channel IN ('onboarding', 'settings')),
    CONSTRAINT fk_consent_events_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_consent_events_policy_version_id FOREIGN KEY (policy_version_id) REFERENCES policy_versions (id)
);

CREATE TABLE dsr_requests (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid,
    subject_ref bytea NOT NULL,
    type text NOT NULL,
    status text NOT NULL,
    received_at timestamptz NOT NULL,
    acknowledged_at timestamptz,
    completed_at timestamptz,
    result_key text,
    note text,
    CONSTRAINT pk_dsr_requests PRIMARY KEY (id),
    CONSTRAINT ck_dsr_requests_completed_at CHECK (completed_at IS NULL OR completed_at >= received_at),
    CONSTRAINT ck_dsr_requests_type_enum CHECK (type IN ('access', 'export', 'correct', 'delete', 'withdraw', 'restrict', 'object')),
    CONSTRAINT ck_dsr_requests_status_enum CHECK (status IN ('received', 'in_progress', 'completed', 'rejected')),
    CONSTRAINT fk_dsr_requests_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE audit_log (
    id bigserial NOT NULL,
    actor_user_id uuid,
    actor_role text NOT NULL,
    action text NOT NULL,
    entity text NOT NULL,
    entity_id text,
    purpose text,
    request_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_audit_log PRIMARY KEY (id),
    CONSTRAINT fk_audit_log_actor_user_id FOREIGN KEY (actor_user_id) REFERENCES users (id) ON DELETE SET NULL
);

-- ===================== Module catalog =====================

CREATE TABLE food_groups (
    code text NOT NULL,
    name_vi text NOT NULL,
    CONSTRAINT pk_food_groups PRIMARY KEY (code)
);

CREATE TABLE nutrient_sources (
    id smallint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    version text NOT NULL,
    license text NOT NULL,
    url text NOT NULL,
    CONSTRAINT pk_nutrient_sources PRIMARY KEY (id),
    CONSTRAINT uq_nutrient_sources_code UNIQUE (code)
);

CREATE TABLE food_items (
    source_id smallint NOT NULL,
    source_code text NOT NULL,
    name text NOT NULL,
    name_en text,
    refuse_pct numeric,
    CONSTRAINT pk_food_items PRIMARY KEY (source_id, source_code),
    CONSTRAINT ck_food_items_refuse_pct CHECK (refuse_pct BETWEEN 0 AND 100),
    CONSTRAINT fk_food_items_source_id FOREIGN KEY (source_id) REFERENCES nutrient_sources (id)
);

CREATE TABLE nutrients (
    code text NOT NULL,
    name_vi text NOT NULL,
    unit text NOT NULL,
    CONSTRAINT pk_nutrients PRIMARY KEY (code)
);

CREATE TABLE food_nutrients (
    source_id smallint NOT NULL,
    source_code text NOT NULL,
    nutrient_code text NOT NULL,
    per_100g numeric NOT NULL,
    CONSTRAINT pk_food_nutrients PRIMARY KEY (source_id, source_code, nutrient_code),
    CONSTRAINT ck_food_nutrients_per_100g CHECK (per_100g >= 0),
    CONSTRAINT fk_food_nutrients_nutrient_code FOREIGN KEY (nutrient_code) REFERENCES nutrients (code),
    CONSTRAINT fk_food_nutrients_source_id_source_code FOREIGN KEY (source_id, source_code) REFERENCES food_items (source_id, source_code)
);

CREATE TABLE allergen_groups (
    code text NOT NULL,
    name_vi text NOT NULL,
    name_en text NOT NULL,
    basis text NOT NULL,
    CONSTRAINT pk_allergen_groups PRIMARY KEY (code),
    CONSTRAINT ck_allergen_groups_basis_enum CHECK (basis IN ('codex_2024', 'tastoria_extra'))
);

CREATE TABLE diets (
    code text NOT NULL,
    name_vi text NOT NULL,
    CONSTRAINT pk_diets PRIMARY KEY (code)
);

CREATE TABLE diet_exclusions (
    diet_code text NOT NULL,
    food_group_code text NOT NULL,
    CONSTRAINT pk_diet_exclusions PRIMARY KEY (diet_code, food_group_code),
    CONSTRAINT fk_diet_exclusions_diet_code FOREIGN KEY (diet_code) REFERENCES diets (code),
    CONSTRAINT fk_diet_exclusions_food_group_code FOREIGN KEY (food_group_code) REFERENCES food_groups (code)
);

CREATE TABLE ingredients (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    name_vi text NOT NULL,
    food_group_code text NOT NULL,
    comp_source_id smallint,
    comp_source_code text,
    is_staple boolean NOT NULL DEFAULT false,
    countable boolean NOT NULL DEFAULT false,
    shelf_life_days numeric,
    shelf_life_basis text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_ingredients PRIMARY KEY (id),
    CONSTRAINT ck_ingredients_comp_pair CHECK ((comp_source_id IS NULL) = (comp_source_code IS NULL)),
    CONSTRAINT ck_ingredients_shelf_life_days CHECK (shelf_life_days > 0),
    CONSTRAINT fk_ingredients_food_group_code FOREIGN KEY (food_group_code) REFERENCES food_groups (code),
    CONSTRAINT fk_ingredients_comp_source_id_comp_source_code FOREIGN KEY (comp_source_id, comp_source_code) REFERENCES food_items (source_id, source_code)
);

CREATE TABLE ingredient_synonyms (
    ingredient_id uuid NOT NULL,
    synonym text NOT NULL,
    lang text NOT NULL,
    source text,
    CONSTRAINT pk_ingredient_synonyms PRIMARY KEY (ingredient_id, synonym, lang),
    CONSTRAINT ck_ingredient_synonyms_lang_enum CHECK (lang IN ('vi', 'en')),
    CONSTRAINT fk_ingredient_synonyms_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)
);

CREATE TABLE ingredient_allergens (
    ingredient_id uuid NOT NULL,
    allergen_code text NOT NULL,
    CONSTRAINT pk_ingredient_allergens PRIMARY KEY (ingredient_id, allergen_code),
    CONSTRAINT fk_ingredient_allergens_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id),
    CONSTRAINT fk_ingredient_allergens_allergen_code FOREIGN KEY (allergen_code) REFERENCES allergen_groups (code)
);

CREATE TABLE ingredient_units (
    ingredient_id uuid NOT NULL,
    unit_code text NOT NULL,
    grams_per_unit numeric NOT NULL,
    source text NOT NULL,
    CONSTRAINT pk_ingredient_units PRIMARY KEY (ingredient_id, unit_code),
    CONSTRAINT ck_ingredient_units_grams_per_unit CHECK (grams_per_unit > 0),
    CONSTRAINT fk_ingredient_units_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)
);

CREATE TABLE qty_levels (
    food_group_code text NOT NULL,
    level text NOT NULL,
    g_min numeric NOT NULL,
    g_max numeric NOT NULL,
    CONSTRAINT pk_qty_levels PRIMARY KEY (food_group_code, level),
    CONSTRAINT ck_qty_levels_1 CHECK (g_min <= g_max),
    CONSTRAINT ck_qty_levels_g_min CHECK (g_min >= 0),
    CONSTRAINT ck_qty_levels_level_enum CHECK (level IN ('it', 'vua', 'nhieu')),
    CONSTRAINT fk_qty_levels_food_group_code FOREIGN KEY (food_group_code) REFERENCES food_groups (code)
);

CREATE TABLE cooking_methods (
    code text NOT NULL,
    name_vi text NOT NULL,
    CONSTRAINT pk_cooking_methods PRIMARY KEY (code)
);

CREATE TABLE tags (
    code text NOT NULL,
    kind text NOT NULL,
    name_vi text NOT NULL,
    CONSTRAINT pk_tags PRIMARY KEY (code),
    CONSTRAINT ck_tags_kind_enum CHECK (kind IN ('flavor', 'texture', 'occasion'))
);

CREATE TABLE recipes (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    name_vi text NOT NULL,
    slot text NOT NULL,
    servings smallint NOT NULL,
    method_code text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_recipes PRIMARY KEY (id),
    CONSTRAINT uq_recipes_id_slot UNIQUE (id, slot),
    CONSTRAINT ck_recipes_servings CHECK (servings > 0),
    CONSTRAINT ck_recipes_slot_enum CHECK (slot IN ('man', 'rau', 'canh')),
    CONSTRAINT ck_recipes_status_enum CHECK (status IN ('draft', 'published', 'retired')),
    CONSTRAINT fk_recipes_method_code FOREIGN KEY (method_code) REFERENCES cooking_methods (code)
);

CREATE TABLE recipe_ingredients (
    recipe_id uuid NOT NULL,
    ingredient_id uuid NOT NULL,
    grams numeric NOT NULL,
    role text NOT NULL,
    is_optional boolean NOT NULL DEFAULT false,
    CONSTRAINT pk_recipe_ingredients PRIMARY KEY (recipe_id, ingredient_id),
    CONSTRAINT ck_recipe_ingredients_grams CHECK (grams > 0),
    CONSTRAINT ck_recipe_ingredients_role_enum CHECK (role IN ('main', 'side', 'seasoning')),
    CONSTRAINT fk_recipe_ingredients_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id),
    CONSTRAINT fk_recipe_ingredients_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)
);

CREATE TABLE recipe_steps (
    recipe_id uuid NOT NULL,
    step_no smallint NOT NULL,
    text_vi text NOT NULL,
    kind text NOT NULL,
    minutes smallint NOT NULL,
    uses_burner boolean NOT NULL DEFAULT false,
    CONSTRAINT pk_recipe_steps PRIMARY KEY (recipe_id, step_no),
    CONSTRAINT ck_recipe_steps_minutes CHECK (minutes > 0),
    CONSTRAINT ck_recipe_steps_step_no CHECK (step_no > 0),
    CONSTRAINT ck_recipe_steps_kind_enum CHECK (kind IN ('active', 'passive')),
    CONSTRAINT fk_recipe_steps_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)
);

CREATE TABLE recipe_tags (
    recipe_id uuid NOT NULL,
    tag_code text NOT NULL,
    CONSTRAINT pk_recipe_tags PRIMARY KEY (recipe_id, tag_code),
    CONSTRAINT fk_recipe_tags_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id),
    CONSTRAINT fk_recipe_tags_tag_code FOREIGN KEY (tag_code) REFERENCES tags (code)
);

CREATE TABLE recipe_sources (
    recipe_id uuid NOT NULL,
    url text NOT NULL,
    title text NOT NULL,
    accessed_on date NOT NULL,
    CONSTRAINT pk_recipe_sources PRIMARY KEY (recipe_id, url),
    CONSTRAINT fk_recipe_sources_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)
);

CREATE TABLE recipe_nutrition (
    recipe_id uuid NOT NULL,
    nutrient_code text NOT NULL,
    per_serving numeric NOT NULL,
    computed_at timestamptz NOT NULL,
    data_version text NOT NULL,
    CONSTRAINT pk_recipe_nutrition PRIMARY KEY (recipe_id, nutrient_code),
    CONSTRAINT ck_recipe_nutrition_per_serving CHECK (per_serving >= 0),
    CONSTRAINT fk_recipe_nutrition_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id),
    CONSTRAINT fk_recipe_nutrition_nutrient_code FOREIGN KEY (nutrient_code) REFERENCES nutrients (code)
);

CREATE TABLE vision_classes (
    id smallint NOT NULL,
    code text NOT NULL,
    name_vi text NOT NULL,
    name_en text NOT NULL,
    countable boolean NOT NULL,
    instance_def text NOT NULL,
    has_freshness_model boolean NOT NULL DEFAULT false,
    CONSTRAINT pk_vision_classes PRIMARY KEY (id),
    CONSTRAINT uq_vision_classes_code UNIQUE (code),
    CONSTRAINT ck_vision_classes_instance_def_enum CHECK (instance_def IN ('item', 'group_of', 'package'))
);

CREATE TABLE vision_class_ingredients (
    vision_class_id smallint NOT NULL,
    ingredient_id uuid NOT NULL,
    is_default boolean NOT NULL DEFAULT false,
    CONSTRAINT pk_vision_class_ingredients PRIMARY KEY (vision_class_id, ingredient_id),
    CONSTRAINT fk_vision_class_ingredients_vision_class_id FOREIGN KEY (vision_class_id) REFERENCES vision_classes (id),
    CONSTRAINT fk_vision_class_ingredients_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)
);

-- ===================== Module profile =====================

CREATE TABLE profiles (
    user_id uuid NOT NULL,
    sex_enc bytea,
    birth_year_enc bytea,
    height_cm_enc bytea,
    weight_kg_enc bytea,
    enc_key_id text,
    activity_level text,
    goal text,
    kcal_target integer,
    kcal_source text,
    diet_code text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_profiles PRIMARY KEY (user_id),
    CONSTRAINT ck_profiles_kcal_target CHECK (kcal_target BETWEEN 800 AND 5000),
    CONSTRAINT ck_profiles_kcal_pair CHECK ((kcal_target IS NULL) = (kcal_source IS NULL)),
    CONSTRAINT ck_profiles_expert CHECK (kcal_source IS NULL OR (goal IS NOT DISTINCT FROM 'expert') = (kcal_source = 'expert')),
    CONSTRAINT ck_profiles_enc_key CHECK (num_nonnulls(sex_enc, birth_year_enc, height_cm_enc, weight_kg_enc) = 0 OR enc_key_id IS NOT NULL),
    CONSTRAINT ck_profiles_activity_level_enum CHECK (activity_level IN ('light', 'moderate', 'heavy')),
    CONSTRAINT ck_profiles_goal_enum CHECK (goal IN ('maintain', 'lose', 'expert')),
    CONSTRAINT ck_profiles_kcal_source_enum CHECK (kcal_source IN ('suggested', 'user', 'expert')),
    CONSTRAINT fk_profiles_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_profiles_diet_code FOREIGN KEY (diet_code) REFERENCES diets (code)
);

CREATE TABLE user_allergens (
    user_id uuid NOT NULL,
    allergen_code text NOT NULL,
    CONSTRAINT pk_user_allergens PRIMARY KEY (user_id, allergen_code),
    CONSTRAINT fk_user_allergens_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_user_allergens_allergen_code FOREIGN KEY (allergen_code) REFERENCES allergen_groups (code)
);

CREATE TABLE user_favorite_recipes (
    user_id uuid NOT NULL,
    recipe_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_favorite_recipes PRIMARY KEY (user_id, recipe_id),
    CONSTRAINT fk_user_favorite_recipes_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_user_favorite_recipes_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)
);

CREATE TABLE user_settings (
    user_id uuid NOT NULL,
    burners smallint NOT NULL DEFAULT 2,
    default_persons smallint NOT NULL DEFAULT 2,
    timezone text NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_settings PRIMARY KEY (user_id),
    CONSTRAINT ck_user_settings_burners CHECK (burners BETWEEN 1 AND 4),
    CONSTRAINT ck_user_settings_default_persons CHECK (default_persons BETWEEN 1 AND 6),
    CONSTRAINT fk_user_settings_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- ===================== Module pantry =====================

CREATE TABLE pantry_lots (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    ingredient_id uuid NOT NULL,
    initial_g_min numeric NOT NULL,
    initial_g_max numeric NOT NULL,
    acquired_at timestamptz NOT NULL,
    acquired_basis text NOT NULL,
    status text NOT NULL DEFAULT 'in_stock',
    p_tuoi real,
    p_dung_som real,
    p_dung_ngay real,
    p_kiem_tra real,
    freshness_observed_at timestamptz,
    freshness_model_version_id uuid,
    user_checked_at timestamptz,
    source_scan_item_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_pantry_lots PRIMARY KEY (id),
    CONSTRAINT ck_pantry_lots_initial_g_min CHECK (initial_g_min >= 0),
    CONSTRAINT ck_pantry_lots_1 CHECK (initial_g_min <= initial_g_max),
    CONSTRAINT ck_pantry_lots_p_range CHECK (p_tuoi BETWEEN 0 AND 1 AND p_dung_som BETWEEN 0 AND 1
                                             AND p_dung_ngay BETWEEN 0 AND 1 AND p_kiem_tra BETWEEN 0 AND 1),
    CONSTRAINT ck_pantry_lots_p_group CHECK (num_nulls(p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra) IN (0, 4)),
    CONSTRAINT ck_pantry_lots_p_sum CHECK (p_tuoi IS NULL OR abs(p_tuoi + p_dung_som + p_dung_ngay + p_kiem_tra - 1) <= 0.01),
    CONSTRAINT ck_pantry_lots_p_observed CHECK (p_tuoi IS NULL OR freshness_observed_at IS NOT NULL),
    CONSTRAINT ck_pantry_lots_acquired_basis_enum CHECK (acquired_basis IN ('purchase_date_entered', 'first_seen')),
    CONSTRAINT ck_pantry_lots_status_enum CHECK (status IN ('in_stock', 'used_up', 'discarded', 'not_seen')),
    CONSTRAINT fk_pantry_lots_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_pantry_lots_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)
);

CREATE TABLE pantry_transactions (
    id bigserial NOT NULL,
    lot_id uuid NOT NULL,
    delta_g_min numeric NOT NULL,
    delta_g_max numeric NOT NULL,
    reason text NOT NULL,
    ref_type text,
    ref_id uuid,
    reverses_id bigint,
    urgency_at_event real,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_pantry_transactions PRIMARY KEY (id),
    CONSTRAINT uq_pantry_transactions_reverses_id UNIQUE (reverses_id),
    CONSTRAINT ck_pantry_transactions_ref_pair CHECK ((ref_type IS NULL) = (ref_id IS NULL)),
    CONSTRAINT ck_pantry_transactions_undo CHECK ((reason = 'undo') = (reverses_id IS NOT NULL)),
    CONSTRAINT ck_pantry_transactions_not_self CHECK (reverses_id <> id),
    CONSTRAINT ck_pantry_transactions_urgency CHECK (urgency_at_event >= 0),
    CONSTRAINT ck_pantry_transactions_reason_enum CHECK (reason IN ('scan_add', 'cook_deduct', 'manual_edit', 'discard', 'undo')),
    CONSTRAINT ck_pantry_transactions_ref_type_enum CHECK (ref_type IN ('scan', 'cook_session', 'user')),
    CONSTRAINT fk_pantry_transactions_lot_id FOREIGN KEY (lot_id) REFERENCES pantry_lots (id) ON DELETE CASCADE,
    CONSTRAINT fk_pantry_transactions_reverses_id FOREIGN KEY (reverses_id) REFERENCES pantry_transactions (id)
);

-- ===================== Module mlops =====================

CREATE TABLE model_versions (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    name text NOT NULL,
    version text NOT NULL,
    artifact_key text NOT NULL,
    sha256 bytea NOT NULL,
    preprocess_version text,
    metrics jsonb NOT NULL,
    gate_report_key text,
    mlflow_run_id text,
    status text NOT NULL DEFAULT 'candidate',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_model_versions PRIMARY KEY (id),
    CONSTRAINT uq_model_versions_name_version UNIQUE (name, version),
    CONSTRAINT uq_model_versions_id_name UNIQUE (id, name),
    CONSTRAINT ck_model_versions_name_enum CHECK (name IN ('detector', 'freshness', 'ranker', 'substitution')),
    CONSTRAINT ck_model_versions_status_enum CHECK (status IN ('candidate', 'validated', 'rejected', 'retired'))
);

CREATE TABLE model_version_classes (
    model_version_id uuid NOT NULL,
    class_index smallint NOT NULL,
    vision_class_id smallint NOT NULL,
    CONSTRAINT pk_model_version_classes PRIMARY KEY (model_version_id, class_index),
    CONSTRAINT uq_model_version_classes_model_version_id_vision_class_id UNIQUE (model_version_id, vision_class_id),
    CONSTRAINT ck_model_version_classes_class_index CHECK (class_index >= 0),
    CONSTRAINT fk_model_version_classes_model_version_id FOREIGN KEY (model_version_id) REFERENCES model_versions (id),
    CONSTRAINT fk_model_version_classes_vision_class_id FOREIGN KEY (vision_class_id) REFERENCES vision_classes (id)
);

CREATE TABLE model_deployments (
    name text NOT NULL,
    active_version_id uuid NOT NULL,
    previous_version_id uuid,
    switched_at timestamptz NOT NULL,
    switched_by uuid,
    CONSTRAINT pk_model_deployments PRIMARY KEY (name),
    CONSTRAINT uq_model_deployments_active_version_id UNIQUE (active_version_id),
    CONSTRAINT ck_model_deployments_previous CHECK (previous_version_id <> active_version_id),
    CONSTRAINT ck_model_deployments_name_enum CHECK (name IN ('detector', 'freshness', 'ranker', 'substitution')),
    CONSTRAINT fk_model_deployments_active_version_id_name FOREIGN KEY (active_version_id, name) REFERENCES model_versions (id, name),
    CONSTRAINT fk_model_deployments_previous_version_id_name FOREIGN KEY (previous_version_id, name) REFERENCES model_versions (id, name),
    CONSTRAINT fk_model_deployments_switched_by FOREIGN KEY (switched_by) REFERENCES users (id) ON DELETE SET NULL
);

-- ===================== Module scan =====================

CREATE TABLE scans (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    mode text NOT NULL,
    status text NOT NULL,
    error_code text,
    attempts smallint NOT NULL DEFAULT 0,
    detector_version_id uuid,
    classifier_version_id uuid,
    preprocess_version text,
    enqueued_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_scans PRIMARY KEY (id),
    CONSTRAINT ck_scans_attempts CHECK (attempts >= 0),
    CONSTRAINT ck_scans_confirmed CHECK ((status = 'confirmed') = (confirmed_at IS NOT NULL)),
    CONSTRAINT ck_scans_mode_enum CHECK (mode IN ('fridge', 'haul')),
    CONSTRAINT ck_scans_status_enum CHECK (status IN ('queued', 'processing', 'done', 'failed', 'expired', 'confirmed', 'discarded')),
    CONSTRAINT fk_scans_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_scans_detector_version_id FOREIGN KEY (detector_version_id) REFERENCES model_versions (id),
    CONSTRAINT fk_scans_classifier_version_id FOREIGN KEY (classifier_version_id) REFERENCES model_versions (id)
);

CREATE TABLE scan_images (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    scan_id uuid NOT NULL,
    ordinal smallint NOT NULL,
    shelf_group smallint NOT NULL DEFAULT 1,
    storage_key text NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    contributed boolean NOT NULL DEFAULT false,
    purged_at timestamptz,
    CONSTRAINT pk_scan_images PRIMARY KEY (id),
    CONSTRAINT uq_scan_images_storage_key UNIQUE (storage_key),
    CONSTRAINT uq_scan_images_scan_id_ordinal UNIQUE (scan_id, ordinal),
    CONSTRAINT ck_scan_images_ordinal CHECK (ordinal BETWEEN 1 AND 2),
    CONSTRAINT ck_scan_images_size CHECK (width > 0 AND height > 0),
    CONSTRAINT ck_scan_images_shelf_group CHECK (shelf_group >= 1),
    CONSTRAINT fk_scan_images_scan_id FOREIGN KEY (scan_id) REFERENCES scans (id) ON DELETE CASCADE
);

CREATE TABLE scan_items (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    scan_id uuid NOT NULL,
    ingredient_id uuid NOT NULL,
    origin text NOT NULL,
    model_count smallint,
    final_count smallint,
    qty_level text,
    user_action text NOT NULL DEFAULT 'kept',
    original_ingredient_id uuid,
    user_freshness text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_scan_items PRIMARY KEY (id),
    CONSTRAINT ck_scan_items_model_count CHECK (model_count >= 0),
    CONSTRAINT ck_scan_items_final_count CHECK (final_count BETWEEN 0 AND 99),
    CONSTRAINT ck_scan_items_relabeled CHECK (user_action <> 'relabeled' OR original_ingredient_id IS NOT NULL),
    CONSTRAINT ck_scan_items_original CHECK (original_ingredient_id IS NULL
                                             OR (origin = 'model' AND original_ingredient_id <> ingredient_id)),
    CONSTRAINT ck_scan_items_user_added CHECK (origin = 'model' OR (model_count IS NULL AND user_action <> 'deleted')),
    CONSTRAINT ck_scan_items_origin_enum CHECK (origin IN ('model', 'user_added')),
    CONSTRAINT ck_scan_items_qty_level_enum CHECK (qty_level IN ('it', 'vua', 'nhieu')),
    CONSTRAINT ck_scan_items_user_action_enum CHECK (user_action IN ('kept', 'relabeled', 'deleted', 'edited')),
    CONSTRAINT ck_scan_items_user_freshness_enum CHECK (user_freshness IN ('tuoi', 'dung_som', 'dung_ngay', 'kiem_tra')),
    CONSTRAINT fk_scan_items_scan_id FOREIGN KEY (scan_id) REFERENCES scans (id) ON DELETE CASCADE,
    CONSTRAINT fk_scan_items_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id),
    CONSTRAINT fk_scan_items_original_ingredient_id FOREIGN KEY (original_ingredient_id) REFERENCES ingredients (id)
);

CREATE TABLE detections (
    id bigserial NOT NULL,
    scan_image_id uuid NOT NULL,
    scan_item_id uuid,
    vision_class_id smallint NOT NULL,
    x1 real NOT NULL,
    y1 real NOT NULL,
    x2 real NOT NULL,
    y2 real NOT NULL,
    confidence real NOT NULL,
    p_tuoi real,
    p_dung_som real,
    p_dung_ngay real,
    p_kiem_tra real,
    CONSTRAINT pk_detections PRIMARY KEY (id),
    CONSTRAINT ck_detections_1 CHECK (0 <= x1 AND x1 < x2 AND x2 <= 1 AND 0 <= y1 AND y1 < y2 AND y2 <= 1),
    CONSTRAINT ck_detections_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_detections_p_range CHECK (p_tuoi BETWEEN 0 AND 1 AND p_dung_som BETWEEN 0 AND 1
                                            AND p_dung_ngay BETWEEN 0 AND 1 AND p_kiem_tra BETWEEN 0 AND 1),
    CONSTRAINT ck_detections_p_group CHECK (num_nulls(p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra) IN (0, 4)),
    CONSTRAINT ck_detections_p_sum CHECK (p_tuoi IS NULL OR abs(p_tuoi + p_dung_som + p_dung_ngay + p_kiem_tra - 1) <= 0.01),
    CONSTRAINT fk_detections_scan_image_id FOREIGN KEY (scan_image_id) REFERENCES scan_images (id) ON DELETE CASCADE,
    CONSTRAINT fk_detections_scan_item_id FOREIGN KEY (scan_item_id) REFERENCES scan_items (id) ON DELETE SET NULL,
    CONSTRAINT fk_detections_vision_class_id FOREIGN KEY (vision_class_id) REFERENCES vision_classes (id)
);

-- ===================== Module substitute =====================

CREATE TABLE substitution_pairs (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    ingredient_id uuid NOT NULL,
    substitute_id uuid NOT NULL,
    context_slot text,
    context_method_code text,
    ratio numeric NOT NULL DEFAULT 1,
    score real NOT NULL,
    source text NOT NULL,
    curated boolean NOT NULL,
    CONSTRAINT pk_substitution_pairs PRIMARY KEY (id),
    CONSTRAINT uq_substitution_pairs_ctx UNIQUE (ingredient_id, substitute_id, context_slot, context_method_code),
    CONSTRAINT ck_substitution_pairs_1 CHECK (ingredient_id <> substitute_id),
    CONSTRAINT ck_substitution_pairs_ratio CHECK (ratio > 0),
    CONSTRAINT ck_substitution_pairs_context_slot_enum CHECK (context_slot IN ('man', 'rau', 'canh')),
    CONSTRAINT fk_substitution_pairs_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id),
    CONSTRAINT fk_substitution_pairs_substitute_id FOREIGN KEY (substitute_id) REFERENCES ingredients (id),
    CONSTRAINT fk_substitution_pairs_context_method_code FOREIGN KEY (context_method_code) REFERENCES cooking_methods (code)
);

CREATE TABLE ingredient_embeddings (
    ingredient_id uuid NOT NULL,
    model_version_id uuid NOT NULL,
    vector bytea NOT NULL,
    CONSTRAINT pk_ingredient_embeddings PRIMARY KEY (ingredient_id, model_version_id),
    CONSTRAINT fk_ingredient_embeddings_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id),
    CONSTRAINT fk_ingredient_embeddings_model_version_id FOREIGN KEY (model_version_id) REFERENCES model_versions (id)
);

CREATE TABLE shopping_items (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    ingredient_id uuid NOT NULL,
    qty_g numeric,
    note text,
    status text NOT NULL DEFAULT 'open',
    source_meal_plan_item_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_shopping_items PRIMARY KEY (id),
    CONSTRAINT ck_shopping_items_qty_g CHECK (qty_g > 0),
    CONSTRAINT ck_shopping_items_status_enum CHECK (status IN ('open', 'bought', 'dropped')),
    CONSTRAINT fk_shopping_items_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_shopping_items_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)
);

-- ===================== Module meal =====================

CREATE TABLE meal_plans (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    meal text NOT NULL,
    persons smallint NOT NULL,
    max_minutes smallint NOT NULL,
    status text NOT NULL DEFAULT 'proposed',
    e_target_kcal numeric,
    kcal_low numeric,
    kcal_high numeric,
    rice_bowls_per_person numeric,
    reason_vi text NOT NULL,
    ranker_version_id uuid,
    params_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_meal_plans PRIMARY KEY (id),
    CONSTRAINT uq_meal_plans_id_user_id UNIQUE (id, user_id),
    CONSTRAINT ck_meal_plans_persons CHECK (persons BETWEEN 1 AND 6),
    CONSTRAINT ck_meal_plans_max_minutes CHECK (max_minutes BETWEEN 10 AND 180),
    CONSTRAINT ck_meal_plans_e_target_kcal CHECK (e_target_kcal > 0),
    CONSTRAINT ck_meal_plans_kcal_pair CHECK ((kcal_low IS NULL) = (kcal_high IS NULL)),
    CONSTRAINT ck_meal_plans_kcal_range CHECK (kcal_low >= 0 AND kcal_low <= kcal_high),
    CONSTRAINT ck_meal_plans_rice_bowls CHECK (rice_bowls_per_person BETWEEN 0.5 AND 3
                                               AND rice_bowls_per_person * 2 = trunc(rice_bowls_per_person * 2)),
    CONSTRAINT ck_meal_plans_meal_enum CHECK (meal IN ('lunch', 'dinner')),
    CONSTRAINT ck_meal_plans_status_enum CHECK (status IN ('proposed', 'accepted', 'cooked', 'abandoned', 'expired')),
    CONSTRAINT fk_meal_plans_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_meal_plans_ranker_version_id FOREIGN KEY (ranker_version_id) REFERENCES model_versions (id)
);

CREATE TABLE meal_plan_coeater_allergens (
    meal_plan_id uuid NOT NULL,
    allergen_code text NOT NULL,
    CONSTRAINT pk_meal_plan_coeater_allergens PRIMARY KEY (meal_plan_id, allergen_code),
    CONSTRAINT fk_meal_plan_coeater_allergens_meal_plan_id FOREIGN KEY (meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE,
    CONSTRAINT fk_meal_plan_coeater_allergens_allergen_code FOREIGN KEY (allergen_code) REFERENCES allergen_groups (code)
);

CREATE TABLE meal_plan_pins (
    meal_plan_id uuid NOT NULL,
    lot_id uuid NOT NULL,
    CONSTRAINT pk_meal_plan_pins PRIMARY KEY (meal_plan_id, lot_id),
    CONSTRAINT fk_meal_plan_pins_meal_plan_id FOREIGN KEY (meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE,
    CONSTRAINT fk_meal_plan_pins_lot_id FOREIGN KEY (lot_id) REFERENCES pantry_lots (id) ON DELETE CASCADE
);

CREATE TABLE meal_plan_items (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    meal_plan_id uuid NOT NULL,
    slot text NOT NULL,
    recipe_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'active',
    replaced_item_id uuid,
    swap_reason text,
    rank_score real NOT NULL,
    servings_scale numeric NOT NULL,
    kcal_per_person numeric,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_meal_plan_items PRIMARY KEY (id),
    CONSTRAINT uq_meal_plan_items_replaced_item_id UNIQUE (replaced_item_id),
    CONSTRAINT uq_meal_plan_items_id_meal_plan_id_recipe_id UNIQUE (id, meal_plan_id, recipe_id),
    CONSTRAINT ck_meal_plan_items_servings_scale CHECK (servings_scale > 0),
    CONSTRAINT ck_meal_plan_items_kcal_per_person CHECK (kcal_per_person >= 0),
    CONSTRAINT ck_meal_plan_items_not_self CHECK (replaced_item_id <> id),
    CONSTRAINT ck_meal_plan_items_slot_enum CHECK (slot IN ('man', 'rau', 'canh')),
    CONSTRAINT ck_meal_plan_items_status_enum CHECK (status IN ('active', 'swapped_out')),
    CONSTRAINT ck_meal_plan_items_swap_reason_enum CHECK (swap_reason IN ('khong_hop_gu', 'moi_an', 'thieu_thoi_gian', 'khac')),
    CONSTRAINT fk_meal_plan_items_meal_plan_id FOREIGN KEY (meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE,
    CONSTRAINT fk_meal_plan_items_replaced_item_id FOREIGN KEY (replaced_item_id) REFERENCES meal_plan_items (id),
    CONSTRAINT fk_meal_plan_items_recipe_id_slot FOREIGN KEY (recipe_id, slot) REFERENCES recipes (id, slot)
);

CREATE TABLE meal_plan_item_substitutions (
    item_id uuid NOT NULL,
    original_ingredient_id uuid NOT NULL,
    substitute_ingredient_id uuid NOT NULL,
    grams numeric NOT NULL,
    origin text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_meal_plan_item_substitutions PRIMARY KEY (item_id, original_ingredient_id),
    CONSTRAINT ck_meal_plan_item_substitutions_grams CHECK (grams > 0),
    CONSTRAINT ck_meal_plan_item_substitutions_distinct CHECK (original_ingredient_id <> substitute_ingredient_id),
    CONSTRAINT ck_meal_plan_item_substitutions_origin_enum CHECK (origin IN ('lookup', 'embedding', 'user')),
    CONSTRAINT fk_meal_plan_item_substitutions_item_id FOREIGN KEY (item_id) REFERENCES meal_plan_items (id) ON DELETE CASCADE,
    CONSTRAINT fk_meal_plan_item_substitutions_original_ingredient_id FOREIGN KEY (original_ingredient_id) REFERENCES ingredients (id),
    CONSTRAINT fk_meal_plan_item_substitutions_substitute_ingredient_id FOREIGN KEY (substitute_ingredient_id) REFERENCES ingredients (id)
);

-- ===================== Module cooking =====================

CREATE TABLE cook_sessions (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    meal_plan_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'in_progress',
    serve_at timestamptz NOT NULL,
    burners smallint NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    reverted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_cook_sessions PRIMARY KEY (id),
    CONSTRAINT ck_cook_sessions_burners CHECK (burners BETWEEN 1 AND 4),
    CONSTRAINT ck_cook_sessions_completed CHECK ((status = 'completed') = (completed_at IS NOT NULL AND reverted_at IS NULL)),
    CONSTRAINT ck_cook_sessions_reverted CHECK ((status = 'reverted') = (reverted_at IS NOT NULL)),
    CONSTRAINT ck_cook_sessions_order CHECK (completed_at >= started_at AND reverted_at >= completed_at
                                             AND (reverted_at IS NULL OR completed_at IS NOT NULL)),
    CONSTRAINT ck_cook_sessions_status_enum CHECK (status IN ('in_progress', 'completed', 'reverted', 'abandoned')),
    CONSTRAINT fk_cook_sessions_meal_plan_id FOREIGN KEY (meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE
);

CREATE TABLE cook_schedule_entries (
    cook_session_id uuid NOT NULL,
    recipe_id uuid NOT NULL,
    step_no smallint NOT NULL,
    start_offset_s integer NOT NULL,
    end_offset_s integer NOT NULL,
    CONSTRAINT pk_cook_schedule_entries PRIMARY KEY (cook_session_id, recipe_id, step_no),
    CONSTRAINT ck_cook_schedule_entries_1 CHECK (start_offset_s < end_offset_s),
    CONSTRAINT ck_cook_schedule_entries_start CHECK (start_offset_s >= 0),
    CONSTRAINT fk_cook_schedule_entries_cook_session_id FOREIGN KEY (cook_session_id) REFERENCES cook_sessions (id) ON DELETE CASCADE,
    CONSTRAINT fk_cook_schedule_entries_recipe_id_step_no FOREIGN KEY (recipe_id, step_no) REFERENCES recipe_steps (recipe_id, step_no)
);

-- ===================== Module events =====================

CREATE TABLE interactions (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    recipe_id uuid NOT NULL,
    meal_plan_id uuid,
    meal_plan_item_id uuid,
    type text NOT NULL,
    position smallint,
    swap_reason text,
    ranker_version_id uuid,
    propensity real,
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    CONSTRAINT pk_interactions PRIMARY KEY (id),
    CONSTRAINT ck_interactions_item_needs_plan CHECK (meal_plan_item_id IS NULL OR meal_plan_id IS NOT NULL),
    CONSTRAINT ck_interactions_position CHECK (position >= 0),
    CONSTRAINT ck_interactions_propensity CHECK (propensity > 0 AND propensity <= 1),
    CONSTRAINT ck_interactions_swap_reason CHECK (swap_reason IS NULL OR type = 'swapped'),
    CONSTRAINT ck_interactions_type_enum CHECK (type IN ('served', 'viewed', 'swapped', 'cooked', 'liked', 'disliked', 'undone')),
    CONSTRAINT ck_interactions_swap_reason_enum CHECK (swap_reason IN ('khong_hop_gu', 'moi_an', 'thieu_thoi_gian', 'khac')),
    CONSTRAINT fk_interactions_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_interactions_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id),
    CONSTRAINT fk_interactions_meal_plan_item_id_meal_plan_id_recipe_id FOREIGN KEY (meal_plan_item_id, meal_plan_id, recipe_id) REFERENCES meal_plan_items (id, meal_plan_id, recipe_id) ON DELETE SET NULL,
    CONSTRAINT fk_interactions_ranker_version_id FOREIGN KEY (ranker_version_id) REFERENCES model_versions (id),
    CONSTRAINT fk_interactions_meal_plan_id_user_id FOREIGN KEY (meal_plan_id, user_id) REFERENCES meal_plans (id, user_id) ON DELETE CASCADE
);

-- ===================== Module survey =====================

CREATE TABLE survey_forms (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    version text NOT NULL,
    n_anchor smallint NOT NULL,
    n_random smallint NOT NULL,
    is_open boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_survey_forms PRIMARY KEY (id),
    CONSTRAINT uq_survey_forms_version UNIQUE (version),
    CONSTRAINT ck_survey_forms_sizes CHECK (n_anchor >= 0 AND n_random >= 0 AND n_anchor + n_random > 0)
);

CREATE TABLE survey_form_anchors (
    form_id uuid NOT NULL,
    recipe_id uuid NOT NULL,
    CONSTRAINT pk_survey_form_anchors PRIMARY KEY (form_id, recipe_id),
    CONSTRAINT fk_survey_form_anchors_form_id FOREIGN KEY (form_id) REFERENCES survey_forms (id),
    CONSTRAINT fk_survey_form_anchors_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)
);

CREATE TABLE survey_respondents (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    form_id uuid NOT NULL,
    policy_version_id uuid NOT NULL,
    consented_at timestamptz NOT NULL,
    completed_at timestamptz,
    channel text NOT NULL,
    CONSTRAINT pk_survey_respondents PRIMARY KEY (id),
    CONSTRAINT ck_survey_respondents_channel_enum CHECK (channel IN ('link', 'qr')),
    CONSTRAINT fk_survey_respondents_form_id FOREIGN KEY (form_id) REFERENCES survey_forms (id),
    CONSTRAINT fk_survey_respondents_policy_version_id FOREIGN KEY (policy_version_id) REFERENCES policy_versions (id)
);

CREATE TABLE survey_assignments (
    respondent_id uuid NOT NULL,
    recipe_id uuid NOT NULL,
    display_order smallint NOT NULL,
    is_anchor boolean NOT NULL,
    CONSTRAINT pk_survey_assignments PRIMARY KEY (respondent_id, recipe_id),
    CONSTRAINT uq_survey_assignments_respondent_id_display_order UNIQUE (respondent_id, display_order),
    CONSTRAINT ck_survey_assignments_display_order CHECK (display_order >= 1),
    CONSTRAINT fk_survey_assignments_respondent_id FOREIGN KEY (respondent_id) REFERENCES survey_respondents (id) ON DELETE CASCADE,
    CONSTRAINT fk_survey_assignments_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)
);

CREATE TABLE survey_ratings (
    respondent_id uuid NOT NULL,
    recipe_id uuid NOT NULL,
    rating smallint,
    never_eaten boolean NOT NULL DEFAULT false,
    answered_at timestamptz NOT NULL,
    CONSTRAINT pk_survey_ratings PRIMARY KEY (respondent_id, recipe_id),
    CONSTRAINT ck_survey_ratings_rating CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT ck_survey_ratings_1 CHECK ((rating IS NULL) = never_eaten),
    CONSTRAINT fk_survey_ratings_respondent_id_recipe_id FOREIGN KEY (respondent_id, recipe_id) REFERENCES survey_assignments (respondent_id, recipe_id) ON DELETE CASCADE
);

CREATE TABLE survey_favorites (
    respondent_id uuid NOT NULL,
    recipe_id uuid NOT NULL,
    CONSTRAINT pk_survey_favorites PRIMARY KEY (respondent_id, recipe_id),
    CONSTRAINT fk_survey_favorites_respondent_id FOREIGN KEY (respondent_id) REFERENCES survey_respondents (id) ON DELETE CASCADE,
    CONSTRAINT fk_survey_favorites_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id)
);

-- ===================== Khoá ngoại trỏ tới bảng tạo sau =====================
ALTER TABLE idempotency_keys ADD CONSTRAINT fk_idempotency_keys_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE pantry_lots ADD CONSTRAINT fk_pantry_lots_freshness_model_version_id FOREIGN KEY (freshness_model_version_id) REFERENCES model_versions (id);
ALTER TABLE pantry_lots ADD CONSTRAINT fk_pantry_lots_source_scan_item_id FOREIGN KEY (source_scan_item_id) REFERENCES scan_items (id) ON DELETE SET NULL;
ALTER TABLE shopping_items ADD CONSTRAINT fk_shopping_items_source_meal_plan_item_id FOREIGN KEY (source_meal_plan_item_id) REFERENCES meal_plan_items (id) ON DELETE SET NULL;

-- ===================== Chỉ mục =====================
-- Duy nhất một phần (ràng buộc nghiệp vụ không viết được bằng UNIQUE thường).
-- Truy vấn nóng.
CREATE INDEX ix_recipe_ingredients_ingredient_id ON recipe_ingredients (ingredient_id);
CREATE INDEX ix_ingredient_allergens_allergen_code ON ingredient_allergens (allergen_code);
CREATE INDEX ix_pantry_lots_user_id_status ON pantry_lots (user_id, status);
CREATE INDEX ix_pantry_transactions_lot_id ON pantry_transactions (lot_id);
CREATE INDEX ix_interactions_user_id_occurred_at ON interactions (user_id, occurred_at DESC);
CREATE INDEX ix_meal_plans_user_id_created_at ON meal_plans (user_id, created_at DESC);
CREATE INDEX ix_meal_plan_items_meal_plan_id ON meal_plan_items (meal_plan_id);
CREATE INDEX ix_scans_user_id_created_at ON scans (user_id, created_at DESC);
CREATE INDEX ix_scan_items_scan_id ON scan_items (scan_id);
CREATE INDEX ix_detections_scan_image_id ON detections (scan_image_id);
CREATE INDEX ix_consent_events_user_id_created_at ON consent_events (user_id, created_at DESC);
CREATE INDEX ix_dsr_requests_status_received_at ON dsr_requests (status, received_at);
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);
CREATE INDEX ix_shopping_items_user_id_status ON shopping_items (user_id, status);
CREATE INDEX ix_audit_log_created_at ON audit_log (created_at);
CREATE INDEX ix_cook_sessions_meal_plan_id ON cook_sessions (meal_plan_id);
CREATE INDEX ix_survey_ratings_recipe_id ON survey_ratings (recipe_id);
CREATE INDEX ix_pantry_transactions_ref ON pantry_transactions (ref_type, ref_id);
-- Khoá ngoại có ON DELETE CASCADE / SET NULL (xoá cứng tài khoản UC07, xoá chip, xoá ảnh): tránh quét tuần tự bảng con.
CREATE INDEX ix_audit_log_actor_user_id ON audit_log (actor_user_id);
CREATE INDEX ix_dsr_requests_user_id ON dsr_requests (user_id);
CREATE INDEX ix_password_resets_user_id ON password_resets (user_id);
CREATE INDEX ix_detections_scan_item_id ON detections (scan_item_id);
CREATE INDEX ix_pantry_lots_source_scan_item_id ON pantry_lots (source_scan_item_id);
CREATE INDEX ix_meal_plan_pins_lot_id ON meal_plan_pins (lot_id);
CREATE INDEX ix_shopping_items_source_meal_plan_item_id ON shopping_items (source_meal_plan_item_id);
CREATE INDEX ix_interactions_meal_plan_item_id ON interactions (meal_plan_item_id);
CREATE INDEX ix_interactions_meal_plan_id_user_id ON interactions (meal_plan_id, user_id);
-- Tác vụ định kỳ (UC32, UC34).
CREATE INDEX ix_idempotency_keys_created_at ON idempotency_keys (created_at);
CREATE INDEX ix_refresh_tokens_expires_at ON refresh_tokens (expires_at);
CREATE INDEX ix_password_resets_expires_at ON password_resets (expires_at);

-- ===================== Chú thích =====================
COMMENT ON TABLE idempotency_keys IS 'Khoá lũy đẳng của các request POST có header Idempotency-Key (tạo quét, mâm, đổi món, phiên nấu, nấu xong); lưu phản hồi đầu tiên để trả lại nguyên văn khi client gửi lại; job dọn xoá sau 48 giờ (UC34).';
COMMENT ON COLUMN idempotency_keys.user_id IS 'Người dùng gửi request; khoá lũy đẳng có phạm vi theo từng người dùng. Nguồn: access token.';
COMMENT ON COLUMN idempotency_keys.key IS 'Giá trị header Idempotency-Key do app sinh (UUID).';
COMMENT ON COLUMN idempotency_keys.request_sha256 IS 'SHA-256 của method, path và thân request; dùng để phát hiện cùng key nhưng nội dung khác.';
COMMENT ON COLUMN idempotency_keys.status_code IS 'Mã trạng thái HTTP của phản hồi đầu tiên.';
COMMENT ON COLUMN idempotency_keys.response_body IS 'Thân phản hồi đầu tiên (JSON), chỉ để trả lại nguyên văn, không truy vấn.';
COMMENT ON COLUMN idempotency_keys.created_at IS 'Thời điểm ghi khoá; job dọn (UC34) xoá bản ghi cũ hơn 48 giờ.';

COMMENT ON TABLE users IS 'Tài khoản đăng nhập của người dùng cuối và nhân sự (quản trị viên, biên soạn công thức, vận hành mô hình).';
COMMENT ON COLUMN users.id IS 'Định danh tài khoản (UUID sinh ở server).';
COMMENT ON COLUMN users.email IS 'Email đăng nhập, so khớp không phân biệt hoa thường (citext), duy nhất.';
COMMENT ON COLUMN users.password_hash IS 'Chuỗi băm Argon2id của mật khẩu (gồm tham số và muối); không lưu mật khẩu gốc.';
COMMENT ON COLUMN users.role IS 'Vai trò: user (người dùng), admin (quản trị viên), curator (biên soạn công thức), ml_operator (vận hành mô hình).';
COMMENT ON COLUMN users.status IS 'Trạng thái tài khoản: active, hoặc deletion_requested khi người dùng đã yêu cầu xoá (UC07) và đang chờ xoá cứng.';
COMMENT ON COLUMN users.token_version IS 'Phiên bản token; tăng khi đăng xuất mọi thiết bị hoặc rút đồng ý để access token cũ hết hiệu lực ngay (BR-CONSENT-04).';
COMMENT ON COLUMN users.failed_logins IS 'Số lần đăng nhập sai liên tiếp; đặt về 0 khi đăng nhập đúng (NFR-SEC-02).';
COMMENT ON COLUMN users.locked_until IS 'Thời điểm hết khoá tạm; NULL là không bị khoá. Khoá 15 phút sau 5 lần sai (NFR-SEC-02).';
COMMENT ON COLUMN users.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';
COMMENT ON COLUMN users.updated_at IS 'Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz).';

COMMENT ON TABLE refresh_tokens IS 'Refresh token xoay vòng (hạn 30 ngày, NFR-SEC-01); chỉ lưu băm. Các token cùng family_id thuộc một chuỗi xoay vòng; dùng lại token đã thu hồi thì thu hồi cả họ.';
COMMENT ON COLUMN refresh_tokens.id IS 'Định danh bản ghi token (UUID).';
COMMENT ON COLUMN refresh_tokens.user_id IS 'Chủ token.';
COMMENT ON COLUMN refresh_tokens.family_id IS 'Định danh họ token: mọi token sinh ra từ cùng một lần đăng nhập qua các lần xoay vòng.';
COMMENT ON COLUMN refresh_tokens.token_sha256 IS 'SHA-256 của refresh token; token gốc chỉ nằm ở app.';
COMMENT ON COLUMN refresh_tokens.issued_at IS 'Thời điểm cấp token.';
COMMENT ON COLUMN refresh_tokens.expires_at IS 'Thời điểm hết hạn (issued_at + 30 ngày).';
COMMENT ON COLUMN refresh_tokens.revoked_at IS 'Thời điểm thu hồi (xoay vòng, đăng xuất, phát hiện dùng lại); NULL là còn hiệu lực.';
COMMENT ON COLUMN refresh_tokens.replaced_by_id IS 'Token mới thay thế token này khi xoay vòng; NULL nếu chưa xoay.';
COMMENT ON COLUMN refresh_tokens.user_agent IS 'Chuỗi User-Agent lúc cấp, giúp người dùng nhận ra thiết bị.';

COMMENT ON TABLE password_resets IS 'Yêu cầu đặt lại mật khẩu qua email (UC04); token dùng một lần, chỉ lưu băm.';
COMMENT ON COLUMN password_resets.id IS 'Định danh yêu cầu (UUID).';
COMMENT ON COLUMN password_resets.user_id IS 'Tài khoản cần đặt lại mật khẩu.';
COMMENT ON COLUMN password_resets.token_sha256 IS 'SHA-256 của token gửi trong thư; token gốc chỉ có trong liên kết email.';
COMMENT ON COLUMN password_resets.created_at IS 'Thời điểm tạo yêu cầu.';
COMMENT ON COLUMN password_resets.expires_at IS 'Thời điểm token hết hạn.';
COMMENT ON COLUMN password_resets.used_at IS 'Thời điểm token đã được dùng; NULL là chưa dùng.';

COMMENT ON TABLE consent_purposes IS 'Danh mục mục đích xử lý dữ liệu cần đồng ý riêng (BR-CONSENT-01); dữ liệu tham chiếu.';
COMMENT ON COLUMN consent_purposes.code IS 'Mã mục đích: health_profile, personalization, photo_contribution, survey.';
COMMENT ON COLUMN consent_purposes.name_vi IS 'Tên mục đích hiển thị cho người dùng.';
COMMENT ON COLUMN consent_purposes.description_vi IS 'Mô tả mục đích hiển thị khi xin đồng ý.';
COMMENT ON COLUMN consent_purposes.data_category IS 'Loại dữ liệu cá nhân được xử lý cho mục đích này (ví dụ chỉ số cơ thể, dữ liệu hành vi, ảnh).';
COMMENT ON COLUMN consent_purposes.is_sensitive IS 'true nếu là dữ liệu cá nhân nhạy cảm (health_profile, personalization).';
COMMENT ON COLUMN consent_purposes.is_required IS 'true nếu bắt buộc để dùng dịch vụ; mặc định false, không tích sẵn.';

COMMENT ON TABLE policy_versions IS 'Phiên bản văn bản điều khoản của từng mục đích; mỗi sự kiện đồng ý gắn với đúng phiên bản người dùng đã đọc.';
COMMENT ON COLUMN policy_versions.id IS 'Định danh phiên bản (UUID).';
COMMENT ON COLUMN policy_versions.purpose_code IS 'Mục đích mà văn bản này áp dụng.';
COMMENT ON COLUMN policy_versions.version IS 'Nhãn phiên bản, duy nhất trong một mục đích.';
COMMENT ON COLUMN policy_versions.text_sha256 IS 'SHA-256 toàn văn điều khoản đã hiển thị, làm bằng chứng nội dung.';
COMMENT ON COLUMN policy_versions.effective_from IS 'Thời điểm phiên bản bắt đầu có hiệu lực.';

COMMENT ON TABLE consent_events IS 'Nhật ký đồng ý và rút đồng ý, chỉ ghi thêm; trạng thái hiện hành = sự kiện mới nhất mỗi (người dùng, mục đích), xem v_current_consents.';
COMMENT ON COLUMN consent_events.id IS 'Định danh sự kiện (UUID).';
COMMENT ON COLUMN consent_events.user_id IS 'Người dùng đưa ra quyết định.';
COMMENT ON COLUMN consent_events.policy_version_id IS 'Phiên bản điều khoản tại thời điểm quyết định; mục đích suy ra qua policy_versions.purpose_code.';
COMMENT ON COLUMN consent_events.action IS 'grant (đồng ý) hoặc withdraw (rút đồng ý).';
COMMENT ON COLUMN consent_events.channel IS 'Nơi thao tác: onboarding (thiết lập hồ sơ, UC09) hoặc settings (cài đặt, UC05).';
COMMENT ON COLUMN consent_events.app_version IS 'Phiên bản app lúc thao tác; NULL nếu không rõ.';
COMMENT ON COLUMN consent_events.created_at IS 'Thời điểm ghi sự kiện (giờ server, clock_timestamp() để hai sự kiện trong một giao dịch vẫn có thứ tự; v_current_consents chọn sự kiện mới nhất theo cột này).';

COMMENT ON TABLE dsr_requests IS 'Yêu cầu của chủ thể dữ liệu (BR-DSR-01): truy cập, tải về, sửa, xoá, rút đồng ý, hạn chế, phản đối; hoàn tất ≤ 24 giờ (NFR-PRIV-01). Bản ghi giữ lại làm bằng chứng sau khi tài khoản bị xoá.';
COMMENT ON COLUMN dsr_requests.id IS 'Định danh yêu cầu (UUID).';
COMMENT ON COLUMN dsr_requests.user_id IS 'Người yêu cầu; thành NULL khi tài khoản bị xoá.';
COMMENT ON COLUMN dsr_requests.subject_ref IS 'HMAC-SHA256 của user_id với khoá bí mật của server; giữ liên kết bằng chứng sau khi xoá tài khoản.';
COMMENT ON COLUMN dsr_requests.type IS 'Loại yêu cầu: access, export, correct, delete, withdraw, restrict, object.';
COMMENT ON COLUMN dsr_requests.status IS 'Trạng thái xử lý: received, in_progress, completed, rejected.';
COMMENT ON COLUMN dsr_requests.received_at IS 'Thời điểm nhận yêu cầu; mốc tính hạn 24 giờ.';
COMMENT ON COLUMN dsr_requests.acknowledged_at IS 'Thời điểm xác nhận đã nhận với người yêu cầu; NULL nếu chưa.';
COMMENT ON COLUMN dsr_requests.completed_at IS 'Thời điểm hoàn tất hoặc từ chối; NULL nếu chưa xong.';
COMMENT ON COLUMN dsr_requests.result_key IS 'Khoá tệp kết quả trong kho lưu trữ (ví dụ gói dữ liệu tải về của UC06); NULL nếu không có tệp.';
COMMENT ON COLUMN dsr_requests.note IS 'Ghi chú xử lý của quản trị viên hoặc lý do từ chối.';

COMMENT ON TABLE audit_log IS 'Nhật ký kiểm toán, chỉ ghi thêm: mỗi lần giải mã cột sức khoẻ và mỗi thao tác của nhân sự.';
COMMENT ON COLUMN audit_log.id IS 'Số thứ tự bản ghi (identity).';
COMMENT ON COLUMN audit_log.actor_user_id IS 'Tài khoản thực hiện; NULL khi tài khoản đã xoá hoặc do tác vụ hệ thống.';
COMMENT ON COLUMN audit_log.actor_role IS 'Vai trò của tác nhân tại thời điểm thao tác; giữ lại cả khi tài khoản đã xoá.';
COMMENT ON COLUMN audit_log.action IS 'Mã thao tác (ví dụ giải mã hồ sơ sức khoẻ, xử lý yêu cầu dữ liệu, triển khai mô hình).';
COMMENT ON COLUMN audit_log.entity IS 'Tên loại đối tượng bị tác động (thường là tên bảng).';
COMMENT ON COLUMN audit_log.entity_id IS 'Khoá của đối tượng bị tác động, dạng chuỗi; NULL nếu thao tác không gắn một đối tượng.';
COMMENT ON COLUMN audit_log.purpose IS 'Mục đích xử lý dẫn tới thao tác (mã consent_purposes hoặc lý do nghiệp vụ); NULL nếu không áp dụng.';
COMMENT ON COLUMN audit_log.request_id IS 'Mã request HTTP hoặc mã lượt chạy CLI để đối chiếu log ứng dụng.';
COMMENT ON COLUMN audit_log.created_at IS 'Thời điểm ghi nhật ký (giờ server).';

COMMENT ON TABLE food_groups IS 'Nhóm thực phẩm; dùng để loại theo chế độ ăn (diet_exclusions) và quy đổi mức lượng (qty_levels).';
COMMENT ON COLUMN food_groups.code IS 'Mã nhóm thực phẩm.';
COMMENT ON COLUMN food_groups.name_vi IS 'Tên nhóm tiếng Việt.';

COMMENT ON TABLE nutrient_sources IS 'Nguồn bảng thành phần thực phẩm: Bảng TPTP Việt Nam 2007, USDA SR Legacy, USDA Foundation.';
COMMENT ON COLUMN nutrient_sources.id IS 'Định danh nguồn (số nhỏ, cấp thủ công).';
COMMENT ON COLUMN nutrient_sources.code IS 'Mã nguồn: fct2007, usda_sr_legacy, usda_foundation.';
COMMENT ON COLUMN nutrient_sources.name IS 'Tên đầy đủ của nguồn.';
COMMENT ON COLUMN nutrient_sources.version IS 'Phiên bản hoặc ngày phát hành của bộ dữ liệu đã nạp.';
COMMENT ON COLUMN nutrient_sources.license IS 'Giấy phép sử dụng (ví dụ CC0 với USDA).';
COMMENT ON COLUMN nutrient_sources.url IS 'Địa chỉ tải dữ liệu gốc.';

COMMENT ON TABLE food_items IS 'Thực phẩm trong bảng thành phần nguồn; khoá tự nhiên là (nguồn, mã trong nguồn).';
COMMENT ON COLUMN food_items.source_id IS 'Nguồn bảng thành phần.';
COMMENT ON COLUMN food_items.source_code IS 'Mã thực phẩm trong bảng nguồn (mã TPTP 2007 hoặc FDC ID của USDA).';
COMMENT ON COLUMN food_items.name IS 'Tên theo nguồn; tên TPTP 2007 đã chuyển từ mã TCVN3 sang Unicode.';
COMMENT ON COLUMN food_items.name_en IS 'Tên tiếng Anh theo nguồn; NULL nếu nguồn không có.';
COMMENT ON COLUMN food_items.refuse_pct IS 'Tỷ lệ thải bỏ, % khối lượng lúc mua (0–100); phần ăn được EP = 100 − refuse_pct.';

COMMENT ON TABLE nutrients IS 'Danh mục chất dinh dưỡng dùng trong tính toán: năng lượng, protein, lipid, glucid, chất xơ, đường, natri.';
COMMENT ON COLUMN nutrients.code IS 'Mã chất: energy_kcal, protein_g, lipid_g, glucid_g, fiber_g, sugar_g, sodium_mg.';
COMMENT ON COLUMN nutrients.name_vi IS 'Tên chất tiếng Việt.';
COMMENT ON COLUMN nutrients.unit IS 'Đơn vị: kcal, g hoặc mg.';

COMMENT ON TABLE food_nutrients IS 'Hàm lượng chất dinh dưỡng của thực phẩm theo bảng nguồn.';
COMMENT ON COLUMN food_nutrients.source_id IS 'Nguồn bảng thành phần (cùng source_code tham chiếu food_items).';
COMMENT ON COLUMN food_nutrients.source_code IS 'Mã thực phẩm trong nguồn.';
COMMENT ON COLUMN food_nutrients.nutrient_code IS 'Chất dinh dưỡng.';
COMMENT ON COLUMN food_nutrients.per_100g IS 'Hàm lượng trên 100 g phần ăn được, đơn vị theo nutrients.unit.';

COMMENT ON TABLE allergen_groups IS 'Nhóm dị ứng (BR-ALG-02): 8 nhóm theo Codex CXS 1-1985 sửa 2024 và nhóm bổ sung đậu nành, nhuyễn thể.';
COMMENT ON COLUMN allergen_groups.code IS 'Mã nhóm dị ứng.';
COMMENT ON COLUMN allergen_groups.name_vi IS 'Tên tiếng Việt.';
COMMENT ON COLUMN allergen_groups.name_en IS 'Tên tiếng Anh.';
COMMENT ON COLUMN allergen_groups.basis IS 'Căn cứ: codex_2024 (Codex sửa 2024) hoặc tastoria_extra (bổ sung của Tastoria).';

COMMENT ON TABLE diets IS 'Chế độ ăn người dùng có thể chọn (v2: chay).';
COMMENT ON COLUMN diets.code IS 'Mã chế độ ăn.';
COMMENT ON COLUMN diets.name_vi IS 'Tên tiếng Việt.';

COMMENT ON TABLE diet_exclusions IS 'Nhóm thực phẩm bị loại theo từng chế độ ăn (BR-DIET-01).';
COMMENT ON COLUMN diet_exclusions.diet_code IS 'Chế độ ăn.';
COMMENT ON COLUMN diet_exclusions.food_group_code IS 'Nhóm thực phẩm bị loại.';

COMMENT ON TABLE ingredients IS 'Nguyên liệu của kho công thức; không xoá cứng, ngừng dùng bằng is_active = false (BR-CATALOG-01).';
COMMENT ON COLUMN ingredients.id IS 'Định danh nguyên liệu (UUID).';
COMMENT ON COLUMN ingredients.name_vi IS 'Tên chuẩn tiếng Việt; duy nhất trong các nguyên liệu đang dùng (ux_ingredients_name_vi_active, is_active = true).';
COMMENT ON COLUMN ingredients.food_group_code IS 'Nhóm thực phẩm, dùng cho chế độ ăn và mức lượng.';
COMMENT ON COLUMN ingredients.comp_source_id IS 'Nguồn bảng thành phần của thực phẩm tương ứng; NULL khi chưa ánh xạ.';
COMMENT ON COLUMN ingredients.comp_source_code IS 'Mã thực phẩm tương ứng trong nguồn; đi cặp với comp_source_id: cả hai cùng NULL hoặc cùng có giá trị (ck_ingredients_comp_pair), vì khoá ngoại ghép MATCH SIMPLE không kiểm khi một cột NULL.';
COMMENT ON COLUMN ingredients.is_staple IS 'true nếu là gia vị luôn có: miễn kiểm kho, không miễn kiểm dị ứng (BR-ALG-01).';
COMMENT ON COLUMN ingredients.countable IS 'true nếu đếm theo đơn vị (quả, bó...), quy đổi gam qua ingredient_units (BR-QTY-02).';
COMMENT ON COLUMN ingredients.shelf_life_days IS 'Thời hạn bảo quản ngăn mát L, đơn vị ngày (BR-FRESH-01); NULL nếu chưa có.';
COMMENT ON COLUMN ingredients.shelf_life_basis IS 'Căn cứ của L: mã FoodKeeper hoặc hiệu chỉnh của nhóm.';
COMMENT ON COLUMN ingredients.is_active IS 'false là ngừng dùng cho món mới; giữ bản ghi để món cũ vẫn tham chiếu được.';
COMMENT ON COLUMN ingredients.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';
COMMENT ON COLUMN ingredients.updated_at IS 'Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz).';

COMMENT ON TABLE ingredient_synonyms IS 'Tên gọi khác của nguyên liệu (tiếng Việt và tiếng Anh); dùng tìm kiếm và nối với Word2Vec trên Food.com.';
COMMENT ON COLUMN ingredient_synonyms.ingredient_id IS 'Nguyên liệu.';
COMMENT ON COLUMN ingredient_synonyms.synonym IS 'Tên gọi khác.';
COMMENT ON COLUMN ingredient_synonyms.lang IS 'Ngôn ngữ của tên: vi hoặc en.';
COMMENT ON COLUMN ingredient_synonyms.source IS 'Nguồn của tên gọi (ví dụ từ điển, biên soạn); NULL nếu do nhóm tự thêm.';

COMMENT ON TABLE ingredient_allergens IS 'Nguyên liệu thuộc nhóm dị ứng nào (quan hệ nhiều–nhiều).';
COMMENT ON COLUMN ingredient_allergens.ingredient_id IS 'Nguyên liệu.';
COMMENT ON COLUMN ingredient_allergens.allergen_code IS 'Nhóm dị ứng.';

COMMENT ON TABLE ingredient_units IS 'Quy đổi đơn vị đếm sang gam lúc mua cho nguyên liệu đếm được (BR-QTY-02).';
COMMENT ON COLUMN ingredient_units.ingredient_id IS 'Nguyên liệu.';
COMMENT ON COLUMN ingredient_units.unit_code IS 'Đơn vị đếm: qua, bo, cu, nhanh, mieng, goi, hop.';
COMMENT ON COLUMN ingredient_units.grams_per_unit IS 'Số gam lúc mua của một đơn vị (> 0), ví dụ 1 quả trứng gà = 50 g.';
COMMENT ON COLUMN ingredient_units.source IS 'Nguồn số liệu quy đổi.';

COMMENT ON TABLE qty_levels IS 'Quy đổi mức lượng ít/vừa/nhiều sang khoảng gam theo nhóm thực phẩm (BR-QTY-02).';
COMMENT ON COLUMN qty_levels.food_group_code IS 'Nhóm thực phẩm.';
COMMENT ON COLUMN qty_levels.level IS 'Mức lượng: it, vua, nhieu.';
COMMENT ON COLUMN qty_levels.g_min IS 'Cận dưới khoảng gam lúc mua.';
COMMENT ON COLUMN qty_levels.g_max IS 'Cận trên khoảng gam lúc mua (≥ g_min).';

COMMENT ON TABLE cooking_methods IS 'Cách nấu (luộc, xào, kho...); dùng cho món và ngữ cảnh cặp thay thế.';
COMMENT ON COLUMN cooking_methods.code IS 'Mã cách nấu.';
COMMENT ON COLUMN cooking_methods.name_vi IS 'Tên tiếng Việt.';

COMMENT ON TABLE tags IS 'Nhãn mô tả món theo vị, kết cấu, dịp ăn; dùng cho xếp hạng nội dung.';
COMMENT ON COLUMN tags.code IS 'Mã nhãn.';
COMMENT ON COLUMN tags.kind IS 'Loại nhãn: flavor (vị), texture (kết cấu), occasion (dịp).';
COMMENT ON COLUMN tags.name_vi IS 'Tên tiếng Việt.';

COMMENT ON TABLE recipes IS 'Món ăn trong kho công thức. Món published là bất biến: sửa thì tạo bản mới, bản cũ chuyển retired (BR-CATALOG-01). Tổng thời gian và nguyên liệu chính là giá trị dẫn xuất, không lưu.';
COMMENT ON COLUMN recipes.id IS 'Định danh món (UUID); mỗi bản sửa là một id mới.';
COMMENT ON COLUMN recipes.name_vi IS 'Tên món tiếng Việt; duy nhất trong các bản chưa retired (ux_recipes_name_vi_live), nên bản mới của món đã sửa (BR-CATALOG-01) giữ được tên cũ.';
COMMENT ON COLUMN recipes.slot IS 'Vị trí trong mâm: man (mặn), rau, canh (BR-TRAY-01).';
COMMENT ON COLUMN recipes.servings IS 'Số khẩu phần mà lượng gam trong recipe_ingredients áp dụng (> 0).';
COMMENT ON COLUMN recipes.method_code IS 'Cách nấu chính.';
COMMENT ON COLUMN recipes.status IS 'Trạng thái: draft, published, retired.';
COMMENT ON COLUMN recipes.notes IS 'Ghi chú biên soạn.';
COMMENT ON COLUMN recipes.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';
COMMENT ON COLUMN recipes.updated_at IS 'Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz).';

COMMENT ON TABLE recipe_ingredients IS 'Nguyên liệu của món và lượng dùng.';
COMMENT ON COLUMN recipe_ingredients.recipe_id IS 'Món.';
COMMENT ON COLUMN recipe_ingredients.ingredient_id IS 'Nguyên liệu.';
COMMENT ON COLUMN recipe_ingredients.grams IS 'Khối lượng lúc mua cho servings khẩu phần, gam (> 0); lượng cần cho n người = grams × n / servings (BR-TRAY-02).';
COMMENT ON COLUMN recipe_ingredients.role IS 'Vai trò trong món: main (chính), side (phụ), seasoning (gia vị).';
COMMENT ON COLUMN recipe_ingredients.is_optional IS 'true nếu có thể bỏ mà món vẫn nấu được.';

COMMENT ON TABLE recipe_steps IS 'Các bước nấu của món, dùng cho lịch nấu CP-SAT (BR-COOK-01).';
COMMENT ON COLUMN recipe_steps.recipe_id IS 'Món.';
COMMENT ON COLUMN recipe_steps.step_no IS 'Số thứ tự bước trong món; các bước làm theo thứ tự này.';
COMMENT ON COLUMN recipe_steps.text_vi IS 'Nội dung bước, tiếng Việt.';
COMMENT ON COLUMN recipe_steps.kind IS 'active (người nấu phải làm) hoặc passive (chờ, người nấu rảnh tay).';
COMMENT ON COLUMN recipe_steps.minutes IS 'Thời lượng bước, phút (> 0).';
COMMENT ON COLUMN recipe_steps.uses_burner IS 'true nếu bước chiếm một họng bếp.';

COMMENT ON TABLE recipe_tags IS 'Nhãn gắn cho món (quan hệ nhiều–nhiều).';
COMMENT ON COLUMN recipe_tags.recipe_id IS 'Món.';
COMMENT ON COLUMN recipe_tags.tag_code IS 'Nhãn.';

COMMENT ON TABLE recipe_sources IS 'Nguồn tham khảo của món (mỗi món ≥ 2 nguồn, nội dung viết lại bằng lời của nhóm).';
COMMENT ON COLUMN recipe_sources.recipe_id IS 'Món.';
COMMENT ON COLUMN recipe_sources.url IS 'Địa chỉ nguồn.';
COMMENT ON COLUMN recipe_sources.title IS 'Tiêu đề trang nguồn.';
COMMENT ON COLUMN recipe_sources.accessed_on IS 'Ngày truy cập nguồn.';

COMMENT ON TABLE recipe_nutrition IS 'Dinh dưỡng mỗi khẩu phần của món. Phi chuẩn hoá có kiểm soát: dẫn xuất từ recipe_ingredients × food_nutrients × EP (BR-NUT-05), job tính lại khi kho món hoặc bảng thành phần đổi.';
COMMENT ON COLUMN recipe_nutrition.recipe_id IS 'Món.';
COMMENT ON COLUMN recipe_nutrition.nutrient_code IS 'Chất dinh dưỡng.';
COMMENT ON COLUMN recipe_nutrition.per_serving IS 'Hàm lượng mỗi khẩu phần, đơn vị theo nutrients.unit.';
COMMENT ON COLUMN recipe_nutrition.computed_at IS 'Thời điểm tính.';
COMMENT ON COLUMN recipe_nutrition.data_version IS 'Phiên bản dữ liệu nguồn dùng khi tính (kho món, bảng thành phần).';

COMMENT ON TABLE vision_classes IS 'Lớp nhận dạng của mô hình phát hiện nguyên liệu trong ảnh.';
COMMENT ON COLUMN vision_classes.id IS 'Định danh lớp (số nhỏ).';
COMMENT ON COLUMN vision_classes.code IS 'Mã lớp, duy nhất.';
COMMENT ON COLUMN vision_classes.name_vi IS 'Tên tiếng Việt.';
COMMENT ON COLUMN vision_classes.name_en IS 'Tên tiếng Anh.';
COMMENT ON COLUMN vision_classes.countable IS 'true nếu đếm theo từng vật; false thì người dùng chọn mức ít/vừa/nhiều.';
COMMENT ON COLUMN vision_classes.instance_def IS 'Cách định nghĩa một thể hiện khi gán khung: item (một vật), group_of (một cụm), package (một gói).';
COMMENT ON COLUMN vision_classes.has_freshness_model IS 'true nếu lớp có bộ phân loại độ tươi.';

COMMENT ON TABLE vision_class_ingredients IS 'Ánh xạ lớp thị giác sang nguyên liệu (một lớp có thể ứng với nhiều nguyên liệu).';
COMMENT ON COLUMN vision_class_ingredients.vision_class_id IS 'Lớp thị giác.';
COMMENT ON COLUMN vision_class_ingredients.ingredient_id IS 'Nguyên liệu.';
COMMENT ON COLUMN vision_class_ingredients.is_default IS 'true nếu là nguyên liệu gán sẵn cho chip khi mô hình phát hiện lớp này.';

COMMENT ON TABLE profiles IS 'Hồ sơ dinh dưỡng của người dùng (users 1 — 0..1 profiles). Cột *_enc mã hoá AES-GCM ở tầng ứng dụng, chỉ module profile giải mã và mỗi lần giải mã ghi audit_log.';
COMMENT ON COLUMN profiles.user_id IS 'Người dùng sở hữu hồ sơ (khoá chính đồng thời là khoá ngoại).';
COMMENT ON COLUMN profiles.sex_enc IS 'Giới tính, mã hoá AES-GCM; NULL khi chưa đồng ý health_profile (BR-CONSENT-02).';
COMMENT ON COLUMN profiles.birth_year_enc IS 'Năm sinh, mã hoá AES-GCM; dùng kiểm ≥ 18 tuổi và chọn khoảng tuổi BMR (BR-NUT-01).';
COMMENT ON COLUMN profiles.height_cm_enc IS 'Chiều cao (cm), mã hoá AES-GCM.';
COMMENT ON COLUMN profiles.weight_kg_enc IS 'Cân nặng (kg), mã hoá AES-GCM; đầu vào BMR (BR-NUT-01).';
COMMENT ON COLUMN profiles.enc_key_id IS 'Định danh khoá đã mã hoá các cột *_enc (phục vụ xoay khoá).';
COMMENT ON COLUMN profiles.activity_level IS 'Mức vận động: light, moderate, heavy; PAL 1,50 / 1,75 / 2,00 (BR-NUT-02).';
COMMENT ON COLUMN profiles.goal IS 'Mục tiêu: maintain (giữ cân), lose (giảm cân), expert (theo chuyên gia).';
COMMENT ON COLUMN profiles.kcal_target IS 'Năng lượng mục tiêu E, kcal/ngày (800–5000); NULL là chưa có mục tiêu.';
COMMENT ON COLUMN profiles.kcal_source IS 'Nguồn của kcal_target: suggested (công thức gợi ý), user (tự nhập), expert (chuyên gia đặt).';
COMMENT ON COLUMN profiles.diet_code IS 'Chế độ ăn; NULL là không theo chế độ nào.';
COMMENT ON COLUMN profiles.updated_at IS 'Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz).';

COMMENT ON TABLE user_allergens IS 'Nhóm dị ứng người dùng đã khai (BR-ALG-01).';
COMMENT ON COLUMN user_allergens.user_id IS 'Người dùng.';
COMMENT ON COLUMN user_allergens.allergen_code IS 'Nhóm dị ứng.';

COMMENT ON TABLE user_favorite_recipes IS 'Món hay ăn người dùng chọn khi thiết lập (tối đa 5, kiểm ở service); dùng xếp hạng nội dung khi không có đồng ý personalization (BR-CONSENT-03).';
COMMENT ON COLUMN user_favorite_recipes.user_id IS 'Người dùng.';
COMMENT ON COLUMN user_favorite_recipes.recipe_id IS 'Món.';
COMMENT ON COLUMN user_favorite_recipes.created_at IS 'Thời điểm chọn.';

COMMENT ON TABLE user_settings IS 'Cài đặt bếp và mặc định của người dùng.';
COMMENT ON COLUMN user_settings.user_id IS 'Người dùng (khoá chính đồng thời là khoá ngoại).';
COMMENT ON COLUMN user_settings.burners IS 'Số họng bếp (1–4), mặc định 2; ràng buộc lịch nấu (BR-COOK-01).';
COMMENT ON COLUMN user_settings.default_persons IS 'Số người ăn mặc định (1–6), mặc định 2.';
COMMENT ON COLUMN user_settings.timezone IS 'Múi giờ IANA dùng hiển thị và tính ngày (v_journal_days); mặc định Asia/Ho_Chi_Minh; trigger trg_user_settings_timezone chỉ nhận tên có trong pg_timezone_names.';
COMMENT ON COLUMN user_settings.updated_at IS 'Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz).';

COMMENT ON TABLE pantry_lots IS 'Lô nguyên liệu trong kho của người dùng; mỗi lần thêm đồ tạo một lô (BR-PANTRY-01). Lượng hiện tại = initial + Σ giao dịch (v_pantry_lot_balance); độ gấp u tính lúc đọc, không lưu (BR-FRESH-05).';
COMMENT ON COLUMN pantry_lots.id IS 'Định danh lô (UUID).';
COMMENT ON COLUMN pantry_lots.user_id IS 'Chủ kho.';
COMMENT ON COLUMN pantry_lots.ingredient_id IS 'Nguyên liệu.';
COMMENT ON COLUMN pantry_lots.initial_g_min IS 'Cận dưới lượng ban đầu, gam lúc mua (≥ 0, BR-QTY-01).';
COMMENT ON COLUMN pantry_lots.initial_g_max IS 'Cận trên lượng ban đầu, gam lúc mua (≥ initial_g_min).';
COMMENT ON COLUMN pantry_lots.acquired_at IS 'Ngày mua người dùng nhập, nếu không thì lần đầu thấy trong ảnh quét; mốc tính u_time (BR-FRESH-01).';
COMMENT ON COLUMN pantry_lots.acquired_basis IS 'Căn cứ của acquired_at: purchase_date_entered (người dùng nhập) hoặc first_seen (lần đầu thấy) (BR-FRESH-03).';
COMMENT ON COLUMN pantry_lots.status IS 'Trạng thái lô: in_stock, used_up, discarded, not_seen (quét toàn tủ không thấy, BR-PANTRY-03).';
COMMENT ON COLUMN pantry_lots.p_tuoi IS 'Xác suất lớp tươi ở lần quan sát mới nhất của lô (bộ phân loại độ tươi đã hiệu chỉnh nhiệt độ, BR-FRESH-02).';
COMMENT ON COLUMN pantry_lots.p_dung_som IS 'Xác suất lớp nên dùng sớm ở lần quan sát mới nhất.';
COMMENT ON COLUMN pantry_lots.p_dung_ngay IS 'Xác suất lớp dùng ngay ở lần quan sát mới nhất.';
COMMENT ON COLUMN pantry_lots.p_kiem_tra IS 'Xác suất lớp kiểm tra trước khi dùng ở lần quan sát mới nhất.';
COMMENT ON COLUMN pantry_lots.freshness_observed_at IS 'Thời điểm quan sát độ tươi mới nhất; NULL nếu lô chưa có ảnh độ tươi (khi đó u = u_time).';
COMMENT ON COLUMN pantry_lots.freshness_model_version_id IS 'Phiên bản bộ phân loại độ tươi đã cho các xác suất p_*.';
COMMENT ON COLUMN pantry_lots.user_checked_at IS 'Thời điểm người dùng xác nhận đồ ở mức kiểm tra vẫn dùng được (BR-FRESH-04).';
COMMENT ON COLUMN pantry_lots.source_scan_item_id IS 'Chip quét đã tạo ra lô; NULL nếu nhập tay hoặc chip đã bị xoá.';
COMMENT ON COLUMN pantry_lots.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';
COMMENT ON COLUMN pantry_lots.updated_at IS 'Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz).';

COMMENT ON TABLE pantry_transactions IS 'Giao dịch kho, chỉ ghi thêm; hoàn tác bằng giao dịch đảo trỏ reverses_id (BR-PANTRY-02).';
COMMENT ON COLUMN pantry_transactions.id IS 'Số thứ tự giao dịch (identity).';
COMMENT ON COLUMN pantry_transactions.lot_id IS 'Lô bị thay đổi.';
COMMENT ON COLUMN pantry_transactions.delta_g_min IS 'Thay đổi cận dưới, gam lúc mua; âm là trừ.';
COMMENT ON COLUMN pantry_transactions.delta_g_max IS 'Thay đổi cận trên, gam lúc mua; âm là trừ.';
COMMENT ON COLUMN pantry_transactions.reason IS 'Lý do: scan_add, cook_deduct, manual_edit, discard, undo.';
COMMENT ON COLUMN pantry_transactions.ref_type IS 'Loại đối tượng gây ra giao dịch: scan, cook_session, user; NULL nếu không có.';
COMMENT ON COLUMN pantry_transactions.ref_id IS 'Id của đối tượng theo ref_type (scans.id, cook_sessions.id hoặc users.id = chủ lô); tham chiếu đa hình: không có khoá ngoại, trigger trg_pantry_transactions_ref kiểm tồn tại và cùng chủ lúc ghi; đi cặp với ref_type (ck_pantry_transactions_ref_pair).';
COMMENT ON COLUMN pantry_transactions.reverses_id IS 'Giao dịch bị đảo bởi giao dịch này; khác NULL đúng khi reason = undo (ck_pantry_transactions_undo); duy nhất: mỗi giao dịch bị đảo tối đa một lần.';
COMMENT ON COLUMN pantry_transactions.urgency_at_event IS 'Độ gấp u của lô tại thời điểm giao dịch (ảnh chụp, BR-FRESH-05); dùng đếm lô gấp được dùng kịp trong nhật ký.';
COMMENT ON COLUMN pantry_transactions.created_at IS 'Thời điểm ghi giao dịch.';

COMMENT ON TABLE model_versions IS 'Phiên bản mô hình học máy đã đăng ký (UC29). Bản đang chạy xác định duy nhất qua model_deployments.';
COMMENT ON COLUMN model_versions.id IS 'Định danh phiên bản (UUID).';
COMMENT ON COLUMN model_versions.name IS 'Loại mô hình: detector, freshness, ranker, substitution.';
COMMENT ON COLUMN model_versions.version IS 'Nhãn phiên bản, duy nhất trong mỗi loại.';
COMMENT ON COLUMN model_versions.artifact_key IS 'Khoá tệp trọng số trong kho lưu trữ.';
COMMENT ON COLUMN model_versions.sha256 IS 'SHA-256 của tệp trọng số, kiểm khi nạp.';
COMMENT ON COLUMN model_versions.preprocess_version IS 'Phiên bản bước tiền xử lý ảnh đi kèm; NULL với mô hình không dùng ảnh.';
COMMENT ON COLUMN model_versions.metrics IS 'Chỉ số đánh giá (JSON), là báo cáo, không truy vấn.';
COMMENT ON COLUMN model_versions.gate_report_key IS 'Khoá tệp báo cáo kiểm định; NULL nếu chưa kiểm định.';
COMMENT ON COLUMN model_versions.mlflow_run_id IS 'Mã lượt chạy MLflow sinh ra mô hình.';
COMMENT ON COLUMN model_versions.status IS 'Trạng thái: candidate, validated, rejected, retired.';
COMMENT ON COLUMN model_versions.created_at IS 'Thời điểm đăng ký.';

COMMENT ON TABLE model_version_classes IS 'Bản đồ chỉ số đầu ra của mô hình sang lớp thị giác, theo từng phiên bản.';
COMMENT ON COLUMN model_version_classes.model_version_id IS 'Phiên bản mô hình.';
COMMENT ON COLUMN model_version_classes.class_index IS 'Chỉ số lớp ở đầu ra mô hình.';
COMMENT ON COLUMN model_version_classes.vision_class_id IS 'Lớp thị giác tương ứng.';

COMMENT ON TABLE model_deployments IS 'Con trỏ triển khai: mỗi loại mô hình có đúng một phiên bản đang chạy (UC30).';
COMMENT ON COLUMN model_deployments.name IS 'Loại mô hình (khoá chính).';
COMMENT ON COLUMN model_deployments.active_version_id IS 'Phiên bản đang chạy.';
COMMENT ON COLUMN model_deployments.previous_version_id IS 'Phiên bản chạy trước đó, dùng khi quay lui; NULL nếu chưa có.';
COMMENT ON COLUMN model_deployments.switched_at IS 'Thời điểm chuyển phiên bản gần nhất.';
COMMENT ON COLUMN model_deployments.switched_by IS 'Nhân sự đã chuyển phiên bản; NULL nếu tài khoản đã xoá.';

COMMENT ON TABLE scans IS 'Một lượt quét nguyên liệu (UC12): 1–2 ảnh, job suy luận chạy ở worker.';
COMMENT ON COLUMN scans.id IS 'Định danh lượt quét (UUID).';
COMMENT ON COLUMN scans.user_id IS 'Người quét.';
COMMENT ON COLUMN scans.mode IS 'Chế độ: fridge (toàn tủ) hoặc haul (đồ vừa mua) (BR-PANTRY-03).';
COMMENT ON COLUMN scans.status IS 'Trạng thái: queued, processing, done, failed, expired, confirmed, discarded.';
COMMENT ON COLUMN scans.error_code IS 'Mã lỗi khi status = failed; NULL nếu không lỗi.';
COMMENT ON COLUMN scans.attempts IS 'Số lần worker đã thử xử lý.';
COMMENT ON COLUMN scans.detector_version_id IS 'Phiên bản mô hình phát hiện đã dùng.';
COMMENT ON COLUMN scans.classifier_version_id IS 'Phiên bản bộ phân loại độ tươi đã dùng.';
COMMENT ON COLUMN scans.preprocess_version IS 'Phiên bản tiền xử lý ảnh đã dùng.';
COMMENT ON COLUMN scans.enqueued_at IS 'Thời điểm đưa job vào hàng đợi.';
COMMENT ON COLUMN scans.started_at IS 'Thời điểm worker bắt đầu xử lý.';
COMMENT ON COLUMN scans.finished_at IS 'Thời điểm worker xử lý xong (done hoặc failed).';
COMMENT ON COLUMN scans.confirmed_at IS 'Thời điểm người dùng xác nhận ghi kho (BR-SCAN-02).';
COMMENT ON COLUMN scans.created_at IS 'Thời điểm tạo lượt quét.';

COMMENT ON TABLE scan_images IS 'Ảnh của lượt quét; ảnh gốc xoá sau 30 ngày trừ khi đã đồng ý góp ảnh (BR-RETAIN-01).';
COMMENT ON COLUMN scan_images.id IS 'Định danh ảnh (UUID).';
COMMENT ON COLUMN scan_images.scan_id IS 'Lượt quét.';
COMMENT ON COLUMN scan_images.ordinal IS 'Thứ tự ảnh trong lượt quét (1–2).';
COMMENT ON COLUMN scan_images.shelf_group IS 'Nhóm ngăn: cùng số là cùng ngăn (số đếm lấy max), khác số thì cộng (BR-SCAN-01).';
COMMENT ON COLUMN scan_images.storage_key IS 'Khoá tệp ảnh trong kho lưu trữ, duy nhất.';
COMMENT ON COLUMN scan_images.width IS 'Chiều rộng ảnh, pixel.';
COMMENT ON COLUMN scan_images.height IS 'Chiều cao ảnh, pixel.';
COMMENT ON COLUMN scan_images.contributed IS 'true nếu người dùng góp ảnh (đồng ý photo_contribution); ảnh không bị xoá sau 30 ngày.';
COMMENT ON COLUMN scan_images.purged_at IS 'Thời điểm tệp ảnh đã bị xoá (UC32); NULL nếu còn.';

COMMENT ON TABLE scan_items IS 'Chip kết quả quét: một nguyên liệu và số lượng chờ người dùng xác nhận; chỉ ghi vào kho khi xác nhận (BR-SCAN-02).';
COMMENT ON COLUMN scan_items.id IS 'Định danh chip (UUID).';
COMMENT ON COLUMN scan_items.scan_id IS 'Lượt quét.';
COMMENT ON COLUMN scan_items.ingredient_id IS 'Nguyên liệu hiện tại của chip (sau khi người dùng sửa nếu có).';
COMMENT ON COLUMN scan_items.origin IS 'Nguồn chip: model (mô hình phát hiện) hoặc user_added (người dùng thêm).';
COMMENT ON COLUMN scan_items.model_count IS 'Số đếm do mô hình đưa ra; NULL với chip người dùng thêm hoặc lớp không đếm.';
COMMENT ON COLUMN scan_items.final_count IS 'Số đếm sau khi người dùng xác nhận hoặc sửa.';
COMMENT ON COLUMN scan_items.qty_level IS 'Mức lượng it/vua/nhieu với nguyên liệu không đếm được (BR-QTY-02).';
COMMENT ON COLUMN scan_items.user_action IS 'Thao tác người dùng: kept, relabeled, deleted, edited.';
COMMENT ON COLUMN scan_items.original_ingredient_id IS 'Nguyên liệu mô hình đề xuất ban đầu khi người dùng đổi nhãn; NULL nếu không đổi.';
COMMENT ON COLUMN scan_items.user_freshness IS 'Nhãn độ tươi người dùng chọn: tuoi, dung_som, dung_ngay, kiem_tra; NULL nếu không chọn.';
COMMENT ON COLUMN scan_items.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';
COMMENT ON COLUMN scan_items.updated_at IS 'Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz).';

COMMENT ON TABLE detections IS 'Khung phát hiện của mô hình trên từng ảnh, kèm xác suất độ tươi.';
COMMENT ON COLUMN detections.id IS 'Số thứ tự khung (identity).';
COMMENT ON COLUMN detections.scan_image_id IS 'Ảnh chứa khung.';
COMMENT ON COLUMN detections.scan_item_id IS 'Chip mà khung được gộp vào; NULL nếu chưa gộp hoặc chip đã xoá.';
COMMENT ON COLUMN detections.vision_class_id IS 'Lớp thị giác dự đoán.';
COMMENT ON COLUMN detections.x1 IS 'Toạ độ trái, chuẩn hoá theo chiều rộng ảnh [0, 1].';
COMMENT ON COLUMN detections.y1 IS 'Toạ độ trên, chuẩn hoá theo chiều cao ảnh [0, 1].';
COMMENT ON COLUMN detections.x2 IS 'Toạ độ phải, chuẩn hoá [0, 1], lớn hơn x1.';
COMMENT ON COLUMN detections.y2 IS 'Toạ độ dưới, chuẩn hoá [0, 1], lớn hơn y1.';
COMMENT ON COLUMN detections.confidence IS 'Độ tin cậy của khung do mô hình phát hiện đưa ra.';
COMMENT ON COLUMN detections.p_tuoi IS 'Xác suất lớp tươi của khung; NULL nếu lớp không có bộ phân loại độ tươi.';
COMMENT ON COLUMN detections.p_dung_som IS 'Xác suất lớp nên dùng sớm của khung.';
COMMENT ON COLUMN detections.p_dung_ngay IS 'Xác suất lớp dùng ngay của khung.';
COMMENT ON COLUMN detections.p_kiem_tra IS 'Xác suất lớp kiểm tra trước khi dùng của khung.';

COMMENT ON TABLE substitution_pairs IS '[Bản VP: uq_substitution_pairs_ctx mất NULLS NOT DISTINCT, context NULL có thể trùng] Cặp thay thế nguyên liệu có ngữ cảnh (slot, cách nấu), do nhóm biên soạn hoặc mô hình đề xuất (UC26).';
COMMENT ON COLUMN substitution_pairs.id IS 'Định danh cặp (UUID).';
COMMENT ON COLUMN substitution_pairs.ingredient_id IS 'Nguyên liệu gốc bị thiếu.';
COMMENT ON COLUMN substitution_pairs.substitute_id IS 'Nguyên liệu thay thế, khác nguyên liệu gốc.';
COMMENT ON COLUMN substitution_pairs.context_slot IS 'Slot áp dụng; NULL là mọi slot.';
COMMENT ON COLUMN substitution_pairs.context_method_code IS 'Cách nấu áp dụng; NULL là mọi cách nấu.';
COMMENT ON COLUMN substitution_pairs.ratio IS 'Tỷ lệ gam thay thế trên gam gốc, mặc định 1.';
COMMENT ON COLUMN substitution_pairs.score IS 'Điểm phù hợp của cặp, dùng xếp hạng gợi ý.';
COMMENT ON COLUMN substitution_pairs.source IS 'Nguồn của cặp (tài liệu, biên soạn, mô hình).';
COMMENT ON COLUMN substitution_pairs.curated IS 'true nếu do nhóm biên soạn và duyệt.';

COMMENT ON TABLE ingredient_embeddings IS 'Vector biểu diễn nguyên liệu (Word2Vec skip-gram trên danh sách nguyên liệu), theo phiên bản mô hình substitution.';
COMMENT ON COLUMN ingredient_embeddings.ingredient_id IS 'Nguyên liệu.';
COMMENT ON COLUMN ingredient_embeddings.model_version_id IS 'Phiên bản mô hình sinh vector.';
COMMENT ON COLUMN ingredient_embeddings.vector IS 'Vector 100 chiều (pgvector); so sánh bằng cosine, không dùng chỉ mục ANN.';

COMMENT ON TABLE shopping_items IS 'Danh sách đi chợ của người dùng (UC18).';
COMMENT ON COLUMN shopping_items.id IS 'Định danh mục (UUID).';
COMMENT ON COLUMN shopping_items.user_id IS 'Người dùng.';
COMMENT ON COLUMN shopping_items.ingredient_id IS 'Nguyên liệu cần mua.';
COMMENT ON COLUMN shopping_items.qty_g IS 'Lượng cần mua, gam lúc mua; NULL nếu không ghi.';
COMMENT ON COLUMN shopping_items.note IS 'Ghi chú tự do của người dùng.';
COMMENT ON COLUMN shopping_items.status IS 'Trạng thái: open, bought, dropped.';
COMMENT ON COLUMN shopping_items.source_meal_plan_item_id IS 'Món trong mâm sinh ra mục này (Thiếu gì?, UC17); NULL nếu tự thêm hoặc món đã xoá.';
COMMENT ON COLUMN shopping_items.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';
COMMENT ON COLUMN shopping_items.updated_at IS 'Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz).';

COMMENT ON TABLE meal_plans IS 'Mâm cơm đề xuất cho một bữa (UC15). Các cột kcal là ảnh chụp lịch sử lúc tạo, không phải dẫn xuất lặp.';
COMMENT ON COLUMN meal_plans.id IS 'Định danh mâm (UUID).';
COMMENT ON COLUMN meal_plans.user_id IS 'Người dùng.';
COMMENT ON COLUMN meal_plans.meal IS 'Bữa: lunch (trưa) hoặc dinner (tối).';
COMMENT ON COLUMN meal_plans.persons IS 'Số người ăn n (1–6, BR-TRAY-01).';
COMMENT ON COLUMN meal_plans.max_minutes IS 'Thời gian nấu tối đa người dùng chọn, phút (10–180, BR-TRAY-05).';
COMMENT ON COLUMN meal_plans.status IS 'Trạng thái: proposed, accepted, cooked, abandoned, expired.';
COMMENT ON COLUMN meal_plans.e_target_kcal IS 'Năng lượng mục tiêu của mâm E_mâm, kcal, chụp lúc tạo (BR-NUT-04, BR-TRAY-07); NULL khi chưa có mục tiêu.';
COMMENT ON COLUMN meal_plans.kcal_low IS 'Cận dưới khoảng kcal/người của mâm (BR-NUT-06); NULL khi chưa hiệu chỉnh.';
COMMENT ON COLUMN meal_plans.kcal_high IS 'Cận trên khoảng kcal/người của mâm; NULL khi chưa hiệu chỉnh.';
COMMENT ON COLUMN meal_plans.rice_bowls_per_person IS 'Số bát cơm gợi ý mỗi người (0,5–3, bước 0,5; BR-TRAY-03); NULL khi chưa có mục tiêu.';
COMMENT ON COLUMN meal_plans.reason_vi IS 'Dòng lý do hiển thị cho người dùng.';
COMMENT ON COLUMN meal_plans.ranker_version_id IS 'Phiên bản mô hình xếp hạng đã dùng; NULL khi dùng xếp hạng mặc định.';
COMMENT ON COLUMN meal_plans.params_version IS 'Phiên bản bộ tham số cấu hình (ngưỡng, hệ số) lúc ghép mâm. Chưa có bảng tham số có phiên bản để làm đích khoá ngoại (đề xuất ở 04 mục 6).';
COMMENT ON COLUMN meal_plans.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';
COMMENT ON COLUMN meal_plans.updated_at IS 'Thời điểm cập nhật bản ghi gần nhất (giờ server, timestamptz).';

COMMENT ON TABLE meal_plan_coeater_allergens IS 'Nhóm dị ứng của người ăn cùng trong bữa này (BR-ALG-01); không lưu danh tính người ăn cùng.';
COMMENT ON COLUMN meal_plan_coeater_allergens.meal_plan_id IS 'Mâm.';
COMMENT ON COLUMN meal_plan_coeater_allergens.allergen_code IS 'Nhóm dị ứng.';

COMMENT ON TABLE meal_plan_pins IS 'Lô người dùng ghim phải dùng trong mâm (tối đa 2, mỗi lô dùng ≥ 50% g_min; BR-TRAY-08).';
COMMENT ON COLUMN meal_plan_pins.meal_plan_id IS 'Mâm.';
COMMENT ON COLUMN meal_plan_pins.lot_id IS 'Lô được ghim.';

COMMENT ON TABLE meal_plan_items IS 'Món trong mâm theo slot; đổi món tạo dòng mới và chuyển dòng cũ sang swapped_out; mỗi slot có tối đa một dòng active.';
COMMENT ON COLUMN meal_plan_items.id IS 'Định danh dòng món (UUID).';
COMMENT ON COLUMN meal_plan_items.meal_plan_id IS 'Mâm.';
COMMENT ON COLUMN meal_plan_items.slot IS 'Slot: man, rau, canh; khoá ngoại ghép (recipe_id, slot) bảo đảm khớp slot của món.';
COMMENT ON COLUMN meal_plan_items.recipe_id IS 'Món (đúng bản đã dùng, BR-CATALOG-01).';
COMMENT ON COLUMN meal_plan_items.status IS 'active hoặc swapped_out (đã bị đổi ra).';
COMMENT ON COLUMN meal_plan_items.replaced_item_id IS 'Dòng món bị dòng này thay thế khi đổi món; NULL với món ban đầu.';
COMMENT ON COLUMN meal_plan_items.swap_reason IS 'Lý do đổi khi dòng bị đổi ra: khong_hop_gu, moi_an, thieu_thoi_gian, khac (BR-SWAP-01).';
COMMENT ON COLUMN meal_plan_items.rank_score IS 'Điểm xếp hạng gu của món lúc ghép.';
COMMENT ON COLUMN meal_plan_items.servings_scale IS 'Hệ số nhân lượng nguyên liệu = n / servings (BR-TRAY-02).';
COMMENT ON COLUMN meal_plan_items.kcal_per_person IS 'Năng lượng món mỗi người, kcal, dẫn xuất từ recipe_nutrition × servings_scale và thay thế nguyên liệu; tính lại trong cùng giao dịch ghi meal_plan_item_substitutions, chỉ khi món active và mâm proposed/accepted (trg_meal_plan_items_guard); NULL nế...';
COMMENT ON COLUMN meal_plan_items.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';

COMMENT ON TABLE meal_plan_item_substitutions IS 'Thay thế nguyên liệu người dùng đã chọn cho một món trong mâm (UC17).';
COMMENT ON COLUMN meal_plan_item_substitutions.item_id IS 'Dòng món trong mâm.';
COMMENT ON COLUMN meal_plan_item_substitutions.original_ingredient_id IS 'Nguyên liệu gốc bị thay.';
COMMENT ON COLUMN meal_plan_item_substitutions.substitute_ingredient_id IS 'Nguyên liệu thay thế.';
COMMENT ON COLUMN meal_plan_item_substitutions.grams IS 'Lượng nguyên liệu thay thế, gam lúc mua.';
COMMENT ON COLUMN meal_plan_item_substitutions.origin IS 'Nguồn gợi ý: lookup (bảng tra), embedding (Word2Vec), user (người dùng tự chọn).';
COMMENT ON COLUMN meal_plan_item_substitutions.created_at IS 'Thời điểm chọn thay thế.';

COMMENT ON TABLE cook_sessions IS 'Phiên nấu cả mâm (UC19); meal_plans 1 — 0..* cook_sessions; không lưu user_id, truy chủ qua meal_plans.';
COMMENT ON COLUMN cook_sessions.id IS 'Định danh phiên (UUID).';
COMMENT ON COLUMN cook_sessions.meal_plan_id IS 'Mâm được nấu.';
COMMENT ON COLUMN cook_sessions.status IS 'Trạng thái: in_progress, completed, reverted, abandoned.';
COMMENT ON COLUMN cook_sessions.serve_at IS 'Giờ dọn cơm mong muốn; mọi món xong trong cửa sổ 5 phút trước giờ này (BR-COOK-01).';
COMMENT ON COLUMN cook_sessions.burners IS 'Số họng bếp chụp lúc tạo phiên.';
COMMENT ON COLUMN cook_sessions.started_at IS 'Thời điểm bắt đầu nấu; mốc của các offset trong cook_schedule_entries.';
COMMENT ON COLUMN cook_sessions.completed_at IS 'Thời điểm bấm nấu xong (BR-COOK-02); NULL nếu chưa xong.';
COMMENT ON COLUMN cook_sessions.reverted_at IS 'Thời điểm hoàn tác trừ kho (trong 10 phút, BR-PANTRY-02); NULL nếu không hoàn tác.';
COMMENT ON COLUMN cook_sessions.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';

COMMENT ON TABLE cook_schedule_entries IS 'Lịch nấu của phiên: thời điểm bắt đầu và kết thúc từng bước (CP-SAT, BR-COOK-01).';
COMMENT ON COLUMN cook_schedule_entries.cook_session_id IS 'Phiên nấu.';
COMMENT ON COLUMN cook_schedule_entries.recipe_id IS 'Món chứa bước.';
COMMENT ON COLUMN cook_schedule_entries.step_no IS 'Số thứ tự bước trong món.';
COMMENT ON COLUMN cook_schedule_entries.start_offset_s IS 'Thời điểm bắt đầu bước, giây tính từ đầu lịch.';
COMMENT ON COLUMN cook_schedule_entries.end_offset_s IS 'Thời điểm kết thúc bước, giây tính từ đầu lịch (> start_offset_s).';

COMMENT ON TABLE interactions IS 'Tương tác của người dùng với món, chỉ ghi khi có đồng ý personalization (BR-CONSENT-03); chống trùng theo event_id. Khoá ngoại ghép (meal_plan_id, user_id) bảo đảm user_id khớp chủ mâm.';
COMMENT ON COLUMN interactions.id IS 'event_id do app sinh (UUID); gửi lại cùng id không tạo bản ghi mới.';
COMMENT ON COLUMN interactions.user_id IS 'Người dùng.';
COMMENT ON COLUMN interactions.recipe_id IS 'Món.';
COMMENT ON COLUMN interactions.meal_plan_id IS 'Mâm chứa món; NULL nếu tương tác ngoài mâm.';
COMMENT ON COLUMN interactions.meal_plan_item_id IS 'Dòng món trong mâm; NULL nếu không gắn dòng nào. Khoá ngoại ghép (meal_plan_item_id, meal_plan_id, recipe_id) buộc mâm và món khớp dòng đó.';
COMMENT ON COLUMN interactions.type IS 'Loại: served, viewed, swapped, cooked, liked, disliked, undone.';
COMMENT ON COLUMN interactions.position IS 'Vị trí món trong danh sách hiển thị; NULL nếu không áp dụng.';
COMMENT ON COLUMN interactions.swap_reason IS 'Lý do đổi khi type = swapped (BR-SWAP-01).';
COMMENT ON COLUMN interactions.ranker_version_id IS 'Phiên bản mô hình xếp hạng lúc hiển thị.';
COMMENT ON COLUMN interactions.propensity IS 'Xác suất món được hiển thị theo chính sách xếp hạng lúc đó; dùng đánh giá ngoại tuyến.';
COMMENT ON COLUMN interactions.occurred_at IS 'Thời điểm xảy ra theo đồng hồ app.';
COMMENT ON COLUMN interactions.received_at IS 'Thời điểm server nhận.';

COMMENT ON TABLE survey_forms IS 'Phiếu khảo sát gu theo khối không đầy đủ: mỗi người chấm các món neo chung và một nhóm món ngẫu nhiên (UC24).';
COMMENT ON COLUMN survey_forms.id IS 'Định danh phiếu (UUID).';
COMMENT ON COLUMN survey_forms.version IS 'Nhãn phiên bản phiếu, duy nhất.';
COMMENT ON COLUMN survey_forms.n_anchor IS 'Số món neo mọi người cùng chấm.';
COMMENT ON COLUMN survey_forms.n_random IS 'Số món ngẫu nhiên giao thêm cho mỗi người.';
COMMENT ON COLUMN survey_forms.is_open IS 'true khi phiếu đang nhận trả lời.';
COMMENT ON COLUMN survey_forms.created_at IS 'Thời điểm tạo bản ghi (giờ server, timestamptz).';

COMMENT ON TABLE survey_form_anchors IS 'Danh sách món neo của phiếu.';
COMMENT ON COLUMN survey_form_anchors.form_id IS 'Phiếu.';
COMMENT ON COLUMN survey_form_anchors.recipe_id IS 'Món neo.';

COMMENT ON TABLE survey_respondents IS 'Người tham gia khảo sát ẩn danh, không cần tài khoản (A03).';
COMMENT ON COLUMN survey_respondents.id IS 'Định danh ẩn danh của người tham gia (UUID).';
COMMENT ON COLUMN survey_respondents.form_id IS 'Phiếu đang trả lời.';
COMMENT ON COLUMN survey_respondents.policy_version_id IS 'Phiên bản điều khoản mục đích survey đã đồng ý.';
COMMENT ON COLUMN survey_respondents.consented_at IS 'Thời điểm đồng ý.';
COMMENT ON COLUMN survey_respondents.completed_at IS 'Thời điểm hoàn thành phiếu; NULL nếu chưa xong.';
COMMENT ON COLUMN survey_respondents.channel IS 'Kênh vào khảo sát: link hoặc qr.';

COMMENT ON TABLE survey_assignments IS 'Món giao cho từng người tham gia và thứ tự hiển thị.';
COMMENT ON COLUMN survey_assignments.respondent_id IS 'Người tham gia.';
COMMENT ON COLUMN survey_assignments.recipe_id IS 'Món được giao.';
COMMENT ON COLUMN survey_assignments.display_order IS 'Thứ tự hiển thị.';
COMMENT ON COLUMN survey_assignments.is_anchor IS 'true nếu là món neo.';

COMMENT ON TABLE survey_ratings IS 'Điểm người tham gia chấm cho món được giao; chỉ chấm món đã giao (khoá ngoại ghép tới survey_assignments).';
COMMENT ON COLUMN survey_ratings.respondent_id IS 'Người tham gia.';
COMMENT ON COLUMN survey_ratings.recipe_id IS 'Món.';
COMMENT ON COLUMN survey_ratings.rating IS 'Điểm 1–5; NULL khi chọn chưa ăn bao giờ.';
COMMENT ON COLUMN survey_ratings.never_eaten IS 'true nếu người tham gia chưa ăn món này (khi đó rating là NULL).';
COMMENT ON COLUMN survey_ratings.answered_at IS 'Thời điểm trả lời.';

COMMENT ON TABLE survey_favorites IS 'Món hay ăn người tham gia khảo sát chọn.';
COMMENT ON COLUMN survey_favorites.respondent_id IS 'Người tham gia.';
COMMENT ON COLUMN survey_favorites.recipe_id IS 'Món.';

COMMIT;
