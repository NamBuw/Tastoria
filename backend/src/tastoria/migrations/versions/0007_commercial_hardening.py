"""Commercial hardening: meal_logs, email_outbox/verification, user MFA, app_params, roles, indexes, policies.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSION = "2026-11-24"
EFFECTIVE_FROM = "2026-11-24T00:00:00+07:00"

POLICIES = [
    {
        "code": "health_profile",
        "sha256": "f2b722cd5804ee6e4eed1bf21a6d5e9bafd1f6f4b9b63bbe5af270799588c4ff",
    },
    {
        "code": "survey",
        "sha256": "8ae3b79fc8541baf74fa191ade9c5bc3e0877b74e54e8b8c91edc74c2fa7cc8b",
    },
]

UPGRADE_SQL = """
CREATE TYPE meal_log_slot_t AS ENUM ('sang', 'trua', 'toi', 'phu');
CREATE TYPE meal_log_source_t AS ENUM ('scan_calorie', 'barcode', 'manual', 'recipe');
CREATE TYPE meal_log_item_kind_t AS ENUM ('dish', 'modifier', 'barcode_item', 'manual_item');
CREATE TYPE email_outbox_status_t AS ENUM ('pending', 'sending', 'sent', 'failed');

CREATE TABLE app_params (
    key text NOT NULL,
    value_num double precision,
    value_text text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_app_params PRIMARY KEY (key)
);

INSERT INTO app_params (key, value_num) VALUES
    ('fresh_u_soon', 0.5),
    ('fresh_u_check', 1.0),
    ('rice_bowl_kcal', 200.0),
    ('kcal_half_width', 0.15)
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION app_param(p_key text) RETURNS numeric
LANGUAGE sql STABLE PARALLEL SAFE
SET search_path = public, pg_temp
AS $$
    SELECT CASE
        WHEN EXISTS (SELECT 1 FROM public.app_params WHERE key = p_key)
            THEN (SELECT value_num::numeric FROM public.app_params WHERE key = p_key)
        ELSE NULLIF(pg_catalog.current_setting('tastoria.' || p_key, true), '')::numeric
    END
$$;

COMMENT ON TABLE app_params IS 'Tham số nghiệp vụ lưu trong bảng để bền vững qua pg_dump/pg_restore (thay thế ALTER DATABASE GUC).';
COMMENT ON FUNCTION app_param(text) IS 'Đọc tham số nghiệp vụ từ app_params (ưu tiên) hoặc GUC tastoria.<khoá>; NULL khi chưa đặt.';

ALTER TABLE idempotency_keys
    ADD COLUMN response_headers jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE users
    ADD COLUMN email_verified_at timestamptz,
    ADD COLUMN totp_secret_enc bytea,
    ADD COLUMN totp_key_id text,
    ADD COLUMN mfa_enabled_at timestamptz,
    ADD CONSTRAINT ck_users_totp_enc_key CHECK (totp_secret_enc IS NULL OR totp_key_id IS NOT NULL),
    ADD CONSTRAINT ck_users_mfa_enabled CHECK (mfa_enabled_at IS NULL OR totp_secret_enc IS NOT NULL);

ALTER TABLE refresh_tokens
    ADD COLUMN ip_address text,
    ADD COLUMN last_used_at timestamptz;

