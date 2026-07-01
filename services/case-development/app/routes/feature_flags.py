# Endpoints defined in this module:
#   GET   /api/v1/settings/feature-flags   — read firmSettings/feature_flags (min: settings.read)
#   PATCH /api/v1/settings/feature-flags   — update firmSettings/feature_flags (min: settings.write, admin only)

from fastapi import APIRouter, Request

from app.models.feature_flags import FeatureFlagsResponse, UpdateFeatureFlagsRequest
from app.services.feature_flags_service import get_feature_flags, update_feature_flags
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Feature Flags"])


def _get_actor_uid(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return user.get("uid", "system")


@router.get(
    "/settings/feature-flags",
    response_model=FeatureFlagsResponse,
    summary="Get current firm-wide feature flags",
)
def get_feature_flags_route(request: Request):
    db     = get_firestore_client()
    result = get_feature_flags(db)
    return FeatureFlagsResponse(**result)


@router.patch(
    "/settings/feature-flags",
    response_model=FeatureFlagsResponse,
    summary="Update firm-wide feature flags (admin only)",
)
def update_feature_flags_route(body: UpdateFeatureFlagsRequest, request: Request):
    db        = get_firestore_client()
    actor_uid = _get_actor_uid(request)
    fields    = {k: v for k, v in body.model_dump().items() if v is not None}
    result    = update_feature_flags(db=db, fields=fields, actor_uid=actor_uid)
    return FeatureFlagsResponse(**result)
