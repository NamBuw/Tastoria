"""Persist mushroom sub-species classification and safety abstention on detections.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
ALTER TABLE detections
    ADD COLUMN sub_species_slug text NULL,
    ADD COLUMN sub_species_conf real NULL,
    ADD COLUMN safety_abstained boolean NOT NULL DEFAULT false,
    ADD CONSTRAINT ck_detections_sub_species_conf CHECK (sub_species_conf IS NULL OR (sub_species_conf BETWEEN 0 AND 1));
"""

DOWNGRADE = """
ALTER TABLE detections
    DROP CONSTRAINT IF EXISTS ck_detections_sub_species_conf,
    DROP COLUMN IF EXISTS safety_abstained,
    DROP COLUMN IF EXISTS sub_species_conf,
    DROP COLUMN IF EXISTS sub_species_slug;
"""


def upgrade() -> None:
    dbapi = op.get_bind().connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(UPGRADE)


def downgrade() -> None:
    dbapi = op.get_bind().connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(DOWNGRADE)
