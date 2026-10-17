"""profile public interface (M05): profile with encrypted body metrics, allergens, diet, favourites, settings,
energy suggestion / target, and `get_meal_constraints()` for meal planning (ADR 0005).

Body metrics are encrypted per column (crypto.FieldCipher) and decrypted only here; every decryption writes one
audit_log row. Storing them requires the `health_profile` consent (BR-CONSENT-02).
"""

from __future__ import annotations

import uuid
import zoneinfo
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tastoria.core.auth import AuthUser
from tastoria.core.clock import local_year, utcnow
from tastoria.core.config import Settings
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.catalog import service as catalog
from tastoria.modules.privacy import service as privacy
from tastoria.modules.profile import energy
from tastoria.modules.profile.crypto import DecryptionFailed, FieldCipher
from tastoria.modules.profile.models import Profile, UserAllergen, UserFavoriteRecipe, UserSettings
from tastoria.modules.profile.schemas import (
    AllergenSet,
    DietSelection,
    EnergySuggestion,
    EnergySuggestionRequest,
    EnergyTarget,
    EnergyTargetOut,
    FavoriteSet,
    ProfileOut,
    ProfileUpdate,
    UserSettingsIn,
    UserSettingsOut,
)

HEALTH = "health_profile"
METRICS = ("sex", "birth_year", "height_cm", "weight_kg")
FAVORITES_MAX = 5
DEFAULT_SETTINGS = {"burners": 2, "default_persons": 2, "timezone": "Asia/Ho_Chi_Minh"}


@dataclass(frozen=True)
class ProfileDeps:
    settings: Settings
    cipher: FieldCipher


def make_cipher(settings: Settings) -> FieldCipher:
    keys = {kid: settings.enc_key(kid) for kid in settings.health_enc_keys}
    return FieldCipher({k: v for k, v in keys.items() if v is not None}, settings.health_enc_active_key_id)


def profile_deps(request: Request) -> ProfileDeps:
    return request.app.state.profile


@dataclass(frozen=True)
class Metrics:
    sex: str | None = None
    birth_year: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None


@dataclass(frozen=True)
class MealConstraints:
    """What meal planning may know about a user (ADR 0005): no raw body metrics."""

    e_meal_kcal: dict[str, int] | None  # {"lunch": .., "dinner": ..}; None → no target (β = 0, BR-CONSENT-02)
    allergen_codes: list[str]
    diet_code: str | None
    favorite_recipe_ids: list[uuid.UUID]
    burners: int
    default_persons: int
    timezone: str


# ---------------------------------------------------------------- rows


def _row(session: Session, user_id: uuid.UUID, *, create: bool) -> Profile | None:
    if create:
        session.execute(insert(Profile).values(user_id=user_id, updated_at=utcnow()).on_conflict_do_nothing())
    return session.scalars(select(Profile).where(Profile.user_id == user_id).with_for_update()).one_or_none()


def _has_metrics(p: Profile | None) -> bool:
    return p is not None and any(getattr(p, f"{m}_enc") is not None for m in METRICS)


def _decrypt(session: Session, deps: ProfileDeps, p: Profile, *, purpose: str, actor: uuid.UUID | None) -> Metrics:
    privacy.write_audit(
        session,
        action="decrypt",
        entity="profiles",
        entity_id=str(p.user_id),
        purpose=purpose,
        actor_user_id=actor,
        actor_role="user" if actor else "system",
    )
    try:
        vals = {
            m: deps.cipher.decrypt(p.enc_key_id, p.user_id, f"{m}_enc", blob)
            for m in METRICS
            if (blob := getattr(p, f"{m}_enc")) is not None
        }
    except DecryptionFailed:
        raise ApiError(500, ProblemCode.decryption_failed, extra={"enc_key_id": p.enc_key_id}) from None
    return Metrics(
        sex=vals.get("sex"),
        birth_year=int(vals["birth_year"]) if "birth_year" in vals else None,
        height_cm=float(vals["height_cm"]) if "height_cm" in vals else None,
        weight_kg=float(vals["weight_kg"]) if "weight_kg" in vals else None,
    )


def _missing(m: Metrics, activity: str | None) -> list[str]:
    missing = [f for f in ("sex", "birth_year", "weight_kg") if getattr(m, f) is None]
    if activity is None:
        missing.append("activity_level")
    return missing


