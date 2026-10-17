"""Reference data of privacy: the four consent purposes (BR-CONSENT-01) and their first policy versions.

The policy texts live in tastoria/modules/privacy/policies/<purpose>-<version>.md. Their SHA-256 is frozen here;
tests/unit/test_policy_texts.py fails if a text file changes. A new text = a new file + a new migration with a
new version label (consents given to the old version then show as `superseded`).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSION = "2026-10-17"
EFFECTIVE_FROM = "2026-10-17T00:00:00+07:00"

PURPOSES = [
    {
        "code": "health_profile",
        "name_vi": "Hồ sơ sức khoẻ",
        "description_vi": "Lưu giới tính, năm sinh, chiều cao, cân nặng (mã hoá), mức vận động và mục tiêu để tính "
        "mục tiêu năng lượng và năng lượng cho từng bữa.",
        "data_category": "Chỉ số cơ thể, mức vận động, mục tiêu năng lượng (dữ liệu sức khoẻ)",
        "is_sensitive": True,
        "sha256": "f27d92963ffce91afb6fff11158f38fa79cb609c64e278ac333a3b5a25d9ec17",
    },
    {
        "code": "personalization",
        "name_vi": "Cá nhân hoá gợi ý",
        "description_vi": "Ghi món được gợi ý, món đổi, món nấu, món thích hoặc không thích để xếp hạng món theo gu.",
        "data_category": "Dữ liệu hành vi sử dụng dịch vụ",
        "is_sensitive": True,
        "sha256": "b3d9f138384c538253338352521394d78d6b5d60b70e28e412e1aa4ca5de90a2",
    },
    {
        "code": "photo_contribution",
        "name_vi": "Góp ảnh quét",
        "description_vi": "Giữ ảnh quét quá 30 ngày để gán nhãn và huấn luyện lại mô hình nhận dạng nguyên liệu.",
        "data_category": "Ảnh tủ lạnh, ảnh túi đồ",
        "is_sensitive": False,
        "sha256": "c20904503e2648d8f9ecfe4909bcc5f9465f10897be4eb58b706988a37b908ef",
    },
    {
        "code": "survey",
        "name_vi": "Khảo sát gu món ăn",
        "description_vi": "Thu điểm chấm món và 5 món hay ăn của người tham gia khảo sát ẩn danh để nghiên cứu xếp "
        "hạng món.",
        "data_category": "Điểm chấm món, món hay ăn (bí danh)",
        "is_sensitive": False,
        "sha256": "89f79cd127568886e9ee5fc60b900b8dac14d5ca1bb148b9b3105db305cee20b",
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    for p in PURPOSES:
        conn.execute(
            sa.text(
                "INSERT INTO consent_purposes (code, name_vi, description_vi, data_category, is_sensitive, is_required)"
                " VALUES (:code, :name_vi, :description_vi, :data_category, :is_sensitive, false)"
            ),
            p,
        )
        conn.execute(
            sa.text(
                "INSERT INTO policy_versions (purpose_code, version, text_sha256, effective_from)"
                " VALUES (:code, :version, decode(:sha, 'hex'), CAST(:eff AS timestamptz))"
            ),
            {"code": p["code"], "version": VERSION, "sha": p["sha256"], "eff": EFFECTIVE_FROM},
        )


def downgrade() -> None:
    conn = op.get_bind()
    codes = [p["code"] for p in PURPOSES]
    conn.execute(
        sa.text("DELETE FROM policy_versions WHERE version = :v AND purpose_code = ANY(:codes)"),
        {"v": VERSION, "codes": codes},
    )
    conn.execute(sa.text("DELETE FROM consent_purposes WHERE code = ANY(:codes)"), {"codes": codes})
