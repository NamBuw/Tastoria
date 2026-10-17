"""Request/response bodies of /auth/* (docs/api/openapi-v1.yaml: AuthSession, RegisterRequest, ...).

Email syntax and password length are checked in the service, not here, so they map to the contract codes
`invalid_email` / `weak_password` instead of a generic validation_error.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(_Req):
    email: str
    password: str


class LoginRequest(_Req):
    email: str
    password: str


class RefreshRequest(_Req):
    refresh_token: str


class LogoutRequest(_Req):
    refresh_token: str


class PasswordResetRequest(_Req):
    email: str


class PasswordResetConfirm(_Req):
    token: str
    new_password: str


class UserSummary(BaseModel):
    id: uuid.UUID
    email: str
    role: Literal["user", "admin", "curator", "ml_operator"]
    status: Literal["active", "deletion_requested"]
    created_at: datetime


class AuthSession(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime
    user: UserSummary