def _age(birth_year: int, settings: Settings) -> int:
    return local_year(settings.timezone) - birth_year


def _suggest(m: Metrics, activity: str, goal: str, settings: Settings, *, mifflin: bool = False) -> energy.EnergyResult:
    assert m.sex and m.birth_year and m.weight_kg
    age = _age(m.birth_year, settings)
    if age < energy.MIN_AGE:
        raise ApiError(422, ProblemCode.age_below_minimum)
    return energy.suggest(
        sex=m.sex,  # type: ignore[arg-type]
        age=age,
        weight_kg=Decimal(str(m.weight_kg)),
        height_cm=Decimal(str(m.height_cm)) if m.height_cm is not None else None,
        activity_level=activity,  # type: ignore[arg-type]
        goal=goal,  # type: ignore[arg-type]
        with_mifflin=mifflin,
    )


def _formula_goal(goal: str | None) -> str:
    return goal if goal in ("maintain", "lose") else "maintain"


def _stale(m: Metrics, p: Profile, settings: Settings) -> tuple[bool, int | None]:
    if p.kcal_source != "suggested" or _missing(m, p.activity_level):
        return False, None
    try:
        e = _suggest(m, p.activity_level, _formula_goal(p.goal), settings).suggested_kcal  # type: ignore[arg-type]
    except ApiError:
        return False, None
    return e != p.kcal_target, e


def _out(
    session: Session, user_id: uuid.UUID, p: Profile | None, m: Metrics, consented: bool, settings: Settings
) -> ProfileOut:
    stale, suggested = _stale(m, p, settings) if p is not None and consented else (False, None)
    return ProfileOut(
        sex=m.sex,  # type: ignore[arg-type]
        birth_year=m.birth_year,
        height_cm=m.height_cm,
        weight_kg=m.weight_kg,
        activity_level=p.activity_level if p else None,  # type: ignore[arg-type]
        goal=p.goal if p else None,  # type: ignore[arg-type]
        kcal_target=p.kcal_target if p else None,
        kcal_source=p.kcal_source if p else None,  # type: ignore[arg-type]
        diet_code=p.diet_code if p else None,
        allergen_codes=_allergens(session, user_id),
        favorite_recipe_ids=_favorites(session, user_id),
        health_profile_consented=consented,
        updated_at=p.updated_at if p else None,
        target_stale=stale,
        suggested_kcal=suggested,
    )


def _allergens(session: Session, user_id: uuid.UUID) -> list[str]:
    return sorted(session.scalars(select(UserAllergen.allergen_code).where(UserAllergen.user_id == user_id)).all())


def _favorites(session: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(UserFavoriteRecipe.recipe_id)
            .where(UserFavoriteRecipe.user_id == user_id)
            .order_by(UserFavoriteRecipe.created_at, UserFavoriteRecipe.recipe_id)
        ).all()
    )


def _field_error(pointer: str, code: str, message: str) -> ApiError:
    return ApiError(422, ProblemCode.validation_error, errors=[{"pointer": pointer, "code": code, "message": message}])


def _require_health_consent(session: Session, user_id: uuid.UUID) -> None:
    if not privacy.has_consent(session, user_id, HEALTH):
        raise ApiError(403, ProblemCode.consent_required, extra={"purpose": HEALTH})


# ---------------------------------------------------------------- profile (UC09, UC10)


def get_profile(session: Session, deps: ProfileDeps, user: AuthUser) -> ProfileOut:
    consented = privacy.has_consent(session, user.id, HEALTH)
    p = session.get(Profile, user.id)
    m = Metrics()
    if consented and _has_metrics(p):
        m = _decrypt(session, deps, p, purpose=HEALTH, actor=user.id)  # type: ignore[arg-type]
    return _out(session, user.id, p, m, consented, deps.settings)


