"""
main.py — Firebase Cloud Functions entry point
===============================================
Firebase CLI discovers functions by importing this module and finding
firebase_functions-decorated callables at the top level.

Architecture:
  functions/
    middleware/
      http.py          — shared HTTP utils, CORS, audit writer, db(), serialise_doc()
      jwt_middleware.py — JWT/session auth; re-exports from http.py
    auth/
      rbac.py          — roles, permissions, guards
      auth_service.py  — user creation, sessions, rate limiting, email dispatch
      triggers.py      — Firebase Auth onCreate / onDelete triggers
    api/
      auth_api.py      — register, createSession, logout, passwordReset, createInvite
      users.py         — createUser, listUsers, getUser, updateUser, deleteUser
      audit.py         — getAuditLog (senior_partner only)
"""

# ── SDK initialisation (must run before any firebase_admin calls) ─────────────

from dotenv import load_dotenv
from pathlib import Path
import os
CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent
env_path = BACKEND_DIR / ".env"
load_dotenv(env_path)

import firebase_admin
firebase_admin.initialize_app()
# ── Re-export every deployed function ─────────────────────────────────────────
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
from api.audit     import get_audit_log_fn
from auth.triggers import on_user_created
