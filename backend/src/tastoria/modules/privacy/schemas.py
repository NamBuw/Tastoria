"""Bodies of /policies/*, /me/consents*, /me/data-requests* (docs/api/openapi-v1.yaml)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PurposeCode = Literal["health_profile", "personalization", "photo_contribution", "survey"]
DsrType = Literal["access", "export", "correct", "delete", "withdraw", "restrict", "object"]
DsrStatus = Literal["received", "in_progress", "completed", "rejected"]
Channel = Literal["onboarding", "settings"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsentPurposeOut(BaseModel):
    code: PurposeCode
    name_vi: str
    description_vi: str
    data_category: str
    is_sensitive: bool
    is_required: bool


class PolicyVersionOut(BaseModel):
    id: uuid.UUID
    purpose_code: PurposeCode
    version: str
    text_sha256: str
    effective_from: datetime
    purpose: ConsentPurposeOut
    text_vi: str


class ConsentState(BaseModel):
    purpose_code: PurposeCode
    state: Literal["none", "granted", "withdrawn", "superseded"]
    policy_version_id: uuid.UUID | None
    version: str | None
    current_policy_version_id: uuid.UUID | None
    decided_at: datetime | None


class ConsentWithdrawResult(ConsentState):
    """ConsentState plus the id of the dsr_requests row created by the withdrawal (UC05 step 9), if any."""

    data_request_id: uuid.UUID | None = None


class ConsentList(BaseModel):
    items: list[ConsentState]


class ConsentDecision(_Req):
    policy_version_id: uuid.UUID
    action: Literal["grant", "withdraw"]


class ConsentDecisionBatch(_Req):
    channel: Channel
    decisions: list[ConsentDecision] = Field(min_length=1, max_length=4)


class ConsentWithdrawRequest(_Req):
    channel: Channel = "settings"


class DataRequestCreate(_Req):
    type: DsrType
    note: str | None = Field(default=None, max_length=2000)
    # Not in openapi DataRequestCreate yet: UC07 step 3 sends the current password with type = delete.
    password: str | None = Field(default=None, max_length=256)


class DataRequestOut(BaseModel):
    id: uuid.UUID
    type: DsrType
    status: DsrStatus
    received_at: datetime
    acknowledged_at: datetime | None
    completed_at: datetime | None
    due_at: datetime
    download_available: bool
    note: str | None


class AdminDataRequestOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    subject_ref: str
    type: DsrType
    status: DsrStatus
    received_at: datetime
    acknowledged_at: datetime | None
    completed_at: datetime | None
    due_at: datetime
    note: str | None


class AdminDataRequestPage(BaseModel):
    items: list[AdminDataRequestOut]
    next_cursor: str | None


class DataRequestResolve(_Req):
    status: Literal["in_progress", "completed", "rejected"]
    note: str = Field(max_length=2000)


class AuditLogEntryOut(BaseModel):
    id: int
    actor_user_id: uuid.UUID | None
    actor_role: str
    action: str
    entity: str
    entity_id: str | None
    purpose: str | None
    request_id: str | None
    created_at: datetime


class AuditLogEntryPage(BaseModel):
    items: list[AuditLogEntryOut]
    next_cursor: str | None
