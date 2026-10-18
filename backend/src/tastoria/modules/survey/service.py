"""survey public interface (M14): anonymous taste survey with an incomplete block design (UC23) and the form
operations the admin CLI runs (UC24).

Respondents have no account. POST /survey/respondents returns a `respondent_token`: an HS256 JWT signed with the
API's active JWT key, audience `tastoria-survey`, `sub` = respondent id, valid RESPONDENT_TOKEN_TTL (UC23 open
question 1: signed, not stored, so survey_respondents needs no token column). Access tokens of users (audience
`tastoria-app`) are not accepted here and respondent tokens are not accepted by identity. A token opens only the
respondent in its `sub`; any other id answers 401 respondent_token_invalid (openapi ProblemCode catalogue).

Assignment (step 6): every anchor of the form + `n_random` published non-anchor recipes, split over the slots in
proportion to the published recipes per slot (largest remainder), least-shown first within a slot so each recipe
collects about the same number of ratings, then the whole list shuffled into display_order (design.py). Creating
a respondent locks the form row, so concurrent starts are serialised and the balance holds exactly.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import random
import secrets
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from tastoria.core import pagination
from tastoria.core.clock import utcnow
from tastoria.core.config import Settings
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.catalog import service as catalog
from tastoria.modules.privacy import service as privacy
from tastoria.modules.survey import design
from tastoria.modules.survey.models import (
    SurveyAssignment,
    SurveyFavorite,
    SurveyForm,
    SurveyFormAnchor,
    SurveyRating,
    SurveyRespondent,
)
from tastoria.modules.survey.schemas import (
    CreatedForm,
    ExportResult,
    FavoriteSet,
    SurveyAssignmentOut,
    SurveyFormSummary,
    SurveyFormSummaryPage,
    SurveyRatingOut,
    SurveyRatingPut,
    SurveyRespondentCreate,
    SurveyRespondentCreated,
    SurveyRespondentOut,
)

log = logging.getLogger("tastoria.survey")

PURPOSE = "survey"
SLOTS = ("man", "rau", "canh")
MAX_FAVORITES = 5
RESPONDENT_TOKEN_TTL = timedelta(days=30)
TOKEN_AUDIENCE = "tastoria-survey"
_rng = random.SystemRandom()


# ---------------------------------------------------------------- respondent token


def issue_token(settings: Settings, respondent_id: uuid.UUID) -> str:
    now = utcnow()
    claims = {
        "sub": str(respondent_id),
        "aud": TOKEN_AUDIENCE,
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + RESPONDENT_TOKEN_TTL).timestamp()),
    }
    kid = settings.jwt_active_kid
    return jwt.encode(claims, settings.jwt_keys[kid], algorithm="HS256", headers={"kid": kid})


def _token_invalid() -> ApiError:
    return ApiError(401, ProblemCode.respondent_token_invalid)


def verify_token(settings: Settings, token: str | None, respondent_id: uuid.UUID) -> None:
    """401 respondent_token_invalid when the token is missing, forged, expired, or names another respondent."""
    if not token:
        raise _token_invalid()
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        key = settings.jwt_keys.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise _token_invalid()
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            audience=TOKEN_AUDIENCE,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "aud"]},
            leeway=0,
        )
    except jwt.PyJWTError:
        raise _token_invalid() from None
    if claims.get("sub") != str(respondent_id):
        raise _token_invalid()


# ---------------------------------------------------------------- UC23: respondents


def _open_form(session: Session, version: str | None) -> SurveyForm:
    q = select(SurveyForm).where(SurveyForm.is_open.is_(True))
    if version is not None:
        q = q.where(SurveyForm.version == version)
    form = session.scalars(q.with_for_update()).first()
    if form is None:
        raise ApiError(409, ProblemCode.survey_closed)
    return form


def _anchor_ids(session: Session, form_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(SurveyFormAnchor.recipe_id)
            .where(SurveyFormAnchor.form_id == form_id)
            .order_by(SurveyFormAnchor.recipe_id)
        )
    )


def _shown_counts(session: Session, form_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = session.execute(
        select(SurveyAssignment.recipe_id, func.count())
        .join(SurveyRespondent, SurveyRespondent.id == SurveyAssignment.respondent_id)
        .where(SurveyRespondent.form_id == form_id, SurveyAssignment.is_anchor.is_(False))
        .group_by(SurveyAssignment.recipe_id)
    )
    return {rid: int(n) for rid, n in rows}


def _misconfigured(form: SurveyForm, why: str) -> ApiError:
    log.error("survey form misconfigured", extra={"form_version": form.version, "reason": why})
    return ApiError(503, ProblemCode.survey_form_misconfigured, why)


def create_respondent(session: Session, settings: Settings, body: SurveyRespondentCreate) -> SurveyRespondentCreated:
    if not body.consent:  # FR-23-02: nothing is written
        raise ApiError(422, ProblemCode.consent_required)
    current = privacy.current_policy(session, PURPOSE)
    if current is None or current.id != body.policy_version_id:  # FR-23-04
        raise ApiError(409, ProblemCode.policy_outdated)
    form = _open_form(session, body.form_version)  # row lock: serialises assignment of this form

    anchors = _anchor_ids(session, form.id)
    if len(anchors) != form.n_anchor:
        raise _misconfigured(form, f"phiếu có {len(anchors)} món neo, cần {form.n_anchor}")
    published = catalog.published_recipe_refs(session)
    in_kho = Counter(r.slot for r in published)
    weights = {s: in_kho.get(s, 0) for s in SLOTS}  # FR-23-06: proportional to the published recipes per slot
    anchor_set = set(anchors)
    pool: dict[str, list[uuid.UUID]] = {s: [] for s in SLOTS}
    for r in published:
        if r.id not in anchor_set:
            pool[r.slot].append(r.id)
    if sum(len(v) for v in pool.values()) < form.n_random:  # UC23 6a
        raise _misconfigured(
            form, f"còn {sum(len(v) for v in pool.values())} món published ngoài neo, cần {form.n_random}"
        )
    picked = design.pick_stratified(pool, form.n_random, weights, _rng, _shown_counts(session, form.id))

    now = utcnow()
    resp = SurveyRespondent(
        form_id=form.id, policy_version_id=current.id, consented_at=now, completed_at=None, channel=body.channel
    )
    session.add(resp)
    session.flush()
    items = [(rid, True) for rid in anchors] + [(rid, False) for rid in picked]
    _rng.shuffle(items)
    session.add_all(
        SurveyAssignment(respondent_id=resp.id, recipe_id=rid, display_order=i, is_anchor=anchor)
        for i, (rid, anchor) in enumerate(items, start=1)
    )
    session.flush()
    return SurveyRespondentCreated(
        respondent=_out(session, resp, form), respondent_token=issue_token(settings, resp.id)
    )


def _respondent(session: Session, settings: Settings, respondent_id: uuid.UUID, token: str | None) -> SurveyRespondent:
    verify_token(settings, token, respondent_id)
    resp = session.scalars(
        select(SurveyRespondent).where(SurveyRespondent.id == respondent_id).with_for_update()
    ).first()
    if resp is None:
        raise ApiError(404, ProblemCode.not_found)
    return resp


def _writable(session: Session, resp: SurveyRespondent) -> SurveyForm:
    form = session.get(SurveyForm, resp.form_id)
    assert form is not None
    if resp.completed_at is not None:  # UC23 14c
        raise ApiError(409, ProblemCode.survey_already_completed)
    if not form.is_open:  # UC23 8c
        raise ApiError(409, ProblemCode.survey_closed)
    return form


def _out(session: Session, resp: SurveyRespondent, form: SurveyForm | None = None) -> SurveyRespondentOut:
    form = form or session.get(SurveyForm, resp.form_id)
    assert form is not None
    assigned = list(
        session.scalars(
            select(SurveyAssignment)
            .where(SurveyAssignment.respondent_id == resp.id)
            .order_by(SurveyAssignment.display_order)
        )
    )
    ratings = {
        r.recipe_id: r for r in session.scalars(select(SurveyRating).where(SurveyRating.respondent_id == resp.id))
    }
    refs = catalog.recipe_refs(session, [a.recipe_id for a in assigned])
    favs = list(
        session.scalars(
            select(SurveyFavorite.recipe_id)
            .where(SurveyFavorite.respondent_id == resp.id)
            .order_by(SurveyFavorite.recipe_id)
        )
    )
    return SurveyRespondentOut(
        id=resp.id,
        form_version=form.version,
        consented_at=resp.consented_at,
        completed_at=resp.completed_at,
        channel=resp.channel,  # type: ignore[arg-type]
        assignments=[
            SurveyAssignmentOut(
                recipe_id=a.recipe_id,
                name_vi=refs[a.recipe_id].name_vi,
                slot=refs[a.recipe_id].slot,  # type: ignore[arg-type]
                display_order=a.display_order,
                is_anchor=a.is_anchor,
                rating=ratings[a.recipe_id].rating if a.recipe_id in ratings else None,
                never_eaten=ratings[a.recipe_id].never_eaten if a.recipe_id in ratings else None,
            )
            for a in assigned
        ],
        favorite_recipe_ids=favs,
    )


def get_respondent(
    session: Session, settings: Settings, respondent_id: uuid.UUID, token: str | None
) -> SurveyRespondentOut:
    return _out(session, _respondent(session, settings, respondent_id, token))


def put_rating(
    session: Session,
    settings: Settings,
    respondent_id: uuid.UUID,
    token: str | None,
    recipe_id: uuid.UUID,
    body: SurveyRatingPut,
) -> SurveyRatingOut:
    resp = _respondent(session, settings, respondent_id, token)
    _writable(session, resp)
    if session.get(SurveyAssignment, (resp.id, recipe_id)) is None:  # FR-23-09
        raise ApiError(404, ProblemCode.not_found, "Món này không nằm trong phiếu của bạn.")
    valid = (body.never_eaten and body.rating is None) or (
        not body.never_eaten and body.rating is not None and 1 <= body.rating <= 5
    )
    if not valid:  # FR-23-08
        raise ApiError(422, ProblemCode.invalid_rating)
    stmt = insert(SurveyRating).values(
        respondent_id=resp.id,
        recipe_id=recipe_id,
        rating=body.rating,
        never_eaten=body.never_eaten,
        answered_at=utcnow(),
    )
    # FR-23-10: the same answer sent again changes nothing (answered_at included); a new answer overwrites.
    stmt = stmt.on_conflict_do_update(
        index_elements=[SurveyRating.respondent_id, SurveyRating.recipe_id],
        set_={
            "rating": stmt.excluded.rating,
            "never_eaten": stmt.excluded.never_eaten,
            "answered_at": stmt.excluded.answered_at,
        },
        where=tuple_(SurveyRating.rating, SurveyRating.never_eaten).is_distinct_from(
            tuple_(stmt.excluded.rating, stmt.excluded.never_eaten)
        ),
    )
    session.execute(stmt)
    session.expire_all()
    row = session.get(SurveyRating, (resp.id, recipe_id))
    assert row is not None
    return SurveyRatingOut(
        recipe_id=recipe_id, rating=row.rating, never_eaten=row.never_eaten, answered_at=row.answered_at
    )


def set_favorites(
    session: Session, settings: Settings, respondent_id: uuid.UUID, token: str | None, body: FavoriteSet
) -> FavoriteSet:
    resp = _respondent(session, settings, respondent_id, token)
    _writable(session, resp)
    ids = body.recipe_ids
    if len(ids) > MAX_FAVORITES or len(set(ids)) != len(ids) or catalog.not_published_recipe_ids(session, ids):
        raise ApiError(422, ProblemCode.invalid_favorites)  # FR-23-11: the old list stays
    session.query(SurveyFavorite).filter(SurveyFavorite.respondent_id == resp.id).delete()
    session.add_all(SurveyFavorite(respondent_id=resp.id, recipe_id=rid) for rid in ids)
    session.flush()
    return FavoriteSet(recipe_ids=ids)


def complete(session: Session, settings: Settings, respondent_id: uuid.UUID, token: str | None) -> SurveyRespondentOut:
    resp = _respondent(session, settings, respondent_id, token)
    if resp.completed_at is not None:  # UC23 14b: idempotent, keeps the first completed_at
        return _out(session, resp)
    form = session.get(SurveyForm, resp.form_id)
    assert form is not None
    if not form.is_open:
        raise ApiError(409, ProblemCode.survey_closed)
    missing = list(
        session.scalars(
            select(SurveyAssignment.recipe_id)
            .outerjoin(
                SurveyRating,
                (SurveyRating.respondent_id == SurveyAssignment.respondent_id)
                & (SurveyRating.recipe_id == SurveyAssignment.recipe_id),
            )
            .where(SurveyAssignment.respondent_id == resp.id, SurveyRating.recipe_id.is_(None))
            .order_by(SurveyAssignment.display_order)
        )
    )
    if missing:  # FR-23-12
        raise ApiError(
            422,
            ProblemCode.survey_incomplete,
            f"Còn {len(missing)} món chưa trả lời.",
            extra={"missing_recipe_ids": [str(m) for m in missing]},
        )
    resp.completed_at = utcnow()
    session.flush()
    return _out(session, resp, form)


# ---------------------------------------------------------------- UC24: forms (called by admin)


class SurveyFormError(ValueError):
    """A form operation that cannot be done; the message is for the operator (CLI exit 1)."""


def published_by_slot(session: Session) -> dict[str, int]:
    counts = Counter(r.slot for r in catalog.published_recipe_refs(session))
    return {s: counts.get(s, 0) for s in SLOTS}


def _next_version(session: Session, day: date) -> str:
    prefix = day.strftime("%Y%m%d")
    taken = set(session.scalars(select(SurveyForm.version).where(SurveyForm.version.like(f"{prefix}-%"))))
    n = 1
    while f"{prefix}-{n}" in taken:
        n += 1
    return f"{prefix}-{n}"


def open_form_summary(session: Session) -> SurveyFormSummary | None:
    form = session.scalars(select(SurveyForm).where(SurveyForm.is_open.is_(True))).first()
    return _summaries(session, [form])[0] if form else None


def create_form(session: Session, *, n_anchor: int, n_random: int, seed: int | None, today: date) -> CreatedForm:
    """FR-24-01..04: N anchors drawn by slot with a recorded seed, a new open version, the previous open form closed,
    all in the caller's transaction. Same seed + same set of published recipes = same anchors."""
    if n_anchor < 1 or n_random < 1:
        raise SurveyFormError("--anchors và --random phải là số nguyên dương")
    refs = catalog.published_recipe_refs(session)  # ordered by id: stable input for the seeded draw
    by_slot: dict[str, list[uuid.UUID]] = {s: [] for s in SLOTS}
    names = {r.id: r.name_vi for r in refs}
    slot_of = {r.id: r.slot for r in refs}
    for r in refs:
        by_slot.setdefault(r.slot, []).append(r.id)
    counts = {s: len(by_slot[s]) for s in SLOTS}
    if any(c == 0 for c in counts.values()) or n_anchor + n_random > len(refs):
        raise SurveyFormError(
            f"không đủ món published: cần {n_anchor} + {n_random} = {n_anchor + n_random}, mỗi slot ít nhất 1; "
            f"hiện có {len(refs)} ({', '.join(f'{s}={c}' for s, c in counts.items())})"
        )
    seed = secrets.randbits(32) if seed is None else seed
    anchors = design.pick_stratified(by_slot, n_anchor, counts, random.Random(seed))
    version = _next_version(session, today)

    previous = session.scalars(select(SurveyForm).where(SurveyForm.is_open.is_(True)).with_for_update()).all()
    for f in previous:
        f.is_open = False
    session.flush()
    # Anchors go in while the new form is still closed (trigger trg_survey_form_anchors_guard), then it opens.
    form = SurveyForm(version=version, n_anchor=n_anchor, n_random=n_random, is_open=False, created_at=utcnow())
    session.add(form)
    session.flush()
    session.add_all(SurveyFormAnchor(form_id=form.id, recipe_id=rid) for rid in anchors)
    session.flush()
    form.is_open = True
    session.flush()
    grouped: dict[str, list[str]] = {s: [] for s in SLOTS}
    for rid in anchors:
        grouped[slot_of[rid]].append(names[rid])
    return CreatedForm(
        form_id=form.id,
        version=version,
        seed=seed,
        anchors=grouped,
        closed_version=", ".join(f.version for f in previous) or None,
    )


