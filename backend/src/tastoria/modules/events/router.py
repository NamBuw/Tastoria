"""HTTP layer of events: POST /events (batch, deduplicated by event_id)."""

from __future__ import annotations

from fastapi import APIRouter

from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.modules.events import service
from tastoria.modules.events.schemas import EventBatch, EventBatchResult

router = APIRouter(tags=["events"])


@router.post("/events", operation_id="events_record_events")
def record_events(body: EventBatch, user: CurrentUser, uow: Uow) -> EventBatchResult:
    return service.record_batch(uow.session, user.id, body)
