"""HTTP layer of events: POST /events (batch, deduplicated by event_id)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.core.ratelimit import enforce_rate_limit
from tastoria.modules.events import service
from tastoria.modules.events.schemas import EventBatch, EventBatchResult

router = APIRouter(tags=["events"])


@router.post("/events", operation_id="events_record_events")
def record_events(body: EventBatch, request: Request, user: CurrentUser, uow: Uow) -> EventBatchResult:
    enforce_rate_limit(request, bucket="events_record", subject=str(user.id), limit=60, window_s=60)
    return service.record_batch(uow.session, user.id, body)