def form_versions(session: Session) -> list[str]:
    return list(session.scalars(select(SurveyForm.version).order_by(SurveyForm.created_at)))


def set_open(session: Session, version: str | None, is_open: bool) -> tuple[SurveyForm, list[str]]:
    """Close a form (default: the open one) or reopen one; reopening closes any other open form (≤ 1 open)."""
    forms = session.scalars(select(SurveyForm).with_for_update()).all()
    if version is None:
        target = next((f for f in forms if f.is_open), None)
        if target is None:
            raise SurveyFormError("không có phiếu nào đang mở")
    else:
        target = next((f for f in forms if f.version == version), None)
        if target is None:
            raise SurveyFormError(
                f"không có phiếu {version}; hiện có: {', '.join(f.version for f in forms) or '(trống)'}"
            )
    closed: list[str] = []
    if is_open:
        for f in forms:
            if f.is_open and f.id != target.id:
                f.is_open = False
                closed.append(f.version)
        session.flush()
    target.is_open = is_open
    session.flush()
    return target, closed


def _summaries(session: Session, forms: list[SurveyForm]) -> list[SurveyFormSummary]:
    ids = [f.id for f in forms]
    counts = {
        fid: (int(total), int(done))
        for fid, total, done in session.execute(
            select(
                SurveyRespondent.form_id,
                func.count(),
                func.count(SurveyRespondent.completed_at),
            )
            .where(SurveyRespondent.form_id.in_(ids))
            .group_by(SurveyRespondent.form_id)
        )
    }
    return [
        SurveyFormSummary(
            id=f.id,
            version=f.version,
            n_anchor=f.n_anchor,
            n_random=f.n_random,
            is_open=f.is_open,
            created_at=f.created_at,
            respondents_total=counts.get(f.id, (0, 0))[0],
            respondents_completed=counts.get(f.id, (0, 0))[1],
        )
        for f in forms
    ]