def update_profile(session: Session, deps: ProfileDeps, user: AuthUser, body: ProfileUpdate) -> ProfileOut:
    gives_health = any(
        getattr(body, f) is not None for f in (*METRICS, "activity_level", "goal")
    )  # FR-10-02: activity and goal are health_profile data too
    if gives_health:
        _require_health_consent(session, user.id)
    if body.birth_year is not None:
        age = _age(body.birth_year, deps.settings)
        if age < energy.MIN_AGE:
            raise ApiError(422, ProblemCode.age_below_minimum)
        if age == energy.MIN_AGE and not body.adult_confirmed:  # may still be 17 this year (FR-09-13)
            raise ApiError(422, ProblemCode.age_confirmation_required)

    p = _row(session, user.id, create=True)
    assert p is not None
    if p.kcal_source == "expert" and body.goal != "expert":
        raise _field_error("/goal", "expert_target", "Mục tiêu do chuyên gia đặt; đổi qua PUT /me/energy-target.")
    if body.goal == "expert" and p.kcal_source in ("suggested", "user"):
        raise _field_error("/goal", "expert_target", "Đặt mục tiêu chuyên gia qua PUT /me/energy-target.")

    values = {"sex": body.sex, "birth_year": body.birth_year, "height_cm": body.height_cm, "weight_kg": body.weight_kg}
    key_id = None
    for name, value in values.items():
        if value is None:
            setattr(p, f"{name}_enc", None)
            continue
        blob, key_id = deps.cipher.encrypt(user.id, f"{name}_enc", str(value))
        setattr(p, f"{name}_enc", blob)
    p.enc_key_id = key_id
    p.activity_level = body.activity_level
    p.goal = body.goal
    p.updated_at = utcnow()
    session.flush()
    m = Metrics(**values)
    return _out(session, user.id, p, m, gives_health or privacy.has_consent(session, user.id, HEALTH), deps.settings)


# ---------------------------------------------------------------- energy (UC11)


def suggest_energy(
    session: Session, deps: ProfileDeps, user: AuthUser, body: EnergySuggestionRequest
) -> EnergySuggestion:
    _require_health_consent(session, user.id)
    p = session.get(Profile, user.id)
    m = _decrypt(session, deps, p, purpose=HEALTH, actor=user.id) if _has_metrics(p) else Metrics()  # type: ignore[arg-type]
    missing = _missing(m, p.activity_level if p else None)
    if missing:
        raise ApiError(422, ProblemCode.profile_incomplete, extra={"missing": missing})
    goal = body.goal or _formula_goal(p.goal if p else None)
    r = _suggest(m, p.activity_level, goal, deps.settings, mifflin=body.formula == "mifflin_st_jeor")  # type: ignore[union-attr,arg-type]
    return EnergySuggestion(
        formula="fao_who_unu_1985",
        bmr_kcal=float(r.bmr_kcal),
        pal=float(r.pal),
        tee_kcal=float(r.tee_kcal),
        suggested_kcal=r.suggested_kcal,
        floor_applied=r.floor_applied,
        e_lunch_kcal=r.e_lunch_kcal,
        e_dinner_kcal=r.e_dinner_kcal,
        goal=goal,  # type: ignore[arg-type]
        age_years=_age(m.birth_year, deps.settings),  # type: ignore[arg-type]
        equation=energy.EQUATION_LABEL,
        source=energy.SOURCE,
        bmr_mifflin_kcal=float(r.bmr_mifflin_kcal) if r.bmr_mifflin_kcal is not None else None,
    )


