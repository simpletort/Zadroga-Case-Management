"""
main.py — Firebase Cloud Functions entry point
===============================================
Firebase CLI discovers functions by importing this module.
All deployed functions must be top-level names here.
"""

import firebase_admin
firebase_admin.initialize_app()

from api.users import (
    create_user_fn,
    list_users_fn,
    get_user_fn,
    update_user_fn,
    delete_user_fn,
)
from api.auth_api import (
    register_fn,
    create_session_fn,
    logout_fn,
    password_reset_fn,
    create_invite_fn,
)
from api.audit import get_audit_log_fn

# Auth event triggers are NOT supported in Python SDK.
# onCreate/onDelete side-effects are handled inside the HTTP functions.