def list_forms(session: Session, *, cursor: str | None, limit: int) -> SurveyFormSummaryPage:
    """FR-24-10, keyset (created_at, id)."""
    q = select(SurveyForm).order_by(SurveyForm.created_at, SurveyForm.id)
    after = pagination.decode_created(cursor)
    if after is not None:
        q = q.where(tuple_(SurveyForm.created_at, SurveyForm.id) > tuple_(*after))
    forms = list(session.scalars(q.limit(limit + 1)))
    more = len(forms) > limit
    forms = forms[:limit]
    nxt = pagination.encode_created(forms[-1].created_at, forms[-1].id) if more and forms else None
    return SurveyFormSummaryPage(items=_summaries(session, forms), next_cursor=nxt)


# ---------------------------------------------------------------- UC24: export


@dataclass
class _Table:
    name: str
    header: list[str]
    rows: list[list[Any]]


def _iso(v: datetime | None) -> str:
    return v.isoformat() if v else ""


def _csv(t: _Table) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(t.header)
    w.writerows(t.rows)
    return buf.getvalue().encode("utf-8")


def export(session: Session, version: str, out_base: Path) -> ExportResult:
    """FR-24-07..09: completed respondents only, respondent_id (random UUID) as the only identifier, six UTF-8 CSV
    files + manifest.json with sha256 per file, in a new directory `<out_base>/<version>-<UTC stamp>` written via a
    temporary directory (a failed export leaves nothing behind; an earlier export is never overwritten)."""
    form = session.scalars(select(SurveyForm).where(SurveyForm.version == version)).first()
    if form is None:
        raise SurveyFormError(f"không có phiếu {version}; hiện có: {', '.join(form_versions(session)) or '(trống)'}")
    resps = list(
        session.scalars(
            select(SurveyRespondent)
            .where(SurveyRespondent.form_id == form.id, SurveyRespondent.completed_at.is_not(None))
            .order_by(SurveyRespondent.completed_at, SurveyRespondent.id)
        )
    )
    rids = [r.id for r in resps]
    order = {rid: i for i, rid in enumerate(rids)}
    labels = privacy.policy_version_labels(session, {r.policy_version_id for r in resps})
    assigns = sorted(
        session.scalars(select(SurveyAssignment).where(SurveyAssignment.respondent_id.in_(rids))),
        key=lambda a: (order[a.respondent_id], a.display_order),
    )
    pos = {(a.respondent_id, a.recipe_id): a.display_order for a in assigns}
    ratings = sorted(
        session.scalars(select(SurveyRating).where(SurveyRating.respondent_id.in_(rids))),
        key=lambda r: (order[r.respondent_id], pos[(r.respondent_id, r.recipe_id)]),
    )
    favs = sorted(
        session.scalars(select(SurveyFavorite).where(SurveyFavorite.respondent_id.in_(rids))),
        key=lambda f: (order[f.respondent_id], str(f.recipe_id)),
    )
    anchors = _anchor_ids(session, form.id)
    recipe_ids = set(anchors) | {a.recipe_id for a in assigns} | {f.recipe_id for f in favs}
    refs = catalog.recipe_refs(session, recipe_ids)
    tables = [
        _Table(
            "respondents.csv",
            ["respondent_id", "policy_version", "consented_at", "completed_at", "channel"],
            [
                [r.id, labels.get(r.policy_version_id, ""), _iso(r.consented_at), _iso(r.completed_at), r.channel]
                for r in resps
            ],
        ),
        _Table(
            "assignments.csv",
            ["respondent_id", "recipe_id", "display_order", "is_anchor"],
            [[a.respondent_id, a.recipe_id, a.display_order, str(a.is_anchor).lower()] for a in assigns],
        ),
        _Table(
            "ratings.csv",
            ["respondent_id", "recipe_id", "rating", "never_eaten", "answered_at"],
            [
                [
                    r.respondent_id,
                    r.recipe_id,
                    "" if r.rating is None else r.rating,
                    str(r.never_eaten).lower(),
                    _iso(r.answered_at),
                ]
                for r in ratings
            ],
        ),
        _Table("favorites.csv", ["respondent_id", "recipe_id"], [[f.respondent_id, f.recipe_id] for f in favs]),
        _Table("anchors.csv", ["recipe_id", "slot"], [[a, refs[a].slot] for a in anchors]),
        _Table(
            "recipes.csv",
            ["recipe_id", "name_vi", "slot", "status"],
            [
                [r.id, r.name_vi, r.slot, r.status]
                for r in sorted(refs.values(), key=lambda x: (x.slot, x.name_vi, str(x.id)))
            ],
        ),
    ]
    now = utcnow()
    out_base = Path(out_base)
    out_base.mkdir(parents=True, exist_ok=True)
    final = out_base / f"{version}-{now.strftime('%Y%m%dT%H%M%SZ')}"
    n = 1
    while final.exists():
        n += 1
        final = out_base / f"{version}-{now.strftime('%Y%m%dT%H%M%SZ')}-{n}"
    tmp = out_base / f".{final.name}.partial"
    files: dict[str, dict[str, Any]] = {}
    try:
        tmp.mkdir()
        for t in tables:
            data = _csv(t)
            (tmp / t.name).write_bytes(data)
            files[t.name] = {"sha256": hashlib.sha256(data).hexdigest(), "rows": len(t.rows)}
        manifest = {
            "form_version": form.version,
            "form_id": str(form.id),
            "n_anchor": form.n_anchor,
            "n_random": form.n_random,
            "is_open": form.is_open,
            "exported_at": now.isoformat(),
            "respondents": len(resps),
            "ratings": len(ratings),
            "favorites": len(favs),
            "policy_versions": sorted(set(labels.values())),
            "files": files,
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return ExportResult(
        form_version=form.version,
        directory=str(final),
        is_open=form.is_open,
        respondents=len(resps),
        ratings=len(ratings),
        files=files,
    )