def set_energy_target(session: Session, deps: ProfileDeps, user: AuthUser, body: EnergyTarget) -> EnergyTargetOut:
    _require_health_consent(session, user.id)
    p = _row(session, user.id, create=True)
    assert p is not None
    below = False
    if body.kcal_source == "suggested":
        if body.goal == "expert":
            raise _field_error("/goal", "invalid", "goal expert cần kcal_source expert")
        m = _decrypt(session, deps, p, purpose=HEALTH, actor=user.id) if _has_metrics(p) else Metrics()
        missing = _missing(m, p.activity_level)
        if missing:
            raise ApiError(422, ProblemCode.profile_incomplete, extra={"missing": missing})
        goal = body.goal or _formula_goal(p.goal)
        kcal = _suggest(m, p.activity_level, goal, deps.settings).suggested_kcal  # type: ignore[arg-type]
        if not 800 <= kcal <= 5000:
            raise _field_error("/kcal_target", "out_of_range", f"{kcal} ngoài [800, 5000]")
    elif body.kcal_source == "expert":
        if body.goal not in (None, "expert"):
            raise _field_error("/goal", "invalid", "kcal_source expert đi với goal expert")
        goal, kcal = "expert", body.kcal_target  # an expert target overrides every formula (BR-NUT-03)
    else:  # user-entered
        if body.goal == "expert":
            raise _field_error("/goal", "invalid", "goal expert cần kcal_source expert")
        goal = body.goal or (p.goal if p.goal != "expert" else None)
        kcal = body.kcal_target
        m = _decrypt(session, deps, p, purpose=HEALTH, actor=user.id) if p.sex_enc is not None else Metrics()
        if m.sex is not None and energy.below_floor(kcal, m.sex):  # type: ignore[arg-type]
            below = True
            if not body.confirm_below_floor:
                floor = energy.FLOOR[m.sex]  # type: ignore[index]
                raise ApiError(409, ProblemCode.below_floor_confirmation_required, extra={"floor_kcal": floor})
    p.kcal_target, p.kcal_source, p.goal = kcal, body.kcal_source, goal
    p.updated_at = utcnow()
    session.flush()
    return EnergyTargetOut(
        kcal_target=kcal,
        kcal_source=body.kcal_source,
        goal=goal,  # type: ignore[arg-type]
        below_floor=below,
        e_lunch_kcal=energy.meal_energy(kcal, "lunch"),
        e_dinner_kcal=energy.meal_energy(kcal, "dinner"),
    )


# ---------------------------------------------------------------- allergens, diet, favourites (UC09, UC10)


def set_allergens(session: Session, user: AuthUser, body: AllergenSet) -> AllergenSet:
    codes = sorted(set(body.allergen_codes))
    unknown = catalog.unknown_allergen_codes(session, codes)
    if unknown:
        raise ApiError(422, ProblemCode.unknown_code, extra={"unknown": unknown})
    session.execute(
        delete(UserAllergen).where(UserAllergen.user_id == user.id, UserAllergen.allergen_code.not_in(codes))
    )
    if codes:
        session.execute(
            insert(UserAllergen)
            .values([{"user_id": user.id, "allergen_code": c} for c in codes])
            .on_conflict_do_nothing()
        )
    return AllergenSet(allergen_codes=_allergens(session, user.id))


def set_diet(session: Session, user: AuthUser, body: DietSelection) -> DietSelection:
    if body.diet_code is not None and not catalog.diet_exists(session, body.diet_code):
        raise ApiError(422, ProblemCode.unknown_code, extra={"unknown": [body.diet_code]})
    p = _row(session, user.id, create=True)
    assert p is not None
    p.diet_code = body.diet_code
    p.updated_at = utcnow()
    return DietSelection(diet_code=p.diet_code)


def set_favorites(session: Session, user: AuthUser, body: FavoriteSet) -> FavoriteSet:
    ids = list(dict.fromkeys(body.recipe_ids))
    if len(ids) > FAVORITES_MAX:
        raise ApiError(422, ProblemCode.favorites_limit, extra={"max": FAVORITES_MAX})
    bad = catalog.not_published_recipe_ids(session, ids)
    if bad:
        raise ApiError(422, ProblemCode.recipe_not_published, extra={"recipe_ids": [str(b) for b in bad]})
    session.execute(
        delete(UserFavoriteRecipe).where(
            UserFavoriteRecipe.user_id == user.id, UserFavoriteRecipe.recipe_id.not_in(ids)
        )
    )
    if ids:
        now = utcnow()
        session.execute(
            insert(UserFavoriteRecipe)
            .values([{"user_id": user.id, "recipe_id": rid, "created_at": now} for rid in ids])
            .on_conflict_do_nothing()
        )
    return FavoriteSet(recipe_ids=_favorites(session, user.id))


# ---------------------------------------------------------------- settings (UC10)


def get_settings(session: Session, user: AuthUser) -> UserSettingsOut:
    s = session.get(UserSettings, user.id)
    if s is None:
        return UserSettingsOut(**DEFAULT_SETTINGS, updated_at=None)  # FR-10-09
    return UserSettingsOut(
        burners=s.burners, default_persons=s.default_persons, timezone=s.timezone, updated_at=s.updated_at
    )


def _valid_timezone(name: str) -> bool:
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return False
    return True


