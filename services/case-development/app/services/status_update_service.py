import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from google.cloud import firestore

logger = logging.getLogger(__name__)


def update_case_status(
    db: firestore.Client,
    case_id: str,
    new_status: str,
    actor_uid: str,
    actor_name: Optional[str],
    notes: Optional[str] = None,
) -> dict:
    case_ref  = db.collection("cases").document(case_id)
    case_snap = case_ref.get()

    if not case_snap.exists:
        raise HTTPException(status_code=404, detail="Case '{}' not found.".format(case_id))

    previous_status = (case_snap.to_dict() or {}).get("status", "")
    now = datetime.now(tz=timezone.utc)

    batch = db.batch()

    batch.update(case_ref, {
        "status":              new_status,
        "updatedAt":           now,
        "lastStatusChangedAt": now,
    })

    timeline_ref = case_ref.collection("timeline").document()
    batch.set(timeline_ref, {
        "eventId":         timeline_ref.id,
        "caseId":          case_id,
        "eventType":       "StatusChange",
        "description":     "Case status manually updated to '{}' by {}.".format(
            new_status, actor_name or actor_uid
        ),
        "performedBy":     actor_uid,
        "performedByName": actor_name,
        "timestamp":       now,
        "metadata": {
            "previousStatus": previous_status,
            "newStatus":      new_status,
            "notes":          notes,
            "source":         "manual_override",
        },
    })

    batch.commit()

    logger.info(
        "Case %s status manually updated: %s → %s by %s",
        case_id, previous_status, new_status, actor_uid,
    )

    return {
        "case_id":         case_id,
        "previous_status": previous_status,
        "new_status":      new_status,
        "updated_at":      now,
        "updated_by":      actor_uid,
    }
