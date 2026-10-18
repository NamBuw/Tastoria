"""HTTP layer of scan: /scans, /scans/{id}, images, chips, confirm, discard (UC12, UC13)."""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Path, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from tastoria.core import idempotency
from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.scan import service
from tastoria.modules.scan.images import MAX_BYTES
from tastoria.modules.scan.schemas import (
    ScanAccepted,
    ScanConfirmRequest,
    ScanConfirmResult,
    ScanItemCreate,
    ScanItemOut,
    ScanItemPatch,
    ScanMode,
    ScanOut,
)

router = APIRouter(prefix="/scans", tags=["scan"])


def _deps(request: Request) -> service.ScanDeps:
    return request.app.state.scan


def _location(scan_id: str) -> dict[str, str]:
    return {"Location": f"/api/v1/scans/{scan_id}", "Retry-After": "1"}


def _read(upload: UploadFile, index: int) -> bytes:
    upload.file.seek(0)
    data = upload.file.read(MAX_BYTES + 1)  # never more than the limit + 1 byte in memory (FR-12-02)
    if len(data) > MAX_BYTES:
        raise ApiError(
            413,
            ProblemCode.image_too_large,
            errors=[{"pointer": f"/images/{index}", "code": "size", "message": f"ảnh thứ {index + 1} > 3 MB"}],
        )
    return data


@router.post("", operation_id="scan_create_scan", status_code=202, responses={202: {"model": ScanAccepted}})
def create_scan(
    request: Request,
    user: CurrentUser,
    uow: Uow,
    mode: Annotated[ScanMode, Form()],
    images: Annotated[list[UploadFile], File()],
    shelf_groups: Annotated[list[int] | None, Form()] = None,
    contribute: Annotated[bool | None, Form()] = None,
) -> Response:
    key = idempotency.header_key(request)
    raws = [_read(u, i) for i, u in enumerate(images[: service.MAX_IMAGES + 1])]
    idem = idempotency.IdempotencyRequest(key, service.request_digest(mode, shelf_groups, contribute, raws))
    deps = _deps(request)
    session = uow.session
    if (replayed := idempotency.begin(session, user.id, idem)) is not None:
        if replayed.status_code == 202:
            replayed.headers.update(_location(json.loads(replayed.body)["id"]))
        return replayed
    accepted, scan_id = service.create_scan(
        session, deps, user, mode=mode, raws=raws, shelf_groups=shelf_groups, contribute=contribute
    )
    uow.after_commit(lambda: service.enqueue_after_commit(deps, scan_id))
    return idempotency.finish(session, user.id, idem, 202, accepted, headers=_location(str(scan_id)))


@router.get("/{id}", operation_id="scan_get_scan", responses={200: {"model": ScanOut}})
def get_scan(
    id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    uow: Uow,
    wait: Annotated[int, Query(ge=0, le=10)] = 0,
) -> JSONResponse:
    out = service.get_scan(uow.session, _deps(request), user, id, wait)
    body = out.model_dump(mode="json", exclude={"unseen_lots"} if out.unseen_lots is None else None)
    headers = {"Retry-After": "1"} if out.status in service.PENDING else None
    return JSONResponse(body, headers=headers)


@router.get("/{id}/images/{ordinal}", operation_id="scan_get_image")
def get_image(
    id: uuid.UUID, ordinal: Annotated[int, Path(ge=1, le=2)], request: Request, user: CurrentUser, uow: Uow
) -> Response:
    return service.image_response(uow.session, _deps(request), user, id, ordinal)


@router.post("/{id}/items", operation_id="scan_add_item", status_code=201)
def add_item(id: uuid.UUID, body: ScanItemCreate, user: CurrentUser, uow: Uow, response: Response) -> ScanItemOut:
    item = service.add_item(uow.session, user, id, body)
    response.headers["Location"] = f"/api/v1/scans/{id}/items/{item.id}"
    return item


@router.patch("/{id}/items/{itemId}", operation_id="scan_update_item")
def update_item(id: uuid.UUID, itemId: uuid.UUID, body: ScanItemPatch, user: CurrentUser, uow: Uow) -> ScanItemOut:  # noqa: N803
    return service.update_item(uow.session, user, id, itemId, body)


@router.delete("/{id}/items/{itemId}", operation_id="scan_delete_item", status_code=204)
def delete_item(id: uuid.UUID, itemId: uuid.UUID, user: CurrentUser, uow: Uow) -> Response:  # noqa: N803
    service.delete_item(uow.session, user, id, itemId)
    return Response(status_code=204)


@router.post("/{id}/confirm", operation_id="scan_confirm_scan")
def confirm(
    id: uuid.UUID, request: Request, user: CurrentUser, uow: Uow, body: ScanConfirmRequest | None = None
) -> ScanConfirmResult:
    return service.confirm(uow.session, _deps(request), user, id, body)


@router.post("/{id}/discard", operation_id="scan_discard_scan", responses={200: {"model": ScanOut}})
def discard(id: uuid.UUID, user: CurrentUser, uow: Uow) -> JSONResponse:
    out = service.discard(uow.session, user, id)
    return JSONResponse(out.model_dump(mode="json", exclude={"unseen_lots"}))
