"""Tables owned by core (model.yaml `tables[].module = core`)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Double, ForeignKey, Index, LargeBinary, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    response_body: Mapped[object] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    response_headers: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (Index("ix_idempotency_keys_created_at", "created_at"),)


class AppParam(Base):
    __tablename__ = "app_params"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value_num: Mapped[float | None] = mapped_column(Double)
    value_text: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