def update_settings(session: Session, user: AuthUser, body: UserSettingsIn) -> UserSettingsOut:
    bad_tz = ApiError(
        422,
        ProblemCode.validation_error,
        errors=[{"pointer": "/timezone", "code": "invalid_timezone", "message": "Không phải tên múi giờ IANA."}],
    )
    if not _valid_timezone(body.timezone):
        raise bad_tz
    now = utcnow()
    stmt = insert(UserSettings).values(user_id=user.id, **body.model_dump(), updated_at=now)
    stmt = stmt.on_conflict_do_update(index_elements=["user_id"], set_={**body.model_dump(), "updated_at": now})
    try:
        with session.begin_nested():
            session.execute(stmt)
    except DBAPIError:  # trg_user_settings_timezone: PostgreSQL does not know this zone
        raise bad_tz from None
    return get_settings(session, user)


# ---------------------------------------------------------------- for other modules


def get_meal_constraints(session: Session, user_id: uuid.UUID) -> MealConstraints:
    """Read fresh on every call (FR-10-08). No decryption: E comes from the stored target, not from metrics."""
    p = session.get(Profile, user_id)
    e_meal = None
    if p is not None and p.kcal_target is not None and privacy.has_consent(session, user_id, HEALTH):
        e_meal = {
            "lunch": energy.meal_energy(p.kcal_target, "lunch"),
            "dinner": energy.meal_energy(p.kcal_target, "dinner"),
        }
    s = session.get(UserSettings, user_id)
    return MealConstraints(
        e_meal_kcal=e_meal,
        allergen_codes=_allergens(session, user_id),
        diet_code=p.diet_code if p else None,
        favorite_recipe_ids=_favorites(session, user_id),
        burners=s.burners if s else DEFAULT_SETTINGS["burners"],
        default_persons=s.default_persons if s else DEFAULT_SETTINGS["default_persons"],
        timezone=s.timezone if s else DEFAULT_SETTINGS["timezone"],
    )


class ProfileSubjectData:
    """profile's part of data-subject requests, registered with privacy by tastoria.app."""

    name = "profile"

    def __init__(self, deps: ProfileDeps) -> None:
        self.deps = deps

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        p = session.get(Profile, user_id)
        profiles: list[dict[str, Any]] = []
        if p is not None:
            row: dict[str, Any] = {
                "activity_level": p.activity_level,
                "goal": p.goal,
                "kcal_target": p.kcal_target,
                "kcal_source": p.kcal_source,
                "diet_code": p.diet_code,
                "updated_at": p.updated_at.isoformat(),
            }
            if _has_metrics(p):
                try:
                    m = _decrypt(session, self.deps, p, purpose="dsr_export", actor=None)
                    row.update(sex=m.sex, birth_year=m.birth_year, height_cm=m.height_cm, weight_kg=m.weight_kg)
                except ApiError:  # UC06 6c: say so in the file, finish the job
                    row.update(metrics="không giải mã được", enc_key_id=p.enc_key_id)
            profiles.append(row)
        favs = session.scalars(select(UserFavoriteRecipe).where(UserFavoriteRecipe.user_id == user_id)).all()
        s = session.get(UserSettings, user_id)
        return {
            "profiles": profiles,
            "user_allergens": [{"allergen_code": c} for c in _allergens(session, user_id)],
            "user_favorite_recipes": [
                {"recipe_id": str(f.recipe_id), "created_at": f.created_at.isoformat()} for f in favs
            ],
            "user_settings": [
                {
                    "burners": s.burners,
                    "default_persons": s.default_persons,
                    "timezone": s.timezone,
                    "updated_at": s.updated_at.isoformat(),
                }
            ]
            if s
            else [],
        }

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None:
        if purpose != HEALTH:
            return
        p = session.get(Profile, user_id, with_for_update=True)
        if p is None:
            return
        # FR-05-11: the seven columns go to NULL; goal stays (it does not reveal a metric on its own).
        p.sex_enc = p.birth_year_enc = p.height_cm_enc = p.weight_kg_enc = None
        p.enc_key_id = None
        p.kcal_target = None
        p.kcal_source = None
        p.updated_at = utcnow()
        session.flush()

    def erase_files(self, user_id: uuid.UUID) -> None:
        return None
