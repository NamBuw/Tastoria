"""Make-ahead recipes (catalog slice 2): table recipe_make_ahead.

Recipes with a passive step longer than 2 hours (muối dưa, ngâm cà, ngâm măng khô) cannot be cooked tonight from
raw ingredients. The catalog import tags them `lam_san` and records here which steps are done ahead
(1..through_step_no, left out of the cook schedule) and which made-ahead product (`item_ingredient_id`) the user must
hold in the pantry for the dish to be proposed. The mapping comes from data/kb/make_ahead.yaml.

The table is a child of recipes like recipe_steps, so the same guard keeps it immutable once the recipe is
published (BR-CATALOG-01).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
CREATE TABLE recipe_make_ahead (
    recipe_id uuid NOT NULL,
    item_ingredient_id uuid NOT NULL,
    through_step_no smallint NOT NULL,
    CONSTRAINT pk_recipe_make_ahead PRIMARY KEY (recipe_id),
    CONSTRAINT ck_recipe_make_ahead_through_step_no CHECK (through_step_no > 0),
    CONSTRAINT fk_recipe_make_ahead_recipe_id FOREIGN KEY (recipe_id) REFERENCES recipes (id),
    CONSTRAINT fk_recipe_make_ahead_recipe_id_through_step_no FOREIGN KEY (recipe_id, through_step_no)
        REFERENCES recipe_steps (recipe_id, step_no),
    CONSTRAINT fk_recipe_make_ahead_item_ingredient_id FOREIGN KEY (item_ingredient_id) REFERENCES ingredients (id)
);
CREATE INDEX ix_recipe_make_ahead_item_ingredient_id ON recipe_make_ahead (item_ingredient_id);
CREATE TRIGGER trg_recipe_make_ahead_guard BEFORE INSERT OR UPDATE OR DELETE ON recipe_make_ahead
    FOR EACH ROW EXECUTE FUNCTION trg_recipe_children_guard();
COMMENT ON TABLE recipe_make_ahead IS 'Món làm sẵn (bước chờ > 2 giờ): bước 1..through_step_no làm từ trước, '
    'không xếp vào lịch nấu; món chỉ được đề xuất khi kho có đồ làm sẵn item_ingredient_id. '
    'Bất biến khi món published.';
COMMENT ON COLUMN recipe_make_ahead.item_ingredient_id IS 'Đồ làm sẵn phải có trong kho (ví dụ dưa cải chua)';
COMMENT ON COLUMN recipe_make_ahead.through_step_no IS 'Bước cuối cùng làm từ trước (bước chờ dài cuối cùng)';
"""


def upgrade() -> None:
    dbapi = op.get_bind().connection.dbapi_connection
    with dbapi.cursor() as cur:
        cur.execute(UPGRADE)


def downgrade() -> None:
    op.execute("DROP TABLE recipe_make_ahead")
