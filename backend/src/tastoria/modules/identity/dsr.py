"""identity's part of data-subject requests (registered by tastoria.app with privacy)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from tastoria.modules.identity import service


class IdentitySubjectData:
    name = "identity"

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        return service.export_subject_data(session, user_id)

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None:
        return None  # no identity data depends on a consent purpose

    def erase_files(self, user_id: uuid.UUID) -> None:
        return None  # identity keeps no files
