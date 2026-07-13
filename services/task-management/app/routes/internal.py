"""
Internal endpoints called by Cloud Tasks (not public API).

Authentication: Cloud Tasks attaches an OIDC token signed by the service account.
We verify the token using google-auth rather than Firebase.
"""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services import task_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


class ReminderPayload(BaseModel):
    taskId: str
    caseId: str
    dueAt: str   # ISO string — informational only; we re-check Firestore state


async def _verify_oidc_token(request: Request) -> None:
    """
    Verify that the request comes from Cloud Tasks via an OIDC token.
    In production, Cloud Run also enforces that only the configured service account
    can invoke this URL, so this is a belt-and-suspenders check.
    """
    from app.config import get_settings
    settings = get_settings()

    # In non-production environments allow bypass for local testing
    if settings.environment != "production":
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing OIDC token.")

    token = auth_header.removeprefix("Bearer ")
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token
        google.oauth2.id_token.verify_oauth2_token(
            token,
            google.auth.transport.requests.Request(),
            audience=settings.task_service_url,
        )
    except Exception as e:
        logger.warning("oidc_verification_failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid OIDC token.")


@router.post("/reminders")
async def handle_reminder(payload: ReminderPayload, request: Request):
    await _verify_oidc_token(request)
    logger.info("reminder_callback task_id=%s case_id=%s", payload.taskId, payload.caseId)
    task = task_service.mark_overdue(payload.taskId, payload.caseId)
    return {"taskId": task.taskId, "status": task.status}
