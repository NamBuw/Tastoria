"""HTTP layer of journal: GET /journal?week=YYYY-Www (UC22)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.modules.journal import service
from tastoria.modules.journal.schemas import JournalWeek

router = APIRouter(tags=["journal"])


@router.get("/journal", operation_id="journal_get_week")
def get_week(user: CurrentUser, uow: Uow, week: Annotated[str | None, Query(max_length=16)] = None) -> JournalWeek:
    return service.get_week(uow.session, user.id, week)
