"""Authenticated caller of `user` endpoints, as a FastAPI dependency every module may use.

The check itself (JWT signature, `kid`, `tv` against users.token_version) belongs to identity; the assembly root
installs identity's authenticator on `app.state.authenticator`. Keeping the dependency here lets modules such as
meal or pantry require a logged-in user without depending on identity (model.yaml deps).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from tastoria.core.db import Uow


@dataclass(frozen=True)
class AuthUser:
    id: uuid.UUID
    role: str
    email: str


class Authenticator(Protocol):
    def authenticate(self, request: Request, session: Session) -> AuthUser: ...


def current_user(request: Request, uow: Uow) -> AuthUser:
    """401 unauthenticated / token_revoked (FR-02-09); raised by the installed authenticator."""
    authenticator: Authenticator = request.app.state.authenticator
    return authenticator.authenticate(request, uow.session)


CurrentUser = Annotated[AuthUser, Depends(current_user)]
