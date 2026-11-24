"""Shopping item to pantry lot link: column shopping_items.pantry_lot_id.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
ALTER TABLE shopping_items
    ADD COLUMN pantry_lot_id uuid NULL,
    ADD CONSTRAINT fk_shopping_items_pantry_lot_id FOREIGN KEY (pantry_lot_id)
        REFERENCES pantry_lots (id) ON DELETE SET NULL;
CREATE INDEX ix_shopping_items_pantry_lot_id ON shopping_items (pantry_lot_id);
"""


def upgrade() -> None:
    dbapi = op.get_bind().connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(UPGRADE)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_shopping_items_pantry_lot_id")
    op.execute("ALTER TABLE shopping_items DROP COLUMN IF EXISTS pantry_lot_id")
