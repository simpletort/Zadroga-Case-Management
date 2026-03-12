"""
tests/test_rbac.py — Unit tests for auth/rbac.py
=================================================
F-05 fix: previously rbac.py had no independent Python test coverage.
Run:  pytest tests/test_rbac.py -v
"""

import sys
from unittest.mock import MagicMock, patch

# ── Stub firebase deps so tests run without a real project ────────────────────
_fb = MagicMock()
for mod in ["firebase_admin", "firebase_admin.firestore", "firebase_functions",
            "firebase_functions.https_fn"]:
    sys.modules.setdefault(mod, _fb)

_mw = MagicMock()
_mw.json_err    = lambda msg, code: ({"error": msg}, code)
_mw.CORS_HEADERS = {}
_mw.write_audit_event = MagicMock()
_mw.db = MagicMock()
sys.modules.setdefault("middleware.http", _mw)
sys.modules.setdefault("middleware.jwt_middleware", _mw)

import pytest
from auth.rbac import (
    Role, Permission, ROLE_PERMISSIONS,
    has_permission, get_role_permissions,
    require_permission, require_any, log_role_change,
)

# ── Expected matrix ───────────────────────────────────────────────────────────
CLIENT_PERMS = {Permission.VIEW_OWN_CASE, Permission.VIEW_OWN_DOCUMENTS, Permission.UPLOAD_DOCUMENTS}
ADMIN_PERMS  = {Permission.VIEW_ALL_CASES, Permission.MANAGE_TASKS, Permission.LOG_COMMUNICATIONS,
                Permission.VIEW_DOCUMENTS, Permission.VIEW_NOTES, Permission.MANAGE_USERS}
PARA_PERMS   = {Permission.VIEW_ALL_CASES, Permission.MANAGE_TASKS, Permission.LOG_COMMUNICATIONS,
                Permission.VIEW_DOCUMENTS, Permission.VIEW_NOTES, Permission.REQUEST_DOCUMENTS,
                Permission.UPLOAD_DOCUMENTS, Permission.ADD_NOTES, Permission.SUBMIT_FOR_REVIEW}
JUNIOR_PERMS = PARA_PERMS | {Permission.APPROVE_REJECT, Permission.ESCALATE, Permission.VIEW_PHI}
SENIOR_PERMS = set(Permission)

FULL_MATRIX  = {
    Role.CLIENT: CLIENT_PERMS, Role.ADMIN_STAFF: ADMIN_PERMS,
    Role.PARALEGAL: PARA_PERMS, Role.JUNIOR_PARTNER: JUNIOR_PERMS,
    Role.SENIOR_PARTNER: SENIOR_PERMS,
}

# ── Build parametrized role×permission triples ────────────────────────────────
_PARAMS = [
    pytest.param(r.value, p, p in FULL_MATRIX[r], id=f"{r.value}::{p.value}")
    for r in Role for p in Permission
]

class TestMatrix:
    @pytest.mark.parametrize("role,perm,expected", _PARAMS)
    def test_has_permission(self, role, perm, expected):
        assert has_permission(role, perm) == expected

    @pytest.mark.parametrize("role", list(Role))
    def test_exact_set(self, role):
        assert ROLE_PERMISSIONS[role] == FULL_MATRIX[role], (
            f"{role.value}: missing={FULL_MATRIX[role]-ROLE_PERMISSIONS[role]}, "
            f"extra={ROLE_PERMISSIONS[role]-FULL_MATRIX[role]}"
        )

    def test_admin_staff_has_manage_users(self):
        """F-04 regression guard."""
        assert has_permission("admin_staff", Permission.MANAGE_USERS)

    def test_invalid_role_returns_false(self):
        assert not has_permission("hacker", Permission.SYSTEM_ADMIN)
        assert not has_permission("", Permission.VIEW_ALL_CASES)

    def test_senior_partner_has_all(self):
        assert ROLE_PERMISSIONS[Role.SENIOR_PARTNER] == set(Permission)

class TestGetRolePermissions:
    @pytest.mark.parametrize("role", list(Role))
    def test_string_set_matches(self, role):
        assert set(get_role_permissions(role.value)) == {p.value for p in FULL_MATRIX[role]}

    def test_invalid_returns_empty(self):
        assert get_role_permissions("ghost") == []

class TestRequirePermission:
    def _u(self, role): return {"uid": "x", "role": role}

    def test_passes_when_permitted(self):
        assert require_permission(self._u("senior_partner"), Permission.VIEW_AUDIT_LOG) is None

    def test_returns_response_when_denied(self):
        assert require_permission(self._u("client"), Permission.MANAGE_USERS) is not None

    def test_admin_staff_can_manage_users(self):
        assert require_permission(self._u("admin_staff"), Permission.MANAGE_USERS) is None

    def test_missing_role_denied(self):
        assert require_permission({"uid": "x"}, Permission.VIEW_AUDIT_LOG) is not None

class TestRequireAny:
    def _u(self, role): return {"uid": "x", "role": role}

    def test_passes_if_any_match(self):
        # paralegal has ADD_NOTES but not APPROVE_REJECT
        assert require_any(self._u("paralegal"), Permission.APPROVE_REJECT, Permission.ADD_NOTES) is None

    def test_denied_if_none_match(self):
        assert require_any(self._u("client"), Permission.MANAGE_USERS, Permission.VIEW_AUDIT_LOG) is not None

    def test_empty_list_denied(self):
        assert require_any(self._u("senior_partner")) is not None

class TestHierarchyInvariants:
    def test_junior_superset_of_paralegal(self):
        assert PARA_PERMS.issubset(JUNIOR_PERMS)

    def test_senior_superset_of_junior(self):
        assert JUNIOR_PERMS.issubset(SENIOR_PERMS)

    def test_phi_only_junior_and_above(self):
        for role in [Role.CLIENT, Role.ADMIN_STAFF, Role.PARALEGAL]:
            assert Permission.VIEW_PHI not in ROLE_PERMISSIONS[role]

    def test_audit_log_only_senior(self):
        for role in [Role.CLIENT, Role.ADMIN_STAFF, Role.PARALEGAL, Role.JUNIOR_PARTNER]:
            assert Permission.VIEW_AUDIT_LOG not in ROLE_PERMISSIONS[role]

class TestLogRoleChange:
    def test_calls_write_audit_event(self):
        _mw.write_audit_event.reset_mock()
        log_role_change("admin", "target", "client", "paralegal")
        _mw.write_audit_event.assert_called_once()
        args = _mw.write_audit_event.call_args
        assert args[0][0] == "role_change"
        assert args[1]["old_role"] == "client"
        assert args[1]["new_role"] == "paralegal"
