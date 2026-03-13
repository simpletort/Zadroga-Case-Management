"""
auth/triggers.py — Firebase Auth event triggers
=================================================
NOTE: The Python Firebase Functions SDK does NOT support Auth event triggers
(onCreate / onDelete). These are only available in the Node.js SDK.

As a workaround, the on_user_created logic is handled directly inside
create_user() in auth_service.py when the user is created via the API.

The on_user_deleted logic is handled inside delete_user_fn() in api/users.py.

This file is kept as a placeholder so main.py imports don't break.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def on_user_created(event: object = None) -> None:  # type: ignore[override]
    """
    Not supported in Python Firebase Functions SDK.
    User creation side-effects are handled in auth_service.create_user().
    """
    logger.warning("on_user_created called as stub — Auth triggers not supported in Python SDK")


def on_user_deleted(event: object = None) -> None:  # type: ignore[override]
    """
    Not supported in Python Firebase Functions SDK.
    User deletion side-effects are handled in api/users.delete_user_fn().
    """
    logger.warning("on_user_deleted called as stub — Auth triggers not supported in Python SDK")