CREATE TABLE email_outbox (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid,
    to_email citext NOT NULL,
    template text NOT NULL,
    subject text NOT NULL,
    body_text text NOT NULL,
    status email_outbox_status_t NOT NULL DEFAULT 'pending',
    attempts smallint NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_email_outbox PRIMARY KEY (id),
    CONSTRAINT ck_email_outbox_attempts CHECK (attempts >= 0),
    CONSTRAINT fk_email_outbox_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_email_outbox_status_next_attempt_at ON email_outbox (status, next_attempt_at);
CREATE INDEX ix_email_outbox_user_id ON email_outbox (user_id);

CREATE TABLE email_verification_tokens (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    token_sha256 bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    verified_at timestamptz,
    CONSTRAINT pk_email_verification_tokens PRIMARY KEY (id),
    CONSTRAINT uq_email_verification_tokens_token_sha256 UNIQUE (token_sha256),
    CONSTRAINT ck_email_verification_tokens_expiry CHECK (expires_at > created_at),
    CONSTRAINT fk_email_verification_tokens_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_email_verification_tokens_user_id ON email_verification_tokens (user_id);
CREATE INDEX ix_email_verification_tokens_expires_at ON email_verification_tokens (expires_at);

CREATE TABLE meal_logs (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    logged_date date NOT NULL,
    logged_at timestamptz NOT NULL DEFAULT now(),
    meal_slot meal_log_slot_t NOT NULL,
    title text NOT NULL,
    source_type meal_log_source_t NOT NULL,
    source_ref_id text,
    portion_label text NOT NULL DEFAULT 'Vừa',
    portion_scale numeric NOT NULL DEFAULT 1,
    modifiers jsonb NOT NULL DEFAULT '[]'::jsonb,
    kcal numeric NOT NULL DEFAULT 0,
    kcal_low numeric NOT NULL DEFAULT 0,
    kcal_high numeric NOT NULL DEFAULT 0,
    protein_g numeric NOT NULL DEFAULT 0,
    carbs_g numeric NOT NULL DEFAULT 0,
    fat_g numeric NOT NULL DEFAULT 0,
    fiber_g numeric NOT NULL DEFAULT 0,
    provenance_label_vi text NOT NULL DEFAULT '',
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_meal_logs PRIMARY KEY (id),
    CONSTRAINT ck_meal_logs_portion_scale CHECK (portion_scale > 0),
    CONSTRAINT ck_meal_logs_kcal CHECK (kcal >= 0 AND kcal_low >= 0 AND kcal_low <= kcal_high),
    CONSTRAINT ck_meal_logs_macros CHECK (protein_g >= 0 AND carbs_g >= 0 AND fat_g >= 0 AND fiber_g >= 0),
    CONSTRAINT fk_meal_logs_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_meal_logs_user_id_logged_date ON meal_logs (user_id, logged_date DESC, created_at DESC);

CREATE TABLE meal_log_items (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    meal_log_id uuid NOT NULL,
    ordinal smallint NOT NULL DEFAULT 1,
    item_kind meal_log_item_kind_t NOT NULL DEFAULT 'dish',
    label_vi text NOT NULL,
    dish_slug text,
    recipe_id uuid,
    ingredient_id uuid,
    barcode text,
    grams numeric,
    kcal numeric NOT NULL DEFAULT 0,
    protein_g numeric NOT NULL DEFAULT 0,
    carbs_g numeric NOT NULL DEFAULT 0,
    fat_g numeric NOT NULL DEFAULT 0,
    fiber_g numeric NOT NULL DEFAULT 0,
    modifiers jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_meal_log_items PRIMARY KEY (id),
    CONSTRAINT uq_meal_log_items_meal_log_id_ordinal UNIQUE (meal_log_id, ordinal),
    CONSTRAINT ck_meal_log_items_ordinal CHECK (ordinal >= 1),
    CONSTRAINT ck_meal_log_items_grams CHECK (grams IS NULL OR grams >= 0),
    CONSTRAINT ck_meal_log_items_kcal CHECK (kcal >= 0),
    CONSTRAINT ck_meal_log_items_macros CHECK (protein_g >= 0 AND carbs_g >= 0 AND fat_g >= 0 AND fiber_g >= 0),
    CONSTRAINT fk_meal_log_items_meal_log_id FOREIGN KEY (meal_log_id) REFERENCES meal_logs (id) ON DELETE CASCADE,
    CONSTRAINT fk_meal_log_items_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id) ON DELETE SET NULL,
    CONSTRAINT fk_meal_log_items_ingredient_id FOREIGN KEY (ingredient_id) REFERENCES ingredients (id) ON DELETE SET NULL
);
CREATE INDEX ix_meal_log_items_meal_log_id ON meal_log_items (meal_log_id);
CREATE INDEX ix_meal_log_items_recipe_id ON meal_log_items (recipe_id);
CREATE INDEX ix_meal_log_items_ingredient_id ON meal_log_items (ingredient_id);

CREATE UNIQUE INDEX ux_shopping_items_open_null_src
    ON shopping_items (user_id, ingredient_id)
    WHERE status = 'open' AND source_meal_plan_item_id IS NULL;

CREATE UNIQUE INDEX ux_shopping_items_open_with_src
    ON shopping_items (user_id, ingredient_id, source_meal_plan_item_id)
    WHERE status = 'open' AND source_meal_plan_item_id IS NOT NULL;

CREATE INDEX ix_cook_sessions_meal_plan_status_completed
    ON cook_sessions (meal_plan_id, status, completed_at DESC);

CREATE INDEX ix_pantry_transactions_cook_deduct
    ON pantry_transactions (ref_type, ref_id, lot_id)
    WHERE reason = 'cook_deduct';

CREATE INDEX ix_pantry_transactions_lot_id_created_at
    ON pantry_transactions (lot_id, created_at DESC);

CREATE INDEX ix_interactions_recipe_type_swap
    ON interactions (recipe_id, type, swap_reason);

CREATE INDEX ix_interactions_user_type_recipe_swap
    ON interactions (user_id, type, recipe_id, swap_reason);

CREATE INDEX ix_pantry_lots_user_status_created
    ON pantry_lots (user_id, status, created_at, id);

CREATE INDEX ix_meal_plans_user_status_created
    ON meal_plans (user_id, status, created_at DESC, id DESC);

CREATE INDEX ix_audit_log_entity_created_at
    ON audit_log (entity, created_at DESC);

CREATE INDEX ix_password_resets_user_created_at
    ON password_resets (user_id, created_at DESC);

CREATE FUNCTION trg_user_favorite_recipes_limit() RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('fav:' || NEW.user_id::text, 0));
    IF (SELECT count(*) FROM public.user_favorite_recipes WHERE user_id = NEW.user_id) > 5 THEN
        RAISE EXCEPTION 'tối đa 5 món hay ăn (FAVORITES_MAX = 5)'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_user_favorite_recipes_limit
    AFTER INSERT ON user_favorite_recipes
    FOR EACH ROW EXECUTE FUNCTION trg_user_favorite_recipes_limit();

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_app') THEN
        CREATE ROLE tastoria_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_jobs') THEN
        CREATE ROLE tastoria_jobs NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_migrator') THEN
        CREATE ROLE tastoria_migrator NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO tastoria_app, tastoria_jobs;
GRANT ALL ON SCHEMA public TO tastoria_migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tastoria_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tastoria_app;
REVOKE UPDATE, DELETE, TRUNCATE ON public.consent_events, public.audit_log, public.pantry_transactions, public.interactions FROM tastoria_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.app_params FROM tastoria_app;
REVOKE DELETE, TRUNCATE ON public.users, public.dsr_requests FROM tastoria_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tastoria_jobs;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tastoria_jobs;

GRANT ALL ON ALL TABLES IN SCHEMA public TO tastoria_migrator;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO tastoria_migrator;

CREATE OR REPLACE FUNCTION erase_user_interactions(p_user_id uuid) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NOT public.erasure_active() THEN
        RAISE EXCEPTION 'tastoria.erasure is not active' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.dsr_requests
         WHERE user_id = p_user_id
           AND type IN ('withdraw', 'delete')
           AND status IN ('received', 'in_progress')
    ) AND NOT EXISTS (
        SELECT 1 FROM public.consent_events ce
        JOIN public.policy_versions pv ON pv.id = ce.policy_version_id
         WHERE ce.user_id = p_user_id
           AND pv.purpose_code = 'personalization'
           AND ce.action = 'withdraw'
           AND ce.created_at >= pg_catalog.now() - interval '5 minutes'
    ) THEN
        RAISE EXCEPTION 'erasure requires an active DSR request or recent consent withdrawal'
            USING ERRCODE = '42501';
    END IF;
    DELETE FROM public.interactions WHERE user_id = p_user_id;
