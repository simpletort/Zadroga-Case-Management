"""
services/opt_out_service.py — SMS opt-out / suppression list.

Opt-out documents are stored in Firestore under:
    /{opt_outs_collection}/{e164_phone}

Document schema
---------------
    phone        : str   — E.164 phone number (also the document ID)
    smsOptedOut  : bool  — True if recipient has opted out of SMS
    optedOutAt   : timestamp | null
    reason       : str   — "STOP", "UNSUBSCRIBE", "manual", etc.
    updatedAt    : timestamp

Design notes
------------
* Document IDs use the E.164 phone number (e.g. ``+12125551234``).
  Firestore document IDs may contain ``+`` and digits so this is safe.
* The ``smsOptedOut`` field is checked; the document being absent means
  the recipient has NOT opted out.
* ``record_opt_out`` and ``clear_opt_out`` are provided for the inbound
  STOP/START handler (wired in app.py).
"""
from __future__ import annotations

from datetime import datetime

from google.cloud import firestore
from google.cloud.firestore_v1.async_client import AsyncClient

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)


async def is_opted_out(phone: str, db: AsyncClient) -> bool:
    """
    Return True if *phone* has opted out of SMS notifications.

    Parameters
    ----------
    phone:
        E.164 phone number (e.g. ``+12125551234``).
    db:
        Async Firestore client.
    """
    settings = get_settings()
    doc_ref = db.collection(settings.opt_outs_collection).document(phone)
    doc = await doc_ref.get()

    if not doc.exists:
        return False

    data = doc.to_dict()
    opted_out = bool(data.get("smsOptedOut", False))

    if opted_out:
        logger.info(
            "sms_opt_out_hit",
            phone_masked="[REDACTED]",
            reason=data.get("reason", "unknown"),
        )

    return opted_out


async def record_opt_out(
    phone: str,
    reason: str,
    db: AsyncClient,
) -> None:
    """
    Record an opt-out for *phone* in Firestore.

    Called when a STOP/UNSUBSCRIBE inbound message is received from Twilio
    (via the webhook handler in app.py) or when ops manually suppress a number.
    """
    settings = get_settings()
    doc_ref = db.collection(settings.opt_outs_collection).document(phone)
    await doc_ref.set(
        {
            "phone": phone,
            "smsOptedOut": True,
            "optedOutAt": datetime.utcnow().isoformat() + "Z",
            "reason": reason,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    logger.info(
        "sms_opt_out_recorded",
        phone_masked="[REDACTED]",
        reason=reason,
    )


async def clear_opt_out(phone: str, db: AsyncClient) -> None:
    """
    Remove the opt-out flag for *phone* (e.g. after a START reply).
    """
    settings = get_settings()
    doc_ref = db.collection(settings.opt_outs_collection).document(phone)
    await doc_ref.set(
        {
            "smsOptedOut": False,
            "clearedAt": datetime.utcnow().isoformat() + "Z",
            "updatedAt": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    logger.info("sms_opt_out_cleared", phone_masked="[REDACTED]")
