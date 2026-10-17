"""HTTP layer of profile: /me/profile, /me/energy-*, /me/allergens, /me/diet, /me/favorites, /me/settings."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends

from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.modules.profile import service
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
from tastoria.modules.profile.service import ProfileDeps, profile_deps

router = APIRouter(prefix="/me", tags=["profile"])
Deps = Annotated[ProfileDeps, Depends(profile_deps)]


@router.get("/profile", operation_id="profile_get_profile")
def get_profile(user: CurrentUser, uow: Uow, deps: Deps) -> ProfileOut:
    return service.get_profile(uow.session, deps, user)


@router.put("/profile", operation_id="profile_update_profile")
def update_profile(body: ProfileUpdate, user: CurrentUser, uow: Uow, deps: Deps) -> ProfileOut:
    return service.update_profile(uow.session, deps, user, body)


@router.post("/energy-suggestion", operation_id="profile_suggest_energy")
def suggest_energy(
    user: CurrentUser, uow: Uow, deps: Deps, body: Annotated[EnergySuggestionRequest | None, Body()] = None
) -> EnergySuggestion:
    return service.suggest_energy(uow.session, deps, user, body or EnergySuggestionRequest())


@router.put("/energy-target", operation_id="profile_set_energy_target")
def set_energy_target(body: EnergyTarget, user: CurrentUser, uow: Uow, deps: Deps) -> EnergyTargetOut:
    return service.set_energy_target(uow.session, deps, user, body)


@router.put("/allergens", operation_id="profile_set_allergens")
def set_allergens(body: AllergenSet, user: CurrentUser, uow: Uow) -> AllergenSet:
    return service.set_allergens(uow.session, user, body)


@router.put("/diet", operation_id="profile_set_diet")
def set_diet(body: DietSelection, user: CurrentUser, uow: Uow) -> DietSelection:
    return service.set_diet(uow.session, user, body)


@router.put("/favorites", operation_id="profile_set_favorites")
def set_favorites(body: FavoriteSet, user: CurrentUser, uow: Uow) -> FavoriteSet:
    return service.set_favorites(uow.session, user, body)


@router.get("/settings", operation_id="profile_get_settings")
def get_settings(user: CurrentUser, uow: Uow) -> UserSettingsOut:
    return service.get_settings(uow.session, user)


@router.put("/settings", operation_id="profile_update_settings")
def update_settings(body: UserSettingsIn, user: CurrentUser, uow: Uow) -> UserSettingsOut:
    return service.update_settings(uow.session, user, body)