END $$;

CREATE OR REPLACE FUNCTION erase_user_account(p_user_id uuid) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_deleted integer;
BEGIN
    IF NOT public.erasure_active() THEN
        RAISE EXCEPTION 'tastoria.erasure is not active' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.dsr_requests
         WHERE user_id = p_user_id
           AND type = 'delete'
           AND status IN ('received', 'in_progress')
    ) THEN
        RAISE EXCEPTION 'account deletion requires an active delete DSR request'
            USING ERRCODE = '42501';
    END IF;
    DELETE FROM public.users WHERE id = p_user_id;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted > 0;
END $$;

REVOKE ALL ON FUNCTION erase_user_interactions(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION erase_user_interactions(uuid) TO tastoria_app, tastoria_jobs;

REVOKE ALL ON FUNCTION erase_user_account(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION erase_user_account(uuid) TO tastoria_app, tastoria_jobs;
"""

DOWNGRADE_SQL = """
DROP FUNCTION IF EXISTS erase_user_account(uuid);

CREATE OR REPLACE FUNCTION erase_user_interactions(p_user_id uuid) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NOT public.erasure_active() THEN
        RAISE EXCEPTION 'tastoria.erasure is not active' USING ERRCODE = '42501';
    END IF;
    DELETE FROM public.interactions WHERE user_id = p_user_id;
END $$;

REVOKE ALL ON FUNCTION erase_user_interactions(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION erase_user_interactions(uuid) TO tastoria_app;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_app') THEN
        GRANT DELETE ON public.users, public.dsr_requests TO tastoria_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_jobs') THEN
        REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM tastoria_jobs;
        REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM tastoria_jobs;
        REVOKE USAGE ON SCHEMA public FROM tastoria_jobs;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_migrator') THEN
        REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM tastoria_migrator;
        REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM tastoria_migrator;
        REVOKE ALL ON SCHEMA public FROM tastoria_migrator;
    END IF;
END $$;

DROP TRIGGER IF EXISTS trg_user_favorite_recipes_limit ON user_favorite_recipes;
DROP FUNCTION IF EXISTS trg_user_favorite_recipes_limit();

DROP INDEX IF EXISTS ix_password_resets_user_created_at;
DROP INDEX IF EXISTS ix_audit_log_entity_created_at;
DROP INDEX IF EXISTS ix_meal_plans_user_status_created;
DROP INDEX IF EXISTS ix_pantry_lots_user_status_created;
DROP INDEX IF EXISTS ix_interactions_user_type_recipe_swap;
DROP INDEX IF EXISTS ix_interactions_recipe_type_swap;
DROP INDEX IF EXISTS ix_pantry_transactions_lot_id_created_at;
DROP INDEX IF EXISTS ix_pantry_transactions_cook_deduct;
DROP INDEX IF EXISTS ix_cook_sessions_meal_plan_status_completed;
DROP INDEX IF EXISTS ux_shopping_items_open_with_src;
DROP INDEX IF EXISTS ux_shopping_items_open_null_src;

DROP TABLE IF EXISTS meal_log_items;
DROP TABLE IF EXISTS meal_logs;
DROP TABLE IF EXISTS email_verification_tokens;
DROP TABLE IF EXISTS email_outbox;

ALTER TABLE refresh_tokens
    DROP COLUMN IF EXISTS last_used_at,
    DROP COLUMN IF EXISTS ip_address;

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS ck_users_mfa_enabled,
    DROP CONSTRAINT IF EXISTS ck_users_totp_enc_key,
    DROP COLUMN IF EXISTS mfa_enabled_at,
    DROP COLUMN IF EXISTS totp_key_id,
    DROP COLUMN IF EXISTS totp_secret_enc,
    DROP COLUMN IF EXISTS email_verified_at;

ALTER TABLE idempotency_keys
    DROP COLUMN IF EXISTS response_headers;

CREATE OR REPLACE FUNCTION app_param(p_key text) RETURNS numeric
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT NULLIF(current_setting('tastoria.' || p_key, true), '')::numeric
$$;

COMMENT ON FUNCTION app_param(text) IS 'Đọc tham số nghiệp vụ tastoria.<khoá> (GUC); NULL khi chưa đặt.';

DROP TABLE IF EXISTS app_params;

DROP TYPE IF EXISTS email_outbox_status_t;
DROP TYPE IF EXISTS meal_log_item_kind_t;
DROP TYPE IF EXISTS meal_log_source_t;
DROP TYPE IF EXISTS meal_log_slot_t;
"""


def upgrade() -> None:
    dbapi = op.get_bind().connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(UPGRADE_SQL)

    conn = op.get_bind()
    for p in POLICIES:
        conn.execute(
            sa.text(
                "INSERT INTO policy_versions (purpose_code, version, text_sha256, effective_from)"
                " VALUES (:code, :version, decode(:sha, 'hex'), CAST(:eff AS timestamptz))"
            ),
            {"code": p["code"], "version": VERSION, "sha": p["sha256"], "eff": EFFECTIVE_FROM},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM policy_versions WHERE version = :v AND purpose_code = ANY(:codes)"),
        {"v": VERSION, "codes": [p["code"] for p in POLICIES]},
    )

    dbapi = conn.connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(DOWNGRADE_SQL)
