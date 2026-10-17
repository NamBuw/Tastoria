"""Tables owned by pantry: pantry_lots and the append-only pantry_transactions (view v_pantry_lot_balance).

FKs to tables of modules that have no code yet (model_versions of mlops, scan_items of scan) exist in the database
and are left out of the mapping until those modules map their tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, Numeric, text
from sqlalchemy.dialects.postgresql import ENUM, REAL, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
ACQUIRED_BASIS = ENUM("purchase_date_entered", "first_seen", name="acquired_basis_t", create_type=False)
LOT_STATUS = ENUM("in_stock", "used_up", "discarded", "not_seen", name="lot_status_t", create_type=False)
TX_REASON = ENUM(
    "scan_add", "cook_deduct", "manual_edit", "discard", "undo", name="pantry_tx_reason_t", create_type=False
)
REF_TYPE = ENUM("scan", "cook_session", "user", name="pantry_ref_type_t", create_type=False)


class PantryLot(Base):
    __tablename__ = "pantry_lots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False)
    initial_g_min: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    initial_g_max: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    acquired_basis: Mapped[str] = mapped_column(ACQUIRED_BASIS, nullable=False)
    status: Mapped[str] = mapped_column(LOT_STATUS, nullable=False, server_default="in_stock")
    p_tuoi: Mapped[float | None] = mapped_column(REAL)
    p_dung_som: Mapped[float | None] = mapped_column(REAL)
    p_dung_ngay: Mapped[float | None] = mapped_column(REAL)
    p_kiem_tra: Mapped[float | None] = mapped_column(REAL)
    freshness_observed_at: Mapped[datetime | None] = mapped_column(TZ)
    freshness_model_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK model_versions
    user_checked_at: Mapped[datetime | None] = mapped_column(TZ)
    source_scan_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK scan_items
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("ix_pantry_lots_user_id_status", "user_id", "status"),
        Index("ix_pantry_lots_source_scan_item_id", "source_scan_item_id"),
    )


class PantryTransaction(Base):
    """Append-only (trigger trg_pantry_transactions_append_only); undo = a new row pointing at `reverses_id`."""

    __tablename__ = "pantry_transactions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pantry_lots.id", ondelete="CASCADE"), nullable=False
    )
    delta_g_min: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    delta_g_max: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    reason: Mapped[str] = mapped_column(TX_REASON, nullable=False)
    ref_type: Mapped[str | None] = mapped_column(REF_TYPE)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reverses_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pantry_transactions.id"), unique=True)
    urgency_at_event: Mapped[float | None] = mapped_column(REAL)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("ix_pantry_transactions_lot_id", "lot_id"),
        Index("ix_pantry_transactions_ref", "ref_type", "ref_id"),
    )
