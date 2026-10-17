"""Tables owned by privacy: consent_purposes, policy_versions, consent_events, dsr_requests, audit_log."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Identity, Index, LargeBinary, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ENUM, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tastoria.core.db import Base

TZ = TIMESTAMP(timezone=True)
CONSENT_ACTION = ENUM("grant", "withdraw", name="consent_action_t", create_type=False)
CONSENT_CHANNEL = ENUM("onboarding", "settings", name="consent_channel_t", create_type=False)
DSR_TYPE = ENUM(
    "access", "export", "correct", "delete", "withdraw", "restrict", "object", name="dsr_type_t", create_type=False
)
DSR_STATUS = ENUM("received", "in_progress", "completed", "rejected", name="dsr_status_t", create_type=False)


class ConsentPurpose(Base):
    __tablename__ = "consent_purposes"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    description_vi: Mapped[str] = mapped_column(Text, nullable=False)
    data_category: Mapped[str] = mapped_column(Text, nullable=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    purpose_code: Mapped[str] = mapped_column(Text, ForeignKey("consent_purposes.code"), nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(TZ, nullable=False)

    __table_args__ = (UniqueConstraint("purpose_code", "version", name="uq_policy_versions_purpose_code_version"),)


class ConsentEvent(Base):
    """Append-only (trigger trg_consent_events_append_only)."""

    __tablename__ = "consent_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_versions.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(CONSENT_ACTION, nullable=False)
    channel: Mapped[str] = mapped_column(CONSENT_CHANNEL, nullable=False)
    app_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.clock_timestamp())

    __table_args__ = (Index("ix_consent_events_user_id_created_at", "user_id", text("created_at DESC")),)


class DsrRequest(Base):
    __tablename__ = "dsr_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    subject_ref: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    type: Mapped[str] = mapped_column(DSR_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(DSR_STATUS, nullable=False)
    received_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(TZ)
    completed_at: Mapped[datetime | None] = mapped_column(TZ)
    result_key: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_dsr_requests_status_received_at", "status", "received_at"),
        Index("ix_dsr_requests_user_id", "user_id"),
    )


class AuditLog(Base):
    """Append-only (trigger trg_audit_log_append_only)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_role: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_actor_user_id", "actor_user_id"),
    )
