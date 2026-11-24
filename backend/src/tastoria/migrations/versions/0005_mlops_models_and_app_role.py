"""Extend model_name_t for meal_calorie/dish_classifier/mushroom_classifier and provision tastoria_app role.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_ROLE_AND_FUNC = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_app') THEN
        CREATE ROLE tastoria_app NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO tastoria_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tastoria_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tastoria_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tastoria_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO tastoria_app;
REVOKE UPDATE, DELETE, TRUNCATE ON consent_events, audit_log, pantry_transactions, interactions FROM tastoria_app;

CREATE OR REPLACE FUNCTION erase_user_interactions(p_user_id uuid) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NOT erasure_active() THEN
        RAISE EXCEPTION 'tastoria.erasure is not active' USING ERRCODE = '42501';
    END IF;
    DELETE FROM interactions WHERE user_id = p_user_id;
END $$;

REVOKE ALL ON FUNCTION erase_user_interactions(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION erase_user_interactions(uuid) TO tastoria_app;
"""

DOWNGRADE_SQL = """
DROP FUNCTION IF EXISTS erase_user_interactions(uuid);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tastoria_app') THEN
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM tastoria_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM tastoria_app;
        REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM tastoria_app;
        REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM tastoria_app;
        REVOKE USAGE ON SCHEMA public FROM tastoria_app;
    END IF;
END $$;

UPDATE scans
   SET detector_version_id = NULL
 WHERE detector_version_id IN (
     SELECT id FROM model_versions WHERE name::text IN ('meal_calorie', 'dish_classifier', 'mushroom_classifier')
 );
UPDATE scans
   SET classifier_version_id = NULL
 WHERE classifier_version_id IN (
     SELECT id FROM model_versions WHERE name::text IN ('meal_calorie', 'dish_classifier', 'mushroom_classifier')
 );
DELETE FROM model_version_classes
 WHERE model_version_id IN (
     SELECT id FROM model_versions WHERE name::text IN ('meal_calorie', 'dish_classifier', 'mushroom_classifier')
 );
DELETE FROM model_deployments
 WHERE name::text IN ('meal_calorie', 'dish_classifier', 'mushroom_classifier');
DELETE FROM model_versions
 WHERE name::text IN ('meal_calorie', 'dish_classifier', 'mushroom_classifier');

ALTER TABLE model_deployments DROP CONSTRAINT IF EXISTS fk_model_deployments_active_version_id_name;
ALTER TABLE model_deployments DROP CONSTRAINT IF EXISTS fk_model_deployments_previous_version_id_name;

ALTER TYPE model_name_t RENAME TO model_name_t_old;
CREATE TYPE model_name_t AS ENUM ('detector', 'freshness', 'ranker', 'substitution');
ALTER TABLE model_versions ALTER COLUMN name TYPE model_name_t USING name::text::model_name_t;
ALTER TABLE model_deployments ALTER COLUMN name TYPE model_name_t USING name::text::model_name_t;

ALTER TABLE model_deployments
    ADD CONSTRAINT fk_model_deployments_active_version_id_name
        FOREIGN KEY (active_version_id, name) REFERENCES model_versions (id, name),
    ADD CONSTRAINT fk_model_deployments_previous_version_id_name
        FOREIGN KEY (previous_version_id, name) REFERENCES model_versions (id, name);

DROP TYPE model_name_t_old;
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE model_name_t ADD VALUE IF NOT EXISTS 'meal_calorie'")
        op.execute("ALTER TYPE model_name_t ADD VALUE IF NOT EXISTS 'dish_classifier'")
        op.execute("ALTER TYPE model_name_t ADD VALUE IF NOT EXISTS 'mushroom_classifier'")

    dbapi = op.get_bind().connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(UPGRADE_ROLE_AND_FUNC)


def downgrade() -> None:
    dbapi = op.get_bind().connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(DOWNGRADE_SQL)
